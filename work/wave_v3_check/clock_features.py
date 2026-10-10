"""凍結済み検知条件を保ち、価格特徴量の観測終端を明示する前処理。"""

from pathlib import Path
import sys

import pandas as pd


OLD = Path(__file__).resolve().parent.parent / "wave_v2"
sys.path.insert(0, str(OLD))
import research_v2 as r


def price_features_until(one: pd.DataFrame, five: pd.DataFrame, tick: float,
                         end: pd.Timestamp) -> pd.DataFrame:
    """機能: 共通の観測終端まで既知価格を持ち越し、銘柄間の時刻軸を一致させる。

    引数: one/five (DataFrame) は確定した実在足、tick (float) は最小価格刻み。
    end (Timestamp) は最後に確定した一分区間の開始時刻。例えば04:00締切なら03:59を渡す。
    返り値: 共通終端までの特徴量 (DataFrame)。無約定分のobservedは偽、stale_minutesは経過分数。

    仮の終端行は特徴量計算だけに使い、約定用の実在足へ追加しない。
    既知終値の持ち越しと出来高ゼロの扱いは元検知器と同じで、検知閾値や取引条件を変えない。
    取引再生へは入力のoneそのものを渡すこと。終端に約定があったと仮定しない。
    """
    if end < one.index[-1]:
        raise ValueError("観測終端が実在足より前です")
    extended = one.reindex(one.index.union(pd.DatetimeIndex([end])))
    z = r.price_features(extended, five, tick)
    seen = pd.Series(pd.NaT, index=z.index, dtype=z.index.dtype)
    seen.loc[one.index] = one.index
    z["stale_minutes"] = (z.index.to_series() - seen.ffill()).dt.total_seconds() / 60
    z["observed"] = z.index.isin(one.index)
    return z
