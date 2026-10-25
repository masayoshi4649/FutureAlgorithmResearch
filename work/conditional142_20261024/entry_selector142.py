"""入口の確認方法を選ぶ判断層。注文・価格約定・損益は扱わない。"""

import numpy as np
from numba import njit


@njit(cache=True)
def choose_entry(policy, a, side, failed_same):
    """
    機能: 低効率帯の反転候補に対し通常反発か二段階の再進行確認を選ぶ。
    引数: policy(int)、a(ndarray[30])は当時特徴、side(int)、failed_same(int)。
    返り値: tuple[int,int]は確認方式(0通常/2再進行)と説明コード。
    """
    if policy == 0:
        return 0, 0
    against40 = side*a[4] < 0. and side*a[15] < 0.
    aligned20 = np.isfinite(a[28]) and np.isfinite(a[29]) and side*a[28] > 0. and side*a[29] > 0.
    aligned5 = side*a[3] > 0. and side*a[14] > 0.
    if policy == 1:
        return (2, 11) if against40 else (0, 12)
    if policy == 2:
        return (0, 21) if aligned20 or (aligned5 and not against40) else (2, 22)
    # ----------------------------------------
    # 同方向の再失敗後は短い反発だけで確認を緩めず、価格と板の再合意を要求する。
    flow = np.isfinite(a[24]) and np.isfinite(a[26]) and side*a[24] >= 0. and side*a[26] >= 0.
    short = side*a[13] >= 0. and side*a[21] >= 0.
    strong = aligned20 and aligned5 and flow and short
    if failed_same > 0:
        return (0, 31) if strong else (2, 32)
    return (0, 33) if strong or (aligned5 and not against40) else (2, 34)


@njit(cache=True)
def allow_add(policy, a, side, floor):
    """
    機能: 初回損失予算内での追撃に利益保護が必要かを選ぶ。
    引数: policy(int)、a(ndarray[30])、side(int)、floor(float)は初回建値からの停止線。
    返り値: boolは追加審査を続けてよい場合に真。
    """
    if policy == 0:
        return True
    aligned = np.isfinite(a[28]) and np.isfinite(a[29]) and side*a[28] > 0. and side*a[29] > 0.
    aligned = aligned and side*a[3] > 0. and side*a[14] > 0.
    return floor > 0. or (policy == 2 and aligned)
