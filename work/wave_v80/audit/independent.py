"""遅延売買の原本気配と注文だけから、会計と到達時計を再構成する。"""

from __future__ import annotations

from collections import Counter
import hashlib
import math

import numpy as np


def assert_near(actual, expected, label: str) -> None:
    """機能: 円と価格の丸め誤差だけを許容して照合する。

    引数: actual/expected(数値又は配列)、label(str)。返り値: なし(None)。
    """
    np.testing.assert_allclose(actual,expected,atol=1e-5,rtol=0,err_msg=label)


def fee(symbol: str, quantity: int) -> int:
    """機能: 注文合計の税込片道料金を整数演算で求める。

    引数: symbol(str)、quantity(int)。返り値: 切捨て後料金(int)。
    """
    return quantity*418//10 if symbol=='TOPIX' else quantity*11


def ratios(row: dict) -> dict:
    """機能: 個別商品内の金額比・平均勝敗・時間を独立の分母で計算する。

    引数: row(dict)。返り値: 比率を追加した会計(dict)。
    """
    p,l,n,w,b=row['profit'],row['loss'],row['trades'],row['wins'],row['losses']
    row.update(profit_share=p/(p+l) if p+l else None,profit_loss_ratio=p/l if l else None,
        win_rate=w/n if n else None,average_win=p/w if w else None,average_loss=l/b if b else None,
        payoff=(p/w)/(l/b) if w and b and l else None,average_net=row['net']/n if n else None,
        average_hold_seconds=row['hold_seconds']/n if n else None)
    return row


def account(key: tuple, args: tuple, ledger: dict) -> tuple:
    """機能: 全注文の時計と売買側を検証し、独立建玉台帳・全行時価を求める。

    引数: key(tuple)、args(tuple)、ledger(dict)。返り値: 会計・時価曲線(tuple)。
    約定順位の仮定を検証するもので、実取引所の約定可能性は証明しない。
    """
    times,bid,ask=args[:3];symbol=key[1];n=len(times)
    qty,value,latency=int(args[15]),float(args[16]),float(args[18]);tick=float(args[12]);mode=int(args[19])
    expected_qty=10 if symbol=='TOPIX' else 20
    assert qty==expected_qty and value==(1000. if symbol=='TOPIX' else 10.)
    orders=ledger['orders'];stored=ledger['trades'];events=ledger['events'];stats=ledger['stats']
    assert orders.shape[1]==18 and stored.shape[1]==12 and events.shape[1]==9
    valid=np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>=bid)
    valid_rows=np.flatnonzero(valid)
    last_valid=np.maximum.accumulate(np.where(valid,np.arange(n),-1))
    bid_known=np.r_[0.,bid][last_valid+1];ask_known=np.r_[0.,ask][last_valid+1]
    change_cash=np.zeros(n);change_qty=np.zeros(n,dtype=int)
    rebuilt=[];position=None;last_fill=-1;maxlong=maxshort=0;spread=lag=0.;missing=stale=gapfills=0
    fees=0;reasons=Counter();waits=[]
    for o in orders:
        row,source,cid,side,q=int(o[0]),int(o[1]),int(o[2]),int(o[3]),int(o[4])
        price=float(o[5]);reason=int(o[6]);opened=bool(o[7]);charge=fee(symbol,q)
        assert 0<=source<row<n and row>=last_fill
        assert side in (-1,1) and q==qty and valid[row]
        assert o[8]==charge and o[12]==times[row] and o[13]==row
        assert times[source]<=o[10] and abs(o[11]-(o[10]+latency))<1e-8
        assert times[row]>=o[11]
        eligible=valid_rows[(valid_rows>source)&(times[valid_rows]>=o[11])]
        assert len(eligible)>0
        if opened and mode==2:
            limit=bid[source] if side==1 else ask[source]
            cancel_due=min(o[11]+15.,args[14]-90.)+latency
            eligible=eligible[times[eligible]<cancel_due]
            quotes=ask[eligible] if side==1 else bid[eligible]
            eligible=eligible[side*(quotes-limit)<=-tick+1e-8]
            assert len(eligible)>0 and row==eligible[0]
            assert_near(price,limit,'待機指値の価格')
        else:
            assert row==eligible[0],('最初の到達後有効行',key,o,eligible[:3])
            assert_near(price,ask[row] if side==1 else bid[row],'成行売買側')
            if opened and mode==1:
                limit=ask[source]+tick if side==1 else bid[source]-tick
                assert side*(price-limit)<=1e-8
        if opened:
            assert position is None and reason==10 and o[14]==mode
            g=int(np.searchsorted(args[6],o[15]))
            assert g<len(args[6]) and args[6][g]==o[15]
            assert args[7][g]==side and args[8][g]==o[16] and args[9][g]==o[17]
            assert args[3][source] and not args[4][source]
            assert times[source]-args[6][g]<=2.+1e-8
            assert args[13]+60.<=o[10]<args[14]-120.
            position=(cid,row,side,q,price,charge)
            maxlong=max(maxlong,q if side==1 else 0);maxshort=max(maxshort,q if side==-1 else 0)
        else:
            assert position is not None
            oldcid,entryrow,d,held,entry,entryfee=position
            assert cid==oldcid and side==-d and q==held
            gross=d*(price-entry)*q*value;net=gross-entryfee-charge
            rebuilt.append([cid,entryrow,row,d,q,entry,price,entryfee,charge,gross,net,0.])
            reasons[str(reason)]+=1;position=None
        fees+=charge;last_fill=row;waits.append(float(o[12]-o[10]))
        change_cash[row]+=-side*q*price*value-charge
        change_qty[row]+=side*q
        spread+=side*(price-(bid[row]+ask[row])/2.)*q*value
        previous=int(last_valid[source])
        if previous<0:
            missing+=1
        else:
            stale+=int(previous!=source)
            previous_quote=ask[previous] if side==1 else bid[previous]
            lag+=side*(price-previous_quote)*q*value
        if (not opened or mode!=2) and times[row]-o[11]>5.:gapfills+=1
    details=np.asarray(rebuilt,dtype=float).reshape((-1,12))
    assert_near(details,stored,'決済明細')
    assert position is None and np.all(stats[:4]==0)
    assert stats[4]==maxlong and stats[5]==maxshort and stats[7]==len(details) and stats[8]==gapfills
    assert max(maxlong,maxshort)<=qty
    held=np.cumsum(change_qty);cash=np.cumsum(change_cash)
    curve=cash+held*np.where(held>=0,bid_known,ask_known)*value-np.where(held!=0,fee(symbol,qty),0.)
    assert np.all(np.abs(held)<=qty) and held[-1]==0
    if 'curve_hash' in ledger:
        assert hashlib.sha256(curve.tobytes()).hexdigest()==ledger['curve_hash'],'全行清算時価の指紋'
    if 'curve' in ledger:assert_near(curve,ledger['curve'],'全行清算時価')
    nets=details[:,10];grosses=details[:,9]
    positive=[float(v) for v in nets if v>0];negative=[-float(v) for v in nets if v<0]
    peaks=np.maximum.accumulate(np.r_[0.,curve])
    drawdown=float(np.max(peaks[1:]-curve))
    hold=sum(float(times[int(t[2])]-times[int(t[1])]) for t in details)
    cancellation=int(np.sum(np.isin(events[:,2],[21,23])))
    assert stats[6]==cancellation
    row=dict(session=key[0],symbol=symbol,profit=sum(positive),loss=sum(negative),net=sum(positive)-sum(negative),
        gross=float(sum(grosses)),fees=fees,trades=len(details),wins=len(positive),losses=len(negative),flats=int(np.sum(nets==0)),
        winning_lots=len(positive)*qty,losing_lots=len(negative)*qty,hold_seconds=hold,
        spread_drag=spread,decision_to_fill_cost=lag,max_trade_loss=max(negative,default=0.),
        drawdown=drawdown,curve_min=min(0.,float(curve.min())),curve_max=max(0.,float(curve.max())),
        max_long=maxlong,max_short=maxshort,cancellations=cancellation,delayed_gap_fills=gapfills,reasons=dict(reasons),
        entry_requests=int(np.sum(events[:,2]==20)),pauses=int(np.sum(events[:,2]==30)),
        decision_quote_missing=missing,decision_quote_last_valid=stale,average_order_wait=sum(waits)/len(waits) if waits else None)
    assert_near(curve[-1],row['net'],'最終時価と確定収支')
    assert_near(row['net'],row['gross']-row['fees'],'総損益と手数料')
    return ratios(row),curve


