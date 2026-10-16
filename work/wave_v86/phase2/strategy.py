"""入口を変えず、料金後黒字の親組終了だけで早期再参加する。"""
from pathlib import Path
import importlib.util
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True


def module(name,path):
    """
    機能: 第一段階を変更せず独立名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules: return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value
    spec.loader.exec_module(value)
    return value


old=module('wave86_strategy',HERE.parent/'strategy.py')
engine=module('wave86_phase2_engine',HERE/'engine.py')
import numba
numba.config.CACHE_DIR=str(HERE/'cache')
base=old.base
previous=old.previous
PROFIT_REENTRY_COLUMNS=['全返済行','親組','料金後親組円額','早期許可','最短新準備時刻','通常影方向','通常影新規行']


def initialize(inputs,signals):
    """
    機能: 第一段階と同じ元E01公開特徴を生成する。
    引数: inputs/signals(dict)。
    返り値: dict[tuple,dict]。
    """
    return old.initialize(inputs,signals)


def play(config,ready,features,observed=False):
    """
    機能: 黒字時だけ影を次行で終了させ、非黒字では元の通常影時計を保つ。
    引数: config/ready/features(dict)、observed(bool)。
    返り値: tuple[dict,dict] の全台帳・証跡と設定。
    """
    columns=features['columns'];valid=features['valid']
    state=np.where(features['gate'],columns[0],0).astype(np.int8)
    normal_settings,settings=base.settings(dict(changes=config['changes']),ready)
    normal_settings=dict(normal_settings,cooldown_min=5.)
    settings=dict(settings,cooldown_min=5.)
    args,quiet=old.actual_args(ready,features,settings,observed)
    nspar=np.asarray([normal_settings[x] for x in old.shadow_engine.PARAMS],float)
    xspar=np.asarray([settings[x] for x in old.shadow_engine.PARAMS],float)
    values=engine.simulate(ready['time_s'],ready['last'],*args,ready['atr'],state,ready['tick'],
        ready['start'],ready['us_open'],ready.get('session_close',ready['limit']+600.),nspar,xspar,
        columns[1],columns[2],valid,config['dynamic_trail'],config['dynamic_activation_atr'],
        config['dynamic_width_atr'],config['cooldown_seconds'],config.get('profit_fast_enabled',True))
    result=dict(zip(old.FIELDS,values[:18]))
    extra=values[18:]
    normal=dict(plans=extra[0],execution_plans=extra[1],prepare_events=extra[2],entry_preparations=extra[3])
    shadow=dict(plans=extra[4],execution_plans=extra[5],prepare_events=extra[6],entry_preparations=extra[7])
    result.update(normal_shadow=normal,shadow=shadow,dynamic_events=extra[8],reentry_events=extra[9],
        gate_evidence=dict(mfe_atr=extra[10],arm_row=extra[11],armed=extra[12],eligible=extra[13]),
        profit_reentry_events=extra[14],prepare_events=shadow['prepare_events'],
        entry_preparations=shadow['entry_preparations'],time_windows=quiet['windows'])
    return result,settings
