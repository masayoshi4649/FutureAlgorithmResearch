"""元E01の仮想時計を維持した改修と、出口時計への統一を区別して再生する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('e01_v67_prior', ROOT / 'work/wave_v50/update_20261001_day/replay_added_session.py')
prior = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = prior
spec.loader.exec_module(prior)
early = prior.early
integration = early.integration
gate = early.source
import numba
numba.config.CACHE_DIR = str(HERE / 'numba_cache')
import engine_shadow as original
import engine_partial as partial


def catalog() -> list[dict]:
    """機能: 損益を見る前に、単独改修と少数の組合せを固定する。

    引数: なし。返り値: 十六条件(list[dict])。
    """
    return [
        dict(id='E01', name='元E01', gate='none', changes={}, reset=False),
        dict(id='R01', name='新規時にも両銘柄のEMA開始条件を要求', gate='rearm', changes={}, reset=False),
        dict(id='R02', name='両銘柄の長いEMAが逆向きなら見送る', gate='slow', changes={}, reset=False),
        dict(id='R03', name='両銘柄の短いEMAが同方向の時だけ入る', gate='fast', changes={}, reset=False),
        dict(id='R04', name='両銘柄の直近5分が逆向きの時は見送る', gate='opposed', changes={}, reset=False),
        dict(id='R05', name='新規待ちの期限を5分から2分へ', gate='none', changes=dict(ttl_seconds=120.), reset=False),
        dict(id='R06', name='反発・反落確認を0.25から0.5ATRへ', gate='none', changes=dict(entry_atr=.5), reset=False),
        dict(id='R07', name='15分で0.5ATR進まなければ損切りを0.5ATRへ', gate='none', changes=dict(failure_min=15., failure_mfe=.5, failure_stop=.5), reset=False),
        dict(id='R08', name='1ATR進んだら幅1ATRで追跡返済', gate='none', changes=dict(activation_atr=1., main_trail=1.), reset=False),
        dict(id='R09', name='0.75ATR進んだら組の建値を守る', gate='none', changes=dict(breakeven_atr=.75, breakeven_floor=0.), reset=False),
        dict(id='R10', name='出口後は通常影を待たず5分後から再検討', gate='none', changes={}, reset=True),
        dict(id='R11', name='EMA再確認＋出口時計に統一', gate='rearm', changes={}, reset=True),
        dict(id='R12', name='長いEMAの逆行拒否＋出口時計に統一', gate='slow', changes={}, reset=True),
        dict(id='R13', name='短いEMA同方向＋1ATR追跡＋出口時計に統一', gate='fast', changes=dict(activation_atr=1., main_trail=1.), reset=True),
        dict(id='R14', name='EMA再確認＋15分停滞損切り＋出口時計に統一', gate='rearm', changes=dict(failure_min=15., failure_mfe=.5, failure_stop=.5), reset=True),
        dict(id='R15', name='長いEMAの逆行拒否＋1ATR追跡＋出口時計に統一', gate='slow', changes=dict(activation_atr=1., main_trail=1.), reset=True),
    ]


def base_spec() -> dict:
    """機能: 元E01の途中減量・復元なしの仕様をコピーする。

    引数: なし。返り値: 元方式の仕様(dict)。
    """
    return deepcopy(next(s for s in early.source.followup.catalog('new') if s['id'] == early.BASE_ID))


def settings(variant: dict, ready: dict) -> tuple[dict, dict]:
    """機能: 元の通常影と改修後の出口設定を分ける。

    引数: variant/ready(dict)。返り値: 通常影・出口設定(tuple[dict,dict])。
    """
    config = integration.config_for(base_spec(), ready)
    base = dict(config, tighten_atr=0., tight_width=1.)
    for name in ('entry_atr', 'ttl_seconds'):
        if name in variant['changes']:
            base[name] = variant['changes'][name]
    modified = dict(config, stop_atr=.75, **variant['changes'])
    return base, modified


def shadow_run(ready: dict, state: np.ndarray, config: dict, allow: np.ndarray, observed: bool) -> dict:
    """機能: 既存の前行条件・次行執行器を、制御済み設定で直接使用する。

    引数: ready/config(dict)、state/allow(ndarray)、observed(bool)。
    返り値: 仮想建玉と公開済み注文計画(dict)。
    """
    par = np.asarray([config[name] for name in original.PARAMS], float)
    values = original.simulate(ready['time_s'], ready['last'], ready['atr'], ready['atr'], state, state,
        ready['tick'], ready['start'], ready['limit'], ready['us_open'], par, True,
        int(config['audit_cap']), 0, observed, allow, 0., float(ready.get('session_close', ready['limit'] + 600)))
    return dict(zip(early.shadow_api.FIELDS, values))


def play(variant: dict, ready: dict, columns: tuple, valid: np.ndarray, *, observed: bool = False) -> tuple:
    """機能: 各改修の注文経路と途中減量を、未来の約定列を参照せず再生成する。

    引数: variant/ready(dict)、columns(tuple)、valid(ndarray)、observed(bool)。
    返り値: 実結果・有効信号・途中判断証跡(tuple)。
    """
    base, config = settings(variant, ready)
    state = columns[0]
    all_allow = np.ones(len(state), bool)
    if variant['reset']:
        shadow = shadow_run(ready, state, config, all_allow, observed)
        scheduler = shadow
        allow = all_allow
    else:
        scheduler = shadow_run(ready, state, base, all_allow, observed)
        allow = np.zeros(len(state), bool)
        allow[scheduler['prepare_events'][:, 1].astype(int)] = True
        shadow = shadow_run(ready, state, config, allow, observed)
        for field in ('prepare_events', 'entry_preparations'):
            np.testing.assert_array_equal(shadow[field], scheduler[field])
    # ----------------------------------------
    # 減量許可は、通常時計又は統一後の時計が1.5ATR進んだ時点から作る。
    spec = base_spec()
    bad, origin, evidence = integration.reference.gate.gate_bad(ready, scheduler, columns[1], columns[2],
        spec['gate_threshold_atr'], mode=spec['gate_mode'], valid=valid)
    effective = (state, bad, origin, *columns[3:])
    shadow['input_sha256'] = integration.engine.input_digest(ready, state, config, observed, 0.)
    shadow['observed_fill'] = observed
    shadow['min_delay_seconds'] = 0.
    result = partial.run(ready, state, config, bad, origin, effective[3], effective[4],
        spec['policy'], observed_fill=observed, detail=True, shadow=shadow, good_valid=effective[5])
    # 再帰参照を作らず、比較用時計は実結果から別に返す。
    return result, effective, evidence, scheduler, config
