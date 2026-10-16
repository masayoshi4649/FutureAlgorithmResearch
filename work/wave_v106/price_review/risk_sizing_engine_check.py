"""固定後の新数量エンジンを独立人工の影・実玉・料金で点検する。"""

from pathlib import Path
import importlib.util
import json
import os
import sys

import numpy as np
import numba

from risk_sizing_oracle import CAP, LOSS, VALUE, fee, sized_quantity, scaled_returns
from range_engine_check import digest


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_risk_sizing'
sys.path.insert(0,str(SOURCE))
sys.dont_write_bytecode=True
os.environ['NUMBA_CACHE_DIR']=str(HERE/'risk_sizing_jit')
numba.config.CACHE_DIR=str(HERE/'risk_sizing_jit')
import engine


def module(path: Path, name: str):
    """
    機能: 私有対照sourceを固有の名前で読み込み、人工にだけ使う。
    引数: path(Path)はsource、name(str)は他importと重複しない名前。
    返り値: moduleは対照関数。正式入力及び旧JIT保存域を実行しない。
    """
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value); return value


def fixture(symbol: str, side: int=1, zero_partial: bool=False) -> dict:
    """
    機能: 所有人工を使わず、元影数量で複数返済と次親を作る。
    引数: symbol(str)、side(int)、zero_partial(bool)は商品・方向・一枚選択例。
    返り値: dictは人工配列と元影数量。市場データは含まない。
    """
    virtual=CAP[symbol]; n=15
    base=100. if symbol=='TOPIX' else 1000.; tick=.5 if symbol=='TOPIX' else 10.
    spread=tick; atr=(3. if zero_partial else 1.) if symbol=='TOPIX' else (130. if zero_partial else 40.)
    bid=np.full(n,base); ask=bid+spread; prices=(bid+ask)/2; times=np.arange(n,dtype=float)
    parts=(2,1,2) if symbol=='TOPIX' else (5,2,3)
    feed=np.array([[1,0,0,side,virtual,prices[1],0,1,0,atr],
        [3,0,0,-side,parts[0],prices[3],0,0,0,0],
        [4,0,0,-side,parts[1],prices[4],0,0,0,0],
        [6,0,0,-side,parts[2],prices[6],0,0,0,0],
        [8,0,1,side,virtual,prices[8],0,1,0,atr],
        [11,0,1,-side,virtual,prices[11],0,0,0,0]],float)
    return dict(symbol=symbol,side=side,virtual=virtual,parts=parts,times=times,prices=prices,bid=bid,ask=ask,
        qok=np.ones(n,bool),quiet=np.zeros(n,bool),quiet_force=np.zeros(n,bool),feed=feed,
        end=14.,cap=2*CAP[symbol],tick=tick,atr=atr,mask=np.ones(n,bool))


def invoke(a: dict, enabled: bool=True, python: bool=True) -> tuple:
    """
    機能: 純人工を新エンジンのPython又は私有JIT関数へ渡す。
    引数: a(dict)、enabled/python(bool)は人工素材・数量制御・実行方式。
    返り値: tupleは新11配列。実注文及び正式バックテストを行わない。
    """
    symbol=a['symbol']; numerator,denominator=(209,5) if symbol=='TOPIX' else (11,1)
    fn=engine.simulate.py_func if python else engine.simulate
    return fn(a['times'],a['prices'],a['bid'],a['ask'],a['qok'],a['feed'],a['quiet'],a['quiet_force'],
        a['end'],a['cap'],a['tick'],0.,True,a['mask'],enabled,LOSS[symbol],1.,VALUE[symbol],numerator,denominator)


