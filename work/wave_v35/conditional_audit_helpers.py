"""条件付き幅の会計監査に用いる、独立再生・価格線・因果性の検算。"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent / 'wave_v34'))
import accounting_audit as legacy
sys.path.insert(0, str(HERE))
import engine_conditional as engine

FIELDS = (*legacy.connection.OLD_FIELDS, *legacy.connection.EXTRA_FIELDS, 'conditional_curve', 'trail_events')
CONTROL_FIELDS = ('held_rows', 'adverse_rows', 'shortening_enabled_rows', 'contracted_atr_rows',
    'stricter_candidate_rows', 'fixed_advance_events', 'additional_advance_events',
    'conditional_advance_events', 'campaigns', 'earlier_exits', 'equal_exit_rows',
    'changed_repayments', 'exit_difference_yen', 'exit_difference_r',
    'held_seconds', 'adverse_seconds', 'shortening_enabled_seconds')
exact, close = legacy.exact, legacy.previous.close


def replay(ready: dict, entry: np.ndarray, direction: np.ndarray, source: np.ndarray,
           config: dict, spec: dict, tracking: np.ndarray | None = None) -> dict:
    """機能: 悪化条件を渡さない固定影から新設許可を毎回再生成する。

    引数: ready/config/spec (dict)、entry/direction/source (ndarray)、tracking (ndarray|None)。
    返り値: 実10配列に影と許可を加えた辞書 (dict)。
    """
    shadow = engine.run(ready, entry, config, detail=True, width_mode=0, observed_fill=spec['observed_fill'])
    allow = np.zeros(len(entry), dtype=np.bool_)
    allow[shadow['prepare_events'][:, 1].astype(np.int64)] = True
    actual = engine.run(ready, entry, config, detail=True, width_mode=spec['width_mode'],
        observed_fill=spec['observed_fill'], trail_atr=tracking, prepare_allow=allow,
        deterioration=direction, deterioration_source=source)
    actual.update(shadow=shadow, allow=allow)
    return actual


def prefix_equal(actual: dict, changed: dict, count: int) -> None:
    """機能: 影を含む全結果の既知部分と新しい短縮証拠の未来不変を確認する。

    引数: actual/changed (dict)、count (int)。返り値: なし (None)。
    """
    legacy.connection.prefix_equal(actual, changed, count)
    for left, right in ((actual, changed), (actual['shadow'], changed['shadow'])):
        exact(left['conditional_curve'][:count], right['conditional_curve'][:count], '短縮状態prefix')
        a, b = left['trail_events'], right['trail_events']
        exact(a[a[:, 0] < count], b[b[:, 0] < count], '短縮進行イベントprefix')


def future_checks(ready: dict, entry: np.ndarray, direction: np.ndarray, source: np.ndarray,
                  config: dict, spec: dict, actual: dict, tracking: np.ndarray | None = None) -> None:
    """機能: 全行の37%切断と73%以後の価格・ATR・両方向・根拠行変更を検査する。

    引数: ready/config/spec/actual (dict)、entry/direction/source (ndarray)、tracking (ndarray|None)。
    返り値: なし (None)。同時刻の後続原本行も変更し、影の許可を流用しない。
    """
    cut = max(2, int(len(entry) * .37))
    shorter = replay(legacy.previous.clipped(ready, cut), entry[:cut], direction[:cut], source[:cut],
        config, spec, None if tracking is None else tracking[:cut])
    prefix_equal(actual, shorter, cut)
    cut = max(2, int(len(entry) * .73))
    changed = dict(ready, last=ready['last'].copy(), atr=ready['atr'].copy())
    changed['last'][cut:] += np.nan_to_num(ready['atr'][cut:] * 3., nan=10 * ready['tick'])
    changed['atr'][cut:] *= 1.7
    new_entry = entry.copy(); new_entry[cut:] = np.where(new_entry[cut:] == 0, 1, -new_entry[cut:])
    new_direction = direction.copy(); new_direction[cut:] = np.where(new_direction[cut:] == 0, -1, -new_direction[cut:])
    new_source = source.copy(); new_source[cut:] = np.arange(cut, len(source))
    new_atr = (ready['atr'] if tracking is None else tracking).copy(); new_atr[cut:] = 50000.
    altered = replay(changed, new_entry, new_direction, new_source, config, spec, new_atr)
    prefix_equal(actual, altered, cut)


def reflection(ready: dict, entry: np.ndarray, direction: np.ndarray, source: np.ndarray,
               config: dict, spec: dict, actual: dict, tracking: np.ndarray | None = None) -> None:
    """機能: 価格と入口・悪化の両符号を反射し、全注文と根拠の対称性を検査する。

    引数: ready/config/spec/actual (dict)、entry/direction/source (ndarray)、tracking (ndarray|None)。
    返り値: なし (None)。
    """
    offset = 2 * np.ceil(np.max(ready['last']) / ready['tick']) * ready['tick']
    reflected = dict(ready, last=offset - ready['last'])
    mirror = replay(reflected, -entry, -direction, source, config, spec, tracking)
    exact(actual['allow'], mirror['allow'], '反射影許可')
    for left, right in ((actual, mirror), (actual['shadow'], mirror['shadow'])):
        legacy.previous.reconstruct(reflected, right, ready['symbol'])
        a, b = left['orders'], right['orders']
        close(a[:, [0, 1, 2, 4, 6, 7]], b[:, [0, 1, 2, 4, 6, 7]], '反射注文')
        close(a[:, 3], -b[:, 3], '反射注文方向'); close(a[:, 5], offset - b[:, 5], '反射注文価格')
        a, b = left['trades'], right['trades']
        close(a[:, [0, 1, 3, 6, 7, 8, 9, 10]], b[:, [0, 1, 3, 6, 7, 8, 9, 10]], '反射返済')
        close(a[:, 2], -b[:, 2], '反射元玉'); close(a[:, 4:6], offset - b[:, 4:6], '反射返済価格')
        close(left['curve'][:, [0, 1, 4]], right['curve'][:, [0, 1, 4]], '反射会計曲線')
        close(left['curve'][:, [2, 3]], right['curve'][:, [3, 2]], '反射在庫')
        exact(left['entry_preparations'], right['entry_preparations'], '反射新規起点')
        a, b = left['prepare_events'], right['prepare_events']
        exact(a[:, [0, 1, 4, 5, 6]], b[:, [0, 1, 4, 5, 6]], '反射準備')
        exact(a[:, 2], -b[:, 2], '反射準備方向'); close(a[:, 3], offset - b[:, 3], '反射準備価格')
        for field, signs, prices in (
            ('atr_curve', (0,), (4, 6, 8)),
            ('conditional_curve', (0, 1), (7, 8, 9, 10, 11)),
            ('trail_events', (2, 14), (3, 4, 5, 6))):
            transformed = right[field].copy()
            transformed[:, signs] *= -1
            transformed[:, prices] = offset - transformed[:, prices]
            np.testing.assert_allclose(left[field], transformed, atol=1e-8, rtol=0, equal_nan=True, err_msg='反射/' + field)


def line_structure(ready: dict, direction: np.ndarray, source: np.ndarray, config: dict,
                   spec: dict, actual: dict, tracking: np.ndarray | None = None) -> dict:
    """機能: 注文起点から固定候補・追加候補・単調床と全進行証拠を別計算する。

    引数: ready/config/spec/actual (dict)、direction/source (ndarray)、tracking (ndarray|None)。
    返り値: 独立行別状態・イベント (dict)。根拠が消えた後も既設床を維持する。
    """
    tracking = ready['atr'] if tracking is None else tracking
    n, mode, tick = len(tracking), spec['width_mode'], ready['tick']
    held = np.zeros(n, bool); enabled = np.zeros(n, bool); contracted = np.zeros(n, bool); strict = np.zeros(n, bool)
    event_rows = []
    openings = {int(r[2]): r for r in actual['orders'] if r[7] == 1}
    ci = {name: i for i, name in enumerate(engine.CONDITIONAL_COLUMNS)}
    ai = {name: i for i, name in enumerate(engine.ATR_COLUMNS)}
    exact(actual['conditional_curve'][:, ci['deterioration_direction']], direction.astype(float), '全行悪化方向')
    exact(actual['conditional_curve'][:, ci['deterioration_source_row']], source.astype(float), '全行悪化根拠')
    for cycle in actual['cycles']:
        campaign, begin, end = map(int, cycle[:3])
        opening = openings[campaign]
        side, anchor, a0 = int(opening[3]), float(opening[5]), float(cycle[5])
        ix = np.arange(begin, end); length = len(ix)
        held[ix] = True
        values = tracking[ix]
        last = np.maximum.accumulate(np.where(np.isfinite(values) & (values > 0), np.arange(length), -1))
        current = np.full(length, a0); use = last >= 0
        current[use] = np.maximum(values[last[use]], tick * 2)
        current_source = np.where(use, begin + last, -1)
        enabled[ix] = (mode == 1) | ((mode == 2) & (direction[ix] == -side))
        width = np.where(enabled[ix], np.minimum(a0, current), a0)
        contracted[ix] = enabled[ix] & (current < a0)
        price = ready['last'][ix]
        assert np.isfinite(price).all() and np.all(price > 0), '主監査は既知有効価格全行を対象とする'
        extreme = np.maximum.accumulate(np.maximum(price, anchor)) if side > 0 else np.minimum.accumulate(np.minimum(price, anchor))
        active = side * (extreme - anchor) >= 1.5 * a0
        fixed = (extreme - side * 3. * a0) / tick
        short = (extreme - side * 3. * width) / tick
        fixed = (np.floor(fixed + 1e-9) if side > 0 else np.ceil(fixed - 1e-9)) * tick
        short = (np.floor(short + 1e-9) if side > 0 else np.ceil(short - 1e-9)) * tick
        fixed[~active] = np.nan; short[~(active & enabled[ix])] = np.nan
        strict[ix] = active & enabled[ix] & (side * (short - fixed) > 1e-8)
        candidate = np.where(strict[ix], short, fixed)
        candidate_kind = np.where(strict[ix], 2 if mode == 1 else 3, 1)
        sentinel = -np.inf if side > 0 else np.inf
        floor = np.where(active, candidate, sentinel)
        floor = np.maximum.accumulate(floor) if side > 0 else np.minimum.accumulate(floor)
        prior = np.r_[sentinel, floor[:-1]]
        advance = active & ((floor > prior) if side > 0 else (floor < prior))
        advance_kind = np.where(advance, candidate_kind, 0)
        latest = np.maximum.accumulate(np.where(advance, np.arange(length), -1))
        latest_row = np.where(latest >= 0, begin + latest, -1)
        evidence = np.full(length, -1, np.int64); evidence_source = evidence.copy()
        valid = latest >= 0
        conditional = valid & (advance_kind[np.maximum(latest, 0)] == 3)
        evidence[conditional] = latest_row[conditional]
        evidence_source[conditional] = source[evidence[conditional]]
        prior[~np.isfinite(prior)] = np.nan; floor[~active] = np.nan
        columns = {'direction': np.full(length, side), 'shortening_enabled': enabled[ix].astype(int),
            'initial_atr': np.full(length, a0), 'current_atr': current, 'used_width_atr': width,
            'prior_level': prior, 'fixed_candidate': fixed, 'short_candidate': short,
            'selected_candidate': candidate, 'final_level': floor, 'advanced': advance.astype(int),
            'advance_kind': advance_kind, 'current_atr_source_row': current_source,
            'line_source_row': latest_row, 'line_evidence_row': evidence, 'line_evidence_source_row': evidence_source}
        for name, expected in columns.items():
            np.testing.assert_allclose(actual['conditional_curve'][ix, ci[name]], expected,
                atol=1e-8, rtol=0, equal_nan=True, err_msg='独立条件状態/' + name)
        for name, expected in {'initial_atr': np.full(length, a0), 'current_atr': current,
            'used_width_atr': width, 'extreme': extreme, 'initial_risk': np.full(length, config['initial_qty'] * a0),
            'trail_level': floor, 'trail_active': active.astype(int),
            'current_atr_source_row': current_source, 'trail_source_row': latest_row}.items():
            np.testing.assert_allclose(actual['atr_curve'][ix, ai[name]], expected,
                atol=1e-8, rtol=0, equal_nan=True, err_msg='独立ATR/' + name)
        for j in np.flatnonzero(advance):
            kind = int(advance_kind[j]); row = int(ix[j])
            event_rows.append([row, campaign, side, prior[j], fixed[j], short[j], floor[j], kind,
                a0, current[j], width[j], current_source[j], row if kind == 3 else -1,
                int(source[row]) if kind == 3 else -1, int(direction[row]) if kind == 3 else 0])
        # 次行から有効な追跡返済には直前原本行の保護線が存在する。
        for order in actual['orders'][(actual['orders'][:, 2] == campaign) & (actual['orders'][:, 6] == 2)]:
            row = int(order[0]); reference = row - 1
            assert reference >= begin and np.isfinite(actual['atr_curve'][reference, ai['trail_level']])
            assert int(order[1]) == reference
            if not spec['observed_fill'] and side * (ready['last'][reference] - actual['atr_curve'][reference, ai['trail_level']]) > 1e-8:
                close(order[5], actual['atr_curve'][reference, ai['trail_level']], '次行追跡約定')
    expected_events = np.asarray(event_rows, float).reshape(-1, len(engine.TRAIL_EVENT_COLUMNS))
    np.testing.assert_allclose(actual['trail_events'], expected_events, atol=1e-8, rtol=0, equal_nan=True)
    exact(actual['conditional_curve'][:, ci['direction']] != 0, held, '原本保有行と条件状態')
    exact(actual['conditional_curve'][:, ci['shortening_enabled']], enabled.astype(float), '全行短縮許可')
    for name, value in (('advanced', 0), ('advance_kind', 0), ('current_atr_source_row', -1),
        ('line_source_row', -1), ('line_evidence_row', -1), ('line_evidence_source_row', -1)):
        exact(actual['conditional_curve'][~held, ci[name]], np.full(int((~held).sum()), value, float), '無建玉状態/' + name)
    return dict(held=held, enabled=enabled, contracted=contracted, strict=strict, events=expected_events)


def control_metrics(ready: dict, config: dict, actual: dict, series: dict, shadow_series: dict,
                    direction: np.ndarray, structure: dict) -> tuple[dict, list]:
    """機能: 独立在庫・価格線と各玉損益から作用17指標と退出対応を再集計する。

    引数: ready/config/actual/series/shadow_series/structure (dict)、direction (ndarray)。
    返り値: 集計値と全組の対応 (tuple[dict,list])。
    """
    shadow = actual['shadow']
    for field in ('prepare_events', 'entry_preparations'):
        exact(actual[field], shadow[field], '全新規機会同一/' + field)
    exact(actual['orders'][actual['orders'][:, 7] == 1], shadow['orders'][shadow['orders'][:, 7] == 1], '全新規約定同一')
    inventory = series['long'] - series['short']
    held = inventory != 0
    exact(held, structure['held'], '注文独立在庫から保有行')
    adverse = held & (direction == -np.sign(inventory))
    duration = np.r_[np.diff(ready['time_s']), 0.]
    assert np.all(duration >= 0)
    pairs = []
    for a, b in zip(actual['cycles'], shadow['cycles'], strict=True):
        campaign, begin, finish = map(int, a[:3]); virtual_finish = int(b[2])
        assert campaign == b[0] and begin == b[1] and finish <= virtual_finish
        exact(a[[4, 5, 8]], b[[4, 5, 8]], '対応組のR/A0/方向')
        legs = actual['trades'][actual['trades'][:, 0] == campaign]
        oldlegs = shadow['trades'][shadow['trades'][:, 0] == campaign]
        assert legs[:, 3].sum() == oldlegs[:, 3].sum() == config['initial_qty']
        gain = float(np.sum(legs[:, 2] * legs[:, 3] * (legs[:, 5] - legs[:, 4])))
        previous_gain = float(np.sum(oldlegs[:, 2] * oldlegs[:, 3] * (oldlegs[:, 5] - oldlegs[:, 4])))
        close(gain, a[3], '実全玉損益'); close(previous_gain, b[3], '影全玉損益')
        risk = config['initial_qty'] * float(a[5])
        factor = config['point_value']
        pairs.append(dict(campaign=campaign, entry_row=begin, shadow_exit_row=virtual_finish,
            actual_exit_row=finish, shadow_yen=previous_gain * factor, actual_yen=gain * factor,
            difference_yen=(gain - previous_gain) * factor, difference_r=(gain - previous_gain) / risk,
            changed_repayments=legs[:, 2:].tolist() != oldlegs[:, 2:].tolist()))
    kinds = structure['events'][:, 7]
    value = dict(held_rows=int(held.sum()), adverse_rows=int(adverse.sum()),
        shortening_enabled_rows=int(structure['enabled'].sum()), contracted_atr_rows=int(structure['contracted'].sum()),
        stricter_candidate_rows=int(structure['strict'].sum()), fixed_advance_events=int(np.sum(kinds == 1)),
        additional_advance_events=int(np.sum(kinds >= 2)), conditional_advance_events=int(np.sum(kinds == 3)),
        campaigns=len(pairs), earlier_exits=sum(r['actual_exit_row'] < r['shadow_exit_row'] for r in pairs),
        equal_exit_rows=sum(r['actual_exit_row'] == r['shadow_exit_row'] for r in pairs),
        changed_repayments=sum(r['changed_repayments'] for r in pairs),
        exit_difference_yen=sum(r['difference_yen'] for r in pairs), exit_difference_r=sum(r['difference_r'] for r in pairs),
        held_seconds=float(duration[held].sum()), adverse_seconds=float(duration[adverse].sum()),
        shortening_enabled_seconds=float(duration[structure['enabled']].sum()))
    assert set(value) == set(CONTROL_FIELDS)
    close(value['exit_difference_yen'], (series['realized'][-1] - shadow_series['realized'][-1]) * config['point_value'], '全退出差と口座差')
    return value, pairs
