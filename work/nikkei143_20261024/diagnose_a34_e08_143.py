"""旧A34と新E08の保存約定を読み、入口・停止・保有を比較する。新しい金融再生を行わない。"""

from pathlib import Path
import hashlib
import json
import pickle
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT/'work/aggressive140_20261024'
sys.path.insert(0, str(OLD))
import active140_v2 as feature_source


def read(path):
    """
    機能: UTF-8の保存JSONを読む。
    引数: path(Path)は対象資料。
    返り値: dict/listは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def stamp(value):
    """
    機能: epoch秒を日本時間へ変換する。
    引数: value(float)は価格時計。
    返り値: strは時差付き日時。
    """
    return datetime.fromtimestamp(float(value), ZoneInfo('Asia/Tokyo')).isoformat()


def parents(orders, ready, quotes, method, trace=None, features=None):
    """
    機能: 保存注文の親を完結単位へ分解し、元価格経路の順行・逆行と停止条件を付ける。
    引数: orders(ndarray)、ready/quotes(dict)、method(str)、trace/features(ndarray|None)。
    返り値: list[dict]は再生を伴わない完結親の診断。
    """
    result = []
    for parent in np.unique(orders[:, 2]):
        rows = orders[orders[:, 2] == parent]
        first, last = rows[0], rows[-1]
        fill, source, final = int(first[0]), int(first[1]), int(last[0])
        side = int(first[3])
        mark = quotes['bid' if side > 0 else 'ask'][fill:final+1]
        gains = side*(mark-first[5])
        gains = gains[np.isfinite(gains)]
        value = dict(method=method, session=ready['session'], parent=int(parent), side=side,
            source_row=source, source_seq=int(ready['seq'][source]), entry_row=fill, entry_seq=int(ready['seq'][fill]),
            exit_row=final, exit_seq=int(ready['seq'][final]), decision=stamp(ready['time_s'][source]),
            entry=stamp(ready['time_s'][fill]), exit=stamp(ready['time_s'][final]),
            entry_price=float(first[5]), exit_price=float(last[5]),
            first_quantity=int(first[4]), entry_quantity=int(rows[rows[:, 7] == 1, 4].sum()),
            net=float((-rows[:, 3]*rows[:, 4]*rows[:, 5]*100.-rows[:, 9]).sum()),
            fees=float(rows[:, 9].sum()), duration_minutes=float((ready['time_s'][final]-ready['time_s'][fill])/60.),
            mfe_liquidation=float(max(gains)), mae_liquidation=float(min(gains)),
            reasons=rows[rows[:, 7] == 0, 6].astype(int).tolist(), orders=rows.tolist())
        if trace is not None:
            selected = trace[(trace[:, 0] == source) & (trace[:, 1] == 1)]
            assert len(selected) == 1
            item = selected[0]
            value.update(fixed_edge=float(item[7]), armed_extreme=float(item[8]), decision_r=float(item[9]),
                         fixed_stop=float(item[10]), fixed_center=float(item[11]),
                         initial_stop_distance=float(side*(first[5]-item[10])),
                         effective_r=max(8.*ready['tick'], float(side*(first[5]-item[10]))))
        if features is not None:
            a = features[source]
            value.update(published_high=float(a[0]), published_low=float(a[1]), published_width=float(a[0]-a[1]),
                efficiency=float(a[2]), old_r_at_source=float(a[9]), self30_r=float(a[12]), self120_r=float(a[13]),
                peer30_r=float(a[20]), peer120_r=float(a[21]), source_bid=float(quotes['bid'][source]), source_ask=float(quotes['ask'][source]))
            if method == 'A34':
                value['old_r_note'] = '判断原行の公開Rであり、準備開始時に固定した実停止Rとは必ずしも同じではない。'
        result.append(value)
    return result


def main():
    """
    機能: 共通23夜の保存注文を比較し、悪化最大2夜の原行証跡と機構差を記録する。
    引数: なし。
    返り値: None。新しい注文は一切生成しない。
    """
    old = read(OLD/'round2_known/結果140.json')
    new = read(HERE/'第一巡結果143.json')
    plan = read(OLD/'第二巡計画140.json')
    manifest = read(OLD/'known_manifest140.json')
    oldrows = {r['session']: r for r in old['rows'] if r['symbol'] == 'NK225' and r['method'] == 'A34' and r['session'].endswith('Night')}
    newrows = {r['session']: r for r in new['rows'] if r['method'] == 'E08' and r['session'].endswith('Night')}
    cases = sorted(oldrows, key=lambda scene: newrows[scene]['net']-oldrows[scene]['net'])[:2]
    provenance = {}
    for source, expected in plan['spec']['implementation'].items():
        if source.endswith(('round2_140.py', 'active140_v2.py')):
            sha = hashlib.sha256((ROOT/source).read_bytes()).hexdigest()
            assert sha == expected
            provenance[source] = sha
    assert plan['configs']['active'][33]['id'] == 'A34'
    packet_paths = {r['session']: ROOT/r['path'] for r in manifest['packets']}
    allparents, differences, rawproof = [], [], []
    for scene in oldrows:
        packet = pickle.loads(packet_paths[scene].read_bytes())
        key = scene, 'NK225'
        ready, quotes = packet['inputs'][key], packet['quotes'][key]
        old_path = OLD/'round2_known/measurement'/f'NK225_{scene}.npz'
        old_ref = next(item for item in old['cache'] if item['session'] == scene and item['symbol'] == 'NK225')
        assert hashlib.sha256(old_path.read_bytes()).hexdigest() == old_ref['sha256']
        with np.load(old_path) as f:
            a = f['A34'].copy()
        with np.load(HERE/'round1/measurement'/f'NK225_{scene}.npz') as f:
            b = f['E08'].copy()
        with np.load(HERE/'round1/traces'/f'NK225_{scene}.npz') as f:
            trace = f['E08'].copy()
        features = feature_source.prepare(packet, 40)['NK225'] if scene in cases else None
        if features is not None:
            for column in ('bid', 'ask', 'quote_valid'):
                np.testing.assert_array_equal(features['quotes'][column], quotes[column])
        oldp = parents(a, ready, quotes, 'A34', features=features['features'] if features else None)
        newp = parents(b, ready, quotes, 'E08', trace=trace, features=features['features'] if features else None)
        assert np.isclose(sum(p['net'] for p in oldp), oldrows[scene]['net'])
        assert np.isclose(sum(p['net'] for p in newp), newrows[scene]['net'])
        allparents.extend(oldp+newp)
        differences.append(dict(session=scene, old_net=oldrows[scene]['net'], new_net=newrows[scene]['net'],
                                difference=newrows[scene]['net']-oldrows[scene]['net'], old_parents=len(oldp), new_parents=len(newp)))
        if scene in cases:
            rawfile = ROOT/'work/raw_diagnosis141_20261024/raw_features'/f'NK225_{scene}.npz'
            with np.load(rawfile) as raw:
                source_path = Path(str(raw['source_path']))
                for method, pp in [('A34', oldp), ('E08', newp)]:
                    for parent in pp:
                        for purpose, seq in [('新規判断', parent['source_seq']), ('返済約定', parent['exit_seq'])]:
                            offset, length = int(raw['byte_offset'][seq]), int(raw['byte_length'][seq])
                            with source_path.open('rb') as stream:
                                stream.seek(offset)
                                line = stream.read(length)
                            parsed = json.loads(line)
                            rawproof.append(dict(session=scene, method=method, parent=parent['parent'], purpose=purpose, seq=seq,
                                offset=offset, length=length, line_sha256=hashlib.sha256(line).hexdigest(),
                                CurrentPrice=parsed.get('CurrentPrice'), CurrentPriceTime=parsed.get('CurrentPriceTime'),
                                BidPrice=parsed.get('BidPrice'), AskPrice=parsed.get('AskPrice'),
                                Buy1=parsed.get('Buy1'), Sell1=parsed.get('Sell1')))
    summary = []
    for method in ('A34', 'E08'):
        pp = [p for p in allparents if p['method'] == method]
        profit, loss = sum(max(p['net'], 0) for p in pp), sum(max(-p['net'], 0) for p in pp)
        summary.append(dict(method=method, nights=23, parents=len(pp), profit=profit, loss=loss, net=profit-loss,
            pf=profit/loss if loss else None, mean_duration_minutes=float(np.mean([p['duration_minutes'] for p in pp])),
            mean_first_quantity=float(np.mean([p['first_quantity'] for p in pp])),
            partial_close_parents=sum(1435 in p['reasons'] for p in pp),
            stop_parents=sum(1436 in p['reasons'] or 32 in p['reasons'] for p in pp),
            mean_entry_quantity=float(np.mean([p['entry_quantity'] for p in pp]))))
    partial_parents = []
    leg_net = {'初回玉': 0., '追加玉': 0.}
    for parent in [p for p in allparents if p['method'] == 'E08']:
        orders = np.asarray(parent['orders'])
        for uid in np.unique(orders[:, 8]):
            part = orders[orders[:, 8] == uid]
            leg_net['追加玉' if uid else '初回玉'] += float((-part[:, 3]*part[:, 4]*part[:, 5]*100.-part[:, 9]).sum())
        partial = orders[(orders[:, 7] == 0) & (orders[:, 6] == 1435)]
        if len(partial):
            after = orders[(orders[:, 7] == 1) & (orders[:, 8] > 0) & (orders[:, 0] > partial[0, 0])]
            partial_parents.append(dict(session=parent['session'], parent=parent['parent'], net=parent['net'],
                post_partial_adds=len(after), first_add_row_gap=float(after[0, 0]-partial[0, 0]) if len(after) else None))
    result = dict(新金融再生=0, 対象='共通の既知23夜・NK225mini・完結親手数料後', 旧生成経路='round2_140.run→active140_v2.replay(config A34)→round2_known/measurement:A34',
        旧生成実装SHA=provenance, 旧設定=plan['configs']['active'][33], summary=summary,
        sessions=sorted(differences, key=lambda row: row['difference']), cases=cases, parents=allparents,
        初回追加玉損益=leg_net, 部分返済後追撃=partial_parents, rawproof=rawproof)
    # 観測できない短期差はゼロにせずnullへ直し、標準JSONとして保存する。
    result = json.loads(json.dumps(result, ensure_ascii=False), parse_constant=lambda _: None)
    (HERE/'E08と旧A34の保存注文診断143.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    for scene in cases:
        print(scene)
        for p in allparents:
            if p['session'] == scene:
                print({k: p.get(k) for k in ('method', 'parent', 'side', 'entry', 'exit', 'entry_price', 'exit_price', 'net', 'first_quantity', 'entry_quantity', 'initial_stop_distance', 'fixed_r', 'mfe_liquidation', 'mae_liquidation', 'reasons', 'self30_r', 'peer30_r')})


if __name__ == '__main__':
    main()
