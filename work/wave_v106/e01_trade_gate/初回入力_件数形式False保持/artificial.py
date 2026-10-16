"""公開maskだけの差分、旧同値、FIFO料金と接頭因果を私有人工で確認する。"""

from decimal import Decimal, ROUND_FLOOR
import traceback

import numpy as np

import common
import catalog
import daily
import engine
import interface
import old_engine
import policy
import votes


def fixture(symbol: str, side: int=1) -> dict:
    """
    機能: 同行到達不可・部分返済・後続親を持つ商品呼値の人工feedを作る。
    引数: symbol(str)、side(int)は商品と買売方向。
    返り値: dictは人工専用のnormal気配・紙上feed・既知票。
    """
    tick=daily.TICK[symbol];q=catalog.QUANTITY[symbol]
    p=np.array([100.,100.,97.,98.,100.,104.,101.,101.,100.,97.,104.,104.,101.,101.])*tick
    bid=np.array([99.,95.,97.,97.,99.,103.,100.,100.,95.,97.,103.,103.,100.,100.])*tick
    ask=np.array([101.,97.,99.,98.,101.,105.,102.,102.,97.,98.,105.,105.,102.,102.])*tick
    first=q//2
    feed=np.array([[1,0,0,1,q,100.*tick,0,1,0,10.*tick],
                   [5,0,0,-1,first,104.*tick,0,0,0,0],
                   [6,0,0,-1,q-first,101.*tick,0,0,0,0],
                   [8,0,1,1,q,100.*tick,0,1,0,10.*tick],
                   [11,0,1,-1,q,104.*tick,0,0,0,0]],float)
    if side<0:
        p=200.*tick-p;bid,ask=200.*tick-ask,200.*tick-bid
        feed[:,3]*=-1;feed[:,5]=200.*tick-feed[:,5]
    times=np.arange(len(p),dtype=float)
    quotes=dict(seq=np.arange(len(p),dtype=np.int64),time_s=times,bid=bid,ask=ask,quote_valid=np.ones(len(p),bool))
    record=dict(seq=quotes['seq'],time_s=times,price=p,start=0.,end=13.,limit=13.,tick=tick)
    values={int(o[0]):dict(known=True,reason=0,direction_votes=2,balance=1.,accepted=True) for o in feed[feed[:,7]==1]}
    return dict(symbol=symbol,record=record,quotes=quotes,feed=feed,quiet=np.zeros(len(p),bool),
        quiet_force=np.zeros(len(p),bool),trade_features={str(w):{k:dict(v) for k,v in values.items()} for w in (10,30,60)})


def legacy(a: dict, config: dict) -> tuple:
    """
    機能: 私有exact旧sourceだけで人工対照を再生する。
    引数: a/config(dict)は人工素材と二執行条件。
    返り値: tupleは旧契約9配列。正式資料は使わない。
    """
    r,q=a['record'],a['quotes']
    return old_engine.simulate(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],a['feed'],
        a['quiet'],a['quiet_force'],r['limit'],catalog.CAP[a['symbol']],r['tick'],
        config['offset_atr'],config['execution']=='D0')


def raw_fixture() -> dict:
    """
    機能: 窓外同clock不正と方向票を分けた小原行を作る。
    引数: なし。
    返り値: dictは代理票専用人工。実原行を読まない。
    """
    times=np.array([0.,10.,10.,11.,12.,20.,20.,21.])
    n=len(times);bid=np.full(n,99.);ask=np.full(n,101.)
    raw=dict(raw_seq=np.arange(n,dtype=np.int64),price_time_s=times,last=np.full(n,102.),bid=bid,ask=ask,
             volume_delta=np.ones(n),volume_delta_usable=np.ones(n,bool),volume_reset_reason=np.zeros(n,np.uint16))
    raw['volume_delta_usable'][0]=False;raw['volume_delta'][0]=np.nan
    raw['volume_delta_usable'][2]=False;raw['volume_delta'][2]=np.nan
    return raw


