"""根の正式固定・登録後に、二cache各一読から九条件の全後続を一回だけ運転する。"""

import argparse
from collections import Counter
import gc
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import pickle
import sys
import time
import traceback

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ENGINE = HERE.parent/'engine'
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(ENGINE))
import common
import catalog
import interface
import financial_metrics
from numba.core.registry import CPUDispatcher

for module in (common,catalog,interface,interface.core,interface.signals,interface.daily,interface.input_contract,interface.price_features,interface.flows,interface.bars):
    assert Path(module.__file__).resolve().parent==ENGINE
    for compiled in vars(module).values():
        if isinstance(compiled,CPUDispatcher):
            assert Path(compiled._cache._impl._locator._cache_path).resolve().is_relative_to(ENGINE/'jit')

spec = __import__('importlib.util',fromlist=['spec_from_file_location']).spec_from_file_location('現在参加の根固定',HERE/'plan.py')
root_plan = __import__('importlib.util',fromlist=['module_from_spec']).module_from_spec(spec)
spec.loader.exec_module(root_plan)

OUT = HERE/'finance'
REGISTRY = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json'
EXPECTED = Counter(TradeGatecache=33,TradeExitcache=33,現在特徴商品=66,新金融口座=594)


def finite(value: object) -> object:
    """
    機能: 保存の原始型をそろえ、未知数をNoneとして非有限JSONを防ぐ。
    引数: value(object) は会計・診断・NumPy値の入れ子。
    返り値: object はJSON可能値。未知を零や既知へ補完しない。
    """
    if isinstance(value,dict):
        return {str(k):finite(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):
        return [finite(v) for v in value]
    if isinstance(value,np.ndarray):
        return finite(value.tolist())
    if isinstance(value,(bool,np.bool_)):
        return bool(value)
    if isinstance(value,(int,np.integer)):
        return int(value)
    if isinstance(value,(float,np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if value is None or isinstance(value,str):
        return value
    raise TypeError(type(value).__name__)


def write(path: Path, value: dict) -> None:
    """
    機能: 既存の成功又はFalseを上書きせず証跡を保存する。
    引数: path(Path)、value(dict) は所有域の新保存先と内容。
    返り値: None。保存先は今回の私有領域に限定する。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(finite(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def load_cache(meta: dict) -> dict:
    """
    機能: 固定したcacheの同bytes一読からSHA検算とgzip復元を行う。
    引数: meta(dict) はpath/SHA256/stat_bytesの固定目録。
    返り値: dict は保存packet。不一致時に他の入力へ差し替えない。
    """
    path=ROOT/meta['path']
    raw=path.read_bytes()
    assert len(raw)==meta['stat_bytes']
    assert hashlib.sha256(raw).hexdigest()==meta['SHA256']
    with gzip.GzipFile(fileobj=io.BytesIO(raw),mode='rb') as stream:
        packet=pickle.load(stream)
    assert isinstance(packet,dict)
    return packet


def packed(values: np.ndarray) -> dict:
    """
    機能: 全normalの階段状会計曲線を同値に復元できる区間へ圧縮する。
    引数: values(ndarray) は一又は二次元の元曲線。
    返り値: dict はshape/dtype/rows/values。失敗すれば元台帳を偽造しない。
    """
    assert values.ndim in (1,2) and len(values)>0
    a=values.reshape(len(values),-1)
    changed=np.any((a[1:]!=a[:-1])&~(np.isnan(a[1:])&np.isnan(a[:-1])),axis=1)
    rows=np.r_[0,np.flatnonzero(changed)+1].astype(np.int64)
    kept=values[rows].copy()
    np.testing.assert_array_equal(values,kept[np.searchsorted(rows,np.arange(len(values)),side='right')-1])
    return dict(type='plateau',shape=list(values.shape),dtype=values.dtype.str,rows=rows,values=kept)


def snapshots(account: dict, features: dict, output: dict) -> list[dict]:
    """
    機能: 判断・約定の原行と当時BBOを、小さな実台帳診断へ残す。
    引数: account/features/output(dict) は同場入力と当該実運転。
    返り値: list[dict] は原row/seq/価格時計/Last/BBO。未来ラベルを発注へ渡さない。
    """
    r,q=account['record'],account['quotes']
    rows=set()
    for order in output['orders']:
        rows.update((int(order[0]),int(order[1])))
    for name in ('publication_events','support_events','exit_judgments','execution_events'):
        value=output.get(name)
        if isinstance(value,np.ndarray) and value.ndim==2 and value.shape[1]>0:
            rows.update(int(v) for v in value[:,0] if np.isfinite(v) and int(v)==v)
            extra=(14,15,18) if name=='publication_events' else (5,9) if name=='support_events' else ()
            for column in extra:
                rows.update(int(v) for v in value[:,column] if np.isfinite(v) and int(v)==v and v>=0)
    origins=output.get('actual_origins')
    if isinstance(origins,np.ndarray) and origins.ndim==2 and origins.shape[1]>=4:
        rows.update(int(v) for v in origins[:,2:4].reshape(-1) if np.isfinite(v) and int(v)==v)
    result=[]
    for row in sorted(rows):
        assert 0<=row<len(r['price'])
        volume=features['volume'];price=features['price'];flow=features['flow'];bar=features['bar']
        known=bool(volume['known'][row])
        result.append(dict(row=row,raw_row=int(account['mapping'][row]),raw_seq=int(r['seq'][row]),price_time_s=float(r['time_s'][row]),
            last=float(r['price'][row]),bid=float(q['bid'][row]),ask=float(q['ask'][row]),quote_valid=bool(q['quote_valid'][row]),
            volume_known=known,volume_reason=int(volume['reason'][row]),
            volume_up=int(volume['up_votes'][row]) if known else None,volume_down=int(volume['down_votes'][row]) if known else None,
            volume_balance=float(volume['balance'][row]) if known else None,
            volume_window_first_raw_row=int(volume['first_vote_raw_row'][row]),volume_reference_raw_row=int(volume['reference_raw_row'][row]),
            own_price_known=bool(price['own']['known'][row]),own_price_count=int(price['own']['count'][row]),own_price_balance=float(price['own']['balance'][row]),
            peer_price_known=bool(price['peer_known'][row]),peer_price_count=int(price['peer_count'][row]),peer_price_balance=float(price['peer_balance'][row]),
            peer_row=int(price['peer_row'][row]),peer_raw_seq=int(price['peer_raw_seq'][row]),peer_age=float(price['peer_price_age_seconds'][row]),
            interval_known=bool(flow['interval_known'][row]),new_up_lower=int(flow['new_up_lower'][row]),new_down_lower=int(flow['new_down_lower'][row]),
            previous_bar_high=float(bar['high'][row]),previous_bar_low=float(bar['low'][row]),bar_confirmed_row=int(bar['confirmed_row'][row])))
    return result


def save_ledger(config: dict, session: str, symbol: str, account: dict, features: dict, output: dict) -> dict:
    """
    機能: 実注文・UID・親・支持線事象と清算会計を一次台帳として保存する。
    引数: config/account/features/output(dict)、session/symbol(str) は同経済の実運転。
    返り値: dict は台帳相対path/SHA256。旧台帳をコピーした新金融ではない。
    """
    fields=('orders','order_uids','exit_target_uids','summary','parent','actual_legs','uid_accounts',
            'publication_events','support_events','exit_judgments','execution_events','actual_origins','parent_diagnostics')
    saved={key:output[key] for key in fields if key in output}
    saved['session']=session
    saved['symbol']=symbol
    saved['config']=config
    saved['snapshots']=snapshots(account,features,output)
    for key in ('equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty','cumulative_fees'):
        if key in output:
            saved[key]=packed(output[key])
    path=OUT/'ledgers'/config['id']/(session+'_'+symbol+'.pkl.gz')
    assert not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    stream=io.BytesIO()
    with gzip.GzipFile(fileobj=stream,mode='wb',mtime=0) as target:
        pickle.dump(saved,target,protocol=5)
    raw=stream.getvalue()
    path.write_bytes(raw)
    return dict(session=session,symbol=symbol,path=path.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(raw).hexdigest())


def guard(fixed: dict, proposal: dict) -> None:
    """
    機能: 登録済み八部品・全source・九条件・必要小目録を大型入力前に照合する。
    引数: fixed/proposal(dict) は根の正式条件。
    返り値: None。不一致や未登録なら金融を開始しない。
    """
    assert fixed['全合格'] and fixed['正式freeze'] and proposal['正式freeze']
    assert proposal['id']==catalog.TRIAL_ID
    assert fixed['configs']==catalog.configs()==proposal['spec']['entry']['conditions']
    assert fixed['sessions']==proposal['spec']['data']['sessions']
    assert fixed['inputs']==proposal['spec']['data']['inputs']
    assert len(fixed['sessions'])==len(set(fixed['sessions']))==len(fixed['inputs'])==33
    assert set(fixed['sessions'])==set(fixed['inputs'])
    assert fixed['case_SHA256']==root_plan.case_hashes(catalog.configs())
    assert fixed['source_SHA256']==root_plan.sources()==proposal['spec']['implementation']
    assert fixed['計画SHA256']==root_plan.sha(HERE/'試行計画.json')
    found=[p for p in root_plan.read(REGISTRY)['trials'] if p['id']==catalog.TRIAL_ID]
    assert len(found)==1 and found[0]['spec']==proposal['spec']
    for item in proposal['spec']['data']['input_manifests']:
        assert root_plan.sha(ROOT/item['path'])==item['sha256']
    assert not OUT.exists() and not (HERE/'金融前False.json').exists()


def run() -> None:
    """
    機能: 登録後の一回運転で九条件×二商品×33場を保存し、保存基準と分離する。
    引数: なし。
    返り値: None。自動再試行や新2場・現在APIの読取は行わない。
    """
    fixed=root_plan.read(HERE/'金融事前固定.json')
    proposal=root_plan.read(HERE/'試行計画.json')
    guard(fixed,proposal)
    source=root_plan.sources()
    configs=fixed['configs']
    rows={c['id']:[] for c in configs}
    parents={cid:[] for cid in rows}
    profiles={cid:[] for cid in rows}
    ledgers={cid:[] for cid in rows}
    activity={cid:[] for cid in rows}
    counts=Counter()
    started=time.monotonic()
    write(OUT/'開始.json',dict(正式一回=True,source_SHA256=source,case_SHA256=fixed['case_SHA256'],予定=dict(EXPECTED)))
    try:
        for session in fixed['sessions']:
            counts['TradeGatecache']+=1
            gate=load_cache(fixed['inputs'][session]['TradeGate'])
            counts['TradeExitcache']+=1
            exit_packet=load_cache(fixed['inputs'][session]['TradeExit'])
            assert gate['session']==exit_packet['session']==session
            features=interface.prepare(gate,exit_packet)
            counts['現在特徴商品']+=2
            for symbol in catalog.CAP:
                account=gate['accounts'][symbol]
                for config in configs:
                    cid=config['id']
                    counts['新金融口座']+=1
                    output=interface.play(account,features[symbol],config,session)
                    assert output['summary']['全会計合格']
                    assert not np.any(np.isin(output['orders'][:,6],(151,152)))
                    rows[cid].append(output['summary'])
                    parents[cid].extend(dict(session=session,symbol=symbol,**p) for p in output['parent'])
                    diagnostics=output.get('parent_diagnostics',[])
                    assert isinstance(diagnostics,list)
                    profiles[cid].extend(dict(session=session,symbol=symbol,**p) for p in diagnostics)
                    pub=output.get('publication_events',np.empty((0,0)))
                    support=output.get('support_events',np.empty((0,0)))
                    activity[cid].append(dict(session=session,symbol=symbol,公開候補=len(pub),支持線事象=len(support),
                                              実親=len(output['parent']),注文件数=len(output['orders'])))
                    ledgers[cid].append(save_ledger(config,session,symbol,account,features[symbol],output))
                    del output
            del gate,exit_packet,features
            gc.collect()
            print(session+' 九新条件の場内会計と台帳保存完了',flush=True)
        assert counts==EXPECTED
        assert source==root_plan.sources()==fixed['source_SHA256']
        results={}
        for config in configs:
            cid=config['id']
            results[cid]=dict(config=config,rows=rows[cid],parents=parents[cid],parent_diagnostics=profiles[cid],
                activity=activity[cid],ledgers=ledgers[cid],
                periods={s:financial_metrics.periods(rows[cid],parents[cid],fixed['sessions'],s) for s in catalog.CAP})
        meta=root_plan.read(HERE/'旧三十三場の入力と保存基準の一読目録.json')
        baseline=meta['保存比較']['cases']['E01_EVID_VOL_SELECTED_TARGET']
        assert len(baseline['rows'])==66
        write(OUT/'結果.json',dict(全合格=True,sessions=fixed['sessions'],configs=configs,results=results,
            保存基準=dict(id='E01_EVID_VOL_SELECTED_TARGET',case=baseline,再金融=0,
                          出典=meta['出典'][1],差='入口母集団/紙上退出/支持線ほか複数差分の参考'),
            counts=dict(counts),新金融口座=594,基準保存会計=66,掲載比較=10,
            source_SHA256=source,case_SHA256=fixed['case_SHA256'],source開始終端一致=True,
            原板=0,NPZ=0,API=0,新二場本文=0,経過秒=time.monotonic()-started,
            表示主候補=proposal['表示主候補'],目標=proposal['limitations']))
        print('全33場・九新条件594会計保存。保存基準66会計の再金融0。',flush=True)
    except BaseException:
        write(OUT/'False.json',dict(全合格=False,原因=traceback.format_exc(),counts=dict(counts),
            source開始SHA256=source,自動再開始=False))
        raise


def main() -> None:
    """
    機能: 根の明示した正式実行だけを受け付ける。
    引数: CLI --root-trial-registered(bool) は根登録後の一回実行指定。
    返り値: None。失敗は保存し、未登録金融を行わない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--root-trial-registered',action='store_true',required=True)
    parser.parse_args()
    try:
        run()
    except BaseException:
        if not OUT.exists() and not (HERE/'金融前False.json').exists():
            write(HERE/'金融前False.json',dict(全合格=False,原因=traceback.format_exc(),金融=0,大型cache=0))
        raise


if __name__ == '__main__':
    main()
