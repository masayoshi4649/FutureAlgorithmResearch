"""自己元GUを保ち、有利指値の成立可否だけを実行層で変える。"""
from pathlib import Path
import importlib.util
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent


def module(name,path):
    """
    機能: 読取実装と今回の実行層を固有名で読む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


prior=module('wave87_round10_strategy',HERE.parent/'round10/strategy.py')
old=prior.old;base=prior.base;previous=prior.previous
engine=module('wave87_round12_engine',HERE/'engine.py')
import numba
numba.config.CACHE_DIR=str(HERE/'cache')


def initialize(inputs,signals):
    """
    機能: 自己の元GU特徴だけを用意する。
    引数: inputs/signals(dict)。
    返り値: dict。実玉損益による特徴や相手改修口座を加えない。
    """
    return old.initialize(inputs,signals)


def virtual(config,ready,features):
    """
    機能: 無変更の自己GUを観測価格で再生する。
    引数: config/ready/features(dict)。
    返り値: tuple[dict,dict]。
    """
    return old.play(dict(id='E01_G_U',mask=1,time_mode='U',changes={}),ready,features,True)


def play(config,ready,features,observed=True):
    """
    機能: 当行までに分かった紙上新規から有利指値を置き、元返済を次観測へコピーする。
    引数: config/ready/features(dict)、observed(bool、Trueのみ)。
    返り値: tuple[dict,dict]。元仮想全結果と実行証跡を別々に保持する。
    """
    assert observed,'第十二段階は観測現在値での約定だけを比較する'
    core,settings=virtual(config,ready,features)
    if config['execution_mode']=='IDEAL':
        result=dict(core)
        result.update(core_result=core,virtual_result=core,execution_events=np.empty((0,12)),
            execution_states=np.empty((0,10)),limit_events=np.empty((0,18)),
            execution_event_columns=engine.EVENT_COLUMNS,execution_state_columns=engine.STATE_COLUMNS,limit_event_columns=engine.LIMIT_COLUMNS)
        return result,settings
    feed=prior.order_feed(core);quiet=old.time_filter.features(ready,'U')
    values=engine.simulate(ready['time_s'],ready['last'],feed,quiet['active'],quiet['force'],ready['limit'],
        int(settings['audit_cap']),float(ready['tick']),float(config['offset_atr']),config['execution_mode']=='NEXT')
    names=('orders','trades','curve','stats','cycles','order_uids','execution_events','execution_states','limit_events')
    result=dict(zip(names,values))
    result.update(core_result=core,virtual_result=core,virtual_feed=feed,
        execution_event_columns=engine.EVENT_COLUMNS,execution_state_columns=engine.STATE_COLUMNS,limit_event_columns=engine.LIMIT_COLUMNS,
        guard_events=np.empty((0,7)),time_events=np.empty((0,7)),time_windows=core.get('time_windows',[]))
    return result,settings
