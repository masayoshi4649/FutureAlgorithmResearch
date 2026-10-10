"""確定五分足のATRを独立した逐次式で再計算し、全生板時点と照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
V8 = OUT.parent / "wave_v8"
sys.dont_write_bytecode = True
sys.path.insert(0, str(OUT))
import execution


def independent_atr(session: str, symbol: str, times: np.ndarray) -> tuple[np.ndarray, int]:
    """EWMAライブラリを使わず、確定足だけのATRを時間順に更新する。

    引数: session/symbol（str）対象識別子。times（ndarray）観測時刻のUnix秒。
    返り値: tuple[ndarray, int]。各時点の独立ATRと読み込んだ足数。
    """
    root = ROOT / "work/wave_v7/live" if session == "2026-09-23_Night" else ROOT
    candles = pd.read_csv(root / "candle_5min" / symbol / f"{session}.csv")
    candles = candles.loc[candles.closed.astype(str).str.lower().eq("true")].copy()
    candles["available"] = pd.to_datetime(candles.time).dt.as_unit("ns").astype("int64") / 1e9 + 360
    values = []
    previous_close = None
    state = None
    tick = 10.0 if symbol == "NK225" else 0.5
    for row in candles.itertuples(index=False):
        true_range = float(row.high - row.low)
        if previous_close is not None:
            true_range = max(true_range, abs(row.high - previous_close), abs(row.low - previous_close))
        state = true_range if state is None else (11.0 * state + true_range) / 12.0
        values.append(max(2 * tick, state) if len(values) >= 2 else np.nan)
        previous_close = float(row.close)
    available = candles.available.to_numpy(float)
    result = np.full(len(times), np.nan)
    cursor = -1
    for index, stamp in enumerate(times):
        while cursor + 1 < len(available) and available[cursor + 1] <= stamp:
            cursor += 1
        if cursor >= 0:
            result[index] = values[cursor]
    return result, len(candles)


def main() -> None:
    """全12系列の生板時点と、途中で足を切る場合のATRを検査する。

    引数: なし。
    返り値: None。監査JSONへ照合数・最大誤差を保存する。
    """
    code_hash = hashlib.sha256(Path(execution.__file__).read_bytes()).hexdigest()
    records = []
    for path in sorted((V8 / "features").glob("約定系列_*.npz")):
        symbol, session = path.stem.removeprefix("約定系列_").split("_", 1)
        with np.load(path) as tape:
            times = tape["time_s"]
        expected, candles = independent_atr(session, symbol, times)
        observed = execution.atr_at(session, symbol, times)
        np.testing.assert_allclose(observed, expected, atol=1e-10, rtol=1e-12, equal_nan=True)
        np.testing.assert_array_equal(np.isnan(observed), np.isnan(expected))
        cuts = []
        for fraction in (0.33337, 0.66671):
            count = int(len(times) * fraction)
            cutoff = float(times[count - 1])
            prefix = execution.atr_at(session, symbol, times[:count], cutoff=cutoff)
            np.testing.assert_array_equal(prefix, observed[:count])
            cuts.append(dict(生板行数=count, 足切断時刻=cutoff, 過去ATR完全一致=True))
        error = float(np.nanmax(np.abs(observed - expected)))
        records.append(dict(セッション=session, 銘柄=symbol, 五分足数=candles, 全生板照合行数=len(times),
                            有効ATR行数=int(np.isfinite(observed).sum()), 最大絶対誤差=error, 足打切り=cuts))
        print(f"ATR独立式一致: {session} {symbol} 最大誤差={error:g}", flush=True)
    result = dict(実装SHA256=code_hash, 監査中変更なし=code_hash == hashlib.sha256(Path(execution.__file__).read_bytes()).hexdigest(),
                  条件="5分足開始＋6分まで利用せず、TRをalpha=1/12で再帰平均。最低3本、下限2tick。", 結果=records,
                  全生板照合行数=sum(row["全生板照合行数"] for row in records),
                  最大絶対誤差=max(row["最大絶対誤差"] for row in records))
    (OUT / "ATR独立再計算監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert result["監査中変更なし"], "実装変更後の再監査が必要"


if __name__ == "__main__":
    main()
