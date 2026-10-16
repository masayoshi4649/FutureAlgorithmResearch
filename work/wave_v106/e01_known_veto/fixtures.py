"""旧人工の二関数だけを同じソースで私有コピーする。実入力は使用しない。"""

import numpy as np
import catalog
import daily
import old_engine


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
