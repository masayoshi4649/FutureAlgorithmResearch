"""同じS1の実新規機会を、当時の相手確認だけで分けて採点する。"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import pickle
import socket


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
JOINT_SIGNAL = 'J1_W300_L0'
SINGLE_SIGNAL = 'S1_W300_L0'
SINGLE_ID = 'S1_W300_L0_T40_H30'


def load(path: Path) -> object:
    """機能: 保存された結果及び因果入口配列を読み取る。

    引数: path(Path)。返り値: 保存内容(object)。原本を変更しない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def deny(*args: object, **kwargs: object) -> None:
    """機能: 保存診断中のネットワーク接続を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)、例外を送出する。
    """
    raise RuntimeError('保存診断からの通信は禁止')


def digest(path: Path) -> str:
    """機能: 診断が参照した固定ファイルの内容指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def past_label(candidate: object, side: int, own: dict, joint: dict, grid: object,
               r: dict, peer: dict) -> dict:
    """機能: S1新規候補の共通判断時点までで、相手確認の有無を分類する。

    引数: candidate(ndarray)、side(int)、own/joint/r/peer(dict)、grid(ndarray)。
    返り値: 二群ラベルと過去参照証跡(dict)。返済・損益・将来値は引数に取らない。
    """
    g, decision, direction, own_row, peer_row = map(int, candidate)
    assert direction == side and own['valid'][g] and joint['valid'][g]
    assert int(own['states'][g]) == side
    assert own_row == int(own['own_source'][g]) == int(joint['own_source'][g])
    assert peer_row == int(own['peer_source'][g]) == int(joint['peer_source'][g])
    assert own_row >= 0 and peer_row >= 0 and own_row < decision
    stamp = float(grid[g])
    own_time, peer_time = float(r['time_s'][own_row]), float(peer['time_s'][peer_row])
    decision_time = float(r['time_s'][decision])
    assert own_time < stamp - 5. and peer_time < stamp - 5.
    assert stamp - 5. - own_time <= 30. and stamp - 5. - peer_time <= 30.
    assert stamp <= decision_time <= stamp + 10.
    confirmed = int(joint['states'][g]) == side
    return dict(相手確認='相手確認あり' if confirmed else '相手確認なし',
        共通判断行=g, 共通代理時計=stamp, 発注判断行=decision, 発注判断連番=int(r['seq'][decision]),
        発注代理時計=decision_time, 建玉方向=side, 自参照行=own_row,
        自参照連番=int(r['seq'][own_row]), 自参照代理時計=own_time,
        相手参照行=peer_row, 相手参照連番=int(peer['seq'][peer_row]),
        相手参照代理時計=peer_time, 単独当時状態=int(own['states'][g]), 共同当時状態=int(joint['states'][g]))


def money(records: list[dict]) -> dict:
    """機能: 固定された群の元S1決済を相殺せず集計する。

    引数: records(list[dict])。返り値: 費用後金額・平均・勝率(dict)。
    """
    count = len(records)
    p = sum(max(0., r['収支']) for r in records)
    loss = sum(max(0., -r['収支']) for r in records)
    wins, losses = sum(r['収支'] > 0 for r in records), sum(r['収支'] < 0 for r in records)
    return dict(取引数=count, 勝数=wins, 負数=losses, 同値数=count - wins - losses,
        勝率=wins / count if count else None, 利益=p, 損失=loss, 収支=p - loss,
        平均一取引収支=(p - loss) / count if count else None,
        平均利益=p / wins if wins else None, 平均負け=loss / losses if losses else None,
        金額損失割合=loss / (p + loss) if p + loss else None,
        手数料=sum(r['手数料'] for r in records),
        活動場数=len({r['セッション'] for r in records}))


def main() -> None:
    """機能: 全S1新規を過去状態で二群に分類し、同じ実決済だけで補足診断する。

    引数: なし。返り値: なし(None)。追加再生・新条件・選定変更はしない。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    fixed = load(WORK / '事前固定.json')
    result = load(WORK / 'results' / (SINGLE_ID + '.json'))
    ledger = load(WORK / 'ledgers' / (SINGLE_ID + '.pkl'))
    signals = load(WORK / 'prepared/signals_delay5.pkl')
    grids = load(WORK / 'inputs/sync_fresh30.pkl')
    meta = load(ROOT / 'work/wave_v74/inputs/refmetadata.json')
    ready = {}
    for path in meta['input_paths']['ready']:
        ready.update(load(ROOT / path))
    records = []
    for key, account in sorted(ledger.items()):
        r, own, joint = ready[key], signals[SINGLE_SIGNAL][key], signals[JOINT_SIGNAL][key]
        other_symbol = 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
        peer = ready[(key[0], other_symbol)]
        grid = grids[key[0]]['grid']
        candidates = {int(c[1]): c for c in own['candidates']}
        assert len(candidates) == len(own['candidates'])
        opens = {int(o[2]): o for o in account['orders'] if o[7] == 1}
        assert len(opens) == len(account['trades'])
        for trade in account['trades']:
            cid, fill_i, exit_i, side = (int(trade[k]) for k in (0, 1, 2, 3))
            order = opens[cid]
            decision_i = int(order[1])
            assert int(order[0]) == fill_i and decision_i < fill_i <= exit_i
            label = past_label(candidates[decision_i], side, own, joint, grid, r, peer)
            # ----------------------------------------
            # ラベル生成を終えた後にだけ、既存の将来決済を採点へ接続する。
            records.append(dict(**label, セッション=key[0], 銘柄=key[1], 取引番号=cid,
                実新規行=fill_i, 実返済行=exit_i, 実新規価格=float(trade[5]), 実返済価格=float(trade[6]),
                手数料=float(trade[7] + trade[8]), 収支=float(trade[10])))
    comparison = {}
    for period in ('前16', '後13', '全29'):
        comparison[period] = {}
        for symbol in ('TOPIX', 'NK225'):
            part = [r for r in records if r['セッション'] in fixed[period] and r['銘柄'] == symbol]
            all_s = money(part)
            saved = result['periods'][period][symbol]
            assert all_s['取引数'] == saved['trades']
            assert abs(all_s['利益'] - saved['profit']) < 1e-5 and abs(all_s['損失'] - saved['loss']) < 1e-5
            yes = money([r for r in part if r['相手確認'] == '相手確認あり'])
            no = money([r for r in part if r['相手確認'] == '相手確認なし'])
            assert yes['取引数'] + no['取引数'] == all_s['取引数']
            assert abs(yes['収支'] + no['収支'] - all_s['収支']) < 1e-5
            assert abs(yes['利益'] + no['利益'] - all_s['利益']) < 1e-5
            assert abs(yes['損失'] + no['損失'] - all_s['損失']) < 1e-5
            comparison[period][symbol] = dict(全S1=all_s, 相手確認あり=yes, 相手確認なし=no,
                平均一取引差=yes['平均一取引収支'] - no['平均一取引収支'] if yes['取引数'] and no['取引数'] else None,
                勝率差=yes['勝率'] - no['勝率'] if yes['取引数'] and no['取引数'] else None,
                金額損失割合差=yes['金額損失割合'] - no['金額損失割合'] if yes['金額損失割合'] is not None and no['金額損失割合'] is not None else None)
    output = dict(固定対象=SINGLE_ID, 相手確認対象=JOINT_SIGNAL, 追加再生数=0, 条件追加なし=True,
        選定変更なし=True, API取得数=0, 実注文数=0,
        ラベル='実S1発注判断行を元S候補の共通判断行へ照合し、その共通行でJ1状態が同方向なら確認あり。J1発火の有無は使わない。',
        因果隔離='past_labelは返済行・返済価格・収支・未来値を引数に取らない。自と相手の参照代理時計が共通判断から五秒より厳密に古いことを全件検査。分類完了後にだけ元のS1決済を接続する。',
        漏れなし='全実S1新規が一意なS候補に一致し、二群の件数・利益・損失・収支が保存済み各期間のS1会計と一致。',
        限界='同じ新規と出口での記述的な二群比較で、相手確認の純粋な因果効果又は将来の確率を証明しない。群の時刻や場面は異なる。CurrentPriceTimeの代理時計上の隔離であり、実受信順の証明ではない。',
        比較=comparison, 全明細数=len(records), 明細=records,
        入力SHA256={str(p.relative_to(ROOT)): digest(p) for p in (
            Path(__file__), WORK / '事前固定.json', WORK / 'results' / (SINGLE_ID + '.json'),
            WORK / 'ledgers' / (SINGLE_ID + '.pkl'), WORK / 'prepared/signals_delay5.pkl',
            WORK / 'inputs/sync_fresh30.pkl', ROOT / 'work/wave_v74/inputs/refmetadata.json')},
        原本入力SHA256=meta['input_SHA256'])
    target = HERE / '同じ新規機会での相手確認診断.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(dict(全照合合格=True, 全S1取引数=len(records), 実行条件追加=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
