"""原GUの両影・途中管理を維持し、実玉の一部だけ狭い出口を重ねる。"""
from pathlib import Path
import importlib.util
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True


def module(name,path):
    """
    機能: 既存又は新規の実装を読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules: return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


old=module('wave86_strategy',HERE.parents[1]/'wave_v86/strategy.py')
engine=module('wave87_round2_engine',HERE/'engine.py')
base=old.base
previous=old.previous
import numba
numba.config.CACHE_DIR=str(HERE/'cache')
PARTIAL_COLUMNS=['行','組','種別','根拠行','方向','枚数','注文線又は約定値','実組極値','初期ATR','実現差又は料金後実現差','残枚数又は見込返済料','先行枠数']


def initialize(inputs,signals):
    """
    機能: 原GUと同じ公開済み特徴を生成する。
    引数: inputs/signals(dict)。
    返り値: dict。
    """
    return old.initialize(inputs,signals)


def play(config,ready,features,observed=False):
    """
    機能: 原GU両影からの同じ入口へ、一部狭追尾と親組床を追加する。
    引数: config/ready/features(dict)、observed(bool)。
    返り値: tuple[dict,dict] の全台帳と設定。
    """
    columns=features['columns']
    state=np.where(features['gate'],columns[0],0).astype(np.int8)
    normal_settings,settings=base.settings(dict(changes={}),ready)
    scheduler=base.shadow_run(ready,state,normal_settings,np.ones(len(state),bool),observed)
    allow=np.zeros(len(state),bool)
    allow[scheduler['prepare_events'][:,1].astype(int)]=True
    shadow=base.shadow_run(ready,state,settings,allow,observed)
    spec=base.base_spec()
    bad,origin,evidence=base.integration.reference.gate.gate_bad(ready,scheduler,columns[1],columns[2],
        spec['gate_threshold_atr'],mode=spec['gate_mode'],valid=features['valid'])
    args,quiet=old.actual_args(ready,features,settings,observed)
    values=engine.simulate(ready['time_s'],ready['last'],shadow['plans'],shadow['execution_plans'],
        shadow['atr_curve'],bad,origin,*args,config['narrow_fraction'],config['protect_after_narrow'],ready['tick'])
    result=dict(zip(old.FIELDS,values[:18]))
    result.update(partial_events=values[18],partial_curve=values[19],normal_shadow=scheduler,
        shadow=shadow,gate_evidence=evidence,prepare_events=shadow['prepare_events'],
        entry_preparations=shadow['entry_preparations'],time_windows=quiet['windows'],
        reentry_events=np.empty((0,6)),dynamic_events=np.empty((0,7)))
    return result,settings
