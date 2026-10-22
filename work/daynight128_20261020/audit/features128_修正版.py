"""当場だけの遅延公開価格履歴。完成セッションの終値・方向は使わない。"""

import numpy as np

NAMES = ("平均5", "平均20", "標準偏差20", "高値20", "安値20", "効率20",
         "差5", "差20", "始値", "資料時刻", "相手差5", "相手差20",
         "相手効率20", "相手始値からの差", "相手資料時刻")


def minute_history(ready):
    """
    機能: 原行価格から境界以前の観測だけで一分終値列を作る。
    引数: ready(dict)は単一場・単一商品原行。価格時計を受信時計と同一視しない。
    返り値: tuple[ndarray,ndarray]は公開時刻と十列特徴。一分終端の60秒後に公開。
    """
    times, price = ready["time_s"], ready["last"]
    ok = np.isfinite(price) & (price > 0)
    ts, px = times[ok], price[ok]
    boundaries = np.arange(float(ready["start"]) + 60., times[-1] + .001, 60.)
    if not len(px):
        return boundaries + 60., np.full((len(boundaries), 11), np.nan)
    ix = np.searchsorted(ts, boundaries, side="left") - 1
    closes = np.full(len(boundaries), np.nan)
    valid = (ix >= 0)
    valid &= boundaries - ts[np.maximum(ix, 0)] <= 90.
    closes[valid] = px[ix[valid]]
    result = np.full((len(boundaries), 11), np.nan)
    opening = px[0]
    for i in range(20, len(boundaries)):
        segment = closes[i-20:i+1]
        if not np.isfinite(segment).all():
            continue
        path = np.abs(np.diff(segment)).sum()
        result[i] = (closes[i-4:i+1].mean(), closes[i-19:i+1].mean(),
            closes[i-19:i+1].std(), max(segment), min(segment),
            abs(segment[-1]-segment[0])/path if path else 0.,
            closes[i]-closes[i-5], closes[i]-closes[i-20], opening,
            boundaries[i], closes[i] - opening)
    return boundaries + 60., result


def build(packet):
    """
    機能: 一分終端60秒後の自己資料と、さらに60秒遅らせた相手資料を原行へ対応する。
    引数: packet(dict)は同場の二商品原行素材。
    返り値: dict[tuple,ndarray]は十五列。未来補完や相手同秒の並び替えはしない。
    """
    histories = {k: minute_history(v) for k, v in packet["inputs"].items()}
    result = {}
    for key, ready in packet["inputs"].items():
        peer = (key[0], "NK225" if key[1] == "TOPIX" else "TOPIX")
        now = ready["time_s"]
        own_time, own = histories[key]
        peer_time, other = histories[peer]
        i = np.searchsorted(own_time, now, side="right") - 1
        j = np.searchsorted(peer_time, now - 60., side="right") - 1
        out = np.full((len(now), 15), np.nan)
        valid = (i >= 0) & (j >= 0)
        vi, vj = i[valid], j[valid]
        out[valid, :10] = own[vi, :10]
        out[valid, 10] = other[vj, 6]
        out[valid, 11] = other[vj, 7]
        out[valid, 12] = other[vj, 5]
        out[valid, 13] = other[vj, 10]
        out[valid, 14] = other[vj, 9]
        stale = (now - out[:, 9] >= 120.) | (now - out[:, 14] >= 180.)
        out[stale] = np.nan
        result[key] = out
    return result
