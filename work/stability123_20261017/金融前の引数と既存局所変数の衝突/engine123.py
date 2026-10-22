"""途中返済を停止し、通常の時刻返済と明示した引け代理精算を分ける。"""

from pathlib import Path
import sys
import numpy as np

import core123 as BASE

PROXY_COLUMNS=('uid','side','rung','entry_decision_row','entry_row','entry_time','entry_price',
    'reference_row','reference_time','exit_price','gross','fees','net','planned_exit_time',
    'reference_last','reference_bid','reference_ask')


def evaluate(quotes: dict,setting: dict,kind: str,initial: float,spacing: float) -> tuple:
    """
    機能: 同じ段階新規を保持し、途中返済なしの二つの終端を計算する。
    引数: quotes(dict[str,np.ndarray])は原行順の五気配列、setting(dict)は商品と時間、
        kind(str)はEARLY又はCLOSE_PROXY、initial/spacing(float)は初回距離と間隔pt。
    返り値: tupleは通常注文・通常完結玉・時価曲線・集計・代理玉・終了仮定。
        無限大追尾で全ての有限価格における利益返済を停止する。
        代理精算は通常の次原行約定へ混ぜず、予定時刻と参照時刻を両方残す。
    """
    assert kind in ('EARLY','CLOSE_PROXY')
    config=dict(setting)
    if kind=='CLOSE_PROXY':config['close_time']=float('inf')
    o,l,c,n=BASE.replay(quotes['row'],quotes['time'],quotes['last'],quotes['bid'],quotes['ask'],
        **config,unit=1.,initial=initial,mode=2,trail=float('inf'),spacing=spacing,reset_after_profit=False)
    summary=dict(zip(BASE.SUMMARY_COLUMNS,n.tolist()))
    proxy=np.empty((0,len(PROXY_COLUMNS)),float)
    context=dict(kind=kind,scheduled_time=setting['close_time'] if kind=='EARLY' else setting['session_end'],
        approximation=False,base_unclosed=int(summary['unclosed']))
    if kind=='EARLY':
        assert np.all(l[:,14]==9) and summary['unclosed']==0
        return o,l,c,summary,proxy,context

    # ----------------------------------------
    # 入口計算を終えた後だけ、予定引けまでに観測した最後の気配を取り出す。
    assert not len(l) and np.all(o[:,1]==1) and int(summary['entries'])==len(o)
    target=setting['session_end']
    assert len(c)>0
    raw=int(c[-1,0]);indices=np.flatnonzero(quotes['row']==raw)
    assert len(indices)==1
    index=int(indices[0]);reference_time=float(quotes['time'][index])
    context.update(reference_row=raw,reference_time=reference_time,age_seconds=target-reference_time,
        approximation=reference_time<target,reference_last=float(quotes['last'][index]),
        reference_bid=float(quotes['bid'][index]),reference_ask=float(quotes['ask'][index]))
    if not target-360<=reference_time<=target:
        context['measured']=False
        summary.update(net=None,cash=None,profit=None,loss=None,closed_lots=0,wins=0,losses=0)
        return o,l,c,summary,proxy,context
    context['measured']=True

    # ----------------------------------------
    # 代理価格で全UIDを一度ずつ終了会計する。実注文のfill原行は作らない。
    fee=float(np.floor(setting['fee']+1e-9));multiplier=setting['multiplier'];values=[]
    for entry in o:
        side=entry[2]
        price=quotes['bid'][index] if side==1 else quotes['ask'][index]
        gross=side*(price-entry[7])*multiplier
        values.append([entry[0],side,entry[10],entry[3],entry[4],entry[6],entry[7],
            raw,reference_time,price,gross,2*fee,gross-2*fee,target,
            quotes['last'][index],quotes['bid'][index],quotes['ask'][index]])
    proxy=np.asarray(values,dtype=float).reshape((-1,len(PROXY_COLUMNS)))
    net=float(proxy[:,12].sum())
    cash=float(summary['cash']+np.sum(proxy[:,10]-fee))
    assert net==cash==summary['net']
    summary.update(net=net,cash=cash,profit=float(np.maximum(proxy[:,12],0).sum()),
        loss=float(np.maximum(-proxy[:,12],0).sum()),fees=2*fee*len(proxy),closed_lots=len(proxy),
        wins=int(np.count_nonzero(proxy[:,12]>0)),losses=int(np.count_nonzero(proxy[:,12]<0)),
        unclosed=0,held_entry_fees=0,last_equity=net)
    context['last_price_reference_net']=float(sum(e[2]*(quotes['last'][index]-e[7])*multiplier-2*fee for e in o))
    context['terminal_event']=dict(scheduled_time=target,equity=net,cash=net,long=0,short=0,
        source='引け前六分以内BBOによる代理精算。実約定原行ではない。')
    return o,l,c,summary,proxy,context
