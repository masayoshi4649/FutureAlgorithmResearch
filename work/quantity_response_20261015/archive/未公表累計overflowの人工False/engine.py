"""外部IOなしで、同BBO数量と公表正出来高差の事象・後続価格先着を測る。"""

import numpy as np
from numba import njit


FIELDS = [
    'type','episode','start_i','pub_i','d','bid','ask','bid_q0','ask_q0',
    'bid_q_at_public','ask_q_at_public','min_bid_q','min_ask_q',
    'opposite_q0','opposite_q_at_public','opposite_min_q','quantity_ratio','minimum_quantity_ratio',
    'quantity_group','total_volume','npositive','first_positive_i','fresh_price_time',
    'volume_after_price','volume_clock_known','first_positive_fresh_price_time',
    'first_positive_volume_after_price','first_positive_volume_clock_known',
    'start_raw_seq','pub_raw_seq','pub_price_time_s',
]
OUTCOME_FIELDS = ['code','end_i']
COUNT_FIELDS = [
    'raw_rows','price_known_rows','price_unknown_rows','quantity_unknown_rows','volume_unknown_rows',
    'volume_flag_unknown_rows','volume_observed_invalid_rows','publication_eligible_rows',
    'episodes','positive_episodes','direction_buy_episodes','direction_sell_episodes',
    'direction_zero_inside_episodes','direction_zero_last_unknown_episodes',
    'excluded_start_positive_rows','type0_events','type1_events','episode_end_price_unknown',
    'episode_end_quantity_unknown','episode_end_volume_unknown','episode_end_bbo_change','episode_end_eof',
]
PRICE_REASON_BITS = {1:'価格時計非有限',2:'価格時計場外',4:'最良両価格不正',8:'原seq不連続',
                     16:'直前価格時計非有限',32:'価格時計逆行又はreset8'}
ELIGIBILITY_REASON_BITS = {**PRICE_REASON_BITS,64:'最良両数量不明又は非正',128:'出来高差knownがfalse',
                           256:'出来高差observed非有限又は負'}


@njit(cache=False)
def _append(events, count, row):
    """
    機能: 事象bufferを必要な場合だけ倍増し、過去事象を保持して追加する。
    引数: events(ndarray[float,二次元])、count(int)、row(ndarray[float])。
    返り値: tuple[ndarray,int] は新bufferと件数。外部書込みを行わない。
    """
    if count==len(events):
        enlarged=np.empty((max(4,len(events)*2),events.shape[1]),np.float64)
        enlarged[:count]=events
        events=enlarged
    events[count]=row
    return events,count+1


