"""短時間の価格速度と直線性を、確定した１分足だけから公開する。"""

from itertools import product

import numpy as np
import pandas as pd


WINDOWS = (2, 3, 5, 10)
SPEEDS = (0.01, 0.02, 0.03)
FAMILIES = ("SPEED", "STRAIGHT", "ACCEL", "BREAK")


def definitions() -> list[dict]:
    """機能: 結果を見る前に固定した48通りの入口定義を返す。

    引数: なし。
    返り値: 手法ID、区間分数、毎分速度の百分率、系統を持つ一覧(list[dict])。
    速度0.01は毎分0.01%を意味し、ラジアンやチャート上の角度ではない。
    """
    return [
        {
            "id": f"{family}_H{window:02d}_V{round(speed * 1000):03d}",
            "window": window,
            "speed": speed,
            "family": family,
        }
        for family, window, speed in product(FAMILIES, WINDOWS, SPEEDS)
    ]


def build(ready: dict, quotes: dict) -> pd.DataFrame:
    """機能: 原板順の価格から確定１分足を作り、次分の最初の原板行で公開する。

    引数: ready(dict)は原板連番・価格時刻・開始時刻・刻み幅、
          quotes(dict)は同じ原板行に対応する買売気配と中間価格。
    返り値: 公開行、気配、速度、直線性、加速とブレイク条件の表(pd.DataFrame)。
    欠測分を補間して取引可能にせず、全必要足の実観測を個別に検査する。
    """
    times = np.asarray(ready["time_s"], dtype=np.float64)
    seq = np.asarray(ready["seq"], dtype=np.int64)
    mid = np.asarray(quotes["mid"], dtype=np.float64)
    bid = np.asarray(quotes["bid"], dtype=np.float64)
    ask = np.asarray(quotes["ask"], dtype=np.float64)
    np.testing.assert_array_equal(seq, quotes["seq"])
    np.testing.assert_array_equal(times, quotes["time_s"])
    assert len(times) > 0, "原板行が１件以上必要です。"
    assert np.all(np.diff(times) >= 0), "価格時刻は非減少である必要があります。"
    assert np.all(np.diff(seq) > 0), "原板連番は単調増加である必要があります。"
    assert len(mid) == len(times) and np.all(mid > 0)
    assert np.all(ask > bid) and np.all(bid > 0)

    buckets = np.floor(times / 60).astype(np.int64)
    starts = np.r_[0, np.flatnonzero(np.diff(buckets)) + 1].astype(np.int64)
    ends = np.r_[starts[1:] - 1, len(times) - 1].astype(np.int64)
    actual = pd.DataFrame(
        {
            "open": mid[starts],
            "high": np.maximum.reduceat(mid, starts),
            "low": np.minimum.reduceat(mid, starts),
            "close": mid[ends],
            "source_last_seq": seq[ends].astype(np.float64),
            "source_last_time": times[ends],
        },
        index=buckets[starts],
    )
    grid = np.arange(
        int(np.floor(float(ready["start"]) / 60)), int(buckets[-1]), dtype=np.int64
    )
    bars = pd.DataFrame(index=grid).join(actual)
    bars["observed"] = bars["close"].notna()
    # ----------------------------------------
    # 欠測足は計算用に価格を据え置くが、必要足の観測条件が必ず発火を抑止する。
    for name in ("close", "source_last_seq", "source_last_time"):
        bars[name] = bars[name].ffill().astype(np.float64)
    for name in ("open", "high", "low"):
        bars[name] = bars[name].fillna(bars["close"]).astype(np.float64)
    one_step = bars["close"].diff().abs()
    observed = bars["observed"].astype(np.int64)
    for window in WINDOWS:
        shifted = bars["close"].shift(window)
        slope = 100.0 * np.log(bars["close"] / shifted) / window
        travel = one_step.rolling(window, min_periods=window).sum()
        displacement = (bars["close"] - shifted).abs()
        bars[f"slope_{window}"] = slope
        bars[f"er_{window}"] = (displacement / travel).where(travel.ne(0), 0.0)
        bars[f"previous_slope_{window}"] = slope.shift(window)
        bars[f"prior_high_{window}"] = (
            bars["high"].shift(1).rolling(window, min_periods=window).max()
        )
        bars[f"prior_low_{window}"] = (
            bars["low"].shift(1).rolling(window, min_periods=window).min()
        )
        bars[f"window_observed_{window}"] = (
            observed.rolling(window + 1, min_periods=window + 1).sum().eq(window + 1)
        )
        bars[f"accel_observed_{window}"] = (
            observed.rolling(2 * window + 1, min_periods=2 * window + 1)
            .sum().eq(2 * window + 1)
        )

    # ----------------------------------------
    # 次バケットで最初に現れた原板行だけを使い、未確定の末尾足を公開しない。
    published = starts[1:]
    frame = bars.reindex(buckets[published] - 1).reset_index(names="source_bucket")
    frame["bar_start"] = frame["source_bucket"] * 60
    frame["bar_end"] = frame["bar_start"] + 60
    frame["i"] = published
    frame["seq"] = seq[published]
    frame["time_s"] = times[published]
    frame["mid"] = mid[published]
    frame["bid"] = bid[published]
    frame["ask"] = ask[published]
    frame["spread"] = ask[published] - bid[published]
    frame["tick"] = float(ready["tick"])
    frame["bar_age"] = frame["time_s"] - frame["source_last_time"]
    frame["publication_delay"] = frame["time_s"] - frame["bar_end"]
    frame["quality"] = (
        frame["observed"].eq(True)
        & frame["bar_age"].between(0, 60)
        & frame["publication_delay"].between(0, 60)
        & frame["spread"].le(frame["mid"] * 0.0002)
    )
    known = frame["source_last_seq"].notna()
    assert (frame.loc[known, "source_last_seq"] < frame.loc[known, "seq"]).all()
    assert (frame.loc[known, "source_last_time"] < frame.loc[known, "time_s"]).all()
    assert (frame["bar_end"] <= frame["time_s"]).all()
    return frame


