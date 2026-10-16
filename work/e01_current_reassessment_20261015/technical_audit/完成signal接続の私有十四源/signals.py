"""最新確定Lと現在票から共通構造episodeを認定し、各入口を一回だけ公開する。"""

import numpy as np
from numba import njit


@njit(cache=True)
def doubled(value):
    """
    機能: 私有二次元bufferを倍へ伸ばして既記録を保持する。
    引数: value(ndarray[float,二次元]) は候補buffer。
    返り値: ndarray は倍長のbuffer。
    """
    out=np.zeros((len(value)*2,value.shape[1]));out[:len(value)]=value
    return out


@njit(cache=True)
def generate(bid,ask,normal,high,low,bucket,confirmed,volume_known,price_known,
             volume_gate,price_gate,interval_known,new_up,new_down,tick,initial_capacity=32):
    """
    機能: 全normalの最新L/side episodeを逐次進め、三入口の各初成立を一回記録する。
    引数: BBO/正常/閉足/現在票(ndarray)、tick(float)、initial_capacity(int) は当時入力。
    返り値: tuple は候補16列・episode診断9列・最終公開消費/不成立終了。paper/実busy/未来を使わない。
    """
    n=len(bid);capacity=max(2,initial_capacity);events=np.zeros((capacity,16));count=0
    records=np.zeros((capacity,9));record_count=0;next_episode=0
    latest=np.full(2,-2,np.int64);levels=np.full(2,np.nan);episode=np.full(2,-1,np.int64);seen_break=np.zeros(2,np.bool_)
    consumed=np.zeros((2,3),np.bool_);retired=consumed.copy();break_row=np.full((2,3),-1,np.int64);b0=np.full((2,3),np.nan);a0=b0.copy()
    opposite_row=np.full(2,-1,np.int64);bp=np.full(2,np.nan);ap=bp.copy();opposite_lower=np.zeros(2,np.int64)
    for row in range(n):
        for direction in range(2):
            side=1 if direction==0 else -1;level=high[row] if side>0 else low[row]
            if int(bucket[row])!=latest[direction]:
                latest[direction]=int(bucket[row]);levels[direction]=level;episode[direction]=next_episode;next_episode+=1
                seen_break[direction]=False;consumed[direction,:]=False;retired[direction,:]=False;break_row[direction,:]=-1;opposite_row[direction]=-1
            if not np.isfinite(level) or int(confirmed[row])>=row or not normal[row]:
                if break_row[direction,2]>=0 and not consumed[direction,2] and not retired[direction,2]:
                    retired[direction,2]=True
                    if record_count>=len(records)-1:records=doubled(records)
                    records[record_count]=np.array([row,episode[direction],side,2.,level,bucket[row],confirmed[row],1.,1.]);record_count+=1
                break_row[direction,:]=-1;opposite_row[direction]=-1;continue
            levels[direction]=level
            returned=(bid[row]<=level and ask[row]<=level) if side>0 else (bid[row]>=level and ask[row]>=level)
            if returned and seen_break[direction]:
                episode[direction]=next_episode;next_episode+=1;seen_break[direction]=False
                consumed[direction,:]=False;retired[direction,:]=False;break_row[direction,:]=-1;opposite_row[direction]=-1
            beyond=(bid[row]>level and ask[row]>level) if side>0 else (bid[row]<level and ask[row]<level)
            if beyond:seen_break[direction]=True
            for mode in range(3):
                if consumed[direction,mode] or retired[direction,mode]:continue
                required=volume_known[row] and (mode==0 or price_known[row])
                if not required:
                    if mode==2 and break_row[direction,mode]>=0:
                        retired[direction,mode]=True
                        if record_count>=len(records)-1:records=doubled(records)
                        records[record_count]=np.array([row,episode[direction],side,mode,level,bucket[row],confirmed[row],1.,2.]);record_count+=1
                    break_row[direction,mode]=-1
                    if mode==2:opposite_row[direction]=-1
                    continue
                if break_row[direction,mode]<0:
                    if beyond:
                        break_row[direction,mode]=row;b0[direction,mode]=bid[row];a0[direction,mode]=ask[row]
                        if record_count>=len(records)-1:records=doubled(records)
                        records[record_count]=np.array([row,episode[direction],side,mode,level,bucket[row],confirmed[row],0.,0.]);record_count+=1
                    continue
                start=int(break_row[direction,mode]);assert start<row
                if mode==2:
                    adverse=side*(bid[row]-b0[direction,mode])<-tick or side*(ask[row]-a0[direction,mode])<-tick
                    if adverse:
                        retired[direction,mode]=True
                        if record_count>=len(records)-1:records=doubled(records)
                        records[record_count]=np.array([row,episode[direction],side,mode,level,bucket[row],confirmed[row],1.,3.]);record_count+=1
                        break_row[direction,mode]=-1;opposite_row[direction]=-1;continue
                    fresh=int(new_down[row] if side>0 else new_up[row])
                    if opposite_row[direction]<0 and interval_known[row] and fresh>=1:
                        opposite_row[direction]=row;bp[direction]=bid[row];ap[direction]=ask[row];opposite_lower[direction]=fresh
                    proof=int(opposite_row[direction])
                    progressed=proof>=0 and proof<row and side*(bid[row]-bp[direction])>=2*tick and side*(ask[row]-ap[direction])>=2*tick
                else:
                    proof=-1;progressed=side*(bid[row]-b0[direction,mode])>=tick and side*(ask[row]-a0[direction,mode])>=tick
                qualification=volume_gate[row,direction] and (mode==0 or price_gate[row,direction])
                if progressed and qualification:
                    if count>=len(events)-1:events=doubled(events)
                    events[count]=np.array([row,mode,side,episode[direction],bucket[row],level,start,b0[direction,mode],a0[direction,mode],
                        proof,bp[direction] if mode==2 else np.nan,ap[direction] if mode==2 else np.nan,confirmed[row],
                        opposite_lower[direction] if mode==2 else 0.,proof-1 if mode==2 else -1.,row]);count+=1
                    consumed[direction,mode]=True
    return events[:count],records[:record_count],consumed,retired
