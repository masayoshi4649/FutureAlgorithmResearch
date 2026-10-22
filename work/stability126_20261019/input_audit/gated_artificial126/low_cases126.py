"""一リスク未満の利益床について、開始閾値と次原行悪化を独立に確認する。"""

from copy import deepcopy
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'bbo_artificial126'))
import check_bbo126 as test


def ramp(quantity: int) -> tuple:
    """
    機能: 0.25R・0.5R・0.75Rへ別行で進み、1Rには届かない合成経路を作る。
    引数: quantity(int)は5又は10。
    返り値: tupleはready/quotes/market/paperの固定人工値。
    """
    bids=[100,100,100,102,103,104,103,102,101,100,100,100,100,100,100]
    value=test.fixture(bids,[(0,1,13,1)],quantity)
    value[2][:]=test.market_known(value[0],value[2]);value[2][:,4:8]=[-.2,-.3,-.2,-.3]
    return value


def verify(configs: dict[float,dict]) -> dict:
    """
    機能: 実際の固定catalogから選んだ四閾値を、独立期待値へ照合する。
    引数: configs(dict[float,dict])は0.25/0.5/0.75/1.0Rの設定。
    返り値: dictは開始行・次正常行約定・上下対称の検査記録。
    """
    assert set(configs)=={.25,.5,.75,1.}
    start=len(test.CHECKS);cases=[]
    for quantity in (5,10):
        base=ramp(quantity)
        for side in (1,-1):
            value=base if side>0 else test.mirror(base)
            for threshold,config in configs.items():
                assert config['protect_start_atr']==threshold
                result=test.run(value,config);events=result['execution_events'];floors=events[events[:,1]==12.]
                if threshold<1.:
                    expected={.25:3.,.5:4.,.75:5.}[threshold]
                    test.check('低Rの開始は閾値別の既知行_'+str((quantity,side,threshold)),len(floors)>0 and floors[0,0]==expected)
                    test.check('低R床の返済も次正常原行_'+str((quantity,side,threshold)),result['orders'][-1,0]==8. and result['orders'][-1,1]==7.)
                    test.check('床価格での約定を保証しない_'+str((quantity,side,threshold)),result['stats'][0]==0.)
                else:
                    test.check('元1Rはこの含み益で不発_'+str((quantity,side)),len(floors)==0 and result['orders'][-1,0]==14.)
                cases.append(dict(quantity=quantity,side=side,threshold=threshold,first_floor=float(floors[0,0]) if len(floors) else None,
                                  actual_exit=float(result['orders'][-1,0]),net=float(result['stats'][0])))
            delayed=deepcopy(value);delayed[1]['quote_valid'][8:10]=False
            result=test.run(delayed,configs[.25])
            test.check('正常気配待ちの低R床返済_'+str((quantity,side)),result['orders'][-1,0]==10. and result['orders'][-1,6]==70.)
            test.check('床待機中の悪化を隠さない_'+str((quantity,side)),result['stats'][0]==-quantity)
    return dict(passed=True,checks=test.CHECKS[start:],cases=cases)
