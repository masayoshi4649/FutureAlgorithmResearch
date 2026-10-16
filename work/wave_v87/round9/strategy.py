"""元玉と保険入口を固定し、初期停止基準の違いだけを比較する。"""
from pathlib import Path
import importlib.util
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent


def module(name,path):
    """
    機能: 凍結した読取実装と新しい独立保険を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
    return result


prior=module('wave87_round7_strategy',HERE.parent/'round7/strategy.py')
old=prior.old
previous=prior.previous
base=prior.base
engine=module('wave87_round9_engine',HERE/'engine.py')
prepare=module('wave87_round9_prepare',HERE/'prepare.py')
import numba
numba.config.CACHE_DIR=str(HERE/'cache')

INSURANCE_COLUMNS=['実新規行','組','予約行','最終許可行','順行極値','極値行','予約線',
    '自己支持','相手支持','自己有効','相手有効','自己終端原本行','相手終端原本行',
    '自己終端時計','相手終端時計','自己公開原本行','相手公開原本行','自己公開時計','相手公開時計']
STRUCTURE_COLUMNS=['新規行','組','停止方式','極値元行','過去極値','建値基準線','実初期線','実建値','保険方向','保険枚数','固定ATR','新規当行で初期線破断済み']
SHORT_FIELDS=['self_value','peer_value','self_valid','peer_valid','self_source_seq','peer_source_seq',
    'self_source_time','peer_source_time','self_release_seq','peer_release_seq','self_release_time','peer_release_time']


def initialize(inputs,signals):
    """
    機能: 元GUの特徴へ、検算済みの最新公開支持を参照接続する。
    引数: inputs/signals(dict)。
    返り値: dict。値の再正規化・将来への補間を行わない。
    """
    features=old.initialize(inputs,signals)
    short,_=prepare.load(verify=True)
    for key,feature in features.items():
        feature['short']=short[key]
        assert len(short[key]['self_value'])==len(inputs[key]['time_s'])
    return features


def play(config,ready,features,observed=False):
    """
    機能: 元GUの当行までの実約定を保険へ送り、全玉会計を合算する。
    引数: config/ready/features(dict)、observed(bool)。
    返り値: tuple[dict,dict]。元玉と保険の明細・公開根拠、および元設定。
    """
    core,settings=old.play(dict(id='E01_G_U',mask=1,time_mode='U',changes={}),ready,features,observed)
    if not config['relation']:
        result=dict(core)
        result.update(core_result=core,satellite_orders=np.empty((0,8)),satellite_trades=np.empty((0,11)),
            satellite_curve=np.zeros_like(core['curve']),satellite_events=np.empty((0,12)),
            satellite_stats=np.zeros(5),satellite_event_columns=engine.EVENT_COLUMNS,
            insurance_events=np.empty((0,len(INSURANCE_COLUMNS))),insurance_event_columns=INSURANCE_COLUMNS,
            structure_events=np.empty((0,len(STRUCTURE_COLUMNS))),structure_event_columns=STRUCTURE_COLUMNS)
        return result,settings
    # ----------------------------------------
    # 親組の将来の終了行・全組損益は渡さず、実約定順の注文と当時のATRだけを接続する。
    feed=np.zeros((len(core['orders']),9));feed[:,:8]=core['orders']
    for index,order in enumerate(core['orders']):
        if order[7]:
            row=int(order[0]);feed[index,8]=core['shadow']['execution_plans'][row,24]
            assert feed[index,8]>0 and np.isfinite(feed[index,8])
    quiet=old.time_filter.features(ready,'U');short=features['short']
    satellite=engine.simulate(ready['time_s'],ready['last'],feed,quiet['active'],quiet['force'],
        ready['limit'],settings['entry_cutoff_min'],ready['tick'],config['relation'],
        config['start_atr'],config['stop_atr'],config['activation_atr'],config['trail_atr'],observed,
        config['prepare_atr'],config['pullback_atr'],config['confirm'],ready['seq'],
        short['self_value'],short['self_valid'],short['peer_value'],short['peer_valid'],
        short['self_release_seq'],short['peer_release_time'],config['stop_mode'])
    result=prior.merge(core,satellite[:5],ready['last'])
    # ----------------------------------------
    # 最後の許可行の根拠を記録する。約定当行の新しい支持を過去の許可へ混ぜない。
    entries=satellite[5]
    proof=np.empty((len(entries),len(INSURANCE_COLUMNS)))
    proof[:,:7]=entries
    permission=entries[:,3].astype(np.int64)
    for column,name in enumerate(SHORT_FIELDS,7):proof[:,column]=short[name][permission]
    if len(entries):
        assert np.all(permission<entries[:,0])
        if config['confirm']:
            assert np.all(short['self_valid'][permission]) and np.all(short['peer_valid'][permission])
            assert np.all(short['self_release_seq'][permission]<=ready['seq'][permission])
            assert np.all(short['peer_release_time'][permission]<ready['time_s'][permission])
    structural=[]
    for event in satellite[3]:
        if int(event[2])!=2:continue
        row=int(event[0]);cid=int(event[1]);side=int(event[4]);qty=int(event[5]);entry=event[6];atr=event[8]
        child=satellite[3][(satellite[3][:,0]==row)&(satellite[3][:,1]==cid)&(satellite[3][:,2]==3)&(satellite[3][:,9]==81)]
        root=entries[(entries[:,0]==row)&(entries[:,1]==cid)]
        assert len(child)==1 and len(root)==1 and root[0,5]<row
        old_line=engine.rounded(entry-side*max(ready['tick'],config['stop_atr']*atr),ready['tick'],-side)
        line=child[0,6];broken=-side*(ready['last'][row]-line)>=-1e-9
        structural.append([row,cid,config['stop_mode'],root[0,5],root[0,4],old_line,line,entry,side,qty,atr,int(broken)])
    result.update(insurance_events=proof,insurance_event_columns=INSURANCE_COLUMNS,
        structure_events=np.asarray(structural).reshape(-1,len(STRUCTURE_COLUMNS)),structure_event_columns=STRUCTURE_COLUMNS)
    assert result['stats'][2]<=settings['audit_cap'] and result['stats'][3]<=settings['audit_cap']
    return result,settings
