"""完成実注文接頭の小利益・損失予算停止を少数人工だけで確認する。"""

from copy import deepcopy
import json

import numpy as np

import common
import daily
import policy
import runner


def fixture(symbol: str, spread_ticks: int=1, partial: bool=False) -> tuple[dict,np.ndarray,np.ndarray]:
    """
    機能: 当時新規・任意の部分返済・既場末返済を持つ9正常行を人工生成する。
    引数: symbol(str)、spread_ticks(int)、partial(bool)は商品・入口気配差・部分返済有無。
    返り値: tuple[dict,ndarray,ndarray]はquote・実注文・新規UID。未来玉テンプレートはない。
    """
    n=9;tick=daily.TICK[symbol];opening=4000. if symbol=='TOPIX' else 66000.;q=daily.QUANTITY[symbol]
    bid=np.full(n,opening);ask=bid+tick;ask[1]=opening+spread_ticks*tick
    quotes=dict(seq=np.arange(n,dtype=np.int64),time_s=np.arange(n,dtype=float),bid=bid,ask=ask,quote_valid=np.ones(n,bool))
    orders=[[1,0,1,1,q,ask[1],1,1]];uids=[101]
    remaining=q
    if partial:
        amount=2 if symbol=='TOPIX' else 3;bid[3]=opening+2*tick;ask[3]=bid[3]+tick
        orders.append([3,2,1,-1,amount,bid[3],2,0]);uids.append(-1);remaining-=amount
    bid[7]=opening+3*tick;ask[7]=bid[7]+tick
    orders.append([7,6,1,-1,remaining,bid[7],3,0]);uids.append(-1)
    return quotes,np.asarray(orders,float),np.asarray(uids,np.int64)


def main() -> None:
    """
    機能: 未到達・入口費用による即停止・次quote悪化・残UID丸め・保存aliasを確認する。
    引数: なし。
    返り値: None。旧人工を再実行せず、最小結合証跡だけ所有域へ保存する。
    """
    checks=[]
    assert common.digest(common.HERE/'daily.py')==common.digest(common.ROOT/'work/wave_v106/e01_daily/core.py')
    for symbol in ('TOPIX','NK225'):
        q,orders,uids=fixture(symbol);base=daily.reconstruct(('人工',symbol),orders,uids,q)
        untouched=daily.apply_policy(base,q,dict(profit_ticks=4,loss_ticks=8))
        assert not untouched['control']['発動'];np.testing.assert_array_equal(untouched['orders'],base['orders'])
        checks.append(symbol+' 閾値未到達では実注文/費用を保持')
        q,orders,uids=fixture(symbol,3);tick=daily.TICK[symbol];opening=q['bid'][0]
        q['quote_valid'][2]=False;q['bid'][3]=opening-2*tick;q['ask'][3]=q['bid'][3]+tick
        base=daily.reconstruct(('人工',symbol),orders,uids,q)
        stopped=daily.apply_policy(base,q,dict(profit_ticks=1,loss_ticks=2))
        assert stopped['control']['発動'] and stopped['control']['種別']=='損失予算' and stopped['control']['判断行']==1 and stopped['control']['返済行']==3
        assert len(stopped['orders'])==2 and int(stopped['orders'][-1,1])==1
        assert stopped['summary']['収支']<-stopped['control']['損失予算']
        assert stopped['control']['判断から返済の悪化']<0
        checks.append(symbol+' 入口spread/費用だけでL2到達し次正常quoteの悪化も保存')
        q,orders,uids=fixture(symbol,1,True);tick=daily.TICK[symbol];opening=q['bid'][0]
        q['bid'][4:7]=opening+4*tick;q['ask'][4:7]=q['bid'][4:7]+tick
        base=daily.reconstruct(('人工',symbol),orders,uids,q)
        stopped=daily.apply_policy(base,q,dict(profit_ticks=2,loss_ticks=8))
        assert stopped['control']['発動'] and stopped['control']['判断行']==4 and stopped['control']['返済行']==5
        remaining=daily.QUANTITY[symbol]-(2 if symbol=='TOPIX' else 3)
        assert int(stopped['orders'][-1,4])==remaining and stopped['exit_target_uids'][-1]==101
        assert stopped['order_fees'][-1]==daily.fee(remaining,symbol)
        assert stopped['summary']['費用']==daily.fee(daily.QUANTITY[symbol],symbol)+daily.fee(daily.QUANTITY[symbol]-remaining,symbol)+daily.fee(remaining,symbol)
        assert np.isclose(sum(p['収支'] for p in stopped['parent']),stopped['equity_yen'][-1])
        checks.append(symbol+' FIFO部分返済後の残UIDにfloor料金と実清算を適用')
    configs=policy.configs();assert len(configs)==18 and sum(c['saved_alias'] for c in configs)==2
    q,orders,uids=fixture('TOPIX');base=daily.reconstruct(('人工','TOPIX'),orders,uids,q)
    difference=runner.compare(base,base);assert all(difference[k]==0 for k in runner.FIELDS) and not difference['元勝ち親が赤字化']
    checks.append('P1L8保存aliasは同じ完成親経済のリンク再利用、追加政策会計へ数えない')
    flat=deepcopy(base);flat['parent']=[dict(p,収支=-1.) for p in base['parent']];flat['summary']=dict(base['summary'],収支=-1.)
    difference=runner.compare(base,flat);assert len(difference['元勝ち親が赤字化'])==1
    checks.append('停止幅変更の共通親勝ち赤字化を検出し、全差の5寄与へ含める')
    proof=dict(全合格=True,検査数=len(checks),検査=checks,source_SHA256=runner.sources(),
        旧daily数式同bytes=True,旧人工再実行=0,正式保存input読取=0,正式金融結果読取=0,
        新金融再生=0,engine再生=0,原NPZ読取=0,現在snapshot読取=0,API取得=0)
    common.write(common.HERE/'小利益と損失予算の最小結合人工.json',proof)
    print(json.dumps(dict(全合格=True,純人工検査=len(checks)),ensure_ascii=False))


if __name__=='__main__':main()
