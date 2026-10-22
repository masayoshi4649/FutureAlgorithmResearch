"""早期改善の保存注文から、確定損失と候補選択を独立に監査する。"""

from collections import Counter, defaultdict
from datetime import datetime
import copy
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np

from audit139 import HERE, ROOT, compare, conditions, digest, ledger, read
from common139 import features129, product
import early139


JST = ZoneInfo('Asia/Tokyo')


def clock(value):
    """
    機能: 観測秒を日本時間の監査表示へ変換する。
    引数: value(float)はUNIX秒。
    返り値: strは日本時間のISO日時。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def boundaries(ready, guard):
    """
    機能: 夜間静観の時計を管理実装に依存せず求める。
    引数: ready/guard(dict)は保存入力から得た既知時計と固定条件。
    返り値: tuple[float,float]は静観開始・終了。対象外は無限大。
    """
    start = datetime.fromtimestamp(float(ready['window_start']), JST)
    if guard['event_gap'] and start.hour == 17:
        us_open = float(ready['window_end']) + 15 * 60
        return us_open - 75 * 60, us_open - 45 * 60
    return float('inf'), float('inf')


def selection(base, candidates, orders, skips, ready, guard, independent):
    """
    機能: 保存候補と実約定だけで、採用・欠落理由と当時確定済み負け数を照合する。
    引数: base/candidates/orders(ndarray)、skips(list[dict])、ready/guard/independent(dict)。
    返り値: dictは候補件数、停止理由、完成した損失親、初回時刻、静観終端の証跡。
    """
    times = ready['time_s']
    gap_start, gap_end = boundaries(ready, guard)
    queue = []
    regular_ids = set(map(int, np.unique(base[:, 2]))) if len(base) else set()
    early_ids = {int(row[2]) + 20000 for row in candidates}
    assert regular_ids.isdisjoint(early_ids), '通常親と早期候補のIDが衝突'
    for pid in np.unique(base[:, 2]) if len(base) else []:
        rows = base[base[:, 2] == pid]
        queue.append((int(rows[0, 1]), 0, int(pid), rows))
    for row in candidates:
        queue.append((int(row[1]), 1, int(row[2]) + 20000, row.reshape(1, -1)))
    queue.sort(key=lambda entry: (entry[0], entry[1]))
    actual = {int(pid): orders[orders[:, 2] == pid] for pid in np.unique(orders[:, 2])} if len(orders) else {}
    rejected = {(int(s['parent']), int(s['decision'])): s for s in skips}
    assert len(rejected) == len(skips), '見送り記録の重複'
    decisions = {(pid, decision) for decision, _, pid, _ in queue}
    assert len(decisions) == len(queue), '候補IDと判断行の重複'
    assert set(rejected) <= decisions
    assert set(actual) <= {pid for _, _, pid, _ in queue}
    accepted_early = []
    last = -1
    reasons = Counter()
    counters = Counter()
    seen = set()
    first_early = None
    for decision, early, pid, original in queue:
        key = pid, decision
        seen.add(key)
        completed = [p for p in accepted_early if p['exit'] <= decision]
        # 部分利確も含む途中現金からは数えず、実在する全返済済み親だけで計算する。
        losses = sum(p['net'] < 0 for p in completed)
        when = float(times[decision])
        bound = min(float(ready['window_end']), gap_start) if when < gap_start else float(ready['window_end'])
        reason = None
        if decision < last:
            reason = '保有中'
        elif early and guard['max_early_losses'] > 0 and losses >= guard['max_early_losses']:
            reason = '早期損失回数の上限'
        elif early and gap_start <= when < gap_end:
            reason = '米国指標時計帯の静観'
        elif early and times[int(original[0, 0])] >= bound:
            reason = '静観又は終了境界で未約定新規を取消'
        if reason is not None:
            assert pid not in actual, ('見送り対象を採用', pid, reason)
            assert key in rejected, ('見送り理由なし', pid, decision, reason)
            recorded = rejected[key]
            assert recorded['reason'] == reason, (pid, reason, recorded)
            assert recorded['kind'] == ('早期' if early else '通常')
            assert recorded['active_until'] == last
            assert recorded['early_losses'] == losses, ('未実現の負け数又は確定損失漏れ', pid, losses, recorded)
            assert recorded['gap_start'] == (gap_start if np.isfinite(gap_start) else None)
            assert recorded['gap_end'] == (gap_end if np.isfinite(gap_end) else None)
            if 'cancel_time' in recorded:
                assert recorded['cancel_time'] == bound
            reasons[('早期' if early else '通常') + '／' + reason] += 1
            counters['skipped'] += 1
            if reason == '保有中':
                pending = [p for p in accepted_early if p['entry'] <= decision < p['exit']]
                counters['unfinished_outcome_not_counted'] += len(pending)
                for p in pending:
                    rows = actual[p['id']]
                    closed = rows[(rows[:, 7] == 0) & (rows[:, 0] <= decision)]
                    counters['partial_close_not_counted'] += bool(len(closed))
            continue
        assert key not in rejected, ('採用可能な候補を理由なく見送り', pid, rejected.get(key))
        assert pid in actual, ('候補の未説明欠落', pid, decision)
        rows = actual[pid]
        assert int(rows[0, 1]) == decision
        assert rows[0, 0] == original[0, 0] and rows[0, 3] == original[0, 3] and rows[0, 5] == original[0, 5]
        if early:
            counters['accepted_early'] += 1
            p = independent['parents'][pid]
            accepted_early.append(dict(id=pid, entry=p['entry'], exit=p['exit'], net=p['net'],
                                       gross=p['gross'], fees=p['fees']))
            if first_early is None:
                first_early = clock(times[int(rows[0, 0])])
            assert not (gap_start <= when < gap_end)
            assert times[int(rows[0, 0])] < bound
            quote = ready['quotes']
            normal = np.flatnonzero(quote['quote_valid'] & np.isfinite(quote['bid']) & np.isfinite(quote['ask'])
                                    & (quote['bid'] > 0) & (quote['bid'] < quote['ask']))
            stop_decision = int(np.searchsorted(times, bound, side='left'))
            end_fill = int(normal[np.searchsorted(normal, stop_decision, side='right')])
            assert int(rows[-1, 0]) <= end_fill, ('予定時刻を超える保有', pid, bound)
            for forced in rows[rows[:, 6] == 1399]:
                assert int(forced[0]) == end_fill and int(forced[1]) == stop_decision
                counters['clock_boundary_closes'] += 1
                if np.isfinite(gap_start) and bound == gap_start:
                    counters['gap_boundary_closes'] += 1
        else:
            assert np.array_equal(rows, original), ('通常親の途中変更', pid)
            counters['accepted_regular'] += 1
        last = int(rows[-1, 0])
    assert set(rejected) <= seen
    assert counters['accepted_early'] + counters['accepted_regular'] == len(actual)
    losses = [p for p in accepted_early if p['net'] < 0]
    if guard['max_early_losses']:
        assert len(losses) <= guard['max_early_losses']
    return dict(counters=dict(counters), skipped_by_reason=dict(reasons), first_early=first_early,
                completed_early_losses=len(losses), fee_only_losses=sum(p['gross'] >= 0 for p in losses),
                early_parents=accepted_early)


def support(initials, small, entry, management):
    """
    機能: 入口の支持を元の短ATR基準のまま照合し、初回枚数を確認する。
    引数: initials(ndarray)、small/entry/management(dict)は原特徴と固定条件。
    返り値: intは確認した早期の初回数。
    """
    for row in initials:
        fill, decision, side = int(row[0]), int(row[1]), int(row[3])
        assert small['time_s'][decision] < small['candidate_until']
        assert small['time_s'][fill] < small['window_end']
        assert small['market'][decision, 11] == 1.
        assert small['market'][decision, 8] < small['time_s'][decision]
        assert small['time_s'][decision] - small['market'][decision, 8] <= 15.
        for column in (4, 6):
            assert side * small['market'][decision, column] >= entry['threshold30']
        for column in (5, 7):
            assert side * small['market'][decision, column] >= entry['threshold120']
        assert small['minute_features'][decision, 7] >= 3
        if entry['mechanism'] in ('ema38', 'ema520'):
            fast = 1 if entry['mechanism'] == 'ema38' else 3
            for features in (small['minute_features'], small['peer_minute_features']):
                assert side * (features[decision, fast] - features[decision, fast + 1]) > 0.
        assert row[4] == management['initial']
    return len(initials)


def holdings(orders, management):
    """
    機能: 追撃の実約定時に初回玉が残存し、指定上限以下であることを確認する。
    引数: orders(ndarray)は早期注文、management(dict)は管理設定。
    返り値: intは初回残存を確認した追加件数。
    """
    count = 0
    for pid in np.unique(orders[:, 2]) if len(orders) else []:
        held = {}
        for row in orders[orders[:, 2] == pid]:
            uid, qty = int(row[8]), int(row[4])
            if row[7]:
                if uid:
                    assert held.get(0, 0) > 0, ('初回消滅後に追撃', pid, uid)
                    count += 1
                held[uid] = qty
            else:
                held[uid] -= qty
            assert 0 <= sum(held.values()) <= management['target']
        assert all(value == 0 for value in held.values())
    return count


def main():
    """
    機能: 保存済み早期改善の全口座を売買再生なしで監査し、参加と停止理由を集計する。
    引数: なし。
    返り値: None。guard_financial_audit139.jsonへ独立監査を新規保存する。
    """
    result_path = HERE / 'guard_results/結果.json'
    result = read(result_path)
    planpath = ROOT / result['plan']['path']
    assert digest(planpath) == result['plan']['sha256']
    plan = read(planpath)
    for path, sha in plan['spec']['implementation'].items():
        assert digest(ROOT / path) == sha, path
    original_config = {c['id']: c for c in read(HERE / '試行計画_v2.json')['configs']}
    configs = {c['id']: c for c in plan['configs']}
    original_cache = {(c['session'], c['symbol']): c for stage in ('results', 'extra_results')
                      for c in read(HERE / stage / '結果.json')['cache']}
    bykey = {(r['session'], r['symbol'], r['method']): r for r in result['rows']}
    cache = {(c['session'], c['symbol']): c for c in result['cache']}
    skips = {(c['session'], c['symbol'], c['method']): c['skipped'] for c in result['skips']}
    packets = read(HERE / 'manifest139.json')['packets'] + read(HERE / 'manifest139_extra.json')['packets']
    counters = Counter()
    accounts = []
    for info in packets:
        scene = info['session']
        assert digest(info['path']) == info['sha256']
        packet = pickle.loads(Path(info['path']).read_bytes())
        prepared = features129.prices_for(packet, 'mid')
        markets = features129.markets(prepared)
        early = early139.prepare(packet)
        for symbol in ('NK225', 'TOPIX'):
            current = cache[(scene, symbol)]
            original = original_cache[(scene, symbol)]
            assert digest(ROOT / current['path']) == current['sha256']
            assert digest(ROOT / original['path']) == original['sha256']
            setting = product(symbol)
            ready, small = prepared[(scene, symbol)], early[symbol]
            quotes = packet['quotes'][(scene, symbol)]
            with np.load(ROOT / current['path'], allow_pickle=False) as arrays, np.load(ROOT / original['path'], allow_pickle=False) as bases:
                assert len(arrays.files) == len(configs) * 3 + 2
                for method in [name for name in arrays.files if not name.startswith('source_')]:
                    basekey = method.split('_')[0] if method.startswith(('B5_', 'C04_')) else None
                    name = method[len(basekey) + 1:] if basekey else method
                    config = configs[name]
                    guard = config['guard']
                    management = copy.deepcopy(config['management'])
                    management.update(setting)
                    management['risk_floor'] *= guard['risk_scale']
                    if guard['initial_only']:
                        management.update(initial=1, adaptive=False, target=1, increments=[], steps=[], recycle_rounds=0)
                    orders = arrays[method]
                    independent = ledger(orders, ready['time_s'], quotes['bid'], quotes['ask'], quotes['quote_valid'],
                                         setting['fee_tenths'], setting['multiplier'])
                    counters['account_fields'] += compare(bykey[(scene, symbol, method)], independent)
                    counters['accounts'] += 1
                    counters['orders'] += len(orders)
                    counters['uids'] += independent['uids']
                    base = bases[basekey] if basekey else np.empty((0, 10))
                    candidates = arrays['source_' + config['source']]
                    early_ids = np.asarray([int(row[2]) + 20000 for row in candidates], dtype=np.int64)
                    regular_ids = np.unique(base[:, 2]) if len(base) else np.empty(0)
                    assert not len(np.intersect1d(early_ids, regular_ids)), '親ID集合の衝突'
                    own_mask = np.isin(orders[:, 2], early_ids)
                    regular_mask = np.isin(orders[:, 2], regular_ids)
                    assert np.all(own_mask | regular_mask), '候補にも通常保存注文にも存在しない親'
                    own, normal = orders[own_mask], orders[regular_mask]
                    checks = conditions(own, small['time_s'], quotes['bid'], quotes['ask'], quotes['quote_valid'],
                                        small['atr'] * guard['risk_scale'], small['market'], management)
                    counters.update({'early_' + k: v for k, v in checks.items()})
                    initials = own[(own[:, 7] == 1) & (own[:, 8] == 0)]
                    assert len(initials) == bykey[(scene, symbol, method)]['early_entries']
                    counters['early_initials'] += support(initials, small, config['entry'], management)
                    counters['initial_present_for_add'] += holdings(own, management)
                    if guard['initial_only']:
                        assert not len(own[(own[:, 7] == 1) & (own[:, 8] != 0)])
                        counters['initial_only_accounts'] += 1
                    facts = selection(base, candidates, orders, skips.get((scene, symbol, method), []),
                                      small, guard, independent)
                    counters.update({'selection_' + k: v for k, v in facts['counters'].items()})
                    if basekey:
                        checks = conditions(normal, ready['time_s'], quotes['bid'], quotes['ask'], quotes['quote_valid'],
                                            ready['atr'], markets[(scene, symbol)], dict(original_config[basekey], **setting))
                        counters.update({'regular_' + k: v for k, v in checks.items()})
                    else:
                        assert not len(normal)
                    early_net = sum(p['net'] for p in facts['early_parents'])
                    accounts.append(dict(session=scene, symbol=symbol, method=method, kind=scene.split('_')[1],
                                         total_net=independent['net'], early_net=early_net, **facts))
        print(scene, '早期改善の独立監査完了', flush=True)
    groups = defaultdict(list)
    for row in accounts:
        groups[(row['symbol'], row['method'], row['kind'])].append(row)
    summary = []
    for (symbol, method, kind), rows in sorted(groups.items()):
        minutes = [datetime.fromisoformat(r['first_early']).hour * 60 + datetime.fromisoformat(r['first_early']).minute
                   + datetime.fromisoformat(r['first_early']).second / 60 for r in rows if r['first_early']]
        reasons = Counter()
        for row in rows:
            reasons.update(row['skipped_by_reason'])
        summary.append(dict(symbol=symbol, method=method, kind=kind, sessions=len(rows),
                            early_participation=len(minutes), first_minute_min=min(minutes) if minutes else None,
                            first_minute_median=float(np.median(minutes)) if minutes else None,
                            first_minute_max=max(minutes) if minutes else None,
                            total_net=sum(r['total_net'] for r in rows), early_net=sum(r['early_net'] for r in rows),
                            completed_early_losses=sum(r['completed_early_losses'] for r in rows),
                            fee_only_losses=sum(r['fee_only_losses'] for r in rows), skipped_by_reason=dict(reasons)))
    expected = len(packets) * 2 * len(configs) * 3
    assert len(accounts) == expected and counters['accounts'] == expected
    outcome = dict(status='合格', counters=dict(counters), summary=summary, accounts=accounts,
                   input_sha256=digest(result_path), plan_sha256=digest(planpath), audit_sha256=digest(Path(__file__)),
                   financial_replays=0, API=0, real_orders=0,
                   scope='保存会計・全候補の採用又は欠落理由・費用後確定損失回数・初回残・元短ATR支持・管理幅・静観終端・通常親不変。金融再生と未知場検証は行わない。')
    target = HERE / 'guard_financial_audit139.json'
    with target.open('x', encoding='utf-8') as handle:
        json.dump(outcome, handle, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(dict(status='合格', **dict(counters)), ensure_ascii=False))


if __name__ == '__main__':
    main()
