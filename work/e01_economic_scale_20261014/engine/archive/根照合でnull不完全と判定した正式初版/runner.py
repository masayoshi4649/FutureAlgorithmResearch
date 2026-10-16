"""根の登録後だけ、33入力各一読から十四実親口座を一回全運転する。"""

import argparse
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
import time
import traceback
import numpy as np
from numba.core.registry import CPUDispatcher
import common
import catalog
import core
import data
import daily
import interface
import entry_policy
import base_policy
import order_kernel
import legacy_engine
import ledger_storage
import storage
import statistics
import plan

EXPECTED=Counter(既input一読=33,新account金融=924)


def case_hashes(configs: list[dict]) -> dict:
    """
    機能: 条件全項目を正規JSONへ結び、別数量/出口/率を同名で混ぜない。
    引数: configs(list[dict]) は結果前十四条件。
    返り値: dict[str,str] は条件IDとSHA256。NaN/重複IDは拒否する。
    """
    out={}
    for c in configs:
        assert c['id'] not in out
        out[c['id']]=hashlib.sha256(json.dumps(c,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()
    return out


def registry_guard(found: list[dict], fixed: dict, proposal: dict) -> None:
    """
    機能: 試行/八spec/条件指紋/全sourceを実input読取より前に一致確認する。
    引数: found(list[dict])、fixed/proposal(dict) は根の登録と固定計画。
    返り値: None。未登録・別条件・別sourceで金融を開始しない。
    """
    assert len(found)==1 and found[0]['id']==proposal['id']==catalog.TRIAL_ID
    assert found[0]['spec']==proposal['spec']
    assert catalog.configs()==fixed['configs']==proposal['spec']['entry']['conditions']
    assert case_hashes(catalog.configs())==fixed['case_SHA256']
    assert common.sources()==fixed['source_SHA256']==proposal['spec']['implementation']


def source_scope_guard() -> None:
    """
    機能: 経済moduleとJIT保存先が新所有域へ隔離され、旧moduleをimportしていないことを確認する。
    引数: なし。
    返り値: None。sourceやcache混在を拒否する。
    """
    for module in (common,catalog,core,data,daily,interface,entry_policy,base_policy,order_kernel,legacy_engine,ledger_storage,storage,statistics,plan):
        assert Path(module.__file__).resolve().parent==common.HERE
        for v in vars(module).values():
            if isinstance(v,CPUDispatcher):assert Path(v._cache._impl._locator._cache_path).resolve().is_relative_to(common.HERE/'jit')


def packed_curve(values: np.ndarray) -> dict:
    """
    機能: 十列の局所清算と場線を同NaN位置を保つplateauへ圧縮する。
    引数: values(ndarray[float,N,10]) は一次経済曲線。
    返り値: dict はshape/dtype/rows/values/lengthを持つexact保存形。
    """
    assert values.ndim==2 and values.shape[1]==10 and len(values)>0
    changed=np.any((values[1:]!=values[:-1])&~(np.isnan(values[1:])&np.isnan(values[:-1])),axis=1)
    rows=np.r_[0,np.flatnonzero(changed)+1].astype(np.int64)
    output=dict(type='plateau',shape=list(values.shape),dtype=values.dtype.str,rows=rows,values=values[rows].copy(),length=len(values))
    np.testing.assert_array_equal(values,output['values'][np.searchsorted(rows,np.arange(len(values)),side='right')-1])
    return output


def boundary(output: dict) -> dict:
    """
    機能: 初実fill名目起点・親線・場線を、未約定と未定義を混ぜず小資料へ保存する。
    引数: output(dict) は一実口座の政策出力。
    返り値: dict は当該口座の実親起点と場停止の判断系譜。
    """
    curve=output['economic_curve'];known=curve[:,9][np.isfinite(curve[:,9])]
    return dict(actual_origins=output['actual_origins'].tolist(),judgments=output['exit_judgments'].tolist(),
        scene_loss_stop_yen=float(known[0]) if len(known) else None,
        definition='名目Nは初actualfillで固定。未約定には実親線無し。場線は最初場内有限正価格の観測後だけ既知。')


def directional(parents: list[dict], symbol: str) -> dict:
    """
    機能: 完結実親の方向別net/枚数を主指標と同じ定義で集計する。
    引数: parents(list[dict])、symbol(str) は同条件の全保存親。
    返り値: dict はlong/shortの利益/損失/netと勝負枚数。
    """
    out={}
    for label,side in (('long',1),('short',-1)):
        group=[p for p in parents if p['symbol']==symbol and p['方向']==side]
        out[label]=dict(**daily.metric([p['収支'] for p in group]),勝ち枚数=sum(p['枚数'] for p in group if p['収支']>0),
            負け枚数=sum(p['枚数'] for p in group if p['収支']<0),枚数=sum(p['枚数'] for p in group),定義='完結親net。実玉別正負とは別。')
    return out


def run(registry: Path) -> None:
    """
    機能: 根登録後の唯一正式runで全33×2×14の実状態と親会計を保存する。
    引数: registry(Path) は根登録済み共通台帳。
    返り値: None。失敗を保持し自動再開始しない。旧GU/旧台帳/原板/APIは読まない。
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
    start=time.monotonic();counts=Counter();rows={c['id']:[] for c in configs};parents={cid:[] for cid in rows}
    legs={cid:[] for cid in rows};profiles={cid:[] for cid in rows};ledgers={cid:[] for cid in rows};bounds={cid:[] for cid in rows}
    try:
        for session in fixed['sessions']:
            packet=data.load(fixed['input_cache'][session]);counts['既input一読']+=1;assert packet['session']==session
            for symbol in catalog.CAP:
                account=packet['accounts'][symbol]
                for config in configs:
                    cid=config['id'];output=interface.play(account,config,session);counts['新account金融']+=1
                    own=interface.parent_diagnostics(account,output)
                    for p in own:
                        p.update(target_active=config['exit_id']=='TARGET',trail_active=config['exit_id'] in ('TRAIL','PARTIAL'),
                            reference_only_target_for_other_exits=config['exit_id']!='TARGET')
                    profiles[cid].extend(dict(session=session,symbol=symbol,**p) for p in own)
                    parents[cid].extend(dict(session=session,symbol=symbol,**p) for p in output['parent'])
                    legs[cid].extend(dict(session=session,symbol=symbol,**p) for p in output['actual_legs'])
                    rows[cid].append(output['summary']);bounds[cid].append(dict(session=session,symbol=symbol,**boundary(output)))
                    saved=ledger_storage.stored(output,len(account['record']['price']));saved['economic_curve']=packed_curve(output['economic_curve'])
                    target=common.HERE/f'finance/ledgers/{cid}/{session}_{symbol}.pkl.gz';data.save(target,saved)
                    ledgers[cid].append(dict(session=session,symbol=symbol,path=target.relative_to(common.ROOT).as_posix(),SHA256=data.digest(target)))
                    del output,saved,own
            del packet;gc.collect();print(session+' 容量十四実口座完了',flush=True)
        assert counts==EXPECTED and common.sources()==source==fixed['source_SHA256']
        results={}
        for cid in rows:
            periods={s:statistics.periods(rows[cid],parents[cid],profiles[cid],fixed['sessions'],s) for s in catalog.CAP}
            results[cid]=dict(rows=rows[cid],ledgers=ledgers[cid],periods=periods,
                symbols={s:periods[s]['全33']['aggregate'] for s in catalog.CAP},
                stability={s:periods[s]['全33']['stability'] for s in catalog.CAP},
                economic={s:periods[s]['全33']['economic'] for s in catalog.CAP},
                directional_symbols={s:directional(parents[cid],s) for s in catalog.CAP},
                actual_leg_symbols={s:dict(**daily.metric([l['収支'] for l in legs[cid] if l['symbol']==s]),定義='実決済玉net正負の副表。主指標は完結親。') for s in catalog.CAP})
        common.write('finance/結果.json',dict(全合格=True,sessions=fixed['sessions'],configs=configs,results=results,
            reused_results=fixed['reused_results'],actual_parent_diagnostics=profiles,boundary=bounds,counts=dict(counts),
            新account金融=924,旧GU再利用=0,旧台帳本文=0,source開始終端一致=True,source_SHA256=source,case_SHA256=fixed['case_SHA256'],
            原板=0,NPZ=0,API=0,現在入力=0,経過秒=time.monotonic()-start,
            主評価='損失/無取引込み全33場net/33。親net正負がP/L主定義、親平均は参考。実UID残0で完結、paper phaseで除外しない。NK円床未指定。'))
    except BaseException:
        common.write('finance/False.json',dict(全合格=False,原因=traceback.format_exc(),counts=dict(counts),source開始SHA256=source,自動再開始=False));raise


def main() -> None:
    """
    機能: 準備/根freeze/根登録後runを分離し、source固定前に大型読取をしない。
    引数: CLI --prepare-only/--prepare/--freeze/--root-trial-registered(bool)、--registry(Path)。
    返り値: None。金融開始は根だけが行う。
    """
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare-only','--prepare',dest='prepare_only',action='store_true')
    group.add_argument('--freeze',action='store_true');group.add_argument('--root-trial-registered',action='store_true')
    parser.add_argument('--registry',type=Path,default=common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    args=parser.parse_args()
    if args.prepare_only or args.freeze:plan.prepare(formal=args.freeze);return
    try:run(args.registry)
    except BaseException:
        if not (common.HERE/'finance').exists() and not (common.HERE/'金融前False.json').exists():
            common.write('金融前False.json',dict(全合格=False,原因=traceback.format_exc(),金融=0,実input=0,自動再開始=False))
        raise


if __name__=='__main__':main()
