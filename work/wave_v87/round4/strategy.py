"""元GUの入口・両影を固定し、実玉の数量だけを条件付きで増やす。"""
from pathlib import Path
import importlib.util
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent


def module(name,path):
    """
    機能: 固定済み又は新しい実装を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules: return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
    return result


old=module('wave86_strategy',HERE.parents[1]/'wave_v86/strategy.py')
base=old.base
previous=old.previous
engine=module('wave87_round4_engine',HERE/'engine.py')
import numba
numba.config.CACHE_DIR=str(HERE/'cache')
ALLOCATION_COLUMNS=['行','組','種別','根拠行','方向','枚数','線又は約定価格','累計使用枠','初回枚数','予算価格単位','既払料金価格単位','見込料金価格単位','床種類又は理由','次段番号']
ALLOCATION_EVENTS={1:'追加予約',2:'追加約定',3:'床更新',4:'床全返済',5:'追加取消',6:'追加停止'}


def initialize(inputs,signals):
    """
    機能: 元GUと同じ公開済み特徴だけを生成する。
    引数: inputs/signals(dict)。
    返り値: dict。
    """
    return old.initialize(inputs,signals)


def play(config,ready,features,observed=False):
    """
    機能: 固定した元GU両影の計画へ、実数量配分と追加後の床を接続する。
    引数: config/ready/features(dict)、observed(bool)。
    返り値: tuple[dict,dict]。旧会計互換の結果と実初回枚数を含む設定。
    """
    columns=features['columns']
    state=np.where(features['gate'],columns[0],0).astype(np.int8)
    normal_settings,settings=base.settings(dict(changes={}),ready)
    scheduler=base.shadow_run(ready,state,normal_settings,np.ones(len(state),bool),observed)
    allow=np.zeros(len(state),bool);allow[scheduler['prepare_events'][:,1].astype(int)]=True
    shadow=base.shadow_run(ready,state,settings,allow,observed)
    spec=base.base_spec()
    bad,origin,evidence=base.integration.reference.gate.gate_bad(ready,scheduler,columns[1],columns[2],
        spec['gate_threshold_atr'],mode=spec['gate_mode'],valid=features['valid'])
    args,quiet=old.actual_args(ready,features,settings,observed)
    initial=config['initial_top']*(1 if ready['symbol']=='TOPIX' else 2)
    values=engine.simulate(ready['time_s'],ready['last'],shadow['plans'],shadow['execution_plans'],
        shadow['atr_curve'],bad,origin,*args,initial,config['add_mode'],config['add_step'],config['floor_mode'],ready['tick'])
    result=dict(zip(old.FIELDS,values[:18]))
    result.update(allocation_events=values[18],allocation_curve=values[19],normal_shadow=scheduler,
        shadow=shadow,gate_evidence=evidence,prepare_events=shadow['prepare_events'],
        entry_preparations=shadow['entry_preparations'],time_windows=quiet['windows'],
        reentry_events=np.empty((0,6)),dynamic_events=np.empty((0,7)))
    return result,dict(settings,initial_qty=initial)
