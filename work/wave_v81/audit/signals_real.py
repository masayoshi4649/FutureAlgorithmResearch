"""原本気配から方向状態を別計算し、二市場の参照時計と未来切断を照合する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numba
import numpy as np

from raw_gaps import load_inputs

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('wave81_signal_audit_target',WORK/'signals.py')
signal=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=signal
spec.loader.exec_module(signal)
numba.config.CACHE_DIR=str(HERE/'numba_cache')
signal.event_features=numba.njit(cache=False)(signal.event_features.py_func)


@numba.njit(cache=True)
def event_average(values, alpha):
    """機能: 過去の方向比と新イベント符号の荷重平均から正規化EMAを別計算する。

    引数: values(ndarray)、alpha(float)。返り値: 非ゼロ各イベントでの方向比(ndarray)。
    分子EMAを直接更新せず、数量の絶対値による混合率を更新する。
    """
    mass=0.;ratio=0.;output=np.zeros(len(values))
    for i in range(len(values)):
        amount=values[i]
        old=mass*(1-alpha);new=alpha*abs(amount);mass=old+new
        weight=old/mass
        ratio=ratio*weight+(1. if amount>0 else -1.)*(1.-weight)
        output[i]=ratio
    return output


@numba.njit(cache=True)
def turning(mid, usable, width):
    """機能: 中値列を一呼値閾値ごとの独立状態機械へ通す。

    引数: mid/usable(ndarray)、width(float)。返り値: 方向・極値・反転行(tuple)。
    最良が不正な行では出力を無効とし、観測済み極値自体は破棄しない。
    """
    n=len(mid);state=0;anchor=np.nan;extreme=np.nan;last=-1
    dirs=np.zeros(n,np.int8);peaks=np.full(n,np.nan,np.float32);rows=np.full(n,-1,np.int32)
    for i in range(n):
        if usable[i]:
            price=mid[i]
            if np.isnan(anchor):anchor=price;extreme=price
            if state==0:
                displacement=price-anchor
                if abs(displacement)>=width-1e-8:
                    state=1 if displacement>0 else -1
                    extreme=price;last=i
            else:
                if (price-extreme)*state>0:extreme=price
                reverse=(price-extreme)*state<=-width+1e-8
                if reverse:state=-state;extreme=price;last=i
            dirs[i]=state
        peaks[i]=extreme;rows[i]=last
    return dirs,peaks,rows


def independent(ready: dict, book: dict) -> dict:
    """機能: 生の最良価格数量を用い、価格方向とイベントEMAを別実装で再構成する。

    引数: ready/book(dict)。返り値: 主な単市場状態(dict)。
    OFIは価格上昇・同値・下落の三場合分け、EMAは非ゼロ列の数量荷重混合で計算する。
    """
    t=ready['time_s'];seq=ready['seq'];n=len(t);tick=ready['tick']
    assert np.all(np.diff(t)>=0)
    b,a,bq,aq=[book[k].astype(float) for k in ['bid','ask','bid_qty','ask_qty']]
    usable=np.isfinite(b+a+bq+aq)&(b>0)&(a>b)&(bq>0)&(aq>0)
    comparable=np.zeros(n,bool)
    comparable[1:]=usable[1:]&usable[:-1]&(np.diff(seq)==1)
    raw=np.full(n,np.nan)
    change_bid=np.where(b[1:]>b[:-1],bq[1:],np.where(b[1:]<b[:-1],-bq[:-1],bq[1:]-bq[:-1]))
    change_ask=np.where(a[1:]>a[:-1],aq[:-1],np.where(a[1:]<a[:-1],-aq[1:],aq[:-1]-aq[1:]))
    j=np.flatnonzero(comparable)
    raw[j]=(change_bid+change_ask)[j-1]
    nonzero=np.flatnonzero(np.isfinite(raw)&(raw!=0))
    count=np.searchsorted(nonzero,np.arange(n),side='right').astype(np.int32)
    last=np.maximum.accumulate(np.where(np.isfinite(raw)&(raw!=0),np.arange(n),-1)).astype(np.int32)
    flows=[]
    for span in [8,32,128]:
        alpha=2/(span+1)
        values=raw[nonzero]
        ratios=event_average(values,alpha)
        flows.append(np.r_[np.nan,ratios][count].astype(np.float32))
    flow=np.asarray(flows)
    dirs=[];peaks=[];turns=[]
    for width in [1,2,4,8]:
        d,p,r=turning((b+a)/2,usable,width*tick)
        dirs.append(d);peaks.append(p);turns.append(r)
    states=np.zeros((13,n),np.int8);valid=np.zeros((13,n),bool)
    states[:4]=np.array(dirs);valid[:4]=usable
    for index,span in enumerate([8,32,128]):
        enough=usable&comparable&(count>=span)&np.isfinite(flow[index])
        for j,threshold in enumerate([.15,.30]):
            m=4+index*2+j
            states[m]=np.where(enough&(flow[index]>=np.float32(threshold)),1,
                       np.where(enough&(flow[index]<=-np.float32(threshold)),-1,0))
            valid[m]=enough
    for m,d,f in [(10,1,6),(11,2,6),(12,2,9)]:
        valid[m]=valid[d]&valid[f]
        states[m]=np.where(valid[m]&(states[d]==states[f]),states[d],0)
    change=np.ones(n,bool)
    change[1:]=(b[1:]!=b[:-1])|(a[1:]!=a[:-1])|(bq[1:]!=bq[:-1])|(aq[1:]!=aq[:-1])|~comparable[1:]
    quote_last=np.maximum.accumulate(np.where(usable&change,np.arange(n),-1)).astype(np.int32)
    rebase=~comparable
    return dict(time_s=t,states=states,valid=valid,price_valid=usable&(a-b<=tick+1e-8),
        direction_price_valid=usable,flow=flow,flow_count=count,last_flow_update=last,
        last_quote_update=quote_last,turn_extreme=np.asarray(peaks),last_price_turn=np.asarray(turns),
        raw_ofi=raw.astype(np.float32),reset_event=np.zeros(n,bool),flow_comparable=comparable,flow_rebase=rebase,
        entry_reset=np.zeros(n,bool),tick=tick,
        **{k:book[k].astype(np.float32) for k in ['bid','ask','bid_qty','ask_qty']})


def reference(target: np.ndarray, other: np.ndarray) -> tuple:
    """機能: 一意時計表から厳密過去の先頭原本行を独立に選ぶ。

    引数: target/other(ndarray)。返り値: 相手行・古さ(tuple)。
    """
    clocks,first=np.unique(other,return_index=True)
    pos=np.searchsorted(clocks,target,side='left')-1
    known=pos>=0
    source=np.full(len(target),-1,np.int32);age=np.full(len(target),np.nan,np.float32)
    source[known]=first[pos[known]]
    age[known]=target[known]-clocks[pos[known]]
    return source,age


def check_arrays(left: dict, right: dict) -> int:
    """機能: 同じ意味を持つ全配列を比較する。

    引数: left/right(dict)。返り値: 照合配列数(int)。
    """
    count=0
    for name,actual in left.items():
        if not isinstance(actual,np.ndarray):continue
        expected=right[name]
        if name=='flow':np.testing.assert_allclose(actual,expected,rtol=0,atol=1e-7,equal_nan=True,err_msg=name)
        else:np.testing.assert_array_equal(actual,expected,err_msg=name)
        count+=1
    return count


def trimmed(record: dict, count: int) -> dict:
    """機能: 原本対応配列を途中で物理的に切断する。

    引数: record(dict)、count(int)。返り値: 切断後資料(dict)。
    """
    n=len(record['time_s'])
    return {k:v[:count] if isinstance(v,np.ndarray) and v.ndim and len(v)==n else v for k,v in record.items()}


def main() -> None:
    """機能: 全60口座の独立状態・二市場参照・原本prefix不変を監査する。

    引数: なし。返り値: なし(None)。会計結果は一切読み込まない。
    """
    ready,books=load_inputs()
    with (WORK/'prepared/signals.pkl').open('rb') as stream:saved=pickle.load(stream)
    arrays=prefixes=rows=0;proof=[]
    for session in sorted({k[0] for k in ready}):
        rebuilt={}
        for symbol in ['TOPIX','NK225']:
            key=(session,symbol);rebuilt[symbol]=independent(ready[key],books[key])
            mainframe=signal.market_features(ready[key],books[key])
            arrays+=check_arrays(rebuilt[symbol],mainframe)
        for symbol,other in [('TOPIX','NK225'),('NK225','TOPIX')]:
            key=(session,symbol);target=saved[key];r=ready[key];n=len(r['time_s'])
            own,peer=rebuilt[symbol],rebuilt[other]
            src,age=reference(own['time_s'],peer['time_s']);safe=np.maximum(src,0)
            fresh=(src>=0)&(age>0)&(age<=10.)
            peer_valid=peer['valid'][:,safe]&fresh
            peer_state=np.where(peer_valid,peer['states'][:,safe],0).astype(np.int8)
            both=own['valid']&peer_valid
            common=np.where(both&(own['states']==peer_state),peer_state,0).astype(np.int8)
            independent_projection=dict(source_self=np.arange(n,dtype=np.int32),source_peer=src,age_peer=age,
                states_self=own['states'],states_peer=peer_state,states=common,valid_self=own['valid'],
                valid_peer=peer_valid,valid=both,price_valid_self=own['price_valid'],
                price_valid_peer=peer['price_valid'][safe]&fresh,
                price_valid=own['price_valid']&peer['price_valid'][safe]&fresh)
            arrays+=check_arrays(independent_projection,target)
            for name in ['flow','flow_count','last_flow_update','last_quote_update','turn_extreme',
                         'last_price_turn','raw_ofi','reset_event','flow_comparable','flow_rebase']:
                val=own[name]
                if name=='flow':np.testing.assert_allclose(val,target[name+'_self'],atol=1e-7,rtol=0,equal_nan=True)
                else:np.testing.assert_array_equal(val,target[name+'_self'])
                arrays+=1
            changes=np.flatnonzero(np.any(target['states'][:,1:]!=target['states'][:,:-1],axis=0))+1
            locs={max(1,int(n*.37)),max(1,int(n*.73))}
            if len(changes):
                locs.update([int(changes[0]),int(changes[0])+1,int(changes[len(changes)//2])+1])
            for cut in sorted(x for x in locs if 0<x<n):
                deadline=r['time_s'][cut-1]
                pk=(session,other);pc=max(1,int(np.searchsorted(ready[pk]['time_s'],deadline,side='left')))
                ownshort=signal.market_features(trimmed(r,cut),trimmed(books[key],cut))
                peershort=signal.market_features(trimmed(ready[pk],pc),trimmed(books[pk],pc))
                projected=signal.project(ownshort,peershort)
                for field,val in projected.items():
                    if isinstance(val,np.ndarray):
                        expected=target[field][:,:cut] if val.ndim==2 else target[field][:cut]
                        np.testing.assert_array_equal(val,expected,err_msg=f'{key} {cut} {field}')
                        arrays+=1
                prefixes+=1
            rows+=n;proof.append(dict(session=session,symbol=symbol,rows=n,prefixes=len(locs)))
        print(f'独立方向照合 {session} 完了',flush=True)
    result=dict(合格=True,口座数=len(saved),全原板行数=rows,配列照合数=arrays,原本途中切断数=prefixes,
        OFI='価格上昇・同値・下落の別式',EMA='過去方向比と新イベント符号を絶対数量荷重で混合して原板へ投影',
        価格方向='呼値ごとの独立状態機械',二市場='一意時計表から厳密過去の先頭原本を選択',
        会計閲覧=False,signals_SHA256=hashlib.sha256((WORK/'prepared/signals.pkl').read_bytes()).hexdigest(),
        コードSHA256=hashlib.sha256((WORK/'signals.py').read_bytes()).hexdigest(),口座別=proof)
    (HERE/'原板方向と二市場時計の独立監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='口座別'},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
