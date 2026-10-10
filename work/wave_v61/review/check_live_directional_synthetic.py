"""取得を行わず、未決済の初回玉・追加玉を含む境界会計を検査する。"""

import os
os.environ['NUMBA_DISABLE_JIT']='1'
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
sys.path.insert(0,str(WORK/'directional'))
spec=importlib.util.spec_from_file_location('現在方向性接続',WORK/'live/directional_replay.py')
live=importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


def main() -> None:
    """機能: 同時計別原本行・4ロット途中・終了後の全費用と含みを独立計算する。

    引数: なし。返り値: なし(None)。API・保存実市場を読み取らない。
    """
    count=0
    for symbol,value,cap in [('TOPIX',1000.,10),('NK225',10.,20)]:
        for side in (1,-1):
            for quote in (True,False):
                mid=1000+side*(np.array([1000,1000,1000,1012,1022,1032,1042,1042,1030]+[1030]*22)-1000)
                times=np.arange(len(mid),dtype=float)*60;times[5]=times[4]
                seq=np.arange(len(mid),dtype=np.int64)*5
                ready=dict(seq=seq,time_s=times,start=0.,limit=1560.,tick=1.,symbol=symbol,session='人工_Day')
                quotes=dict(seq=seq,time_s=times,mid=mid,bid=mid-.5,ask=mid+.5)
                candidates=np.array([[1.,side,10.]])
                config=dict(fraction=.01,minutes=60,initial_fraction=.5,pyramid=True,cooldown_minutes=0)
                result=live.engine.execute(ready,quotes,candidates,config,quote)
                assert result['additions']==3
                orders=result['orders']
                for size in range(len(mid)+1):
                    state=live.state_at(ready,quotes,orders,size,quote)
                    chosen=orders[orders[:,3]<=seq[size-1]] if size else orders[:0]
                    cash=float((-chosen[:,5]*chosen[:,6]*chosen[:,7]*value-chosen[:,9]).sum())
                    quantity=float((chosen[:,5]*chosen[:,6]).sum())
                    mark=(quotes['bid' if quantity>=0 else 'ask'][size-1] if quote else mid[size-1]) if size else 0
                    expected=cash+quantity*mark*value
                    assert abs(state['net']-expected)<1e-6
                    assert state['long_qty']-state['short_qty']==quantity
                    assert state['fees']==chosen[:,9].sum()
                    if size==7:
                        assert len(state['open_positions'])==4 and abs(quantity)==cap
                        assert abs(sum(p['entry_fee'] for p in state['open_positions'])-state['open_entry_fees'])<1e-8
                    count+=1
    result=dict(合格=True,途中境界検査=count,四ロット未決済と費用=True,同時計行分割=True,
                現在API取得=0,実市場再生=False)
    (HERE/'方向性途中会計の独立合成監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
