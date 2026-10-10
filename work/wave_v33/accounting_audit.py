"""保有ATR比較96条件の全玉会計・ピーク悪化・因果性を独立に検査する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
from pathlib import Path
import pickle
import socket
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / 'wave_v23'
V30 = HERE.parent / 'wave_v30'
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import input_audit
import engine_dynamic_atr as ENGINE
import design
sys.path.insert(0, str(V30))
import all_accounting_audit as previous
from context_structure_audit import read, save, digest, original_hashes, reject_network

MANAGERS = previous.managers
INPUTS, ENTRIES, FIXED = {}, {}, {}
PARTICIPATION = ('long_unit_minutes', 'short_unit_minutes', 'opening_orders')
SESSION_FIELDS = set(('id symbol session gross_profit_yen gross_loss_yen net_yen profit_units loss_units zero_units '
    'cycles cycle_wins cycle_losses cycle_profit_yen cycle_loss_yen net_r drawdown_yen min_equity_yen max_equity_yen '
    'max_long max_short closed_units reversals longest_losing_streak maximum_trade_profit maximum_trade_loss '
    'two_largest_cycle_profits long_unit_minutes short_unit_minutes opening_orders first_entry_min retracements').split())
PERIOD_FIELDS = set(('gross_profit_yen gross_loss_yen net_yen profit_units loss_units zero_units cycles cycle_wins '
    'cycle_losses cycle_profit_yen cycle_loss_yen net_r closed_units money_ratio cycle_ratio win_sessions active_sessions '
    'worst_session drawdown_yen best_removed_net best_removed_pf best_trade_removed_net max_long max_short '
    'longest_losing_streak session_count average_unit_payoff long_unit_minutes short_unit_minutes opening_orders retracement').split())


def freeze() -> dict:
    """機能: 全96の会計範囲と損益未選別の検査内容を固定する。

    引数: なし。返り値: 監査規則 (dict)。既存固定と異なる再実行を拒否する。
    """
    source = read(HERE / '探索条件の固定.json')
    paths = [Path(__file__), HERE / 'engine_dynamic_atr.py', HERE / 'input_audit.py',
             HERE / 'input_causality_before_pnl.json', V30 / 'all_accounting_audit.py',
             HERE.parent / 'wave_v29/selected_accounting_audit.py', V30 / 'context_structure_audit.py']
    value = dict(固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        対象条件ID=[s['id'] for s in source['conditions']], 対象条件数=96, 対象入力数=26,
        対象='全12入口×固定/更新×4変形。成績で選別せず全2496区間。',
        原本行数='元26入力last長の実合計×96を検算する。',
        会計='全注文から現金・両在庫・元建値・部分返済・全行時価/DD・上限・次行約定・場末完結を再構成。',
        比較='保存session全必須項目、全13/後半7全必須項目、orders/trades/cycles/stats全配列・全curveSHA・返済台帳SHA。',
        返却='注文から独立生成した当組実現+含み曲線の最大値（0を含む）−最終組損益。初回枚数×1A0からRを再計算。全組と正peak組を区別し全期間集計。',
        追跡='各組A0/初回risk、保有後既知At保持、幅使用ATR、追跡始動1.5A0、極値と3ATR候補、既存床を緩めない条件を全行で再計算。',
        未来検査='全2496区間で37%切断、73%以後価格/入口ATR/追跡用At/入口方向変更、上下反射。',
        基準='固定A0のV000/L300全24は旧同入口D273の26session数値と返済台帳SHAに一致。全12のL300とV000は旧5結果完全一致。',
        制限='旧実装/原本不変。新候補選抜・追加API・現在保存物不使用。指定波は別監査。',
        参照SHA256={p.relative_to(ROOT).as_posix(): digest(p) for p in paths},
        探索固定SHA256=digest(HERE / '探索条件の固定.json'))
    path = HERE / 'accounting_fixed.json'
    if path.exists():
        old = read(path)
        assert {k: v for k, v in old.items() if k != '固定日時'} == {k: v for k, v in value.items() if k != '固定日時'}
        return old
    save(path, value)
    return value


def exact(left: np.ndarray, right: np.ndarray, label: str) -> None:
    """機能: 全配列の形状・値とNaN位置を厳密比較する。

    引数: left/right (ndarray)、label (str)。返り値: なし (None)。
    """
    assert left.shape == right.shape, (label, left.shape, right.shape)
    np.testing.assert_array_equal(left, right, err_msg=label)


def compare(actual: object, expected: object, label: str) -> None:
    """機能: 入れ子の保存値を欠落なく比較し、金額丸め誤差だけを許容する。

    引数: actual/expected (object)、label (str)。返り値: なし (None)。
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), label
        for key in expected:
            compare(actual[key], expected[key], label + '/' + str(key))
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), label
        for i, item in enumerate(expected):
            compare(actual[i], item, label + '/' + str(i))
    elif expected is None or actual is None:
        assert actual is expected, label
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert np.isfinite(expected) and np.isfinite(actual), label
        previous.close(actual, expected, label)
    else:
        assert actual == expected, label