@njit(cache=False)
def _generate(seq,pt,last,bid,ask,bq,aq,quantity_flag,volume_known,observed,vt,reset,start,end):
    """
    機能: 原seq順に価格資格・公開資格・同BBOepisodeと二種類の因果事象を生成する。
    引数: 原列(ndarray)、start/end(float) は同一保存商品の原観測。
    返り値: tuple はevents/価格mask/価格reason/公開reason/件数配列。未来列を参照しない。
    """
    n=len(pt);price_valid=np.zeros(n,np.bool_);price_reason=np.zeros(n,np.uint16);eligibility=np.zeros(n,np.uint16)
    counts=np.zeros(22,np.int64);counts[0]=n
    events=np.empty((64,31),np.float64);ec=0
    active=False;episode=-1;start_i=-1;bid0=0.;ask0=0.;bq0=0.;aq0=0.;minb=0.;mina=0.
    total=0.;npositive=0;first_positive=-1;direction=0;threshold_published=False
    first_fresh=0;first_after=0;first_vknown=0
    for i in range(n):
        pr=0
        if not np.isfinite(pt[i]):pr|=1
        elif not(start<=pt[i]<end):pr|=2
        if not(np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0<bid[i]<ask[i]):pr|=4
        if i>0:
            if seq[i]!=seq[i-1]+1:pr|=8
            if not np.isfinite(pt[i-1]):pr|=16
            elif np.isfinite(pt[i]) and pt[i]<pt[i-1]:pr|=32
        if reset[i]&8:pr|=32
        price_reason[i]=pr;price_valid[i]=pr==0
        qty=bool(quantity_flag[i] and np.isfinite(bq[i]) and np.isfinite(aq[i]) and bq[i]>0 and aq[i]>0)
        obs=bool(np.isfinite(observed[i]) and observed[i]>=0)
        vol=bool(volume_known[i] and obs)
        reason=pr
        if not qty:reason|=64;counts[3]+=1
        if not volume_known[i]:reason|=128;counts[5]+=1
        if not obs:reason|=256;counts[6]+=1
        if not vol:counts[4]+=1
        eligibility[i]=reason
        if pr==0:counts[1]+=1
        else:counts[2]+=1
        if reason!=0:
            if active:
                if pr!=0:counts[17]+=1
                elif not qty:counts[18]+=1
                else:counts[19]+=1
            active=False
            continue
        counts[7]+=1
        changed=active and (bid[i]!=bid0 or ask[i]!=ask0)
        if changed:counts[20]+=1
        if not active or changed:
            active=True;episode+=1;counts[8]+=1;start_i=i
            bid0=bid[i];ask0=ask[i];bq0=bq[i];aq0=aq[i];minb=bq0;mina=aq0
            total=0.;npositive=0;first_positive=-1;direction=0;threshold_published=False
            first_fresh=0;first_after=0;first_vknown=0
            if observed[i]>0:counts[14]+=1
            continue
        minb=min(minb,bq[i]);mina=min(mina,aq[i])
        positive=observed[i]>0
        if positive:total+=observed[i];npositive+=1
        fresh=int(i>0 and np.isfinite(pt[i-1]) and pt[i]>pt[i-1])
        clock_known=int(np.isfinite(vt[i]));after=int(clock_known and vt[i]>pt[i])
        publish0=False
        if positive and first_positive<0:
            first_positive=i;first_fresh=fresh;first_after=after;first_vknown=clock_known;counts[9]+=1
            if not(np.isfinite(last[i]) and last[i]>0):
                counts[13]+=1
            elif last[i]>=ask[i-1]:
                direction=1;counts[10]+=1;publish0=True
            elif last[i]<=bid[i-1]:
                direction=-1;counts[11]+=1;publish0=True
            else:
                counts[12]+=1
        if direction==0:continue
        opposite0=aq0 if direction>0 else bq0
        current=aq[i] if direction>0 else bq[i]
        minimum=mina if direction>0 else minb
        publish1=bool(not threshold_published and total>=opposite0)
        for kind in range(2):
            if (kind==0 and not publish0) or (kind==1 and not publish1):continue
            event=np.array([kind,episode,start_i,i,direction,bid0,ask0,bq0,aq0,bq[i],aq[i],minb,mina,
                opposite0,current,minimum,current/opposite0,minimum/opposite0,int(current>=opposite0),
                total,npositive,first_positive,fresh,after,clock_known,first_fresh,first_after,first_vknown,
                seq[start_i],seq[i],pt[i]],np.float64)
            events,ec=_append(events,ec,event);counts[15+kind]+=1
        if publish1:threshold_published=True
    if active:counts[21]+=1
    return events[:ec],price_valid,price_reason,eligibility,counts


@njit(cache=False)
def _search(maxb,maxa,minb,mina,node,lo,hi,left,right,tb,ta,ge):
    """
    機能: 両BBOが同時に閾値へ達した最初の原行を区間木で探索する。
    引数: 最大最小木(ndarray)、位置/区間(int)、tb/ta(float)、ge(bool)。
    返り値: int は最初の行又は−1。片側到達だけでは成立しない。
    """
    if left>=right or hi<=left or right<=lo:return -1
    if ge:
        if maxb[node]<tb or maxa[node]<ta:return -1
        if minb[node]>=tb and mina[node]>=ta:return max(lo,left)
    else:
        if minb[node]>tb or mina[node]>ta:return -1
        if maxb[node]<=tb and maxa[node]<=ta:return max(lo,left)
    if hi-lo==1:return lo
    mid=(lo+hi)//2
    found=_search(maxb,maxa,minb,mina,node*2,lo,mid,left,right,tb,ta,ge)
    if found>=0:return found
    return _search(maxb,maxa,minb,mina,node*2+1,mid,hi,left,right,tb,ta,ge)


@njit(cache=False)
def _outcomes(events,price_valid,bid,ask,tick):
    """
    機能: 公開後から価格資格の切断まで、順逆各一呼値の最初の両BBO到達を測る。
    引数: events/price_valid/bid/ask(ndarray)、tick(float) は原事象と価格だけ。
    返り値: ndarray[float,二列] はcodeとend_i。未来数量・出来高は引数に含めない。
    """
    n=len(bid);size=1
    while size<n:size*=2
    maxb=np.full(size*2,-np.inf);maxa=np.full(size*2,-np.inf)
    minb=np.full(size*2,np.inf);mina=np.full(size*2,np.inf)
    next_bad=np.full(n+1,n,np.int64)
    for i in range(n-1,-1,-1):
        next_bad[i]=i if not price_valid[i] else next_bad[i+1]
        if price_valid[i]:
            maxb[size+i]=bid[i];minb[size+i]=bid[i];maxa[size+i]=ask[i];mina[size+i]=ask[i]
    for node in range(size-1,0,-1):
        maxb[node]=max(maxb[node*2],maxb[node*2+1]);maxa[node]=max(maxa[node*2],maxa[node*2+1])
        minb[node]=min(minb[node*2],minb[node*2+1]);mina[node]=min(mina[node*2],mina[node*2+1])
    result=np.empty((len(events),2),np.float64)
    for k in range(len(events)):
        event=events[k];pub=int(event[3]);direction=int(event[4]);left=pub+1;right=next_bad[left]
        b,a=event[5],event[6]
        favourable=_search(maxb,maxa,minb,mina,1,0,size,left,right,b+direction*tick,a+direction*tick,direction>0)
        adverse=_search(maxb,maxa,minb,mina,1,0,size,left,right,b-direction*tick,a-direction*tick,direction<0)
        if favourable>=0 and (adverse<0 or favourable<adverse):result[k]=np.array([1.,float(favourable)])
        elif adverse>=0:result[k]=np.array([-1.,float(adverse)])
        elif right<n:result[k]=np.array([0.,float(right)])
        else:result[k]=np.array([2.,float(n-1)])
    return result


