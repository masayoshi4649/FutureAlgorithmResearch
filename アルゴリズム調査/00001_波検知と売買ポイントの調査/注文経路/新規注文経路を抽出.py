"""元の約定処理を変更せず、主候補の新規待機と約定の実行経路を記録する。"""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
from pathlib import Path
import sys

import pandas as pd


OUT = Path(__file__).resolve().parent
ARCHIVE = OUT.parent / "保存版"
V4 = ARCHIVE / "work" / "wave_v4"
V5 = ARCHIVE / "work" / "wave_v5"
sys.path.insert(0, str(V4))
sys.path.insert(0, str(V5))
sys.dont_write_bytecode = True

from engine import TICKS, prepare, sign_schedule
from exits import BASE, ConfigV5
from signals import build_features, get_signals


def source_hash(path: Path) -> str:
    """機能: 読取対象のコードが変更されていないことを確認するハッシュを求める。

    引数: path (Path) は対象ファイル。
    返り値: ＳＨＡ－２５６文字列 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normal(value: object) -> object:
    """機能: 時刻と数値を比較・保存に適した標準型へ変換する。

    引数: value (object) は取引・計測値。
    返り値: ＪＳＯＮ互換の値 (object)。
    """
    return json.loads(json.dumps(value, ensure_ascii=False, default=str, allow_nan=False))


def write_csv(path: Path, rows: list[dict]) -> None:
    """機能: 日本語列名を持つ表を保存する。

    引数: path (Path) は出力先、rows (list[dict]) は行一覧。
    返り値: なし (None)。
    """
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_saved_inputs(target: dict, cfg: ConfigV5) -> tuple[dict, dict, list[dict]]:
    """機能: 文書フォルダ内の凍結した足だけを読み、元の処理で主候補の再生入力を作る。

    引数: target (dict) は保存主候補、cfg (ConfigV5) は主候補条件。
    返り値: 入力・元の信号列・二十足ファイルの照合一覧 (tuple[dict, dict, list[dict]])。
    手法１は生板と相手銘柄の特徴を使わないため、板の取得・再抽出は行わない。
    """
    if cfg.family != 9 or cfg.exit_mode != "nativebaseline":
        raise ValueError("保存主候補の手法１だけを観測できます")
    audit = json.loads((V5 / "データ監査.json").read_text(encoding="utf-8"))
    checks = []
    for original, expected in audit["source_sha256"].items():
        relative = original.replace("\\", "/")
        if relative.split("/")[0] not in ("candle_1min", "candle_5min"):
            continue
        actual = source_hash(ARCHIVE / relative)
        checks.append({"ファイル": relative, "期待ハッシュ": expected,
                       "実測ハッシュ": actual, "一致": actual == expected})
    assert len(checks) == 20 and all(row["一致"] for row in checks)
    data, schedule = {}, {}
    sessions = list(dict.fromkeys(row["session"] for row in target["trades"]))
    for session in sessions:
        frames = {}
        for symbol in ("NK225", "TOPIX"):
            loaded = []
            for interval in ("1min", "5min"):
                frame = pd.read_csv(ARCHIVE / f"candle_{interval}" / symbol / f"{session}.csv")
                frame["time"] = pd.to_datetime(frame.time)
                frame = frame[frame.closed.astype(str).str.lower().eq("true")].set_index("time").sort_index()
                assert not frame.index.duplicated().any()
                loaded.append(frame)
            frames[symbol] = loaded
        end = max(one.index[-1] for one, five in frames.values())
        for symbol, (one, five) in frames.items():
            features = build_features(one, five, None, TICKS[symbol], end)
            key = (session, symbol)
            data[key] = prepare(one, features, symbol, session)
            values = get_signals(features, features, cfg.family, cfg.param).to_numpy()
            schedule[key] = sign_schedule(values)
    return data, schedule, checks


def trace_session(item: dict, schedule: tuple, cfg: ConfigV5) -> tuple[list[dict], list[dict]]:
    """機能: 元の再生関数の実行を観測し、注文待機・約定時点の内部状態を記録する。

    引数: item (dict) は保存足入力、schedule (tuple) は元の方向列、cfg (ConfigV5) は主候補条件。
    返り値: 元の取引一覧と観測記録 (tuple[list[dict], list[dict]])。
    元関数の局所変数と入力を読み取るだけで、判定・変数の変更や独自の約定計算は行わない。
    """
    source, first = inspect.getsourcelines(BASE.simulate)
    marker = {}
    for number, line in enumerate(source, first):
        stripped = line.strip()
        if stripped == 'direction = pending["side"]':
            marker["待機"] = number
        elif stripped == "if px is None:":
            marker["判定"] = number
        elif stripped.startswith("active = dict(symbol=data["):
            marker["約定"] = number
    pending_continues = [number for number, line in enumerate(source, first)
                        if marker["判定"] < number < marker["約定"] and line.strip() == "continue"]
    assert len(pending_continues) == 1
    marker["更新後"] = pending_continues[0]
    assert len(marker) == 4
    orders, ordered = {}, []

    def observer(frame: object, event: str, arg: object) -> object:
        """機能: 元関数の指定行で、注文状態を複製して記録する。

        引数: frame (frame) は実行フレーム、event (str) は実行事象、arg (object) は付随値。
        返り値: 継続観測関数または観測不要を表す値 (callable | None)。
        """
        if frame.f_code is not BASE.simulate.__code__:
            return None
        if event != "line" or frame.f_lineno not in marker.values():
            return observer
        local = frame.f_locals
        pending = local["pending"]
        key = (float(pending["armed"]), int(pending["side"]), str(pending["signal_time"]))
        if frame.f_lineno == marker["待機"]:
            if key not in orders:
                record = {
                    "銘柄": item["symbol"], "セッション": item["session"],
                    "売買": "買い" if pending["side"] == 1 else "売り",
                    "待機開始時刻": str(local["now"]),
                    "参照足開始時刻": str(item["z"].index[local["pos"]]),
                    "信号利用可能時刻": str(pending["signal_time"]),
                    "注意": "信号時刻は参照足の確定時刻であり、方向が初めて発生した時刻とは限らない。",
                    "基準終値": float(pending["ref"]),
                    "固定ＡＴＲ": float(pending["atr"]),
                    "初期待機価格": float(pending["level"]),
                    "経路": [],
                }
                orders[key] = record
                ordered.append(record)
        elif frame.f_lineno == marker["判定"]:
            orders[key]["経路"].append({
                "判定足開始時刻": str(local["now"]),
                "足の始値": float(local["op"]), "足の高値": float(local["high"]),
                "足の安値": float(local["low"]), "足の終値": float(local["close"]),
                "判定前の追跡安値": float(pending["anchor_low"]),
                "判定前の追跡高値": float(pending["anchor_high"]),
                "判定価格": float(pending["level"]),
                "判定結果": "未成立" if local["px"] is None else "成立",
                "約定価格": None if local["px"] is None else float(local["px"]),
                "確定後の追跡安値": None,
                "確定後の追跡高値": None,
                "次の足の判定価格": None,
            })
        elif frame.f_lineno == marker["更新後"]:
            orders[key]["経路"][-1].update({
                "確定後の追跡安値": float(pending["anchor_low"]),
                "確定後の追跡高値": float(pending["anchor_high"]),
                "次の足の判定価格": float(pending["level"]),
            })
        elif frame.f_lineno == marker["約定"]:
            orders[key].update({
                "約定足開始時刻": str(local["now"]),
                "約定価格": float(local["px"]),
                "初期損切り価格": float(local["stop"]),
            })
        return observer

    prior = sys.gettrace()
    try:
        sys.settrace(observer)
        trades = BASE.simulate(item, schedule, cfg)
    finally:
        sys.settrace(prior)
    return trades, ordered


def main() -> None:
    """機能: 全十二取引の経路を生成し、保存済み主候補の取引と一致することを検算する。

    引数: なし。
    返り値: なし (None)。自領域へ日本語のＣＳＶ・ＪＳＯＮを保存する。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    target = json.loads((V5 / "方向主候補.json").read_text(encoding="utf-8"))
    cfg = ConfigV5(**target["config"])
    code_path = Path(inspect.getsourcefile(BASE.simulate))
    before = source_hash(code_path)
    data, schedule, input_checks = load_saved_inputs(target, cfg)
    replayed, orders = [], []
    for key, item in data.items():
        trades, observed = trace_session(item, schedule[key], cfg)
        replayed.extend(trades)
        orders.extend(observed)
    expected = {(row["symbol"], row["session"], row["entry_time"]): row for row in target["trades"]}
    for trade in normal(replayed):
        key = (trade["symbol"], trade["session"], trade["entry_time"])
        assert trade == expected[key], (key, trade, expected[key])
    assert len(replayed) == len(expected) == 12
    assert source_hash(code_path) == before

    # ----------------------------------------
    # 約定に至った待機注文だけを抽出し、取消された先行注文を区別する。
    fills = [row for row in orders if "約定足開始時刻" in row]
    assert len(fills) == 12
    summary, paths = [], []
    for order in fills:
        trade = expected[(order["銘柄"], order["セッション"], order["約定足開始時刻"])]
        assert order["約定価格"] == trade["entry_price"]
        assert order["固定ＡＴＲ"] == trade["atr"]
        assert order["信号利用可能時刻"] == trade["signal_time"]
        order["返済足開始時刻"] = trade["exit_time"]
        order["返済価格"] = trade["exit_price"]
        order["費用控除後値幅"] = trade["net_points"]
        order["保存取引と一致"] = True
        row = {key: value for key, value in order.items() if key not in ("経路", "注意")}
        row["待機分数"] = (pd.Timestamp(order["約定足開始時刻"]) - pd.Timestamp(order["待機開始時刻"])).total_seconds() / 60
        summary.append(row)
        for point in order["経路"]:
            paths.append({"銘柄": order["銘柄"], "セッション": order["セッション"],
                          "売買": order["売買"], "待機開始時刻": order["待機開始時刻"], **point})
    output = {
        "方法": "元の engine.simulate に sys.settrace を付けて局所変数を読取観測。独自の約定処理なし。",
        "注意": "時刻は日本時間。約定時刻は一分足の開始ラベルであり、秒単位の成立時刻は不明。",
        "使用データ": "文書フォルダ内の保存版のみ。生板なし。外部接続なし。",
        "足照合": input_checks,
        "参照コード": str(code_path.relative_to(OUT.parent)), "参照コードハッシュ": before,
        "全取引一致": True, "一致件数": len(replayed),
        "約定に至った注文": fills,
        "取消を含む全待機注文": orders,
    }
    (OUT / "主候補の新規注文経路.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    write_csv(OUT / "主候補の全十二取引.csv", summary)
    write_csv(OUT / "主候補の待機中の一分経路.csv", paths)
    print(json.dumps({"一致件数": len(replayed), "全待機注文数": len(orders),
                      "約定経路行数": len(paths), "出力先": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
