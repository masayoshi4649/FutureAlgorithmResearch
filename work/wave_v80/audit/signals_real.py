"""原本の一意時計から特徴を再計算し、八入口の因果時計と未来不変を照合する。"""

from __future__ import annotations

import json
import sys

import numpy as np

from accounts import HERE,WORK,study

import signals


def close(left, right, label: str) -> None:
    """機能: 保存float32の丸めだけを許して特徴を比較する。

    引数: left/right(ndarray)、label(str)。返り値: なし(None)。
    """
    np.testing.assert_allclose(left,right,atol=1e-6,rtol=1e-7,equal_nan=True,err_msg=label)


def references(grid: np.ndarray, ready: dict, book: dict) -> dict:
    """機能: 同時計を一意化した別探索で厳密過去の三参照を求める。

    引数: grid(ndarray)、ready/book(dict)。返り値: 独立特徴(dict)。
    """
    times=ready['time_s'];tick=ready['tick'];clock,first=np.unique(times,return_index=True)
    endpoint=book['valid']&~book['reset']&np.isfinite(book['bid'])&np.isfinite(book['ask'])
    endpoint&=(book['bid']>0)&(book['ask']>book['bid'])&(book['ask']-book['bid']<=tick+1e-8)
    endpoint&=np.isfinite(book['bid_qty'])&np.isfinite(book['ask_qty'])&(book['bid_qty']>0)&(book['ask_qty']>0)
    out={};indices={}
    for window,maximum in [(0,10.),(10,15.),(30,15.)]:
        deadline=grid-1.-window;position=np.searchsorted(clock,deadline,side='left')-1
        original=first[np.maximum(position,0)]
        age=deadline-times[original]
        good=(position>=0)&endpoint[original]&(age>0)&(age<=maximum)
        index=np.where(good,original,-1).astype(np.int32)
        indices[window]=index
        out['source' if window==0 else f'old{window}']=index
        out['age' if window==0 else f'old_age{window}']=np.where(good,age,np.nan)
    n=indices[0];safe=np.maximum(n,0)
    out['time']=np.where(n>=0,times[safe],np.nan)
    out['source_seq']=np.where(n>=0,ready['seq'][safe],-1)
    for field in ['bid','ask','mid','bid_qty','ask_qty']:
        out[field]=np.where(n>=0,book[field][safe],np.nan)
    out['spread']=(out['ask']-out['bid'])/tick
    out['imbalance']=(out['bid_qty']-out['ask_qty'])/(out['bid_qty']+out['ask_qty'])
    bad_prefix=np.r_[0,np.cumsum((~book['valid'])|book['reset'])]
    raw=book['best_ofi'];finite=np.isfinite(raw)
    sumflow=np.r_[0,np.cumsum(np.where(finite,raw,0.))]
    sumabs=np.r_[0,np.cumsum(np.where(finite,abs(raw),0.))]
    missing=np.r_[0,np.cumsum(~finite)]
    changing=np.r_[0,np.cumsum(finite&(raw!=0))]
    for window in [10,30]:
        old=indices[window];left=np.maximum(old,0)
        valid=(n>=0)&(old>=0)&(n>old)&((bad_prefix[safe+1]-bad_prefix[left+1])==0)
        out[f'valid{window}']=valid
        out[f'ret{window}']=np.where(valid,(book['mid'][safe]-book['mid'][left])/tick,np.nan)
        if window==10:
            count=changing[safe+1]-changing[left+1]
            known=valid&((missing[safe+1]-missing[left+1])==0)
            numerator=sumflow[safe+1]-sumflow[left+1];denominator=sumabs[safe+1]-sumabs[left+1]
            sufficient=known&(count>=3)&(denominator>0)
            out['flow_valid10']=sufficient;out['flow_count10']=np.where(known,count,0)
            out['flow10']=np.full(len(grid),np.nan)
            out['flow10'][sufficient]=numerator[sufficient]/denominator[sufficient]
    out['valid']=(n>=0)&out['valid10']&out['valid30'];out['tick']=tick
    return out


def recover(prices, quantities, valid, reset, start: int, end: int) -> bool:
    """機能: 同価格の連続部分で50%以下減少後80%以上回復した状態を走査する。

    引数: prices/quantities/valid/reset(ndarray)、start/end(int)。返り値: 回復状態(bool)。
    """
    left=end
    while left>start and prices[left-1]==prices[end] and valid[left-1] and not reset[left]:
        left-=1
    peak=0.;had_half=False;recovered=False
    for row in range(left,end+1):
        amount=quantities[row]
        if not np.isfinite(amount) or amount<=0 or not valid[row] or reset[row]:
            peak=0.;had_half=recovered=False
        else:
            previous=peak;peak=max(peak,amount)
            if had_half and amount>=.8*previous:recovered=True
            if amount>previous and not recovered:had_half=False
            if amount<=.5*peak:had_half=True
            if amount<.8*peak:recovered=False
    return recovered


