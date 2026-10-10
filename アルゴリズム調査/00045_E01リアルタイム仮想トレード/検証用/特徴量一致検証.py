"""保存された追加デイで、実行版の特徴量を既存研究実装と照合する。"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
SESSION = "2026-10-01_Day"
sys.dont_write_bytecode = True
sys.path.insert(0, str(TASK))
sys.path.insert(0, str(ROOT / "work/wave_v35"))
sys.path.insert(0, str(ROOT / "work/wave_v47"))

from papertrade.features import FeatureEngine, timestamp
import deterioration_signals as old_mid
import component_signals as old_entry


def sha256(path: Path) -> str:
    """機能: 検証対象と参照資料の内容指紋を求める。

    引数: path(Path) は入力ファイル。返り値: SHA256文字列(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> dict:
    """機能: 同一の研究時計で指標と公開イベント方向を照合し証跡を保存する。

    引数: なし。返り値: 比較件数と一致証跡(dict)。
    通信は使わず、保存済み入力を読み取る。実売買APIは参照しない。
    この検証だけは研究用NumPy・pandas・Numbaと既存workを使用する。
    """
    folder = ROOT / "work/wave_v50/update_20261001_day"
    input_path, feature_path = folder / "new_inputs.pkl", folder / "new_features_depth.pkl"
    inputs = pickle.loads(input_path.read_bytes())
    features = pickle.loads(feature_path.read_bytes())
    engine = FeatureEngine(SESSION, next(iter(inputs.values()))["start"])
    source_paths = [input_path, feature_path, TASK / "papertrade/features.py", Path(__file__),
                    ROOT / "work/wave_v35/deterioration_signals.py",
                    ROOT / "work/wave_v47/component_signals.py",
                    ROOT / "work/wave_v27/hierarchy_signals.py",
                    ROOT / "work/wave_v27/hierarchy_design_fixed.json",
                    ROOT / "work/wave_v23/signals.py"]
    counts = {}
    for key, ready in inputs.items():
        symbol = key[1]
        for interval, name in ((300, "candle_5min"), (60, "candle_1min")):
            path = ROOT / name / symbol / (SESSION + ".csv")
            source_paths.append(path)
            with path.open(encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    row["closed"] = row["closed"].lower() == "true"
                    engine.ingest_candles(symbol, interval, [row], timestamp(row["time"]) + interval)
        model = engine._model(symbol)
        atr_times = np.array([value["nominal"] for value in model["atr"]])
        atr_values = np.array([np.nan if value["value"] is None else value["value"] for value in model["atr"]])
        positions = np.searchsorted(atr_times, ready["time_s"], side="right") - 1
        actual = np.where(positions >= 0, atr_values[np.maximum(positions, 0)], np.nan)
        np.testing.assert_allclose(actual, ready["atr"], rtol=1e-12, atol=1e-9, equal_nan=True)
        rows = sorted(engine.markets[symbol]["bars"]["60"].values(), key=lambda value: value["time"])
        closes = pd.Series([row["close"] for row in rows])
        for span, field in ((15, "fast"), (60, "slow")):
            expected = closes.ewm(span=span, adjust=False, min_periods=span).mean()
            actual = [np.nan if row[field] is None else row[field] for row in model["main"]]
            np.testing.assert_allclose(actual, expected, rtol=1e-12, equal_nan=True)
        counts[symbol] = {"価格行数": len(ready["time_s"]), "確定1分足数": len(rows),
                          "ATR全行一致": True, "EMA15とEMA60全足一致": True}
    # ----------------------------------------
    # 旧公開特徴に同じ時計を与え、入口H019と途中根拠B00を別実装で照合する。
    reference_mid = old_mid.build(old_mid.catalog()[0], inputs, features)
    reference_entry = old_entry.build(old_entry.specification(), inputs, features)
    for key, ready in inputs.items():
        symbol, frame = key[1], features[key]
        for event in frame.itertuples(index=False):
            raw_index = int(np.searchsorted(ready["seq"], event.seq))
            indicator = engine.snapshot(symbol, event.time_s)
            engine._release(symbol, event.time_s,
                {"time": float(event.source_time_s), "mid": float(event.source_mid_last)}, raw_index, indicator)
            actual = engine.markets[symbol]
            if actual["adverse"] != int(reference_mid[key]["direction"][raw_index]):
                raise AssertionError((symbol, raw_index, "B00不一致"))
            if actual["direction"] != int(reference_entry[key][raw_index]):
                raise AssertionError((symbol, raw_index, "H019不一致"))
        counts[symbol].update({"公開イベント数": len(frame), "B00不一致数": 0, "H019不一致数": 0})
    proof = {"対象": SESSION, "銘柄": counts, "全一致": True, "現在APIアクセス数": 0,
             "時計": "研究と同じCurrentPriceTime代理時計。足は確定時受信、利用は終了後60秒以降。",
             "適用限界": "実運用では実受信時計を使う。遅延・断線・開始途中の暖機による売買時刻差まで一致とは主張しない。",
             "再現コマンド": "python -X utf8 検証用/特徴量一致検証.py",
             "入力と実装SHA256": {str(path.relative_to(ROOT)): sha256(path) for path in source_paths}}
    (TASK / "特徴量一致検証.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    return proof


if __name__ == "__main__":
    result = main()
    print(json.dumps({"全一致": result["全一致"], "銘柄": result["銘柄"]}, ensure_ascii=False))
