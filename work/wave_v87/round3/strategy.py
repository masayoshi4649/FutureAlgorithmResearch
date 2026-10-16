"""個々の追跡極値より後の公開支持だけを次観測の注文許可へ用いる。"""
from pathlib import Path
import importlib.util
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True


def module(name,path):
    """
    機能: 独立名で旧実装と新実装を読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


prior=module('wave86_phase2_strategy',HERE.parents[1]/'wave_v86/phase2/strategy.py')
old=prior.old
base=old.base
previous=old.previous
core=module('wave87_round3_core',HERE/'core.py')
shadow_engine=module('wave87_round3_shadow',HERE/'shadow_engine.py')
engine=module('wave87_round3_engine',HERE/'engine.py')
prepare=module('wave87_round3_prepare',HERE/'prepare.py')
import numba
numba.config.CACHE_DIR=str(HERE/'cache')
SUPPORT_COLUMNS=['内部待機方向','追跡極値行','次観測の公開許可','内部注文線','自己支持終端seq','相手支持終端時刻']


def support_events(curve):
    """
    機能: 待機方向・極値行・許可・線が変わった観測だけを保存する。
    引数: curve(ndarray)。
    返り値: ndarray の原本行＋六列。公開元の詳細は同じ行の保存特徴で追跡できる。
    """
    changed=np.r_[True,np.any(curve[1:,:4]!=curve[:-1,:4],axis=1)]
    active=(curve[:,0]!=0)|np.r_[False,curve[:-1,0]!=0]
    rows=np.flatnonzero(changed&active)
    return np.column_stack((rows,curve[rows]))


def initialize(inputs,signals):
    """
    機能: 元特徴と保存済み公開支持を接続する。
    引数: inputs/signals(dict)。
    返り値: dict。売買状態や損益は参照しない。
    """
    features=prior.initialize(inputs,signals)
    short,_=prepare.load(verify=True)
    for key in features:features[key]['short']=short[key]
    return features


def support_args(config,ready,features):
    """
    機能: 共通判定器へ因果列を所定順に渡す。
    引数: config/ready/features(dict)。
    返り値: tuple。
    """
    short=features['short']
    return (config['support_mode'],ready['seq'],short['self_value'],short['self_valid'],
        short['self_source_seq'],short['peer_value'],short['peer_valid'],short['peer_source_time'])


def shadow(ready,state,settings,allow,observed,features,config):
    """
    機能: GUの独立影へ同じ支持条件を接続する。
    引数: ready/settings/features/config(dict)、state/allow(ndarray)、observed(bool)。
    返り値: dict。
    """
    n=len(state);columns=features['columns']
    par=np.asarray([settings[x] for x in shadow_engine.PARAMS],float)
    values=shadow_engine.simulate(ready['time_s'],ready['last'],ready['atr'],ready['atr'],state,state,
        ready['tick'],ready['start'],ready['limit'],ready['us_open'],par,True,int(settings['audit_cap']),
        0,observed,allow,0.,ready.get('session_close',ready['limit']+600.),columns[1],columns[2],features['valid'],
        False,1.,.5,np.zeros(n,bool),np.zeros(n,bool),np.full(n,-np.inf),*support_args(config,ready,features))
    fields=tuple(base.early.shadow_api.FIELDS)+('dynamic_events','support_curve')
    return dict(zip(fields,values))


def play(config,ready,features,observed=False):
    """
    機能: 同じ支持制御を元GUとT2_P1へ適用して入口・出口依存を分ける。
    引数: config/ready/features(dict)、observed(bool)。
    返り値: tuple[dict,dict]。
    """
    columns=features['columns'];state=np.where(features['gate'],columns[0],0).astype(np.int8)
    normal_settings,settings=base.settings(dict(changes=config['changes']),ready)
    args,quiet=old.actual_args(ready,features,settings,observed)
    if config['parent_id']=='GU':
        scheduler=shadow(ready,state,normal_settings,np.ones(len(state),bool),observed,features,config)
        allow=np.zeros(len(state),bool);allow[scheduler['prepare_events'][:,1].astype(int)]=True
        follow=shadow(ready,state,settings,allow,observed,features,config)
        spec=base.base_spec()
        bad,origin,evidence=base.integration.reference.gate.gate_bad(ready,scheduler,columns[1],columns[2],
            spec['gate_threshold_atr'],mode=spec['gate_mode'],valid=features['valid'])
        values=old.old.engine.simulate(ready['time_s'],ready['last'],follow['plans'],follow['execution_plans'],
            follow['atr_curve'],bad,origin,*args)
        result=dict(zip(old.FIELDS,values))
        result.update(gate_evidence=evidence,reentry_events=np.empty((0,6)),dynamic_events=follow['dynamic_events'])
    else:
        normal_settings=dict(normal_settings,cooldown_min=5.);settings=dict(settings,cooldown_min=5.)
        nspar=np.asarray([normal_settings[x] for x in shadow_engine.PARAMS],float)
        xspar=np.asarray([settings[x] for x in shadow_engine.PARAMS],float)
        values=engine.simulate(ready['time_s'],ready['last'],*args,ready['atr'],state,ready['tick'],
            ready['start'],ready['us_open'],ready.get('session_close',ready['limit']+600.),nspar,xspar,
            columns[1],columns[2],features['valid'],False,1.,.5,60.,True,*support_args(config,ready,features))
        result=dict(zip(old.FIELDS,values[:18]));extra=values[18:]
        scheduler=dict(plans=extra[0],execution_plans=extra[1],prepare_events=extra[2],entry_preparations=extra[3],support_curve=extra[15])
        follow=dict(plans=extra[4],execution_plans=extra[5],prepare_events=extra[6],entry_preparations=extra[7],support_curve=extra[16])
        result.update(dynamic_events=extra[8],reentry_events=extra[9],
            gate_evidence=dict(mfe_atr=extra[10],arm_row=extra[11],armed=extra[12],eligible=extra[13]),profit_reentry_events=extra[14])
    result.update(normal_shadow=scheduler,shadow=follow,prepare_events=follow['prepare_events'],
        entry_preparations=follow['entry_preparations'],time_windows=quiet['windows'],
        normal_support_curve=scheduler['support_curve'],support_curve=follow['support_curve'],
        normal_support_events=support_events(scheduler['support_curve']),support_events=support_events(follow['support_curve']))
    return result,settings
