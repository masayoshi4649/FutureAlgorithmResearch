"""取得前の在庫途中会計を、残玉・両建て・同時計境界で独立検査する。"""

import os
os.environ['NUMBA_DISABLE_JIT']='1'
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import check_inventory_independent as independent
spec=importlib.util.spec_from_file_location('在庫現在境界監査',HERE.parent/'live/inventory_replay.py')
live=importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


def main() -> None:
    """機能: 各境界より後の返済を含めず、現金・発生費用・残玉を別式で復元する。

    引数: なし。返り値: なし(None)。API又は保存市場の現在原本を使用しない。
    """
    checks=hedges=0
    paths=[([100,100,97,97,96.5,96.5,96.5,97,97,98,98,98],[[0,0,0,1],[4,-5,-3,1],[7,0,0,1]]),
           ([100,100,103,103,105,106,107,108,109,108,108,108],[[0,5,3,1]]),
           ([100,100,98,96,94,92,90,88,80,70,70,70],[[0,0,0,1]])]
    for prices,events in paths:
        for side in (1,-1):
            data=independent.fixture((100+side*(np.asarray(prices)-100)).tolist(),
                 [[e[0],e[1]*side,e[2]*side,e[3]] for e in events])
            data['times'][3]=data['times'][2]
            for family in range(5):
                for mode in range(3):
                    raw=independent.run(data,family,mode)
                    orders,trades=raw[:2]
                    for count in range(len(prices)+1):
                        state=live.snapshot(raw,count,data['times'],1000.)
                        selected=orders[orders[:,2]<count]
                        closed=trades[trades[:,8]<count]
                        cash=float((-selected[:,10]*selected[:,11]*selected[:,12]*1000-selected[:,13]).sum())
                        paid=sum(int(o[11])*418//10 for o in selected)
                        gross=float((closed[:,3]*closed[:,4]*(closed[:,14]-closed[:,13])*1000).sum())
                        ended=set(closed[:,5].astype(int));floating=0.;lqty=sqty=0
                        for order in selected:
                            if order[9]!=1 or int(order[0]) in ended:continue
                            s,q,p=order[10:13]
                            mark=data['mid'][count-1] if mode==1 else data['bid' if s>0 else 'ask'][count-1]
                            floating+=s*q*(mark-p)*1000
                            if s>0:lqty+=q
                            else:sqty+=q
                        expected=dict(cash=cash,fees=paid,gross_realized=gross,unrealized=floating,
                                      net=gross-paid+floating,long_qty=lqty,short_qty=sqty)
                        for key,value in expected.items():assert abs(state[key]-value)<1e-5,(family,mode,count,key)
                        checks+=1;hedges+=lqty>0 and sqty>0
    result=dict(合格=True,独立途中境界=checks,両建てを含む境界=int(hedges),同時計原本順維持=True,
                将来返済費用未計上=True,現在API取得=0,保存市場未使用=True)
    (HERE/'在庫途中会計の独立合成監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
