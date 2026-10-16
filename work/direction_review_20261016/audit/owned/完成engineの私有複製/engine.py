"""外部IOなしで、保存公開の三資格と三値幅・二起点の場内価格先着を測る。"""

import numpy as np
from numba import njit


WIDTHS=np.array([.0005,.001,.002],dtype=np.float64)
RULE_NAMES=['A','B','C']
ORIGIN_NAMES=['publication_mid','next_raw_net_quote']
CODE_NAMES={1:'方向順先',-1:'方向逆先',0:'価格資格切断',2:'原EOF',3:'観測窓末',-2:'直後entry不可'}
PRICE_REASON_BITS={1:'価格時計非有限',2:'価格時計が窓開始前',4:'最良両価格不正',8:'原seq不連続',
    16:'直前価格時計非有限',32:'価格時計逆行又はreset8',64:'観測窓末以上'}
TERMINAL_REASON_BITS={**PRICE_REASON_BITS,128:'原EOF',256:'直後entry不可'}
ELIGIBILITY_REASON_BITS={1:'公開時間外',2:'公開時静観',4:'公開時執行正常でない',8:'公開spreadが2T以上'}
ENTRY_REASON_BITS={1:'直後raw未観測',2:'直後rawのseq不連続',4:'直後価格不明',8:'直後数量不明'}
CAP={'TOPIX':10,'NK225':20}
MULT={'TOPIX':1000.,'NK225':10.}
FEE={'TOPIX':(418,10),'NK225':(11,1)}


@njit(cache=False)
def _price_reasons(seq,pt,bid,ask,reset,start,end):
    """
    機能: 114と同じ価格資格の理由を数量・出来高から分離する。
    引数: 原列(ndarray)、start/end(float) は旧保存価格時計の観測窓。
    返り値: ndarray[uint16] は重複可の理由。窓末だけの到達を別bitにする。
    """
    reasons=np.zeros(len(seq),np.uint16)
    for i in range(len(seq)):
        reason=0
        if not np.isfinite(pt[i]):reason|=1
        elif pt[i]<start:reason|=2
        elif pt[i]>=end:reason|=64
        if not(np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0<bid[i]<ask[i]):reason|=4
        if i:
            if seq[i]!=seq[i-1]+1:reason|=8
            if not np.isfinite(pt[i-1]):reason|=16
            elif np.isfinite(pt[i]) and pt[i]<pt[i-1]:reason|=32
        if reset[i]&8:reason|=32
        reasons[i]=reason
    return reasons


@njit(cache=False)
def _trees(mid,bid,ask,valid):
    """
    機能: mid/bid/askそれぞれのmin/max区間木を一度構築する。
    引数: mid/bid/ask/valid(ndarray) は価格と価格資格。
    返り値: tuple は最大木・最小木・葉容量。未知価格を有限値へ補完しない。
    """
    size=1
    while size<len(mid):size*=2
    high=np.full((3,size*2),-np.inf);low=np.full((3,size*2),np.inf)
    for i in range(len(mid)):
        if valid[i]:
            high[0,size+i]=mid[i];low[0,size+i]=mid[i]
            high[1,size+i]=bid[i];low[1,size+i]=bid[i]
            high[2,size+i]=ask[i];low[2,size+i]=ask[i]
    for j in range(size-1,0,-1):
        for series in range(3):
            high[series,j]=max(high[series,j*2],high[series,j*2+1])
            low[series,j]=min(low[series,j*2],low[series,j*2+1])
    return high,low,size


@njit(cache=False)
def _first(high,low,series,node,lo,hi,left,right,threshold,above):
    """
    機能: 単一価格の閾値へ等号を含めて初到達する原行を探す。
    引数: 木(ndarray)、位置/範囲(int)、threshold(float)、above(bool) は照会条件。
    返り値: int は最初の原行又は−1。公開行への巻戻しを行わない。
    """
    if right<=lo or hi<=left:return -1
    if above:
        if high[series,node]<threshold:return -1
    elif low[series,node]>threshold:return -1
    if hi-lo==1:return lo
    middle=(lo+hi)//2
    first=_first(high,low,series,node*2,lo,middle,left,right,threshold,above)
    if first>=0:return first
    return _first(high,low,series,node*2+1,middle,hi,left,right,threshold,above)


