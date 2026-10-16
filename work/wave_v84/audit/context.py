"""注文管理エンジンを変更せず読み、人工経路と独立台帳を準備する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import numba
import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
numba.config.CACHE_DIR = str(HERE/'numba_cache')
engine=None


def load_engine() -> object:
    """機能: 完成後の今回エンジンだけを監査用名前空間へ読み込む。

    引数: なし。返り値: Pythonモジュール(object)。
    """
    global engine
    if engine is None:
        spec=importlib.util.spec_from_file_location('wave84_engine',WORK/'engine.py')
        engine=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=engine
        spec.loader.exec_module(engine)
    return engine


def digest(path: Path) -> str:
    """機能: 保存ファイルの内容指紋を求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(8*1024*1024):h.update(chunk)
    return h.hexdigest()


def save(name: str, result: dict) -> None:
    """機能: 日本語の監査証跡だけを自分の領域へ保存する。

    引数: name(str)、result(dict)。返り値: なし(None)。
    """
    path=HERE/name
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def record(times, prices, bid=None, ask=None, tick=1., limit=300.) -> tuple:
    """機能: 欠測と同時計も表現できる現在値・約定気配の人工原本を作る。

    引数: times/prices(list)、bid/ask(list|None)、tick/limit(float)。返り値: 入力tuple。
    """
    times=np.asarray(times,dtype=float);prices=np.asarray(prices,dtype=float);n=len(times)
    bid=prices-.5*tick if bid is None else np.asarray(bid,dtype=float)
    ask=prices+.5*tick if ask is None else np.asarray(ask,dtype=float)
    return (times,prices,bid,ask,np.arange(n,dtype=np.int64),np.arange(n,dtype=np.int32),
        np.isfinite(prices)&(prices>0),np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid),
        tick,float(times[0]),limit+300.,limit)


def arguments(r: tuple, family: int, width=2, variant=0, symbol='TOPIX',delay=0.,seed=0,slip=0.) -> tuple:
    """機能: 2商品の実料金と片方向上限を人工実行へ渡す。

    引数: r(tuple)、family/width/variant/seed(int)、symbol(str)、delay/slip(float)。返り値: 引数tuple。
    """
    cap,value,fee=(10,1000.,41.8) if symbol=='TOPIX' else (20,10.,11.)
    return r,family,width,variant,cap,value,fee,delay,seed,slip


