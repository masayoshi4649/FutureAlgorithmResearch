"""実注文からの独立会計と、支持・episode消費のSOURCE_ONLY監査。"""

from decimal import Decimal, ROUND_FLOOR
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

import numpy as np

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
ENGINE=BASE/'engine'
sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf-8')
os.environ['NUMBA_CACHE_DIR']=str(HERE/'jit')
sys.path.insert(0,str(ENGINE))
import numba
numba.config.CACHE_DIR=str(HERE/'jit')
import core
import signals
import daily


def sha(path: Path) -> str:
    """
    機能: 検査対象sourceの同bytes指紋を計算する。
    引数: path(Path)はsource又は自所有の小証跡。
    返り値: strはSHA256。実入力へ呼び出さない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def charge(q: int,symbol: str) -> int:
    """
    機能: 実注文の枚数ごとに独立Decimalで片道手数料を切り捨てる。
    引数: q(int)は実注文枚数、symbol(str)は商品。
    返り値: intは円料。対象kernel/dailyの料金関数を使わない。
    """
    fee=Decimal('41.8') if symbol=='TOPIX' else Decimal('11')
    return int((fee*Decimal(q)).to_integral_value(rounding=ROUND_FLOOR))


def fixture(symbol: str,side: int,expire: bool=False,unknown: bool=True) -> dict:
    """
    機能: 方向を反射した小BBOと当時根拠を生成し、既入力を読まない。
    引数: symbol(str)、side(int±1)、expire/unknown(bool)は人工反例の切替。
    返り値: dictは45行の小配列。確定Lと根拠は未来ピークから作らない。
    """
    tick=.5 if symbol=='TOPIX' else 10.;base=4000. if symbol=='TOPIX' else 70000.
    offset=np.array([1,1,2,3,3,3,3,5,5,5,7,7,7,7,9,9,9,10,9,11,11,12,13,14,14,12,9,8,1,3,-1,1,1,3,3,2,-2,-4,-4,-4,-4,-4,-4,-4,-4],float)
    if expire:offset[4]=5
    n=len(offset);buy_bid=base+(offset-.5)*tick;buy_ask=buy_bid+tick
    bid=buy_bid if side>0 else 2*base-buy_ask
    ask=buy_ask if side>0 else 2*base-buy_bid
    prices=(bid+ask)/2
    times=600.+np.arange(n,dtype=float)
    known=np.ones(n,bool)
    if unknown:known[[11,18]]=False
    normal=np.ones(n,bool);interval=np.ones(n,bool)
    fresh=np.zeros(n,np.int64);fresh[[1,6,9,12,13,16,20,21,32]]=1
    up=fresh.copy() if side<0 else np.zeros(n,np.int64)
    down=fresh.copy() if side>0 else np.zeros(n,np.int64)
    gate=np.zeros((n,2),bool);gate[:,0 if side>0 else 1]=True
    bucket=np.ones(n,np.int64);confirmed=np.full(n,-1,np.int64)
    level=np.full(n,base)
    candidates,episodes,consumed,retired=signals.generate.py_func(bid,ask,normal,level,level,bucket,confirmed,
        known,known,gate,gate,interval,up,down,tick,2)
    return dict(symbol=symbol,side=side,tick=tick,base=base,cap=10 if symbol=='TOPIX' else 20,
        mult=1000. if symbol=='TOPIX' else 10.,num=209 if symbol=='TOPIX' else 11,den=5 if symbol=='TOPIX' else 1,
        times=times,prices=prices,bid=bid,ask=ask,qok=np.ones(n,bool),quiet=np.zeros(n,bool),force=np.zeros(n,bool),
        normal=normal,known=known,gate=gate,interval=interval,up=up,down=down,
        candidates=candidates,episodes=episodes,consumed=consumed,retired=retired,level=level,bucket=bucket,confirmed=confirmed)


def play(f: dict,mode: int,exit_mode: int,compiled: bool=False,strong: bool=True) -> tuple:
    """
    機能: SOURCE_ONLYの合成配列だけをNativeへ渡す。
    引数: f(dict)はtoy、mode/exit_mode(int)は入口/出口、compiled/strong(bool)は対照。
    返り値: tupleは実注文等。input/cache/金融driver/APIを呼ばない。
    """
    candidates=f['candidates'][f['candidates'][:,1]==mode]
    s=f['gate'].copy() if strong else np.zeros_like(f['gate'])
    call=core.simulate if compiled else core.simulate.py_func
    return call(f['times'],f['prices'],f['bid'],f['ask'],f['qok'],f['quiet'],f['force'],f['normal'],
        f['known'],f['known'],f['gate'],f['gate'],f['interval'],f['up'],f['down'],s,candidates,
        0.,1000.,f['cap'],f['tick'],f['mult'],f['num'],f['den'],exit_mode,
        .00075,.00125,.00075 if exit_mode==1 else .00125,.00025 if exit_mode==1 else .000375,
        .0005 if exit_mode==1 else .00075,.0025,.00375,.5,2)


def oracle(f: dict,orders: np.ndarray,uids: np.ndarray) -> dict:
    """
    機能: 実注文だけを一行ずつ分数現金へ適用し、独立親/UID/全行清算を作る。
    引数: f(dict)はtoy気配、orders/uids(ndarray)はNativeが実際に約定した注文。
    返り値: dictは実料金・親net・全行曲線。日次再構成/Nativeの会計関数を使わない。
    """
    n=len(f['times']);curve=np.zeros((n,6));cash=Fraction();fees=0;position=None;cursor=0
    parents={};last_bid=Fraction();last_ask=Fraction();used_uids=set()
    for row in range(n):
        good=bool(f['qok'][row] and np.isfinite(f['times'][row]) and np.isfinite(f['bid'][row]) and np.isfinite(f['ask'][row]) and 0<f['bid'][row]<f['ask'][row])
        if good:last_bid=Fraction(str(f['bid'][row]));last_ask=Fraction(str(f['ask'][row]))
        while cursor<len(orders) and int(orders[cursor,0])==row:
            o=orders[cursor];uid=int(uids[cursor]);source,cid,side,q,new=map(int,(o[1],o[2],o[3],o[4],o[7]))
            assert 0<=source<row and good and q==f['cap'] and side in (-1,1)
            assert o[5]==f['ask' if side>0 else 'bid'][row]
            p=Fraction(str(o[5]));fee=charge(q,f['symbol']);fees+=fee;cash-=side*q*p
            if new:
                assert position is None and cid not in parents and uid>=0 and uid not in used_uids
                used_uids.add(uid);position=dict(cid=cid,side=side,q=q,price=p,entryfee=fee,uid=uid)
                parents[cid]=dict(方向=side,枚数=q,費用=fee,粗損益=Fraction(),収支=None)
            else:
                assert position is not None and position['cid']==cid and position['side']==-side and position['q']==q and uid==-1
                gross=position['side']*q*(p-position['price'])*int(f['mult']);par=parents[cid]
                par['粗損益']=gross;par['費用']+=fee;par['収支']=gross-par['費用'];position=None
            cursor+=1
        longq=position['q'] if position is not None and position['side']>0 else 0
        shortq=position['q'] if position is not None and position['side']<0 else 0
        reserved=charge(longq+shortq,f['symbol'])
        equity=(cash+longq*last_bid-shortq*last_ask)*int(f['mult'])-fees
        curve[row]=[float(equity),float(equity-reserved),longq,shortq,fees,reserved]
    assert cursor==len(orders) and position is None
    assert all(p['収支'] is not None for p in parents.values())
    assert sum(p['収支'] for p in parents.values())==Fraction(str(curve[-1,0]))
    return dict(curve=curve,parents=parents,fees=fees,UID数=len(used_uids))


def verify(f: dict,mode: int,exit_mode: int) -> dict:
    """
    機能: Nativeと独立注文会計・日次会計・根拠/支持の時系列を三者で確認する。
    引数: f(dict)、mode/exit_mode(int)は同toyの入口/出口。
    返り値: dictは比較項目数と実親/支持更新数。
    """
    a=play(f,mode,exit_mode);b=play(f,mode,exit_mode,compiled=True)
    for i in range(8):np.testing.assert_array_equal(a[i],b[i])
    orders,uids,curve,pubs,judges,events,origins,updates,_=a
    expected=oracle(f,orders,uids)
    np.testing.assert_allclose(curve[:,[0,1,4,5,6,7]],expected['curve'],rtol=1e-12,atol=1e-7)
    quotes=dict(bid=f['bid'],ask=f['ask'],quote_valid=f['qok'],seq=np.arange(len(curve),dtype=np.int64),time_s=f['times'])
    rebuilt=daily.reconstruct(('合成_Day',f['symbol']),orders,uids,quotes)
    for par in rebuilt['parent']:
        e=expected['parents'][par['親']]
        for name in ('粗損益','収支','費用','方向','枚数'):assert float(par[name])==float(e[name])
    assert rebuilt['summary']['費用']==expected['fees'] and len(origins)==expected['UID数']
    assert np.all(orders[:,1]<orders[:,0])
    assert not np.any(np.isin(orders[:,6],(151,152)))
    # ----------------------------------------
    # 支持線は実約定後の未使用probeだけで更新し、有利方向にしか移さない。
    seen={};bycid={int(o[0]):o for o in origins}
    for u in updates:
        row,cid,side=int(u[0]),int(u[1]),int(u[2]);origin=bycid[cid];proof=int(u[5]);entry=int(origin[2])
        assert proof>entry and proof<row and int(u[9])==proof-1
        assert proof not in seen.setdefault(cid,set());seen[cid].add(proof)
        fresh=f['down'][proof] if side>0 else f['up'][proof]
        assert fresh>=1 and f['known'][proof] and f['known'][proof-1] and f['interval'][proof]
        assert side*(f['bid'][row]-f['bid'][proof])>=2*f['tick'] and side*(f['ask'][row]-f['ask'][proof])>=2*f['tick']
        line=max(u[3],f['bid'][proof]-f['tick']) if side>0 else min(u[3],f['ask'][proof]+f['tick'])
        assert u[4]==line and side*(u[4]-u[3])>=0
        assert proof not in (1,12,16,20), ('入口/未知直後/取消済/旧probe再利用',u)
    for o in origins:
        cid=int(o[0]);entry=int(o[2]);side=int(o[4])
        rows=np.flatnonzero((curve[:,8]==cid)&((curve[:,4]+curve[:,5])>0))
        line=curve[rows,11]
        assert np.all(np.diff(side*line)>=0)
        if int(o[15])>=0:assert int(o[15])<entry
    selected=f['candidates'][f['candidates'][:,1]==mode]
    pairs=[(int(e[3]),int(e[1])) for e in selected]
    assert len(pairs)==len(set(pairs))
    assert len(pubs)==len(selected) and len({int(p[3]) for p in pubs})==len(pubs)
    return dict(配列8=8,会計曲線項目=curve.shape[0]*6,実親=len(origins),支持更新=len(updates),根拠検査=len(updates)*9)


def consumption_cases(symbol: str,side: int) -> int:
    """
    機能: FAK失効/保有中拒否の同episodeを復活せず、新episodeのみ再参加できると確認する。
    引数: symbol(str)、side(int)はtoy商品と方向。
    返り値: intは反例ケース数。将来の勝敗を候補の採否へ使わない。
    """
    f=fixture(symbol,side,expire=True)
    a=play(f,2,0,strong=True)
    orders,uids,_,pubs,_,events,origins,_,_=a
    assert len(pubs)==2 and len(origins)==1
    assert int(events[0,7])==98 and int(events[0,8])==0 and int(events[0,2])==0
    assert int(origins[0,0])==1 and int(origins[0,3])==33
    assert not np.any((orders[:,0]<34)&(orders[:,7]==1))
    oracle(f,orders,uids)
    # 同候補は一回消費されるので、その後の安い気配を過去FAKへ充当しない。
    assert not np.any((events[:,1]==1)&(events[:,2]==0)&(events[:,0]>4))
    f=fixture(symbol,side)
    candidates=f['candidates'][f['candidates'][:,1]==2]
    # 生産者が同episodeで再公開しないことを、保有中にも進む元候補列で確認する。
    assert len(candidates)==2 and candidates[0,3]!=candidates[1,3]
    assert not np.any((candidates[:,0]>3)&(candidates[:,0]<30))
    return 2


def main() -> None:
    """
    機能: 閉鎖済sourceをtoyだけで独立監査し、旧証跡やroot源へ変更しない。
    引数: なし。
    返り値: None。所有域へ成功又はFalseを一度保存。実金融/cache/API0。
    """
    paths=sorted(ENGINE.glob('*.py'));before={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    counts=dict(口座=0,実親=0,支持更新=0,配列8=0,会計曲線項目=0,根拠検査=0,反例ケース=0)
    output=HERE/'実注文独立会計と支持非後退及び同事象一回消費の純人工.json'
    assert not output.exists()
    try:
        for symbol in ('TOPIX','NK225'):
            for side in (1,-1):
                for mode in range(3):
                    for exit_mode in range(3):
                        checked=verify(fixture(symbol,side),mode,exit_mode);counts['口座']+=1
                        for name,v in checked.items():counts[name]+=v
                counts['反例ケース']+=consumption_cases(symbol,side)
        assert counts['支持更新']>0 and before=={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
        proof=dict(全合格=True,対象='実注文を独立Fraction/Decimalで親・UID・全行清算へ再構成。買売/両商品/九条件、支持非後退・新probe・同episode一回消費。',
            counts=counts,source_SHA256=before,監査source_SHA256=sha(Path(__file__)),
            未測='実取得入力の性質/真の攻撃量/未知2場/金融効果はこの合成監査から主張しない。',実入力=0,金融=0,API=0)
        output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,proof_SHA256=sha(output),counts=counts,実入力=0,金融=0),ensure_ascii=False))
    except BaseException:
        path=HERE/'独立親会計人工_初回False.json';assert not path.exists()
        path.write_text(json.dumps(dict(全合格=False,source_SHA256=before,原因=traceback.format_exc(),実入力=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':main()
