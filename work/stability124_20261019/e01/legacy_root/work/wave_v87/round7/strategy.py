"""元GUを完全に残し、独立追加の注文と会計だけを合算する。"""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent


def module(name,path):
    """
    機能: 凍結した旧実装と局所会計を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
    return result


old=module('wave85_strategy',HERE.parents[1]/'wave_v85/strategy.py')
fees=module('wave87_multi_fee_account',HERE.parent/'round6/fee_account.py')
previous=SimpleNamespace(VALUES=old.previous.VALUES,FEES=old.previous.FEES,
                        account=fees.account,aggregate=old.previous.aggregate)
base=old.base
engine=module('wave87_round7_engine',HERE/'engine.py')
import numba
numba.config.CACHE_DIR=str(HERE/'cache')


def initialize(inputs,signals):
    """
    機能: 元GUと同じ入力特徴を準備する。
    引数: inputs/signals(dict)。
    返り値: dict。
    """
    return old.initialize(inputs,signals)


def merge(core,satellite,prices):
    """
    機能: 独立に生成した元注文と追加注文を因果順に合算する。
    引数: core(dict)、satellite(tuple)、prices(ndarray)。
    返り値: dict。将来情報を売買判断へ返さない会計段階。
    """
    sat_orders,sat_trades,sat_curve,sat_events,sat_stats=satellite
    result=dict(core)
    result.update(core_result=core,satellite_orders=sat_orders,satellite_trades=sat_trades,
                  satellite_curve=sat_curve,satellite_events=sat_events,satellite_stats=sat_stats,
                  satellite_event_columns=engine.EVENT_COLUMNS)
    if not len(sat_orders):
        return result
    # ----------------------------------------
    # 同一行では前行の追加注文が先、当行のコア約定が後。
    orders=np.concatenate((sat_orders,core['orders']))
    orders=orders[np.argsort(orders[:,0],kind='stable')]
    trades=np.concatenate((sat_trades,core['trades']))
    trades=trades[np.argsort(trades[:,7],kind='stable')]
    curve=core['curve'].copy()
    for column in (0,1,2,3,5,6):curve[:,column]+=sat_curve[:,column]
    curve[:,4]=np.maximum.accumulate(np.maximum.accumulate(np.maximum(curve[:,0],0.))-curve[:,0])
    held=np.zeros(2,int);max_held=np.zeros(2,int);peak_gross=peak_net=0
    parent_held={};parent_max={}
    for order in orders:
        cid=int(order[2]);side=int(order[3]) if order[7] else -int(order[3]);index=0 if side>0 else 1
        delta=int(order[4]) if order[7] else -int(order[4])
        held[index]+=delta;assert held[index]>=0
        max_held=np.maximum(max_held,held)
        peak_gross=max(peak_gross,int(held.sum()));peak_net=max(peak_net,int(abs(held[0]-held[1])))
        if cid not in parent_held:parent_held[cid]=np.zeros(2,int);parent_max[cid]=[0,0]
        parent_held[cid][index]+=delta;assert parent_held[cid][index]>=0
        parent_max[cid][0]=max(parent_max[cid][0],int(parent_held[cid].sum()))
        parent_max[cid][1]=max(parent_max[cid][1],int(abs(parent_held[cid][0]-parent_held[cid][1])))
    cycles=[]
    for original in core['cycles']:
        cid=int(original[0])
        if np.any(parent_held[cid]):continue
        out=original.copy();tt=trades[trades[:,0]==cid]
        out[2]=np.max(tt[:,7]);out[3]=tt[:,10].sum()
        out[6],out[7]=parent_max[cid]
        last=tt[np.flatnonzero(tt[:,7]==out[2])[-1]];out[9]=last[9]
        cycles.append(out)
    stats=core['stats'].copy()
    stats[0]=trades[:,10].sum();stats[1]=curve[:,4].max(initial=0)
    stats[2:4]=max_held;stats[4]=peak_gross;stats[5]=peak_net
    stats[7]=min(0.,curve[:,0].min(initial=0));stats[8]=max(0.,curve[:,0].max(initial=0))
    stats[9]=held.sum()
    result.update(orders=orders,trades=trades,cycles=np.asarray(cycles).reshape(-1,10),curve=curve,stats=stats)
    return result


def play(config,ready,features,observed=False):
    """
    機能: 元GUを変更せず実行し、現在までの約定を独立追加へ渡す。
    引数: config/ready/features(dict)、observed(bool)。
    返り値: tuple[dict,dict]。全玉会計用結果と元設定。
    """
    core,settings=old.play(dict(id='E01_G_U',mask=1,time_mode='U',changes={}),ready,features,observed)
    if not config['relation']:
        result=dict(core)
        result.update(core_result=core,satellite_orders=np.empty((0,8)),satellite_trades=np.empty((0,11)),
            satellite_curve=np.zeros_like(core['curve']),satellite_events=np.empty((0,12)),
            satellite_stats=np.zeros(5),satellite_event_columns=engine.EVENT_COLUMNS)
        return result,settings
    feed=np.zeros((len(core['orders']),9));feed[:,:8]=core['orders']
    for index,order in enumerate(core['orders']):
        if order[7]:
            row=int(order[0])
            feed[index,8]=core['shadow']['execution_plans'][row,24]
            assert feed[index,8]>0 and np.isfinite(feed[index,8])
    quiet=old.time_filter.features(ready,'U')
    satellite=engine.simulate(ready['time_s'],ready['last'],feed,quiet['active'],quiet['force'],
        ready['limit'],settings['entry_cutoff_min'],ready['tick'],config['relation'],
        config['start_atr'],config['stop_atr'],config['activation_atr'],config['trail_atr'],observed)
    result=merge(core,satellite,ready['last'])
    assert result['stats'][2]<=settings['audit_cap'] and result['stats'][3]<=settings['audit_cap']
    return result,settings
