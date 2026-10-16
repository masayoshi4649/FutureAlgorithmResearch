"""相手の無変更GUを観測する入口・途中判断を、自己の元GUへ接続する。"""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent


def module(name,path):
    """
    機能: 読取実装と今回の部品を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
    return result


prior=module('wave87_round10_strategy',HERE.parent/'round10/strategy.py')
old=prior.old;base=prior.base;previous=prior.previous
prepare=module('wave87_round11_prepare',HERE/'prepare.py')
engine=module('wave87_round11_engine',HERE/'engine.py')
import numba
numba.config.CACHE_DIR=str(HERE/'cache')


def initialize(inputs,signals):
    """
    機能: 元GU特徴へ相手の無変更注文と厳密過去参照行を付ける。
    引数: inputs/signals(dict)。
    返り値: dict。相手改修口座や将来親組成績を使用しない。
    """
    features=old.initialize(inputs,signals);peers=prepare.build(inputs)
    for key in features:features[key]['peer']=peers[key]
    return features


def virtual(config,ready,features):
    """
    機能: 自己の無変更GUを再生する。
    引数: config/ready/features(dict)。
    返り値: tuple[dict,dict]。
    """
    return old.play(dict(id='E01_G_U',mask=1,time_mode='U',changes={}),ready,features,True)


def play(config,ready,features,observed=True):
    """
    機能: 元GUの当行結果と相手当時状態から、次観測の実目標を作る。
    引数: config/ready/features(dict)、observed(bool、Trueのみ)。
    返り値: tuple[dict,dict]。元仮想全結果は会計確認用に別保持する。
    """
    assert observed,'第十一段階は観測現在値約定だけを比較する'
    core,settings=virtual(config,ready,features)
    if config['execution_mode']=='IDEAL':
        result=dict(core)
        result.update(core_result=core,virtual_result=core,execution_events=np.empty((0,12)),
            execution_states=np.empty((0,10)),peer_events=np.empty((0,21)),
            execution_event_columns=engine.EVENT_COLUMNS,execution_state_columns=engine.STATE_COLUMNS,
            peer_event_columns=engine.PEER_COLUMNS)
        return result,settings
    feed=prior.order_feed(core);quiet=old.time_filter.features(ready,'U');peer=features['peer']
    values=engine.simulate(ready['time_s'],ready['last'],feed,quiet['active'],quiet['force'],ready['limit'],
        int(config['entry_mode']),int(config['holding_mode']),int(settings['audit_cap']),
        peer['time_s'],peer['last'],peer['feed'],peer['ref'],peer['value'],peer['fee'])
    names=('orders','trades','curve','stats','cycles','order_uids','execution_events','execution_states','peer_events')
    result=dict(zip(names,values))
    result.update(core_result=core,virtual_result=core,virtual_feed=feed,
        execution_event_columns=engine.EVENT_COLUMNS,execution_state_columns=engine.STATE_COLUMNS,peer_event_columns=engine.PEER_COLUMNS,
        guard_events=np.empty((0,7)),time_events=np.empty((0,7)),time_windows=core.get('time_windows',[]))
    return result,settings
