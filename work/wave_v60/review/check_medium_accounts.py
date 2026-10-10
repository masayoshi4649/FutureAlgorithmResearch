"""中期全口座を売買器と別の会計・出口判定で検算する。"""

from __future__ import annotations

from datetime import date,timedelta
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
MEDIUM=WORK/'medium'


def near(actual: object,expected: object) -> None:
    """機能: Noneと数値を区別し、浮動小数の集計誤差だけを許容する。

    引数: actual/expected(object)。返り値: なし(None)。
    """
    if expected is None:assert actual is None
    else:assert np.isclose(actual,expected,rtol=1e-10,atol=1e-5),(actual,expected)


def account_audit(account: dict,ready: dict,quote: dict,candidate: np.ndarray,config: dict) -> dict:
    """機能: 全注文・返済・判断時刻・原本全行の含み込み収支を独立検算する。

    引数: account/ready/quote/config(dict)、candidate(ndarray)。返り値: 検算統計(dict)。
    """
    orders=np.asarray(account['orders'],float).reshape(-1,15)
    trades=np.asarray(account['trades'],float).reshape(-1,22)
    seq=ready['seq'];stamp=ready['time_s'];tick=ready['tick'];limit=ready['limit']
    value,qty=(1000.,5) if account['symbol']=='TOPIX' else (10.,10)
    fee=(qty*418)//10 if account['symbol']=='TOPIX' else qty*11
    quote_mode=account['price_mode']=='quote';n=len(seq)
    assert len(orders)==len(trades)*2
    assert not len(orders) or np.all(orders[:,6]==qty)
    assert not len(orders) or np.all(orders[:,9]==fee)
    net=gross=0.;cash=0.;position=0;cursor=0
    curve=np.zeros(n);previous_exit=0;maxdelay=0.;late=0
    for k,trade in enumerate(trades):
        op,cl=orders[2*k:2*k+2];entry,exit=map(int,trade[[19,20]])
        decision=entry-1;out=exit-1;side=int(trade[2]);width=trade[10]
        assert seq[decision]==trade[18] and seq[entry]==trade[12] and seq[exit]==trade[13] and seq[out]==trade[14]
        assert trade[0]==stamp[entry] and trade[1]==stamp[exit] and trade[11]==stamp[out]
        assert entry<exit and stamp[entry]<limit-300 and stamp[exit]<limit+300
        assert side in (-1,1) and width>=2*tick and width/tick==round(width/tick)
        c=np.searchsorted(candidate[:,0],decision)
        np.testing.assert_array_equal(candidate[c],[decision,side,width])
        if k:assert stamp[decision]>=trades[k-1,1]+300 and entry>int(trades[k-1,20])
        source=quote['mid'] if not quote_mode else quote['ask'] if side>0 else quote['bid']
        liq=quote['mid'] if not quote_mode else quote['bid'] if side>0 else quote['ask']
        assert trade[4]==source[entry] and trade[5]==liq[exit]
        for row,action,idx,d,order_side in ((op,1,entry,decision,side),(cl,2,exit,out,-side)):
            np.testing.assert_array_equal(row[:7],[stamp[d],stamp[idx],seq[d],seq[idx],action,order_side,qty])
            assert row[12]==k and row[14]==width and row[13]==(side*qty if action==1 else 0)
            cash-=order_side*qty*row[7]*value+fee;position+=order_side*qty
            maxdelay=max(maxdelay,row[1]-row[0])
        amount=side*qty*(trade[5]-trade[4])*value
        np.testing.assert_allclose(trade[6:9],[amount,2*fee,amount-2*fee],atol=1e-6)
        np.testing.assert_allclose(op[7:12],[trade[4],0,fee,-fee,0],atol=1e-6)
        np.testing.assert_allclose(cl[7:12],[trade[5],amount,fee,amount-fee,trade[9]],atol=1e-6)
        assert position==0;gross+=amount;net+=amount-2*fee
        path=side*(liq[entry:exit+1]-trade[4])
        near(trade[15],max(0.,path.max())/width);near(trade[16],max(0.,-path.min())/width)
        near(trade[17],(stamp[exit]-stamp[entry])/60)
        # ----------------------------------------
        # 保存された返済理由を信用せず、入口後最初に成立する保護条件を計算する。
        before=path[:-1];best=np.maximum.accumulate(before)
        trail=(config['exit_id']=='X2')&(best>=width)
        stop=np.where(trail,best-width,-width)
        triggers=np.zeros(len(before),int)
        triggers[stamp[entry:exit]-stamp[entry]>=config['minutes']*60]=4
        if config['exit_id']=='X1':triggers[before>=np.ceil(1.5*width/tick-1e-10)*tick]=2
        stophit=before<=stop;triggers[stophit]=np.where(trail[stophit],3,1)
        triggers[stamp[entry:exit]>=limit-60]=5
        found=np.flatnonzero(triggers)
        assert len(found) and found[0]==len(before)-1 and triggers[-1]==trade[9]
        # ----------------------------------------
        # 累積実現＋当該玉含み−新規時費用で曲線を再構成する。
        balance=net-(amount-2*fee)
        curve[previous_exit:entry]=balance
        curve[entry:exit]=balance-fee+side*qty*(liq[entry:exit]-trade[4])*value
        previous_exit=exit
        late+=int(stamp[exit]>limit)
    curve[previous_exit:]=net
    near(cash,net)
    p=trades[:,8];win=p>0;lose=p<0
    expected=dict(gross_pnl=gross,fees=len(orders)*fee,net=net,profit=p[win].sum(),loss=-p[lose].sum(),
                  cycles=len(trades),wins=win.sum(),losses=lose.sum(),win_qty=trades[win,3].sum(),loss_qty=trades[lose,3].sum(),
                  flat_qty=trades[p==0,3].sum(),max_long_qty=qty if (trades[:,2]>0).any() else 0,
                  max_short_qty=qty if (trades[:,2]<0).any() else 0,
                  drawdown=np.max(np.maximum.accumulate(np.r_[0.,curve])[1:]-curve,initial=0),
                  equity_min=np.min(curve,initial=0),equity_max=np.max(curve,initial=0),
                  unrealized_start=0.,unrealized_end=0.,mtm_change=net)
    for key,val in expected.items():near(account[key],val)
    near(account['pf'],expected['profit']/expected['loss'] if expected['loss'] else None)
    win_mean=expected['profit']/expected['win_qty'] if expected['win_qty'] else None
    loss_mean=expected['loss']/expected['loss_qty'] if expected['loss_qty'] else None
    near(account['payoff'],win_mean/loss_mean if win_mean is not None and loss_mean else None)
    return dict(**expected,session=account['session'],late=late,maxdelay=maxdelay,orders=len(orders),trades=len(trades))


