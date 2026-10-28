"""旧入口に依存しない原板の因果的特徴を作る。将来ラベルを読み込まない。"""
from __future__ import annotations

from collections import Counter, deque
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

import numpy as np

WINDOWS = (5, 15, 30, 60, 120, 300)
FLOW_WINDOWS = (5, 15, 30, 60)
TOLERANCE = 15.0


def depth_snapshot(obj: dict, bid: float, ask: float, tick: float) -> tuple:
    """表示板だけから厚みと距離重みを計算する。

    引数: obj(dict)、bid/ask/tick(float)。返り値: tuple[float,float,float]は5段/10段/距離重み不均衡。
    """
    sides = []
    for name, best, direction in (("Buy", bid, -1), ("Sell", ask, 1)):
        values = []
        prior = best
        for level in range(1, 11):
            item = obj.get(name+str(level)) or {}
            price, quantity = float(item.get("Price") or 0), float(item.get("Qty") or 0)
            if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity < 0 or direction*(price-prior) < 0:
                values.append((math.nan, math.nan))
            else:
                values.append((quantity, quantity/(1+abs(price-best)/tick)))
                prior = price
        sides.append(values)
    answer = []
    for count, field in ((5, 0), (10, 0), (10, 1)):
        buy = sum(x[field] for x in sides[0][:count])
        sell = sum(x[field] for x in sides[1][:count])
        answer.append((buy-sell)/(buy+sell) if math.isfinite(buy+sell) and buy+sell > 0 else math.nan)
    return tuple(answer)


def read_market(scene: dict, symbol: str) -> tuple[dict, dict]:
    """全原行を読み、過去模型と同じ採番と時刻最初の正常観測を作る。

    引数: scene(dict)、symbol(str)。返り値: tuple[dict,dict]は市場配列と内容指紋/除外根拠。
    """
    path = Path(scene["books"][symbol])
    digest, counts = hashlib.sha256(), Counter()
    columns = {k: [] for k in ("time", "last", "bid", "ask", "bq", "aq", "line", "imb5", "imb10", "depth_imb")}
    observations, representatives = [], []
    prior = scene["start"]
    current_time, current_good = None, False
    tick = 10.0 if symbol == "NK225" else .5
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            digest.update(line)
            counts["physical"] += 1
            obj = json.loads(line)
            clock = obj.get("CurrentPriceTime")
            try:
                if not isinstance(clock, str):
                    raise ValueError("価格時計欠測")
                at = datetime.fromisoformat(clock).timestamp()
            except (TypeError, ValueError):
                counts["clock_missing"] += 1
                continue
            if at < scene["start"] or at > scene["end"] or scene.get("cutoff", 0) > 0 and at >= scene["cutoff"]:
                counts["outside"] += 1
                continue
            if at < prior:
                counts["backwards"] += 1
                continue
            last = float(obj.get("CurrentPrice") or 0)
            if not math.isfinite(last) or last <= 0:
                counts["last_missing"] += 1
                continue
            prior = at
            bid, ask = obj.get("Buy1") or {}, obj.get("Sell1") or {}
            bp, ap = float(bid.get("Price") or 0), float(ask.get("Price") or 0)
            bq, aq = float(bid.get("Qty") or 0), float(ask.get("Qty") or 0)
            normal = math.isfinite(bp) and math.isfinite(ap) and 0 < bp < ap
            index = len(columns["time"])
            if at != current_time:
                current_time, current_good = at, False
                representatives.append(index)
            depth = (math.nan,)*3
            if normal and not current_good:
                current_good = True
                representatives[-1] = index
                observations.append(index)
                depth = depth_snapshot(obj, bp, ap, tick)
            for name, value in zip(columns, (at, last, bp, ap, bq, aq, line_number, *depth)):
                columns[name].append(value)
            counts["adopted"] += 1
    expected = next(x["sha256"] for x in scene["fingerprints"] if Path(x["path"]) == path)
    assert digest.hexdigest() == expected, "原資料指紋の相違"
    data = {k: np.asarray(v, dtype=np.int64 if k == "line" else np.float64) for k, v in columns.items()}
    data["observations"] = np.asarray(observations, dtype=np.int64)
    data["representatives"] = np.asarray(representatives, dtype=np.int64)
    data["valid"] = np.isfinite(data["bid"]) & np.isfinite(data["ask"]) & (data["bid"] > 0) & (data["ask"] > data["bid"])
    data["mid"] = data["bid"]+(data["ask"]-data["bid"])/2
    return data, {"path": str(path), "sha256": digest.hexdigest(), "counts": dict(counts), "observations": len(observations)}


