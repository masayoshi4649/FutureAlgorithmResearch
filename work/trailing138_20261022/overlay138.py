"""初回玉を維持し、追撃玉自身の順行後だけ利益追尾を加える。"""

import numpy as np
from numba import njit


@njit(cache=True)
def campaign(times, bid, ask, valid, atr, original, activation, width, tighten_at, tight_width, protect):
    """
    機能: 保存済みの因果的な入口を保持し、追撃の利益追尾だけを追加する。
    引数: times/bid/ask/valid/atr/original(ndarray)は原行と元注文。
          activation/width/tighten_at/tight_width(float)は初回判断時R単位。
          protect(int)は一度に保護する最大枚数。0なら追撃残数全部。
    返り値: ndarrayは約定行・判断行・親・方向・枚数・価格・理由・新規・脚・費用。
    """
    out = np.zeros((len(original)+4, 10)); count = 0; pointer = 0
    held = 0; virtual = 0; added_price = 0.; initial_added = 0
    risk = max(20., atr[int(original[0, 1])]); side = int(original[0, 3])
    parent = original[0, 2]; peak = -np.inf; floor = -np.inf
    active = False; done = False; pending = -1
    for i in range(int(original[0, 0]), int(original[-1, 0])+1):
        good = valid[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0 < bid[i] < ask[i]
        mark = bid[i] if side > 0 else ask[i]
        # ----------------------------------------
        # 発生済みの元通知だけ処理する。元親の返済を優先し、独自予約は取り消す。
        while pointer < len(original) and int(original[pointer, 0]) == i:
            o = original[pointer]; pointer += 1
            if int(o[7]) == 0:
                pending = -1
            if int(o[8]) != 1:
                out[count] = o; count += 1
            elif int(o[7]) == 1:
                held = int(o[4]); virtual = held; initial_added = held; added_price = o[5]
                peak = -np.inf; floor = -np.inf; active = False; done = False
                out[count] = o; count += 1
            else:
                before = virtual; virtual -= int(o[4])
                remain = int(np.floor(held*virtual/before+.5)) if virtual else 0
                take = held-remain; held = remain
                if take:
                    out[count] = o; out[count, 4] = take; out[count, 9] = take*385//10; count += 1
        # ----------------------------------------
        # 判断行では執行せず、次の正常気配で返す。ギャップによる赤字も許容して記録する。
        if pending >= 0 and i > pending and good and held:
            take = held if protect == 0 else min(held, min(protect, initial_added))
            out[count] = np.array([i,pending,parent,-side,take,mark,1381.,0.,1.,take*385//10])
            count += 1; held -= take; pending = -1; done = True
        if not good or not held or done or activation <= 0.:
            continue
        move = side*(mark-added_price)
        peak = max(peak, move)
        if peak >= activation*risk:
            active = True
        if active:
            distance = tight_width if tighten_at > 0. and peak >= tighten_at*risk else width
            floor = max(floor, peak-distance*risk)
            if move <= floor and pending < 0:
                pending = i
    assert held == 0 and virtual == 0
    return out[:count]


def replay(times, quotes, atr, baseline, config):
    """
    機能: 追撃のある親だけ出口を変え、初回玉と補完担当を維持する。
    引数: times/atr/baseline(ndarray)、quotes/config(dict)は固定入力と比較条件。
    返り値: ndarrayは全場の十列注文。
    """
    parts = []
    for parent in np.unique(baseline[:, 2]):
        original = baseline[baseline[:, 2] == parent]
        if np.any((original[:, 8] == 1) & (original[:, 7] == 1)):
            parts.append(campaign(times, quotes['bid'], quotes['ask'], quotes['quote_valid'], atr, original,
                                  config['activation'], config['width'], config['tighten_at'],
                                  config['tight_width'], config['protect']))
        else:
            parts.append(original)
    result = np.concatenate(parts) if parts else np.empty((0, 10))
    return result[np.argsort(result[:, 0], kind='stable')] if len(result) else result
