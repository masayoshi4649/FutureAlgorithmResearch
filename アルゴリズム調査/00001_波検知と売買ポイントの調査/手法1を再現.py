"""凍結した足と実装だけで手法１を再生し、保存した全取引との一致を確認する。"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import platform
import sys

import numpy as np
import pandas as pd


BASE = Path(__file__).resolve().parent
ARCHIVE = BASE / "保存版"
V4 = ARCHIVE / "work" / "wave_v4"
V5 = ARCHIVE / "work" / "wave_v5"
OUTPUT = BASE / "再現確認"
sys.path.insert(0, str(V4))
sys.path.insert(0, str(V5))
sys.dont_write_bytecode = True

from engine import TICKS, prepare, sign_schedule
from exits import ConfigV5, simulate_exit
from signals import build_features, get_signals


def sha256(path: Path) -> str:
    """機能: ファイルを変更せずにＳＨＡ２５６を求める。

    引数: path (Path) は読み取るファイル。
    返り値: ハッシュの十六進表現 (str)。
    """
    state = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            state.update(block)
    return state.hexdigest()


def save_json(path: Path, value: object) -> None:
    """機能: 日本語を保持した厳密なＪＳＯＮを書き出す。

    引数: path (Path) は出力先、value (object) は保存する値。
    返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def normalize(value: object) -> object:
    """機能: 日時と配列の数値型だけを保存記録と同じ標準型へ変換する。

    引数: value (object) は比較対象の値。
    返り値: 日時を文字列、配列数値を標準数値に変換した値 (object)。数値は丸めない。
    """
    if isinstance(value, pd.Timestamp):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalize(item) for item in value]
    return value


def verify_candles(source_hashes: dict[str, str]) -> list[dict]:
    """機能: 保存された足２０ファイルの内容を元のデータ監査記録と照合する。

    引数: source_hashes (dict[str, str]) は調査時点の相対パスとハッシュ。
    返り値: 対象・期待値・実測値・一致結果の一覧 (list[dict])。
    """
    checks = []
    for original, expected in source_hashes.items():
        relative = original.replace("\\", "/")
        if relative.split("/")[0] not in ("candle_1min", "candle_5min"):
            continue
        path = ARCHIVE / relative
        actual = sha256(path) if path.is_file() else None
        checks.append({"ファイル": relative, "期待ＳＨＡ２５６": expected,
                       "実測ＳＨＡ２５６": actual, "一致": expected == actual})
    return checks


def read_candle(path: Path) -> pd.DataFrame:
    """機能: 保存版から確定済みの足だけを時刻順に読み込む。

    引数: path (Path) は足ＣＳＶ。
    返り値: 足の開始時刻を索引とする確定足 (DataFrame)。時刻重複はエラーとする。
    """
    frame = pd.read_csv(path)
    frame["time"] = pd.to_datetime(frame.time)
    frame = frame[frame.closed.astype(str).str.lower().eq("true")].set_index("time").sort_index()
    if frame.index.duplicated().any():
        raise ValueError(f"時刻が重複しています: {path}")
    return frame


def replay(config: dict, sessions: list[str]) -> list[dict]:
    """機能: 手法１だけを凍結された実装で再生する。

    引数: config (dict) は保存された主候補の条件、sessions (list[str]) は対象セッション。
    返り値: 全フィールドを保持した仮想取引 (list[dict])。
    価格累積和の手法１には板・相手銘柄の特徴を使わず、足だけから同じ結果を再現する。
    """
    cfg = ConfigV5(**config)
    if cfg.family != 9 or cfg.exit_mode != "nativebaseline":
        raise ValueError("手法１の価格累積和・従来返済設定だけを再生できます")
    trades = []
    for session in sessions:
        frames = {}
        for symbol in ("NK225", "TOPIX"):
            one = read_candle(ARCHIVE / "candle_1min" / symbol / f"{session}.csv")
            five = read_candle(ARCHIVE / "candle_5min" / symbol / f"{session}.csv")
            frames[symbol] = (one, five)
        end = max(one.index[-1] for one, five in frames.values())
        for symbol, (one, five) in frames.items():
            features = build_features(one, five, None, TICKS[symbol], end)
            data = prepare(one, features, symbol, session)
            values = get_signals(features, features, cfg.family, cfg.param).to_numpy()
            trades.extend(simulate_exit(data, sign_schedule(values), cfg))
    return normalize(trades)


def compare_trades(actual: list[dict], expected: list[dict]) -> list[dict]:
    """機能: 取引の順序・項目集合・全フィールドを数値の丸めなしで比較する。

    引数: actual (list[dict]) は再現取引、expected (list[dict]) は保存取引。
    返り値: 不一致の説明一覧 (list[dict])。完全一致なら空の一覧。
    """
    differences = []
    if len(actual) != len(expected):
        differences.append({"項目": "取引数", "再現": len(actual), "保存": len(expected)})
    for number, (got, prior) in enumerate(zip(actual, expected), start=1):
        for field in sorted(set(got) | set(prior)):
            if field not in got or field not in prior or got[field] != prior[field]:
                differences.append({"取引番号": number, "項目": field,
                                    "再現": got.get(field), "保存": prior.get(field)})
    return differences


