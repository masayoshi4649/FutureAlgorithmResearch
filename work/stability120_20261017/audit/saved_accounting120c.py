"""固定済み独立会計を使い、新四管理の保存台帳だけを算術監査する。"""

import argparse
from collections import Counter
import hashlib
import importlib.util
from io import BytesIO
import json
import math
from pathlib import Path
import sys

import numpy as np

import saved_accounting120 as core


HERE=Path(__file__).resolve().parent
OWNER=HERE.parent
ROOT=OWNER.parents[1]
CORE_SHA='3cf2c6727301b401a548b501ece268d62e996ec92528f35bb6b7897f2e78d16e'
READS=Counter()


def qualifications(quotes: dict,orders: np.ndarray,row: dict,setting: dict,spec: dict) -> None:
    """
    機能: 保存実注文から当原rowの追加信用・片側・価格限定・気配差と方向停止を独立照合する。
    引数: quotes(dict)、orders(ndarray18列)、row/setting/spec(dict)は保存小会計と固定契約。
    返り値: None。取消済み未約定注文のstateは推測せず実fillの条件だけを確認する。
    """
    q,_=core.valid_quotes(quotes,setting);rr=q['row'];bb=q['bid'];aa=q['ask'];n=len(rr)
    fee=math.floor(setting['fee']+1e-9);mult=setting['multiplier'];step=row['step'];mode=spec['mode']
    entry=orders[orders[:,1]==1];exits=orders[orders[:,1]==2]
    lookup={int(o[0]):o for o in entry}
    traces={}
    for side in (1,-1):
        count=np.zeros(n);basis=np.zeros(n);closing=np.zeros(n);pending=np.zeros(n)
        for o in entry[entry[:,2]==side]:
            di,fi=core.positions(rr,o[[3,4]],'信用新規の判断約定原row')
            count[fi]+=1;basis[fi]+=o[7];pending[di]+=1;pending[fi]-=1
        for o in exits[exits[:,2]==-side]:
            en=lookup[int(o[0])];di,fi=core.positions(rr,o[[3,4]],'信用返済の判断約定原row')
            count[fi]-=1;basis[fi]-=en[7];closing[di]+=1;closing[fi]-=1
        qty=np.cumsum(count);value=np.cumsum(basis)
        pure=(qty*(bb if side==1 else aa)-value)*side*mult-2*fee*qty
        traces[side]=(qty,pure,np.cumsum(closing),np.cumsum(pending))
    for side in (1,-1):
        own=entry[entry[:,2]==side];di=core.positions(rr,own[:,3],'追加資格判断原row')
        unique,counts=np.unique(di,return_counts=True);qty,pure,closing,pending=traces[side]
        core.check(np.all(closing[unique]==0),'方向返済予約中の実追加なし')
        first=qty[unique]==0
        core.check(np.all(counts[first]==1),'当方向に保有が無い最初の実新規は一枚')
        core.check(np.all(pure[unique[~first]]+1e-5>=3*step*mult*counts[~first]),'同原row実追加数は当時の全清算純益で一回ずつ予約')
        if mode>=9:
            oq,_,_,op=traces[-side]
            core.check(np.all(oq[unique]==0) and np.all(op[unique]==0),'片側型は対向保有又は実新規予約中に判断しない')
        if mode>=10:
            decision_price=aa[di] if side==1 else bb[di]
            core.check(np.all(side*(own[:,7]-decision_price)<=setting['observed_tick']+1e-6),'実新規は判断気配から一観測刻み以内')
        if mode==11:
            fi=core.positions(rr,own[:,4],'COST約定原row')
            core.check(np.all(aa[di]-bb[di]<=step+1e-8) and np.all(aa[fi]-bb[fi]<=step+1e-8),'COSTは判断と最初実fillの両方でspread資格を満たす')
        stops=exits[(exits[:,2]==-side)&(exits[:,9]==8)]
        si=core.positions(rr,stops[:,3],'方向停止判断原row')
        unique=np.unique(si)
        core.check(np.all(pure[unique]<=-3*step*mult+1e-5),'方向停止は全同方向費用後清算損で判断')
        core.check(np.all(qty[unique]==closing[unique]),'方向停止は同方向実全玉を返済予約へ')


