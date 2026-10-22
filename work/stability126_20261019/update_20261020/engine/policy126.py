"""原E01のLast影を保持し、新部品を実組へ独立に加える接続。"""

import importlib
import numpy as np


MARKET_COLUMNS = ('own_last', 'peer_last', 'own_atr', 'peer_atr',
                  'own_30_atr', 'own_120_atr', 'peer_30_atr', 'peer_120_atr',
                  'peer_source_time', 'own_30_source_time', 'peer_30_source_time',
                  'current_known')
POLICY_COLUMNS = ('protect_start_atr', 'protect_keep_fraction',
                  'rearm_progress_atr', 'session_loss_r')
POLICY_EVENT_COLUMNS = ('row', 'campaign', 'event', 'direction', 'source_row',
                        'value_1', 'value_2', 'value_3', 'value_4', 'value_5',
                        'value_6', 'value_7', 'value_8', 'value_9')
POLICY_EVENT_NAMES = {1: '赤字組後の同方向制限', 2: '損失後の新アンカー固定',
                      3: '新進行による次行からの制限解除', 4: '場損失による全返済予約',
                      5: '場損失による全返済約定', 6: '両市場反対時の利益床昇格',
                      7: '利益床による全返済予約'}


def bind_runtime(rt: dict, inputs: dict, signals: dict) -> None:
    """
    機能: 保存packetの当場入力と元小設定だけを新runtimeへ注入する。
    引数: rt/inputs/signals(dict)は所有runtimeと保存済み当場入力・信号。
    返り値: None。特徴と金融の再計算、旧cacheの読取は行わない。
    """
    from source126 import MIRROR, read
    old = rt['old']
    reference = old.base.integration.reference
    reference.old.FIXED = read(MIRROR / 'work/wave_v38/探索条件の固定.json')
    reference.FIXED = read(MIRROR / 'work/wave_v44/探索条件の固定.json')
    reference.INPUTS = inputs
    reference.old.INPUTS = inputs
    old.base.prior.activate(inputs, signals)


def original_features(rt: dict, inputs: dict, signals: dict) -> dict:
    """
    機能: 原版で使う十列を同じ関数で生成し、無効部品専用の足再読を省く。
    引数: rt/inputs/signals(dict)は所有runtimeと当場の元入力・信号。
    返り値: dict[tuple,dict]は元十列・品質・共同方向。gate/EMAは未計算の未知。
    """
    bind_runtime(rt, inputs, signals)
    old = rt['old']
    features = {}
    for key, ready in inputs.items():
        columns, valid = old.base.early.source.replay.new_columns(old.base.base_spec(), key)
        n = len(ready['last'])
        unknown_direction = np.zeros(n, dtype=np.int8)
        unknown_source = np.full(n, -1, dtype=np.int64)
        unknown_valid = np.zeros(n, dtype=bool)
        features[key] = dict(columns=columns, valid=valid, gate=unknown_valid,
            ema=(unknown_direction, unknown_source.copy(), unknown_source.copy(), unknown_valid.copy()),
            unused_gate_ema='mask0かつEMA/方向停止無効のため未計算。中立又は実測零と扱わない。')
    for key in inputs:
        features[key]['joint'] = old.joint_features(key, inputs, features)
    return features


def trailing(ready: dict, seconds: float) -> tuple[np.ndarray, np.ndarray]:
    """
    機能: 指定秒より未来を含まないLast方向差と窓端時計を求める。
    引数: ready(dict)は旧E01入力、seconds(float)は窓秒数。
    返り値: tuple[ndarray,ndarray]は公開ATR比の差と参照時計。未知はNaN。
    """
    time = np.asarray(ready['time_s'], dtype=float)
    price = np.asarray(ready['last'], dtype=float)
    atr = np.asarray(ready['atr'], dtype=float)
    assert time.ndim == price.ndim == atr.ndim == 1
    assert len(time) == len(price) == len(atr) and np.all(np.diff(time) >= 0.)
    target = time - seconds
    index = np.searchsorted(time, target, side='right') - 1
    safe = np.maximum(index, 0)
    valid = (index >= 0) & np.isfinite(atr) & (atr > 0.)
    valid &= np.isfinite(price) & np.isfinite(price[safe])
    valid &= (target-time[safe] >= 0.) & (target-time[safe] <= 30.)
    assert np.all(index[valid] < np.flatnonzero(valid))
    value = np.full(len(time), np.nan)
    source = np.full(len(time), np.nan)
    value[valid] = (price[valid]-price[safe[valid]])/atr[valid]
    source[valid] = time[safe[valid]]
    return value, source