def cash_oracle(args: tuple, out: tuple, symbol: str) -> dict:
    """機能: 全約定から各玉と現金を再構成し、全原板の清算時価を独立検算する。

    引数: args(tuple)、out(tuple)、symbol(str)。返り値: 照合数と会計(dict)。
    新規未約定の監査は別の予約イベントで行い、ここでは実保有を独立計算する。
    """
    r,family,width,variant,cap,value,fee,delay,seed,slip=args
    times,prices,bid,ask,seq,source,pok,qok,tick,start,end,limit=r
    orders,trades,curve,stats=out[:4]
    assert orders.shape[1]==16 and trades.shape[1]==14
    held={};rebuilt=[];cash=0.;lastbid=lastask=np.nan;oi=0;maxlong=maxshort=maxtotal=0
    path=np.zeros(len(times));fees=0;all_fills=[]
    for i,t in enumerate(times):
        if qok[i]:lastbid,lastask=bid[i],ask[i]
        while oi<len(orders) and int(orders[oi,0])==i:
            o=orders[oi];oi+=1;ticket=int(o[2]);side=int(o[3]);qty=int(o[4]);price=o[5]
            source=int(o[1]);assert (i>=source if delay==0 else i>source) and t>=o[10] and o[10]==o[9]+delay
            assert qok[i]
            expected=ask[i]+slip*tick if side==1 else bid[i]-slip*tick
            if int(o[6])==1 and int(o[15])==2:
                assert side*(expected-o[13])<=0
                expected=o[13]
            assert abs(price-expected)<1e-8
            charge=qty*418//10 if symbol=='TOPIX' else qty*11
            assert o[8]==charge;fees+=charge
            cash-=side*qty*price*value+charge
            if int(o[6])==1:
                assert ticket not in held and o[9]<limit-120.
                if o[15]:assert side*(price-o[13])<=0
                held[ticket]=o.copy()
            else:
                opening=held.pop(ticket)
                assert side==-opening[3] and qty==opening[4]
                gross=opening[3]*qty*(price-opening[5])*value
                rebuilt.append([ticket,opening[0],i,opening[3],qty,opening[5],price,
                    opening[8],charge,gross,gross-opening[8]-charge,opening[7],o[7],opening[14]])
            all_fills.append((i,ticket,int(o[6])))
            instant_long=sum(int(v[4]) for v in held.values() if v[3]==1)
            instant_short=sum(int(v[4]) for v in held.values() if v[3]==-1)
            maxlong=max(maxlong,instant_long);maxshort=max(maxshort,instant_short)
            maxtotal=max(maxtotal,instant_long+instant_short)
        long=sum(int(o[4]) for o in held.values() if o[3]==1)
        short=sum(int(o[4]) for o in held.values() if o[3]==-1)
        assert long<=cap and short<=cap
        maxlong=max(maxlong,long);maxshort=max(maxshort,short);maxtotal=max(maxtotal,long+short)
        equity=cash
        for opening in held.values():
            side=int(opening[3]);qty=int(opening[4])
            liquidation=lastbid-slip*tick if side==1 else lastask+slip*tick
            exitfee=qty*418//10 if symbol=='TOPIX' else qty*11
            equity+=side*qty*liquidation*value-exitfee
        path[i]=equity
    assert oi==len(orders)
    expected=np.array(rebuilt,dtype=float).reshape(-1,14)
    np.testing.assert_allclose(expected,trades,rtol=0,atol=1e-5)
    np.testing.assert_allclose(path,curve,rtol=0,atol=1e-5)
    np.testing.assert_array_equal(stats[[0,1,4,5,11]],[maxlong,maxshort,long,short,maxtotal])
    assert stats[9]==int(np.sum(orders[:,6]==1)) and stats[10]==len(trades)
    if not held:assert abs(cash-trades[:,10].sum())<1e-5
    return dict(注文数=len(orders),決済数=len(trades),全行時価数=len(path),残保有玉数=len(held),
        収支=float(trades[:,10].sum()),最終清算時価=float(curve[-1]),料金=fees,最大総保有=maxtotal)