def compare(actual: dict, expected: dict) -> int:
    """機能: 保存会計の全項目を独立再計算と比較する。

    引数: actual/expected(dict)。返り値: 照合した項目数(int)。
    """
    assert set(actual)==set(expected),(set(actual)-set(expected),set(expected)-set(actual))
    count=0
    for key,value in expected.items():
        if isinstance(value,dict):
            count+=compare(actual[key],value)
        elif isinstance(value,(int,float)):
            assert_near(actual[key],value,key)
        else:
            assert actual[key]==value,(key,actual[key],value)
        count+=1
    return count


def aggregate(rows: list, symbol: str, sessions: list) -> dict:
    """機能: 商品別の期間比率と残高曲線を独立に合算する。

    引数: rows(list)、symbol(str)、sessions(list)。返り値: 期間会計(dict)。
    """
    by_session={r['session']:r for r in rows if r['symbol']==symbol}
    selected=[by_session[s] for s in sessions if s in by_session]
    totals=('profit','loss','net','gross','fees','trades','wins','losses','flats','winning_lots','losing_lots','hold_seconds',
        'spread_drag','decision_to_fill_cost','cancellations','delayed_gap_fills','entry_requests','pauses','decision_quote_missing','decision_quote_last_valid')
    out={k:sum(row[k] for row in selected) for k in totals}
    for k in ('max_trade_loss','max_long','max_short'):
        out[k]=max((row[k] for row in selected),default=0.)
    out.update(sessions=len(selected),active_sessions=sum(r['trades']>0 for r in selected),
        winning_sessions=sum(r['net']>0 for r in selected),losing_sessions=sum(r['net']<0 for r in selected),
        no_trade_sessions=sum(r['trades']==0 for r in selected),worst_session=min((r['net'] for r in selected),default=0.),
        without_best_session=out['net']-max((r['net'] for r in selected),default=0.))
    balance=high=dd=0.
    for row in selected:
        dd=max(dd,row['drawdown'],high-(balance+row['curve_min']))
        high=max(high,balance+row['curve_max']);balance+=row['net']
    out['drawdown']=dd
    return ratios(out)
