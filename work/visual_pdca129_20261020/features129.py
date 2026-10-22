"""現在値と実気配の違いを切り分ける因果特徴。"""

import sys
import numpy as np
from common129 import PREV

sys.path.insert(0, str(PREV))
import features128


def prices_for(packet, kind):
    """
    機能: 原行を増減せず、正常気配中値又は現在値を選ぶ。
    引数: packet(dict)は保存原行、kind(str)はmid又はlast。
    返り値: dictは原行順・公開済みＡＴＲを保った価格入力。
    """
    out = {}
    for key, ready in packet["inputs"].items():
        price = ready["last"].copy()
        if kind == "mid":
            q = packet["quotes"][key]
            good = q["quote_valid"] & np.isfinite(q["bid"]) & np.isfinite(q["ask"])
            good &= (q["bid"] > 0.) & (q["ask"] > q["bid"])
            price[:] = np.nan
            price[good] = (q["bid"][good]+q["ask"][good])*.5
        out[key] = dict(ready, last=price)
    return out


def changes(ready, seconds):
    """
    機能: 窓端と同時刻の後続原行を参照せず、過去との差を計算する。
    引数: ready(dict)、seconds(float)は入力と窓幅。
    返り値: tuple[ndarray,ndarray]はＡＴＲ比変化と参照時刻。欠測は未知。
    """
    times, prices, atr = ready["time_s"], ready["last"], ready["atr"]
    ix = np.searchsorted(times, times-seconds, side="left")-1
    safe = np.maximum(ix, 0)
    valid = (ix >= 0) & (times-seconds-times[safe] <= 30.)
    valid &= np.isfinite(prices) & np.isfinite(prices[safe]) & np.isfinite(atr) & (atr > 0.)
    value, source = np.full(len(times), np.nan), np.full(len(times), np.nan)
    value[valid] = (prices[valid]-prices[safe[valid]])/atr[valid]
    source[valid] = times[safe[valid]]
    return value, source


def markets(inputs, peer_delay=0.):
    """
    機能: 相手市場を厳密過去だけで接続し、二市場の短期支持を作る。
    引数: inputs(dict)、peer_delay(float)は入力と追加の相手遅延秒。
    返り値: dictは十二列特徴。共通受信時計を再現したものではない。
    """
    deltas = {k: {sec: changes(v, sec) for sec in (30., 120.)} for k, v in inputs.items()}
    out = {}
    for key, ready in inputs.items():
        otherkey = key[0], "NK225" if key[1] == "TOPIX" else "TOPIX"
        other = inputs[otherkey]
        times, pt = ready["time_s"], other["time_s"]
        ix = np.searchsorted(pt, times-peer_delay, side="left")-1
        safe = np.maximum(ix, 0)
        valid = (ix >= 0) & (times-peer_delay-pt[safe] <= 15.)
        valid &= np.isfinite(ready["last"]) & np.isfinite(other["last"][safe])
        valid &= np.isfinite(ready["atr"]) & (ready["atr"] > 0.)
        valid &= np.isfinite(other["atr"][safe]) & (other["atr"][safe] > 0.)
        value = np.full((len(times), 12), np.nan)
        value[:, 0], value[:, 2] = ready["last"], ready["atr"]
        value[:, 4], value[:, 9] = deltas[key][30.]
        value[:, 5] = deltas[key][120.][0]
        for col, source in ((1, other["last"]), (3, other["atr"]),
                            (6, deltas[otherkey][30.][0]), (7, deltas[otherkey][120.][0]),
                            (8, pt), (10, deltas[otherkey][30.][1])):
            value[valid, col] = source[safe[valid]]
        value[:, 11] = valid.astype(float)
        out[key] = value
    return out


def long_history(inputs):
    """
    機能: 一時間の既知価格帯と進行を、確定後の公開時点だけへ接続する。
    引数: inputs(dict)は同一場の二市場。足端以前の価格のみ使う。
    返り値: dictは自己差60・高60・安60・相手差60・資料時刻二つの六列。
    """
    records = {}
    for key, ready in inputs.items():
        time, price = ready["time_s"], ready["last"]
        good = np.isfinite(price) & (price > 0.)
        ts, px = time[good], price[good]
        end = np.arange(ready["start"]+60., time[-1]+.001, 60.)
        ix = np.searchsorted(ts, end, side="left")-1
        close = np.full(len(end), np.nan)
        if len(px):
            valid = (ix >= 0) & (end-ts[np.maximum(ix, 0)] <= 90.)
            close[valid] = px[ix[valid]]
        data = np.full((len(end), 4), np.nan)
        for i in range(60, len(end)):
            segment = close[i-60:i+1]
            if np.isfinite(segment).all():
                data[i] = (segment[-1]-segment[0], max(segment), min(segment), end[i])
        records[key] = end+60., data
    result = {}
    for key, ready in inputs.items():
        other = key[0], "NK225" if key[1] == "TOPIX" else "TOPIX"
        own_t, own = records[key]
        peer_t, peer = records[other]
        time = ready["time_s"]
        i = np.searchsorted(own_t, time, side="right")-1
        j = np.searchsorted(peer_t, time-60., side="right")-1
        value = np.full((len(time), 6), np.nan)
        valid = (i >= 0) & (j >= 0)
        value[valid, :3] = own[i[valid], :3]
        value[valid, 3] = peer[j[valid], 0]
        value[valid, 4] = own[i[valid], 3]
        value[valid, 5] = peer[j[valid], 3]
        value[(time-value[:, 4] >= 120.) | (time-value[:, 5] >= 180.)] = np.nan
        result[key] = value
    return result


def build(packet, kind, peer_delay=0.):
    """
    機能: 選んだ観測価格で中期帯・短期二市場・長期文脈を統一する。
    引数: packet(dict)、kind(str)、peer_delay(float)は素材と固定仕様。
    返り値: tuple[dict,...]は入力、二市場、十五列履歴、六列長期文脈。
    """
    inputs = prices_for(packet, kind)
    return inputs, markets(inputs, peer_delay), features128.build(dict(inputs=inputs)), long_history(inputs)
