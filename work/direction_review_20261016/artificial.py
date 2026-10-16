"""保存入力を開かず、逐次直走査と厳密料で二起点三幅の採点を反証する。"""

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import traceback

import numpy as np

import engine


HERE=Path(__file__).resolve().parent
ART=HERE/'三値幅二起点と共通非重複及び保存統合の人工検査.json'
FIELDS=['type','episode','start_i','pub_i','d','bid','ask','bid_q0','ask_q0','bid_q_at_public',
    'ask_q_at_public','min_bid_q','min_ask_q','opposite_q0','opposite_q_at_public','opposite_min_q',
    'quantity_ratio','minimum_quantity_ratio','quantity_group','total_volume','npositive','first_positive_i',
    'fresh_price_time','volume_after_price','volume_clock_known','first_positive_fresh_price_time',
    'first_positive_volume_after_price','first_positive_volume_clock_known','start_raw_seq','pub_raw_seq','pub_price_time_s']


def sources() -> dict:
    """
    機能: 所有二源だけの開始終端SHA256を求める。
    引数: なし。
    返り値: dict[str,str] は源指紋。実入力・保存事象・金融本文を開かない。
    """
    return {name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ('engine.py','artificial.py')}


def safe(value: object) -> object:
    """
    機能: 合成出力の未観測NaNをNoneとした保存構造へ写す。
    引数: value(object) は合成出力。資格・採点の入力へ返さない。
    返り値: object はJSON原始型。未観測を0へ補完しない。
    """
    if isinstance(value,np.ndarray):return safe(value.tolist())
    if isinstance(value,np.generic):return safe(value.item())
    if isinstance(value,float):return value if math.isfinite(value) else None
    if isinstance(value,dict):return {str(k):safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [safe(v) for v in value]
    return value


def reason(a: dict,i: int,start: float,end: float) -> int:
    """
    機能: 一行ずつ価格時計・seq・BBOの不成立理由を独立判定する。
    引数: a(dict)、i(int)、start/end(float) は合成観測と位置。
    返り値: int は重複bit。量と出来高を判定へ使用しない。
    """
    r=0;t=a['price_time_s'][i]
    if not math.isfinite(t):r|=1
    elif t<start:r|=2
    elif t>=end:r|=64
    if not(math.isfinite(a['bid'][i]) and math.isfinite(a['ask'][i]) and 0<a['bid'][i]<a['ask'][i]):r|=4
    if i:
        if a['raw_seq'][i]!=a['raw_seq'][i-1]+1:r|=8
        prev=a['price_time_s'][i-1]
        if not math.isfinite(prev):r|=16
        elif math.isfinite(t) and t<prev:r|=32
    if a['price_reset_reason'][i]&8:r|=32
    return r


def events(a: dict,pubs: list[int],directions: list[int],start: float,end: float) -> dict:
    """
    機能: 同rowtype0/type1を含む保存schemaの合成公開を組み立てる。
    引数: a(dict)、pubs/directions(list[int])、start/end(float) は原列と公開位置。
    返り値: dict はevents/fields/price_valid_mask。未来の結果欄を持たない。
    """
    rows=[]
    for episode,(row,d) in enumerate(zip(pubs,directions)):
        if reason(a,row,start,end):continue
        for typ in (0,1):
            v=np.zeros(len(FIELDS));data=dict(type=typ,episode=episode,start_i=max(0,row-1),pub_i=row,d=d,
                bid=a['bid'][row],ask=a['ask'][row],bid_q0=10.,ask_q0=10.,bid_q_at_public=a['bid_qty'][row],
                ask_q_at_public=a['ask_qty'][row],min_bid_q=10.,min_ask_q=10.,opposite_q0=10.,
                opposite_q_at_public=10.,opposite_min_q=10. if episode%3 else 5.,quantity_ratio=1.,
                minimum_quantity_ratio=1. if episode%3 else .5,quantity_group=1,total_volume=10.,npositive=1,
                first_positive_i=row,fresh_price_time=1,volume_clock_known=1,first_positive_fresh_price_time=1,
                first_positive_volume_clock_known=1,start_raw_seq=a['raw_seq'][max(0,row-1)],pub_raw_seq=a['raw_seq'][row],
                pub_price_time_s=a['price_time_s'][row])
            for name,value in data.items():v[FIELDS.index(name)]=value
            rows.append(v)
    return dict(events=np.asarray(rows,float).reshape((-1,len(FIELDS))),fields=list(FIELDS),
        price_valid_mask=np.array([reason(a,i,start,end)==0 for i in range(len(a['raw_seq']))],bool))


def fixture(symbol: str,mirror: bool=False) -> tuple:
    """
    機能: 多数公開・同時計・順逆到達を持つ価格経路を合成する。
    引数: symbol(str)、mirror(bool) は価格水準と価格鏡映の指定。
    返り値: tuple はarrays/signal/symbol/start/end/tick/time_policy。
    """
    base=4000. if symbol=='TOPIX' else 70000.;tick=.5 if symbol=='TOPIX' else 10.
    path=np.array([0,0,.0003,.0007,.0011,.0017,.0022,.001,.0002,-.0006,-.0012,-.0023,
        -.001,.0001,.0006,.0016,.0026,.0011,0,-.0011,-.0022,0,0,0])
    mid=base+np.rint(base*path/tick)*tick
    if mirror:mid=2*base-mid
    n=len(mid);a=dict(raw_seq=np.arange(n,dtype=np.int64),price_time_s=np.arange(n,dtype=float),
        bid=mid-tick/2,ask=mid+tick/2,bid_qty=np.full(n,20.),ask_qty=np.full(n,10.),
        best_quantity_valid=np.ones(n,bool),price_reset_reason=np.zeros(n,np.uint16),
        volume_delta_known=np.ones(n,bool),volume_delta_observed=np.ones(n))
    pubs=[1,4,7,10,14,18,22];directions=[(-1 if mirror else 1)*(1 if j%2==0 else -1) for j in range(len(pubs))]
    for row,d in zip(pubs,directions):a['bid_qty'][row]=20. if d>0 else 10.;a['ask_qty'][row]=10. if d>0 else 20.
    start=0.;end=1000.;s=events(a,pubs,directions,start,end)
    policy=dict(entry_start_s=0.,entry_end_s=400.,force_start_s=700.,quiet_windows=np.empty((0,2)))
    return a,s,symbol,start,end,tick,policy


def oracle(data: tuple) -> dict:
    """
    機能: 区間木を使わず公開ごと全未来を逐次走査する独立期待を返す。
    引数: data(tuple) は合成列・信号・方針。
    返り値: dict はlabel/終端/資格/極値等。Fractionの各注文料を点へ換算する。
    """
    a,s,symbol,start,end,tick,policy=data;ev=s['events'];n=len(a['raw_seq']);e=len(ev)
    widths=(Fraction(1,2000),Fraction(1,1000),Fraction(1,500));cap=10 if symbol=='TOPIX' else 20;mult=1000 if symbol=='TOPIX' else 10
    one=Fraction(209,5)*cap if symbol=='TOPIX' else Fraction(11)*cap
    cost=Fraction(2*(one.numerator//one.denominator),cap*mult)
    pub=ev[:,3].astype(int);d=ev[:,4].astype(int)
    lab=np.full((e,3,2),-2,np.int8);term=np.full((e,3,2),-1,np.int64)
    er=np.zeros(e,np.uint8);entry=np.full(e,-1,np.int64);ep=np.full(e,np.nan)
    mfe=np.full((e,2),np.nan);mae=np.full((e,2),np.nan);ends=np.full((e,2),-1,np.int64)
    eligible=np.zeros((e,3),bool);eligreason=np.zeros(e,np.uint8)
    for k,p in enumerate(pub):
        typ=int(ev[k,0]);dr=int(d[k]);t=a['price_time_s'][p]
        raw=[typ==0,typ==1 and ev[k,15]>=ev[k,13],False]
        own,other=(ev[k,9],ev[k,10]) if dr>0 else (ev[k,10],ev[k,9]);raw[2]=raw[1] and own>=other
        if not policy['entry_start_s']<=t<policy['entry_end_s']:eligreason[k]|=1
        if any(lo<=t<hi for lo,hi in policy['quiet_windows']):eligreason[k]|=2
        if not a['best_quantity_valid'][p] or not np.isfinite(a['bid_qty'][p]) or not np.isfinite(a['ask_qty'][p]) or min(a['bid_qty'][p],a['ask_qty'][p])<=0:eligreason[k]|=4
        if a['ask'][p]-a['bid'][p]>=2*tick:eligreason[k]|=8
        eligible[k]=np.array(raw)&(eligreason[k]==0)
        x=p+1
        if x>=n:er[k]|=1
        else:
            if a['raw_seq'][x]!=a['raw_seq'][p]+1:er[k]|=2
            if reason(a,x,start,end):er[k]|=4
            if not a['best_quantity_valid'][x] or not np.isfinite(a['bid_qty'][x]) or not np.isfinite(a['ask_qty'][x]) or min(a['bid_qty'][x],a['ask_qty'][x])<=0:er[k]|=8
            if er[k]==0:entry[k]=x;ep[k]=a['ask'][x] if dr>0 else a['bid'][x]
        public=(Fraction(str(a['bid'][p]))+Fraction(str(a['ask'][p])))/2
        for origin in (0,1):
            if origin and er[k]:continue
            reference=public if origin==0 else Fraction(str(ep[k]));fee=Fraction() if origin==0 else cost
            scores=[];end_code=2;end_row=n-1;right=n
            for row in range(p+1,n):
                why=reason(a,row,start,end)
                if why:end_code=3 if why==64 else 0;end_row=row;right=row;break
                price=(Fraction(str(a['bid'][row]))+Fraction(str(a['ask'][row])))/2 if origin==0 else Fraction(str(a['bid'][row] if dr>0 else a['ask'][row]))
                score=dr*(price-reference)-fee;scores.append(score)
                for w,alpha in enumerate(widths):
                    if lab[k,w,origin]!=-2:continue
                    if score>=public*alpha:lab[k,w,origin]=1;term[k,w,origin]=row
                    elif score<=-public*alpha:lab[k,w,origin]=-1;term[k,w,origin]=row
            for w in range(3):
                if lab[k,w,origin]==-2:lab[k,w,origin]=end_code;term[k,w,origin]=end_row
            ends[k,origin]=right
            if scores:mfe[k,origin]=float(max(scores));mae[k,origin]=float(min(scores))
    selected=np.zeros((e,3),bool)
    for rule in range(3):
        busy=-1
        for k,p in enumerate(pub):
            if eligible[k,rule] and p>busy:selected[k,rule]=True;busy=max(term[k,2,:])
    return dict(labels=lab,terminal_rows=term,entry_rows=entry,entry_prices=ep,entry_available=er==0,
        entry_reason_mask=er,eligible=eligible,nonoverlap=selected,mfe=mfe,mae=mae,continuous_end_exclusive=ends,
        eligibility_reason_mask=eligreason,roundtrip_fee_points=float(cost))


def play(data: tuple,python: bool=False) -> tuple[dict,int]:
    """
    機能: 読取専用合成列で本体を動かし、独立直走査・有限JSON・入力不変を確認する。
    引数: data(tuple)、python(bool) は素材とPython対照指定。
    返り値: tuple[dict,int] は出力と比較数。旧経済source又はJIT保存を変更しない。
    """
    a,s,symbol,start,end,tick,policy=data
    aa={k:v.copy() for k,v in a.items()};ss=dict(s,events=s['events'].copy(),price_valid_mask=s['price_valid_mask'].copy())
    for value in aa.values():value.flags.writeable=False
    ss['events'].flags.writeable=False;ss['price_valid_mask'].flags.writeable=False
    names=('_price_reasons','_trees','_first','_range','_score','_nonoverlap');original={name:getattr(engine,name) for name in names}
    try:
        if python:
            for name,value in original.items():setattr(engine,name,value.py_func)
        out=engine.measure(aa,ss,symbol,start,end,tick,policy)
    finally:
        for name,value in original.items():setattr(engine,name,value)
    checks=0;wanted=oracle(data)
    for key,value in wanted.items():
        np.testing.assert_allclose(out[key],value,rtol=1e-12,atol=1e-8,equal_nan=True);checks+=int(np.asarray(value).size)
    for key in a:np.testing.assert_array_equal(aa[key],a[key]);checks+=1
    np.testing.assert_array_equal(out['events'],s['events']);checks+=1
    json.loads(json.dumps(safe(out),ensure_ascii=False,allow_nan=False));checks+=1
    assert np.all(out['nonoverlap']<=out['eligible']);checks+=1
    assert np.all(out['mfe'][np.isfinite(out['mfe'])]>=out['mae'][np.isfinite(out['mfe'])]);checks+=1
    return out,checks


def rebuild(data: tuple,pubs: list[int] | None=None,directions: list[int] | None=None) -> tuple:
    """
    機能: 故意の欠測又は価格変更後に、変更当時の公開値だけを合成し直す。
    引数: data(tuple)、pubs/directions(list[int]|None) は観測と任意の公開位置。
    返り値: tuple は整合する合成入力。未来採点値を公開列へ戻さない。
    """
    a,s,symbol,start,end,tick,policy=data
    if pubs is None:
        source=s['events'][s['events'][:,0]==0];pubs=source[:,3].astype(int).tolist();directions=source[:,4].astype(int).tolist()
    return a,events(a,pubs,directions,start,end),symbol,start,end,tick,policy


def main() -> None:
    """
    機能: 二起点/反転/接頭/打切/三幅共通選択/C元d等を実素材なしで固定する。
    引数: なし。
    返り値: None。成功又はFalseを新保存し、大入力・金融・APIへ接続しない。
    """
    assert not ART.exists() and not (HERE/'人工False.json').exists()
    source=sources();checks=0;accounts=0;prefixes=0
    try:
        for symbol in ('TOPIX','NK225'):
            for mirror in (False,True):
                data=fixture(symbol,mirror);out,n=play(data);checks+=n;accounts+=1
                py,n=play(data,python=True);checks+=n
                for key in ('labels','terminal_rows','terminal_reason_mask','eligible','nonoverlap','mfe','mae','entry_rows','continuous_end_exclusive'):
                    np.testing.assert_array_equal(out[key],py[key]);checks+=1
                a,s,y,start,end,tick,policy=data
                for cut in range(2,len(a['raw_seq'])+1):
                    small={k:v[:cut].copy() for k,v in a.items()};sig=dict(s,events=s['events'][s['events'][:,3]<cut].copy(),price_valid_mask=s['price_valid_mask'][:cut].copy())
                    short,n=play((small,sig,y,start,end,tick,policy));checks+=n;prefixes+=1;e=len(sig['events'])
                    for key in ('eligible','nonoverlap'):
                        np.testing.assert_array_equal(short[key],out[key][:e]);checks+=1
                    resolved=np.isin(short['labels'],[-1,1])
                    np.testing.assert_array_equal(short['labels'][resolved],out['labels'][:e][resolved]);checks+=1
                    np.testing.assert_array_equal(short['terminal_rows'][resolved],out['terminal_rows'][:e][resolved]);checks+=1
                # ----------------------------------------
                # 同じ観測点で予測dだけ反転。midの物理先着を独立標本へ水増ししない。
                flipped=dict(s,events=s['events'].copy());flipped['events'][:,4]*=-1
                reverse,n=play((a,flipped,y,start,end,tick,policy));checks+=n;accounts+=1
                physical=np.isin(out['labels'][:,:,0],[-1,1]);np.testing.assert_array_equal(reverse['labels'][:,:,0][physical],-out['labels'][:,:,0][physical]);checks+=1
                np.testing.assert_array_equal(reverse['terminal_rows'][:,:,0],out['terminal_rows'][:,:,0]);checks+=1
                np.testing.assert_allclose(reverse['mfe'][:,0],-out['mae'][:,0],equal_nan=True);checks+=1
                # ----------------------------------------
                # 未来価格/方向の改変は、既観測時点の資格・非重複選択を変えない。
                future=fixture(symbol,mirror);fa,fs,*_=future
                fa['bid'][12:]+=30*tick;fa['ask'][12:]+=30*tick
                for ev in fs['events']:
                    if ev[3]>=12:ev[4]*=-1
                changed,n=play(rebuild(future));checks+=n;accounts+=1
                before=out['events'][:,3]<12
                for key in ('eligible','nonoverlap'):
                    np.testing.assert_array_equal(out[key][before],changed[key][before]);checks+=1
            # ----------------------------------------
            # 直後の価格/seq/量不正はentry不可。後正常へ繰り延べない。
            for kind in ('price','sequence','quantity'):
                data=fixture(symbol);a,s,*_=data
                if kind=='price':a['bid'][2]=np.nan
                elif kind=='sequence':a['raw_seq'][2:]+=1
                else:a['best_quantity_valid'][2]=False
                out,n=play(rebuild(data,[1],[1]));checks+=n;accounts+=1
                assert not out['entry_available'].any() and np.all(out['entry_rows']==-1);checks+=2
                assert np.all(out['labels'][:,:,1]==-2) and np.all(out['terminal_rows'][:,:,1]==-1);checks+=2
            # ----------------------------------------
            # entry以後のQty/V欠測は、価格連続区間と採点を切らない。
            base=rebuild(fixture(symbol),[1],[1]);reference,n=play(base);checks+=n
            a,s,*_=base;a['best_quantity_valid'][3:]=False;a['bid_qty'][3:]=np.nan
            a['volume_delta_known'][3:]=False;a['volume_delta_observed'][3:]=np.nan
            out,n=play(base);checks+=n;accounts+=1
            for key in ('labels','terminal_rows','mfe','mae','continuous_end_exclusive'):
                np.testing.assert_array_equal(out[key],reference[key]);checks+=1
            # ----------------------------------------
            # 公開spreadだけ資格。arrival拡幅でも参照entryを取消さず当行逆先になり得る。
            data=rebuild(fixture(symbol),[1],[1]);a,s,*_=data;a['ask'][2]=a['bid'][2]+20*(.5 if symbol=='TOPIX' else 10.)
            out,n=play(data);checks+=n;accounts+=1
            assert out['eligible'][out['events'][:,0]==0,0].all() and out['entry_available'].all();checks+=2
            assert np.all(out['labels'][:,0,1]==-1) and np.all(out['terminal_rows'][:,0,1]==2);checks+=2
            # ----------------------------------------
            # 窓末・EOF・seqgap同時窓末を別終端として保全する。
            for kind in ('window','eof','gap_window','reset','clock','bbo'):
                data=rebuild(fixture(symbol),[1],[1]);a,s,y,start,end,tick,policy=data
                a['bid'][:]=a['bid'][1];a['ask'][:]=a['ask'][1]
                if kind in ('window','gap_window'):a['price_time_s'][8:]=end
                if kind=='gap_window':a['raw_seq'][8:]+=1
                if kind=='reset':a['price_reset_reason'][8]=8
                if kind=='clock':a['price_time_s'][8]=-1
                if kind=='bbo':a['ask'][8]=np.nan
                out,n=play(rebuild(data,[1],[1]));checks+=n;accounts+=1
                expected=3 if kind=='window' else 2 if kind=='eof' else 0
                assert np.all(out['labels'][:,:,0]==expected);checks+=1
            # ----------------------------------------
            # 常に負の気配評価MFEも負で保持。時刻静観は未来観測を打ち切らない。
            data=rebuild(fixture(symbol),[1],[1]);a,s,y,start,end,tick,policy=data
            a['bid'][:]=a['bid'][1];a['ask'][:]=a['ask'][1];policy['quiet_windows']=np.array([[2.,100.]])
            out,n=play(rebuild(data,[1],[1]));checks+=n;accounts+=1
            assert out['eligible'][out['events'][:,0]==0,0].all() and out['entry_available'].all();checks+=2
            assert np.all(out['mfe'][:,1]<0) and np.all(out['mae'][:,1]<0);checks+=2
            assert np.all(out['labels'][:,:,0]==2);checks+=1
            # ----------------------------------------
            # 完全空の公開表も同じshapeと有限JSON保存契約を満たす。
            out,n=play(rebuild(fixture(symbol),[],[]));checks+=n;accounts+=1
            assert out['labels'].shape==(0,3,2) and out['nonoverlap'].shape==(0,3);checks+=2
        # ----------------------------------------
        # ランダム刻み価格を独立Fraction直走査へ照合する。実観測は一切使わない。
        rng=np.random.default_rng(117)
        for case in range(100):
            symbol='TOPIX' if case%2==0 else 'NK225';data=fixture(symbol);a,s,y,start,end,tick,policy=data
            base=4000. if symbol=='TOPIX' else 70000.;mid=base+np.cumsum(rng.integers(-15,16,len(a['raw_seq'])))*tick
            a['bid']=mid-tick/2;a['ask']=mid+tick/2
            if case%5==0:a['price_reset_reason'][12]=8
            out,n=play(rebuild(data));checks+=n;accounts+=1
        assert source==sources()
        proof=dict(全合格=True,source_SHA256=source,比較数=checks,合成素材=accounts,接頭=prefixes,
            原NPZ=0,保存events=0,金融本文=0,金融再生=0,原板=0,API=0,
            方法='独立Fraction逐次走査、全compiled helperのPython/JIT、readonly、全出力JSON統合。',
            仕様='三幅同じ選択。最大幅の両起点の遅い終端rowまでlock。Cは元d。未来量欠測をpricecutへ使用しない。',
            極値='mfe=max(score),mae=min(score)の符号付き点。entry側の全時点負MFEもclipなし。',
            留保='非金融の価格応答と気配評価であり、約定勝率・手数料後の実金融成績・独立な新標本ではない。')
        ART.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,比較数=checks,合成素材=accounts,接頭=prefixes,source_SHA256=source,
            SHA256=hashlib.sha256(ART.read_bytes()).hexdigest()),ensure_ascii=False))
    except BaseException:
        (HERE/'人工False.json').write_text(json.dumps(dict(全合格=False,source_SHA256=source,比較数=checks,
            原因=traceback.format_exc(),実入力=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':
    main()
