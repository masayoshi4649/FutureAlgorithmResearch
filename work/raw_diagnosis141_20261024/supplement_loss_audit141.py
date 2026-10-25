"""保存済み補完注文の悪化を、入口・出口・主担当干渉へ分けて監査する。"""

import hashlib
import json
import pickle
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT/'work/aggressive140_20261024'
sys.path.insert(0, str(OLD))
import run140_v2 as prior
from loss_raw141 import snapshot, clean
from supplemental141_v2 import original_direction


def stamp(value):
    """
    機能: 保存された価格時計を日本時間で表示する。
    引数: value(float)はepoch秒。
    返り値: strは価格時計。独立した受信時計の意味ではない。
    """
    return datetime.fromtimestamp(float(value), ZoneInfo('Asia/Tokyo')).isoformat()


def cash(orders):
    """
    機能: 全返済済み保存注文の円収支を独立に再集計する。
    引数: orders(ndarray[m,10])は日経miniの保存約定。
    返り値: floatは手数料込み収支。新たな売買条件の再生はしない。
    """
    return float(np.sum(-orders[:, 3]*orders[:, 4]*orders[:, 5]*100.-orders[:, 9]))


def evidence(row, ready, quote, history, market, raw, peer_ready, peer_raw):
    """
    機能: 判断原行の公開特徴と原文板を接続する。
    引数: row(int)、ready/quote/raw/peer_ready/peer_raw(dict)、history/market(ndarray)は保存資料。
    返り値: dictは過去だけで観測可能だった特徴と原文行識別。
    """
    t, seq = ready['time_s'][row], int(ready['seq'][row])
    h = history[row]
    mid = (quote['bid'][row]+quote['ask'][row])*.5
    own = snapshot(raw, seq)
    # ----------------------------------------
    # 原文行のSHAと気配を直接確認。相手は価格時計が厳密に過去の行だけ。
    source = Path(str(raw['source_path']))
    assert not bool(raw['offset_is_uncompressed'])
    with source.open('rb') as stream:
        stream.seek(int(raw['byte_offset'][seq]))
        line = stream.read(int(raw['byte_length'][seq]))
    assert hashlib.sha256(line).digest() == raw['line_sha256'][seq].tobytes()
    obj = json.loads(line)
    assert obj['Buy1']['Price'] == quote['bid'][row]
    assert obj['Sell1']['Price'] == quote['ask'][row]
    peer_row = int(np.searchsorted(peer_ready['time_s'], t, side='left')-1)
    other = None
    if peer_row >= 0:
        peer_seq = int(peer_ready['seq'][peer_row])
        other = snapshot(peer_raw, peer_seq)
    return dict(row=row, seq=seq, line_no=seq+1, time=stamp(t),
        bid=float(quote['bid'][row]), ask=float(quote['ask'][row]),
        opening=float(h[8]), own_from_open=float(mid-h[8]), peer_from_open=float(h[13]),
        own5=float(h[6]), peer5=float(h[10]), own20=float(h[7]), peer20=float(h[11]),
        original_side=int(original_direction(h, mid)),
        own30r=float(market[row, 4]), own120r=float(market[row, 5]),
        peer30r=float(market[row, 6]), peer120r=float(market[row, 7]),
        market_valid=bool(market[row, 11] == 1.), raw=own, peer_raw=other)


def parent_record(rows, ready, quote, history, market, raw, peer_ready, peer_raw):
    """
    機能: 保存親の全注文、保有中の最大順行・逆行と判断原行をまとめる。
    引数: rows(ndarray[m,10])と市場辞書・特徴配列は一親の保存証跡。
    返り値: dictは親診断。未来の極値は事後診断としてのみ記載する。
    """
    first = rows[0]
    begin, end = int(first[0]), int(rows[-1, 0])
    side, px = int(first[3]), float(first[5])
    good = quote['quote_valid'][begin:end+1]
    indexes = np.flatnonzero(good)+begin
    liquidate = quote['bid'] if side > 0 else quote['ask']
    move = side*(liquidate[indexes]-px)
    peak, trough = indexes[int(np.argmax(move))], indexes[int(np.argmin(move))]
    orders = []
    for o in rows:
        i, d = int(o[0]), int(o[1])
        orders.append(dict(side=int(o[3]), quantity=int(o[4]), price=float(o[5]),
            reason=int(o[6]), new=bool(o[7]), fee=float(o[9]),
            fill_row=i, fill_seq=int(ready['seq'][i]), fill_time=stamp(ready['time_s'][i]),
            decision=evidence(d, ready, quote, history, market, raw, peer_ready, peer_raw)))
    return dict(parent=int(first[2]), role='補完' if int(first[8]) == 999 else '主担当',
        side=side, quantity=int(first[4]), net=cash(rows), orders=orders,
        maximum_favorable_points=float(move.max()), favorable_time=stamp(ready['time_s'][peak]),
        maximum_adverse_points=float(move.min()), adverse_time=stamp(ready['time_s'][trough]))


