"""注文だけの仮説を、固定乱数と整合した反転価格経路で検査する。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd


DIRECTION_SEEDS = tuple(range(260923000, 260923100))
PATH_SEEDS = tuple(range(260924000, 260924100))


def random_directions(index: pd.DatetimeIndex, seed: int, cadence_min: int = 30) -> pd.Series:
    """機能: 過去価格に依存せず、一定時間ごとに公平な方向を生成する。

    引数: index (DatetimeIndex) は判定グリッド、seed (int) は固定乱数種、
        cadence_min (int) は方向を保持する分数。
    返り値: 各時刻の -1 または 1 の方向 (Series)。
    """
    if cadence_min < 1:
        raise ValueError("方向更新の間隔は１分以上が必要です。")
    if not len(index):
        return pd.Series(dtype=float, index=index)
    block = np.asarray((index - index[0]).total_seconds() // (60 * cadence_min), dtype=int)
    draws = np.random.default_rng(seed).choice(np.array([-1.0, 1.0]), size=int(block.max()) + 1)
    return pd.Series(draws[block], index=index)


def reflect_paths(
    candles: dict[tuple[str, str], pd.DataFrame], seed: int
) -> dict[tuple[str, str], pd.DataFrame]:
    """機能: 各１分足のギャップと足内部を同じ符号で無作為に反転する。

    引数: candles (dict[tuple[str, str], DataFrame]) はセッション・銘柄別の１分足、
        seed (int) は固定乱数種。
    返り値: OHLC とギャップの整合を守った新しい１分足辞書 (dict)。入力は変更しない。
    """
    timestamps = sorted({stamp for one in candles.values() for stamp in one.index})
    signs = np.random.default_rng(seed).choice(np.array([-1.0, 1.0]), size=len(timestamps))
    common = pd.Series(signs, index=pd.DatetimeIndex(timestamps))
    result = {}
    for key, one in sorted(candles.items()):
        if one.empty:
            result[key] = one.copy(deep=True)
            continue
        mirror = common.reindex(one.index).to_numpy(dtype=float)
        opening = one.open.to_numpy(dtype=float)
        high = one.high.to_numpy(dtype=float)
        low = one.low.to_numpy(dtype=float)
        closing = one.close.to_numpy(dtype=float)
        previous = np.concatenate(([opening[0]], closing[:-1]))
        new_close = opening[0] + np.cumsum(mirror * (closing - previous))
        new_open = new_close - mirror * (closing - opening)
        upward = mirror * (high - opening)
        downward = mirror * (low - opening)
        transformed = one.copy(deep=True)
        transformed["open"] = np.round(new_open, 10)
        transformed["high"] = np.round(new_open + np.maximum(upward, downward), 10)
        transformed["low"] = np.round(new_open + np.minimum(upward, downward), 10)
        transformed["close"] = np.round(new_close, 10)
        result[key] = transformed
    return result


def rebuild_five(one: pd.DataFrame) -> pd.DataFrame:
    """機能: 反転後の１分足のみから、確定済み５分足を組み立てる。

    引数: one (DataFrame) は時刻索引と OHLCV を持つ確定済み１分足。
    返り値: 終端の未確定区間を除いた５分足 (DataFrame)。
    """
    if one.empty:
        return one.copy(deep=True)
    aggregate = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "volume_complete" in one:
        aggregate["volume_complete"] = "all"
    five = one.resample("5min", label="left", closed="left").agg(aggregate).dropna(subset=["open", "close"])
    five = five[five.index + pd.Timedelta(minutes=5) <= one.index[-1] + pd.Timedelta(minutes=1)].copy()
    five["closed"] = True
    return five


def summarize_runs(
    samples: list[dict[str, Any]], observed: dict[str, float] | None = None
) -> list[dict[str, Any]]:
    """機能: 同じ市場期間で生じた乱数間の損益分布を銘柄別にまとめる。

    引数: samples (list[dict]) は symbol/seed/net_points/count の一覧、
        observed (dict[str, float] | None) は比較する固定条件の銘柄別損益。
    返り値: 百分位、利益割合、種間ばらつきと参考順位の一覧 (list[dict])。
    """
    frame = pd.DataFrame(samples)
    if frame.empty:
        return []
    result = []
    for symbol, rows in frame.groupby("symbol", sort=True):
        totals = rows.groupby("seed", sort=True).agg(net_points=("net_points", "sum"), count=("count", "sum"))
        values = totals.net_points.to_numpy(dtype=float)
        count = totals["count"].to_numpy(dtype=float)
        value = dict(
            symbol=str(symbol),
            seed_count=len(values),
            mean=float(values.mean()),
            median=float(np.median(values)),
            percentile_05=float(np.quantile(values, 0.05)),
            percentile_95=float(np.quantile(values, 0.95)),
            minimum=float(values.min()),
            maximum=float(values.max()),
            standard_deviation_between_seeds=float(values.std(ddof=1)) if len(values) > 1 else 0.0,
            monte_carlo_standard_error=float(values.std(ddof=1) / np.sqrt(len(values))) if len(values) > 1 else 0.0,
            profitable_seed_fraction=float((values > 0).mean()),
            mean_count=float(count.mean()),
            mean_points_per_trade=float(values.sum() / count.sum()) if count.sum() else None,
            zero_trade_seed_count=int((count == 0).sum()),
            zero_trade_cell_fraction=float((rows["count"] == 0).mean()),
            scope="同じ保存期間での乱数のばらつき。独立した市場期間の信頼区間ではない。",
        )
        if observed is not None and symbol in observed:
            actual = float(observed[symbol])
            value["observed_net_points"] = actual
            value["at_least_observed_count"] = int((values >= actual).sum())
            value["reference_rank_fraction"] = float((1 + (values >= actual).sum()) / (1 + len(values)))
            value["selection_bias_note"] = "探索後に選んだ１条件の参考比較であり、全探索の多重比較は補正していない。"
        result.append(value)
    return result


def run_direction_baseline(
    evaluate_seed: Callable[[int], list[dict[str, Any]]],
    observed: dict[str, float] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """機能: 事前固定した 100 種を全て実行し、無作為方向の基準を集計する。

    引数: evaluate_seed (Callable[[int], list[dict]]) は種を受けて銘柄・セル集計を返す関数、
        observed (dict[str, float] | None) は実データの比較損益。
    返り値: 全種のセル集計と分布の要約 (tuple[list[dict], list[dict]])。
    """
    samples = []
    for seed in DIRECTION_SEEDS:
        for row in evaluate_seed(seed):
            samples.append(dict(row, seed=seed))
    return samples, summarize_runs(samples, observed)


def run_path_baseline(
    candles: dict[tuple[str, str], pd.DataFrame],
    evaluate_candles: Callable[[dict[tuple[str, str], pd.DataFrame]], list[dict[str, Any]]],
    observed: dict[str, float] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """機能: 事前固定した 100 種の反転価格経路を同じ固定条件で評価する。

    引数: candles (dict) は元１分足、evaluate_candles (Callable) は再構築足を評価する関数、
        observed (dict[str, float] | None) は同じ５分足再構築を用いた実価格の損益。
    返り値: 全経路のセル集計と分布の要約 (tuple[list[dict], list[dict]])。
    """
    samples = []
    for seed in PATH_SEEDS:
        for row in evaluate_candles(reflect_paths(candles, seed)):
            samples.append(dict(row, seed=seed))
    return samples, summarize_runs(samples, observed)
