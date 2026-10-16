"""原入力を読まず、数量事象と両BBO先着を直接走査の独立期待へ照合する。"""

import hashlib
import json
import math
from pathlib import Path
import traceback

import numpy as np

import engine

HERE=Path(__file__).resolve().parent
ART=HERE/'固定BBO数量と公表活動及び価格先着の人工検査.json'


def hashes() -> dict:
    """
    機能: 二つの新私有sourceだけを開始終端の指紋へ束縛する。
    引数: なし。
    返り値: dict[str,str] はファイル名とSHA256。入力を開かない。
    """
    return {n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in ('engine.py','artificial_engine.py')}


def fixture(n: int=8) -> dict:
    """
    機能: 同BBOの初正増・閾値等号・反方向正増を持つ原行を合成する。
    引数: n(int) は合成行数。
    返り値: dict は必要列。元44列の本文又は金融は読まない。
    """
    bid=np.full(n,100.);ask=np.full(n,101.)
    if n>4:bid[4:]=101.;ask[4:]=102.
    volume=np.zeros(n)
    if n>0:volume[0]=99.
    if n>1:volume[1]=2.
    if n>2:volume[2]=3.
    last=ask.copy()
    if n>2:last[2]=100.
    return dict(raw_seq=np.arange(n,dtype=np.int64),price_time_s=np.arange(n,dtype=float),last=last,
        bid=bid,ask=ask,bid_qty=np.full(n,10.),ask_qty=np.full(n,5.),
        best_quantity_valid=np.ones(n,bool),volume_delta_known=np.ones(n,bool),
        volume_delta_observed=volume,volume_time_s=np.arange(n,dtype=float),price_reset_reason=np.zeros(n,np.uint16))


def oracle_price(a: dict,start: float,end: float) -> np.ndarray:
    """
    機能: 必要な価格資格だけをPython逐次条件で独立に求める。
    引数: a(dict)、start/end(float) は合成原行と場内範囲。
    返り値: ndarray[bool] は価格mask。数量・出来高を参照しない。
    """
    out=[]
    for i,t in enumerate(a['price_time_s']):
        good=bool(math.isfinite(t) and start<=t<end and math.isfinite(a['bid'][i]) and math.isfinite(a['ask'][i])
                  and 0<a['bid'][i]<a['ask'][i] and not (a['price_reset_reason'][i]&8))
        if i:
            good=bool(good and a['raw_seq'][i]==a['raw_seq'][i-1]+1 and math.isfinite(a['price_time_s'][i-1]) and t>=a['price_time_s'][i-1])
        out.append(good)
    return np.asarray(out,bool)


def oracle_events(a: dict,start: float,end: float) -> list[dict]:
    """
    機能: 最大の同BBO有資格runを先に切り、各run内の初正増と閾値を集合的に求める。
    引数: a(dict)、start/end(float) は合成原行と期間。
    返り値: list[dict] は独立期待の主事象。実装の状態関数を呼ばない。
    """
    valid=oracle_price(a,start,end);runs=[];current=[]
    for i in range(len(valid)):
        ok=bool(valid[i] and a['best_quantity_valid'][i] and math.isfinite(a['bid_qty'][i]) and a['bid_qty'][i]>0
            and math.isfinite(a['ask_qty'][i]) and a['ask_qty'][i]>0 and a['volume_delta_known'][i]
            and math.isfinite(a['volume_delta_observed'][i]) and a['volume_delta_observed'][i]>=0)
        same=bool(current and a['bid'][current[0]]==a['bid'][i] and a['ask'][current[0]]==a['ask'][i])
        if current and (not ok or not same):runs.append(current);current=[]
        if ok:current.append(i)
    if current:runs.append(current)
    expected=[]
    for eid,run in enumerate(runs):
        rows=run[1:];positive=[i for i in rows if a['volume_delta_observed'][i]>0]
        if not positive:continue
        first=positive[0];last=a['last'][first]
        d=0 if not math.isfinite(last) or last<=0 else 1 if last>=a['ask'][first-1] else -1 if last<=a['bid'][first-1] else 0
        if d==0:continue
        zero=run[0];qname='ask_qty' if d>0 else 'bid_qty';q0=a[qname][zero]
        threshold=next((i for i in rows if sum(a['volume_delta_observed'][j] for j in rows if j<=i)>=q0),None)
        for typ,pub in ((0,first),(1,threshold)):
            if pub is None:continue
            expected.append(dict(type=typ,episode=eid,start_i=zero,pub_i=pub,d=d,bid=a['bid'][zero],ask=a['ask'][zero],
                opposite_q0=q0,opposite_q_at_public=a[qname][pub],opposite_min_q=min(a[qname][zero:pub+1]),
                total_volume=sum(a['volume_delta_observed'][i] for i in rows if i<=pub),
                npositive=sum(a['volume_delta_observed'][i]>0 for i in rows if i<=pub)))
    return sorted(expected,key=lambda e:(e['pub_i'],e['type']))


