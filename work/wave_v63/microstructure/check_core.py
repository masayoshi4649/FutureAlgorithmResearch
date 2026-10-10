"""短期板売買器について原簿と各原本行の全含み会計を独立再構成する。"""

import json
from pathlib import Path

import numpy as np

from core import replay


HERE=Path(__file__).resolve().parent


def inspect(times: np.ndarray,bid: np.ndarray,ask: np.ndarray,orders: np.ndarray,trades: np.ndarray,equity: np.ndarray,value: float,qty: int,fee_unit: float) -> None:
    """機能: 注文から現金と両側保有を再構成し、組・次行約定・全含みを照合する。

    引数: 時計・気配・注文・組・資産(ndarray)、value/fee_unit(float)、qty(int)。返り値: なし(None)。
    """
    cash=0.
    position=0
    pointer=0
    for i in range(len(times)):
        while pointer<len(orders) and int(orders[pointer,1])==i:
            d,fill,kind,side,quantity,price,fee,gross,net=orders[pointer]
            assert fill==d+1
            assert price==(ask[i] if side>0 else bid[i])
            assert fee==int(qty*fee_unit+1e-9)
            cash-=side*quantity*price*value+fee
            position+=int(side*quantity)
            assert abs(position)<=qty
            pointer+=1
        mark=bid[i] if position>0 else ask[i]
        assert abs(cash+position*mark*value-equity[i])<1e-6
    assert pointer==len(orders)
    assert position==0
    assert abs(cash-trades[:,11].sum())<1e-6
    for t in trades:
        assert t[1]==t[0]+1 and t[3]==t[2]+1
        assert abs(t[10]-t[4]*(t[7]-t[6])*t[5]*value)<1e-6
        assert abs(t[11]-t[10]+t[8]+t[9])<1e-6


def main() -> None:
    """機能: 上下・横ばい・ギャップ・全flat・校正・保護の人工経路を確認する。

    引数: なし。返り値: なし(None)。実データ利益は参照しない。
    """
    cases=0
    prefix=0
    n=720
    times=np.arange(n,dtype=float)
    paths=[1000.+np.arange(n)*.25,1000.-np.arange(n)*.25,1000.+np.sin(np.arange(n)/7)*4,
        np.ones(n)*1000.,np.r_[np.full(160,1000.),np.full(n-160,1010.)]]
    tested_trades=0
    for path in paths:
        for direction in (1,-1):
            for protect in (0,1):
                for calibration in (0,1):
                    for value,qty,fee in ((1000.,5,41.8),(10.,10,11.)):
                        bid,ask=path-.5,path+.5
                        signal=np.zeros(n,dtype=np.int8)
                        signal[::4]=direction
                        result=replay(times,bid,ask,signal,1.,0.,660.,value,qty,fee,4,2,40.,0.,protect,calibration,4,5)
                        orders,trades,equity,counters=result
                        inspect(times,bid,ask,orders,trades,equity,value,qty,fee)
                        assert counters[0]==0
                        tested_trades+=len(trades)
                        for end in (150,201):
                            short=replay(times[:end],bid[:end],ask[:end],signal[:end],1.,0.,660.,value,qty,fee,4,2,40.,0.,protect,calibration,4,5)
                            np.testing.assert_array_equal(short[0],orders[orders[:,1]<end])
                            np.testing.assert_allclose(short[2],equity[:end],atol=1e-8)
                            prefix+=1
                        cases+=1
    assert tested_trades>100
    record=dict(合格=True,人工経路=cases,prefix比較=prefix,実際の人工決済組=tested_trades,注文現金全行含みと組損益一致=True)
    (HERE/'売買器の合成照合.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False))


if __name__=='__main__':
    main()
