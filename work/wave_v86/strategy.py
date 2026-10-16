"""E01_G_Uの入口と通常影MFEを維持し、出口と実返済時計だけ比較する。"""
from pathlib import Path
import importlib.util
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.dont_write_bytecode=True


def module(name,path):
    """
    機能: 旧成果を変更せず独立名で再生実装を読み込む。
    引数: name(str)、path(Path)。
    返り値: module の実装。
    """
    if name in sys.modules: return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value
    spec.loader.exec_module(value)
    return value


old=module('wave85_strategy',ROOT/'work/wave_v85/strategy.py')
import numba
numba.config.CACHE_DIR=str(HERE/'cache')
previous=old.previous
base=old.base
shadow_engine=module('wave86_shadow',HERE/'shadow_engine.py')
engine=module('wave86_engine',HERE/'engine.py')
FIELDS=old.engine.FIELDS+('control_curve','slot_curve','slot_events','adjustment_events',
    'budget_events','branch_events','branch_curve','risk_events','guard_curve','guard_events','block_events','time_events')
SHADOW_FIELDS=tuple(base.early.shadow_api.FIELDS)+('dynamic_events',)
REENTRY_COLUMNS=['実返済行','反映行','次準備可能時刻','実組','通常影組','出口影組']
DYNAMIC_COLUMNS=['判断行','出口影組','B00元行','保有方向','最大順行ATR倍','旧幅ATR倍','新幅ATR倍']


def initialize(inputs,signals):
    """
    機能: 原E01と同じ公開済み入口・EMA・B00特徴を生成する。
    引数: inputs/signals(dict)。
    返り値: dict[tuple,dict] の口座別特徴。
    """
    return old.initialize(inputs,signals)


def shadow_run(ready,state,settings,allow,observed,features,config):
    """
    機能: 通常影の新準備行だけで改修出口影を再生する。
    引数: ready/settings/features/config(dict)、state/allow(ndarray)、observed(bool)。
    返り値: dict の出口影台帳と短縮証跡。
    """
    n=len(state)
    columns=features['columns']
    par=np.asarray([settings[x] for x in shadow_engine.PARAMS],float)
    values=shadow_engine.simulate(ready['time_s'],ready['last'],ready['atr'],ready['atr'],state,state,
        ready['tick'],ready['start'],ready['limit'],ready['us_open'],par,True,int(settings['audit_cap']),
        0,observed,allow,0.,ready.get('session_close',ready['limit']+600.),
        columns[1],columns[2],features['valid'],config['dynamic_trail'],
        config['dynamic_activation_atr'],config['dynamic_width_atr'],np.zeros(n,bool),
        np.zeros(n,bool),np.full(n,-np.inf))
    return dict(zip(SHADOW_FIELDS,values))


def actual_args(ready,features,settings,observed):
    """
    機能: 旧実玉会計で必要な、今回変更しない途中管理と時間窓を用意する。
    引数: ready/features/settings(dict)、observed(bool)。
    返り値: tuple[tuple,dict] の引数と時間窓。
    """
    n=len(ready['last'])
    zero=np.zeros(n,np.int8);source=np.full(n,-1,np.int64);invalid=np.zeros(n,bool)
    spec=base.base_spec();policy=spec['policy'];columns=features['columns']
    losspar=np.concatenate((old.legacy.control_parameters({},ready['symbol']),np.asarray([False,1.5,.5,False],float)))
    joint=features['joint'];ema=features['ema']
    quiet=old.time_filter.features(ready,'U')
    args=(columns[3],columns[4],columns[5],ready['limit'],settings['entry_cutoff_min'],
        int(settings['initial_qty']),int(settings['audit_cap']),3,policy['reduce_fraction'],0,
        int(policy['max_reductions']),120.,observed,True,True,0.,zero,source,invalid,zero,0,-1,
        losspar,joint['direction'],joint['source'],joint['valid'],ema[0],ema[1],ema[2],ema[3],
        quiet['active'],quiet['force'],quiet['not_before'])
    return args,quiet


def play(config,ready,features,observed=False):
    """
    機能: 共通入口のまま出口と再準備時計を変更し、旧会計と同じ形式で返す。
    引数: config/ready/features(dict)、observed(bool)。
    返り値: tuple[dict,dict] の全台帳・監査証跡と設定。
    """
    if config['id']=='E01_G_U':
        return old.play(dict(id='E01_G_U',mask=1,time_mode='U'),ready,features,observed)
    columns=features['columns'];valid=features['valid']
    state=np.where(features['gate'],columns[0],0).astype(np.int8)
    normal_settings,settings=base.settings(dict(changes=config['changes']),ready)
    args,quiet=actual_args(ready,features,settings,observed)
    n=len(state)
    if config['reentry_mode']=='shadow':
        scheduler=base.shadow_run(ready,state,normal_settings,np.ones(n,bool),observed)
        allow=np.zeros(n,bool)
        allow[scheduler['prepare_events'][:,1].astype(int)]=True
        shadow=shadow_run(ready,state,settings,allow,observed,features,config)
        spec=base.base_spec()
        bad,origin,evidence=base.integration.reference.gate.gate_bad(ready,scheduler,columns[1],columns[2],
            spec['gate_threshold_atr'],mode=spec['gate_mode'],valid=valid)
        values=old.engine.simulate(ready['time_s'],ready['last'],shadow['plans'],shadow['execution_plans'],
            shadow['atr_curve'],bad,origin,*args)
        result=dict(zip(FIELDS,values))
        result['normal_shadow']=scheduler
        result['gate_evidence']=evidence
        result['reentry_events']=np.empty((0,6))
        result['dynamic_events']=shadow['dynamic_events']
    else:
        normal_settings=dict(normal_settings,cooldown_min=config['cooldown_seconds']/60.)
        settings=dict(settings,cooldown_min=config['cooldown_seconds']/60.)
        np_=np.asarray([normal_settings[x] for x in shadow_engine.PARAMS],float)
        xp_=np.asarray([settings[x] for x in shadow_engine.PARAMS],float)
        values=engine.simulate(ready['time_s'],ready['last'],*args,ready['atr'],state,ready['tick'],
            ready['start'],ready['us_open'],ready.get('session_close',ready['limit']+600.),np_,xp_,
            columns[1],columns[2],valid,config['dynamic_trail'],config['dynamic_activation_atr'],
            config['dynamic_width_atr'],config['cooldown_seconds'])
        result=dict(zip(FIELDS,values[:18]))
        extra=values[18:]
        scheduler=dict(plans=extra[0],execution_plans=extra[1],prepare_events=extra[2],entry_preparations=extra[3])
        shadow=dict(plans=extra[4],execution_plans=extra[5],prepare_events=extra[6],entry_preparations=extra[7])
        result['normal_shadow']=scheduler
        result['dynamic_events']=extra[8]
        result['reentry_events']=extra[9]
        result['gate_evidence']=dict(mfe_atr=extra[10],arm_row=extra[11],armed=extra[12],eligible=extra[13])
    result['prepare_events']=shadow['prepare_events']
    result['entry_preparations']=shadow['entry_preparations']
    result['shadow']=shadow
    result['time_windows']=quiet['windows']
    return result,settings
