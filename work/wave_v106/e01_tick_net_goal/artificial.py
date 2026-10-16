"""日次固定純目標のちょうど到達・次気配悪化・残UID料金を最小人工で検査する。"""

from copy import deepcopy
import json

import numpy as np

import common
import daily
import policy
import runner


def fixture(symbol: str, partial: bool=False) -> tuple[dict,np.ndarray,np.ndarray]:
    """
    機能: 当時新規・任意の部分返済・旧GU場内返済を持つ人工正常気配を生成する。
    引数: symbol(str)、partial(bool)は商品と部分返済有無。
    返り値: tuple[dict,ndarray,ndarray]はquote・八列実注文・UID。実市場を使わない。
    """
    n=9;tick=daily.TICK[symbol];opening=4000. if symbol=='TOPIX' else 66000.;q=daily.QUANTITY[symbol]
    bid=np.full(n,opening);ask=bid+tick;entry=ask[1]
    bid[3]=entry+tick;ask[3]=bid[3]+tick
    bid[7]=entry+3*tick;ask[7]=bid[7]+tick
    quotes=dict(seq=np.arange(n,dtype=np.int64),time_s=np.arange(n,dtype=float),bid=bid,ask=ask,quote_valid=np.ones(n,bool))
    orders=[[1,0,1,1,q,entry,1,1]];uids=[101];remaining=q
    if partial:
        amount=2 if symbol=='TOPIX' else 3;bid[2]=entry+tick;ask[2]=bid[2]+tick
        orders.append([2,1,1,-1,amount,bid[2],2,0]);uids.append(-1);remaining-=amount
    orders.append([7,6,1,-1,remaining,bid[7],3,0]);uids.append(-1)
    return quotes,np.asarray(orders,float),np.asarray(uids,np.int64)


def main() -> None:
    """
    機能: 固定円定数・exact倍率・ちょうど到達・未到達・UID料・未来不変を人工検査する。
    引数: なし。
    返り値: None。旧人工は再数えせず、新結合proofのみ私有域へ保存する。
    """
    checks=[];assert common.digest(common.HERE/'daily.py')==common.digest(common.ROOT/'work/wave_v106/e01_daily/core.py')
    assert policy.goals()=={'TOPIX':2082.,'NK225':780.};assert len(policy.configs())==6
    for symbol in ('TOPIX','NK225'):
        config=next(c for c in policy.configs() if c['mode']=='CONFIRM' and c['loss_ticks']==8)
        quote,orders,uids=fixture(symbol);base=daily.reconstruct(('人工',symbol),orders,uids,quote)
        goal=policy.goals()[symbol];assert base['liquidation_yen'][3]==goal
        stopped=policy.apply(base,quote,config)
        assert stopped['control']['発動'] and stopped['control']['判断行']==3 and stopped['control']['返済行']==4
        assert stopped['control']['目標']==goal and stopped['fixed_policy']['profit_ticks_equivalent']*daily.TICK[symbol]*daily.QUANTITY[symbol]*daily.VALUE[symbol]==goal
        assert stopped['summary']['収支']<goal and stopped['control']['判断から返済の悪化']<0
        assert np.array_equal(stopped['orders'][:1],orders[:1]) and not np.any(stopped['orders'][1:,7])
        checks.append(symbol+' 1tick純目標ちょうど到達を>=で検出し、次気配悪化は実額へ残す')
        changed=deepcopy(quote);changed['bid'][5:]+=100*daily.TICK[symbol];changed['ask'][5:]=changed['bid'][5:]+daily.TICK[symbol]
        changed_orders=orders.copy();changed_orders[-1,5]=changed['bid'][7]
        future=policy.apply(daily.reconstruct(('人工',symbol),changed_orders,uids,changed),changed,config)
        np.testing.assert_array_equal(future['orders'],stopped['orders']);assert future['control']==stopped['control']
        checks.append(symbol+' 返済後の未来価格/旧終了利益を変更しても初判断と新実注文は不変')
        quote,orders,uids=fixture(symbol);quote['bid'][:]=quote['bid'][0];quote['ask'][:]=quote['bid']+daily.TICK[symbol];orders[-1,5]=quote['bid'][7]
        base=daily.reconstruct(('人工',symbol),orders,uids,quote);untouched=policy.apply(base,quote,config)
        assert not untouched['control']['発動'];np.testing.assert_array_equal(untouched['orders'],base['orders'])
        checks.append(symbol+' 純目標/損失未到達では元実注文と料金を同一保持')
        quote,orders,uids=fixture(symbol,True);base=daily.reconstruct(('人工',symbol),orders,uids,quote)
        stopped=policy.apply(base,quote,config);remaining=daily.QUANTITY[symbol]-(2 if symbol=='TOPIX' else 3)
        assert stopped['control']['判断行']==2 and stopped['control']['返済行']==3
        assert stopped['orders'][-1,4]==remaining and stopped['exit_target_uids'][-1]==101
        assert stopped['order_fees'][-1]==daily.fee(remaining,symbol)
        assert stopped['fixed_policy']['goal_yen']==goal
        assert stopped['summary']['費用']==sum(daily.fee(int(o[4]),symbol) for o in stopped['orders'])
        checks.append(symbol+' 部分返済後も目標は初回q固定、残UID料だけ残qtyへ別floor')
        quote,orders,uids=fixture(symbol);entry=orders[0,5];tick=daily.TICK[symbol]
        quote['bid'][3]=entry-4*tick;quote['ask'][3]=quote['bid'][3]+tick
        quote['quote_valid'][4]=False;quote['bid'][5]=entry-6*tick;quote['ask'][5]=quote['bid'][5]+tick
        low=dict(config,loss_ticks=4);base=daily.reconstruct(('人工',symbol),orders,uids,quote);stopped=policy.apply(base,quote,low)
        assert stopped['control']['種別']=='損失予算' and stopped['control']['判断行']==3 and stopped['control']['返済行']==5
        assert stopped['summary']['収支']<-stopped['control']['損失予算']
        checks.append(symbol+' 損失4tick初到達と不正quote待ち、次正常quoteの予算超過を保存')
    common.write(runner.ARTIFICIAL,dict(全合格=True,検査数=len(checks),検査=checks,source_SHA256=runner.sources(),
        旧daily同bytes=True,旧数式人工再実行=0,完成input読取=0,完成巨大ledger読取=0,新金融再生=0,
        engine再生=0,原NPZ読取=0,現在snapshot読取=0,API取得=0))
    print(json.dumps(dict(全合格=True,最小人工=len(checks),金融0=True),ensure_ascii=False))


if __name__=='__main__':main()