def participation(ready: dict, result: dict) -> dict:
    """機能: 原本行の約定後在庫×次観測までの分数から参加量を独立計算する。

    引数: ready/result (dict)。返り値: 枚数分・新規回数・初回分 (dict)。
    """
    inventory = result['curve'][:, 2:4]
    elapsed = np.diff(ready['time_s']) / 60.
    assert np.all(elapsed >= 0)
    units = np.sum(inventory[:-1] * elapsed[:, None], axis=0)
    opens = int(np.count_nonzero(np.any(np.diff(inventory, axis=0, prepend=np.zeros((1, 2))) > 0, axis=1)))
    held = np.flatnonzero(inventory.sum(axis=1) > 0)
    assert opens == int(np.sum(result['orders'][:, 7] == 1))
    return dict(long_unit_minutes=float(units[0]), short_unit_minutes=float(units[1]), opening_orders=opens,
                first_entry_min=None if not len(held) else float((ready['time_s'][held[0]] - ready['start']) / 60.))


def retracements(ready: dict, result: dict, series: dict, config: dict) -> list[dict]:
    """機能: 注文会計だけから各組ピーク・最終収支・悪化・初回Rを再構成する。

    引数: ready/result/series/config (dict)。返り値: 全組の独立計測値 (list[dict])。
    """
    output = []
    for cycle in result['cycles']:
        number, begin, end = map(int, cycle[:3])
        base = float(series['realized'][begin - 1]) if begin else 0.
        curve = series['equity'][begin:end + 1] - base
        peak = max(0., float(np.max(curve)))
        final = float(series['realized'][end] - base)
        previous.close(final, cycle[3], '組の最終実現損益')
        previous.close(curve[-1], final, '組の全返済曲線')
        risk = config['initial_qty'] * config['stop_atr'] * cycle[5]
        previous.close(risk, cycle[4], '固定A0からRを計算')
        loss = max(0., peak - final)
        factor = previous.MULT[ready['symbol']]
        output.append(dict(campaign=number, entry_row=begin, exit_row=end,
                           peak_yen=peak * factor, final_yen=final * factor, retracement_yen=loss * factor,
                           risk_yen=risk * factor, retracement_r=loss / risk, positive_peak=peak > 1e-8,
                           holding_minutes=float((ready['time_s'][end] - ready['time_s'][begin]) / 60.)))
    return output


def retracement_totals(rows: list[dict]) -> dict:
    """機能: 全組と利益経験組を分けてピーク悪化を独立に集計する。

    引数: rows (list[dict])。返り値: 件数・合計・平均・中央値 (dict)。
    """
    output = {}
    for name, selected in (('all', rows), ('positive_peak', [r for r in rows if r['positive_peak']])):
        values = sorted(r['retracement_r'] for r in selected)
        n = len(values)
        median = None if n == 0 else values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2.
        output[name] = dict(cycles=n, sum_yen=sum(r['retracement_yen'] for r in selected),
                            sum_r=sum(values), mean_r=None if not n else sum(values) / n, median_r=median)
    output['holding_minutes'] = sum(r['holding_minutes'] for r in rows)
    return output


