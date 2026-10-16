"""全normal代理のscalar一致と保有中AND退出を金融前に確認する。"""

import traceback
import numpy as np

import common
import catalog
import daily
import features
import policy
import votes


def raw_fixture(seed: int) -> dict:
    """
    機能: 同clock・未知・逆時計・窓外reset・seq断裂を含む小原行を作る。
    引数: seed(int)は再現用人工番号。
    返り値: dictは人工proxy入力。正式市場を読まない。
    """
    rng=np.random.default_rng(seed);n=90;time=np.cumsum(rng.integers(0,4,n)).astype(float)
    seq=np.arange(n,dtype=np.int64);bid=np.full(n,100.);ask=np.full(n,101.)
    last=rng.choice([99.,100.5,102.],n);delta=rng.choice([0.,1.,2.],n)
    usable=np.ones(n,bool);reset=np.zeros(n,np.uint16)
    if seed%5==0:usable[12]=False;delta[12]=np.nan
    if seed%5==1:time[25]=np.nan
    if seed%5==2:time[45]=time[40]-2.
    if seed%5==3:seq[50:]+=1
    if seed%5==4:bid[35]=np.nan
    if seed%3==0:reset[18]=128
    return dict(raw_seq=seq,price_time_s=time,last=last,bid=bid,ask=ask,
        volume_delta=delta,volume_delta_usable=usable,volume_reset_reason=reset)


def market_fixture(symbol: str, side: int=1, partial: bool=False) -> tuple[dict,dict,dict]:
    """
    機能: 実新規・4tick逆行・後の回復・任意部分返済を持つ人工GU接頭を作る。
    引数: symbol(str)、side(int)、partial(bool)は商品・方向・部分返済。
    返り値: tuple[dict,dict,dict]は独立実会計・quote・当時normal票。
    """
    tick=daily.TICK[symbol];qty=daily.QUANTITY[symbol];n=10
    bid=np.array([100.,100.,100.,97.,96.,101.,104.,104.,104.,104.])*tick;ask=bid+tick
    orders=[[1,0,0,1,qty,101.*tick,90,1]];uids=[0];remaining=qty
    if partial:
        take=2 if symbol=='TOPIX' else 3
        orders.append([3,2,0,-1,take,bid[3],91,0]);uids.append(-1);remaining-=take
    orders.append([8,7,0,-1,remaining,bid[8],91,0]);uids.append(-1)
    orders=np.asarray(orders,float)
    if side<0:
        bid,ask=200.*tick-ask,200.*tick-bid;orders[:,3]*=-1;orders[:,5]=200.*tick-orders[:,5]
    q=dict(bid=bid,ask=ask,quote_valid=np.ones(n,bool),seq=np.arange(n,dtype=np.int64),time_s=np.arange(n,dtype=float))
    base=daily.reconstruct(('人工',symbol),orders,np.asarray(uids,np.int64),q)
    observed=dict(known=np.ones(n,bool),up_votes=np.full(n,2 if side<0 else 0,np.int32),
        down_votes=np.full(n,2 if side>0 else 0,np.int32),balance=np.full(n,-float(side)))
    return base,q,observed


