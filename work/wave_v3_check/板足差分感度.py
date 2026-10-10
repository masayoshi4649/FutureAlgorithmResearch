"""生板と保存足の小差を代替コピーへ反映し、固定検知器の感度を検算する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
OLD = OUT.parent / "wave_v2"
SESSION = "2026-09-22_Night"
sys.dont_write_bytecode = True
sys.path.insert(0, str(OLD))
import research_v2 as r


def digest(path: Path) -> str:
    """ファイルの同一性を確認するためのハッシュを計算する。

    引数: path（Path）検査するファイル。
    返り値: str。SHA-256値。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plain(value: object) -> object:
    """時刻を含む結果をJSON保存時と同じ型へ変換する。

    引数: value（object）変換対象。
    返り値: object。文字列・数値・配列・辞書のみからなる値。
    """
    return json.loads(json.dumps(value, ensure_ascii=False, default=str, allow_nan=False))


def aggregate(one: pd.DataFrame) -> pd.DataFrame:
    """一分足を保存五分足と同じOHLCV定義で再集約する。

    引数: one（DataFrame）観測された確定一分足。
    返り値: DataFrame。無観測枠を除外した五分足。
    """
    return one.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "volume_complete": "all", "closed": "all"}).dropna(subset=["open"])


def compare_trades(before: list[dict], after: list[dict]) -> list[dict]:
    """同じ順序の取引について変更された項目を記録する。

    引数: before・after（list[dict]）正本と代替コピーの取引。
    返り値: list[dict]。取引番号・項目・変更前後の値。
    """
    differences = []
    for index in range(max(len(before), len(after))):
        left = plain(before[index]) if index < len(before) else None
        right = plain(after[index]) if index < len(after) else None
        if left is None or right is None:
            differences.append({"取引番号": index + 1, "項目": "取引の有無", "正本": left, "代替": right})
            continue
        for key in left.keys() | right.keys():
            if left.get(key) != right.get(key):
                differences.append({"取引番号": index + 1, "銘柄": left["symbol"], "項目": key, "正本": left.get(key), "代替": right.get(key)})
    return differences


