"""現行の因果的な仮想売買通知を固定し、初回と追撃の数量だけを比較する。"""

import numpy as np
from numba import njit


@njit(cache=True)
def campaign(times, bid, ask, qok, atr, market, phase, original, initial, mode, width, hold, adaptive):
    """
    機能: 一親の既存通知をその発生原行で読み、試し玉と一回の追撃を会計する。
    引数: 原行配列(ndarray)、original(ndarray)は当該親の既存約定通知、
          initial/mode(int)、width/hold(float)、adaptive(bool)は事前固定条件。
    返り値: ndarrayは約定行・判断行・親・方向・枚数・価格・理由・新規・脚・費用の十列。
    """
    out = np.zeros((128, 10)); count = 0
    side = int(original[0, 3]); parent = int(original[0, 2])
    full = int(original[0, 4]); virtual = full; pointer = 0
    held = np.zeros(2, np.int64); entries = np.zeros(2)
    target = 5; used = False; reduced = False
    pending = 0; pending_source = -1; pending_qty = 0
    entry_row = -1; risk = 0.; since = -np.inf
    for i in range(int(original[0, 0]), int(original[-1, 0])+1):
        good = qok[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0 < bid[i] < ask[i]
        mark = bid[i] if side > 0 else ask[i]
        # ----------------------------------------
        # 既存通知は発生した行だけで読む。将来の返済価格・勝敗は使用しない。
        while pointer < len(original) and int(original[pointer, 0]) == i:
            o = original[pointer]; pointer += 1
            if int(o[7]) == 1:
                entry_row = i; risk = max(20., atr[int(o[1])])
                qty = initial
                if adaptive:
                    src = int(o[1])
                    strong = market[src,11] == 1. and side*market[src,4] >= .05 and side*market[src,6] >= .05
                    strong = strong and side*market[src,5] >= .2 and side*market[src,7] >= .2
                    if strong and phase[src] not in (0,2,7,9): qty = 5
                    if phase[src] in (0,2,7,9): qty = 1
                held[0] = qty; entries[0] = o[5]
                out[count] = np.array([i,o[1],parent,side,qty,o[5],o[6],1.,0.,int(qty*385)//10]); count += 1
            else:
                before = virtual; virtual -= int(o[4]); reduced = True
                # 返済を優先し、未実行の追加は取り消す。
                pending = 0
                for leg in range(2):
                    remaining = int(np.floor(held[leg]*virtual/before+.5)) if virtual else 0
                    take = held[leg]-remaining
                    if take:
                        out[count] = np.array([i,o[1],parent,-side,take,o[5],o[6],0.,leg,int(take*385)//10]); count += 1
                        held[leg] -= take
        # ----------------------------------------
        # 追加独自の予約を次の正常原行で執行する。元玉の停止は動かさない。
        if pending and good and i > pending_source:
            if pending == 1 and held[0] > 0 and not reduced:
                held[1] = pending_qty; entries[1] = ask[i] if side > 0 else bid[i]
                out[count] = np.array([i,pending_source,parent,side,pending_qty,entries[1],901.,1.,1.,int(pending_qty*385)//10]); count += 1
            elif pending == 2 and held[1]:
                qty = held[1]
                out[count] = np.array([i,pending_source,parent,-side,qty,mark,902.,0.,1.,int(qty*385)//10]); count += 1
                held[1] = 0
            pending = 0
        if not good or (i > 0 and times[i]-times[i-1] > 15.): since = -np.inf
        if good and held[1] and side*(mark-entries[1]) <= -.5*risk and pending == 0:
            pending = 2; pending_source = i
        if mode == 0 or not good or used or reduced or not held[0] or held[0] >= target or pending:
            continue
        move = side*(mark-entries[0])/risk
        support = market[i,11] == 1. and side*market[i,4] >= .05 and side*market[i,6] >= .05
        support = support and side*market[i,5] >= .2 and side*market[i,7] >= .2
        support = support and market[i,8] > times[entry_row] and times[i] >= times[entry_row]+30.
        if support:
            if not np.isfinite(since): since = times[i]
        else: since = -np.inf
        passed = move >= width and (mode == 1 or (support and times[i]-since >= hold))
        if adaptive and phase[i] in (0,2,7,9): passed = False
        if passed:
            pending = 1; pending_source = i; pending_qty = target-int(held.sum()); used = True
    assert held.sum() == 0
    return out[:count]


def replay(times, quotes, atr, market, phase, core, extra, config):
    """
    機能: 主担当の分割数量と未参加補完を同一の上限内で合算する。
    引数: times/atr/market/phase/core/extra(ndarray)、quotes/config(dict)は固定入力。
    返り値: ndarrayは十列注文。元の仮想通知を固定した数量層の比較である。
    """
    parts = []
    for cid in np.unique(core[:, 2]):
        rows = core[core[:, 2] == cid]
        parts.append(campaign(times, quotes['bid'], quotes['ask'], quotes['quote_valid'], atr, market, phase,
                              rows, config['initial'], config['mode'], config['width'], config['hold'], config['adaptive']))
    for cid in np.unique(extra[:, 2]):
        rows = extra[extra[:, 2] == cid]
        original = int(rows[0, 4]); qty = max(1, original//2); held = qty; virtual = original
        for o in rows:
            new = int(o[7])
            if new: take = qty
            else:
                virtual -= int(o[4]); remain = int(np.floor(qty*virtual/original+.5)); take = held-remain; held = remain
            if take:
                parts.append(np.array([[o[0],o[1],10000+cid,o[3],take,o[5],o[6],new,2,(take*385)//10]], dtype=float))
        assert held == 0
    result = np.concatenate(parts) if parts else np.empty((0,10))
    if len(result): result = result[np.argsort(result[:,0], kind='stable')]
    return result