def atr_structure(ready: dict, tracking: np.ndarray, config: dict, spec: dict, result: dict) -> None:
    """機能: 全保有行でA0固定・At保持・追跡候補の単調保護を独立計算する。

    引数: ready/config/spec/result (dict)、tracking (ndarray)。返り値: なし (None)。
    """
    names = {name: i for i, name in enumerate(ENGINE.ATR_COLUMNS)}
    curve = result['atr_curve']
    assert curve.shape == (len(tracking), len(names))
    opens = {int(r[2]): r for r in result['orders'] if r[7] == 1}
    held_mask = np.zeros(len(tracking), bool)
    for cycle in result['cycles']:
        campaign, begin, end = map(int, cycle[:3])
        entry = opens[campaign]
        side, anchor, a0 = int(entry[3]), float(entry[5]), float(cycle[5])
        held_mask[begin:end] = True
        section = curve[begin:end]
        previous.close(section[:, names['initial_atr']], a0, '全保有行A0固定')
        previous.close(section[:, names['initial_risk']], config['initial_qty'] * a0, '全保有行初期R固定')
        # ----------------------------------------
        # 注文器の逐次ループとは別に、累積参照行・累積極値から全行をベクトル再構成する。
        local = tracking[begin:end]
        valid = np.isfinite(local) & (local > 0)
        latest = np.maximum.accumulate(np.where(valid, np.arange(len(local)), -1))
        has_atr = latest >= 0
        current = np.full(len(local), a0)
        current[has_atr] = np.maximum(local[latest[has_atr]], 2 * ready['tick'])
        current_source = np.where(has_atr, begin + latest, -1)
        width_atr = current if spec['dynamic_trail_atr'] else np.full(len(local), a0)
        prices = ready['last'][begin:end]
        extreme = np.maximum.accumulate(np.maximum(prices, anchor)) if side == 1 else np.minimum.accumulate(np.minimum(prices, anchor))
        active = side * (extreme - anchor) >= 1.5 * a0
        raw = (extreme - side * 3. * width_atr) / ready['tick']
        planned = (np.floor(raw + 1e-9) if side == 1 else np.ceil(raw - 1e-9)) * ready['tick']
        sentinel = -np.inf if side == 1 else np.inf
        candidates = np.where(active, planned, sentinel)
        floor = np.maximum.accumulate(candidates) if side == 1 else np.minimum.accumulate(candidates)
        former = np.r_[sentinel, floor[:-1]]
        advances = active & ((floor > former) if side == 1 else (floor < former))
        floor_source = np.maximum.accumulate(np.where(advances, np.arange(begin, end), -1))
        floor[~active] = np.nan
        expected = np.column_stack([np.full(len(local), side), current, width_atr, extreme, current_source, floor_source])
        columns = [names[n] for n in ('direction', 'current_atr', 'used_width_atr', 'extreme', 'current_atr_source_row', 'trail_source_row')]
        previous.close(section[:, columns], expected, '独立追跡状態')
        exact(section[:, names['trail_active']], active.astype(float), '独立追跡始動')
        np.testing.assert_allclose(section[:, names['trail_level']], floor, atol=1e-8, rtol=0, equal_nan=True)
    exact(curve[:, names['direction']] != 0, held_mask, '建玉とATR保有状態')


def replay(ready: dict, state: np.ndarray, tracking: np.ndarray, config: dict, spec: dict) -> dict:
    """機能: 追跡専用Atを入口ATRとは別引数で詳細再生する。

    引数: ready/config/spec (dict)、state/tracking (ndarray)。返り値: 全詳細結果 (dict)。
    """
    return ENGINE.run(ready, state, config, detail=True, width_mode=spec['dynamic_trail_atr'],
                      observed_fill=spec['observed_fill'], trail_atr=tracking)


def prefix_equal(actual: dict, changed: dict, count: int) -> None:
    """機能: 注文会計と追跡ATR状態の接頭辞を検査する。

    引数: actual/changed (dict)、count (int)。返り値: なし (None)。
    """
    previous.prefix_equal(actual, changed, count)
    exact(actual['atr_curve'][:count], changed['atr_curve'][:count], '追跡ATR状態の未来不変')


