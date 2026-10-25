"""P04の保存済み全親を入口状態と価格移動・気配差・手数料へ分解する。"""

import json
import pickle
from pathlib import Path
import numpy as np
import run142

HERE, ROOT, prior = run142.HERE, run142.ROOT, run142.prior


def summarize(rows):
    """
    機能: 保存親会計と値動き・保有時間を加算し、比較可能な統計にする。
    引数: rows(list[dict])は親別証跡。
    返り値: dictは収支と母数。中値・判断中値は費用分解の代理であり実売買成績ではない。
    """
    if not rows:
        return dict(parents=0)
    keys = ('net','gross','fees','mid_gross','spread_drag','decision_mid_gross','next_row_mid_drag')
    return dict(parents=len(rows),wins=sum(r['net']>0 for r in rows),losses=sum(r['net']<0 for r in rows),
        sessions=len({r['session'] for r in rows}),**{k:float(sum(r[k] for r in rows)) for k in keys},
        avg_held_minutes=float(np.mean([r['held_seconds']/60. for r in rows])),
        avg_signed_mid_points=float(np.mean([r['signed_mid_points'] for r in rows])),
        avg_signed_fill_points=float(np.mean([r['signed_fill_points'] for r in rows])),
        median_signed_mid_points=float(np.median([r['signed_mid_points'] for r in rows])))


def main():
    """
    機能: 原行と保存trace・約定だけを読み、全50場のP04を新規保存する。
    引数: なし。
    返り値: None。金融エンジンを呼ばず、売買方向・時刻・枚数・出口を変更しない。
    """
    packets,_,_=run142.first.material()
    records=[]
    for item in packets:
        scene=item['session'];packet=pickle.loads((ROOT/item['path']).read_bytes())
        for symbol in ('NK225','TOPIX'):
            ready=packet['inputs'][scene,symbol];quote=packet['quotes'][scene,symbol]
            t=ready['time_s'];mid=(quote['bid']+quote['ask'])*.5
            mult=100. if symbol=='NK225' else 1000.
            with np.load(HERE/'round2/measurement'/f'{symbol}_{scene}.npz') as z:o=z['P04']
            with np.load(HERE/'round2/traces'/f'{symbol}_{scene}.npz') as z:trace=z['P04']
            entry_trace={int(x[5]):x for x in trace if int(x[1])==1}
            for parent in np.unique(o[:,2]):
                orders=o[o[:,2]==parent]
                assert len(orders)==2 and orders[0,7]==1 and orders[1,7]==0
                first,last=orders
                begin,end,decision=int(first[0]),int(last[0]),int(first[1])
                q,side=int(first[4]),int(first[3])
                trigger=entry_trace[int(parent)]
                assert int(trigger[0])==decision and int(trigger[2])==side
                fees=float(orders[:,9].sum())
                gross=float(np.sum(-orders[:,3]*orders[:,4]*orders[:,5]*mult))
                mid_gross=float(np.sum(-orders[:,3]*orders[:,4]*mid[orders[:,0].astype(int)]*mult))
                decision_mid=float(np.sum(-orders[:,3]*orders[:,4]*mid[orders[:,1].astype(int)]*mult))
                spread=float(np.sum(orders[:,4]*(quote['ask'][orders[:,0].astype(int)]-quote['bid'][orders[:,0].astype(int)])*.5*mult))
                assert abs(gross-(mid_gross-spread))<1.e-6
                records.append(dict(session=scene,kind=scene.split('_')[1],symbol=symbol,parent=int(parent),
                    regime=int(trigger[3]),side=side,quantity=q,risk=float(trigger[7]),
                    decision_row=decision,decision_seq=int(ready['seq'][decision]),entry_row=begin,exit_row=end,
                    entry_time=float(t[begin]),exit_time=float(t[end]),entry_price=float(first[5]),exit_price=float(last[5]),
                    exit_reason=int(last[6]),held_seconds=float(t[end]-t[begin]),
                    signed_mid_points=float(side*(mid[end]-mid[begin])),signed_fill_points=float(side*(last[5]-first[5])),
                    gross=gross,fees=fees,net=gross-fees,mid_gross=mid_gross,spread_drag=spread,
                    decision_mid_gross=decision_mid,next_row_mid_drag=decision_mid-mid_gross))
    groups=[]
    for symbol in ('NK225','TOPIX'):
        for kind in ('all','Day','Night'):
            for regime in (0,1,2,3):
                chosen=[r for r in records if r['symbol']==symbol and (kind=='all' or r['kind']==kind)
                        and (regime==0 or r['regime']==regime)]
                result=dict(symbol=symbol,kind=kind,regime=regime,**summarize(chosen))
                groups.append(result)
                if kind=='all':print(result,flush=True)
    per_scene=[]
    for symbol in ('NK225','TOPIX'):
        for scene in sorted({r['session'] for r in records}):
            chosen=[r for r in records if r['symbol']==symbol and r['session']==scene]
            per_scene.append(dict(symbol=symbol,session=scene,**summarize(chosen)))
    value=dict(financial_replays=0,API=0,records=records,groups=groups,sessions=per_scene,
        definitions={'mid_gross':'保存済み同じ約定時刻・方向・枚数の中値代理会計。実行可能な戦略の収益ではない。',
            'spread_drag':'保存各約定の半気配差×枚数×倍率の合計。中値代理と実grossとの差。',
            'next_row_mid_drag':'判断原行中値代理から次正常約定原行中値代理への差。符号が負なら有利。'})
    content=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)
    with (HERE/'P04全親の状態別と気配差分解142.json').open('x',encoding='utf8') as f:f.write(content)


if __name__=='__main__':main()
