"""公開後の単発入口を共通の1枚OCOで比較する。"""

from __future__ import annotations

import numpy as np
from numba import njit

TRADE_COLUMNS = ['entry_row','exit_row','direction','entry_price','exit_price','risk_points',
    'pnl_points','exit_reason','entry_decision_row','exit_decision_row']
ORDER_COLUMNS = ['row','source_row','direction','quantity','price','reason','opening']


@njit(cache=True)
def simulate(times, prices, atr, pulses, limit, close_time, tick, delay, observed, require_flat):
    """機能: 次行かつ伝達時間後の注文を、1枚の全口座として再生する。

    引数: times/prices/atr/pulses (ndarray)、時刻/呼値/遅延 (float)、observed/require_flat (bool)。
    返り値: 全取引、全注文、全行口座、統計 (tuple[ndarray, ndarray, ndarray, ndarray])。
    OCOは新規約定後に予約し、未成熟な返済条件を先に使わない。
    """
    n = len(times)
    trades = np.empty((n,10)); orders = np.empty((2*n,7)); curve = np.zeros((n,4))
    tc = oc = 0
    d = 0; pending = 0; source = -1; entered = -1; entry_source = -1
    exit_source = -1; force_reason = 0
    entry = risk = cash = realized = 0.
    last_exit = -np.inf; maximum = drawdown = 0.
    candidates = accepted = cancelled = 0
    for i in range(n):
        t,p = times[i], prices[i]
        acted = False
        fill = p; reason = 0; reason_source = -1
        if t >= close_time and (d != 0 or pending != 0):
            raise ValueError('真の場末に残玉又は新規予約があります')
        # ----------------------------------------
        # 成熟したOCOは、未成熟の時間返済予約があっても有効なままにする。
        if d != 0:
            if i > entered and t >= times[entered]+delay:
                stop = entry-d*risk; target = entry+d*2*risk
                if d*(p-stop) <= 0:
                    fill = p if observed else stop
                    reason = 1; reason_source = entered
                elif d*(p-target) >= 0:
                    fill = p if observed else target
                    reason = 2; reason_source = entered
            if reason == 0 and exit_source >= 0 and i > exit_source and t >= times[exit_source]+delay:
                fill = p; reason = force_reason; reason_source = exit_source
            if reason != 0:
                pnl = d*(fill-entry)
                cash += d*fill; realized += pnl
                orders[oc] = np.array([i,reason_source,-d,1.,fill,reason,0.]); oc += 1
                trades[tc] = np.array([entered,i,d,entry,fill,risk,pnl,reason,entry_source,reason_source]); tc += 1
                d = 0; exit_source = -1; force_reason = 0; last_exit = t; acted = True
        # ----------------------------------------
        # 新規予約は場末で取り消す。それ以外は最初の判断を約定まで保持する。
        if pending != 0 and t >= limit:
            pending = 0; cancelled += 1
        if not acted and d == 0 and pending != 0 and i > source and t >= times[source]+delay:
            d = pending; pending = 0; entry = p; entered = i; entry_source = source
            risk = np.ceil(max(atr[source],2*tick)/tick)*tick
            cash -= d*p
            orders[oc] = np.array([i,source,d,1.,p,0.,1.]); oc += 1
            acted = True
        if d != 0 and exit_source < 0:
            if t >= limit:
                exit_source = i; force_reason = 4
            elif t >= times[entered]+1800:
                exit_source = i; force_reason = 3
        # ----------------------------------------
        # 入口パルスは待ち行列へ蓄積しない。保有中・休止中のものは消費して終える。
        if pulses[i] != 0:
            candidates += 1
            if not acted and d == 0 and pending == 0 and t < limit-300 and t >= last_exit+300:
                if np.isfinite(atr[i]) and atr[i] > 0:
                    pending = int(pulses[i]); source = i; accepted += 1
        equity = cash+d*p
        maximum = max(maximum,equity); drawdown = max(drawdown,maximum-equity)
        curve[i] = np.array([realized,equity,d,maximum-equity])
    if require_flat and (d != 0 or pending != 0):
        raise ValueError('保存末尾で返済又は予約取消が完了していません')
    return trades[:tc],orders[:oc],curve,np.array([realized,drawdown,candidates,accepted,cancelled,d,pending])


def run(ready: dict, pulses: np.ndarray, delay: float = 0., observed: bool = False, require_flat: bool = True) -> dict:
    """機能: 共通の呼値・注文遅延を検査して1枚売買を再生する。

    引数: ready (dict)、pulses (ndarray[int8])、delay (float)、observed/require_flat (bool)。
    返り値: trades/orders/curve/stats (dict[str, ndarray])。価格×1枚の損益。
    """
    required = ('seq','time_s','last','atr')
    if any(not isinstance(ready[k],np.ndarray) or ready[k].ndim != 1 for k in required):
        raise ValueError('原本の行番号・時刻・価格・ATRは1次元配列が必要です')
    n = len(ready['seq'])
    if n == 0 or any(len(ready[k]) != n for k in required):
        raise ValueError('原本の全列は同じ非ゼロ行数が必要です')
    if not np.issubdtype(ready['seq'].dtype,np.integer):
        raise ValueError('原本行番号は整数が必要です')
    if not np.isfinite(ready['time_s']).all():
        raise ValueError('原本時刻は有限値が必要です')
    if not np.isfinite(ready['tick']) or ready['tick'] <= 0:
        raise ValueError('呼値は有限の正数が必要です')
    close_time = ready.get('session_close',ready['limit']+600.)
    if not np.isfinite(ready['limit']) or not np.isfinite(close_time) or ready['limit'] >= close_time:
        raise ValueError('安全返済判断は有限の真の場末より前である必要があります')
    if not isinstance(pulses,np.ndarray):
        raise ValueError('入口パルスは原本行に対応する配列が必要です')
    assert pulses.shape == (n,) and pulses.dtype == np.int8 and np.isin(pulses,[-1,0,1]).all()
    assert not isinstance(delay,(bool,np.bool_)) and delay in (0.,1.,5.,15.)
    assert isinstance(observed,(bool,np.bool_)) and isinstance(require_flat,(bool,np.bool_))
    assert np.all(np.diff(ready['time_s']) >= 0) and np.all(np.diff(ready['seq']) > 0)
    assert np.isfinite(ready['last']).all() and (ready['last'] > 0).all()
    values = simulate(ready['time_s'], ready['last'], ready['atr'], pulses,
        ready['limit'],ready.get('session_close',ready['limit']+600.),ready['tick'],delay,observed,require_flat)
    return dict(zip(('trades','orders','curve','stats'),values))