def future_checks(ready: dict, state: np.ndarray, tracking: np.ndarray, config: dict, spec: dict, actual: dict) -> None:
    """機能: 37%切断と73%以後の価格/入口ATR/At/方向変更で過去不変を確認する。

    引数: ready/config/spec/actual (dict)、state/tracking (ndarray)。返り値: なし (None)。
    """
    cut = max(2, int(len(state) * .37))
    truncated = replay(previous.clipped(ready, cut), state[:cut], tracking[:cut], config, spec)
    prefix_equal(actual, truncated, cut)
    cut = max(2, int(len(state) * .73))
    changed = dict(ready, last=ready['last'].copy(), atr=ready['atr'].copy())
    changed['last'][cut:] += np.nan_to_num(ready['atr'][cut:] * 3, nan=10 * ready['tick'])
    changed['atr'][cut:] *= 1.7
    direction = state.copy(); direction[cut:] = np.where(direction[cut:] == 0, 1, -direction[cut:])
    altered_atr = tracking.copy(); altered_atr[cut:] = 50000.
    altered = replay(changed, direction, altered_atr, config, spec)
    prefix_equal(actual, altered, cut)


def reflection(ready: dict, state: np.ndarray, tracking: np.ndarray, config: dict, spec: dict, actual: dict) -> None:
    """機能: ATR値は同じまま価格と入口を上下反射し全約定・会計の対称性を検査する。

    引数: ready/config/spec/actual (dict)、state/tracking (ndarray)。返り値: なし (None)。
    """
    offset = 2 * np.ceil(np.max(ready['last']) / ready['tick']) * ready['tick']
    mirror_ready = dict(ready, last=offset - ready['last'])
    mirrored = replay(mirror_ready, -state, tracking, config, spec)
    previous.reconstruct(mirror_ready, mirrored, ready['symbol'])
    left, right = actual['orders'], mirrored['orders']
    previous.close(left[:, [0, 1, 2, 4, 6, 7]], right[:, [0, 1, 2, 4, 6, 7]], '反射注文の行・数量・理由')
    previous.close(left[:, 3], -right[:, 3], '反射注文方向')
    previous.close(left[:, 5], offset - right[:, 5], '反射約定値')
    left, right = actual['trades'], mirrored['trades']
    previous.close(left[:, [0, 1, 3, 6, 7, 8, 9, 10]], right[:, [0, 1, 3, 6, 7, 8, 9, 10]], '反射全返済')
    previous.close(left[:, 2], -right[:, 2], '反射元玉方向')
    previous.close(left[:, 4:6], offset - right[:, 4:6], '反射建値と返済値')
    previous.close(actual['curve'][:, [0, 1, 4]], mirrored['curve'][:, [0, 1, 4]], '反射損益とDD')
    previous.close(actual['curve'][:, [2, 3]], mirrored['curve'][:, [3, 2]], '反射両在庫')
    for name in ('initial_atr', 'current_atr', 'used_width_atr', 'initial_risk', 'current_atr_source_row', 'trail_source_row'):
        index = ENGINE.ATR_COLUMNS.index(name)
        exact(actual['atr_curve'][:, index], mirrored['atr_curve'][:, index], '反射ATRと参照元/' + name)