def make_market(inputs: dict) -> dict:
    """
    機能: 両市場の当時Lastと公開ATRを厳密過去の相手だけで対応する。
    引数: inputs(dict[tuple,dict])は一場以上の旧E01二商品入力。
    返り値: dict[tuple,ndarray]は十二列の因果特徴。未知を零へ置換しない。
    """
    result = {}
    deltas = {key: {seconds: trailing(ready, seconds) for seconds in (30., 120.)}
              for key, ready in inputs.items()}
    for key, own in inputs.items():
        peer_key = key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
        peer = inputs[peer_key]
        time = np.asarray(own['time_s'])
        peer_time = np.asarray(peer['time_s'])
        index = np.searchsorted(peer_time, time, side='left')-1
        safe = np.maximum(index, 0)
        valid = (index >= 0) & (peer_time[safe] < time)
        valid &= (time-peer_time[safe] <= 15.)
        valid &= np.isfinite(own['last']) & np.isfinite(peer['last'][safe])
        valid &= np.isfinite(own['atr']) & (own['atr'] > 0.)
        valid &= np.isfinite(peer['atr'][safe]) & (peer['atr'][safe] > 0.)
        value = np.full((len(time), len(MARKET_COLUMNS)), np.nan)
        value[:, 0] = own['last']; value[:, 2] = own['atr']
        value[:, 4], value[:, 9] = deltas[key][30.]
        value[:, 5] = deltas[key][120.][0]
        value[valid, 1] = peer['last'][safe[valid]]
        value[valid, 3] = peer['atr'][safe[valid]]
        value[valid, 6] = deltas[peer_key][30.][0][safe[valid]]
        value[valid, 7] = deltas[peer_key][120.][0][safe[valid]]
        value[valid, 8] = peer_time[safe[valid]]
        value[valid, 10] = deltas[peer_key][30.][1][safe[valid]]
        value[:, 11] = valid.astype(float)
        assert np.all(value[valid, 8] < time[valid])
        result[key] = value
    return result


def policy_parameters(config: dict) -> np.ndarray:
    """
    機能: 事前固定した三部品だけを数値列へ対応する。
    引数: config(dict)は原版又は十六条件の一つ。
    返り値: ndarray[float64]は利益閾値・利益保持率・再成立幅・場損失倍数。
    """
    assert config['mask'] == 0 and not config['changes']
    assert config['time_mode'] in ('none', '')
    assert config['fee_per_side'] == 0.
    assert config['cooldown_seconds'] == 300.
    assert not config['increase_positions'] and not config['restore_positions']
    assert not config['force_first_entry']
    assert config['protect_keep_fraction'] == .5
    assert config['protect_window_seconds'] == 30.
    assert config['protect_long_window_seconds'] == 120.
    assert config['protect_short_opposition_atr'] == .05
    assert config['protect_long_opposition_atr'] == .1
    assert config['rearm_window_seconds'] == 30. and config['rearm_support_atr'] == .05
    assert config['peer_freshness_seconds'] == 15.
    assert config['protect_require_opposition'] and config['protect_only_raise_during_opposition']
    assert config['rearm_mode'] in ('none', 'loss_anchor')
    return np.asarray([config[name] for name in POLICY_COLUMNS], dtype=float)