def write_csv(trades: list[dict]) -> None:
    """機能: 再現した全取引を日本語列名のＣＳＶへ出力する。

    引数: trades (list[dict]) は再現取引。
    返り値: なし (None)。元の全フィールドとラージ１枚の円換算額を保存する。
    """
    labels = {
        "symbol": "銘柄", "session": "セッション", "config": "条件識別子", "side": "方向符号",
        "signal_time": "判定資料の確定時刻", "entry_time": "新規成立足の開始時刻",
        "entry_price": "新規価格", "atr": "注文準備時のＡＴＲ", "entry_method": "新規方式",
        "exit_time": "返済成立足の開始時刻", "exit_price": "返済価格", "closed": "返済済み",
        "duration_min": "保有分数", "gross_points": "費用控除前値幅", "reason": "返済理由",
        "ambiguous_entry": "新規足の順序不明", "net_points": "２ティック控除後値幅",
        "stress_points": "４ティック控除後値幅", "net_atr": "２ティック控除後ＡＴＲ比",
    }
    fields = list(dict.fromkeys(key for trade in trades for key in trade))
    unknown = set(fields) - set(labels)
    if unknown:
        raise ValueError(f"日本語列名が未定義です: {unknown}")
    columns = [labels[field] for field in fields] + ["売買方向", "２ティック控除後収支円", "４ティック控除後収支円"]
    with (OUTPUT / "手法1の全取引.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for trade in trades:
            multiple = 1000 if trade["symbol"] == "NK225" else 10000
            row = {labels[field]: trade[field] for field in fields}
            row.update({"売買方向": "買い" if trade["side"] == 1 else "売り",
                        "２ティック控除後収支円": trade["net_points"] * multiple,
                        "４ティック控除後収支円": trade["stress_points"] * multiple})
            writer.writerow(row)


def main() -> None:
    """機能: 入力照合・手法１の再生・全フィールド比較・結果保存を順に行う。

    引数: なし。
    返り値: なし (None)。不一致時は結果を保存して異常終了する。外部接続は行わない。
    """
    OUTPUT.mkdir(parents=True, exist_ok=True)
    candidate_path = V5 / "方向主候補.json"
    audit_path = V5 / "データ監査.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    checks = verify_candles(audit["source_sha256"])
    report = {"外部接続": False, "使用原本": "このフォルダ内の保存版のみ",
              "実行環境": {"Ｐｙｔｈｏｎ": platform.python_version(), "ＮｕｍＰｙ": np.__version__, "ｐａｎｄａｓ": pd.__version__},
              "足ファイル数": len(checks), "足一致数": sum(item["一致"] for item in checks), "足照合": checks,
              "主候補ＳＨＡ２５６": sha256(candidate_path), "データ監査ＳＨＡ２５６": sha256(audit_path),
              "実装ＳＨＡ２５６": {str(path.relative_to(BASE)): sha256(path)
                                 for path in (Path(__file__).resolve(), V4 / "engine.py", V4 / "signals.py", V5 / "exits.py")}}
    if len(checks) != 20 or not all(item["一致"] for item in checks):
        report["一致"] = False
        save_json(OUTPUT / "再現結果.json", report)
        raise SystemExit("保存足２０ファイルの照合に失敗しました。再生を中止します")

    # ----------------------------------------
    # 条件探索を行わず、保存済みの主候補１条件だけを再生する。
    sessions = list(dict.fromkeys(cell["session"] for cell in candidate["cells"]))
    trades = replay(candidate["config"], sessions)
    differences = compare_trades(trades, candidate["trades"])
    matched = not differences and len(trades) == 12 and all(trade["closed"] for trade in trades)
    report.update({"条件": candidate["config"], "セッション": sessions,
                   "再現取引数": len(trades), "保存取引数": len(candidate["trades"]),
                   "比較フィールド数": sum(len(trade) for trade in candidate["trades"]),
                   "比較方式": "取引順序と全項目を厳密比較。日時と数値型のみ標準化し、数値は丸めない",
                   "一致": matched, "差分": differences, "全取引": trades})
    save_json(OUTPUT / "再現結果.json", report)
    write_csv(trades)
    if not matched:
        raise SystemExit("再現取引が保存記録と一致しません。再現確認/再現結果.json を確認してください")
    print("保存足２０ファイルのＳＨＡ２５６が一致しました。")
    print(f"手法１の１２取引・全{report['比較フィールド数']}フィールドが保存記録と厳密一致しました。")
    print(f"結果: {OUTPUT}")


if __name__ == "__main__":
    main()
