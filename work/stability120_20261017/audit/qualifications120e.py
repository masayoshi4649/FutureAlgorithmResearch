"""保存済みe注文から初回・組baseline・飽和救済・個別追尾を算術照合する。"""

import math

import numpy as np

import saved_accounting120 as core


def valid_quotes_e(quotes: dict,setting: dict) -> tuple[dict,int]:
    """
    機能: e固有の有限正Lastと、既存時計BBO資格を合成する。
    引数: quotes(dict[str,ndarray])、setting(dict)は保存五列と時刻。
    返り値: tuple[dict,int]は全正常行と元五列からの棄却数。価格を補完しない。
    """
    keep=np.isfinite(quotes['last'])&(quotes['last']>0)
    accepted,_=core.valid_quotes({k:v[keep] for k,v in quotes.items()},setting)
    return accepted,int(len(quotes['row'])-len(accepted['row']))


def qualifications(q: dict,o: np.ndarray,row: dict,setting: dict,spec: dict) -> None:
    """
    機能: 正常保存気配と実注文だけから組ごとの全玉純益・個別出口・飽和救済を検査する。
    引数: q(dict)、o(ndarray18列)、row/setting/spec(dict)は保存小会計と事前仕様。
    返り値: None。取消済み未約定の内部状態は捏造せず、保存実注文と源人工の範囲を分ける。
    """
    rr=q['row'];bb=q['bid'];aa=q['ask'];last=q['last'];n=len(rr)
    fee=math.floor(setting['fee']+1e-9);mult=setting['multiplier'];cap=setting['cap'];step=row['step'];trail=spec['trail'];mode=spec['mode']
    entry=o[o[:,1]==1];exits=o[o[:,1]==2]
    eidx=core.positions(rr,entry[:,4],'e新規実約定原row');didx=core.positions(rr,entry[:,3],'e新規判断原row')
    core.check(np.all(didx>0) and np.all(entry[:,2]*(last[didx]-last[didx-1])>0),'e実新規は当時Last方向へ成立')
    core.check(np.all(entry[:,2]*(last[didx]-entry[:,17])>=-1e-6),'e実新規のLastは追尾新規線へ到達')
    decision_price=np.where(entry[:,2]>0,aa[didx],bb[didx])
    core.check(np.all(entry[:,2]*(entry[:,7]-decision_price)<=setting['observed_tick']+1e-6),'e実新規価格は判断BBOから一観測tick以内')
    core.check(np.all(aa[didx]-bb[didx]<=step+1e-6) and np.all(aa[eidx]-bb[eidx]<=step+1e-6),'e新規判断と最初fillはspread資格を満たす')
    if mode==0:core.check(np.all(np.isin(exits[:,9],(9,10))),'KEEPは組又は場末だけ返済')
    elif mode==1:core.check(np.all(np.isin(exits[:,9],(9,10,11))),'RESCUEに勝玉個別利確を混ぜない')
    else:core.check(np.all(np.isin(exits[:,9],(1,9))),'ROTATEに組又は飽和出口を混ぜない')
    lookup={int(v[0]):v for v in entry};exit_lookup={int(v[0]):v for v in exits}
    cash_delta=np.zeros(n);count_delta=np.zeros((2,n));basis_delta=np.zeros((2,n))
    for order in o:
        index=int(np.searchsorted(rr,order[4]));uid=int(order[0])
        en=order if order[1]==1 else lookup[uid];side=int(en[2]);s=0 if side==1 else 1
        if order[1]==1:
            count_delta[s,index]+=1;basis_delta[s,index]+=order[7];cash_delta[index]-=fee
        else:
            count_delta[s,index]-=1;basis_delta[s,index]-=en[7]
            cash_delta[index]+=side*(order[7]-en[7])*mult-fee
    cash=np.cumsum(cash_delta);counts=np.cumsum(count_delta,axis=1);basis=np.cumsum(basis_delta,axis=1)
    qty=counts[0]+counts[1]
    equity=cash+(counts[0]*bb-basis[0]+basis[1]-counts[1]*aa)*mult-qty*fee
    starts=np.flatnonzero((qty>0)&(np.r_[0.,qty[:-1]]==0));ends=np.flatnonzero((qty==0)&(np.r_[0.,qty[:-1]]>0))
    cycle_ids=np.cumsum((qty>0)&(np.r_[0.,qty[:-1]]==0));baseline=np.zeros(n);peaks=np.zeros(n)
    for number,start in enumerate(starts):
        end=starts[number+1] if number+1<len(starts) else n
        initial_cash=cash[start]-cash_delta[start]
        baseline[start:end]=initial_cash
        marks=equity[start:end]-initial_cash;peaks[start:end]=np.maximum.accumulate(np.maximum(marks,0.))
        same_first=entry[entry[:,4]==rr[start]]
        core.check(len(same_first)==1 and same_first[0,10]==0,'e組最初の実約定はrung0一枚だけ')
    basket=equity-baseline
    core.check(not np.any(np.isin(entry[:,3],rr[ends])),'e全flat完了原rowに再新規を判断しない')
    # ----------------------------------------
    # RESCUEの独立極値は両側が実capとなった連続区間だけで積み上げる。
    full=(counts[0]==cap)&(counts[1]==cap)
    full_starts=np.flatnonzero(full&~np.r_[False,full[:-1]])
    full_ends=np.flatnonzero(full&~np.r_[full[1:],False])+1
    low=np.full(n,np.nan);high=np.full(n,np.nan)
    for begin,end in zip(full_starts,full_ends):
        low[begin:end]=np.minimum.accumulate(last[begin:end]);high[begin:end]=np.maximum.accumulate(last[begin:end])
    for order in exits:
        uid=int(order[0]);en=lookup[uid];side=int(en[2]);reason=int(order[9]);di=int(np.searchsorted(rr,order[3]));ei=int(np.searchsorted(rr,en[4]))
        if reason==1:
            marks=side*((bb[ei:di+1] if side==1 else aa[ei:di+1])-en[7])*mult-2*fee
            core.check(np.max(marks)>0 and marks[-1]>0 and np.max(marks)-marks[-1]>=trail*step*mult-1e-5,'ROTATEの正peakと現在純益と幅戻りを当時全気配で確認')
        elif reason==10:
            core.check(basket[di]>0 and peaks[di]>=(trail+1)*step*mult-1e-5 and peaks[di]-basket[di]>=trail*step*mult-1e-5,'e組追尾は初回fee前cashと途中RESCUE実損を含む')
            held=[v for v in entry if v[4]<=order[3] and (int(v[0]) not in exit_lookup or exit_lookup[int(v[0])][4]>order[3])]
            closing=exits[exits[:,3]==order[3]]
            core.check(set(int(v[0]) for v in held)==set(closing[:,0].astype(int)),'e組追尾はその時の全実玉を同時返済予約')
        elif reason==11:
            core.check(mode==1 and full[di] and di>0,'e飽和救済は両側実capのRESCUEだけ')
            if side==-1:
                core.check(last[di]>last[di-1] and last[di]>=low[di]+3*step-1e-6,'e売り削減は飽和Last安値から三単位反発')
                core.near(order[17],low[di]+3*step,'e売り削減判断線')
            else:
                core.check(last[di]<last[di-1] and last[di]<=high[di]-3*step+1e-6,'e買い削減は飽和Last高値から三単位反落')
                core.near(order[17],high[di]-3*step,'e買い削減判断線')
            held=[v for v in entry if v[2]==side and v[4]<=order[3] and (int(v[0]) not in exit_lookup or exit_lookup[int(v[0])][4]>order[3])]
            marks=[side*((bb[di] if side==1 else aa[di])-v[7])*mult-2*fee for v in held]
            own=side*((bb[di] if side==1 else aa[di])-en[7])*mult-2*fee
            core.check(own<0 and own==min(marks),'e飽和救済は逆方向最悪負け玉一枚')
            core.check(sum((exits[:,3]==order[3])&(exits[:,9]==11))==1,'e一救済判断は一枚だけ')
