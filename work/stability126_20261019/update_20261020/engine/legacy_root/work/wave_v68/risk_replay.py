"""E01/R01の数量と通常影時計を維持し、初期失敗と連敗の制御を比較する。"""

import importlib.util
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'work/wave_v67'))
import study as previous
import replay as base_replay
import numba
numba.config.CACHE_DIR = str(HERE / 'numba_cache')


def module(name: str, path: Path) -> object:
    """機能: 新作業エンジンを固有名で読む。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


shadow_engine = module('e01_loss_shadow_v68', HERE / 'loss_shadow.py')
engine = module('e01_loss_partial_v68', HERE / 'loss_engine.py')


def catalog() -> list[dict]:
    """機能: 負け機序を対象に、単独制御と少数の組合せを事前指定する。

    引数: なし。返り値: 基準二つと改修条件(list[dict])。
    """
    components = [
        ('S50', '初期損失枠を0.75から0.5ATRへ', dict(stop_atr=.5), {}),
        ('S375', '初期損失枠を0.375ATRへ', dict(stop_atr=.375), {}),
        ('T05H', '5分で0.5ATR未達・0.25ATR逆行なら一度半減', {}, dict(time=300., time_mfe=.5, time_loss=.25, time_action=1)),
        ('T05X', '5分で0.5ATR未達・0.25ATR逆行なら全返済', {}, dict(time=300., time_mfe=.5, time_loss=.25, time_action=2)),
        ('T10X', '10分で0.5ATR未達・0.25ATR逆行なら全返済', {}, dict(time=600., time_mfe=.5, time_loss=.25, time_action=2)),
        ('T15S', '15分で0.5ATR未達なら損失枠0.5ATRへ', dict(failure_min=15., failure_mfe=.5, failure_stop=.5), {}),
        ('T30S', '30分で0.5ATR未達なら損失枠0.5ATRへ', dict(failure_min=30., failure_mfe=.5, failure_stop=.5), {}),
        ('B15H', '1.5ATR未達・0.25ATR逆行で新しい板中値悪化なら半減', {}, dict(bad=1, bad_mfe=1.5, bad_loss=.25)),
        ('B05X', '0.5ATR未達・0.25ATR逆行で新しい板中値悪化なら全返済', {}, dict(bad=2, bad_mfe=.5, bad_loss=.25)),
        ('M25X', '両市場EMAの新しい開始条件が崩れ0.25ATR逆行なら全返済', {}, dict(ema=1, ema_loss=.25)),
        ('A50', '実建玉の料金込み損失予算を0.5ATRへ', {}, dict(risk=.5)),
        ('P2T', '実建玉が料金後2連敗したら新規を30分休止', {}, dict(streak=2, pause=1800.)),
        ('P2E', '実建玉が料金後2連敗したらその場の新規を終了', {}, dict(streak=2, pause=-1.)),
        ('D2R', '料金後の組R合計がマイナス2Rならその場の新規を終了', {}, dict(day_r=2.)),
        ('S50_T05H', '初期0.5ATR＋5分失敗半減', dict(stop_atr=.5), dict(time=300., time_mfe=.5, time_loss=.25, time_action=1)),
        ('S50_B15H', '初期0.5ATR＋新しい悪化で早期半減', dict(stop_atr=.5), dict(bad=1, bad_mfe=1.5, bad_loss=.25)),
        ('T05H_P2T', '5分失敗半減＋2連敗で30分休止', {}, dict(time=300., time_mfe=.5, time_loss=.25, time_action=1, streak=2, pause=1800.)),
        ('M25X_P2T', 'EMA失効時の損失撤退＋2連敗で30分休止', {}, dict(ema=1, ema_loss=.25, streak=2, pause=1800.)),
    ]
    out = []
    for base in ('E01', 'R01'):
        out.append(dict(id=base, base=base, name='元E01' if base == 'E01' else 'EMA再確認R01', changes={}, control={}))
        out.extend(dict(id=base + '_' + code, base=base, name=name, changes=changes, control=control)
            for code, name, changes, control in components)
    return out


def control_parameters(control: dict, symbol: str) -> np.ndarray:
    """機能: 固定制御と商品料金をエンジンの数値列にする。

    引数: control(dict)、symbol(str)。返り値: 制御列(ndarray[float64])。
    """
    return np.asarray([control.get('bad', 0), control.get('bad_mfe', 1.5), control.get('bad_loss', .25),
        control.get('time', 0), control.get('time_mfe', .5), control.get('time_loss', .25),
        control.get('ema', 0), control.get('ema_loss', .25), control.get('risk', 1.),
        control.get('streak', 0), control.get('pause', 0), control.get('day_r', 0),
        previous.FEES[symbol], previous.VALUES[symbol], control.get('time_action', 0)], float)


def shadow_run(ready: dict, state: np.ndarray, config: dict, allow: np.ndarray) -> dict:
    """機能: 通常時計と改修出口を観測価格で再生成する。

    引数: ready/config(dict)、state/allow(ndarray)。返り値: 影の注文計画(dict)。
    """
    par = np.asarray([config[n] for n in shadow_engine.PARAMS], float)
    values = shadow_engine.simulate(ready['time_s'], ready['last'], ready['atr'], ready['atr'], state, state,
        ready['tick'], ready['start'], ready['limit'], ready['us_open'], par, True, int(config['audit_cap']),
        0, True, allow, 0., float(ready.get('session_close', ready['limit'] + 600)))
    return dict(zip(base_replay.early.shadow_api.FIELDS, values))


def ema_columns(key: tuple, ready: dict, models: dict) -> tuple:
    """機能: 両市場の公開済みEMA開始条件と自市場の公開元行を得る。

    引数: key(tuple)、ready/models(dict)。返り値: 方向・根拠行(tuple[ndarray,ndarray])。
    """
    own, peer = base_replay.gate.expanded(key, models, ready['time_s'])
    direction = np.zeros(len(ready['last']), np.int8)
    for side in (1, -1):
        mask = base_replay.gate.gate_mask(dict(kind='rearm'), np.full(len(direction), side, np.int8), own, peer)
        direction[mask] = side
    source = np.full(len(direction), -1, np.int64)
    valid = np.isfinite(own['release']) & np.isfinite(peer['release'])
    source[valid] = np.searchsorted(ready['time_s'], own['release'][valid], side='left')
    assert not (source > np.arange(len(source))).any()
    return direction, source


def play(variant: dict, ready: dict, columns: tuple, valid: np.ndarray, ema: tuple) -> tuple:
    """機能: 未来の組損益を使わず、実玉の失敗整理と休止を逐次実行する。

    引数: variant/ready(dict)、columns(tuple)、valid(ndarray)、ema(tuple)。
    返り値: 実結果・影・通常影・設定(tuple)。
    """
    spec = base_replay.base_spec()
    config = base_replay.integration.config_for(spec, ready)
    base = dict(config, tighten_atr=0., tight_width=1.)
    modified = {**config, 'stop_atr': .75, **variant['changes']}
    state = columns[0]
    scheduler = shadow_run(ready, state, base, np.ones(len(state), bool))
    allow = np.zeros(len(state), bool)
    allow[scheduler['prepare_events'][:, 1].astype(int)] = True
    shadow = shadow_run(ready, state, modified, allow)
    bad, origin, evidence = base_replay.integration.reference.gate.gate_bad(ready, scheduler, columns[1], columns[2],
        spec['gate_threshold_atr'], mode=spec['gate_mode'], valid=valid)
    n = len(state)
    zero, source, invalid = np.zeros(n, np.int8), np.full(n, -1, np.int64), np.zeros(n, bool)
    policy = spec['policy']
    values = engine.simulate(ready['time_s'], ready['last'], shadow['plans'], shadow['execution_plans'],
        shadow['atr_curve'], bad, origin, columns[3], columns[4], columns[5], ready['limit'], modified['entry_cutoff_min'],
        int(modified['initial_qty']), int(modified['audit_cap']), 3, policy['reduce_fraction'], 0,
        int(policy['max_reductions']), 120., True, True, True, 0., zero, source, invalid, zero, 0, -1,
        control_parameters(variant['control'], ready['symbol']), columns[1], columns[2], valid, ema[0], ema[1])
    fields = engine.FIELDS + ('control_curve', 'slot_curve', 'slot_events', 'adjustment_events',
        'budget_events', 'branch_events', 'branch_curve', 'risk_events')
    result = dict(zip(fields, values))
    result['prepare_events'] = shadow['prepare_events']
    result['entry_preparations'] = shadow['entry_preparations']
    result['shadow'] = shadow
    return result, shadow, scheduler, modified
