"""根の正式固定/登録後だけ33packet各一読から十二保護再参加を一回運転する。"""

import argparse
from collections import Counter
import gc
from pathlib import Path
import time
import traceback
import numpy as np
from numba.core.registry import CPUDispatcher
import common
import catalog
import core
import daily
import data
import interface
import price_votes
import plan
import ledger_storage
import storage
import statistics
import order_kernel

EXPECTED=Counter(既input一読=33,価格票準備口座=66,新account金融=792)


def registry_guard(found: list[dict], fixed: dict, proposal: dict) -> None:
    """
    機能: 大型読取前に登録八部品・試行ID・十二case/全sourceの指紋を一致確認する。
    引数: found(list[dict])、fixed/proposal(dict) は根登録と正式固定。
    返り値: None。未登録/別spec/別sourceでは金融を開始しない。
    """
    assert len(found)==1 and found[0]['id']==proposal['id']==catalog.TRIAL_ID
    assert found[0]['spec']==proposal['spec']
    assert catalog.configs()==fixed['configs']==proposal['spec']['entry']['conditions']
    assert plan.case_hashes(catalog.configs())==fixed['case_SHA256']
    assert common.sources()==fixed['source_SHA256']==proposal['spec']['implementation']


def source_scope_guard() -> None:
    """
    機能: 全経済moduleとNumba cacheを新所有域へ限定する。
    引数: なし。
    返り値: None。旧module/cacheへの実行接続を拒否する。
    """
    for module in (common,catalog,core,daily,data,interface,price_votes,plan,ledger_storage,storage,statistics,order_kernel):
        assert Path(module.__file__).resolve().parent==common.HERE
        for value in vars(module).values():
            if isinstance(value,CPUDispatcher):assert Path(value._cache._impl._locator._cache_path).resolve().is_relative_to(common.HERE/'jit')


def packed(values: np.ndarray) -> dict:
    """
    機能: 曲線/geometryを同NaN位置のplateauへ圧縮しexact復元を検査する。
    引数: values(ndarray[二次元]) は一次全normal配列。
    返り値: dict はtype/shape/dtype/length/rows/values。未知を零へ変えない。
    """
    assert values.ndim==2 and len(values)>0
    changed=np.any((values[1:]!=values[:-1])&~(np.isnan(values[1:])&np.isnan(values[:-1])),axis=1)
    rows=np.r_[0,np.flatnonzero(changed)+1].astype(np.int64)
    result=dict(type='plateau',shape=list(values.shape),dtype=values.dtype.str,length=len(values),rows=rows,values=values[rows].copy())
    np.testing.assert_array_equal(values,result['values'][np.searchsorted(rows,np.arange(len(values)),side='right')-1])
    return result


def directional(parents: list[dict], symbol: str) -> dict:
    """
    機能: 完結実親netを買/売別に集計する。
    引数: parents(list[dict])、symbol(str) は一次全場実親。
    返り値: dict はlong/shortの主金額と親数量。実決済玉の副表とは別。
    """
    result={}
    for label,side in (('long',1),('short',-1)):
        own=[p for p in parents if p['symbol']==symbol and p['方向']==side]
        result[label]=dict(**daily.metric([p['収支'] for p in own]),枚数=sum(p['枚数'] for p in own),定義='完結実CIDのnet正負。')
    return result


