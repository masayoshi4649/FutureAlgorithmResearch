"""保存O17日中の入口除外と固定支持退出を、全変更親と原文板へ分解する。"""

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import audit143 as audit
import common143 as shared


HERE, ROOT = audit.HERE, audit.ROOT
RAW = ROOT/'work/raw_diagnosis141_20261024/raw_features'
DATA = ROOT.parent/'JP_OSE_Data/future'
JST = ZoneInfo('Asia/Tokyo')
REASONS = {32:'元手法の損切り', 70:'元手法の追尾返済', 93:'場末返済',
    14301:'自己120秒逆流による入口除外', 14312:'固定入口MA20・自己20分・120秒の逆行15秒'}


def stamp(value):
    """
    機能: 保存価格時計を日本時間へ変換する。
    引数: value(float)はepoch秒。返り値: strはISO時刻。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def finite(value):
    """
    機能: 未知の数値をJSONのnullへ変換する。
    引数: value(float)は値。返り値: float|Noneは有限値又は未知。
    """
    return float(value) if np.isfinite(value) else None


def orders_record(orders, ready):
    """
    機能: 保存注文を数量・価格・理由・原行時計付きの記録へ変換する。
    引数: orders(ndarray)、ready(dict)は一親の約定と時計。返り値: list[dict]は約定記録。
    """
    result = []
    for order in orders:
        fill, decision = int(order[0]), int(order[1])
        result.append(dict(decision_row=decision, decision_seq0=int(ready['seq'][decision]),
            decision_time=stamp(ready['time_s'][decision]), fill_row=fill,
            fill_seq0=int(ready['seq'][fill]), fill_time=stamp(ready['time_s'][fill]),
            side=int(order[3]), quantity=int(order[4]), price=float(order[5]),
            reason=int(order[6]), reason_text=REASONS.get(int(order[6]), '元手法の理由コード'),
            new=bool(order[7]), uid=int(order[8]), fee=int(order[9])))
    return result


def cash(orders):
    """
    機能: 全返済済みの一親を標準mini倍率と保存手数料で会計する。
    引数: orders(ndarray)は一親約定。返り値: floatは費用後収支。
    """
    return float(np.sum(-orders[:, 3]*orders[:, 4]*orders[:, 5]*100.-orders[:, 9]))


def raw_line(scene, symbol, seq):
    """
    機能: 原行のbyte索引とSHAを照合し、板価格・数量・時計を直接読む。
    引数: scene/symbol(str)、seq(int)は場・銘柄・0始まり原行。
    返り値: dictは原文抜粋。約定価格時計を受信時計とは扱わない。
    """
    import json
    path = DATA/symbol/scene/'book.jsonl'
    with np.load(RAW/f'{symbol}_{scene}.npz') as raw:
        offset, size = int(raw['byte_offset'][seq]), int(raw['byte_length'][seq])
        expected = raw['line_sha256'][seq].tobytes().hex()
    with path.open('rb') as stream:
        stream.seek(offset)
        line = stream.read(size)
    digest = hashlib.sha256(line).hexdigest()
    assert digest == expected
    value = json.loads(line)
    return dict(path=str(path), seq0=seq, line_no=seq+1, sha256=digest,
        fields={key:value.get(key) for key in ('CurrentPrice', 'CurrentPriceTime', 'TradingVolumeTime',
            'CurrentPriceStatus', 'Buy1', 'Sell1', 'TradingVolume')})


def evidence(scene, row, packet, data, history, fixed_ma, fixed_risk, side):
    """
    機能: 選択した判断原行の固定支持・公開中期・短期と二市場の原文を照合する。
    引数: scene(str)、row(int)、packet/data(dict)、history(ndarray)、fixed_ma/fixed_risk(float)、side(int)。
    返り値: dictは当時観測だけの判断根拠。相手の同時刻・未来行は除く。
    """
    ready, quote = data['ready'], data['quotes']
    features = data['features'][row]
    time = float(ready['time_s'][row])
    seq = int(ready['seq'][row])
    peer = packet['inputs'][scene, 'TOPIX']
    peer_row = int(np.searchsorted(peer['time_s'], time, side='left')-1)
    source = raw_line(scene, 'NK225', seq)
    assert source['fields']['Buy1']['Price'] == quote['bid'][row]
    assert source['fields']['Sell1']['Price'] == quote['ask'][row]
    own_delta120 = features[13]*features[9]
    width = max(float(ready['atr'][row]), 8.*ready['tick']) if np.isfinite(ready['atr'][row]) else 8.*ready['tick']
    return dict(row=row, seq0=seq, line_no=seq+1, time=stamp(time),
        bid=float(quote['bid'][row]), ask=float(quote['ask'][row]), mid=finite(features[10]),
        fixed_entry_ma20=finite(fixed_ma), fixed_entry_risk=fixed_risk,
        fixed_adverse_boundary=finite(fixed_ma-side*.1*fixed_risk),
        signed_fixed_distance_r=finite(side*(features[10]-fixed_ma)/fixed_risk),
        current_ma20=finite(history[row, 1]), current_public_atr=finite(ready['atr'][row]),
        own20_delta=finite(features[28]), peer20_delta=finite(features[29]),
        own120_delta_points=finite(own_delta120), own120_current_atr_r=finite(own_delta120/width),
        own120_fixed_entry_r=finite(own_delta120/fixed_risk),
        peer120_r=finite(features[21]), own_ofi30=finite(features[24]), peer_ofi30=finite(features[26]),
        own_raw=source, peer_raw=raw_line(scene, 'TOPIX', int(peer['seq'][peer_row])) if peer_row >= 0 else None,
        peer_timestamp_strictly_before=bool(peer_row >= 0 and peer['time_s'][peer_row] < time))


def main():
    """
    機能: 日中全25場の変更親を分解し、上位改善悪化と10/22維持の根拠を保存する。
    引数: なし。返り値: None。保存注文・trace・原文だけを読み、金融再生は行わない。
    """
    first, second = audit.read(HERE/'第一巡結果143.json'), audit.read(HERE/'第二巡結果143.json')
    rows = {(row['session'], row['method']):row for row in first['rows']+second['rows']}
    scenes = sorted({scene for scene, method in rows if method == 'O17' and scene.endswith('_Day')})
    packets, _, _ = shared.material()
    manifest = {item['session']:item for item in packets}
    first_cache = {item['session']:item for item in first['cache']}
    second_cache = {item['session']:item for item in second['cache']}
    all_changes, session_totals, arrays_by_scene = [], [], {}
    aggregates = {}
    for method in ('B0', 'O01', 'O12', 'O17'):
        selected = [rows[scene, method] for scene in scenes]
        gain, loss = sum(row['profit'] for row in selected), sum(row['loss'] for row in selected)
        aggregates[method] = dict(profit=gain, loss=loss, net=gain-loss, pf=gain/loss if loss else None,
            red=sum(row['net'] < 0 for row in selected), no_trade=sum(row['entries'] == 0 for row in selected))
    for scene in scenes:
        packet = shared.packet_from(manifest[scene])
        ready = packet['inputs'][scene, 'NK225']
        arrays = {}
        for cache, methods in ((first_cache, ('B0', 'O01')), (second_cache, ('O12', 'O17'))):
            ref = cache[scene]
            path = ROOT/ref['path']
            assert audit.digest(path) == ref['sha256']
            with np.load(path) as saved:
                arrays.update({method:saved[method].copy() for method in methods})
        arrays_by_scene[scene] = arrays
        with np.load(HERE/'round2/traces'/f'NK225_{scene}.npz') as saved:
            trace = saved['O17']
        for parent in np.unique(arrays['B0'][:, 2]):
            chosen = {method:order[order[:, 2] == parent] for method, order in arrays.items()}
            gate_admitted = bool(len(chosen['O01']))
            if gate_admitted:
                np.testing.assert_array_equal(chosen['B0'], chosen['O01'])
                np.testing.assert_array_equal(chosen['O12'], chosen['O17'])
            else:
                assert len(chosen['O17']) == 0
            changes = {method:cash(orders) for method, orders in chosen.items()}
            changed_gate = not np.array_equal(chosen['O01'], chosen['B0'])
            changed_exit = not np.array_equal(chosen['O17'], chosen['O01'])
            if not changed_gate and not changed_exit:
                continue
            own_trace = trace[trace[:, 1] == parent]
            all_changes.append(dict(session=scene, parent=int(parent), side=int(chosen['B0'][0, 3]),
                role='補完' if chosen['B0'][0, 8] == 999 else '主担当',
                gate_removed=changed_gate, fixed_exit_changed=changed_exit,
                net=changes, gate_effect=changes['O01']-changes['B0'],
                exit_after_gate_effect=changes['O17']-changes['O01'], total_effect=changes['O17']-changes['B0'],
                orders={method:orders_record(order, ready) for method, order in chosen.items()},
                trace=[dict(row=int(t[0]), seq0=int(ready['seq'][int(t[0])]), time=stamp(ready['time_s'][int(t[0])]),
                    kind=int(t[2]), side=int(t[3]), action=int(t[4]), reason=int(t[5]),
                    quantity=int(t[6]), gain_r=finite(t[7]), best_r=finite(t[8]), fixed_risk=finite(t[9]),
                    original_reserved=int(t[10])) for t in own_trace]))
        session_totals.append(dict(session=scene, **{method:rows[scene, method]['net'] for method in arrays},
            gate_effect=rows[scene, 'O01']['net']-rows[scene, 'B0']['net'],
            exit_after_gate_effect=rows[scene, 'O17']['net']-rows[scene, 'O01']['net'],
            total_effect=rows[scene, 'O17']['net']-rows[scene, 'B0']['net']))
    assert abs(sum(item['total_effect'] for item in all_changes)-(aggregates['O17']['net']-aggregates['B0']['net'])) < 1e-7
    changed_exit = [item for item in all_changes if item['fixed_exit_changed']]
    selected = sorted([item for item in changed_exit if item['exit_after_gate_effect'] > 0], key=lambda item:-item['exit_after_gate_effect'])[:2]
    selected += sorted([item for item in changed_exit if item['exit_after_gate_effect'] < 0], key=lambda item:item['exit_after_gate_effect'])[:2]
    protected = dict(session='2026-10-22_Day', parent=0)
    detailed = []
    for choice in selected+[protected]:
        scene, parent = choice['session'], choice['parent']
        packet = shared.packet_from(manifest[scene])
        data, _, _, history = shared.previous.prepared(packet)
        source = data['NK225']
        h = history[scene, 'NK225']
        arrays = arrays_by_scene[scene]
        orders = {method:array[array[:, 2] == parent] for method, array in arrays.items()}
        initial = int(orders['B0'][0, 1])
        side = int(orders['B0'][0, 3])
        fixed_ma = h[initial, 1]
        atr = source['ready']['atr'][initial]
        fixed_risk = max(float(atr), 8.*source['ready']['tick']) if np.isfinite(atr) else 8.*source['ready']['tick']
        with np.load(HERE/'round2/traces'/f'NK225_{scene}.npz') as archive:
            trace = archive['O17']
            trace = trace[trace[:, 1] == parent]
        decision_rows = {initial}
        decision_rows.update(int(order[1]) for group in orders.values() for order in group if order[7] == 0)
        decision_rows.update(int(t[0]) for t in trace if t[2] in (2, 3))
        if choice is protected:
            with np.load(HERE/'round1/measurement'/f'NK225_{scene}.npz') as archive:
                old_bad = archive['O03']
                orders['O03'] = old_bad[old_bad[:, 2] == parent]
            decision_rows.update(int(order[1]) for order in orders['O03'] if order[7] == 0)
        detailed.append(dict(session=scene, parent=parent, side=side,
            net={method:cash(order) for method, order in orders.items()},
            orders={method:orders_record(order, source['ready']) for method, order in orders.items()},
            fixed_ma20=finite(fixed_ma), fixed_risk=fixed_risk,
            evidence=[evidence(scene, row, packet, source, h, fixed_ma, fixed_risk, side) for row in sorted(decision_rows)]))
    effect = dict(changed_parents=len(changed_exit), nonzero_change_parents=sum(item['exit_after_gate_effect'] != 0 for item in changed_exit),
        improved_parents=sum(item['exit_after_gate_effect'] > 0 for item in changed_exit),
        worsened_parents=sum(item['exit_after_gate_effect'] < 0 for item in changed_exit),
        gross_improvement=sum(max(item['exit_after_gate_effect'], 0) for item in changed_exit),
        gross_worsening=sum(max(-item['exit_after_gate_effect'], 0) for item in changed_exit),
        net=sum(item['exit_after_gate_effect'] for item in changed_exit))
    output = dict(新金融再生=0, source=[shared.prior.ref(HERE/name) for name in ('第一巡結果143.json', '第二巡結果143.json')],
        定義='日中25場、日経mini、標準手数料込みの完結親会計。O17対O01を固定出口の条件付き差とし、入口除外と分ける。',
        aggregates=aggregates, exit_effect=effect, sessions=session_totals, all_changed_parents=all_changes, examples=detailed,
        composition_verified='O01採用親のO17注文はO12と完全一致。O01拒否親はO17でも不採用。親同士の新候補生成は変更しない。',
        limitations=['元の準備時停止幅は保存通知だけから厳密復元できない。ここに記録した幅は改修判断用の初回通知時公開ATR。',
            '全50場は既知開発。原時計は約定価格時計であり受信時計ではない。表示板から市場参加者の意図は断定しない。'])
    audit.save(HERE/'O17日中の全変更親と固定支持診断143.json', output)
    print(aggregates)
    print(effect)
    for example in detailed:
        print(example['session'], example['parent'], example['net'])
        for row in example['evidence']:
            print(row['time'], row['seq0'], row['mid'], row['fixed_entry_ma20'], row['fixed_adverse_boundary'],
                row['own20_delta'], row['peer20_delta'], row['own120_current_atr_r'])


if __name__ == '__main__':
    main()