def summary_audit(summary: dict,accounts: list) -> None:
    """機能: 独立口座集計から全期間・週の金額、枚数、損小利大比、資産減少幅を照合する。

    引数: summary(dict)、accounts(list[dict])。返り値: なし(None)。
    """
    summed=('gross_pnl','fees','net','profit','loss','cycles','wins','losses','win_qty','loss_qty','flat_qty')
    expected={k:sum(a[k] for a in accounts) for k in summed}
    for k,v in expected.items():near(summary[k],v)
    near(summary['pf'],expected['profit']/expected['loss'] if expected['loss'] else None)
    w=expected['profit']/expected['win_qty'] if expected['win_qty'] else None
    l=expected['loss']/expected['loss_qty'] if expected['loss_qty'] else None
    near(summary['payoff'],w/l if w is not None and l else None)
    balance=peak=dd=0.
    for a in sorted(accounts,key=lambda x:x['session']):
        dd=max(dd,a['drawdown'],peak-balance-a['equity_min']);peak=max(peak,balance+a['equity_max']);balance+=a['net']
    near(summary['drawdown'],dd)
    near(summary['positive_sessions'],sum(a['net']>0 for a in accounts))
    near(summary['negative_sessions'],sum(a['net']<0 for a in accounts))


def main() -> None:
    """機能: 保存された全120条件・二方式・50口座を一括で検算し証跡を保存する。

    引数: なし。返り値: なし(None)。順位や条件は変更しない。
    """
    result=json.loads((MEDIUM/'売買結果.json').read_text(encoding='utf-8'))
    inputs=pickle.loads((WORK/'inputs.pkl').read_bytes());quotes=pickle.loads((WORK/'quotes.pkl').read_bytes())
    candidates=pickle.loads((MEDIUM/'入口候補.pkl').read_bytes())
    counts=orders=trades=summaries=0;delay=0.;late=0
    for mi,method in enumerate(result['methods']):
        cfg=method['config'];audited=[]
        for account in method['accounts']:
            key=(account['session'],account['symbol'])
            found=candidates[key][cfg['setting_id']][cfg['width_id']][cfg['family']]
            checked=account_audit(account,inputs[key],quotes[key],found,cfg)
            checked.update(symbol=key[1],price_mode=account['price_mode'])
            audited.append(checked);counts+=1;orders+=checked['orders'];trades+=checked['trades'];late+=checked['late'];delay=max(delay,checked['maxdelay'])
        for mode in ('quote','mid'):
            for symbol in ('TOPIX','NK225'):
                selected=[a for a in audited if a['symbol']==symbol and a['price_mode']==mode]
                summary_audit(method['summary' if mode=='quote' else 'mid_summary'][symbol],selected);summaries+=1
                for week,summary in method['weeks' if mode=='quote' else 'mid_weeks'][symbol].items():
                    members=[]
                    for a in selected:
                        day=date.fromisoformat(a['session'][:10]);label=(day-timedelta(days=day.weekday())).isoformat()
                        if label==week:members.append(a)
                    summary_audit(summary,members);summaries+=1
        if (mi+1)%20==0:print(json.dumps({'検算済条件':mi+1,'口座':counts},ensure_ascii=False),flush=True)
    evidence=dict(合格=True,条件=len(result['methods']),口座=counts,注文=orders,返済=trades,全期間週集計=summaries,
                  原本全行時価再計算=True,全取引最初の出口条件照合=True,判断後約定最大秒=delay,任意運用期限後返済数=late,
                  参照データ='保存済み25場、気配主と中値参考を別々に検算',
                  結果SHA256=hashlib.sha256((MEDIUM/'売買結果.json').read_bytes()).hexdigest())
    (HERE/'中期全口座の独立監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