def main() -> None:
    """
    機能: 根の完成SHA通知後だけ、八十cacheを各一読保全して全千九百二十口座を照合する。
    引数: CLI --result(Path)、--sha256(str)、--output(Path)は指定完成物と所有先。
    返り値: None。新市場読取・旧b金融再生・台帳変更を行わない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--result',type=Path,required=True);parser.add_argument('--sha256',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    core.check(core.sha(Path(core.__file__).read_bytes())==CORE_SHA,'既監査済み算術source不変')
    core.check(not args.output.exists(),'c所有監査先未使用')
    raw=args.result.read_bytes();READS['完成結果']+=1;core.check(core.sha(raw)==args.sha256,'根指定c完成SHA')
    own=args.output/'owned';own.mkdir(parents=True);(own/'完成結果.json').write_bytes(raw)
    data=json.loads(raw.decode('utf8'));del raw
    core.check(len(data['specs'])==24 and len(data['runs'])==1920 and len(data['cache'])==80 and len(data['sessions'])==40,'新二十四政策八十入力千九百二十口座')
    core.check(tuple(data['order_columns'])==core.ORDER_COLUMNS and tuple(data['lot_columns'])==core.LOT_COLUMNS and tuple(data['curve_columns'])==core.CURVE_COLUMNS,'既存列契約を維持')
    source={p:core.sha((ROOT/p).read_bytes()) for p in data['source_SHA256']};core.check(source==data['source_SHA256'],'c正式源開始SHA')
    sys.path.insert(0,str(OWNER));cat_path=OWNER/'recovery_c'/'catalog120c.py'
    loader=importlib.util.spec_from_file_location('audit_saved120c_catalog',cat_path);catalog=importlib.util.module_from_spec(loader);loader.loader.exec_module(catalog)
    core.check(catalog.specifications()==data['specs'],'c固定二十四仕様')
    rows={(r['symbol'],r['session'],r['method']):r for r in data['runs']};core.check(len(rows)==1920,'c全口座一意')
    fixed=json.loads((OWNER/'recovery_c'/'固定計画.json').read_text(encoding='utf8'))
    manifest_path=ROOT/fixed['input_manifest']['path'];manifest_raw=manifest_path.read_bytes();core.check(core.sha(manifest_raw)==fixed['input_manifest']['sha256'],'c入力目録固定SHA')
    meta=json.loads(manifest_raw.decode('utf8'));expected={(m['symbol'],m['session']):(m['path'],m['sha256']) for m in meta['inputs']}
    references={(r['symbol'],r['session']):(r['input_path'],r['input_sha256']) for r in data['cache']};core.check(expected==references and len(expected)==80,'c八十入力参照は目録と完全一致')
    reports=[]
    for number,ref in enumerate(data['cache']):
        symbol,session=ref['symbol'],ref['session'];path=(ROOT/ref['path']).resolve();core.check(path.is_relative_to(args.result.resolve().parent),'c保存cache領域')
        raw=path.read_bytes();READS['小cache']+=1;core.check(core.sha(raw)==ref['sha256'],'c小cache同bytes')
        dest=own/symbol/(session+'.npz');dest.parent.mkdir(parents=True,exist_ok=True);core.check(not dest.exists(),'c保全先一意');dest.write_bytes(raw)
        with np.load(BytesIO(raw),allow_pickle=False) as z:arrays={k:z[k].copy() for k in z.files}
        del raw
        core.check(set(arrays)=={'orders','lots','curves','quotes__row','quotes__time','quotes__last','quotes__bid','quotes__ask'},'c保存配列集合')
        for key,columns in (('orders',19),('lots',20),('curves',9)):
            a=arrays[key];core.check(a.ndim==2 and a.shape[1]==columns and np.all(a[:,0]==a[:,0].astype(int)) and np.all((a[:,0]>=0)&(a[:,0]<24)),'c政策indexと列数')
        quotes={k:arrays['quotes__'+k] for k in ('row','time','last','bid','ask')};setting=catalog.settings(symbol,session)
        for index,policy in enumerate(data['specs']):
            pieces=[arrays[k][arrays[k][:,0]==index,1:] for k in ('orders','lots','curves')];row=rows[symbol,session,policy['id']]
            result=core.audit_account(quotes,*pieces,row,setting,policy);qualifications(quotes,pieces[0],row,setting,policy)
            reports.append(dict(symbol=symbol,session=session,method=policy['id'],**result))
        print(f'{number+1}/80 新二十四条件の保存会計照合',flush=True)
    core.check(source=={p:core.sha((ROOT/p).read_bytes()) for p in source},'c正式源終端不変')
    unclosed=[r for r in reports if r['unclosed']]
    proof=dict(passed=not unclosed,result_sha256=args.sha256,audit_source_sha256=core.sha(Path(__file__).read_bytes()),accounting_source_sha256=CORE_SHA,source_SHA256=source,checks=dict(core.CHECKS),reads=dict(READS),saved_accounts=len(reports),unclosed_accounts=unclosed,reconstructed=reports,original_market_reads=0,original119_cache_reads=0,baseline_b_financial_replay=0,financial_replay=0,registry_changes=0,留保='保存注文と気配の算術監査。同じ既知40場の再生条件であり独立した新有効性証拠ではない。取消済み未約定のstateは保存に無いので数を再現せず実新規の資格と人工へ委譲。')
    target=args.output/'新四管理二十四政策の全千九百二十口座独立会計監査.json';core.save(target,proof)
    print(json.dumps(dict(passed=not unclosed,accounts=len(reports),sha256=core.sha(target.read_bytes()),reads=dict(READS)),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