def run(registry: Path) -> None:
    """
    機能: 根登録後の一回runで33入力の新価格票と792実口座を保存する。
    引数: registry(Path) は根の登録台帳。
    返り値: None。旧GU/旧台帳/原board/NPZ/APIは読まず、失敗を自動再開始しない。
    """
    fixed=data.read(common.HERE/'金融事前固定.json');proposal=data.read(common.HERE/'試行計画.json')
    found=[r for r in data.read(registry)['trials'] if r['id']==catalog.TRIAL_ID]
    registry_guard(found,fixed,proposal);source_scope_guard()
    assert fixed['正式freeze'] and proposal['正式freeze']
    assert data.digest(common.HERE/'試行計画.json')==fixed['計画SHA256'] and plan.clones()==proposal['同bytesコピー']
    for m in proposal['spec']['data']['input_manifests']:assert data.digest(common.ROOT/m['path'])==m['sha256']
    assert not (common.HERE/'finance').exists() and not (common.HERE/'金融前False.json').exists()
    source=common.sources();configs=fixed['configs'];(common.HERE/'finance').mkdir()
    common.write('finance/開始.json',dict(正式一回=True,source_SHA256=source,case_SHA256=fixed['case_SHA256'],予定=dict(EXPECTED)))
    counts=Counter();started=time.monotonic();rows={c['id']:[] for c in configs};parents={cid:[] for cid in rows}
    profiles={cid:[] for cid in rows};legs={cid:[] for cid in rows};ledgers={cid:[] for cid in rows};bounds={cid:[] for cid in rows};activity={cid:[] for cid in rows}
    try:
        for session in fixed['sessions']:
            packet=data.load(fixed['input_cache'][session]);counts['既input一読']+=1;assert packet['session']==session
            features=price_votes.pair(packet);counts['価格票準備口座']+=2
            for s in catalog.CAP:
                account=packet['accounts'][s]
                for config in configs:
                    cid=config['id'];output=interface.play(account,features[s],config,session);counts['新account金融']+=1
                    own=interface.parent_diagnostics(account,features[s],output)
                    profiles[cid].extend(dict(session=session,symbol=s,**p) for p in own)
                    parents[cid].extend(dict(session=session,symbol=s,**p) for p in output['parent'])
                    legs[cid].extend(dict(session=session,symbol=s,**p) for p in output['actual_legs'])
                    rows[cid].append(output['summary'])
                    bounds[cid].append(dict(session=session,symbol=s,actual_origins=interface.finite(output['actual_origins']),
                        judgments=interface.finite(output['exit_judgments']),
                        definition='実fill名目/親純清算/全場線。新CID受理ごと、UID fillごと。'))
                    pub,ev=output['publication_events'],output['execution_events']
                    activity[cid].append(dict(session=session,symbol=s,候補=len(pub),受理=int(np.sum(pub[:,12]==1)),
                        origin候補=int(np.sum(pub[:,4]==0)),pull候補=int(np.sum(pub[:,4]==1)),break候補=int(np.sum(pub[:,4]==2)),
                        新規fill=int(np.sum((ev[:,1]==1)&(ev[:,9]==1))),一回FAK失効=int(np.sum((ev[:,1]==1)&(ev[:,9]==0))),
                        未試行取消=int(np.sum(ev[:,1]==3)),最大buffer=output['buffer_capacity'],
                        拒否理由={str(int(reason)):int(np.sum(pub[:,13]==reason)) for reason in np.unique(pub[:,13]) if reason!=0}))
                    saved=ledger_storage.stored(output,len(account['record']['price']))
                    for field in ('economic_curve','geometry_trace'):saved[field]=packed(output[field])
                    target=common.HERE/f'finance/ledgers/{cid}/{session}_{s}.pkl.gz';data.save(target,saved)
                    ledgers[cid].append(dict(session=session,symbol=s,path=target.relative_to(common.ROOT).as_posix(),SHA256=data.digest(target)))
                    del output,saved,own
            del packet,features;gc.collect();print(session+' 十二保護再参加完了',flush=True)
        assert counts==EXPECTED and common.sources()==source==fixed['source_SHA256']
        results={}
        for cid in rows:
            periods={s:statistics.periods(rows[cid],parents[cid],profiles[cid],fixed['sessions'],s) for s in catalog.CAP}
            results[cid]=dict(rows=rows[cid],ledgers=ledgers[cid],periods=periods,
                symbols={s:periods[s]['全33']['aggregate'] for s in catalog.CAP},stability={s:periods[s]['全33']['stability'] for s in catalog.CAP},
                economic={s:periods[s]['全33']['economic'] for s in catalog.CAP},directional_symbols={s:directional(parents[cid],s) for s in catalog.CAP},
                actual_leg_symbols={s:dict(**daily.metric([l['収支'] for l in legs[cid] if l['symbol']==s]),定義='実決済玉副表。主指標は完結実親net。') for s in catalog.CAP})
        common.write('finance/結果.json',dict(全合格=True,sessions=fixed['sessions'],configs=configs,results=results,
            comparison_reference=fixed['comparison_reference'],actual_parent_diagnostics=profiles,boundary=bounds,activity=activity,
            counts=dict(counts),新account金融=792,旧GU再利用=0,旧台帳本文=0,source開始終端一致=True,source_SHA256=source,
            case_SHA256=fixed['case_SHA256'],原board=0,NPZ=0,API=0,現在入力=0,経過秒=time.monotonic()-started,
            主評価='損失/無取引込み全33場平均net。親平均は参考、NK床未指定。価格票はLast代理でvolume方向とは別。'))
    except BaseException:
        common.write('finance/False.json',dict(全合格=False,原因=traceback.format_exc(),counts=dict(counts),source開始SHA256=source,自動再開始=False));raise


def main() -> None:
    """
    機能: 小目録/草案準備と根freeze/登録後金融を分離する。
    引数: CLI --metadata-only/--prepare-only/--freeze/--root-trial-registered(bool)、--registry(Path)。
    返り値: None。金融は根の指示だけで実行する。
    """
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    for flag in ('metadata-only','prepare-only','freeze','root-trial-registered'):group.add_argument('--'+flag,action='store_true')
    parser.add_argument('--registry',type=Path,default=common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    args=parser.parse_args()
    if args.metadata_only:plan.metadata();return
    if args.prepare_only or args.freeze:plan.prepare(formal=args.freeze);return
    try:run(args.registry)
    except BaseException:
        if not (common.HERE/'finance').exists() and not (common.HERE/'金融前False.json').exists():
            common.write('金融前False.json',dict(全合格=False,原因=traceback.format_exc(),金融=0,大型input=0,自動再開始=False))
        raise


if __name__=='__main__':main()