def oracle_outcome(a: dict,event: dict,price: np.ndarray,tick: float) -> tuple[int,int]:
    """
    機能: 公開後の原行を一つずつ調べ、価格未知又は順逆両BBOの最初を求める。
    引数: a/event(dict)、price(ndarray[bool])、tick(float)。
    返り値: tuple[int,int] はcode/end_i。将来quantity/volumeは使わない。
    """
    for i in range(int(event['pub_i'])+1,len(price)):
        if not price[i]:return 0,i
        db=event['d']*(a['bid'][i]-event['bid']);da=event['d']*(a['ask'][i]-event['ask'])
        if db>=tick and da>=tick:return 1,i
        if db<=-tick and da<=-tick:return -1,i
    return 2,len(price)-1


def safe(value: object) -> object:
    """
    機能: rootの保存統合に向け、NumPy型をJSON原始型へ写す。
    引数: value(object) は合成measure出力。
    返り値: object は非有限だけNoneで残す保存構造。計算へ戻さない。
    """
    if isinstance(value,np.ndarray):return safe(value.tolist())
    if isinstance(value,np.generic):return safe(value.item())
    if isinstance(value,float):return value if math.isfinite(value) else None
    if isinstance(value,dict):return {str(k):safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [safe(v) for v in value]
    return value


def verify(a: dict,start: float=0.,end: float=1000.,tick: float=1.) -> tuple[dict,int]:
    """
    機能: 新coreを独立run切出し・逐次先着・入力不変・保存JSONへ照合する。
    引数: a(dict)、start/end/tick(float) は合成原行と条件。
    返り値: tuple[dict,int] は実出力と比較数。旧sourceをimportしない。
    """
    before={k:v.copy() for k,v in a.items()}
    readonly={k:v.copy() for k,v in a.items()}
    for v in readonly.values():v.setflags(write=False)
    out=engine.measure(readonly,start,end,tick);price=oracle_price(a,start,end)
    np.testing.assert_array_equal(out['price_valid_mask'],price);checks=1
    expected=oracle_events(a,start,end);assert len(expected)==len(out['events']);checks+=1
    for i,e in enumerate(expected):
        actual=dict(zip(out['fields'],out['events'][i]))
        for k,v in e.items():
            assert math.isclose(actual[k],v,rel_tol=1e-12,abs_tol=1e-12),(k,actual[k],v);checks+=1
        assert tuple(out['outcomes'][i])==oracle_outcome(a,e,price,tick);checks+=1
    for k,v in a.items():np.testing.assert_array_equal(v,before[k]);checks+=1
    packed=safe(out);json.loads(json.dumps(packed,ensure_ascii=False,allow_nan=False));checks+=1
    return out,checks


def reflected(a: dict) -> dict:
    """
    機能: 買売の鏡映素材を作り、原seq/時計/出来高をそのまま保持する。
    引数: a(dict) は合成原列。
    返り値: dict はbid/ask・数量を交換し価格を定数から反転した素材。
    """
    b={k:v.copy() for k,v in a.items()}
    b['bid']=1000.-a['ask'];b['ask']=1000.-a['bid']
    b['last']=np.where(np.isfinite(a['last'])&(a['last']>0),1000.-a['last'],a['last'])
    b['bid_qty']=a['ask_qty'].copy();b['ask_qty']=a['bid_qty'].copy()
    return b


def main() -> None:
    """
    機能: 境界・未来欠測・鏡映・prefix・無作為原行を人工だけで検査し証跡を保存する。
    引数: なし。
    返り値: None。成功/Falseを保全し、原入力/金融/APIは全て0。
    """
    assert not ART.exists() and not (HERE/'人工False.json').exists()
    source=hashes();checks=0;cases=[];fixtures=[]
    try:
        a=fixture();base,n=verify(a);checks+=n
        assert len(base['events'])==2 and list(base['outcomes'][:,0])==[1,1];checks+=3
        assert base['events'][1,engine.FIELDS.index('total_volume')]==5.;checks+=1
        fixtures.append(('基本等号',a))
        for label,changes in (
            ('inside初正増凍結',{'last':(1,100.5)}),('Last不明初正増凍結',{'last':(1,np.nan)}),
            ('future数量不明',{'ask_qty':(3,np.nan)}),('futurevolume不明',{'volume_delta_known':(3,False)}),
            ('futurevolume値不明',{'volume_delta_observed':(3,np.nan)}),('future価格時計不明',{'price_time_s':(3,np.nan)}),
            ('futureBBO不明',{'ask':(3,np.nan)}),('future価格逆行',{'price_time_s':(3,1.)}),
            ('future価格reset8',{'price_reset_reason':(3,8)}),('future場外',{'price_time_s':(3,1000.)}),
            ('閾値未満',{'volume_delta_observed':(2,2.999)}),('同初正増で二型',{'volume_delta_observed':(1,5.)}),
            ('途中減少後回復',{'ask_qty':(1,4.)}),('連続表示維持',{'ask_qty':(1,6.)}),
            ('片側更新は未達',{'ask':(3,102.)}),('Last零は不明',{'last':(1,0.)}),
        ):
            b=fixture()
            for k,(i,value) in changes.items():b[k][i]=value
            o,n=verify(b);checks+=n;fixtures.append((label,b));cases.append(label)
            if label.startswith('future数量') or label.startswith('futurevolume'):
                np.testing.assert_array_equal(o['outcomes'],base['outcomes']);checks+=1
            if '凍結' in label or label=='Last零は不明':assert not len(o['events']);checks+=1
        b=fixture();b['bid'][2:4]=100.5;b['ask'][2:4]=101.5
        o,n=verify(b);checks+=n;fixtures.append(('BBO変更同rowは開始量除外',b));assert len(o['events'])==1;checks+=1
        b=fixture();b['raw_seq'][3:]+=1;o,n=verify(b);checks+=n;fixtures.append(('原seqgap',b));assert o['outcomes'][0,0]==0;checks+=1
        b=fixture();b['volume_time_s']+=100.;o,n=verify(b);checks+=n;fixtures.append(('出来高時計が先でも除外しない',b))
        np.testing.assert_array_equal(o['outcomes'],base['outcomes']);assert np.all(o['events'][:,engine.FIELDS.index('volume_after_price')]==1);checks+=2
        b=fixture();b['price_time_s'][:]=0.;b['volume_time_s'][:]=0.;o,n=verify(b);checks+=n;fixtures.append(('同価格時計後原seq',b))
        assert np.all(o['events'][:,engine.FIELDS.index('fresh_price_time')]==0) and len(o['events'])==2;checks+=1
        b=fixture(1);o,n=verify(b);checks+=n;fixtures.append(('先頭だけ',b));assert len(o['events'])==0;checks+=1
        b=fixture(3);o,n=verify(b);checks+=n;fixtures.append(('最終公開はEOF',b));assert np.all(o['outcomes'][:,0]==2);checks+=1
        prefix_count=0;mirror_count=0
        for label,a in fixtures:
            out,n=verify(a);checks+=n
            opposite,n=verify(reflected(a));checks+=n
            assert len(out['events'])==len(opposite['events']);checks+=1
            if len(out['events']):
                np.testing.assert_array_equal(out['outcomes'],opposite['outcomes']);checks+=1
                for name in ('type','episode','start_i','pub_i','total_volume','npositive','quantity_ratio','minimum_quantity_ratio','opposite_q0'):
                    j=engine.FIELDS.index(name);np.testing.assert_allclose(out['events'][:,j],opposite['events'][:,j]);checks+=1
                np.testing.assert_array_equal(out['events'][:,4],-opposite['events'][:,4]);checks+=1
            mirror_count+=1
            for cutoff in range(1,len(a['raw_seq'])+1):
                small={k:v[:cutoff].copy() for k,v in a.items()};partial,n=verify(small);checks+=n
                expected=out['events'][out['events'][:,engine.FIELDS.index('pub_i')]<cutoff]
                np.testing.assert_array_equal(partial['events'],expected);checks+=1
                for i,event in enumerate(expected):
                    full=out['outcomes'][i]
                    target=full if full[1]<cutoff else np.array([2.,cutoff-1.])
                    np.testing.assert_array_equal(partial['outcomes'][i],target);checks+=1
                prefix_count+=1
        rng=np.random.default_rng(114)
        for iteration in range(300):
            n=int(rng.integers(1,45));a=fixture(n)
            a['bid']=100.+np.cumsum(rng.choice([-.5,0.,.5],n,p=[.15,.7,.15]));a['ask']=a['bid']+rng.choice([1.,2.],n,p=[.85,.15])
            a['last']=rng.choice([-1.,0.,1.],n)+a['bid'];a['bid_qty']=rng.integers(1,8,n).astype(float);a['ask_qty']=rng.integers(1,8,n).astype(float)
            a['volume_delta_observed']=rng.integers(0,9,n).astype(float);a['volume_delta_known']=rng.random(n)>.08
            a['best_quantity_valid']=rng.random(n)>.05
            a['price_time_s']=np.cumsum(rng.choice([0.,1.],n));a['volume_time_s']=a['price_time_s']+rng.choice([-1.,0.,1.],n)
            if iteration%3==0:a['price_reset_reason'][int(rng.integers(n))]=8
            o,ncheck=verify(a);checks+=ncheck
        over=fixture();over['volume_delta_observed'][1:3]=1e308;over['ask_qty'][:]=1e308
        try:
            engine.measure(over,0.,1000.,1.)
        except AssertionError:
            checks+=1
        else:
            raise AssertionError('無限累計を通常事象へ保存')
        assert source==hashes()
        proof=dict(全合格=True,source_SHA256=source,比較数=checks,固定素材=len(fixtures),鏡映素材=mirror_count,
            prefix回数=prefix_count,無作為直接走査素材=300,実入力本文=0,NPZ=0,原板=0,金融=0,API=0,
            追加未来成績=False,数式='先着は両BBO・公開後のみ。type1>=Q0。未来数量/volumeは先着の引数にない。',
            限界='表示量維持と公表量の価格応答。真攻撃/補充/Technical/peer/損益効能は未測。')
        ART.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,比較数=checks,prefix回数=prefix_count,source_SHA256=source,
                             artifact_SHA256=hashlib.sha256(ART.read_bytes()).hexdigest()),ensure_ascii=False))
    except BaseException:
        (HERE/'人工False.json').write_text(json.dumps(dict(全合格=False,source_SHA256=source,比較数=checks,
            原因=traceback.format_exc(),実入力=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':
    main()
