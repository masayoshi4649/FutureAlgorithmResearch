"""既知逆票見送りの公開maskへ、表示維持の単一部品だけを重ねる。"""

import numpy as np

import known_policy


def mask(feed: np.ndarray, count: int, features: dict, absorption: dict) -> tuple:
    """
    機能: 元KNOWN_VETOで許可した新規公開だけに、既知の表示維持見送りを追加する。
    引数: feed(ndarray)、count(int)、features/absorption(dict[int,dict])は保存票と新しい公開観測。
    返り値: tuple[ndarray,ndarray]は全normal行の採否・拒否理由。影feedや返済は削除しない。
    """
    accepted, reasons = known_policy.mask(feed, count, features, 'KNOWN_VETO')
    for entry in feed[feed[:, 7] == 1]:
        row = int(entry[0])
        value = absorption[row]
        assert value['side'] == int(entry[3])
        if accepted[row] and value['eligible'] and value['known'] and value['hit']:
            accepted[row] = False
            reasons[row] = 501
    return accepted, reasons
