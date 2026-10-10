"""仮想準備制御192条件の全玉会計・ピーク悪化・因果性を独立に検査する。"""

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
sys.path.insert(0, str(HERE.parent / 'wave_v33'))
import input_audit
sys.path.insert(0, str(HERE))
import engine_scheduler as ENGINE
import scheduler_audit_helpers as connection
import scheduler_design as design
sys.path.insert(0, str(V30))
import all_accounting_audit as previous
from context_structure_audit import read, save, digest, original_hashes, reject_network

MANAGERS = previous.managers
INPUTS, ENTRIES, FIXED = {}, {}, {}
PARTICIPATION = ('long_unit_minutes', 'short_unit_minutes', 'opening_orders')
SESSION_FIELDS = {'gate'} | set(('id symbol session gross_profit_yen gross_loss_yen net_yen profit_units loss_units zero_units '
    'cycles cycle_wins cycle_losses cycle_profit_yen cycle_loss_yen net_r drawdown_yen min_equity_yen max_equity_yen '
    'max_long max_short closed_units reversals longest_losing_streak maximum_trade_profit maximum_trade_loss '
    'two_largest_cycle_profits long_unit_minutes short_unit_minutes opening_orders first_entry_min retracements').split())
PERIOD_FIELDS = {'gate'} | set(('gross_profit_yen gross_loss_yen net_yen profit_units loss_units zero_units cycles cycle_wins '
    'cycle_losses cycle_profit_yen cycle_loss_yen net_r closed_units money_ratio cycle_ratio win_sessions active_sessions '
    'worst_session drawdown_yen best_removed_net best_removed_pf best_trade_removed_net max_long max_short '
    'longest_losing_streak session_count average_unit_payoff long_unit_minutes short_unit_minutes opening_orders retracement').split())




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
        yen = sorted(r['retracement_yen'] for r in selected)
        n = len(values)
        median = None if n == 0 else values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2.
        output[name] = dict(cycles=n, sum_yen=sum(r['retracement_yen'] for r in selected),
                            sum_r=sum(values), mean_r=None if not n else sum(values) / n, median_r=median,
                            mean_yen=None if not n else sum(yen) / n,
                            median_yen=None if not n else yen[n // 2] if n % 2 else (yen[n // 2 - 1] + yen[n // 2]) / 2.)
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
    assert len(INPUTS) == 26 and len(FIXED['conditions']) == 192









replay = connection.replay
future_checks = connection.future_checks
reflection = connection.reflection

GATE_FIELDS = ('shadow_preparations', 'actual_preparations', 'shared_preparations', 'extra_preparations',
               'skipped_shadow_preparations', 'shadow_opening_orders', 'actual_opening_orders',
               'matched_openings', 'unmatched_openings', 'skipped_holding', 'skipped_cooldown',
               'skipped_pending', 'skipped_other')


def gate_metrics(ready: dict, result: dict, series: dict) -> dict:
    """機能: 影と実の新設集合・起点・独立在庫から参加と見送り理由を計数する。

    引数: ready/result/series (dict)。返り値: 固定13指標 (dict)。
    """
    shadow = result['shadow']
    source = {tuple(r[1:]) for r in shadow['prepare_events']}
    actual = {tuple(r[1:]) for r in result['prepare_events']}
    common = source & actual
    shared_rows = {int(r[0]) for r in common}
    sources = {int(r[1]) for r in shadow['prepare_events']}
    shadow_fills = {(int(r[3]), int(r[1])) for r in shadow['entry_preparations']}
    matched = sum(int(r[3]) in shared_rows and (int(r[3]), int(r[1])) in shadow_fills for r in result['entry_preparations'])
    reasons = dict(skipped_holding=0, skipped_cooldown=0, skipped_pending=0, skipped_other=0)
    exits = result['cycles'][:, 2].astype(np.int64)
    # 独立注文会計から在庫を使用する。既存pendingの表示だけは注文器の全行診断へ照合する。
    for row in sorted(sources - shared_rows):
        recent = np.searchsorted(exits, row, side='right') - 1
        if series['long'][row] + series['short'][row] > 0:
            reasons['skipped_holding'] += 1
        elif recent >= 0 and ready['time_s'][row] - ready['time_s'][exits[recent]] < 300.:
            reasons['skipped_cooldown'] += 1
        elif np.isfinite(result['atr_curve'][row, ENGINE.ATR_COLUMNS.index('pending_initial_atr')]):
            reasons['skipped_pending'] += 1
        else:
            reasons['skipped_other'] += 1
    return dict(shadow_preparations=len(source), actual_preparations=len(actual), shared_preparations=len(common),
                extra_preparations=len(actual - source), skipped_shadow_preparations=len(source - actual),
                shadow_opening_orders=len(shadow['entry_preparations']), actual_opening_orders=len(result['entry_preparations']),
                matched_openings=matched, unmatched_openings=len(result['entry_preparations']) - matched, **reasons)


def freeze() -> dict:
    """機能: 全192条件の独立会計・影準備接続・因果検査を結果前に固定する。

    引数: なし。返り値: 監査規則 (dict)。固定済み内容の変更は拒否する。
    """
    fixed = read(HERE / '探索条件の固定.json')
    paths = [Path(__file__), HERE / 'scheduler_audit_helpers.py', HERE / 'engine_scheduler.py',
             HERE / 'scheduler_input_audit.py', HERE / 'input_causality_before_pnl.json',
             HERE.parent / 'wave_v33/accounting_audit_v2.py', HERE.parent / 'wave_v33/input_audit.py',
             V30 / 'all_accounting_audit.py', HERE.parent / 'wave_v29/selected_accounting_audit.py',
             V30 / 'context_structure_audit.py']
    value = dict(固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 対象条件ID=[s['id'] for s in fixed['conditions']],
                 対象条件数=192, 対象入力数=26, 対象='全12入口×A0/At×通常/影新設制御×4変形、成績による選別なし。',
                 会計='全注文から現金・両在庫・部分返済・全行時価/DD・上限・次行約定・場内を再構成。影も全原本行で会計検算。',
                 集計='全13/後半7の全保存数値。返却額は注文独立曲線から全組/正peakを分離し、円/R平均中央値も計算。gate13項目を別計数。',
                 接続='影はA0通常、実の保有/結果/追跡Atに非依存。影の新設行のみ許可し実の準備属性・約定起点・同じ影新規を検算。',
                 未来='全4992入力で37%切断・73%以後価格/入口ATR/追跡ATR/方向変更・上下反射。毎回影から許可を再生成。',
                 互換='通常96はv33旧6結果と保存全数値に一致。制御A0全48は影旧5+新設/起点に一致し、同変形v33A0旧6にも一致。',
                 欠測='追跡欠測はA0開始の既知値維持、下限2tick、Atは追跡幅だけ。原本時刻は受信時刻でなくCurrentPriceTime代理。',
                 制限='原本・旧版・現在保存物不使用。API0。未知収益性や損失額上限を証明する監査ではない。',
                 参照SHA256={p.relative_to(ROOT).as_posix(): digest(p) for p in paths},
                 探索固定SHA256=digest(HERE / '探索条件の固定.json'))
    path = HERE / 'accounting_fixed.json'
    if path.exists():
        old = read(path)
        assert {k: v for k, v in old.items() if k != '固定日時'} == {k: v for k, v in value.items() if k != '固定日時'}
        return old
    save(path, value)
    return value


def fingerprint(result: dict) -> dict:
    """機能: 旧6配列の実体と形を個別に指紋化する。

    引数: result (dict)。返り値: 配列別shape/SHA (dict)。
    """
    return {name: dict(shape=list(result[name].shape), SHA256=hashlib.sha256(result[name].tobytes()).hexdigest())
            for name in connection.OLD_FIELDS}


def ledger_equal(result: dict, saved: dict) -> None:
    """機能: 保存された影又は実の全台帳と旧6配列SHAを照合する。

    引数: result/saved (dict)。返り値: なし (None)。
    """
    for name, width in (('trades', 11), ('orders', 8), ('cycles', 10), ('prepare_events', 7), ('entry_preparations', 4)):
        exact(result[name], np.asarray(saved[name], float).reshape(-1, width), '保存全台帳/' + name)
    exact(result['stats'], np.asarray(saved['stats'], float), '保存stats')
    compare(fingerprint(result), saved['result_fingerprints'], '保存旧6指紋')


def evaluate(spec: dict) -> dict:
    """機能: 一条件全26入力の全玉会計と影接続・未来・旧版対応を独立検査する。

    引数: spec (dict)。返り値: 全区間・全期間監査結果 (dict)。
    """
    identifier = spec['id']
    paths = [HERE / folder / (identifier + suffix) for folder, suffix in
             (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('summaries', '.json'))]
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    saved_rows, saved_ledgers, summary = (read(p) for p in paths)
    targets = {(r['session'], r['symbol']): r for r in saved_rows}
    ledgers = {(r['session'], r['symbol']): r for r in saved_ledgers}
    assert len(saved_rows) == len(targets) == len(saved_ledgers) == len(ledgers) == 26
    assert set(targets) == set(ledgers) == set(INPUTS)
    assert summary['id'] == identifier and summary['spec'] == spec
    assert summary['探索固定SHA256'] == digest(HERE / '探索条件の固定.json')
    assert summary['旧通常再現'] is (not spec['gated'])
    fixed_identity = spec['gated'] and not spec['dynamic_trail_atr']
    assert summary['固定制御同値'] is fixed_identity
    old_id = spec['signal_id'] + '__' + spec['atr_mode_id'] + '__' + spec['variant_id']
    old_rows = {(r['session'], r['symbol']): r for r in read(HERE.parent / 'wave_v33/sessions' / (old_id + '.json.gz'))}
    rows, series, hasher = [], {}, hashlib.sha256()
    for key, ready in INPUTS.items():
        entry, _ = input_audit.make_entry(ready, ENTRIES[spec['signal_id']][key], spec['entry_delay_seconds'])
        tracking, _ = input_audit.make_tracking_atr(ready, spec['trail_atr_delay_seconds'])
        config = MANAGERS.make_config(FIXED['manager'], key[1], ready)
        result = replay(ready, entry, tracking, config, spec)
        row, reconstructed = previous.session_values(ready, result, config, identifier)
        previous.reconstruct(ready, result['shadow'], ready['symbol'])
        row.update(participation(ready, result))
        row['retracements'] = retracements(ready, result, reconstructed, config)
        if not spec['gated'] or fixed_identity:
            legacy = connection.baseline.ENGINE.run(ready, entry, config, detail=True,
                width_mode=spec['dynamic_trail_atr'], observed_fill=spec['observed_fill'], trail_atr=tracking)
            connection.same_results(result, legacy)
            compare({field: row[field] if field != 'id' else old_id for field in old_rows[key]}, old_rows[key], '旧v33全保存値')
        if not spec['dynamic_trail_atr']:
            connection.same_results(result, result['shadow'], ('trades', 'orders', 'cycles', 'curve', 'stats', *connection.EXTRA_FIELDS))
        links = connection.preparation_links(ready, entry, config, result, spec['gated'])
        row['gate'] = gate_metrics(ready, result, reconstructed)
        assert set(targets[key]) == SESSION_FIELDS
        compare({name: row[name] for name in SESSION_FIELDS}, targets[key], '全session保存値')
        stored = ledgers[key]
        assert stored['config'] == config
        ledger_equal(result, stored); ledger_equal(result['shadow'], stored['shadow'])
        assert hashlib.sha256(result['curve'].tobytes()).hexdigest() == stored['curve_SHA256']
        allowed_sha = hashlib.sha256(result['allow'].tobytes()).hexdigest() if spec['gated'] else None
        assert allowed_sha == stored['prepare_allow_SHA256']
        hasher.update(str(key).encode()); hasher.update(result['trades'].tobytes())
        assert len(result['orders']) == len(np.unique(result['orders'][:, 0])), '一行一約定'
        atr_structure(ready, tracking, config, spec, result)
        future_checks(ready, entry, tracking, config, spec, result)
        reflection(ready, entry, tracking, config, spec, result)
        row.update(prefix検査合格=True, 未来改変合格=True, 買売反射合格=True, 全台帳配列一致=True,
                   全時価曲線SHA一致=True, ATR全保有行検算=True, 返却独立検算=True, 影会計一致=True, 準備起点検査=links)
        rows.append(row); series[key] = reconstructed['equity']
    assert hasher.hexdigest() == summary['ledger_hash']
    periods = {}
    for name, sessions in (('all_symbols', FIXED['全セッション']), ('symbols', FIXED['共通評価7セッション'])):
        assert len(sessions) == (13 if name == 'all_symbols' else 7)
        members = [r for r in rows if r['session'] in sessions]
        curves = {k: v for k, v in series.items() if k[0] in sessions}
        periods[name] = {}
        for symbol in previous.MULT:
            selected = [r for r in members if r['symbol'] == symbol]
            value = previous.period_values(members, curves, symbol)
            value.update({f: sum(r[f] for r in selected) for f in PARTICIPATION})
            value['retracement'] = retracement_totals([t for r in selected for t in r['retracements']])
            value['gate'] = {f: sum(r['gate'][f] for r in selected) for f in GATE_FIELDS}
            assert set(summary[name][symbol]) == PERIOD_FIELDS
            periods[name][symbol] = {f: value[f] for f in PERIOD_FIELDS}
            compare(periods[name][symbol], summary[name][symbol], '全期間集計/' + name)
    assert before == {name: digest(ROOT / name) for name in before}
    output = dict(id=identifier, 全入力数=26, 原本行会計数=sum(r['検算した観測行数'] for r in rows),
        prefix検査数=26, 未来価格入口ATR追跡ATR方向改変数=26, 買売反射数=26,
        全保存数値一致=True, 全台帳配列一致=True, 全時価曲線SHA一致=True, ATR全保有行検算=True,
        返却独立検算=True, 影会計一致=True, 準備接続検査=True, 台帳SHA256=hasher.hexdigest(),
        旧通常一致=not spec['gated'], 固定制御同値=fixed_identity,
        固定ATR遅延経済準備同値=not spec['dynamic_trail_atr'] and spec['variant_id'] == 'L300',
        sessions=rows, 保存資料SHA256=before, **periods)
    save(HERE / 'accounting_details' / (identifier + '.json.gz'), output)
    return {k: v for k, v in output.items() if k not in ('sessions', '保存資料SHA256')}


def self_test() -> dict:
    """機能: 人工相場だけで影の独立性・準備接続・欠測ATR・会計・因果性を検査する。

    引数: なし。返り値: 合成結果 (dict)。新しい実相場の制御損益は計算しない。
    """
    prices = np.tile(np.array([100., 96., 98., 104., 111., 118., 120., 110., 103., 90., 94., 99.]), 20)
    n = len(prices)
    ready = dict(time_s=np.r_[np.floor(np.arange(n) / 2.) * 10., 1300., 1301.], seq=np.arange(n + 2),
                 last=np.r_[prices, prices[-1], prices[-1]], atr=np.full(n + 2, 4.), tick=1.,
                 start=-1200., limit=1300., us_open=np.inf, symbol='TOPIX', session='合成Day')
    state = np.where(np.arange(n + 2) % 51 < 25, 1, -1).astype(np.int8)
    tracking = np.resize(np.array([np.nan, 1., 2., 8., np.inf, -1., 4.]), n + 2)
    manager = read(HERE.parent / 'wave_v33/探索条件の固定.json')['manager']
    config = MANAGERS.make_config(manager, 'TOPIX', ready)
    for dynamic in (0, 1):
        for observed in (False, True):
            for gated in (False, True):
                spec = dict(dynamic_trail_atr=dynamic, observed_fill=observed, gated=gated)
                result = replay(ready, state, tracking, config, spec)
                row, series = previous.session_values(ready, result, config, '合成')
                previous.reconstruct(ready, result['shadow'], 'TOPIX')
                assert row['新規注文数'] > 0
                connection.preparation_links(ready, state, config, result, gated)
                gate_metrics(ready, result, series)
                retracements(ready, result, series, config)
                atr_structure(ready, tracking, config, spec, result)
                future_checks(ready, state, tracking, config, spec, result)
                reflection(ready, state, tracking, config, spec, result)
                if not dynamic and gated:
                    connection.same_results(result, result['shadow'], ('trades', 'orders', 'cycles', 'curve', 'stats', *connection.EXTRA_FIELDS))
                other = replay(ready, state, np.full(len(state), 50000.), config, spec)
                connection.same_results(result['shadow'], other['shadow'], (*connection.OLD_FIELDS, *connection.EXTRA_FIELDS))
                exact(result['allow'], other['allow'], '実追跡At変更で影許可不変')
    # ----------------------------------------
    # 影が先に返済した人工経路。保有中と休止中に見送った準備へ後から参加しない。
    path = np.array([120., 121., 140., 127., 127., 126., 110., 110., 110., 111., 140., 127., 120., 121.])
    clock = np.array([0., 1., 2., 3., 303., 304., 305., 603., 606., 607., 608., 609., 909., 910.])
    fixture = dict(ready, time_s=np.r_[clock, 10000., 10001.], last=np.r_[path, path[-1], path[-1]],
                   seq=np.arange(16), atr=np.full(16, 4.), limit=10000.)
    direction = np.ones(16, dtype=np.int8)
    at = np.r_[4., 4., np.full(14, 10.)]
    spec = dict(dynamic_trail_atr=1, observed_fill=False, gated=True)
    actual = replay(fixture, direction, at, config, spec)
    exact(actual['prepare_events'][:, 1], np.array([0., 12.]), '見送った準備への途中参加なし')
    exact(actual['entry_preparations'][:, 1], np.array([1., 13.]), '影の次新設から参加')
    exact(actual['shadow']['prepare_events'][:, 1], np.array([0., 4., 7., 12.]), '実が遅れても影は独立継続')
    _, series = previous.session_values(fixture, actual, config, '境界合成')
    metrics = gate_metrics(fixture, actual, series)
    assert metrics['skipped_holding'] == metrics['skipped_cooldown'] == 1
    connection.preparation_links(fixture, direction, config, actual, True)
    future_checks(fixture, direction, at, config, spec, actual)
    reflection(fixture, direction, at, config, spec, actual)
    # 未来の影を再生成した証拠: 未来入口を全中立化すると未来準備は消えるが既知許可は同じ。
    changed = direction.copy(); changed[8:] = 0
    altered = replay(fixture, changed, at, config, spec)
    exact(actual['allow'][:8], altered['allow'][:8], '影未来再生成の過去一致')
    assert not np.array_equal(actual['allow'][8:], altered['allow'][8:]), '旧mask流用ではこの負例を通せない'
    rejected = False
    try:
        exact(actual['allow'], altered['allow'], '全未来にも旧maskを流用する誤実装')
    except AssertionError:
        rejected = True
    assert rejected
    connection.baseline.self_test()
    return dict(合成合格=True, 合成組合せ数=8, 同時刻原本順=True, 影独立再生成=True, 準備起点全属性=True,
                影同一新規約定=True, 固定制御恒等=True, ATR欠測下限保持=True, 全玉会計=True,
                未来切断改変=True, 上下反射=True, 円平均中央値_偶数奇数空集合=True,
                見送り途中参加禁止=True, 保有休止見送り独立計数=True, 旧未来mask流用負例拒否=True,
                新損益読取=False, 現在保存物使用=False, API取得数=0)


def main() -> None:
    """機能: 合成と結果前固定、又は全192の独立全玉会計を実行する。

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
        print('独立接続・会計合成8条件を確認。実相場制御損益なし。', flush=True)
        return
    protocol = freeze()
    if args.prepare:
        print('全192会計の仕様とコードを固定。新損益読取なし。', flush=True)
        return
    started = time.perf_counter()
    initialize()
    assert read(HERE / '主再生の完了.json')['全条件数'] == 192
    before = {name: digest(ROOT / name) for name in FIXED['SHA256']}
    assert before == FIXED['SHA256']
    structure = read(HERE / 'input_causality_before_pnl.json')
    assert structure['構造監査合格'] and structure['全監査完了']
    sources = {name: digest(ROOT / name) for name in structure['参照SHA256']}
    assert sources == structure['参照SHA256']
    originals = original_hashes()
    assert originals == structure['原本78SHA256']
    output = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(evaluate, spec): spec['id'] for spec in FIXED['conditions']}
        for future in as_completed(futures):
            output.append(future.result())
            print(f'{len(output)}/192 {futures[future]} 会計・ATR・影準備・未来・反射一致', flush=True)
    assert len(output) == len({r['id'] for r in output}) == 192
    assert {r['id'] for r in output} == {s['id'] for s in FIXED['conditions']}
    raw_count = sum(len(r['last']) for r in INPUTS.values())
    assert sum(r['原本行会計数'] for r in output) == raw_count * 192
    assert sum(r['旧通常一致'] for r in output) == 96
    assert sum(r['固定制御同値'] for r in output) == 48
    assert sum(r['固定ATR遅延経済準備同値'] for r in output) == 24
    assert before == {name: digest(ROOT / name) for name in before}
    assert sources == {name: digest(ROOT / name) for name in sources}
    assert originals == original_hashes()
    assert freeze() == protocol
    result = dict(全監査合格=True, 対象条件数=192, 全入力数=192 * len(INPUTS), 一条件原本行数=raw_count,
        全原本行会計数=raw_count * 192, prefix検査数=192 * len(INPUTS),
        未来価格入口ATR追跡ATR方向改変数=192 * len(INPUTS), 買売反射数=192 * len(INPUTS),
        全保存数値一致=True, 全台帳配列一致=True, 全時価曲線SHA一致=True, ATR全保有行検算=True,
        返却独立検算=True, 影会計一致=True, 準備接続検査=True, 旧通常一致条件数=96, 固定制御同値条件数=48,
        固定ATR遅延経済準備同値条件数=24,
        監査規則=protocol, 合成検査=synthetic, 条件=sorted(output, key=lambda r: r['id']),
        詳細='accounting_details/{id}.json.gz', 参照SHA256=before, 事前入力監査参照SHA256=sources,
        原本78SHA256=originals, 探索固定SHA256=digest(HERE / '探索条件の固定.json'),
        API取得数=0, 現在保存物使用=False, 成績による対象選別=False, 規則変更=False,
        実行秒=time.perf_counter() - started)
    save(HERE / 'accounting_audit.json', result)
    (HERE / 'accounting_audit.md').write_text('# 仮想準備制御の全192独立監査\n\n全192×26入力の全注文会計、実と影の台帳・原本時価・ATR・返却額・準備起点が一致。全件で影から再生成した37%切断・73%未来値改変・上下反射が一致した。通常96は旧v33、固定A0制御48は仮想側と同値。原本78と固定コードは前後不変、API・現在保存物なし。\n\nこれは機械的実装と会計の確認であり、未知期間の利益を保証するものではない。\n', encoding='utf-8')
    print({k: result[k] for k in ('全監査合格', '対象条件数', '全入力数', '全原本行会計数', '実行秒')}, flush=True)


if __name__ == '__main__':
    main()