@njit(cache=False)
def _range(high,low,series,left,right,size):
    """
    機能: 価格連続区間の最大・最小を反復区間照会で求める。
    引数: 木(ndarray)、series/left/right/size(int) は価格種類と排他的範囲。
    返り値: tuple[float,float] は最大・最小。空区間は呼出し側で未測のまま残す。
    """
    maximum=-np.inf;minimum=np.inf;left+=size;right+=size
    while left<right:
        if left&1:
            maximum=max(maximum,high[series,left]);minimum=min(minimum,low[series,left]);left+=1
        if right&1:
            right-=1;maximum=max(maximum,high[series,right]);minimum=min(minimum,low[series,right])
        left//=2;right//=2
    return maximum,minimum


@njit(cache=False)
def _score(pub,direction,public_mid,entry_price,entry_available,mid,bid,ask,valid,reasons,widths,fee_points):
    """
    機能: 全保存公開を二起点三幅で採点し、全連続区間の符号付き極値を得る。
    引数: 候補/価格/資格(ndarray)、fee_points(float) は参照起点と全量往復料点。
    返り値: tuple は先着code・終端row/reason・極値・連続区間末。未来は採点にだけ用いる。
    """
    n=len(mid);e=len(pub);high,low,size=_trees(mid,bid,ask,valid)
    next_bad=np.full(n+1,n,np.int64)
    for i in range(n-1,-1,-1):next_bad[i]=i if not valid[i] else next_bad[i+1]
    labels=np.full((e,len(widths),2),-2,np.int8)
    terminal=np.full((e,len(widths),2),-1,np.int64)
    terminal_reason=np.full((e,len(widths),2),256,np.uint16)
    mfe=np.full((e,2),np.nan);mae=np.full((e,2),np.nan)
    continuous_end=np.full((e,2),-1,np.int64)
    for k in range(e):
        left=int(pub[k])+1;right=next_bad[left];d=int(direction[k])
        end_row=right if right<n else n-1
        end_reason=int(reasons[right]) if right<n else 128
        end_code=3 if end_reason==64 else 0 if right<n else 2
        for origin in range(2):
            if origin==1 and not entry_available[k]:continue
            continuous_end[k,origin]=right
            series=0 if origin==0 else 1 if d>0 else 2
            reference=public_mid[k] if origin==0 else entry_price[k]
            cost=0. if origin==0 else fee_points
            if left<right:
                maximum,minimum=_range(high,low,series,left,right,size)
                mfe[k,origin]=d*((maximum if d>0 else minimum)-reference)-cost
                mae[k,origin]=d*((minimum if d>0 else maximum)-reference)-cost
            for w in range(len(widths)):
                width=public_mid[k]*widths[w]
                assert np.isfinite(width) and width>0
                favourable=reference+d*(cost+width);adverse=reference+d*(cost-width)
                assert np.isfinite(favourable) and np.isfinite(adverse)
                plus=_first(high,low,series,1,0,size,left,right,favourable,d>0) if left<right else -1
                minus=_first(high,low,series,1,0,size,left,right,adverse,d<0) if left<right else -1
                assert plus<0 or minus<0 or plus!=minus
                if plus>=0 and (minus<0 or plus<minus):
                    labels[k,w,origin]=1;terminal[k,w,origin]=plus;terminal_reason[k,w,origin]=0
                elif minus>=0:
                    labels[k,w,origin]=-1;terminal[k,w,origin]=minus;terminal_reason[k,w,origin]=0
                else:
                    labels[k,w,origin]=end_code;terminal[k,w,origin]=end_row;terminal_reason[k,w,origin]=end_reason
    return labels,terminal,terminal_reason,mfe,mae,continuous_end


@njit(cache=False)
def _nonoverlap(pub,eligible,terminal,entry_available):
    """
    機能: 三資格それぞれで、最大幅二起点の遅い終端まで新候補を重ねない。
    引数: pub/eligible/terminal/entry_available(ndarray) は全候補の時系列と採点終端。
    返り値: ndarray[bool,E,3] は共通選択。終端当行の候補も消費せず選外とする。
    """
    selected=np.zeros(eligible.shape,np.bool_)
    for rule in range(3):
        locked_until=-1
        for k in range(len(pub)):
            if eligible[k,rule] and pub[k]>locked_until:
                selected[k,rule]=True
                locked_until=int(terminal[k,2,0])
                if entry_available[k]:locked_until=max(locked_until,int(terminal[k,2,1]))
    return selected