def reservation_oracle(args: tuple, out: tuple) -> dict:
    """機能: 発注・失効イベントから予約を再構成し、到達順と片方向上限を確認する。

    引数: args(tuple)、out(tuple)。返り値: 予約・子注文・失効の検査数(dict)。
    """
    r,family,width,variant,cap,value,fee,delay,seed,slip=args
    times,prices,bid,ask,seq,source,pok,qok,tick,start,end,limit=r
    orders,trades,curve,stats,events=out
    assert events.shape[1]==12
    requests={};exits={};failed={};live={};oi=0;opened={};closed={}
    validrows=np.flatnonzero(qok);validtimes=times[validrows]
    maxlong=maxshort=maxlh=maxsh=maxgross=0
    for e in events:
        row,ticket,slot,code=map(int,e[:4]);side=int(e[4]);qty=int(e[5])
        assert 0<=row<len(times) and side in [-1,1] and 0<qty<=cap
        assert e[7]==e[6]+delay
        if code==1:
            assert e[6]==times[row] and pok[row] and e[6]<limit-120.
            assert ticket not in requests and not any(v['slot']==slot for v in live.values())
            requests[ticket]=e;live[ticket]=dict(slot=slot,status=1,side=side,qty=qty)
        elif code==2:
            assert ticket in requests and ticket not in exits and live[ticket]['status']==2
            assert side==-live[ticket]['side'] and qty==live[ticket]['qty']
            assert e[6]>=times[row]
            if e[10]!=6:assert e[6]==times[row] and pok[row]
            else:assert e[6]>=limit-60.
            assert opened[ticket][0]<=row and opened[ticket][11]<=e[6]
            exits[ticket]=e;live[ticket]['status']=3
        elif code in [3,4,5]:
            request=exits[ticket] if code==5 else requests[ticket]
            earliest=max(int(np.searchsorted(validtimes,request[7],side='left')),
                         int(np.searchsorted(validrows,int(request[0])+(1 if delay>0 else 0),side='left')))
            if code==4 and request[9]==2:
                candidates=validrows[earliest:int(np.searchsorted(validrows,row,side='right'))]
                executable=(ask[candidates]+slip*tick<=request[8]) if side==1 else (bid[candidates]-slip*tick>=request[8])
                eligible=candidates[executable]
                assert len(eligible) and eligible[0]==row and times[row]<limit-120.
            else:
                assert earliest<len(validrows) and validrows[earliest]==row
            assert np.array_equal(e[1:3],request[1:3]) and np.array_equal(e[4:],request[4:])
            if code==3:
                assert request[9]==1 and live[ticket]['status']==1 and ticket not in failed
                fill=ask[row]+slip*tick if side==1 else bid[row]-slip*tick
                assert side*(fill-request[8])>0
                failed[ticket]=e;live.pop(ticket)
            else:
                o=orders[oi];oi+=1
                assert int(o[0])==row and int(o[2])==ticket and int(o[6])==(1 if code==4 else 0)
                assert np.array_equal(o[[1,3,4,7,9,10,12,13,14,15]],request[[0,4,5,10,6,7,2,8,11,9]])
                if code==4:
                    assert live[ticket]['status']==1 and ticket not in opened
                    opened[ticket]=o;live[ticket]['status']=2
                else:
                    assert live[ticket]['status']==3 and ticket not in closed
                    closed[ticket]=o;live.pop(ticket)
        elif code==6:
            request=requests[ticket]
            assert request[9]==2 and live[ticket]['status']==1 and ticket not in failed
            assert np.array_equal(e[1:3],request[1:3]) and np.array_equal(e[4:],request[4:])
            candidates=validrows[(validrows>=request[0])&(validrows<row)&(validtimes>=request[7])]
            executable=(ask[candidates]+slip*tick<=request[8]) if side==1 else (bid[candidates]-slip*tick>=request[8])
            assert not executable.any()
            if times[row]<limit-120.:
                assert np.any((events[:,0]==row)&(events[:,3]==2)&np.isin(events[:,10],[5,9]))
            failed[ticket]=e;live.pop(ticket)
        else:raise AssertionError(code)
        long=sum(v['qty'] for v in live.values() if v['side']==1)
        short=sum(v['qty'] for v in live.values() if v['side']==-1)
        assert long<=cap and short<=cap
        maxlong=max(maxlong,long);maxshort=max(maxshort,short)
        lh=sum(v['qty'] for v in live.values() if v['side']==1 and v['status']>1)
        sh=sum(v['qty'] for v in live.values() if v['side']==-1 and v['status']>1)
        maxlh=max(maxlh,lh);maxsh=max(maxsh,sh);maxgross=max(maxgross,lh+sh)
    pe=sum(v['qty'] for v in live.values() if v['status']==1)
    px=sum(v['qty'] for v in live.values() if v['status']==3)
    assert oi==len(orders)
    np.testing.assert_array_equal(stats[[0,1,2,3,6,7,8,11]],[maxlh,maxsh,maxlong,maxshort,pe,px,len(failed),maxgross])
    return dict(新規予約数=len(requests),返済予約数=len(exits),失効数=len(failed),最大予約ロング=maxlong,最大予約ショート=maxshort)
