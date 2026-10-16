"""旧P1の途中管理を保持し、同方向の再入口と初期停止を独立比較する。"""
from pathlib import Path
import importlib.util
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def module(name, path):
    """
    機能: 旧成果を上書きせず読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


prior = module('wave86_phase2_strategy', HERE.parents[1] / 'wave_v86/phase2/strategy.py')
old = prior.old
previous = old.previous
base = old.base
engine = module('wave87_round1_engine', HERE / 'engine.py')
import numba
numba.config.CACHE_DIR = str(HERE / 'cache')
RESTART_COLUMNS = ['観測行','種別','前黒字全返済行','前方向','前実組極値','有効非支持確認行','自己EMA元行','相手EMA元行','状態又は新規方向','注文線又は約定値']


def initialize(inputs, signals):
    """
    機能: 元P1と同じ過去公開特徴を生成する。
    引数: inputs/signals(dict)。
    返り値: dict。
    """
    return prior.initialize(inputs, signals)


def play(config, ready, features, observed=False):
    """
    機能: 追加再入口条件と出口影停止幅を変えて同じ実玉会計を再生する。
    引数: config/ready/features(dict)、observed(bool)。
    返り値: tuple[dict,dict] の全台帳・証跡と設定。
    """
    columns = features['columns']
    state = np.where(features['gate'], columns[0], 0).astype(np.int8)
    changes = {key:value for key,value in config['changes'].items() if key != 'stop_atr'}
    normal_settings, settings = base.settings(dict(changes=changes), ready)
    settings = dict(settings, stop_atr=config['stop_atr'])
    normal_settings = dict(normal_settings, cooldown_min=5.)
    settings = dict(settings, cooldown_min=5.)
    args, quiet = old.actual_args(ready, features, settings, observed)
    nspar = np.asarray([normal_settings[x] for x in old.shadow_engine.PARAMS], float)
    xspar = np.asarray([settings[x] for x in old.shadow_engine.PARAMS], float)
    values = engine.simulate(ready['time_s'], ready['last'], *args, ready['atr'], state,
        ready['tick'], ready['start'], ready['us_open'], ready.get('session_close', ready['limit']+600.),
        nspar, xspar, columns[1], columns[2], features['valid'], config['dynamic_trail'],
        config['dynamic_activation_atr'], config['dynamic_width_atr'], config['cooldown_seconds'],
        config.get('profit_fast_enabled', True), config['reentry_filter'])
    result = dict(zip(old.FIELDS, values[:18]))
    extra = values[18:]
    normal = dict(plans=extra[0], execution_plans=extra[1], prepare_events=extra[2], entry_preparations=extra[3])
    shadow = dict(plans=extra[4], execution_plans=extra[5], prepare_events=extra[6], entry_preparations=extra[7])
    result.update(normal_shadow=normal, shadow=shadow, dynamic_events=extra[8], reentry_events=extra[9],
        gate_evidence=dict(mfe_atr=extra[10], arm_row=extra[11], armed=extra[12], eligible=extra[13]),
        profit_reentry_events=extra[14], restart_events=extra[15],
        prepare_events=shadow['prepare_events'], entry_preparations=shadow['entry_preparations'],
        time_windows=quiet['windows'])
    return result, settings