def measure(arrays: dict,signal: dict,symbol: str,start: float,end: float,tick: float,time_policy: dict) -> dict:
    """
    機能: 114保存事象を過去資格で分類し、価格応答と評価気配の先着を共有計算する。
    引数: arrays/signal/time_policy(dict)、symbol(str)、start/end/tick(float) は読取済み素材と既入口方針。
    返り値: dict はfields付き全保存事象・二起点三幅label・三資格mask・極値・理由/件数。
    原配列変更・外部IO・注文・金融・未来を用いた公開採否は行わない。
    """
    assert symbol in CAP and np.isfinite(start) and np.isfinite(end) and start<end and np.isfinite(tick) and tick>0
    names=('raw_seq','price_time_s','bid','ask','bid_qty','ask_qty','best_quantity_valid','price_reset_reason')
    n=len(arrays['raw_seq']);assert n>0
    assert all(isinstance(arrays[k],np.ndarray) and arrays[k].shape==(n,) for k in names)
    seq,pt,bid,ask=(arrays[k] for k in ('raw_seq','price_time_s','bid','ask'))
    assert np.issubdtype(seq.dtype,np.integer) and np.all((seq>=0)&(seq<2**53))
    assert arrays['best_quantity_valid'].dtype==bool and np.issubdtype(arrays['price_reset_reason'].dtype,np.integer)
    valid=np.asarray(signal['price_valid_mask']);assert valid.shape==(n,) and valid.dtype==bool
    reasons=_price_reasons(seq,pt,bid,ask,arrays['price_reset_reason'],start,end)
    np.testing.assert_array_equal(valid,reasons==0)
    quantity=arrays['best_quantity_valid']&np.isfinite(arrays['bid_qty'])&np.isfinite(arrays['ask_qty'])&(arrays['bid_qty']>0)&(arrays['ask_qty']>0)
    normal=valid&quantity
    events=np.asarray(signal['events']);fields=list(signal['fields'])
    assert events.ndim==2 and events.shape[1]==len(fields) and len(fields)==len(set(fields)) and np.isfinite(events).all()
    col={name:events[:,fields.index(name)] for name in ('pub_i','d','type','episode','opposite_q0','opposite_min_q','bid_q_at_public','ask_q_at_public','bid','ask','pub_raw_seq','pub_price_time_s')}
    pub=col['pub_i'].astype(np.int64);direction=col['d'].astype(np.int64);types=col['type'].astype(np.int64)
    assert np.array_equal(pub,col['pub_i']) and np.array_equal(direction,col['d']) and np.array_equal(types,col['type'])
    assert np.all((pub>=0)&(pub<n)) and np.all(np.diff(pub)>=0) and np.all(np.isin(direction,[-1,1])) and np.all(np.isin(types,[0,1]))
    assert np.all(valid[pub]) and np.all(col['opposite_q0']>0)
    for saved,original in (('bid',bid),('ask',ask),('pub_raw_seq',seq),('pub_price_time_s',pt),('bid_q_at_public',arrays['bid_qty']),('ask_q_at_public',arrays['ask_qty'])):
        np.testing.assert_array_equal(col[saved],original[pub])
    quiet=np.asarray(time_policy['quiet_windows'],np.float64).reshape((-1,2))
    assert np.isfinite(quiet).all() and np.all(quiet[:,0]<quiet[:,1])
    entry_start=float(time_policy['entry_start_s']);entry_end=float(time_policy['entry_end_s'])
    assert start<=entry_start<entry_end<=end
    eligibility=np.zeros(len(pub),np.uint8)
    eligibility[(pt[pub]<entry_start)|(pt[pub]>=entry_end)]|=1
    for lo,hi in quiet:eligibility[(lo<=pt[pub])&(pt[pub]<hi)]|=2
    eligibility[~normal[pub]]|=4
    eligibility[ask[pub]-bid[pub]>=2*tick]|=8
    raw_group=np.zeros((len(pub),3),bool);raw_group[:,0]=types==0
    raw_group[:,1]=(types==1)&(col['opposite_min_q']>=col['opposite_q0'])
    own=np.where(direction>0,col['bid_q_at_public'],col['ask_q_at_public'])
    opposite=np.where(direction>0,col['ask_q_at_public'],col['bid_q_at_public'])
    raw_group[:,2]=raw_group[:,1]&(own>=opposite)
    eligible=raw_group&(eligibility[:,None]==0)
    entry_rows=np.full(len(pub),-1,np.int64);entry_prices=np.full(len(pub),np.nan)
    entry_reason=np.zeros(len(pub),np.uint8)
    for k,row in enumerate(pub):
        next_row=int(row)+1
        if next_row>=n:entry_reason[k]|=1;continue
        if seq[next_row]!=seq[row]+1:entry_reason[k]|=2
        if not valid[next_row]:entry_reason[k]|=4
        if not quantity[next_row]:entry_reason[k]|=8
        if entry_reason[k]==0:
            entry_rows[k]=next_row;entry_prices[k]=ask[next_row] if direction[k]>0 else bid[next_row]
    available=entry_reason==0
    mid=bid*.5+ask*.5;public_mid=mid[pub]
    numerator,denominator=FEE[symbol];roundtrip_fee=2*(CAP[symbol]*numerator//denominator)
    fee_points=roundtrip_fee/(CAP[symbol]*MULT[symbol])
    labels,terminal,terminal_reason,mfe,mae,continuous_end=_score(pub,direction,public_mid,entry_prices,available,mid,bid,ask,valid,reasons,WIDTHS,fee_points)
    selected=_nonoverlap(pub,eligible,terminal,available)
    counts=dict(saved_events=len(events),raw_rows=n,price_known_rows=int(valid.sum()),execution_normal_rows=int(normal.sum()),
        entry_available=int(available.sum()),entry_unavailable=int((~available).sum()),
        eligibility_reason_counts={str(bit):int(np.count_nonzero(eligibility&bit)) for bit in ELIGIBILITY_REASON_BITS},
        entry_reason_counts={str(bit):int(np.count_nonzero(entry_reason&bit)) for bit in ENTRY_REASON_BITS},
        price_reason_counts={str(bit):int(np.count_nonzero(reasons&bit)) for bit in PRICE_REASON_BITS},
        rules={name:dict(source_candidates=int(raw_group[:,i].sum()),eligible=int(eligible[:,i].sum()),nonoverlap=int(selected[:,i].sum())) for i,name in enumerate(RULE_NAMES)})
    return dict(events=events.copy(),fields=fields,widths=WIDTHS.tolist(),rule_names=list(RULE_NAMES),origin_names=list(ORIGIN_NAMES),
        labels=labels,terminal_rows=terminal,terminal_reason_mask=terminal_reason,eligible=eligible,nonoverlap=selected,source_qualified=raw_group,
        entry_available=available,entry_rows=entry_rows,entry_prices=entry_prices,entry_reason_mask=entry_reason,
        public_mid=public_mid,roundtrip_fee_yen=roundtrip_fee,roundtrip_fee_points=fee_points,
        mfe=mfe,mae=mae,continuous_end_exclusive=continuous_end,price_valid_mask=valid.copy(),price_reason_mask=reasons,
        execution_normal_mask=normal,eligibility_reason_mask=eligibility,counts=counts,
        code_names=dict(CODE_NAMES),price_reason_bits=dict(PRICE_REASON_BITS),terminal_reason_bits=dict(TERMINAL_REASON_BITS),
        eligibility_reason_bits=dict(ELIGIBILITY_REASON_BITS),entry_reason_bits=dict(ENTRY_REASON_BITS),
        definition=dict(width='H=公開mid×alpha、丸めなし。全三幅で同じ非重複候補を用いる。',
            origin1='公開rowの次raw以降の方向付きmid変化。常時買売は同じ物理先着から派生する。',
            origin2='直後seq+1の執行正常原rowだけで新規ask/bidを参照し、同rowから将来返済bid/ask−全量往復floor料点を評価。実返済約定勝率でない。',
            future='先着後もMFE/MAEは価格連続区間末まで。未来Qty/V欠測だけでは打切らない。',
            extrema='mfe=max(score),mae=min(score)の符号付き点。両方負も保持し0へclipしない。',
            nonoverlap='rule別。最大幅二起点の遅い終端rowの次row以後だけ新候補。entry不可ならmid起点だけ。',
            censor='窓末だけの不正時計は3。同rowのseqgap/逆行/価格不正等を伴えば0。N到達は常に2、end−1秒を窓完了へ補完しない。',
            scope='CurrentPriceTime模型。真の受信順・注文・金融・独立した利益標本は未測。'))