def metadata(frame: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """機能: 符号状態が無方向・逆方向から切り替わった入口だけを抽出する。

    引数: frame(pd.DataFrame)は公開特徴、cfg(dict)はdefinitionsの入口定義。
    返り値: 原板行、方向、速度、直線性、直前速度とブレイクを持つ入口表(pd.DataFrame)。
    SPEEDは速度のみ、STRAIGHTは直線性を追加、ACCELは加速を追加、
    BREAKは加速に加えて直前高安を１刻み以上突破したことを要求する。
    """
    window, speed, family = int(cfg["window"]), float(cfg["speed"]), cfg["family"]
    assert window in WINDOWS and speed in SPEEDS and family in FAMILIES
    slope = frame[f"slope_{window}"]
    er = frame[f"er_{window}"]
    previous = frame[f"previous_slope_{window}"]
    direction = pd.Series(
        np.sign(slope.fillna(0.0)).astype(np.int64), index=frame.index
    )
    valid = (
        frame["quality"]
        & frame[f"window_observed_{window}"]
        & slope.abs().ge(speed)
    )
    if family != "SPEED":
        valid &= er.ge(0.7)
    if family in ("ACCEL", "BREAK"):
        valid &= (
            frame[f"accel_observed_{window}"]
            & (direction * previous).le(slope.abs() / 2.0)
        )
    breakthrough = (
        (direction.eq(1) & frame["close"].ge(frame[f"prior_high_{window}"] + frame["tick"]))
        | (direction.eq(-1) & frame["close"].le(frame[f"prior_low_{window}"] - frame["tick"]))
    )
    if family == "BREAK":
        valid &= breakthrough
    state = direction.where(valid, 0).astype(np.int64)
    fire = state.ne(0) & state.ne(state.shift(1, fill_value=0))
    columns = (
        "i", "seq", "time_s", "source_bucket", "bar_end", "source_last_seq",
        "source_last_time", "mid", "bid", "ask", "spread", "close", "bar_age",
        "publication_delay", "tick",
    )
    result = frame.loc[fire, list(columns)].copy()
    result["side"] = state[fire]
    result["slope"] = slope[fire]
    result["er"] = er[fire]
    result["previous_slope"] = previous[fire]
    result["breakthrough"] = breakthrough[fire]
    result["prior_high"] = frame.loc[fire, f"prior_high_{window}"]
    result["prior_low"] = frame.loc[fire, f"prior_low_{window}"]
    result["id"] = cfg["id"]
    result["family"] = family
    result["window"] = window
    result["speed"] = speed
    return result.reset_index(drop=True)


def candidates(frame: pd.DataFrame, cfg: dict) -> np.ndarray:
    """機能: 入口表を注文再生器の３列配列へ変換する。

    引数: frame(pd.DataFrame)は公開特徴、cfg(dict)は入口定義。
    返り値: 原板行番号・売買方向・幅予約欄の配列(np.ndarray、形状N×3)。
    幅は今回使わないため０とし、入口価格は次の原板行で決める。
    """
    selected = metadata(frame, cfg)
    result = np.zeros((len(selected), 3), dtype=np.float64)
    result[:, 0] = selected["i"].to_numpy(dtype=np.float64)
    result[:, 1] = selected["side"].to_numpy(dtype=np.float64)
    return result