def range_features(market: dict, book: dict, common: np.ndarray) -> int:
    """機能: 共通有効窓の高安と同価格回復を直接原本から計算する。

    引数: market/book(dict)、common(bool ndarray)。返り値: 直接検査した独立窓数(int)。
    """
    cache={}
    for name in ['older_high','older_low','recent_high','recent_low']:
        market[name]=np.full(len(common),np.nan)
    market['bid_recovered']=np.zeros(len(common),dtype=bool)
    market['ask_recovered']=np.zeros(len(common),dtype=bool)
    for g in np.flatnonzero(common):
        n,a,b=int(market['source'][g]),int(market['old10'][g]),int(market['old30'][g])
        if not b<a<n:continue
        key=n,a,b
        if key not in cache:
            mid=book['mid'];cache[key]=[float(np.max(mid[b:a+1])),float(np.min(mid[b:a+1])),
                float(np.max(mid[a+1:n+1])),float(np.min(mid[a+1:n+1])),
                recover(book['bid'],book['bid_qty'],book['valid'],book['reset'],a,n),
                recover(book['ask'],book['ask_qty'],book['valid'],book['reset'],a,n)]
        for name,value in zip(['older_high','older_low','recent_high','recent_low','bid_recovered','ask_recovered'],cache[key]):
            market[name][g]=value
    return len(cache)


def confirm(grid, raw, valid, own, peer, peer_required: bool) -> np.ndarray:
    """機能: 連続区間の始点を一括特定する別実装で3秒持続を確かめる。

    引数: grid/raw/valid/own/peer(ndarray)、peer_required(bool)。返り値: 確認方向(ndarray)。
    """
    enabled=valid&(raw!=0)
    breaks=np.r_[True,(raw[1:]!=raw[:-1])|(~enabled[:-1])|(np.diff(grid)>1.000001)]
    starts=np.maximum.accumulate(np.where(breaks,np.arange(len(grid)),0))
    accepted=enabled&(grid-grid[starts]>=3.)&(own>own[starts])
    if peer_required:accepted&=peer>peer[starts]
    return np.where(accepted,raw,0).astype(np.int8)


