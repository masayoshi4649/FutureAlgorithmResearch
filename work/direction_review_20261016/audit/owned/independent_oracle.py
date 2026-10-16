"""方向採点を逐行の有理数計算へ照合し、小さい値幅の先着と利益を混同しない。"""

from __future__ import annotations

from fractions import Fraction
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[1]
ALPHAS=(Fraction(1,2000),Fraction(1,1000),Fraction(1,500))
FIELDS=['type','episode','start_i','pub_i','d','bid','ask','bid_q0','ask_q0','bid_q_at_public','ask_q_at_public',
        'min_bid_q','min_ask_q','opposite_q0','opposite_q_at_public','opposite_min_q','quantity_ratio','minimum_quantity_ratio',
        'quantity_group','total_volume','npositive','first_positive_i','fresh_price_time','volume_after_price','volume_clock_known',
        'first_positive_fresh_price_time','first_positive_volume_after_price','first_positive_volume_clock_known',
        'start_raw_seq','pub_raw_seq','pub_price_time_s']


def exact(value) -> Fraction:
    """
    機能: 人工価格を十進文字列から有理数へ移す。
    引数: value(int|float)。
    返り値: Fraction。
    """
    return Fraction(str(value))


def reference(arrays: dict,signal: dict,symbol: str,start: float,end: float,tick: float,policy: dict) -> dict:
    """
    機能: 全原行の直接走査だけで候補資格・二起点・三幅・打切を判定する。
    引数: 人工原配列/公開/方針(dict)、symbol(str)、start/end/tick(float)。
    返り値: dict 独立期待。区間木や完成源の採点関数は呼ばない。
    """
    n=len(arrays['raw_seq']);events=signal['events'];fields=signal['fields'];index={k:fields.index(k) for k in fields}
    e=len(events);valid=[];reasons=[]
    for i in range(n):
        pt,b,a=float(arrays['price_time_s'][i]),float(arrays['bid'][i]),float(arrays['ask'][i]);r=0
        if not math.isfinite(pt):r|=1
        elif pt<start:r|=2
        elif pt>=end:r|=64
        if not(math.isfinite(b) and math.isfinite(a) and 0<b<a):r|=4
        if i:
            if arrays['raw_seq'][i]!=arrays['raw_seq'][i-1]+1:r|=8
            previous=arrays['price_time_s'][i-1]
            if not math.isfinite(previous):r|=16
            elif math.isfinite(pt) and pt<previous:r|=32
        if int(arrays['price_reset_reason'][i])&8:r|=32
        valid.append(r==0);reasons.append(r)
    quantity=[bool(arrays['best_quantity_valid'][i] and math.isfinite(arrays['bid_qty'][i]) and math.isfinite(arrays['ask_qty'][i]) and arrays['bid_qty'][i]>0 and arrays['ask_qty'][i]>0) for i in range(n)]
    labels=np.full((e,3,2),-2,np.int8);terminal=np.full((e,3,2),-1,np.int64)
    mfe=np.full((e,2),np.nan);mae=np.full((e,2),np.nan);ending=np.full((e,2),-1,np.int64)
    eligible=np.zeros((e,3),bool);available=np.zeros(e,bool);entries=np.full(e,-1,np.int64)
    entryprice=np.full(e,np.nan);entryreasons=np.zeros(e,np.uint8)
    cap,mult,fee=(10,1000,Fraction(418,10)) if symbol=='TOPIX' else (20,10,Fraction(11))
    roundtrip=2*(cap*fee.numerator//fee.denominator);cost=Fraction(roundtrip,cap*mult)
    for k,event in enumerate(events):
        p=int(event[index['pub_i']]);d=int(event[index['d']]);typ=int(event[index['type']]);stamp=arrays['price_time_s'][p]
        qualified=policy['entry_start_s']<=stamp<policy['entry_end_s'] and valid[p] and quantity[p] and arrays['ask'][p]-arrays['bid'][p]<2*tick
        qualified=qualified and not any(lo<=stamp<hi for lo,hi in policy['quiet_windows'])
        b=typ==1 and event[index['opposite_min_q']]>=event[index['opposite_q0']]
        same=event[index['bid_q_at_public']] if d==1 else event[index['ask_q_at_public']]
        opp=event[index['ask_q_at_public']] if d==1 else event[index['bid_q_at_public']]
        eligible[k]=[qualified and typ==0,qualified and b,qualified and b and same>=opp]
        j=p+1;r=0
        if j>=n:r=1
        else:
            if arrays['raw_seq'][j]!=arrays['raw_seq'][p]+1:r|=2
            if not valid[j]:r|=4
            if not quantity[j]:r|=8
        entryreasons[k]=r;available[k]=r==0
        if not r:entries[k]=j;entryprice[k]=arrays['ask'][j] if d==1 else arrays['bid'][j]
        stop=j
        while stop<n and valid[stop]:stop+=1
        endcode=2 if stop==n else 3 if reasons[stop]==64 else 0
        endrow=n-1 if stop==n else stop
        public=(exact(arrays['bid'][p])+exact(arrays['ask'][p]))/2
        for origin in range(2):
            if origin==1 and r:continue
            ending[k,origin]=stop
            scores=[]
            for row in range(j,stop):
                q=(exact(arrays['bid'][row])+exact(arrays['ask'][row]))/2 if origin==0 else exact(arrays['bid'][row] if d==1 else arrays['ask'][row])
                ref=public if origin==0 else exact(entryprice[k])
                scores.append((row,d*(q-ref)-(cost if origin else 0)))
            if scores:mfe[k,origin]=float(max(v for _,v in scores));mae[k,origin]=float(min(v for _,v in scores))
            for w,alpha in enumerate(ALPHAS):
                code,at=endcode,endrow
                for row,value in scores:
                    if value>=public*alpha:code,at=1,row;break
                    if value<=-public*alpha:code,at=-1,row;break
                labels[k,w,origin]=code;terminal[k,w,origin]=at
    chosen=np.zeros((e,3),bool)
    for rule in range(3):
        busy_through=-1
        for k,event in enumerate(events):
            p=int(event[index['pub_i']])
            if eligible[k,rule] and p>busy_through:
                chosen[k,rule]=True
                busy_through=max(int(terminal[k,2,0]),int(terminal[k,2,1]))
    return dict(labels=labels,terminal_rows=terminal,eligible=eligible,nonoverlap=chosen,entry_available=available,
                entry_rows=entries,entry_prices=entryprice,entry_reason_mask=entryreasons,mfe=mfe,mae=mae,
                continuous_end_exclusive=ending,price_valid_mask=np.array(valid),price_reason_mask=np.array(reasons,np.uint16),
                roundtrip_fee_yen=roundtrip,roundtrip_fee_points=float(cost))


def fixture(symbol: str,side: int,mids: list[float],pubs: tuple[int,...]=(1,)) -> tuple[dict,dict,dict]:
    """
    機能: 同一価格の公開と後続だけを持つ独立人工配列を作る。
    引数: symbol(str)、side(int)、mids(list[float])、pubs(tuple[int,...])。
    返り値: tuple 原配列・公開列・方針。
    """
    n=len(mids);tick=.5 if symbol=='TOPIX' else 10.;center=4000. if symbol=='TOPIX' else 60000.
    actual=np.array([center+side*x for x in mids],float)
    arrays=dict(raw_seq=np.arange(n,dtype=np.int64),price_time_s=np.arange(n,dtype=float)+1000,
        bid=actual-tick/2,ask=actual+tick/2,bid_qty=np.full(n,20. if side==1 else 10.),
        ask_qty=np.full(n,10. if side==1 else 20.),best_quantity_valid=np.ones(n,bool),price_reset_reason=np.zeros(n,np.uint16))
    events=[]
    for ep,p in enumerate(pubs):
        for typ in (0,1):
            values={k:0. for k in FIELDS}
            values.update(type=typ,episode=ep,start_i=max(0,p-1),pub_i=p,d=side,bid=arrays['bid'][p],ask=arrays['ask'][p],
                bid_q0=arrays['bid_qty'][p],ask_q0=arrays['ask_qty'][p],bid_q_at_public=arrays['bid_qty'][p],ask_q_at_public=arrays['ask_qty'][p],
                min_bid_q=arrays['bid_qty'][p],min_ask_q=arrays['ask_qty'][p],opposite_q0=10.,opposite_q_at_public=10.,
                opposite_min_q=10.,quantity_ratio=1.,minimum_quantity_ratio=1.,quantity_group=1.,total_volume=10.,npositive=1.,
                first_positive_i=p,fresh_price_time=1.,volume_clock_known=1.,first_positive_fresh_price_time=1.,
                first_positive_volume_clock_known=1.,start_raw_seq=max(0,p-1),pub_raw_seq=p,pub_price_time_s=arrays['price_time_s'][p])
            events.append([values[k] for k in FIELDS])
    policy=dict(entry_start_s=0.,entry_end_s=1400.,force_start_s=1700.,quiet_windows=np.empty((0,2)))
    signal=dict(events=np.array(events,float).reshape(-1,31),fields=FIELDS.copy(),price_valid_mask=np.ones(n,bool))
    return arrays,signal,policy


def main() -> None:
    """
    機能: 完成二源を私有copyへ接続し、直接走査の独立期待を照合する。
    引数: なし。
    返り値: None。原入力・旧金融・新金融・APIは0。
    """
    private=HERE/'完成engineの私有複製';private.mkdir(exist_ok=True)
    for name in ('engine.py','artificial.py'):(private/name).write_bytes((BASE/name).read_bytes())
    source={name:hashlib.sha256((BASE/name).read_bytes()).hexdigest() for name in ('engine.py','artificial.py')}
    assert source['engine.py']=='c62d3c93c745038843c5d10d8b4f8520340955e48db0fba116777d88fcd9fd1e'
    sys.path.insert(0,str(private));engine=importlib.import_module('engine')
    cases=[];checks=0;matrices=0;prefixes=0
    paths=([0,0,2,2,4,4,8,8,12,12,14,14], [0,0,-2,-4,-8,-10], [0,0,-1,-2,-1,3,9], [0,0,0,0,0,0])
    for symbol in ('TOPIX','NK225'):
        scale=1 if symbol=='TOPIX' else 15
        for side in (1,-1):
            for path in paths:
                mids=[x*scale for x in path]
                cases.append((symbol,*fixture(symbol,side,mids)))
            for kind in ('qty_future','price_cut','window_end','window_and_gap','eof_public','entry_qty','entry_gap','quiet_arrival'):
                a,s,p=fixture(symbol,side,[x*scale for x in [0,0,2,2,4,4,8,8,12,12,14,14]],(1,3,5,9,11))
                if kind=='qty_future':a['best_quantity_valid'][4:]=False
                elif kind=='price_cut':a['ask'][4]=np.nan
                elif kind=='window_end':a['price_time_s'][4:]=np.arange(len(a['raw_seq'])-4)+2000.
                elif kind=='window_and_gap':
                    a['price_time_s'][4:]=np.arange(len(a['raw_seq'])-4)+2000.;a['raw_seq'][4:]+=1
                elif kind=='eof_public':s['events']=s['events'][-2:].copy()
                elif kind=='entry_qty':a['best_quantity_valid'][2]=False
                elif kind=='entry_gap':a['raw_seq'][2:]+=1
                else:p['quiet_windows']=np.array([[1002.,1003.]])
                # 将来cut後のpubは保存114では生じないため、既知pubだけ残す。
                initial=reference(a,s,symbol,0.,2000.,.5 if symbol=='TOPIX' else 10.,p)
                pubs=s['events'][:,FIELDS.index('pub_i')].astype(int)
                s['events']=s['events'][initial['price_valid_mask'][pubs]].copy()
                for event in s['events']:
                    pub=int(event[FIELDS.index('pub_i')])
                    event[FIELDS.index('pub_raw_seq')]=a['raw_seq'][pub]
                    event[FIELDS.index('pub_price_time_s')]=a['price_time_s'][pub]
                cases.append((symbol,a,s,p))
    def inspect(symbol,a,s,p):
        """
        機能: 直接走査と完成木照会を全配列で比べる。
        引数: symbol(str)、a/s/p(dict)。
        返り値: dict 完成源の結果。
        """
        nonlocal checks,matrices
        tick=.5 if symbol=='TOPIX' else 10.
        wanted=reference(a,s,symbol,0.,2000.,tick,p);s['price_valid_mask']=wanted['price_valid_mask'].copy()
        out=engine.measure(a,s,symbol,0.,2000.,tick,p)
        for name,value in wanted.items():
            if isinstance(value,np.ndarray):
                if value.dtype.kind=='f':np.testing.assert_allclose(out[name],value,rtol=0,atol=1e-9,equal_nan=True)
                else:np.testing.assert_array_equal(out[name],value)
                matrices+=1
            else:assert abs(out[name]-value)<1e-12
            checks+=1
        assert out['rule_names']==['A','B','C']
        return out
    for symbol,a,s,p in cases:
        full=inspect(symbol,a,s,p)
        for size in (2,4,len(a['raw_seq'])-1):
            if size<=0 or size>=len(a['raw_seq']):continue
            aa={k:v[:size].copy() for k,v in a.items()};ss=dict(s,events=s['events'][s['events'][:,FIELDS.index('pub_i')]<size].copy())
            cut=inspect(symbol,aa,ss,p);prefixes+=1
            count=len(ss['events'])
            np.testing.assert_array_equal(cut['eligible'],full['eligible'][:count])
            np.testing.assert_array_equal(cut['nonoverlap'],full['nonoverlap'][:count])
            checks+=2
    assert source=={name:hashlib.sha256((BASE/name).read_bytes()).hexdigest() for name in source}
    proof=dict(全合格=True,source_SHA256=source,確認数=checks,配列照合数=matrices,素材数=len(cases),接頭数=prefixes,
        独立源_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),実入力=0,原NPZ=0,保存event=0,既金融=0,新金融=0,API=0,
        重要境界='公開資格のみ時刻審査。参照用の次行気配はquiet/force取消を再現しない。実新規可否・実金融勝率ではない。',
        比較='MFE/MAEは先着後も連続価格区間末までで負値も保持。先着・未到達・cut/EOF/窓末・entry不可を混同しない。')
    target=HERE/'三幅二起点と共通非重複の独立逐行oracle.json'
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,確認数=checks,配列照合数=matrices,接頭数=prefixes,素材数=len(cases)),ensure_ascii=False))


if __name__=='__main__':main()
