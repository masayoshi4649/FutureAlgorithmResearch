"""新金融結果を読まず、赤字順位・部分返済分解・反証の保存境界を合成検査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import reader


HERE = Path(__file__).resolve().parent


def endpoint(row: int, bid: float) -> dict:
    """
    機能: 実相場と無関係な一呼値幅のBBOを作る。
    引数: row(int)、bid(float)。
    返り値: dict はseq・価格時計・両数量付きの合成点。
    """
    return dict(raw_seq=row+100, price_time_s=1000+row, bid=bid, ask=bid+.5, bid_qty=20, ask_qty=10)


def fixture() -> tuple[dict, list[dict], dict, dict]:
    """
    機能: 半分が黒字・残りが赤字で、中値合計は正の負け親を作る。
    引数: なし。
    返り値: tuple は親・実脚・公開写真・親分解の独立手計算。
    """
    entry, first, last = endpoint(1, 100), endpoint(3, 101.5), endpoint(4, 99)
    parent = dict(parent=3, uid=7, side=1, quantity=10, publication_row=0, entry_row=1, exit_row=4,
        entry_price=100.5, net_yen=-3336, gross_yen=-2500, fee_yen=836,
        peak_gross_ticks=2, worst_gross_ticks=-3, peak_liquidation_net_yen=9164, worst_liquidation_net_yen=-15836)
    legs = [dict(parent=3, uid=7, side=1, q=5, entry_row=1, exit_row=3, entry_price=100.5,
                 exit_price=101.5, gross_yen=5000, entry_fee_allocated=209, exit_fee=209, net_yen=4582),
            dict(parent=3, uid=7, side=1, q=5, entry_row=1, exit_row=4, entry_price=100.5,
                 exit_price=99, gross_yen=-7500, entry_fee_allocated=209, exit_fee=209, net_yen=-7918)]
    snapshot = dict(parent=3, uid=7, 公開=endpoint(0, 100), 新規=entry, 最終返済=last)
    breakdown = dict(parent=3, uid=7, 中値差粗損益=2500, 気配差負担=5000, 手数料=836, 収支=-3336,
        legs=[dict(q=5, side=1, entry_row=1, exit_row=3, 新規=entry, 返済=first),
              dict(q=5, side=1, entry_row=1, exit_row=4, 新規=entry, 返済=last)])
    return parent, legs, snapshot, breakdown


def reject(function: object) -> None:
    """
    機能: 不一致をAssertionErrorで拒否することを確かめる。
    引数: function(Callable) は引数なしの検査。
    返り値: None。
    """
    try:
        function()
    except AssertionError:
        return
    raise AssertionError('不一致が受理された')


def main() -> None:
    """
    機能: 合成だけで主候補赤字3場選定・部分返済分解と原seq非混同を検査する。
    引数: なし。
    返り値: None。金融・台帳・原入力・event本文は読まない。
    """
    target = HERE / '赤字選定と部分返済気配分解のSOURCE_ONLY人工.json'
    assert not target.exists()
    p, legs, snap, decomposition = fixture()
    obs = reader.parent_observation(p, legs, snap, decomposition, 'TOPIX')
    assert obs['親全体の中値と気配差分解']['中値差粗損益'] == 2500
    assert obs['親全体の中値と気配差分解']['気配差負担'] == 5000
    assert obs['損失の観測分類']['中値非負だが気配差後は負'] is True
    assert obs['公開から新規の不利値幅'] == 0 and obs['入口拡幅'] is False
    assert obs['粗利ピーク2T以上'] is True and obs['極値は事後のみ'] is True
    for key in ('中値差粗損益', '気配差負担', '収支', '手数料'):
        broken = deepcopy(decomposition)
        broken[key] += 1
        reject(lambda broken=broken: reader.parent_observation(p, legs, snap, broken, 'TOPIX'))
    broken = deepcopy(decomposition)
    broken['legs'][0]['返済']['bid'] += .5
    reject(lambda: reader.parent_observation(p, legs, snap, broken, 'TOPIX'))
    other = deepcopy(snap)
    other['新規']['ask'] += .5
    reject(lambda: reader.parent_observation(p, legs, other, decomposition, 'TOPIX'))
    for value in (True, False, float('nan'), float('inf'), None):
        reject(lambda value=value: reader.number(value))
    rows, parents = [], []
    for symbol in ('TOPIX', 'NK225'):
        for i in range(33):
            # IDは順位検査用の仮の場名で、実日付や実損益ではない。
            session = f'合成場{i:02d}_Day'
            net = [-100, -500, -500, 0, 300][i%5] if symbol == 'TOPIX' else 100
            rows.append(dict(case=reader.MAIN, symbol=symbol, session=session, 収支=net))
            parents.append(dict(case=reader.MAIN, symbol=symbol, session=session,
                parent=i, uid=i, net_yen=net))
    selected = reader.rank_cases(dict(rows=rows, parents=parents))
    assert len(selected) == 3
    assert [case['session'] for case in selected] == ['合成場01_Day', '合成場02_Day', '合成場06_Day']
    assert all(case['symbol'] == 'TOPIX' for case in selected)
    reflected = deepcopy(decomposition)
    reflected['legs'].append(deepcopy(reflected['legs'][0]))
    reject(lambda: reader.parent_observation(p, legs, snap, reflected, 'TOPIX'))
    md = reader.explanation(dict(対象=[dict(symbol='TOPIX', session='合成場',
        場の金額分解=decomposition, 負け親=[obs])]))
    assert '未検証' in md and '実現利益ではない' in md and '親を削除' in md
    proof = dict(全合格=True, 算術境界=14, 拒否境界=12, 赤字なし商品を場で補完=False,
        source_SHA256={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ('reader.py','artificial_diagnosis.py')},
        範囲='合成の順位とBBO/脚/中値気配差の恒等式だけ。金融結果・台帳・原入力未読。',
        金融結果=0, 新台帳=0, 原NPZ=0, eventNPZ=0, 旧金融=0, API=0)
    reader.write(target, proof)
    print(json.dumps(dict(全合格=True, SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