def raw_states(grid: np.ndarray, own: dict, peer: dict) -> tuple:
    """機能: 日本語仕様から八方向条件を独立に組み立てる。

    引数: grid(ndarray)、own/peer(dict)。返り値: 瞬時方向・持続後方向(tuple)。
    """
    valid=own['valid']&peer['valid'];f=own['flow10'];p=peer['flow10']
    a=own['ret10'];b=peer['ret10'];c=own['ret30'];d=peer['ret30']
    crosses=np.zeros(len(grid),dtype=np.int8);last_direction=0;last_time=-1e30;prior=np.nan
    for i in range(len(grid)):
        if not valid[i] or not own['flow_valid10'][i] or not np.isfinite(f[i]):
            prior=np.nan;last_direction=0;last_time=-1e30;continue
        if np.isfinite(prior) and ((prior<=0<f[i]) or (prior>=0>f[i])):
            last_direction=1 if f[i]>0 else -1;last_time=grid[i]
        if last_direction*f[i]>0 and grid[i]-last_time<=5.:
            crosses[i]=last_direction
        prior=f[i]
    raw=np.zeros((8,len(grid)),dtype=np.int8)
    for sign in [-1,1]:
        direction=sign
        conditions=[
            (sign*f>=.3)&(sign*a>=0)&(sign*a<=1),
            (sign*f>=.3)&(sign*p>=.3)&(sign*a>=0)&(sign*a<=1)&(sign*b>=0),
            (sign*a>=1)&(sign*b>=1)&(sign*f>=.1)&(sign*p>=.1),
            (sign*b>=2)&(sign*a>=0)&(sign*a<=1)&(sign*f>=.1)&(sign*p>=.1),
            (sign*c>=2)&(sign*d>=2)&(sign*a>=-2)&(sign*a<=-1)&(sign*f>=.1)&(sign*p>=0)&(crosses==sign),
        ]
        extreme=(own['recent_high']<=own['older_high'])&(own['mid']<own['older_high']) if sign==-1 else (own['recent_low']>=own['older_low'])&(own['mid']>own['older_low'])
        conditions.append((-sign*c>=3)&extreme&(sign*f>=.1)&(sign*p>=0))
        recovery=own['bid_recovered'] if sign==1 else own['ask_recovered']
        conditions.append(recovery&(sign*p>=.1)&(sign*a>=-1)&(sign*a<=1))
        for k,condition in enumerate(conditions):raw[k,valid&condition]=direction
    raw[7,valid]=np.where(((grid[valid]-grid[0]).astype(int)//30)%2==0,1,-1)
    state=np.stack([confirm(grid,row,valid,own['source'],peer['source'],k!=0) for k,row in enumerate(raw)])
    return raw,state


def main() -> None:
    """機能: 全格子を独立特徴と照合し実信号成立近傍で未来を切断する。

    引数: なし。返り値: なし(None)。監査JSONだけを保存する。
    """
    ready,books,prepared,maps=study.material()
    arrays=grids=windows=prefixes=0;active=np.zeros(8,dtype=int)
    sessions=study.load(WORK/'初回事前固定.json')['全30']
    for session in sessions:
        grid=prepared[(session,'TOPIX')]['grid']
        markets={s:references(grid,ready[(session,s)],books[(session,s)]) for s in ['TOPIX','NK225']}
        common=markets['TOPIX']['valid']&markets['NK225']['valid']
        for symbol in ['TOPIX','NK225']:
            windows+=range_features(markets[symbol],books[(session,symbol)],common)
        for own,peer in [('TOPIX','NK225'),('NK225','TOPIX')]:
            saved=prepared[(session,own)];m=markets[own]
            for label,symbol in [('self',own),('peer',peer)]:
                source=markets[symbol]
                for field in ['time','age','source_seq','bid_qty','ask_qty','spread','flow10','flow_count10','flow_valid10','ret10','ret30','old10','old30','old_age10','old_age30']:
                    name=f'{field[:-2]}_{label}10' if field.endswith('10') else f'{field[:-2]}_{label}30' if field.endswith('30') else f'{field}_{label}'
                    close(saved[name],source[field],name);arrays+=1
                close(saved[f'source_{label}'],source['source'],f'原本行{label}');arrays+=1
                for field in ['bid_recovered','ask_recovered']:
                    np.testing.assert_array_equal(saved[f'{field}_{label}'][common],source[field][common]);arrays+=1
            close(saved['bid'],m['bid'],'参照買気配');close(saved['ask'],m['ask'],'参照売気配')
            np.testing.assert_array_equal(saved['valid'],common)
            raw,state=raw_states(grid,m,markets[peer])
            np.testing.assert_array_equal(saved['raw_states'],raw)
            np.testing.assert_array_equal(saved['states'],state)
            arrays+=5;grids+=len(grid);active+=np.count_nonzero(state,axis=1)
        any_signal=np.flatnonzero(np.any(prepared[(session,'TOPIX')]['states'][:7]!=0,axis=0)|np.any(prepared[(session,'NK225')]['states'][:7]!=0,axis=0))
        cuts={max(1,int(len(grid)*.37)),max(1,int(len(grid)*.73))}
        if len(any_signal):cuts.update([max(1,int(any_signal[0])),min(len(grid)-1,int(any_signal[0])+2)])
        for cut in sorted(cuts):
            sliced={}
            for symbol in ['TOPIX','NK225']:
                r,b=ready[(session,symbol)],books[(session,symbol)]
                stop=np.searchsorted(r['time_s'],grid[cut-1]-1.,side='left');n=len(r['time_s'])
                cutr={k:v[:stop] if isinstance(v,np.ndarray) and v.ndim>0 and len(v)==n else v for k,v in r.items()}
                cutb={k:v[:stop] if isinstance(v,np.ndarray) and v.ndim>0 and len(v)==n else v for k,v in b.items()}
                sliced[symbol]=signals.market_features(grid[:cut],cutr,cutb)
            for own,peer in [('TOPIX','NK225'),('NK225','TOPIX')]:
                actual=signals.direction_states(grid[:cut],sliced[own],sliced[peer]);saved=prepared[(session,own)]
                for field,value in actual.items():
                    if isinstance(value,np.ndarray):
                        expected=saved[field][:,:cut] if value.ndim==2 else saved[field][:cut]
                        np.testing.assert_array_equal(value,expected);arrays+=1
                prefixes+=1
        print(f'独立信号 {session} 合格',flush=True)
    result=dict(合格=True,商品場数=60,全格子数=grids,直接原本窓数=windows,比較配列数=arrays,
        未来切断口座地点数=prefixes,入口別確認格子数=active.tolist(),
        信号SHA256=study.digest(WORK/'prepared/signals.pkl'),実装SHA256=study.digest(WORK/'signals.py'),
        注記='一意時計から別実装で参照行を算出。全格子特徴と八入口を照合。数量回復の直接走査は両市場の共通有効窓で実施。実受信時計と成行/取消/補充の識別は証明しない。')
    (HERE/'原本からの独立特徴と八入口未来監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
