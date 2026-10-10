"""損益を見る前に指値の待機、費用、将来改変、場末を人工経路で検査する。"""

import json
from pathlib import Path

import numpy as np

from engine import drive


def inspect(times: np.ndarray,bid: np.ndarray,ask: np.ndarray,result: tuple,mode: int) -> None:
    """機能: 注文から独立に現金と一組の費用を再構成する。

    引数: times/bid/ask(ndarray)、result(tuple)、mode(int)。返り値: なし(None)。
    """
    orders,groups,curve,position,_=result
    cash=0.
    inventory=0
    oi=0
    for i in range(len(times)):
        while oi<len(orders) and orders[oi,2]==i:
            r=orders[oi]
            side=int(r[6])
            qty=int(r[7])
            assert r[9]==qty*418//10
            cash-=side*qty*r[8]*1000+r[9]
            inventory+=side*qty
            assert abs(inventory)<=5
            if mode==0 or (mode in (1,2) and r[11]!=5 and r[5]==2):
                assert r[2]>r[1]
                assert r[8]==(ask[i] if side>0 else bid[i])
            if mode in (1,2) and r[5]==1:
                assert r[2]>r[1]
                assert (ask[i]<=r[8]-1 if side>0 else bid[i]>=r[8]+1)
            if mode==2 and r[5]==2 and r[11]==5:
                assert r[2]>r[1]
                assert (ask[i]<=r[8]-1 if side>0 else bid[i]>=r[8]+1)
            oi+=1
        liquid=(bid[i]+ask[i])/2 if mode==3 else (bid[i] if inventory>0 else ask[i])
        assert np.isclose(cash+inventory*liquid*1000,curve[i])
        assert np.sign(inventory)==position[i]
    assert inventory==0
    assert np.isclose(cash,groups[:,11].sum())
    assert len(orders)==2*len(groups)


def main() -> None:
    """機能: 五つの人工経路と鏡像・管理・執行別に会計と未来独立性を検査する。

    引数: なし。返り値: なし(None)。実データは読み込まない。
    """
    checked=0
    for sign in (-1,1):
        for path in (np.zeros(200),np.arange(200)*.2,-np.arange(200)*.2,
                     np.sin(np.arange(200)/6)*9,np.r_[np.zeros(50),np.ones(150)*20]):
            for mode in range(4):
                for protect,lock in ((0,0),(1,0),(1,1)):
                    times=np.arange(200)*10.
                    midpoint=100+sign*path
                    bid=midpoint-1
                    ask=midpoint+1
                    signal=np.zeros(200,np.int8)
                    signal[5::20]=sign
                    result=drive(times,bid,ask,signal,4.,1.,5,1000.,418,1990.,mode,protect,lock)
                    inspect(times,bid,ask,result,mode)
                    # ----------------------------------------
                    # 将来だけ大きく変えても、変更行より前の注文と資産は同一。
                    futurebid=bid.copy()
                    futureask=ask.copy()
                    futurebid[140:]+=20
                    futureask[140:]+=20
                    changed=drive(times,futurebid,futureask,signal,4.,1.,5,1000.,418,1990.,mode,protect,lock)
                    np.testing.assert_array_equal(result[0][result[0][:,2]<140],changed[0][changed[0][:,2]<140])
                    np.testing.assert_array_equal(result[2][:140],changed[2][:140])
                    checked+=1
    output=dict(合格=True,人工経路=checked,未来改変比較=checked,注文費用と全行時価='別式一致',実データ損益参照=False)
    (Path(__file__).parent/'合成監査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print(output)


if __name__=='__main__':
    main()