def main():
    """
    機能: Q03悪化上位3場を具体原行へ接続し、旧夜間全場の会計差も分解する。
    引数: なし。
    返り値: None。保存会計の監査だけを新規保存し、金融再生・原資料更新はしない。
    """
    saved = prior.read(HERE/'結果141.json')
    rows = [r for r in saved['rows'] if r['symbol'] == 'NK225' and r['kind'] == 'Night'
            and r['session'] < '2026-10-22_Night']
    lookup = {(r['session'], r['method']): r for r in rows}
    scenes = sorted({r['session'] for r in rows})
    ranked = sorted(scenes, key=lambda s: lookup[s, 'Q03']['net']-lookup[s, 'B5']['net'])
    manifest = prior.read(OLD/'known_manifest140.json')['packets']
    aggregate = []
    records = []
    for scene in scenes:
        path = HERE/'results/measurement'/f'NK225_{scene}.npz'
        with np.load(path) as z:
            methods = {k: z[k].copy() for k in ('B5', 'Q01', 'Q02', 'Q03')}
        attribution = dict(session=scene)
        for method, orders in methods.items():
            core, extra = orders[orders[:, 8] != 999], orders[orders[:, 8] == 999]
            assert abs(cash(orders)-lookup[scene, method]['net']) < 1.e-6
            attribution[method] = dict(net=cash(orders), core=cash(core), supplement=cash(extra),
                core_exact_same_as_B5=bool(np.array_equal(core, methods['B5'][methods['B5'][:, 8] != 999])))
        attribution['changes'] = dict(wait_and_recheck=attribution['Q01']['net']-attribution['B5']['net'],
            prefer20=attribution['Q02']['net']-attribution['Q01']['net'],
            short_exit=attribution['Q03']['net']-attribution['Q02']['net'],
            total=attribution['Q03']['net']-attribution['B5']['net'])
        aggregate.append(attribution)
        if scene not in ranked[:3]:
            continue
        item = next(p for p in manifest if p['session'] == scene)
        packet = pickle.loads((ROOT/item['path']).read_bytes())
        inputs, markets, histories, _ = prior.common.features129.build(packet, 'mid', 0.)
        key, peer = (scene, 'NK225'), (scene, 'TOPIX')
        rawsets = {}
        for symbol in ('NK225', 'TOPIX'):
            with np.load(HERE/'raw_features'/f'{symbol}_{scene}.npz') as z:
                rawsets[symbol] = {k: z[k] for k in z.files}
        record = dict(session=scene, attribution=attribution, methods={})
        for method, orders in methods.items():
            parents = []
            for parent in np.unique(orders[:, 2]):
                selected = orders[orders[:, 2] == parent]
                parents.append(parent_record(selected, inputs[key], packet['quotes'][key], histories[key],
                    markets[key], rawsets['NK225'], inputs[peer], rawsets['TOPIX']))
            notes = [] if method == 'B5' else prior.read(HERE/'results/notes'/f'NK225_{scene}_{method}.json')
            for note in notes:
                note['価格時計'] = stamp(inputs[key]['time_s'][note['原行']])
            record['methods'][method] = dict(parents=parents, notes=notes)
        records.append(record)
        print(scene, attribution['changes'], flush=True)
    out = dict(financial_replays=0, API=0, real_orders=0,
        basis='保存注文の因果特徴・原文行と費用後会計を照合。事後の極値は原因診断のみ。',
        limitations=['旧47場のうち夜間は23場。追加3場を含め全場既知の開発標本。',
            'Q01-B5には待機・再判断・建値・新R・同じ旧数量式の変更が一緒に含まれる。独立要因効果と断定しない。',
            '旧補完で既に見送られB5にない主担当は復元していない。',
            '時刻は価格時計であり共通受信時計ではない。板数量変化を新規・取消・約定へ分解できない。'],
        ranking=ranked, aggregate=aggregate, records=records)
    destination = HERE/'補完悪化上位3場の原板監査141.json'
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(clean(out), stream, ensure_ascii=False, indent=2, allow_nan=False)
    print('旧夜間合計', {k:sum(r['changes'][k] for r in aggregate) for k in aggregate[0]['changes']}, flush=True)
    print('主担当差異場', [r['session'] for r in aggregate if not r['Q03']['core_exact_same_as_B5']], flush=True)


if __name__ == '__main__':
    main()
