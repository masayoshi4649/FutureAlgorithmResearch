"""原E01の通常影・出口影を維持して四つの改修部品を接続する。"""
from pathlib import Path
import importlib.util
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'work/wave_v68'))
import risk_replay as legacy
import numba
numba.config.CACHE_DIR = str(HERE / 'cache')
previous = legacy.previous
base = legacy.base_replay

spec = importlib.util.spec_from_file_location('wave85_engine', HERE / 'engine.py')
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
spec.loader.exec_module(engine)
time_spec = importlib.util.spec_from_file_location('wave85_time_filter', HERE / 'time_filter.py')
time_filter = importlib.util.module_from_spec(time_spec)
sys.modules[time_spec.name] = time_filter
time_spec.loader.exec_module(time_filter)


def ema_features(key, ready, models):
    """
    機能: 元の両市場開始条件と、停止後の再成立を監査できる公開元を作る。
    引数: key(tuple)、ready/models(dict)。
    返り値: tuple[ndarray,...]。方向、自己元行、相手公開対応行、有効性。
    """
    own, peer = base.gate.expanded(key, models, ready['time_s'])
    n = len(ready['last'])
    direction = np.zeros(n, np.int8)
    for side in (1, -1):
        mask = base.gate.gate_mask(dict(kind='rearm'), np.full(n, side, np.int8), own, peer)
        direction[mask] = side
    valid = np.ones(n, bool)
    sources = []
    for item in (own, peer):
        ok = np.isfinite(item['gap']) & np.isfinite(item['slow']) & np.isfinite(item['release'])
        ok &= (ready['time_s'] - item['release'] >= 0) & (ready['time_s'] - item['release'] <= 180.)
        source = np.full(n, -1, np.int64)
        source[ok] = np.searchsorted(ready['time_s'], item['release'][ok], side='left')
        assert np.all(source <= np.arange(n))
        sources.append(source)
        valid &= ok
    return direction, sources[0], sources[1], valid


def joint_features(key, inputs, features):
    """
    機能: 両市場の公開済みB00逆行を、同時計の未来行を使わず対応する。
    引数: key(tuple)、inputs/features(dict)。
    返り値: dict。共同方向、自己元行、有効性、相手観測行と元行の証跡。
    """
    other = key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
    own, peer = inputs[key], inputs[other]
    oc, pc = features[key]['columns'], features[other]['columns']
    ov, pv = features[key]['valid'], features[other]['valid']
    index = np.searchsorted(peer['time_s'], own['time_s'], side='left') - 1
    safe = np.maximum(index, 0)
    os = oc[2]
    ps = pc[2][safe]
    safe_os = np.maximum(os, 0)
    safe_ps = np.maximum(ps, 0)
    valid = (index >= 0) & ov & pv[safe] & (os >= 0) & (ps >= 0)
    valid &= peer['time_s'][safe] < own['time_s']
    own_age = own['time_s'] - own['time_s'][safe_os]
    peer_age = own['time_s'] - peer['time_s'][safe_ps]
    valid &= (own_age >= 0) & (own_age <= 30) & (peer_age >= 0) & (peer_age <= 30)
    same = (oc[1] == pc[1][safe]) & (oc[1] != 0)
    direction = np.where(valid & same, oc[1], 0).astype(np.int8)
    assert np.all(os <= np.arange(len(os)))
    return dict(direction=direction, source=os, valid=valid, peer_row=index,
                peer_source=np.where(index >= 0, ps, -1), own_age=own_age, peer_age=peer_age)


