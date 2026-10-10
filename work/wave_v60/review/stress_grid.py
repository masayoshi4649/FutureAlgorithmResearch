"""単調・急変経路を成績選抜に使わず在庫管理の性質として検査する。"""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'grid'))
import engine
import features


def main() -> None:
    """機能: 同じ人工経路を全5方式・三約定仮定に流し、在庫上限と予算超過を記録する。

    引数: なし。返り値: なし(None)。実相場の確率・有用性は推定しない。
    """
    results=[]
    base=np.arange(240,dtype=float)
    paths={'上昇のみ':10000.+base*5,'下落のみ':10000.-base*5,
           '反落から急回復':10000.-np.minimum(base,100)*5+np.maximum(base-100,0)*9,
           '下落の途中で大きく飛ぶ':10000.-base*3-(base>=100)*1000}
    for name,body in paths.items():
        mid=np.r_[body,body[-1],body[-1]];n=len(mid)
        times=np.r_[base*60,14500.,14501.]
        seq=np.arange(n,dtype=np.int64)
        ready=dict(time_s=times,seq=seq,start=0.,limit=14560.)
        quotes=dict(mid=mid,bid=mid-.5,ask=mid+.5)
        events=features.direction_events(ready,quotes)
        for family in range(5):
            for mode in range(3):
                out=engine.replay(times,seq,mid,quotes['bid'],quotes['ask'],np.zeros(n,np.int64),
                                  np.array([14560.]),events,2,family,5,1,mode,.001,10,1000.,1.,418)
                orders,trades,equity,_,risks=out[:5]
                assert max(risks[:,:2].max(initial=0),0)<=10 and not out[6][:,1].any()
                np.testing.assert_allclose(equity[-1],trades[:,18].sum(),atol=1e-5)
                results.append(dict(経路=name,方式=f'G{family}',約定=['気配','中値','待機指値'][mode],
                                    収支=float(equity[-1]),手数料=float(orders[:,13].sum()),
                                    最大買枚数=int(risks[:,0].max(initial=0)),最大売枚数=int(risks[:,1].max(initial=0)),
                                    最大負け玉含み=float(risks[:,4].min(initial=0)),
                                    最大資産減少=float((np.maximum.accumulate(np.r_[0,equity])[1:]-equity).max(initial=0)),
                                    週予算返済数=int(((orders[:,9]==2)&(orders[:,15]==4)).sum()),
                                    運用組保護返済数=int(((orders[:,9]==2)&(orders[:,15]==5)).sum())))
    record=dict(合格=True,人工経路=True,利益選抜不使用=True,実市場の期待利益を示さない=True,
                契約='人工TOPIX相当、5段各2枚、週初10000、間隔10、1pt=1000円、1枚片道41.8円',
                条件='方向材料も人工原本から過去5分足のみで生成、未来の経路名は売買器へ渡さない',
                結果=results,コードSHA256=hashlib.sha256((HERE.parent/'grid/engine.py').read_bytes()).hexdigest())
    (HERE/'人工相場での在庫機構検査.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'合格':True,'再生':len(results),'実市場成績ではない':True},ensure_ascii=False))


if __name__=='__main__':main()
