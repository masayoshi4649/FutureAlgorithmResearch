"""Q01の保存経路を玉ごとに診断する。新条件・新約定は生成しない。"""

import json
import pickle
from pathlib import Path
import numpy as np
from decompose_saved import clock, ROOT, HERE, OLD

REASON = {3:'初期100pt損切り',4:'赤字の方向反証',5:'利益後トレール',6:'米国前終了'}


def tickets_for(scene):
    """一場の保存約定を玉ごとに照合し順行・逆行の最大値を計算する。

    引数: scene(str)は保存夜間場ID。
    返り値: list[dict]は玉別の事後診断。未来極値を売買判断には渡さない。
    """
    with (OLD/'inputs'/f'{scene}.pkl').open('rb') as stream:
        packet = pickle.load(stream)
    data = packet['data']
    times, quotes = data['ready']['time_s'], data['quotes']
    bid, ask, good = quotes['bid'], quotes['ask'], quotes['quote_valid']
    midpoint = (bid+ask)/2
    with np.load(OLD/'round2/orders'/f'{scene}.npz') as stored:
        orders = stored['Q01'].copy()
    result=[]
    keys = dict.fromkeys((int(r[2]),int(r[8])) for r in orders)
    for parent,uid in keys:
        rows=orders[(orders[:,2]==parent)&(orders[:,8]==uid)]
        opening=rows[rows[:,7]==1]
        closing=rows[rows[:,7]==0]
        assert len(opening)==1 and len(closing)>0
        first,last=int(opening[0,0]),int(closing[-1,0])
        side,qty=int(opening[0,3]),int(opening[0,4])
        entry=float(opening[0,5])
        assert np.sum(closing[:,4])==qty
        path=np.arange(first,last+1)[good[first:last+1]]
        liquidation=(bid if side>0 else ask)[path]
        gains=side*(liquidation-entry)
        net=float(np.sum(side*(closing[:,5]-entry)*closing[:,4])*100)
        result.append(dict(session=scene,parent=parent,uid=uid,side='買い' if side>0 else '売り',qty=qty,
                           entry_time=clock(times[first]),exit_time=clock(times[last]),entry=entry,
                           exit_average=float(np.sum(closing[:,5]*closing[:,4])/qty),net=net,
                           mfe=float(np.max(gains)),mae=float(np.min(gains)),
                           mid_mfe=float(np.max(side*(midpoint[path]-midpoint[first]))),
                           entry_spread=float(ask[first]-bid[first]),
                           reason=REASON.get(int(closing[-1,6]),str(int(closing[-1,6])))))
    return result


def main():
    """全25夜と最悪3夜・最高益夜の保存経路の診断を出力する。

    引数: なし。
    返り値: None。既存の金融結果を変更しない。
    """
    decomposition=json.loads((HERE/'保存約定の中値と気配差分解.json').read_text(encoding='utf-8'))
    parents=[r for r in decomposition['parents'] if r['method']=='Q01']
    sessions=sorted(set(r['session'] for r in parents))
    amounts={s:sum(r['net'] for r in parents if r['session']==s) for s in sessions}
    details=[ticket for s in sessions for ticket in tickets_for(s)]
    assert sum(r['net'] for r in details)==sum(amounts.values())
    losses=[r for r in details if r['net']<0]
    worst=sorted(amounts,key=amounts.get)[:3]
    best=max(amounts,key=amounts.get)
    summary=dict(tickets=len(details),loss_tickets=len(losses),loss_mfe_nonpositive=sum(r['mfe']<=0 for r in losses),
                 loss_mfe_under40=sum(r['mfe']<40 for r in losses),loss_mfe_under100=sum(r['mfe']<100 for r in losses),
                 loss_mid_mfe_nonpositive=sum(r['mid_mfe']<=0 for r in losses),
                 by_reason={reason:dict(count=sum(r['reason']==reason for r in details),net=sum(r['net'] for r in details if r['reason']==reason)) for reason in REASON.values()},
                 worst=worst,best=best,session_net=amounts)
    (HERE/'Q01の玉別順行と損失.json').write_text(json.dumps(dict(summary=summary,tickets=details),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    lines=['# Q01の保存経路で何が起きたか','',
           '全25夜の米国開始前。日経mini上限10枚、手数料0円。保存約定の事後診断で、入口条件・返済条件は変更していない。',
           '',f"損失玉{len(losses)}玉のうち、返済可能な気配で一度も含み益が正にならなかった玉は{summary['loss_mfe_nonpositive']}玉、最大順行40pt未満は{summary['loss_mfe_under40']}玉。",
           '','最大順行は各玉の実保有区間内だけ。未来の最良時刻で利確できたと仮定した利益ではない。','']
    for scene in worst+[best]:
        selected=[r for r in details if r['session']==scene]
        lines += [f"## {scene} 前半収支 {amounts[scene]:+,.0f}円",'',
                  '|新規時刻|方向・枚数|新規価格|返済時刻|返済平均価格|収支円|最大順行pt|入口気配差pt|返済理由|',
                  '|---|---|---:|---|---:|---:|---:|---:|---|']
        for r in selected:
            lines.append(f"|{r['entry_time'][11:19]}|{r['side']}{r['qty']}|{r['entry']:,.0f}|{r['exit_time'][11:19]}|{r['exit_average']:,.0f}|{r['net']:+,.0f}|{r['mfe']:.0f}|{r['entry_spread']:.0f}|{r['reason']}|")
        lines.append('')
    (HERE/'Q01の具体的な損失と勝ち.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
