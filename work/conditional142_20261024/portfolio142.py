"""親IDの名前空間を分けて、主担当と巡回担当を時系列合成する。"""

import numpy as np


def merge_patrol(main,patrol):
    """
    機能: 主担当内の追加親とも衝突しない専用IDで巡回担当を合成する。
    引数: main/patrol(ndarray[m,10])は各最大5枚枠の実約定。
    返り値: ndarrayは約定原行順の合成。時刻・価格・枚数・費用を変更しない。
    """
    extra=patrol.copy()
    if len(extra):
        assert np.all((extra[:,2]>=0)&(extra[:,2]<1_000_000))
        extra[:,2]+=5_000_000
    assert not set(main[:,2]).intersection(set(extra[:,2]))
    merged=np.concatenate((main,extra))
    return merged[np.argsort(merged[:,0],kind='stable')]
