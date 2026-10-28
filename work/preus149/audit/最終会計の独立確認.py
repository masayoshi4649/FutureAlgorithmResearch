"""保存済みの約定と最終表だけを読み、会計・対照・境界を再確認する。"""

import json
from pathlib import Path
from statistics import mean, median

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent


def path_signature(case, phase=None):
    """約定の意味だけを抽出し、条件間で比較可能にする。

    引数: case(dict)は保存条件、phase(str|None)は対象区間。
    返り値: list[tuple]は時刻・価格・担当・売買・数量の列。
    """
    return [(e['signal']['owner'], e['signal']['action'], e['signal']['side'],
             e['fill']['Quantity'], e['fill']['Price'], e['signal']['time'],
             e['fill']['Time'], e['decision_index'], e['fill_index'])
            for e in case['events'] or [] if phase is None or e['phase'] == phase]


def account(case, scene):
    """約定順に所有玉を追跡し、現金差と実現損益を別々に集計する。

    引数: case(dict)は約定列、scene(dict)は場の時刻。
    返り値: dictは独立集計と監査件数。
    """
    lots, parents, parent_sides = {}, {}, {}
    cash = realized = positive = negative = 0
    largest = entries = checked_features = 0
    prior_fill = 0
    for e in case['events'] or []:
        sig, fill = e['signal'], e['fill']
        side, qty, price = sig['side'], fill['Quantity'], fill['Price']
        assert side in (-1, 1) and qty > 0 and qty == sig['quantity']
        assert e['fill_index'] > e['decision_index'] == sig['source_index']
        assert fill['Time'] >= sig['time'] and fill['Time'] >= prior_fill
        assert fill['Fee'] == 0
        prior_fill = fill['Time']
        cash -= side * qty * price * 100
        gain = 0
        if sig['action'] == 'new':
            key = fill['HoldID']
            assert key not in lots
            parent = (e['phase'], sig['owner'], sig['campaign'])
            lots[key] = [side, qty, price, parent]
            parents.setdefault(parent, 0)
            parent_sides[parent] = side
            entries += 1
            if case['config'].get('reset'):
                if e['phase'] == '前半':
                    assert sig['time'] < scene['us_open'] - case['config']['close_before_minutes'] * 60
                else:
                    assert sig['time'] >= scene['us_open'] + case['config']['restart_wait_minutes'] * 60
        else:
            total = 0
            for target in fill['Closed']:
                lot = lots[target['id']]
                q = target['quantity']
                assert lot[0] == -side and 0 < q <= lot[1]
                value = lot[0] * q * (price - lot[2]) * 100
                gain += value
                parents[lot[3]] += value
                lot[1] -= q
                total += q
            assert total == qty
        assert gain == e['gross']
        realized += gain
        positive += max(gain, 0)
        negative += max(-gain, 0)
        for s in (-1, 1):
            held = sum(lot[1] for lot in lots.values() if lot[0] == s)
            assert held <= 10
            largest = max(largest, held)
        obs = sig.get('evidence', {}).get('observation')
        if obs:
            assert obs['Time'] == sig['time'] and obs['Index'] == sig['source_index']
            for name in ('main_available', 'peer_available', 'atr_available'):
                assert obs['E01'][name] <= obs['Time']
            for name in ('DayMarket', 'LastMarket', 'MidMarket'):
                if obs[name]['Known']:
                    assert obs[name]['PeerTime'] < obs['Time']
            checked_features += 1
    assert realized == case['Gross'] and positive == case['Profit'] and negative == case['Loss']
    assert largest == case['max_per_side'] and case['cancelled_new'] == 0
    if not scene['partial']:
        assert all(lot[1] == 0 for lot in lots.values())
        assert not case['positions'] and not case['final_pending']
        assert case['Unrealized'] == 0 and cash == realized
        if case['config'].get('reset'):
            assert 0 < case['pre_flat_at'] <= case['post_started']
            assert case['post_started'] >= scene['us_open']
    return dict(net=realized, profit=sum(max(x, 0) for x in parents.values()),
                loss=sum(max(-x, 0) for x in parents.values()), entries=entries,
                checked_events=len(case['events'] or []), checked_feature_events=checked_features,
                max_per_side=largest,
                buy_net=sum(x for p, x in parents.items() if parent_sides[p] == 1),
                sell_net=sum(x for p, x in parents.items() if parent_sides[p] == -1))


def main():
    """完成した20条件表と保存約定を読み、独立確認の結果を残す。

    引数: なし。
    返り値: None。売買判断・価格再生は行わず、JSONの確認書だけ保存する。
    """
    report = json.loads((STUDY / 'report149.json').read_text('utf-8'))
    assert len(report['methods']) == 20
    methods = {m['id']: m for m in report['methods']}
    records, summaries = {}, {}
    for folder in ('results_go', 'results_round2'):
        for file in sorted((STUDY / folder).glob('*_Night.json')):
            saved = json.loads(file.read_text('utf-8'))
            scene = saved['scene']
            for case in saved['cases']:
                key = (scene['session'], case['config']['id'])
                records[key] = (scene, case, account(case, scene))
    events = features = 0
    for ident, method in methods.items():
        assert len(method['rows']) == 25
        rows = []
        for row in method['rows']:
            scene, case, checked = records[(row['session'], ident)]
            for key in ('net', 'profit', 'loss', 'entries', 'max_per_side'):
                assert row[key] == checked[key], (ident, row['session'], key)
            assert row['pre']['net'] + row['post']['net'] == checked['net']
            rows.append(checked)
            events += checked['checked_events']
            features += checked['checked_feature_events']
        sums = method['summary']
        for key in ('net', 'profit', 'loss', 'entries'):
            assert sums[key] == sum(r[key] for r in rows)
        red = [-r['net'] for r in rows if r['net'] < 0]
        assert sums['losses'] == len(red)
        assert sums['maxloss'] == max(red, default=0)
        assert sums['avgloss'] == (mean(red) if red else 0)
        assert sums['medianloss'] == (median(red) if red else 0)
        winners = sorted((r['net'] for r in rows if r['net'] > 0), reverse=True)
        assert sums['ex3'] == sums['net'] - sum(winners[:3])
        summaries[ident] = dict(buy_net=sum(r['buy_net'] for r in rows),
                               sell_net=sum(r['sell_net'] for r in rows))
    # ----------------------------------------
    # 売買状態を初期化した後半が前半条件に依存しないことを保存約定列で照合する。
    contrasts = []
    for row in methods['S02']['rows']:
        scene, s02, _ = records[(row['session'], 'S02')]
        _, s04, _ = records[(row['session'], 'S04')]
        assert s02['post_started'] == s04['post_started']
        assert path_signature(s02, '後半') == path_signature(s04, '後半')
        for ident in ('R02', 'S01', 'S02', 'S03'):
            _, case, _ = records[(row['session'], ident)]
            assert path_signature(case, '前半') == path_signature(s02, '前半')
        contrasts.append(row['session'])
    output = dict(financial_replays=0, methods=20, complete_nights=25,
                  method_nights=500, event_rows=events, evidence_rows=features,
                  partial_method_nights=sum(scene['partial'] for scene, _, _ in records.values()),
                  s02_s04_post_exact_nights=len(contrasts),
                  r02_s01_s02_s03_pre_exact_nights=len(contrasts),
                  side_results=summaries, all_checks_passed=True)
    (HERE / '最終会計の独立確認.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(output, ensure_ascii=True))


if __name__ == '__main__':
    main()