def account_check(a: dict, values: tuple) -> dict:
    """
    機能: 実注文接頭だけから料金、保有、清算時価を独立に復元する。
    引数: a(dict)、values(tuple)は人工気配とエンジン出力。
    返り値: dictは独立支払料・最終収支。エンジンdaily関数を使用しない。
    """
    symbol=a['symbol']; orders,uids=values[0],values[5]; held={}; cash=0.; paid=0; position=0; cursor=0
    markbid=0.; markask=0.; maximum=0; fees=[]
    for row in range(len(a['times'])):
        good=bool(a['qok'][row] and np.isfinite(a['bid'][row]) and np.isfinite(a['ask'][row]) and 0<a['bid'][row]<a['ask'][row])
        if good: markbid=a['bid'][row]; markask=a['ask'][row]
        while cursor<len(orders) and int(orders[cursor,0])==row:
            order=orders[cursor]; source,cid,side,q,new=map(int,(order[1],order[2],order[3],order[4],order[7]))
            assert 0 <= source < row and q>0 and good
            assert order[5]==(a['ask'][row] if side==1 else a['bid'][row])
            cost=fee(q,symbol); paid+=cost; fees.append(cost); cash-=side*q*order[5]; position+=side*q
            if new:
                uid=int(uids[cursor]); assert uid>=0 and uid not in held
                held[uid]=dict(cid=cid,side=side,remaining=q)
            else:
                assert uids[cursor]==-1; need=q
                for state in held.values():
                    if state['cid']==cid and state['side']==-side:
                        closed=min(need,state['remaining']); state['remaining']-=closed; need-=closed
                assert need==0
            cursor+=1
        assert abs(position)<=a['cap']; maximum=max(maximum,abs(position))
        reserve=sum(fee(s['remaining'],symbol) for s in held.values() if s['remaining'])
        marked=(cash+max(position,0)*markbid+min(position,0)*markask)*VALUE[symbol]-paid
        observed=values[10][row]
        assert observed[0]==paid and observed[1]==reserve
        np.testing.assert_allclose(observed[2:],(marked,marked-reserve,max(0.,LOSS[symbol]+marked-reserve)),rtol=1e-12,atol=1e-7)
        assert int(values[7][row,3])-int(values[7][row,4])==position
    assert cursor==len(orders)
    return dict(料金=paid,注文別料金=fees,収支=marked,残玉=abs(position),最大玉=maximum)


def shadow_check(a: dict, values: tuple) -> None:
    """
    機能: 元feedの方向と数量だけから全行の影残玉を独立復元する。
    引数: a(dict)、values(tuple)は人工feedと実出力。
    返り値: None。実数量、busy又は見送りで影が変われば拒否する。
    """
    delta=np.zeros(len(a['times']),np.int64)
    for order in a['feed']: delta[int(order[0])]+=int(order[3])*int(order[4])
    np.testing.assert_array_equal(values[7][:,1],np.cumsum(delta))


def clone(a: dict) -> dict:
    """
    機能: 人工配列を独立コピーし、後続反例の変更を元へ混ぜない。
    引数: a(dict)は人工素材。
    返り値: dictはnumpy配列を別bytesへコピーした素材。
    """
    return {k:v.copy() if isinstance(v,np.ndarray) else v for k,v in a.items()}