def endpoints(market: dict, targets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """既知の過去端以前にある最後の正常板と15秒許容を取得する。

    引数: market(dict)、targets(ndarray)。返り値: tuple[ndarray,ndarray]は添字と既知判定。
    """
    good = np.flatnonzero(market["valid"])
    found = np.searchsorted(market["time"][good], targets, side="right")-1
    indices = np.full(len(targets), -1, dtype=np.int64)
    exists = found >= 0
    indices[exists] = good[found[exists]]
    known = exists.copy()
    known[exists] &= targets[exists]-market["time"][indices[exists]] <= TOLERANCE
    return indices, known


def extrema(market: dict, observations: np.ndarray, seconds: int, offset: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """現在原行を含めない観測高安を単調キューで計算する。

    引数: market(dict)、observations(ndarray)、seconds/offset(int)。返り値: tuple[ndarray,ndarray]は高値と安値。
    """
    times, mid, good = market["time"], market["mid"], market["valid"]
    highs, lows = np.full(len(observations), np.nan), np.full(len(observations), np.nan)
    upper, lower, cursor = deque(), deque(), 0
    for n, current in enumerate(observations):
        end = times[current]-offset
        stop = current if offset == 0 else int(np.searchsorted(times, end, side="left"))
        while cursor < stop:
            if good[cursor]:
                while upper and mid[upper[-1]] <= mid[cursor]:
                    upper.pop()
                while lower and mid[lower[-1]] >= mid[cursor]:
                    lower.pop()
                upper.append(cursor)
                lower.append(cursor)
            cursor += 1
        start = end-seconds
        while upper and times[upper[0]] < start:
            upper.popleft()
        while lower and times[lower[0]] < start:
            lower.popleft()
        if upper:
            highs[n], lows[n] = mid[upper[0]], mid[lower[0]]
    return highs, lows


def flows(market: dict) -> dict:
    """最良板の数量変化をOFIと表示補充/消耗代理に分ける。

    引数: market(dict)。返り値: dictは各原行の正規化値と既知判定。
    """
    bp, ap, bq, aq = (market[k] for k in ("bid", "ask", "bq", "aq"))
    goodq = market["valid"] & np.isfinite(bq) & np.isfinite(aq) & (bq > 0) & (aq > 0)
    valid = np.r_[False, goodq[1:] & goodq[:-1] & (np.diff(market["time"]) <= TOLERANCE)]
    out = {k: np.zeros(len(bp)) for k in ("ofi", "bid_refill", "ask_refill", "bid_deplete", "ask_deplete")}
    i = np.flatnonzero(valid)
    previous = i-1
    numerator = np.where(bp[i] >= bp[previous], bq[i], 0)-np.where(bp[i] <= bp[previous], bq[previous], 0)-np.where(ap[i] <= ap[previous], aq[i], 0)+np.where(ap[i] >= ap[previous], aq[previous], 0)
    denominator = bq[i]+bq[previous]+aq[i]+aq[previous]
    finite = np.isfinite(numerator) & np.isfinite(denominator) & (denominator > 0)
    valid[i[~finite]] = False
    i, previous = i[finite], previous[finite]
    out["ofi"][i] = numerator[finite]/denominator[finite]
    for side, price, qty in (("bid", bp, bq), ("ask", ap, aq)):
        same_price = price[i] == price[previous]
        diff = (qty[i]-qty[previous])/(qty[i]+qty[previous])
        out[side+"_refill"][i] = np.where(same_price, np.maximum(0, diff), 0)
        out[side+"_deplete"][i] = np.where(same_price, np.maximum(0, -diff), 0)
    out["valid"] = valid
    return out


def integral_at(market: dict, target: np.ndarray, numerator: np.ndarray, denominator: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """過去板を最大15秒だけ保持する積分を指定時計で評価する。

    引数: market(dict)、target/numerator/denominator(ndarray)。返り値: tuple[ndarray,ndarray]は価格積分と既知秒。
    """
    positions = np.searchsorted(market["time"], target, side="right")-1
    result, duration = np.zeros(len(target)), np.zeros(len(target))
    exists = positions >= 0
    at = positions[exists]
    hold = np.minimum(TOLERANCE, np.maximum(0, target[exists]-market["time"][at]))*market["valid"][at]
    result[exists] = numerator[at]+hold*np.where(market["valid"][at], market["mid"][at], 0)
    duration[exists] = denominator[at]+hold
    return result, duration


def build_features(own: dict, peer: dict, scene: dict) -> dict:
    """当時の原行prefixだけから特徴行列を作る。

    引数: own/peer/scene(dict)。返り値: dictはNPZ向け配列。将来の約定・ラベルを含めない。
    """
    obs = own["observations"]
    times, mid = own["time"][obs], own["mid"][obs]
    cols = {"mid": mid, "last": own["last"][obs], "spread": own["ask"][obs]-own["bid"][obs]}
    invalid_prefix = np.r_[0, np.cumsum(~own["valid"])]
    good = np.flatnonzero(own["valid"])
    variation = np.zeros(len(own["time"]))
    variation[good[1:]] = np.abs(np.diff(own["mid"][good]))
    path = np.cumsum(variation)
    ends = {}
    for seconds in WINDOWS:
        ix, known = endpoints(own, times-seconds)
        assert np.all(ix[known] < obs[known])
        ends[seconds] = (ix, known)
        changes, elapsed, delay = (np.full(len(obs), np.nan) for _ in range(3))
        changes[known] = mid[known]-own["mid"][ix[known]]
        elapsed[known] = times[known]-own["time"][ix[known]]
        delay[known] = elapsed[known]-seconds
        cols[f"ret{seconds}_pt"] = changes
        cols[f"vel{seconds}_pt_s"] = changes/elapsed
        cols[f"elapsed{seconds}_s"] = elapsed
        cols[f"endpoint_delay{seconds}_s"] = delay
        cols[f"known{seconds}"] = known.astype(float)
        bad = np.full(len(obs), np.nan)
        bad[known] = invalid_prefix[obs[known]+1]-invalid_prefix[ix[known]]
        cols[f"invalid{seconds}_rows"] = bad
        if seconds in (30, 60, 120, 300):
            high, low = extrema(own, obs, seconds)
            high[~known], low[~known] = np.nan, np.nan
            cols[f"high{seconds}_prev"], cols[f"low{seconds}_prev"] = high, low
            width = high-low
            cols[f"range{seconds}_pt"] = width
            cols[f"pos{seconds}"] = np.divide(mid-low, width, out=np.full(len(obs), np.nan), where=width > 0)
            distance = np.zeros(len(obs))
            distance[known] = path[obs[known]]-path[ix[known]]
            efficiency = np.full(len(obs), np.nan)
            efficiency[known] = np.divide(np.abs(changes[known]), distance[known], out=np.zeros(np.sum(known)), where=distance[known] > 0)
            cols[f"er{seconds}"] = efficiency
    for short, long in ((5, 15), (15, 60), (30, 120), (60, 300)):
        cols[f"accel{short}_{long}_pt_s"] = cols[f"vel{short}_pt_s"]-cols[f"vel{long}_pt_s"]
    now5, known5 = ends[5]
    prior10, known10 = endpoints(own, times-10)
    known = known5 & known10
    lag = np.full(len(obs), np.nan)
    lag[known] = own["mid"][now5[known]]-own["mid"][prior10[known]]
    lag_elapsed = np.full(len(obs), np.nan)
    lag_elapsed[known] = own["time"][now5[known]]-own["time"][prior10[known]]
    cols["ret5_lag5_pt"] = lag
    cols["vel5_lag5_pt_s"] = np.divide(lag, lag_elapsed, out=np.full(len(obs), np.nan), where=lag_elapsed > 0)
    cols["accel5_prev5_pt_s"] = cols["vel5_pt_s"]-cols["vel5_lag5_pt_s"]
    high, low = extrema(own, obs, 60, 60)
    ready = ends[120][1]
    high[~ready], low[~ready] = np.nan, np.nan
    cols["range60_previous_pt"] = high-low
    cols["range60_ratio"] = np.divide(cols["range60_pt"], high-low, out=np.full(len(obs), np.nan), where=high-low > 0)
    # ----------------------------------------
    # OFIは表示数量の変化。取消しと取引、注文ID別の補充を識別するものではない。
    flow = flows(own)
    valid_count = np.r_[0, np.cumsum(flow["valid"])]
    for seconds in FLOW_WINDOWS:
        left = np.searchsorted(own["time"], times-seconds, side="left")
        n = valid_count[obs+1]-valid_count[left]
        required = ends[seconds][1] & (n >= 2)
        cols[f"ofi{seconds}_count"] = n.astype(float)
        cols[f"ofi{seconds}_coverage"] = n/np.maximum(1, obs-left+1)
        for name in ("ofi", "bid_refill", "ask_refill", "bid_deplete", "ask_deplete"):
            total = np.r_[0, np.cumsum(flow[name])]
            mean = np.full(len(obs), np.nan)
            mean[required] = (total[obs[required]+1]-total[left[required]])/n[required]
            cols[f"{name}{seconds}"] = mean
    bq, aq = own["bq"][obs], own["aq"][obs]
    quantity_known = np.isfinite(bq) & np.isfinite(aq) & (bq > 0) & (aq > 0) & np.isfinite(bq+aq)
    cols["imb1"] = np.divide(bq-aq, bq+aq, out=np.full(len(obs), np.nan), where=quantity_known)
    cols["microprice_offset_pt"] = cols["spread"]*cols["imb1"]*.5
    for key in ("imb5", "imb10", "depth_imb"):
        cols[key] = own[key][obs]
    # ----------------------------------------
    # VWAP固有時計がないため、取引VWAPを創作せず観測価格の時間加重平均を保存する。
    delta = np.r_[0.0, np.diff(own["time"])]
    held = np.minimum(delta, TOLERANCE)*np.r_[False, own["valid"][:-1]]
    prior_mid = np.r_[0.0, np.where(own["valid"][:-1], own["mid"][:-1], 0)]
    integral, seconds_known = np.cumsum(held*prior_mid), np.cumsum(held)
    for window in (60, 300):
        before, before_seconds = integral_at(own, times-window, integral, seconds_known)
        duration = seconds_known[obs]-before_seconds
        value = np.divide(integral[obs]-before, duration, out=np.full(len(obs), np.nan), where=duration > 0)
        value[~ends[window][1]] = np.nan
        cols[f"twap{window}"] = value
        cols[f"twap{window}_distance_pt"] = mid-value
        cols[f"twap{window}_coverage"] = duration/window
    # ----------------------------------------
    # 相手は各価格時計の最初正常代表だけ。現在同時計と後着snapshotを採用しない。
    reps = peer["representatives"]
    peer_market = {k: v[reps] for k, v in peer.items() if isinstance(v, np.ndarray) and len(v) == len(peer["time"])}
    found = np.searchsorted(peer_market["time"], times, side="left")-1
    has = found >= 0
    age = np.full(len(obs), np.nan)
    age[has] = times[has]-peer_market["time"][found[has]]
    fresh = has.copy()
    fresh[has] &= peer_market["valid"][found[has]] & (age[has] <= TOLERANCE)
    cols["peer_age_s"] = age
    cols["peer_current_known"] = fresh.astype(float)
    for seconds in (5, 15, 60):
        targets = np.full(len(obs), -np.inf)
        targets[fresh] = peer_market["time"][found[fresh]]-seconds
        ix, known = endpoints(peer_market, targets)
        known &= fresh
        value, elapsed = np.full(len(obs), np.nan), np.full(len(obs), np.nan)
        value[known] = (peer_market["mid"][found[known]]/peer_market["mid"][ix[known]]-1)*10000
        elapsed[known] = peer_market["time"][found[known]]-peer_market["time"][ix[known]]
        cols[f"peer_ret{seconds}_bp"], cols[f"peer_elapsed{seconds}_s"] = value, elapsed
        cols[f"peer_vel{seconds}_bp_s"] = value/elapsed
    cols["since_start_s"] = times-scene["start"]
    cols["to_end_s"] = scene["end"]-times
    cols["to_us_open_s"] = scene.get("us_open", 0)-times if scene["kind"] == "Night" else np.full(len(obs), np.nan)
    phase = np.zeros(len(obs), dtype=np.int8) if scene["kind"] == "Day" else np.where(times < scene["us_open"], 1, 2).astype(np.int8)
    names = list(cols)
    matrix = np.column_stack([cols[n] for n in names])
    matrix[~np.isfinite(matrix)] = np.nan
    return {"features": matrix, "feature_names": np.asarray(names), "time": times, "decision_index": obs,
            "physical_line": own["line"][obs], "phase": phase}
