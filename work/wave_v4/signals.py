"""確定足と利用可能時刻を付けた生板特徴から、対称な新規方向を計算する。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


PARAMETERS = (0.75, 1.0, 1.25)
FAMILIES = {
    1: "価格・５分対20分移動平均と傾き",
    2: "価格・８分対40分移動平均と傾き",
    3: "価格・15分回帰と直線性",
    4: "価格・30分回帰と直線性",
    5: "価格・20分方向効率",
    6: "価格・20分高安突破",
    7: "価格・５分足方向指数20分",
    8: "価格・セッションVWAPと傾き",
    9: "価格・変化点累積和",
    10: "価格・直近極値からのATR方向転換",
    11: "価格・14分RSIと変位",
    12: "価格・適応移動平均からの変位",
    13: "価格・20分と40分の方向一致",
    14: "価格・両指数の短期回帰一致",
    15: "板・最良気配中心の短期傾き",
    16: "板・数量加重気配の短期傾き",
    17: "板・注文フロー10分と30分",
    18: "板・15分約定方向推定出来高",
    19: "板・10分売買気配更新方向",
    20: "板・10分最良数量の偏り",
    21: "板・10分５段数量の偏り",
    22: "板・注文フローの累積変化点",
    23: "混合・価格と約定方向推定出来高",
    24: "混合・両指数短期方向と気配フロー",
}


def _regression(series: pd.Series, window: int) -> tuple[pd.Series, pd.Series]:
    """機能: 確定終値の回帰による期間変位と決定係数を計算する。

    引数: series (Series) は価格、window (int) は分数。
    返り値: 期間変位と決定係数 (tuple[Series, Series])。
    """
    x = np.arange(window, dtype=float) - (window - 1) / 2
    denominator = float(np.dot(x, x))
    displacement = series.rolling(window).apply(
        lambda values: np.dot(x, values) / denominator * (window - 1), raw=True
    )
    determination = series.rolling(window).apply(
        lambda values: np.dot(x, values - values.mean()) ** 2 /
        (denominator * np.dot(values - values.mean(), values - values.mean()))
        if np.ptp(values) else 0.0,
        raw=True,
    )
    return displacement, determination


def _adaptive_average(close: pd.Series, efficiency: pd.Series) -> pd.Series:
    """機能: 方向効率に応じて平滑化速度が変わる適応移動平均を作る。

    引数: close (Series) は価格、efficiency (Series) は０〜１の方向効率。
    返り値: 過去情報のみを使う適応移動平均 (Series)。
    """
    smooth = (efficiency.fillna(0) * (2 / 3 - 2 / 31) + 2 / 31) ** 2
    values = close.to_numpy(dtype=float)
    output = np.full(len(values), np.nan)
    previous = np.nan
    for position, (value, factor) in enumerate(zip(values, smooth)):
        if np.isfinite(value):
            previous = value if not np.isfinite(previous) else previous + factor * (value - previous)
        output[position] = previous
    return pd.Series(output, index=close.index)


def _ratio(numerator: pd.Series, denominator: pd.Series, window: int) -> pd.Series:
    """機能: 分子と分母を別々に合算して、期間内のフロー比率を作る。

    引数: numerator/denominator (Series)、window (int) は集計分数。
    返り値: 分母ゼロを欠測とする比率 (Series)。
    """
    minimum = max(3, window // 2)
    return numerator.fillna(0).rolling(window, min_periods=minimum).sum() / denominator.fillna(0).rolling(
        window, min_periods=minimum
    ).sum().replace(0, np.nan)


def build_features(
    one: pd.DataFrame,
    five: pd.DataFrame,
    book_path: Path | None,
    tick: float,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """機能: 共通確定時刻までの足と生板由来特徴を１分格子にそろえる。

    引数: one/five (DataFrame) は開始時刻を索引とする確定足、
    book_path (Path | None) は既存の利用可能時刻付き板特徴、tick (float) は呼値、
    end (Timestamp) は両銘柄に共通する確定済み最終１分足の開始時刻。
    返り値: その分の終了後に参照可能となる特徴 (DataFrame)。
    無約定分の価格は引き継ぐが、売買の実行可能性とは区別する。
    """
    if one.empty or tick <= 0:
        raise ValueError("確定１分足と正の呼値が必要です")
    one = one.loc[one.index <= end].sort_index().copy()
    five = five.loc[five.index + pd.Timedelta(minutes=4) <= end].sort_index().copy()
    if one.empty or one.index.duplicated().any() or five.index.duplicated().any():
        raise ValueError("対象時刻までの足が空、または時刻が重複しています")
    first = one.index[0]
    if first.hour >= 17:
        start = first.normalize() + pd.Timedelta(hours=17)
    elif first.hour < 6:
        start = first.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=17)
    else:
        start = first.normalize() + pd.Timedelta(hours=8, minutes=45)
    index = pd.date_range(start, end, freq="min")
    z = one.reindex(index)
    for column in ("open", "high", "low", "close", "volume"):
        z[column] = z[column].astype(float)
    for column in ("closed", "volumeComplete", "volume_complete"):
        if column in z:
            z[column] = z[column].eq(True)
    z["observed"] = z.close.notna()
    z["close"] = z.close.ffill()
    z["volume"] = z.volume.fillna(0)
    seen = pd.Series(pd.NaT, index=index, dtype=index.dtype)
    seen.loc[one.index] = one.index
    z["stale_minutes"] = (index.to_series() - seen.ffill()).dt.total_seconds() / 60
    z["age"] = np.arange(len(z))
    z["tick"] = float(tick)

    # ----------------------------------------
    # ５分足は開始から４分目の１分足が確定した時だけ利用する。
    true_range = pd.concat([
        five.high - five.low,
        (five.high - five.close.shift()).abs(),
        (five.low - five.close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1 / 12, adjust=False, min_periods=3).mean().clip(lower=2 * tick)
    atr.index += pd.Timedelta(minutes=4)
    z["atr"] = atr.reindex(index, method="ffill")
    up, down = five.high.diff(), -five.low.diff()
    plus = up.where((up > down) & (up > 0), 0).ewm(span=4, adjust=False, min_periods=3).mean()
    minus = down.where((down > up) & (down > 0), 0).ewm(span=4, adjust=False, min_periods=3).mean()
    direction = (plus - minus) / (plus + minus).replace(0, np.nan)
    direction.index += pd.Timedelta(minutes=4)
    z["di20"] = direction.reindex(index, method="ffill")

    # ----------------------------------------
    # １分格子の価格特徴を作る。追加した未来行で過去値を変化させない。
    close = z.close
    for window in (3, 5, 8, 10, 15, 20, 30, 40):
        z[f"ema{window}"] = close.ewm(span=window, adjust=False, min_periods=min(window, 15)).mean()
    z["gap20"] = (z.ema5 - z.ema20) / z.atr
    z["gap40"] = (z.ema8 - z.ema40) / z.atr
    z["slope5"] = z.ema5.diff(5) / z.atr
    z["slope8"] = z.ema8.diff(5) / z.atr
    for window in (5, 10, 15, 20, 30, 40):
        z[f"move{window}"] = (close - close.shift(window)) / z.atr
    z["delta_atr"] = close.diff() / z.atr
    for window in (15, 30):
        change, determination = _regression(close, window)
        z[f"reg{window}"] = change / z.atr
        z[f"r2_{window}"] = determination
    z["er20"] = (close - close.shift(20)).abs() / close.diff().abs().rolling(20).sum().replace(0, np.nan)
    z["prior_high20"] = z.high.rolling(20, min_periods=10).max().shift()
    z["prior_low20"] = z.low.rolling(20, min_periods=10).min().shift()
    gain = close.diff().clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=10).mean()
    loss = -close.diff().clip(upper=0).ewm(alpha=1 / 14, adjust=False, min_periods=10).mean()
    z["rsi14"] = 100 * gain / (gain + loss).replace(0, np.nan)
    z["vwap"] = (close * z.volume).cumsum() / z.volume.cumsum().replace(0, np.nan)
    z["vwap_gap"] = (close - z.vwap) / z.atr
    z["vwap_slope"] = z.vwap.diff(10) / z.atr
    z["kama"] = _adaptive_average(close, z.er20)
    z["kama_gap"] = (close - z.kama) / z.atr
    z["kama_slope"] = z.kama.diff(5) / z.atr

    # ----------------------------------------
    # 生板特徴の time は確定利用時刻の属する１分の開始時刻。
    z["book_present"] = False
    if book_path is None or not Path(book_path).exists():
        return z
    board = pd.read_csv(book_path)
    board["time"] = pd.to_datetime(board.time)
    board["available_at"] = pd.to_datetime(board.available_at)
    if board.time.duplicated().any():
        raise ValueError("板特徴の時刻が重複しています")
    if (board.available_at > board.time + pd.Timedelta(minutes=1)).any():
        raise ValueError("板特徴の利用可能時刻が１分足確定より後です")
    board = board.set_index("time").sort_index().reindex(index)
    events = board.event_count.fillna(0)
    z["book_present"] = events.rolling(5, min_periods=1).sum().gt(0)
    for original, prefix in (("book_mid_last", "mid"), ("microprice_last", "micro")):
        values = board[original].ffill(limit=5)
        z[f"{prefix}_gap"] = (
            values.ewm(span=3, adjust=False, min_periods=3).mean() -
            values.ewm(span=15, adjust=False, min_periods=10).mean()
        ) / z.atr
        z[f"{prefix}_move10"] = values.diff(10) / z.atr
    for window in (5, 10, 30):
        z[f"ofi{window}"] = _ratio(board.ofi_sum, board.ofi_abs_sum, window)
    z["ofi1"] = board.ofi_sum / board.ofi_abs_sum.replace(0, np.nan)
    z["signed15"] = _ratio(board.signed_volume, board.volume_delta, 15)
    ups = board.bid_up.fillna(0) + board.ask_up.fillna(0)
    downs = board.bid_down.fillna(0) + board.ask_down.fillna(0)
    z["quote10"] = _ratio(ups - downs, ups + downs, 10)
    # 板更新数が多い１分を過剰に重視しないよう、１分平均を時間平均する。
    z["imbalance1_10"] = board.imbalance1_mean.rolling(10, min_periods=5).mean()
    z["imbalance5_10"] = board.imbalance5_mean.rolling(10, min_periods=5).mean()
    return z


def _threshold(value: pd.Series, magnitude: float, condition: pd.Series | None = None) -> pd.Series:
    """機能: 対称閾値を超えた符号だけを新規方向として残す。

    引数: value (Series)、magnitude (float)、condition (Series | None) は追加条件。
    返り値: −１、０、＋１の方向 (Series)。
    """
    valid = value.abs().ge(magnitude)
    if condition is not None:
        valid &= condition.fillna(False)
    return np.sign(value).where(valid, 0).fillna(0)


def _cusum(values: pd.Series, limit: float, drift: float, valid: pd.Series) -> pd.Series:
    """機能: 逐次の正負累積和が閾値を超えた最新方向を保持する。

    引数: values (Series) は差分、limit/drift (float) は閾値と微小変動控除、
    valid (Series) はその時刻の利用可否。
    返り値: 反対側累積和が成立するまで続く方向 (Series)。
    """
    positive, negative, side = 0.0, 0.0, 0
    output = np.zeros(len(values), dtype=np.int8)
    for position, (value, usable) in enumerate(zip(values.to_numpy(), valid.to_numpy())):
        if usable and np.isfinite(value):
            positive = max(0.0, positive + value - drift)
            negative = min(0.0, negative + value + drift)
            if positive >= limit:
                side, positive, negative = 1, 0.0, 0.0
            elif negative <= -limit:
                side, positive, negative = -1, 0.0, 0.0
        output[position] = side
    return pd.Series(output, index=values.index)


def _directional_change(z: pd.DataFrame, multiple: float, valid: pd.Series) -> pd.Series:
    """機能: 過去の確定終値極値から一定ATRの反発・反落を検知する。

    引数: z (DataFrame) は価格特徴、multiple (float) は反転幅、valid (Series) は利用可否。
    返り値: 将来の極値確認を使わない方向状態 (Series)。
    """
    high, low, side = np.nan, np.nan, 0
    output = np.zeros(len(z), dtype=np.int8)
    for position, (close, atr, usable) in enumerate(zip(z.close, z.atr, valid)):
        if usable and np.isfinite(close) and np.isfinite(atr):
            if not np.isfinite(high):
                high = low = close
            high, low = max(high, close), min(low, close)
            width = multiple * atr
            if side <= 0 and close >= low + width:
                side, high = 1, close
            elif side >= 0 and close <= high - width:
                side, low = -1, close
        output[position] = side
    return pd.Series(output, index=z.index)


def get_signals(z: pd.DataFrame, peer: pd.DataFrame, family: int, param: float) -> pd.Series:
    """機能: 24個の独立仮説からロング・中立・ショートの新規許可を作る。

    引数: z/peer (DataFrame) は共通確定時刻までの特徴、family (int) は系統番号、
    param (float) は標準感度倍率で、0.75・1.0・1.25を想定する。
    返り値: １分の確定後に参照できる−１、０、＋１の方向 (Series)。
    この方向の消滅自体は返済指示ではなく、返済は別のトレーリング処理が扱う。
    """
    if family not in FAMILIES or param <= 0:
        raise ValueError("系統番号または感度倍率が不正です")
    p = peer.reindex(z.index)
    valid = z.age.ge(14) & z.atr.notna() & z.stale_minutes.le(10)
    peer_valid = p.stale_minutes.le(10) & p.atr.notna()

    # ----------------------------------------
    # 価格と他指数の仮説。
    if family == 1:
        signal = _threshold(z.gap20, 0.20 * param, z.gap20 * z.slope5 > 0)
    elif family == 2:
        signal = _threshold(z.gap40, 0.30 * param, z.gap40 * z.slope8 > 0)
    elif family == 3:
        signal = _threshold(z.reg15, 0.60 * param, z.r2_15.ge(0.25))
    elif family == 4:
        signal = _threshold(z.reg30, 0.80 * param, z.r2_30.ge(0.25))
    elif family == 5:
        signal = _threshold(z.move20, 0.70 * param, z.er20.ge(0.22))
    elif family == 6:
        upside = z.close.ge(z.prior_high20 + 0.05 * param * z.atr)
        downside = z.close.le(z.prior_low20 - 0.05 * param * z.atr)
        signal = upside.astype(float) - downside.astype(float)
        signal = signal.where(z.move10.abs().ge(0.35 * param), 0)
    elif family == 7:
        signal = _threshold(z.di20, 0.22 * param, z.di20 * z.move10 > 0)
    elif family == 8:
        signal = _threshold(z.vwap_gap, 0.60 * param, z.vwap_gap * z.vwap_slope > 0)
    elif family == 9:
        signal = _cusum(z.delta_atr, 0.85 * param, 0.025, valid)
    elif family == 10:
        signal = _directional_change(z, 1.25 * param, valid)
    elif family == 11:
        signal = _threshold(z.rsi14 - 50, 8 * param, (z.rsi14 - 50) * z.move10 > 0)
    elif family == 12:
        signal = _threshold(z.kama_gap, 0.65 * param, z.kama_gap * z.kama_slope > 0)
    elif family == 13:
        signal = _threshold(z.move20, 0.60 * param, (z.move20 * z.move40 > 0) & z.move40.abs().ge(0.80 * param))
    elif family == 14:
        signal = _threshold(z.reg15, 0.50 * param, z.r2_15.ge(0.20) & p.r2_15.ge(0.20) &
                            (z.reg15 * p.reg15 > 0) & peer_valid)

    # ----------------------------------------
    # 生板由来の仮説。板欠損の場合、価格で代替せず中立にする。
    elif not z.book_present.any():
        return pd.Series(0, index=z.index, dtype=np.int8)
    elif family == 15:
        signal = _threshold(z.mid_gap, 0.20 * param, z.mid_gap * z.mid_move10 > 0)
    elif family == 16:
        signal = _threshold(z.micro_gap, 0.20 * param, z.micro_gap * z.micro_move10 > 0)
    elif family == 17:
        signal = _threshold(z.ofi10, 0.06 * param, z.ofi10 * z.ofi30 > 0)
    elif family == 18:
        signal = _threshold(z.signed15, 0.20 * param)
    elif family == 19:
        signal = _threshold(z.quote10, 0.06 * param)
    elif family == 20:
        signal = _threshold(z.imbalance1_10, 0.10 * param)
    elif family == 21:
        signal = _threshold(z.imbalance5_10, 0.10 * param)
    elif family == 22:
        signal = _cusum(z.ofi1, 0.45 * param, 0.025, valid & z.book_present)
    elif family == 23:
        signal = _threshold(z.gap20, 0.20 * param, (z.gap20 * z.signed15 > 0) & z.signed15.abs().ge(0.12 * param))
    else:
        board_direction = z.ofi10 / 0.06 + z.quote10 / 0.06
        signal = _threshold(z.reg15, 0.50 * param, (z.reg15 * p.reg15 > 0) &
                            (z.reg15 * board_direction > 0) & z.r2_15.ge(0.20) & peer_valid)
    if family >= 15:
        valid &= z.book_present
    return signal.replace([np.inf, -np.inf], np.nan).fillna(0).where(valid, 0).astype(np.int8)
