"""確定５秒価格グリッドから、直近60秒・120秒の急な方向変化を公開する。"""

from itertools import product

import numpy as np
import pandas as pd


SECONDS = 5
WINDOW_SECONDS = (60, 120)
SPEEDS = (0.03, 0.05, 0.08)
FAMILIES = ("SPEED", "STRAIGHT", "ACCEL", "BREAK")


def definitions() -> list[dict]:
    """機能: ５秒価格グリッドで検査する24通りの入口を返す。

    引数: なし。
    返り値: ID、観測区間秒数、毎分速度の百分率、系統を持つ一覧(list[dict])。
    毎分速度0.05は１分あたり0.05%を意味する。
    """
    return [
        {
            "id": f"RAW_{family}_S{window:03d}_V{round(speed * 1000):03d}",
            "window_seconds": window,
            "speed": speed,
            "family": family,
        }
        for family, window, speed in product(FAMILIES, WINDOW_SECONDS, SPEEDS)
    ]


def build(ready: dict, quotes: dict) -> pd.DataFrame:
    """機能: 原板順から完全５秒グリッドを作り、次区間の最初の原板行で公開する。

    引数: ready(dict)は原板連番・価格時刻・開始時刻・刻み幅、
          quotes(dict)は同じ原板行に対応する買売気配と中間価格。
    返り値: 原板行、確定価格、速度、直線性、欠測判定を持つ特徴表(pd.DataFrame)。
    最後の未確定区間を使わず、欠測足は据置しても観測条件を偽に維持する。
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

    buckets = np.floor(times / SECONDS).astype(np.int64)
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
        int(np.floor(float(ready["start"]) / SECONDS)), int(buckets[-1]), dtype=np.int64
    )
    bars = pd.DataFrame(index=grid).join(actual)
    bars["observed"] = bars["close"].notna()
    # ----------------------------------------
    # 欠測を計算用に据え置くが、窓内の全ての足が実観測でなければ発火しない。
    for name in ("close", "source_last_seq", "source_last_time"):
        bars[name] = bars[name].ffill().astype(np.float64)
    for name in ("open", "high", "low"):
        bars[name] = bars[name].fillna(bars["close"]).astype(np.float64)
    one_step = bars["close"].diff().abs()
    observed = bars["observed"].astype(np.int64)
    for window in WINDOW_SECONDS:
        count = window // SECONDS
        shifted = bars["close"].shift(count)
        slope = 100.0 * np.log(bars["close"] / shifted) / (window / 60.0)
        travel = one_step.rolling(count, min_periods=count).sum()
        bars[f"slope_{window}"] = slope
        bars[f"er_{window}"] = (
            (bars["close"] - shifted).abs() / travel
        ).where(travel.ne(0), 0.0)
        bars[f"previous_slope_{window}"] = slope.shift(count)
        bars[f"prior_high_{window}"] = (
            bars["high"].shift(1).rolling(count, min_periods=count).max()
        )
        bars[f"prior_low_{window}"] = (
            bars["low"].shift(1).rolling(count, min_periods=count).min()
        )
        bars[f"window_observed_{window}"] = (
            observed.rolling(count + 1, min_periods=count + 1)
            .sum().eq(count + 1)
        )
        bars[f"accel_observed_{window}"] = (
            observed.rolling(2 * count + 1, min_periods=2 * count + 1)
            .sum().eq(2 * count + 1)
        )
        bars[f"window_observed_fraction_{window}"] = (
            observed.rolling(count + 1, min_periods=count + 1).mean()
        )
        bars[f"accel_observed_fraction_{window}"] = (
            observed.rolling(2 * count + 1, min_periods=2 * count + 1).mean()
        )

    # ----------------------------------------
    # 飛び越えた区間を遡って重複公開せず、直前の１区間だけを原板時点へ対応付ける。
    published = starts[1:]
    frame = bars.reindex(buckets[published] - 1).reset_index(names="source_bucket")
    frame["bar_start"] = frame["source_bucket"] * SECONDS
    frame["bar_end"] = frame["bar_start"] + SECONDS
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
        & frame["bar_age"].between(0, SECONDS)
        & frame["publication_delay"].between(0, SECONDS)
        & frame["spread"].le(frame["mid"] * 0.0002)
    )
    known = frame["source_last_seq"].notna()
    assert (frame.loc[known, "source_last_seq"] < frame.loc[known, "seq"]).all()
    assert (frame.loc[known, "source_last_time"] < frame.loc[known, "time_s"]).all()
    assert (frame["bar_end"] <= frame["time_s"]).all()
    return frame


def metadata(frame: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """機能: 符号状態が無方向・逆方向から切り替わった初発入口と根拠を返す。

    引数: frame(pd.DataFrame)は確定５秒足の公開特徴、cfg(dict)は入口定義。
    返り値: 原板行・方向・速度・直線性・前区間速度とブレイクの表(pd.DataFrame)。
    SPEEDは速度、STRAIGHTは直線性、ACCELは加速、BREAKは高安突破を順に追加する。
    """
    window = int(cfg["window_seconds"])
    speed, family = float(cfg["speed"]), cfg["family"]
    assert window in WINDOW_SECONDS and speed in SPEEDS and family in FAMILIES
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
    result["window_seconds"] = window
    result["speed"] = speed
    return result.reset_index(drop=True)


def candidates(frame: pd.DataFrame, cfg: dict) -> np.ndarray:
    """機能: ５秒足の初発入口を注文再生器へ渡す３列配列にする。

    引数: frame(pd.DataFrame)は公開特徴、cfg(dict)は24条件のうち１条件。
    返り値: 原板行番号・方向・幅予約欄０を並べた配列(np.ndarray、形状N×3)。
    """
    selected = metadata(frame, cfg)
    result = np.zeros((len(selected), 3), dtype=np.float64)
    result[:, 0] = selected["i"].to_numpy(dtype=np.float64)
    result[:, 1] = selected["side"].to_numpy(dtype=np.float64)
    return result
