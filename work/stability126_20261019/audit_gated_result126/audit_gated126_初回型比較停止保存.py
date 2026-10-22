"""追加53条件の独立会計・公開Q・商品場内同値引用を再金融なしで監査する。"""

from copy import deepcopy
import hashlib
import importlib.util
from io import BytesIO
import json
import math
from pathlib import Path
import pickle
import sys
import time

import numpy as np


HERE=Path(__file__).resolve().parent
TASK=HERE.parent
ROOT=HERE.parents[2]
GATED=TASK/'gated_bbo126'
FIELDS=('orders','trades','cycles','curve','stats','execution_events','execution_states','order_uids')
READS=[]
SEEN=set()
math_path=TASK/'audit_bbo_result126/audit126.py'
spec=importlib.util.spec_from_file_location('独立BBO会計数式の再利用126',math_path)
account_math=importlib.util.module_from_spec(spec);sys.modules[spec.name]=account_math;spec.loader.exec_module(account_math)


def sha(path: Path) -> str:
    """
    機能: 明示した保存資料の内容指紋を得る。
    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def meta(path: Path) -> dict:
    """
    機能: 保存済み小目録又は完成集計を読む。
    引数: path(Path)はJSON位置。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 新所有域の未使用位置へ有限JSONを保存する。
    引数: path(Path)、value(dict)は保存先と内容。
    返り値: None。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def once(item: dict, kind: str) -> bytes:
    """
    機能: 原本以外の固定保存資料を一監査読取し、同bytesでSHAを照合する。
    引数: item(dict)はpath/sha256、kind(str)は監査区分。
    返り値: bytesは指紋一致した素材。
    """
    path=(ROOT/item['path']).resolve();name=path.relative_to(ROOT).as_posix()
    assert name.startswith('work/') and name not in SEEN
    raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    row=dict(path=name,kind=kind,sha256=digest,expected_sha256=item['sha256'],bytes=len(raw),reads=1)
    READS.append(row);SEEN.add(name)
    with (HERE/'固定保存素材の一監査読取.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    assert digest==item['sha256'],name
    return raw


def feed(paper: dict) -> np.ndarray:
    """
    機能: 元通知8列と親開始時固定aだけから10列通知を独立構築する。
    引数: paper(dict)は元orders/cycles。
    返り値: ndarray[N,10]は数値通知。親終了・最終PL・極値は使わない。
    """
    orders=np.asarray(paper['orders']);parents={int(v[0]):float(v[5]) for v in paper['cycles']}
    assert orders.ndim==2 and orders.shape[1]==8
    value=np.zeros((len(orders),10));value[:,:8]=orders
    for i,order in enumerate(orders):
        assert 0<=int(order[1])<int(order[0]) and order[6]!=32.
        if order[7]==1.:value[i,9]=parents[int(order[2])];assert value[i,9]>0.
    assert np.isfinite(value).all()
    return value


def parameters(config: dict) -> np.ndarray:
    """
    機能: 固定された四数値方策だけを取り出す。
    引数: config(dict)は入口源や手法名も含む固定条件。
    返り値: ndarray[4]は同値判定と数値核に渡す値。
    """
    assert config['mask']==0 and config['fee_per_side']==0. and not config['increase_positions'] and not config['restore_positions']
    return np.array([config[k] for k in ('protect_start_atr','protect_keep_fraction','rearm_progress_atr','session_loss_r')],float)


def identity(notices: np.ndarray, policy: np.ndarray) -> str:
    """
    機能: 指定された完全同値プロトコルを別実装で指紋化する。
    引数: notices(ndarray[N,10])、policy(ndarray[4])は数値入力。
    返り値: strは同account内だけで使えるSHA256。
    """
    digest=hashlib.sha256()
    for value in (notices,policy):
        array=np.array(value,dtype=np.float64,order='C',copy=True)
        digest.update(str(array.shape).encode('ascii'));digest.update(array.dtype.str.encode('ascii'));digest.update(array.tobytes())
    return digest.hexdigest()


def array_hash(value: np.ndarray) -> str:
    """
    機能: alias先と元の配列の型・形・全bytes同値を確認する。
    引数: value(ndarray)は経済又は診断配列。
    返り値: strは同値比較用SHA256。
    """
    array=np.ascontiguousarray(value);digest=hashlib.sha256(repr((array.dtype.str,array.shape)).encode());digest.update(array.tobytes())
    return digest.hexdigest()


def finite(value: float) -> float | None:
    """
    機能: 独立Q診断値の未知をNoneとして保持する。
    引数: value(float)は比率又は価格。
    返り値: float|Noneは有限値又は未知。
    """
    return float(value) if math.isfinite(value) else None


def quote_filter(paper: dict, ready: dict, quotes: dict) -> tuple[dict,list[dict]]:
    """
    機能: 新規公開行と固定aだけからQ採否を独立再計算する。
    引数: paper/ready/quotes(dict)は保存元通知・価格・気配。
    返り値: tupleは親採否に基づく通知部分集合と独立trace。
    """
    notices=feed(paper);accepted={};selected=[];traces=[]
    for index,row in enumerate(notices):
        publication,preparation,cid=map(int,row[:3])
        if row[7]==1.:
            side=int(row[3]);a=float(row[9]);last=float(ready['last'][publication]);bid=float(quotes['bid'][publication]);ask=float(quotes['ask'][publication])
            normal=bool(quotes['quote_valid'][publication]) and math.isfinite(bid) and math.isfinite(ask) and 0<bid<ask
            known=normal and math.isfinite(last) and last>0 and math.isfinite(a) and a>0
            spread=ask-bid if normal else math.nan
            adverse=side*((ask if side>0 else bid)-last) if known else math.nan
            permit=known and spread<=a/2. and adverse<=a/2.
            accepted[cid]=permit
            reason='許可' if permit else '気配又は価格が未知' if not known else '気配幅超過' if spread>a/2. else 'Lastから不利幅超過'
            traces.append(dict(parent=cid,publication_row=publication,preparation_row=preparation,
                publication_seq=int(ready['seq'][publication]),publication_time=float(ready['time_s'][publication]),
                side=side,initial_atr=a,normal_quote=normal,enabled=True,last=finite(last),bid=finite(bid),ask=finite(ask),
                spread=finite(spread),adverse=finite(adverse),spread_atr=finite(spread/a),adverse_atr=finite(adverse/a),accepted=bool(permit),reason=reason))
        assert cid in accepted
        if accepted[cid]:selected.append(index)
    result=dict(paper);result['orders']=np.asarray(paper['orders'])[selected].copy()
    return result,traces


def papers(fixed: dict, baseline: dict) -> dict:
    """
    機能: 元通知24保存源を各一監査読取して三入口246口座へ対応する。
    引数: fixed/baseline(dict)は固定計画と旧30会計。
    返り値: dict[tuple,dict]は(source,session,symbol)ごとの元orders/cycles。
    """
    result={};items=fixed['paper_caches']
    with np.load(BytesIO(once(items[0],'原版旧30通知')),allow_pickle=False) as arrays:
        for row in baseline['rows']:
            prefix=row['symbol']+'_'+row['session'];result['E01',row['session'],row['symbol']]={name:arrays[prefix+'__'+name] for name in ('orders','cycles')}
    for item in items[1:]:
        with np.load(BytesIO(once(item,'原版新11通知')),allow_pickle=False) as arrays:
            result['E01',item['session'],item['symbol']]={name:arrays['E01__'+name] for name in ('orders','cycles')}
    with np.load(BytesIO(once(fixed['gated_cache'],'G_GU全41統合通知')),allow_pickle=False) as arrays:
        for source in ('G','GU'):
            for scene in fixed['sessions']:
                for symbol in ('TOPIX','NK225'):
                    prefix=source+'_'+symbol+'_'+scene
                    result[source,scene,symbol]={name:arrays[prefix+'__'+name] for name in ('orders','cycles')}
    assert len(result)==246
    return result


def execute() -> None:
    """
    機能: 新53×82表示会計の固有金融と旧/段内引用を分けて独立監査する。
    引数: なし。
    返り値: None。原本・金融再生なし。旧検証済会計はSHAと全配列同値で引用する。
    """
    assert not (HERE/'独立監査開始.json').exists()
    fixed=meta(GATED/'固定計画.json');completed_path=GATED/'GとGU及び低R利益床の全四十一場BBO会計.json'
    completed_raw=completed_path.read_bytes();completed=json.loads(completed_raw);assert completed['passed'] and len(completed['rows'])==4346
    baseline=meta(ROOT/fixed['baseline']['path']);previous=meta(ROOT/fixed['previous']['path'])
    assert completed['specs']==fixed['specs'] and completed['sessions']==fixed['sessions']
    assert completed['sources']==fixed['sources']
    assert {(r['path'],r['sha256']) for r in previous['paper_reads']}=={(r['path'],r['sha256']) for r in fixed['paper_caches']}
    verified_path=TASK/'audit_bbo_result126/全千三百十二BBO会計と全行清算の独立監査.json';verified=meta(verified_path)
    assert verified['passed'] and verified['result']['sha256']==sha(ROOT/fixed['previous']['path'])
    assert verified['source_sha256']==sha(math_path)
    save(HERE/'独立監査開始.json',dict(start=time.time(),result_sha256=hashlib.sha256(completed_raw).hexdigest(),
         expected_reads=dict(packet=41,new_npz=82,previous_npz=82,paper=24),original_market_reads=0,financial_replays=0))
    source_papers=papers(fixed,baseline)
    old_verified={(r['method'],r['session'],r['symbol']):r for r in verified['accounts']}
    previous_refs={(r['session'],r['symbol']):r for r in fixed['previous_caches']}
    previous_read_proof={r['path']:r['sha256'] for r in verified['read_log']}
    actual_refs={(r['session'],r['symbol']):r for r in completed['cache']}
    stored={(r['method'],r['session'],r['symbol']):r for r in completed['rows']}
    aliases={(r['method'],r['session'],r['symbol']):r for r in completed['aliases']}
    trace_index={(r['paper_source'],r['session'],r['symbol']):r for r in completed['quote_gate_traces']}
    assert len(stored)==len(aliases)==4346 and len(trace_index)==246
    independent=[];unique=0;old_count=0;within_count=0;array_comparisons=0;quote_parents=0
    for item in fixed['packets']:
        assert previous_read_proof[item['path']]==item['sha256']
        packet=pickle.loads(once(item,'元入力packet'));scene=packet['session'];assert scene==item['session']
        for symbol in ('TOPIX','NK225'):
            key=scene,symbol;ready=packet['inputs'][key];quotes=packet['quotes'][key];market=packet['markets'][key]
            memo={};base_feed=feed(source_papers['E01',scene,symbol]);oldref=previous_refs[key]
            assert previous_read_proof[oldref['path']]==oldref['sha256']
            with np.load(BytesIO(once(oldref,'独立確認済み旧BBO16')),allow_pickle=False) as arrays:
                for config in previous['specs']:
                    result={name:arrays[config['id']+'__'+name] for name in FIELDS}
                    signature=identity(base_feed,parameters(config))
                    memo[signature]=dict(origin='保存旧十六条件引用',canonical=config['id'],
                        hashes={name:array_hash(value) for name,value in result.items()},
                        summary=old_verified[config['id'],scene,symbol])
            filtered={}
            for source in ('E01','G','GU'):
                selected,trace=quote_filter(source_papers[source,scene,symbol],ready,quotes)
                original_trace=trace_index[source,scene,symbol]
                assert original_trace['parents']==trace,(source,scene,symbol,'公開時Q不一致')
                assert original_trace['accepted']==sum(r['accepted'] for r in trace)
                assert original_trace['rejected']==sum(not r['accepted'] for r in trace)
                quote_parents+=len(trace);filtered[source]=selected
            with np.load(BytesIO(once(actual_refs[key],'新53表示会計')),allow_pickle=False) as arrays:
                for config in completed['specs']:
                    method=config['id'];source=config['paper_source'];paper=filtered[source] if config['quote_gate_enabled'] else source_papers[source,scene,symbol]
                    signature=identity(feed(paper),parameters(config));row=stored[method,scene,symbol];alias=aliases[method,scene,symbol]
                    assert row['economic_key']==alias['economic_key']==signature
                    assert alias['packet_sha256']==item['sha256'] and alias['end']==ready['limit']
                    assert alias['cap']==(10 if symbol=='TOPIX' else 20)
                    result={name:arrays[method+'__'+name] for name in FIELDS};hashes={name:array_hash(value) for name,value in result.items()}
                    if signature in memo:
                        known=memo[signature];origin=known['origin'];canonical=known['canonical']
                        assert hashes==known['hashes'],(scene,symbol,method,'引用配列不一致')
                        array_comparisons+=len(FIELDS);summary=deepcopy(known['summary'])
                        if origin=='保存旧十六条件引用':old_count+=1
                        else:within_count+=1
                    else:
                        summary=account_math.audit_account(ready,quotes,market,paper,result,config)
                        unique+=1;origin='新規金融';canonical=method
                        memo[signature]=dict(origin='今回同値条件引用',canonical=method,hashes=hashes,summary=deepcopy(summary))
                    assert alias['origin']==row['calculation_origin']==origin
                    assert alias['canonical_method']==row['canonical_method']==canonical
                    for name,value in summary.items():
                        if name in row:account_math.equal(row[name],value,scene+'/'+symbol+'/'+method+'/'+name)
                    independent.append(dict(method=method,session=scene,symbol=symbol,
                        calculation_origin=origin,canonical_method=canonical,economic_key=signature,**{k:v for k,v in summary.items() if k not in ('method','session','symbol')}))
            print(scene+' '+symbol+' 53表示会計とQ及び同値引用を独立確認',flush=True)
    assert len(READS)==len(SEEN)==229 and len(independent)==4346
    assert unique==completed['new_financial_accounts'] and old_count==completed['reused_previous_accounts'] and within_count==completed['reused_within_stage_accounts']
    assert unique+old_count+within_count==4346
    totals=[]
    for config in completed['specs']:
        for symbol in ('TOPIX','NK225'):
            rows=[r for r in independent if r['method']==config['id'] and r['symbol']==symbol]
            totals.append(dict(method=config['id'],symbol=symbol,
                **{field:float(sum(r[field] for r in rows)) for field in ('profit','loss','net','entry_orders','entry_quantity','closed_quantity','long_net','short_net')},
                green=sum(r['net']>0 for r in rows),red=sum(r['net']<0 for r in rows),no_trade=sum(r['entry_orders']==0 for r in rows)))
    proof=dict(passed=True,result=dict(path=completed_path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(completed_raw).hexdigest()),
        fixed_plan=dict(path=(GATED/'固定計画.json').relative_to(ROOT).as_posix(),sha256=sha(GATED/'固定計画.json')),
        frozen_sources=completed['sources'],
        source_sha256=sha(Path(__file__)),reused_account_math=dict(path=math_path.relative_to(ROOT).as_posix(),sha256=sha(math_path)),
        previous_verified=dict(path=verified_path.relative_to(ROOT).as_posix(),sha256=sha(verified_path)),
        accounts=independent,totals=totals,read_log=READS,displayed_accounts=4346,
        new_financial_accounts_audited=unique,reused_previous_accounts_checked=old_count,
        reused_within_stage_accounts_checked=within_count,array_byte_comparisons=array_comparisons,
        quote_parents_recomputed=quote_parents,original_market_reads=0,financial_replays=0,API=0,real_orders=0,
        scope='新固有会計は独立FIFO/全行BBO。旧1312独立確認済会計と段内同値は同商品場・同通知方策key・全8配列bytes一致と全場額を確認。Qは公開行と固定初回ATRだけで別実装再計算。')
    save(HERE/'全四千三百四十六表示会計と公開Q及び同値引用の独立監査.json',proof)
    print(json.dumps(dict(passed=True,displayed=4346,new_unique=unique,reused_old=old_count,reused_new=within_count,reads=len(READS)),ensure_ascii=False))


if __name__=='__main__':
    try:execute()
    except Exception as error:
        save(HERE/('独立監査停止_'+str(time.time_ns())+'.json'),dict(passed=False,error=repr(error),read_log=READS,
            original_market_reads=0,financial_replays=0,API=0))
        raise