def main() -> None:
    """
    機能: 完成済みsourceを、独立数量期待値と会計・影・接頭の反例へ接続する。
    引数: なし。源の完成通知後だけ実行し、正式金融は禁止する。
    返り値: Noneは自所有の人工証跡。実装が変更されたら別証跡で固定し直す。
    """
    target=HERE/'risk_sizing_実数量影分離と実料金予約及び接頭の独立人工.json'; assert not target.exists()
    scope=[SOURCE/name for name in ('engine.py','order_kernel.py','baseline.py')]
    sources={p.relative_to(ROOT).as_posix():digest(p) for p in scope}
    baseline=module(SOURCE/'baseline.py','独立旧数量対照'); rows=[]; arrays=0
    for symbol in CAP:
        for side in (1,-1):
            for tiny in (False,True):
                a=fixture(symbol,side,tiny); values=invoke(a); jit=invoke(a,python=False)
                for observed,expected in zip(values,jit):
                    np.testing.assert_array_equal(observed,expected); arrays+=1
                shadow_check(a,values); acct=account_check(a,values)
                expected=sized_quantity(a['atr'],a['bid'][1],a['ask'][1],LOSS[symbol],symbol)['quantity']
                assert int(values[9][0,4])==expected
                first=values[0][values[0][:,2]==0]; assert int(first[0,4])==expected
                returns=tuple(int(x) for x in first[first[:,7]==0,4])
                full=scaled_returns(expected,a['virtual'],a['parts'])
                assert returns==tuple(x for x in full if x)
                second=values[9][1]; first_net=-expected*(a['ask'][1]-a['bid'][1])*VALUE[symbol]-sum(fee(int(o[4]),symbol) for o in first)
                np.testing.assert_allclose(second[8:10],(first_net,max(0.,LOSS[symbol]+first_net)),rtol=1e-12,atol=1e-7)
                expected2=sized_quantity(a['atr'],a['bid'][8],a['ask'][8],max(0.,LOSS[symbol]+first_net),symbol)['quantity']
                assert int(second[4])==expected2
                rows.append(dict(商品=symbol,方向=side,一枚例=tiny,公開q=expected,返済=returns,次公開q=expected2,会計=acct))
                off=invoke(a,enabled=False)
                old=baseline.simulate.py_func(a['times'],a['prices'],a['bid'],a['ask'],a['qok'],a['feed'],a['quiet'],a['quiet_force'],a['end'],a['cap'],a['tick'],0.,True,a['mask'])
                for observed,expected_array in zip(off[:9],old):
                    np.testing.assert_array_equal(observed,expected_array); arrays+=1
                # ----------------------------------------
                # 未観測の次気配を飛ばしても、公開行の数量と残予算は変えない。
                changed=clone(a); changed['bid'][2:]+=100*a['tick']; changed['ask'][2:]+=100*a['tick']; changed['prices'][2:]+=100*a['tick']
                future=invoke(changed)
                np.testing.assert_array_equal(values[9][0],future[9][0]); arrays+=1
                # 全入力を未来まで持つ走行と、同じ当時行で切った走行の接頭一致。
                for endrow in (1,2,3,4,6,8,11):
                    cut=clone(a)
                    for k in ('times','prices','bid','ask','qok','quiet','quiet_force','mask'): cut[k]=cut[k][:endrow+1]
                    cut['feed']=cut['feed'][cut['feed'][:,0]<=endrow]; cut['end']=1000.
                    prefix=invoke(cut)
                    np.testing.assert_array_equal(prefix[0],values[0][values[0][:,0]<=endrow]); arrays+=1
                    np.testing.assert_array_equal(prefix[7],values[7][:endrow+1]); arrays+=1
                    np.testing.assert_array_equal(prefix[9],values[9][values[9][:,0]<=endrow]); arrays+=1
                    np.testing.assert_array_equal(prefix[10],values[10][:endrow+1]); arrays+=1
                # 既予約の部分返済と静観強制返済を重複させない。
                quiet=clone(a); quiet['quiet'][4]=True
                forced=invoke(quiet); shadow_check(quiet,forced); forced_account=account_check(quiet,forced)
                close=forced[0][(forced[0][:,2]==0)&(forced[0][:,7]==0)]
                assert len(close)==1 and close[0,4]==int(values[9][0,4]) and close[0,6]==92
                rows.append(dict(商品=symbol,方向=side,種類='部分予約の静観取消と全残返済',会計=forced_account))
                # 新規待機中に影の返済が来たら取消し、後の正常気配で遅れて建てない。
                cancel=clone(a); cancel['qok'][2:5]=False
                cancelled=invoke(cancel); shadow_check(cancel,cancelled); account_check(cancel,cancelled)
                assert not np.any(cancelled[0][:,2]==0)
                # 欠測中に旧影を閉じて次親を公開しても、旧実残玉の返済を次親へ流用しない。
                busy=clone(a); busy['qok'][4:8]=False
                busy['feed'][4,0]=6; busy['feed'][4,9]=a['atr']; busy['feed'][5,0]=9
                output=invoke(busy); shadow_check(busy,output); account_check(busy,output)
                assert not np.any(output[0][:,2]==1) and np.all(output[0][output[0][:,7]==0,2]==0)
                published=output[8][(output[8][:,1]==1)&(output[8][:,2]==1)]
                assert len(published)==1 and published[0,17]==94
    assert sources=={p.relative_to(ROOT).as_posix():digest(p) for p in scope}
    proof=dict(全合格=True,source_SHA256=sources,独立source_SHA256=digest(Path(__file__)),配列比較数=arrays,人工観測=rows,
        算術契約='risk_sizing_oracle.pyの十進料金・整数累積切り捨て・当行qを使用。元所有fixtureを使わない。',
        検査=['公開当行だけの数量','影の元数量と継続','累積返済と0枚非注文','次親の実現収支を使う残予算',
              '実注文ごとの料金と残返済料','制御無効時の旧9配列同値','Pythonと私有JIT同値','当時接頭及び将来気配反転',
              '静観で予約部分返済を取消して全残返済','新規待機の取消','欠測中の旧返済待ちと次親busy'],
        原入力=0,原板=0,NPZ=0,API=0,金融=0,旧source及び旧JIT変更=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,配列=arrays,SHA256=digest(target)),ensure_ascii=False))


if __name__=='__main__': main()