def run() -> None:
    """
    機能: scalar同値・買売・flat/未知・P1/hard8先着・次q/部分料を人工だけで点検する。
    引数: なし。
    返り値: None。金融・原NPZ・現在APIを使わず証跡を保存する。
    """
    scalar_count=0;checks=[]
    for seed in range(15):
        raw=raw_fixture(seed);ctx=votes.context(raw);mapping=np.arange(len(raw['raw_seq']),dtype=np.int64)
        for w in (10,30,60):
            out=features.all_normal(raw,ctx,mapping,w)
            for row in mapping:
                truth=votes.measure(raw,ctx,int(row),w,1)
                assert bool(out['known'][row])==truth['known'] and int(out['reason'][row])==truth['reason']
                assert int(out['up_votes'][row])==truth.get('measured_up_votes',0)
                assert int(out['down_votes'][row])==truth.get('measured_down_votes',0)
                if truth['balance'] is not None:assert out['balance'][row]==truth['balance']
                scalar_count+=1
            cut=40;short={k:v[:cut] for k,v in raw.items()};prefix=features.all_normal(short,votes.context(short),mapping[:cut],w)
            for name in ('known','reason','up_votes','down_votes','balance'):
                np.testing.assert_array_equal(out[name][:cut],prefix[name])
            checks.append(dict(観点='全normal scalar/同clock/未知/seq/接頭',seed=seed,window=w))
    # ----------------------------------------
    # 窓外同clockresetを無理に持ち込まない。代理定義は修正52ed exact。
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            for partial in (False,True):
                base,q,obs=market_fixture(symbol,side,partial);cfg=catalog.configs()[0]
                fresh=policy.apply_policy(base,q,obs,cfg)
                assert fresh['control']['種別']=='逆票かつ4呼値損失' and fresh['control']['判断行']==3 and fresh['control']['返済行']==4
                assert fresh['orders'][-1,6]==96 and fresh['exit_target_uids'][-1]==0
                assert fresh['summary']['費用']==sum(daily.fee(int(o[4]),symbol) for o in fresh['orders'])
                assert fresh['control']['判断から返済の悪化']<0
                # 未知では早期条件なし、P1/hard8の経済は元通り。
                unknown={k:v.copy() for k,v in obs.items()};unknown['known'][:]=False
                off=policy.apply_policy(base,q,unknown,cfg);old=daily.apply_policy(base,q,dict(profit_ticks=1,loss_ticks=8))
                for name in ('orders','order_uids','order_fees','equity_yen','liquidation_yen','long_qty','short_qty'):
                    np.testing.assert_array_equal(off[name],old[name])
                assert off['summary']==old['summary']
                # 判断後に票が戻っても、予約は次正常quoteへ残す。
                delayed={k:v.copy() for k,v in obs.items()};delayed['balance'][4:]=float(side)
                q['quote_valid'][4]=False
                late=policy.apply_policy(base,q,delayed,cfg)
                assert late['control']['判断行']==3 and late['control']['返済行']==5
                checks.append(dict(観点='実残方向/AND/未知off/次q/料金/判断後票回復',symbol=symbol,side=side,partial=partial))
    # ----------------------------------------
    # 条件の閾値だけでなく、当行に返済済みでflatの旧親を使わない。
    base,q,obs=market_fixture('TOPIX');closed=daily.reconstruct(('人工','TOPIX'),np.array([[1,0,0,1,5,q['ask'][1],90,1],[3,2,0,-1,5,q['bid'][3],91,0]]),np.array([0,-1]),q)
    assert not policy.early_mask(closed,obs,'TOPIX')[3:].any()
    base,q,obs=market_fixture('TOPIX');aligned={k:v.copy() for k,v in obs.items()};aligned['balance'][:]=1.
    keep=policy.apply_policy(base,q,aligned,catalog.configs()[0]);assert keep['control']['種別']=='利益目標'
    # hard8と早期が同時ならhardを理由とする。
    q['bid'][2]=90.*daily.TICK['TOPIX'];q['ask'][2]=q['bid'][2]+daily.TICK['TOPIX']
    hard=daily.reconstruct(base['key'],base['orders'],base['order_uids'],q)
    hardout=policy.apply_policy(hard,q,obs,catalog.configs()[0]);assert hardout['control']['判断行']==2 and hardout['control']['種別']=='損失予算'
    checks.append(dict(観点='flat旧親/順行保持/P1先着/hard8優先'))
    common.write(common.HERE/'全normal票と逆票損失退出の人工検査.json',dict(全合格=True,
        検査数=len(checks),scalar全normal同値=scalar_count,検査=checks,source_SHA256=common.source_hashes(),
        正式input読取=0,金融結果読取=0,新金融=0,原NPZ=0,API=0))
    print('全normal票と逆票AND損失退出の人工合格',flush=True)


if __name__=='__main__':
    try:run()
    except Exception:
        common.write(common.HERE/'人工False.json',dict(全合格=False,原因=traceback.format_exc(),source_SHA256=common.source_hashes(),新金融=0));raise