def run() -> None:
    """
    機能: 修正代理・公開mask・旧同値・実注文料・未来接頭を結果前に確認する。
    引数: なし。
    返り値: None。新金融・旧paper・大型入力0で証跡を新規保存する。
    """
    target=common.HERE/'E01公開maskとUID料金及び接頭の人工検査.json'
    assert not target.exists();checks=[];agreements=0
    for mode in ('CONFIRM','VETO'):
        for known in (False,True):
            for count in (0,1,2,3):
                for balance in (-1.,-.25,-.249,0.,.249,.25,1.):
                    v=dict(known=known,reason=8 if not known else 0,direction_votes=count,
                           balance=balance if known and count else None)
                    allow,_=policy.verdict(v,mode)
                    expected=known and count>=2 and balance>=.25 if mode=='CONFIRM' else not(known and count>=2 and balance<=-.25)
                    assert allow==expected;checks.append(dict(観点='政策真偽表',mode=mode,known=known,votes=count,balance=balance))
    raw=raw_fixture();value=votes.measure(raw,votes.context(raw),6,10,1)
    assert value['known'] and value['direction_votes']==4 and value['balance']==1.
    bad=raw_fixture();bad['volume_delta_usable'][5]=False;bad['volume_delta'][5]=np.nan
    assert not votes.measure(bad,votes.context(bad),6,10,1)['known']
    checks.append(dict(観点='同clock窓外不正は除外し窓内不正だけ未知',窓外原行=2,窓内原行=5))
    # ----------------------------------------
    # 通過maskは旧全9配列と完全一致。実料金は注文単位Decimalで再確認する。
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            a=fixture(symbol,side)
            for c in catalog.configs():
                old=legacy(a,c)
                fresh=interface.execute(a,c);py=interface.execute(a,c,True)
                for x,y,z in zip(old,fresh,py):
                    np.testing.assert_array_equal(x,y);np.testing.assert_array_equal(y,z);agreements+=2
                assert fresh[0][0,0]==(2 if c['execution']=='D0' else 3) and fresh[0][0,1]==1
                out=interface.account_output('人工',a,c,fresh)
                expected=[int((Decimal(str(daily.FEE[symbol]))*Decimal(int(o[4]))).to_integral_value(rounding=ROUND_FLOOR)) for o in out['orders']]
                np.testing.assert_array_equal(out['order_fees'],expected)
                if symbol=='TOPIX' and c['exit']=='GU':np.testing.assert_array_equal(out['order_fees'][:3],[209,83,125])
            checks.append(dict(観点='通過旧exactとPythonJIT及び注文別料',symbol=symbol,side=side))
            # ----------------------------------------
            # 拒否しても影の部分返済・後続親feedを消さず、別の親だけを実約定できる。
            a=fixture(symbol,side)
            for w in (10,30,60):a['trade_features'][str(w)][1]['balance']=-1.
            c=next(v for v in catalog.configs() if v['window_seconds']==10 and v['mode']=='VETO' and v['exit']=='GU' and v['execution']=='D20')
            fresh=interface.execute(a,c);assert len(fresh[0])==2 and np.all(fresh[0][:,2]==1)
            assert fresh[7][1,1]==side*catalog.QUANTITY[symbol] and fresh[7][6,1]==0
            assert int(fresh[8][fresh[8][:,2]==0][0,17])==95
            interface.account_output('人工拒否',a,c,fresh)
            checks.append(dict(観点='拒否後も影部分返済と後続親を保持',symbol=symbol,side=side))
    # ----------------------------------------
    # 非公開行のmaskがFalseでも待機を追加取消しない。同到達行の元返済とquietは旧順。
    a=fixture('TOPIX');r,q=a['record'],a['quotes'];m=np.ones(len(r['price']),bool);m[2:8]=False
    got=engine.simulate(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],a['feed'],a['quiet'],a['quiet_force'],r['limit'],10,r['tick'],.2,False,m)
    np.testing.assert_array_equal(got[0],legacy(a,c)[0]);checks.append(dict(観点='公開時以外のmaskはpending保有へ無効'))
    same=fixture('TOPIX');same['feed'][1,0]=3
    got=interface.execute(same,c);assert got[0][0,0]==3 and got[0][1,0]==4
    quiet=fixture('TOPIX');quiet['quiet'][3]=True;got=interface.execute(quiet,c)
    assert not np.any((got[0][:,2]==0)&(got[0][:,7]==1))
    checks.append(dict(観点='既live到達同行維持と既知quiet取消優先'))
    # ----------------------------------------
    # 切断端で未返済を残し、未来気配・mask変更が前方の予約と注文を変えない。
    a=fixture('TOPIX');full=interface.execute(a,c);cut=5
    short=dict(a,record={k:v[:cut] if isinstance(v,np.ndarray) else v for k,v in a['record'].items()},
        quotes={k:v[:cut] for k,v in a['quotes'].items()},feed=a['feed'][a['feed'][:,0]<cut],
        quiet=a['quiet'][:cut],quiet_force=a['quiet_force'][:cut])
    partial=interface.execute(short,c)
    np.testing.assert_array_equal(full[0][full[0][:,0]<cut],partial[0])
    np.testing.assert_array_equal(full[2][:cut],partial[2]);np.testing.assert_array_equal(full[7][:cut],partial[7])
    a['quotes']['bid'][cut:]+=100.;a['quotes']['ask'][cut:]+=100.
    future=interface.execute(a,c)
    np.testing.assert_array_equal(full[0][full[0][:,0]<cut],future[0][future[0][:,0]<cut]);np.testing.assert_array_equal(full[2][:cut],future[2][:cut])
    checks.append(dict(観点='未返済prefixと未来BBO不変'))
    common.write(target,dict(全合格=True,検査数=len(checks),PythonJIT旧配列照合数=agreements,検査=checks,
        source_SHA256=common.sources(),原paper再計算=0,大型入力読取=0,新金融=0,原book=0,API=0))
    print('E01公開mask・旧同値・UID料金・接頭の人工合格',flush=True)


if __name__=='__main__':
    try:run()
    except Exception:
        common.write(common.HERE/'人工初回False.json',dict(全合格=False,原因=traceback.format_exc(),source_SHA256=common.sources(),新金融=0));raise
