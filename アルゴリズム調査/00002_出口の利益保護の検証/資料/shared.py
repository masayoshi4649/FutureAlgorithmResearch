"""保存版の足と方法①の固定入口を、出口だけの比較へ読み込む。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
ARCHIVE = ROOT / "アルゴリズム調査" / "保存版"
V4 = ARCHIVE / "work" / "wave_v4"
V5 = ARCHIVE / "work" / "wave_v5"
sys.path.insert(0, str(V4))
sys.path.insert(0, str(V5))
sys.path.insert(0, str(OUT))
sys.dont_write_bytecode = True

from engine import TICKS, prepare, sign_schedule
from exits import ConfigV5
from signals import build_features, get_signals


SYMBOLS = ("NK225", "TOPIX")
MULTIPLIERS = {"NK225": 1000, "TOPIX": 10000}
SESSIONS = ("2026-09-21_Day", "2026-09-21_Night", "2026-09-22_Day", "2026-09-22_Night", "2026-09-23_Day")


def normalize(value: object) -> object:
    """機能: 配列数値と日時を日本語JSONに保存できる標準型へ変換する。

    引数: value (object) は変換する値。
    返り値: JSON互換値 (object)。浮動小数点値は丸めない。
    """
    if isinstance(value, pd.Timestamp):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    return value


def save_json(path: Path, value: object) -> None:
    """機能: 非数を許可せず日本語JSONを保存する。

    引数: path (Path) は出力先、value (object) は保存内容。
    返り値: なし (None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalize(value), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def load_inputs() -> tuple[dict, dict, ConfigV5, dict]:
    """機能: 保存済み20足のハッシュを照合し、両銘柄５セッションを準備する。

    引数: なし。
    返り値: 再生入力・方向列・固定入口設定・保存主候補 (tuple[dict,dict,ConfigV5,dict])。
    生板や現在APIには接続せず、自銘柄価格を使う方法①だけを読み込む。
    """
    primary = json.loads((V5 / "方向主候補.json").read_text(encoding="utf-8"))
    audit = json.loads((V5 / "データ監査.json").read_text(encoding="utf-8"))
    checks = []
    for name, expected in audit["source_sha256"].items():
        path = name.replace("\\", "/")
        if not path.startswith(("candle_1min/", "candle_5min/")):
            continue
        actual = hashlib.sha256((ARCHIVE / path).read_bytes()).hexdigest()
        checks.append(dict(ファイル=path, 一致=actual == expected, SHA256=actual))
    assert len(checks) == 20 and all(row["一致"] for row in checks)
    cfg = ConfigV5(**primary["config"])
    data, schedules = {}, {}
    for session in SESSIONS:
        frames = {}
        for symbol in SYMBOLS:
            parts = []
            for minutes in (1, 5):
                frame = pd.read_csv(ARCHIVE / f"candle_{minutes}min" / symbol / f"{session}.csv")
                frame["time"] = pd.to_datetime(frame.time)
                frame = frame[frame.closed.astype(str).str.lower().eq("true")].set_index("time").sort_index()
                assert not frame.index.duplicated().any()
                parts.append(frame)
            frames[symbol] = parts
        end = max(one.index[-1] for one, five in frames.values())
        for symbol, (one, five) in frames.items():
            z = build_features(one, five, None, TICKS[symbol], end)
            key = (session, symbol)
            data[key] = prepare(one, z, symbol, session)
            schedules[key] = sign_schedule(get_signals(z, z, cfg.family, cfg.param).to_numpy())
    save_json(OUT / "入力照合.json", dict(保存足=checks, 現在API取得=False, 固定入口=primary["config"]))
    return data, schedules, cfg, primary