def initialize(inputs, signals):
    """
    機能: 全セッション素材を旧E01へ接続し、成績と独立した共同特徴を作る。
    引数: inputs/signals(dict)。
    返り値: dict[tuple,dict]。各口座の元10列・品質・EMA・共同B00。
    """
    base.integration.reference.initialize()
    base.prior.activate(inputs, signals)
    models = {key: base.gate.model(ready) for key, ready in inputs.items()}
    features = {}
    for key, ready in inputs.items():
        columns, valid = base.early.source.replay.new_columns(base.base_spec(), key)
        own, peer = base.gate.expanded(key, models, ready['time_s'])
        gate = base.gate.gate_mask(dict(kind='rearm'), columns[0], own, peer)
        features[key] = dict(columns=columns, valid=valid, gate=gate, ema=ema_features(key, ready, models))
    for key in inputs:
        features[key]['joint'] = joint_features(key, inputs, features)
    return features


def shadow_run(ready, state, config, allow, observed):
    """
    機能: 旧E01の指定価格又は観測価格の独立影を再生する。
    引数: ready/config(dict)、state/allow(ndarray)、observed(bool)。
    返り値: dict。通常影又は出口影と前行有効計画。
    """
    return base.shadow_run(ready, state, config, allow, observed)


def play(config, ready, features, observed=False):
    """
    機能: 同一条件のE01影と実玉を再生成し、指定部品だけ有効化する。
    引数: config/ready/features(dict)、observed(bool)。
    返り値: tuple[dict,dict]。売買・証跡一式と元出口設定。
    """
    mask = config['mask']
    columns, valid = features['columns'], features['valid']
    state = columns[0]
    if mask & 1:
        state = np.where(features['gate'], state, 0).astype(np.int8)
    settings_base, settings = base.settings(dict(changes={}), ready)
    scheduler = shadow_run(ready, state, settings_base, np.ones(len(state), bool), observed)
    allow = np.zeros(len(state), bool)
    allow[scheduler['prepare_events'][:, 1].astype(int)] = True
    shadow = shadow_run(ready, state, settings, allow, observed)
    for field in ('prepare_events', 'entry_preparations'):
        np.testing.assert_array_equal(shadow[field], scheduler[field])
    original_spec = base.base_spec()
    bad, origin, evidence = base.integration.reference.gate.gate_bad(ready, scheduler, columns[1], columns[2],
        original_spec['gate_threshold_atr'], mode=original_spec['gate_mode'], valid=valid)
    n = len(state)
    zero = np.zeros(n, np.int8); source = np.full(n, -1, np.int64); invalid = np.zeros(n, bool)
    control = dict(bad=1, bad_mfe=1.5, bad_loss=.25) if mask & 4 else {}
    losspar = np.concatenate((legacy.control_parameters(control, ready['symbol']),
                              np.asarray([bool(mask & 2), 1.5, .5, bool(mask & 8)], float)))
    joint = features['joint']
    raw = joint['direction'], joint['source'], joint['valid']
    ema = features['ema']
    quiet = time_filter.features(ready, config.get('time_mode', ''))
    policy = original_spec['policy']
    values = engine.simulate(ready['time_s'], ready['last'], shadow['plans'], shadow['execution_plans'],
        shadow['atr_curve'], bad, origin, columns[3], columns[4], columns[5], ready['limit'],
        settings['entry_cutoff_min'], int(settings['initial_qty']), int(settings['audit_cap']),
        3, policy['reduce_fraction'], 0, int(policy['max_reductions']), 120., observed, True, True, 0.,
        zero, source, invalid, zero, 0, -1, losspar, *raw, ema[0], ema[1], ema[2], ema[3],
        quiet['active'], quiet['force'], quiet['not_before'])
    fields = engine.FIELDS + ('control_curve', 'slot_curve', 'slot_events', 'adjustment_events',
        'budget_events', 'branch_events', 'branch_curve', 'risk_events', 'guard_curve', 'guard_events', 'block_events', 'time_events')
    result = dict(zip(fields, values))
    result['prepare_events'] = shadow['prepare_events']
    result['entry_preparations'] = shadow['entry_preparations']
    result['shadow'] = shadow
    result['gate_evidence'] = evidence
    result['time_windows'] = quiet['windows']
    return result, settings
