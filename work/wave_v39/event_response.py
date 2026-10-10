"""公開後の未来価格を評価用にだけ測り、入口生成へ返さない。"""

import numpy as np


def measure(ready: dict,pulse: np.ndarray) -> dict:
    """機能: 候補の次原本行価格から5/15分先の反応を別集計する。

    引数: ready (dict)、pulse (ndarray[int8])。返り値: 時間別の反応評価 (dict)。
    未来ラベルは評価専用。保有・休止による実際の取引採否を条件にしない。
    """
    n=len(pulse);t=ready['time_s'];p=ready['last'];output={}
    for minutes in (5,15):
        rows=[]
        for decision in np.flatnonzero(pulse):
            entered=int(decision)+1
            if entered>=n or not np.isfinite(ready['atr'][decision]) or ready['atr'][decision]<=0:continue
            future=int(np.searchsorted(t,t[entered]+minutes*60,side='left'))
            if future>=n or t[future]>=ready.get('session_close',ready['limit']+600.):continue
            direction=int(pulse[decision]);move=direction*(p[future]-p[entered])/ready['atr'][decision]
            rows.append([int(decision),entered,future,direction,float(move)])
        move=np.asarray([r[4] for r in rows],float)
        output[str(minutes)]=dict(件数=len(rows),正方向数=int((move>0).sum()),逆方向数=int((move<0).sum()),
            同値数=int((move==0).sum()),平均ATR反応=float(move.mean()) if len(move) else None,
            中央値ATR反応=float(np.median(move)) if len(move) else None,明細=rows,
            解釈='候補の次行を起点とする評価用の重複窓。実際の遅延約定や独立標本数ではない。')
    return output
