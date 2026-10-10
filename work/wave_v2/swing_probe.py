"""平滑価格の押し戻し幅で長い波を保つ補助探索。現在データは使わない。"""

import itertools

import numpy as np
import pandas as pd

import research_v2 as r


def swing(z: pd.DataFrame, multiple: float, smoothing: int) -> pd.Series:
    """機能: 平滑価格の極値から一定ATR逆行したときだけ方向を変更する。

    引数: z (DataFrame)、multiple (float)、smoothing (int)。返り値: 方向 (Series)。
    """
    smoothed = z.close.ewm(span=smoothing, adjust=False).mean().to_numpy()
    atr = z.atr.to_numpy()
    result = np.zeros(len(z))
    side, low, high = 0, None, None
    for i, price in enumerate(smoothed):
        if i<30 or not np.isfinite(atr[i]):
            continue
        if low is None:
            low = high = price
        width = multiple*atr[i]
        if side==0:
            low, high = min(low, price), max(high, price)
            if price-low>=width:
                side, high = 1, price
            elif high-price>=width:
                side, low = -1, price
        elif side==1:
            high = max(high, price)
            if high-price>=width:
                side, low = -1, price
        else:
            low = min(low, price)
            if price-low>=width:
                side, high = 1, price
        result[i] = side
    return pd.Series(result, index=z.index)


def main() -> None:
    """機能: 反転幅と平滑時間を保存６系列で比較する。

    引数: なし。返り値: なし (None)。
    """
    data = r.load_data()
    rows = []
    for k, smooth, trail in itertools.product((1, 1.5, 2, 2.5, 3, 4), (3, 5, 10, 15), (4, 6)):
        for (session, symbol), (one, z) in data.items():
            cfg = r.Config(5, 0.5, 1, trail, 1)
            trades = r.simulate(one, z, swing(z, k, smooth), cfg, symbol, session)
            targets = r.target_metrics(one, trades, symbol, session)
            rows.append(dict(k=k, smoothing=smooth, trail=trail, session=session, symbol=symbol,
                             count=len(trades), net_points=sum(t.get("net_points", 0) for t in trades),
                             stress_points=sum(t.get("stress_points", 0) for t in trades),
                             passed=sum(t["passed"] for t in targets),
                             capture=targets[0]["capture_ratio"] if targets else None,
                             coverage=targets[0]["correct_coverage"] if targets else None,
                             delay=targets[0]["detection_delay_min"] if targets else None))
    df = pd.DataFrame(rows)
    df.to_csv(r.OUT/"反転幅探索.csv", index=False, encoding="utf-8-sig")
    result = df.groupby(["k", "smoothing", "trail", "symbol"]).agg(passed=("passed", "sum"),
                min_count=("count", "min"), max_count=("count", "max"), net=("net_points", "sum"),
                stress=("stress_points", "sum"), capture=("capture", "min"), coverage=("coverage", "min"))
    print(result[result.passed.eq(2)&result.max_count.le(6)].sort_values(["symbol", "stress"], ascending=[True, False]).head(30).to_string())


if __name__ == "__main__":
    main()
