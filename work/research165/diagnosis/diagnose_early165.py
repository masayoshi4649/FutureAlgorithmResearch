"""前20夜の保存会計だけを分解する。売買生成・候補変更は行わない。"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BASE = ROOT / 'work/research165'
JST = dt.timezone(dt.timedelta(hours=9))


def read(path: Path) -> dict:
    """機能: UTF-8のJSONを読む。引数: path(Path)。返り値: dict。"""
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """機能: 内容指紋を得る。引数: path(Path)。返り値: str。"""
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def clock(value: float) -> str:
    """機能: 価格時計を日本時間へ表示する。引数: value(float)。返り値: str。"""
    return dt.datetime.fromtimestamp(value, JST).isoformat()


def quantiles(values: list[float]) -> dict:
    """機能: 線形補間分位点を得る。引数: values(list[float])。返り値: dict。"""
    a = sorted(values)
    if not a:
        return {'n': 0}
    ans = {'n': len(a), 'mean': sum(a) / len(a), 'min': a[0], 'max': a[-1]}
    for q in (.25, .5, .75, .9):
        z = (len(a) - 1) * q
        lo = int(z)
        hi = min(len(a) - 1, lo + 1)
        ans[f'q{int(q*100)}'] = a[lo] * (hi-z) + a[hi] * (z-lo) if lo != hi else a[lo]
    return ans


def summary(rows: list[dict]) -> dict:
    """機能: 完結玉の実績と固定約定の恒等分解を集計する。引数: rows(list[dict])。返り値: dict。"""
    n = len(rows)
    qty = sum(x['quantity'] for x in rows)
    return {
        'lots': n, 'quantity_micro': qty,
        'net_yen': sum(x['gross'] for x in rows),
        'profit_yen': sum(max(0, x['gross']) for x in rows),
        'loss_yen': -sum(min(0, x['gross']) for x in rows),
        'mid_move_yen': sum(x['mid_move_yen'] for x in rows),
        'spread_cost_yen': sum(x['spread_cost_yen'] for x in rows),
        'positive': sum(x['gross'] > 0 for x in rows),
        'negative': sum(x['gross'] < 0 for x in rows),
        'zero': sum(x['gross'] == 0 for x in rows),
        'mid_positive': sum(x['mid_move_yen'] > 0 for x in rows),
        'mid_nonnegative_but_actual_negative': sum(x['mid_move_yen'] >= 0 and x['gross'] < 0 for x in rows),
        'never_positive_losses': sum(x['best'] <= 0 and x['gross'] < 0 for x in rows),
        'never_positive_loss_yen': -sum(min(0, x['gross']) for x in rows if x['best'] <= 0),
        'positive_then_negative': sum(x['best'] > 0 and x['gross'] < 0 for x in rows),
        'mean_spread_cost_yen_per_lot': sum(x['spread_cost_yen'] for x in rows) / n if n else None,
        'quantity_weighted_roundtrip_spread_pt': sum(x['spread_cost_yen'] for x in rows) / (qty * 10) if qty else None,
        'mean_net_pt_per_micro': sum(x['gross'] for x in rows) / (qty * 10) if qty else None,
        'holding_price_clock_seconds': quantiles([x['hold_seconds'] for x in rows]),
        'holding_raw_rows': quantiles([x['exit_index']-x['entry_index'] for x in rows]),
        'entry_exit_same_price_clock': sum(x['hold_seconds'] == 0 for x in rows),
        'decision_to_fill_price_clock_seconds': quantiles([x['entry_time']-x['decision_time'] for x in rows]),
    }


def independent_rows(saved: dict, case: dict) -> list[dict]:
    """機能: 独立玉を新規と全返済へ結び、中値と気配差へ分解する。引数: saved(dict),case(dict)。返り値: list[dict]。"""
    ledger = case['actual']
    new = {e['HoldID']: e for e in ledger['Events'] if e.get('HoldID')}
    closes = collections.defaultdict(list)
    active = collections.Counter()
    seen = collections.Counter()
    modes = {}
    waves = set()
    for e in ledger['Events']:
        if e.get('HoldID'):
            lot = ledger['Lots'][e['HoldID']]
            state = case['states'][lot['Parent']]
            sid, wave = state['StateID'], state['WaveID']
            assert wave not in waves, ('同一押戻り重複', saved['scene']['session'], wave)
            waves.add(wave)
            modes[lot['ID']] = 'first_state_entry' if not seen[sid] else ('overlap_same_state' if active[sid] else 'reentry_after_same_state_flat')
            seen[sid] += 1
            active[sid] += lot['Quantity']
        for piece in e.get('Pieces') or []:
            closes[piece['ID']].append((e, piece))
            sid = case['states'][ledger['Lots'][piece['ID']]['Parent']]['StateID']
            active[sid] -= piece['Quantity']
            assert active[sid] >= 0
    initial_trace = {t['Parent']: t for t in case['trigger_trace'] if t['Action'] == '独立新規' and t['Accepted'] > 0}
    result = []
    for key, lot in ledger['Lots'].items():
        assert lot['Remaining'] == 0 and len(closes[key]) == 1
        entry = new[key]
        exit_event, piece = closes[key][0]
        q = piece['Quantity']
        emid = (entry['Bid'] + entry['Ask']) / 2
        xmid = (exit_event['Bid'] + exit_event['Ask']) / 2
        midmove = lot['Side'] * (xmid - emid) * q * 10
        spread = ((entry['Ask'] - entry['Bid']) + (exit_event['Ask'] - exit_event['Bid'])) / 2 * q * 10
        assert abs(midmove - spread - piece['Gross']) < 1e-8
        assert piece['Gross'] == lot['Gross'] and q == lot['Quantity']
        trace = initial_trace[lot['Parent']]
        hold = trace['State']['Buy' if lot['Side'] > 0 else 'Sell']
        state = case['states'][lot['Parent']]
        result.append({
            'session': saved['scene']['session'], 'method': case['config']['id'],
            'lot_id': key, 'parent': lot['Parent'], 'state_id': state['StateID'], 'wave_id': state['WaveID'],
            'participation': modes[key], 'side': lot['Side'], 'quantity': q,
            'decision_index': entry['Order']['DecisionIndex'], 'decision_time': entry['Order']['DecisionTime'],
            'entry_index': entry['FillIndex'], 'entry_time': entry['FillTime'], 'entry_price': entry['Price'],
            'entry_bid': entry['Bid'], 'entry_ask': entry['Ask'],
            'exit_decision_index': exit_event['Order']['DecisionIndex'], 'exit_decision_time': exit_event['Order']['DecisionTime'],
            'exit_index': exit_event['FillIndex'], 'exit_time': exit_event['FillTime'], 'exit_price': exit_event['Price'],
            'exit_bid': exit_event['Bid'], 'exit_ask': exit_event['Ask'], 'exit_reason': exit_event['Order']['Reason'],
            'gross': lot['Gross'], 'best': lot['Best'], 'worst': lot['Worst'],
            'mid_move_yen': midmove, 'spread_cost_yen': spread,
            'hold_seconds': exit_event['FillTime'] - entry['FillTime'],
            'state_age_clock_seconds': entry['Order']['DecisionTime'] - hold['Time'],
            'state_age_price_events': trace['State']['PriceEvent'] - hold['Event'],
            'state_index': hold['Index'], 'pressure_index': hold['PressureIndex'],
            'entry_from_band_pt': lot['Side'] * (emid - (hold['Bid'] + hold['Ask']) / 2),
        })
    assert sum(x['gross'] for x in result) == ledger['Realized']
    return result


def source_parent_diffs(saved: dict, candidate: dict) -> list[dict]:
    """機能: 元親と04親をSourceID単位で対応する。引数: saved(dict),candidate(dict)。返り値: list[dict]。"""
    old = saved['control']['actual']
    new = candidate['actual']
    oldgroups, newgroups = collections.defaultdict(list), collections.defaultdict(list)
    for lot in old['Lots'].values(): oldgroups[lot['Parent']].append(lot)
    for lot in new['Lots'].values(): newgroups[lot['Parent']].append(lot)
    rows = []
    for parent in sorted(set(oldgroups) | set(newgroups)):
        o, n = oldgroups[parent], newgroups[parent]
        oldids = {x['SourceID']: x for x in o}
        newids = {x['SourceID']: x for x in n}
        assert set(newids) <= set(oldids)
        same = []
        for sid in newids:
            a, b = oldids[sid], newids[sid]
            same.append({'source_id': sid, 'old_gross': a['Gross'], 'new_gross': b['Gross'],
                         'entry_equal': all(a[k] == b[k] for k in ('Quantity','Entry','At','EntryIndex','Side'))})
            assert same[-1]['entry_equal']
        missing = [v for k, v in oldids.items() if k not in newids]
        delta = sum(x['Gross'] for x in n) - sum(x['Gross'] for x in o)
        rows.append({'session': saved['scene']['session'], 'parent': parent,
                     'old_net': sum(x['Gross'] for x in o), 'new_net': sum(x['Gross'] for x in n), 'difference': delta,
                     'removed_lots': missing, 'common_lots': same,
                     'removed_net': sum(x['Gross'] for x in missing),
                     'common_difference': sum(x['new_gross'] - x['old_gross'] for x in same)})
        assert delta == -rows[-1]['removed_net'] + rows[-1]['common_difference']
    return rows


def half_audit(saved: dict) -> dict:
    """機能: 12の半量化を経済会計と数量断面に分けて確認する。引数: saved(dict)。返り値: dict。"""
    cs = {x['config']['id'][-2:]: x for x in saved['cases']}
    full, half = cs['11']['actual'], cs['12']['actual']
    virtual = cs['12']['virtual_control']
    assert full['Realized'] == virtual['Realized'] == half['Realized'] * 2
    assert len(full['Events']) == len(half['Events']) == len(virtual['Events'])
    for a, b, v in zip(full['Events'], half['Events'], virtual['Events']):
        assert all(a[k] == b[k] == v[k] for k in ('FillIndex', 'FillTime', 'Price', 'Bid', 'Ask'))
        assert a['Order']['Quantity'] == b['Order']['Quantity'] * 2 == v['Order']['Quantity']
        assert a['Gross'] == b['Gross'] * 2 == v['Gross']
        assert len(a.get('Pieces') or []) == len(b.get('Pieces') or [])
    discrepancies = []
    for name in ('MinimumAt','PeakAt','DDFrom','DDTo','MinimumRealizedAt','MinimumUnrealizedAt'):
        a, b, v = full['Risk'][name], half['Risk'][name], virtual['Risk'][name]
        assert all(a[k] == v[k] == b[k]*2 for k in ('Realized','Unrealized','Equity','MidEquity','Long','Short'))
        if sum((b['Lots'] or {}).values()) != b['Long'] + b['Short']:
            discrepancies.append({'mark': name, 'time': b['Time'], 'index': b['Index'],
                                  'saved_quantities': b['Lots'], 'expected_half_quantities': {k:q//2 for k,q in (v['Lots'] or {}).items()},
                                  'saved_long': b['Long'], 'saved_short': b['Short'], 'unrealized': b['Unrealized']})
    return {'session': saved['scene']['session'], 'economics_half_equal': True,
            'snapshot_quantity_discrepancies': discrepancies}


def main() -> None:
    """機能: 前20夜だけの事後分解を保存する。引数: なし。返り値: None。"""
    proofpath = BASE / 'results/train_validation/再生完了165_train_validation.json'
    proof = read(proofpath)
    assert proof['completed'] is True and proof['returncode'] == 0 and proof['sources_unchanged'] is True
    assert proof['sessions'] == 20 and proof['cases'] == 280 and proof['stage']['stage'] == 'train_validation'
    allrows, differences, halves, proofs, totals = [], [], [], [], []
    for item in proof['results']:
        path = ROOT / item['path']
        assert path.parent.name == 'train_validation'
        digest = sha(path)
        assert digest == item['sha256']
        saved = read(path)
        assert saved['scene']['split'] in ('train','validation') and saved['scene']['confirmation'] is False
        cases = {x['config']['id'][-2:]: x for x in saved['cases']}
        for code in ('10','11','12','13','14'):
            rows = independent_rows(saved, cases[code])
            allrows.extend(rows)
            totals.append({'session': saved['scene']['session'], 'method': cases[code]['config']['id'], **summary(rows)})
        differences.extend(source_parent_diffs(saved, cases['04']))
        halves.append(half_audit(saved))
        proofs.append({'path': item['path'], 'sha256': digest})
        print(saved['scene']['session'], '保存配賦照合済み', flush=True)
    reports = {}
    for code in ('10','11','12','13','14'):
        mid = 'NK225_U165_' + code
        rows = [x for x in allrows if x['method'] == mid]
        groups = collections.defaultdict(list)
        for row in rows: groups[(row['session'], row['state_id'])].append(row)
        repeats = sorted([{'session': key[0], 'state_id': key[1], **summary(rs), 'parents': [r['parent'] for r in rs]} for key, rs in groups.items()], key=lambda x: (x['net_yen'], -x['lots']))
        reports[mid] = {**summary(rows),
            'exit_reasons': {reason: summary([r for r in rows if r['exit_reason'] == reason]) for reason in sorted({r['exit_reason'] for r in rows})},
            'participation': {mode: summary([r for r in rows if r['participation'] == mode]) for mode in sorted({r['participation'] for r in rows})},
            'state_count': len(groups), 'states_with_repeated_entry': sum(len(v)>1 for v in groups.values()),
            'entries_per_state': quantiles([len(v) for v in groups.values()]),
            'state_age_clock_seconds': quantiles([r['state_age_clock_seconds'] for r in rows]),
            'state_age_price_events': quantiles([r['state_age_price_events'] for r in rows]),
            'entry_from_band_pt': quantiles([r['entry_from_band_pt'] for r in rows]),
            'worst_states': repeats[:10]}
    payload = {
        'scope': '前20夜のみ。後7夜の結果は未読。新金融再生なし。',
        'definitions': {'holding_seconds':'CurrentPriceTimeの差。受信時計上の保持秒数ではない。',
            'decomposition':'実成立注文・数量・時計を固定した事後恒等式。中値で実行可能な手法成績ではない。',
            'state_reentry':'StateID=同じ確認価格帯、WaveID=その帯内の別の押戻り。WaveIDの同一二重採用なし。',
            'quantity':'micro。1micro×1円=10円、20micro=mini2枚相当。'},
        'proof': {'path': str(proofpath.relative_to(ROOT)), 'sha256': sha(proofpath)}, 'result_sources': proofs,
        'methods': reports, 'sessions': totals,
        'u04_parents': differences,
        'u04_effect': {'parent_count': len(differences), 'improved': sum(x['difference']>0 for x in differences), 'worsened': sum(x['difference']<0 for x in differences),
            'difference': sum(x['difference'] for x in differences), 'removed_lots': sum(len(x['removed_lots']) for x in differences),
            'best_parent': max(differences,key=lambda x:x['difference']), 'worst_parent': min(differences,key=lambda x:x['difference'])},
        'half_snapshot_audit': halves,
        'trade_rows': allrows,
    }
    dest = OUT / '前20夜の独立入口と追撃抑制の分解165.json'
    dest.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'output':str(dest),'methods':{k:{z:v[z] for z in ('lots','net_yen','mid_move_yen','spread_cost_yen')} for k,v in reports.items()},'u04':payload['u04_effect']},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
