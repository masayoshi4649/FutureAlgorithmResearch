"""既検証の仮想判断を固定し、次観測の実建玉を両建て又は差引で再生する。"""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent


def module(name,path):
    """
    機能: 過去の読取実装と今回の実行層を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
    return result


prior=module('wave87_round8_strategy',HERE.parent/'round8/strategy.py')
source7=prior.prior
old=prior.old
base=prior.base
catalog7=module('wave87_round7_catalog',HERE.parent/'round7/catalog.py')
catalog8=module('wave87_round8_catalog',HERE.parent/'round8/catalog.py')
engine=module('wave87_round10_engine',HERE/'engine.py')
fees=module('wave87_round10_fee_account',HERE/'fee_account.py')
fees.ORIGINAL_ACCOUNT=prior.previous.account
previous=SimpleNamespace(VALUES=fees.VALUES,FEES=fees.FEES,account=fees.account,aggregate=prior.previous.aggregate)
import numba
numba.config.CACHE_DIR=str(HERE/'cache')


def initialize(inputs,signals):
    """
    機能: 元GUと既存の公開支持特徴を読取接続する。
    引数: inputs/signals(dict)。
    返り値: dict。仮想戦略の特徴値を変更しない。
    """
    return prior.initialize(inputs,signals)


def virtual(config,ready,features):
    """
    機能: 指定された既検証戦略を観測約定で忠実再生する。
    引数: config/ready/features(dict)。
    返り値: tuple[dict,dict]。全結果は会計照合専用で、実行層へは当行注文のみ渡す。
    """
    stage=config['source_round'];identifier=config['source_id']
    if stage==85:
        return old.play(dict(id='E01_G_U',mask=1,time_mode='U',changes={}),ready,features,True)
    source=source7 if stage==7 else prior
    catalog=catalog7 if stage==7 else catalog8
    selected=next(c for c in catalog.catalog() if c['id']==identifier)
    return source.play(selected,ready,features,True)


def order_feed(virtual_result):
    """
    機能: 当行の仮想注文へ役割と当行公開済み初回ATRだけを付ける。
    引数: virtual_result(dict)。
    返り値: ndarray[float,10列]。列0〜7は仮想注文、8は役割、9は新規時ATR。
    将来の終了行・組収支・最終極値を参照しない。
    """
    core=virtual_result.get('core_result',virtual_result)
    hedge=virtual_result.get('satellite_orders',np.empty((0,8)))
    first=np.zeros((len(hedge),10));first[:,:8]=hedge;first[:,8]=1
    second=np.zeros((len(core['orders']),10));second[:,:8]=core['orders']
    for index,order in enumerate(core['orders']):
        if order[7]:
            row=int(order[0]);second[index,9]=core['shadow']['execution_plans'][row,24]
            assert second[index,9]>0 and np.isfinite(second[index,9])
    feed=np.concatenate((first,second));feed=feed[np.argsort(feed[:,0],kind='stable')]
    np.testing.assert_array_equal(feed[:,:8],virtual_result['orders'])
    return feed


def play(config,ready,features,observed=True):
    """
    機能: 仮想の当行情報を次観測実行層へ渡し、実注文と仮想対照を分けて返す。
    引数: config/ready/features(dict)、observed(bool、Trueだけを許可)。
    返り値: tuple[dict,dict]。実注文・実会計素材・仮想原結果・元GU原結果・設定。
    """
    assert observed,'第十段階は観測現在値約定だけを比較する'
    virtual_result,settings=virtual(config,ready,features)
    core=virtual_result.get('core_result',virtual_result)
    if config['execution_mode']=='IDEAL':
        result=dict(virtual_result)
        result.update(virtual_result=virtual_result,core_result=core,
            execution_events=np.empty((0,12)),execution_states=np.empty((0,10)),
            execution_event_columns=engine.EVENT_COLUMNS,execution_state_columns=engine.STATE_COLUMNS)
        return result,settings
    feed=order_feed(virtual_result)
    quiet=old.time_filter.features(ready,'U')
    mode={'G':0,'N':1,'F':2}[config['execution_mode']]
    values=engine.simulate(ready['time_s'],ready['last'],feed,quiet['active'],quiet['force'],
        ready['limit'],mode,int(settings['audit_cap']))
    names=('orders','trades','curve','stats','cycles','order_uids','execution_events','execution_states')
    result=dict(zip(names,values))
    result.update(virtual_result=virtual_result,core_result=core,virtual_feed=feed,
        execution_event_columns=engine.EVENT_COLUMNS,execution_state_columns=engine.STATE_COLUMNS,
        guard_events=np.empty((0,7)),time_events=np.empty((0,7)),time_windows=core.get('time_windows',[]))
    return result,settings