def main() -> None:
    """差分をメモリ上だけで反映して、検知と売買結果の変更を調べる。

    引数: なし。
    返り値: None。感度結果のJSONとMarkdownだけを新規保存する。
    """
    sys.stdout.reconfigure(encoding="utf-8")
    fixed = json.loads((OLD / "固定設定.json").read_text(encoding="utf-8"))
    assert digest(OLD / "research_v2.py") == fixed["code_sha256"]
    cfg = r.Config(**fixed["config"])
    assert cfg.family == 24
    audit = json.loads((OUT / "追加データ監査.json").read_text(encoding="utf-8"))
    inputs = [ROOT / f"candle_{period}min" / symbol / f"{SESSION}.csv" for symbol in r.SYMBOLS for period in (1, 5)]
    protected = inputs + [OLD / "research_v2.py", OLD / "固定設定.json", OUT / "追加_取引.json"]
    original_hashes = {str(path.relative_to(ROOT)): digest(path) for path in protected}
    baseline, alternative, replacements, five_differences = {}, {}, [], []
    for symbol in r.SYMBOLS:
        one = r.read_candle(ROOT / "candle_1min" / symbol / f"{SESSION}.csv")
        five = r.read_candle(ROOT / "candle_5min" / symbol / f"{SESSION}.csv")
        computed = aggregate(one)
        pd.testing.assert_frame_equal(computed.loc[:, five.columns], five, check_dtype=False, check_freq=False)
        changed = one.copy(deep=True)
        source = next(row for row in audit["books"] if row["instrument"] == symbol)
        for item in source["raw_candle_ohlc_differences"]:
            assert item["field"] in ("open", "high", "low", "close")
            stamp = pd.Timestamp(item["time"])
            assert float(changed.at[stamp, item["field"]]) == item["candle"]
            changed.at[stamp, item["field"]] = item["raw"]
            replacements.append({"銘柄": symbol, "時刻": stamp, "項目": item["field"], "正本": item["candle"], "代替": item["raw"]})
        changed_five = aggregate(changed)
        for stamp in five.index:
            for field in ("open", "high", "low", "close", "volume"):
                if five.at[stamp, field] != changed_five.at[stamp, field]:
                    five_differences.append({"銘柄": symbol, "時刻": stamp, "項目": field, "正本": float(five.at[stamp, field]), "代替": float(changed_five.at[stamp, field])})
        baseline[(SESSION, symbol)] = (one, r.price_features(one, five, r.TICKS[symbol]))
        alternative[(SESSION, symbol)] = (changed, r.price_features(changed, changed_five, r.TICKS[symbol]))

    # ----------------------------------------
    # 全期間の信号状態と実際の取引を比較する。条件は両側とも凍結設定そのまま。
    before, _, before_cells = r.evaluate(baseline, cfg)
    after, _, after_cells = r.evaluate(alternative, cfg)
    expected = json.loads((OUT / "追加_取引.json").read_text(encoding="utf-8"))
    assert plain(before) == expected
    signal_differences = []
    for symbol in r.SYMBOLS:
        peer = "TOPIX" if symbol == "NK225" else "NK225"
        old_signal = r.score(baseline[(SESSION, symbol)][1], baseline[(SESSION, peer)][1], cfg.family, cfg.threshold)
        new_signal = r.score(alternative[(SESSION, symbol)][1], alternative[(SESSION, peer)][1], cfg.family, cfg.threshold)
        for stamp in old_signal.index[old_signal.ne(new_signal)]:
            signal_differences.append({"銘柄": symbol, "特徴量足時刻": stamp, "正本": float(old_signal.at[stamp]), "代替": float(new_signal.at[stamp])})
    differences = compare_trades(before, after)
    execution_keys = {"symbol", "session", "side", "signal_time", "entry_time", "entry_price", "exit_time", "exit_price", "closed", "duration_min", "gross_points", "reason", "net_points", "stress_points", "取引の有無"}
    execution_differences = [row for row in differences if row["項目"] in execution_keys]
    rows = []
    for symbol in r.SYMBOLS:
        left = next(cell for cell in before_cells if cell["symbol"] == symbol)
        right = next(cell for cell in after_cells if cell["symbol"] == symbol)
        rows.append({"銘柄": symbol, "正本取引数": left["count"], "代替取引数": right["count"], "正本通常損益": left["net_points"], "代替通常損益": right["net_points"], "損益差": right["net_points"] - left["net_points"], "正本厳格損益": left["stress_points"], "代替厳格損益": right["stress_points"]})
    assert all(digest(ROOT / path) == expected_hash for path, expected_hash in original_hashes.items())
    result = {"固定設定": cfg.key, "通信回数": 0, "正本再生の元結果一致": True, "保護対象不変更": True, "一分足変更": replacements, "五分足再集約による変更": five_differences, "信号状態差分": signal_differences, "実売買項目差分": execution_differences, "その他を含む全取引差分": differences, "銘柄別結果": rows, "正本全取引": before, "代替全取引": after, "保護対象SHA256": original_hashes}
    r.save_json(OUT / "板足差分感度.json", result)

    # ----------------------------------------
    # 正本の優劣を断定せず、観測された差が固定条件に与える影響だけを記載する。
    lines = ["# 生板と保存足の小差に対する感度検算", "", "保存一分足を正本とした結果は変更せず、メモリ上のコピーの5分・7項目だけを監査で観測した生板OHLC値へ置換した。各変更は1ティック。出来高は変更せず、五分足は同じOHLCV集約定義で再作成し、前回の固定条件 24_0.25_1_4_1 で追加夜間全体を再生した。真値の選択や条件調整ではない。", "", f"正本の8取引は保存済み結果と完全一致。代替側との信号状態の相違は {len(signal_differences)} 枠、実売買項目の相違は {len(execution_differences)} 項目。", "", "|銘柄|正本／代替取引数|正本通常損益|代替通常損益|差|正本／代替厳格損益|", "|---|---|---:|---:|---:|---|"]
    for row in rows:
        lines.append(f"|{row['銘柄']}|{row['正本取引数']}／{row['代替取引数']}|{row['正本通常損益']:g}|{row['代替通常損益']:g}|{row['損益差']:g}|{row['正本厳格損益']:g}／{row['代替厳格損益']:g}|")
    lines.extend(["", "損益単位は NK225 が円幅、TOPIX が指数ポイント。通常は往復2ティック、厳格は往復4ティックを控除。", ""])
    if not execution_differences and not signal_differences:
        lines.append("方向、新規・返済の時刻と価格、返済理由、保有時間、通常・厳格損益は全8取引で同一だった。この7項目の差では、今回の検知評価は変わらなかった。")
    if differences:
        lines.append(f"ATRとATR単位損益を含めると、取引記録に {len(differences)} 項目の数値差がある。全項目は JSON に記録した。これは約定損益の差とは区別する。")
    else:
        lines.append("ATRとATR単位損益を含む全取引項目も完全一致した。")
    lines.extend(["", f"変更前一分足の再集約が保存五分足に完全一致することを確認した上で代替側を作成した。代替側の五分足は {len(five_differences)} 項目が変化。全変更明細と検算結果は 板足差分感度.json を参照。", "", "元1分足・5分足、前回固定コード・設定、今回の正本取引結果について処理前後のSHA-256一致を確認した。外部通信は行っていない。"])
    (OUT / "板足差分感度.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"信号差分": len(signal_differences), "実売買差分": len(execution_differences), "全項目差分": len(differences), "結果": rows}, ensure_ascii=False))


if __name__ == "__main__":
    main()