def initialize() -> None:
    """機能: 通信を遮断し固定入力と既存12入口を子処理へ読む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, ENTRIES, FIXED
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    urllib.request.OpenerDirector.open = reject_network
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    ENTRIES = input_audit.load_entries(INPUTS)
    FIXED = read(HERE / '探索条件の固定.json')
    assert len(INPUTS) == 26 and len(FIXED['conditions']) == 96


def evaluate(spec: dict) -> dict:
    """機能: 一条件26区間の全保存会計・ATR状態・返却・未来検査を行う。

    引数: spec (dict)。返り値: 独立監査結果 (dict)。
    """
    identifier = spec['id']
    paths = [HERE / name / (identifier + suffix) for name, suffix in
             (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('summaries', '.json'))]
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    saved_rows, saved_ledgers, summary = read(paths[0]), read(paths[1]), read(paths[2])
    target = {(r['session'], r['symbol']): r for r in saved_rows}
    ledgers = {(r['session'], r['symbol']): r for r in saved_ledgers}
    assert len(saved_rows) == len(target) == len(saved_ledgers) == len(ledgers) == 26
    assert set(target) == set(ledgers) == set(INPUTS)
    assert summary['id'] == identifier and summary['spec'] == spec
    assert summary['探索固定SHA256'] == digest(HERE / '探索条件の固定.json')
    fixed_old = spec['atr_mode'] == 'initial' and spec['variant_id'] in ('V000', 'L300')
    old_id = spec['signal_id'] + '__L000__V000'
    old_rows = {}
    if fixed_old:
        old_rows = {(r['session'], r['symbol']): r for p in read(HERE.parent / 'wave_v31/sessions' / (spec['signal_id'] + '.json.gz'))
                    if p['id'] == old_id for r in p['rows']}
    assert summary['旧固定再現'] is fixed_old
    rows, series, hasher = [], {}, hashlib.sha256()
    for key, ready in INPUTS.items():
        entry, _ = input_audit.make_entry(ready, ENTRIES[spec['signal_id']][key], spec['entry_delay_seconds'])
        tracking, _ = input_audit.make_tracking_atr(ready, spec['trail_atr_delay_seconds'])
        config = MANAGERS.make_config(FIXED['manager'], key[1], ready)
        result = replay(ready, entry, tracking, config, spec)
        row, reconstructed = previous.session_values(ready, result, config, identifier)
        row.update(participation(ready, result))
        if fixed_old:
            previous.compare_fields(dict(row, id=old_id), old_rows[key], '旧固定全26項目')
        row['retracements'] = retracements(ready, result, reconstructed, config)
        assert set(target[key]) == SESSION_FIELDS, ('保存session必須集合', set(target[key]) ^ SESSION_FIELDS)
        compare({name: row[name] for name in SESSION_FIELDS}, target[key], '全session保存値')
        stored = ledgers[key]
        assert stored['config'] == config
        for name, width in (('trades', 11), ('orders', 8), ('cycles', 10)):
            exact(result[name], np.asarray(stored[name], float).reshape(-1, width), '保存全台帳/' + name)
        exact(result['stats'], np.asarray(stored['stats'], float), '保存stats')
        assert hashlib.sha256(result['curve'].tobytes()).hexdigest() == stored['curve_SHA256']
        hasher.update(str(key).encode()); hasher.update(result['trades'].tobytes())
        assert len(result['orders']) == len(np.unique(result['orders'][:, 0])), '一行一約定'
        atr_structure(ready, tracking, config, spec, result)
        future_checks(ready, entry, tracking, config, spec, result)
        reflection(ready, entry, tracking, config, spec, result)
        if fixed_old:
            other_atr, _ = input_audit.make_tracking_atr(ready, 300 if spec['variant_id'] == 'V000' else 0)
            identical = replay(ready, entry, other_atr, config, spec)
            for name in ('trades', 'orders', 'cycles', 'stats', 'curve'):
                exact(result[name], identical[name], '固定方式の追跡ATR不使用/' + name)
        row.update(prefix検査合格=True, 未来改変合格=True, 買売反射合格=True,
                   全台帳配列一致=True, 全時価曲線SHA一致=True, ATR全保有行検算=True, 返却独立検算=True)
        rows.append(row); series[key] = reconstructed['equity']
    assert hasher.hexdigest() == summary['ledger_hash']
    if fixed_old:
        old = next(r for r in read(HERE.parent / 'wave_v31/summaries' / (spec['signal_id'] + '.json'))['candidates'] if r['id'] == old_id)
        assert hasher.hexdigest() == old['ledger_hash']
    periods = {}
    for name, sessions in (('all_symbols', FIXED['全セッション']), ('symbols', FIXED['共通評価7セッション'])):
        assert len(sessions) == (13 if name == 'all_symbols' else 7)
        members = [r for r in rows if r['session'] in sessions]
        paths = {k: v for k, v in series.items() if k[0] in sessions}
        periods[name] = {}
        for symbol in previous.MULT:
            value = previous.period_values(members, paths, symbol)
            value.update({f: sum(r[f] for r in members if r['symbol'] == symbol) for f in PARTICIPATION})
            value['retracement'] = retracement_totals([t for r in members if r['symbol'] == symbol for t in r['retracements']])
            assert set(summary[name][symbol]) == PERIOD_FIELDS, ('保存期間必須集合', set(summary[name][symbol]) ^ PERIOD_FIELDS)
            periods[name][symbol] = {f: value[f] for f in PERIOD_FIELDS}
            compare(periods[name][symbol], summary[name][symbol], '全期間集計/' + name)
    assert before == {name: digest(ROOT / name) for name in before}
    output = dict(id=identifier, 全入力数=26, 原本行会計数=sum(r['検算した観測行数'] for r in rows),
        prefix検査数=26, 未来価格入口ATR追跡ATR方向改変数=26, 買売反射数=26,
        全保存数値一致=True, 全台帳配列一致=True, 全時価曲線SHA一致=True, ATR全保有行検算=True,
        返却独立検算=True, 台帳SHA256=hasher.hexdigest(), 旧固定一致=fixed_old,
        固定方式の追跡ATR不使用一致=fixed_old, sessions=rows, 保存資料SHA256=before, **periods)
    save(HERE / 'accounting_details' / (identifier + '.json.gz'), output)
    return {k: v for k, v in output.items() if k not in ('sessions', '保存資料SHA256')}


def self_test() -> dict:
    """機能: 人工価格だけで固定/更新・指定/観測・欠測を会計とATR状態へ照合する。

    引数: なし。返り値: 合成検査結果 (dict)。新損益は読まない。
    """
    prices = np.tile(np.array([100., 96., 98., 104., 111., 118., 120., 110., 103., 90., 94., 99.]), 20)
    n = len(prices)
    ready = dict(time_s=np.r_[np.floor(np.arange(n) / 2.) * 10., 1300., 1301.], seq=np.arange(n + 2),
                 last=np.r_[prices, prices[-1], prices[-1]], atr=np.full(n + 2, 4.), tick=1.,
                 start=-1200., limit=1300., us_open=np.inf, symbol='TOPIX', session='合成Day')
    state = np.where(np.arange(n + 2) % 51 < 25, 1, -1).astype(np.int8)
    tracking = np.resize(np.array([np.nan, 1., 2., 8., np.inf, -1., 4.]), n + 2)
    manager = next(m for m in read(HERE.parent / 'wave_v31/探索条件の固定.json')['managers'] if m['id'] == 'L000')
    config = MANAGERS.make_config(manager, 'TOPIX', ready)
    for dynamic in (0, 1):
        for observed in (False, True):
            spec = dict(dynamic_trail_atr=dynamic, observed_fill=observed)
            result = replay(ready, state, tracking, config, spec)
            row, series = previous.session_values(ready, result, config, '合成')
            assert row['新規注文数'] > 0
            retracements(ready, result, series, config)
            atr_structure(ready, tracking, config, spec, result)
            future_checks(ready, state, tracking, config, spec, result)
            reflection(ready, state, tracking, config, spec, result)
    artificial = [dict(retracement_r=r, retracement_yen=r * 100, positive_peak=positive, holding_minutes=1.)
                  for r, positive in ((1., False), (2., True), (4., True), (5., True))]
    sums = retracement_totals(artificial)
    assert sums['all']['median_r'] == sums['all']['mean_r'] == 3.
    assert sums['positive_peak']['median_r'] == 4. and sums['holding_minutes'] == 4.
    return dict(合成合格=True, 合成組合せ数=4, 固定更新_指定観測=True, ATR欠測下限保持=True,
                独立追跡候補=True, 全玉会計=True, 未来切断改変=True, 上下反射=True, 返却全組正peak別計算=True,
                新損益読取=False, 現在保存物使用=False, API取得数=0)


def main() -> None:
    """機能: 合成・結果前固定、又は全96の独立全玉会計を実行する。

    引数: --prepare/--synthetic-only (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--synthetic-only', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    synthetic = self_test()
    save(HERE / 'accounting_selftest.json', synthetic)
    if args.synthetic_only:
        print('独立会計合成4条件を確認。売買は人工値のみ。', flush=True)
        return
    protocol = freeze()
    if args.prepare:
        print('全96会計の仕様とコードを固定。新損益読取なし。', flush=True)
        return
    started = time.perf_counter()
    initialize()
    assert read(HERE / '主再生の完了.json')['全条件数'] == 96
    before = {name: digest(ROOT / name) for name in FIXED['SHA256']}
    assert before == FIXED['SHA256']
    structure = read(HERE / 'input_causality_before_pnl.json')
    assert structure['構造監査合格'] is True and structure['全監査完了'] is True
    sources = {name: digest(ROOT / name) for name in structure['参照SHA256']}
    assert sources == structure['参照SHA256']
    originals = original_hashes()
    assert originals == structure['原本78SHA256']
    output = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(evaluate, spec): spec['id'] for spec in FIXED['conditions']}
        for future in as_completed(futures):
            output.append(future.result())
            print(f'{len(output)}/96 {futures[future]} 会計・ATR・返却・未来・反射一致', flush=True)
    assert len(output) == len({r['id'] for r in output}) == 96
    assert {r['id'] for r in output} == {s['id'] for s in FIXED['conditions']}
    raw_count = sum(len(r['last']) for r in INPUTS.values())
    assert sum(r['原本行会計数'] for r in output) == raw_count * 96
    assert sum(r['旧固定一致'] for r in output) == 24
    assert before == {name: digest(ROOT / name) for name in before}
    assert sources == {name: digest(ROOT / name) for name in sources}
    assert originals == original_hashes()
    assert freeze() == protocol
    result = dict(全監査合格=True, 対象条件数=96, 全入力数=96 * len(INPUTS), 一条件原本行数=raw_count,
        全原本行会計数=raw_count * 96, prefix検査数=96 * len(INPUTS),
        未来価格入口ATR追跡ATR方向改変数=96 * len(INPUTS), 買売反射数=96 * len(INPUTS),
        全保存数値一致=True, 全台帳配列一致=True, 全時価曲線SHA一致=True, ATR全保有行検算=True,
        返却独立検算=True, 旧固定一致条件数=24, 固定方式の追跡ATR不使用一致条件数=24,
        監査規則=protocol, 合成検査=synthetic, 条件=sorted(output, key=lambda r: r['id']),
        詳細='accounting_details/{id}.json.gz', 参照SHA256=before, 事前入力監査参照SHA256=sources,
        原本78SHA256=originals, 探索固定SHA256=digest(HERE / '探索条件の固定.json'),
        API取得数=0, 現在保存物使用=False, 成績による対象選別=False, 規則変更=False,
        実行秒=time.perf_counter() - started)
    save(HERE / 'accounting_audit.json', result)
    (HERE / 'accounting_audit.md').write_text('\n'.join([
        '# 全96条件の独立会計監査', '',
        f'全96×26={result["全入力数"]:,}区間、原本{result["全原本行会計数"]:,}行を検算。', '',
        '- 全現金・在庫・元建値・部分返済・時価DD・次行約定・上限・場内返済が一致。',
        '- 全13と共通7の保存必須数値、全台帳配列と時価曲線SHAが一致。',
        '- 組ピークから返済までの悪化は注文独立曲線から再計算。負け組を含む全組と正peak組を分けた。',
        '- 全保有行でA0と初回Rの固定、At保持・下限・追跡開始・候補線・緩まない床を別計算した。',
        '- 全2496で37%切断、73%以後の価格・入口ATR・追跡At・方向変更、上下反射が一致。',
        '- 固定A0の主12とATR遅延12は旧同入口D273に一致。Atを遅らせても旧5結果は不変。',
        '- 原本78・固定コード・事前入力監査参照は前後不変。API・現在保存物なし。', '',
        'これは実装と会計の監査。未知期間の収益性や損失額上限の保証ではない。']) + '\n', encoding='utf-8')
    print({k: result[k] for k in ('全監査合格', '対象条件数', '全入力数', '全原本行会計数', '実行秒')}, flush=True)


if __name__ == '__main__':
    main()
