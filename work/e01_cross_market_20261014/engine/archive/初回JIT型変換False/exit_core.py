"""因果的な清算高水準だけで保護線と初先着を検知する小さい走査部品。"""

import numpy as np
from numba import njit


@njit(cache=True)
def scan(liquidation, normal, start, arm, drawdown, floor, hard_loss, target):
    """
    機能: 正常な現在行までの清算高水準から保護線を単調更新し、最初の退出を返す。
    引数: liquidation(float配列)、normal(bool配列)、start(int)、各円閾値(float)。無設定はNaN。
    返り値: tuple[int,int,ndarray] は判断行、理由1損失/2利確/3保護、4列の途中判断。
    """
    count=len(liquidation);trace=np.zeros((count,4));trace[:,2]=np.nan
    peak=0.;line=np.nan;armed=False;decision=-1;reason=0
    for row in range(count):
        if row>=start and normal[row] and decision<0:
            value=liquidation[row];assert np.isfinite(value)
            peak=max(peak,value)
            if np.isfinite(hard_loss) and value<=-hard_loss:
                decision=row;reason=1
            elif np.isfinite(target) and value>=target:
                decision=row;reason=2
            else:
                if not armed and value>=arm:armed=True
                if armed:
                    proposed=max(floor,peak-drawdown)
                    line=proposed if not np.isfinite(line) else max(line,proposed)
                    if value<=line:decision=row;reason=3
        trace[row]=np.array([peak,float(armed),line,float(reason)])
    return decision,reason,trace