def measure(arrays: dict, start: float, end: float, tick: float) -> dict:
    """
    機能: 保存44列の必要列だけから因果数量事象と後続価格先着を返す。
    引数: arrays(dict[str,ndarray])、start/end/tick(float) は読取済み原配列と場/観測呼値。
    返り値: dict はevents/fields/outcomes/outcome_fields/counts及び価格/公開資格mask。
    入出力・金融・原配列変更は行わず、Technical高安・peer・真の攻撃/補充は未測。
    """
    assert np.isfinite(start) and np.isfinite(end) and start<end and np.isfinite(tick) and tick>0
    names=('raw_seq','price_time_s','last','bid','ask','bid_qty','ask_qty','best_quantity_valid',
           'volume_delta_known','volume_delta_observed','volume_time_s','price_reset_reason')
    n=len(arrays['raw_seq']);assert n>0
    assert all(isinstance(arrays[name],np.ndarray) and arrays[name].shape==(n,) for name in names)
    assert np.issubdtype(arrays['raw_seq'].dtype,np.integer) and np.issubdtype(arrays['price_reset_reason'].dtype,np.integer)
    assert arrays['best_quantity_valid'].dtype==bool and arrays['volume_delta_known'].dtype==bool
    assert np.all((arrays['raw_seq']>=0)&(arrays['raw_seq']<2**53)),'事象float64で厳密表現できる非負原seqが必要'
    values=_generate(*(arrays[name] for name in names),start,end)
    events,valid,reason,eligibility,counts=values
    outcomes=_outcomes(events,valid,arrays['bid'],arrays['ask'],tick)
    assert events.shape==(len(outcomes),len(FIELDS))
    assert np.all(np.isfinite(events)), '累計又は数量比が有限表現域を超えた事象は保存せず停止する'
    result_counts={name:int(counts[i]) for i,name in enumerate(COUNT_FIELDS)}
    result_counts['no_positive_episodes']=result_counts['episodes']-result_counts['positive_episodes']
    result_counts['outcome_counts']={str(code):int(np.sum(outcomes[:,0]==code)) for code in (1,-1,0,2)}
    result_counts['price_reason_counts']={str(bit):int(np.count_nonzero(reason&bit)) for bit in PRICE_REASON_BITS}
    result_counts['eligibility_reason_counts']={str(bit):int(np.count_nonzero(eligibility&bit)) for bit in ELIGIBILITY_REASON_BITS}
    return dict(events=events,fields=list(FIELDS),event_dtype=str(events.dtype),
        field_types={name:('float64' if name in ('bid','ask','bid_q0','ask_q0','bid_q_at_public','ask_q_at_public',
            'min_bid_q','min_ask_q','opposite_q0','opposite_q_at_public','opposite_min_q','quantity_ratio',
            'minimum_quantity_ratio','total_volume','pub_price_time_s') else 'int_exact_float64') for name in FIELDS},
        outcomes=outcomes,outcome_fields=list(OUTCOME_FIELDS),outcome_dtype=str(outcomes.dtype),
        counts=result_counts,price_valid_mask=valid,price_reason_mask=reason,publication_reason_mask=eligibility,
        price_reason_bits=dict(PRICE_REASON_BITS),publication_reason_bits=dict(ELIGIBILITY_REASON_BITS),
        definitions=dict(type0='最初正ΔVでLast対前BBOの方向d±1が一回確定した行。d0は件数のみ。',
            type1='開始行ΔVを除いた全正ΔV累計が初期反対最良Q0以上となった最初の行。',
            quantity_group='1:Q*/Q0>=1、0:Q*/Q0<1。min比で連続維持と途中減少後回復を別分類。',
            outcome='公開rowより後だけ。+1/-1は両BBO各1観測T先着。0は価格資格切断、2は原EOF。end_iは観測行、EOFは最終原行。',
            scope='価格時計模型の公表活動/表示量。真の攻撃/約定消費/補充/心理/金融/Technical高安/peerは未測。',
            unknown_counts='行別理由は重複可。episode終端はprice→quantity→volumeの先着分類。',
            clock='volumeTime>priceTimeを未来として除外しない。freshはflagだけでd採否に不使用。'))