def play(rt: dict, config: dict, ready: dict, feature: dict, market: np.ndarray,
         observed: bool = True) -> tuple[dict, dict]:
    """
    機能: 原版の影・実枠・減量・段階出口を維持し、設定された新部品だけ運転する。
    引数: rt/config/ready/feature(dict)、market(ndarray)、observed(bool)は所有源と当時入力。
    返り値: tuple[dict,dict]は全会計配列と元出口設定。手数料は零。
    """
    assert observed is True, 'この比較は観測Last約定だけです'
    parameters = policy_parameters(config)
    old = rt['old']
    core = importlib.import_module('last_core126')
    columns, valid = feature['columns'], feature['valid']
    state = columns[0]
    settings_base, settings = old.base.settings(dict(changes={}), ready)
    scheduler = old.shadow_run(ready, state, settings_base, np.ones(len(state), bool), observed)
    allow = np.zeros(len(state), bool)
    allow[scheduler['prepare_events'][:, 1].astype(int)] = True
    shadow = old.shadow_run(ready, state, settings, allow, observed)
    for name in ('prepare_events', 'entry_preparations'):
        np.testing.assert_array_equal(shadow[name], scheduler[name])
    original_spec = old.base.base_spec()
    bad, origin, evidence = old.base.integration.reference.gate.gate_bad(
        ready, scheduler, columns[1], columns[2], original_spec['gate_threshold_atr'],
        mode=original_spec['gate_mode'], valid=valid)
    n = len(state)
    zero = np.zeros(n, np.int8)
    source = np.full(n, -1, np.int64)
    invalid = np.zeros(n, bool)
    losspar = np.concatenate((old.legacy.control_parameters({}, ready['symbol']),
                              np.asarray([False, 1.5, .5, False], float)))
    losspar[12] = 0.
    joint = feature['joint']
    raw = joint['direction'], joint['source'], joint['valid']
    ema = feature['ema']
    quiet = old.time_filter.features(ready, '')
    policy = original_spec['policy']
    values = core.simulate(
        ready['time_s'], ready['last'], shadow['plans'], shadow['execution_plans'], shadow['atr_curve'],
        bad, origin, columns[3], columns[4], columns[5], ready['limit'],
        settings['entry_cutoff_min'], int(settings['initial_qty']), int(settings['audit_cap']),
        3, policy['reduce_fraction'], 0, int(policy['max_reductions']), 120., observed, True, True, 0.,
        zero, source, invalid, zero, 0, -1, losspar, *raw, ema[0], ema[1], ema[2], ema[3],
        quiet['active'], quiet['force'], quiet['not_before'], parameters, market)
    fields = core.FIELDS + ('control_curve', 'slot_curve', 'slot_events', 'adjustment_events',
        'budget_events', 'branch_events', 'branch_curve', 'risk_events', 'guard_curve',
        'guard_events', 'block_events', 'time_events', 'policy_curve126', 'policy_events126')
    assert len(fields) == len(values)
    result = dict(zip(fields, values))
    result['prepare_events'] = shadow['prepare_events']
    result['entry_preparations'] = shadow['entry_preparations']
    result['shadow'] = shadow
    result['gate_evidence'] = evidence
    result['time_windows'] = quiet['windows']
    return result, settings


def normalized_summary(result: dict, ready: dict) -> dict:
    """
    機能: 手数料零の返済脚正負と親組正負を別々に円へ換算する。
    引数: result/ready(dict)は完成会計と旧入力。
    返り値: dictは各場の利益・損失・収支、枚数、未返済、追加部品件数。
    """
    multiplier = {'TOPIX': 1000., 'NK225': 10.}[ready['symbol']]
    trades, orders, cycles = result['trades'], result['orders'], result['cycles']
    pnl = trades[:, 10]*multiplier
    parent = cycles[:, 3]*multiplier
    profit = float(pnl[pnl > 0.].sum())
    loss = float(-pnl[pnl < 0.].sum())
    net = profit-loss
    assert np.isclose(net, result['stats'][0]*multiplier, rtol=1e-12, atol=1e-6)
    assert np.isclose(net, parent.sum(), rtol=1e-12, atol=1e-6)
    assert result['stats'][9] == 0., '未返済のある口座を完成成績にしません'
    entry = orders[:, 7] == 1.
    return dict(symbol=ready['symbol'], profit=profit, loss=loss, net=net, fees=0,
        entries=int(entry.sum()), campaigns=len(cycles),
        winning_lots=int(trades[pnl > 0., 3].sum()), losing_lots=int(trades[pnl < 0., 3].sum()),
        flat_lots=int(trades[pnl == 0., 3].sum()), new_lots=int(orders[entry, 4].sum()),
        settled_lots=int(trades[:, 3].sum()), unclosed=0,
        parent_profit=float(parent[parent > 0.].sum()), parent_loss=float(-parent[parent < 0.].sum()),
        winning_campaigns=int((parent > 0.).sum()), losing_campaigns=int((parent < 0.).sum()),
        policy_event_counts={name: int((result['policy_events126'][:, 2] == code).sum())
                             for code, name in POLICY_EVENT_NAMES.items()})
