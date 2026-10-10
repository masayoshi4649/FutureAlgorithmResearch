"""原本を途中で打ち切る再抽出により、生板特徴の未来非依存を独立に検証する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import raw_features


OUT = Path(__file__).resolve().parent


def verify_prefix(path: Path, symbol: str, session: str) -> list[dict]:
    """各ファイルの二つの生行打切り点で特徴と気配系列の不変性を検査する。

    引数: path（Path）原本。symbol（str）銘柄。session（str）セッション名。
    返り値: list[dict]。各打切り点の照合行数と比較列数を含む検証結果。
    """
    quotes = []
    full, audit = raw_features.extract_features(path, symbol, session, quotes=quotes)
    quote_frame = pd.DataFrame(quotes)
    assert (full["source_last_seq"] < full["seq"]).all()
    assert (full["source_time_s"] < full["time_s"]).all()
    records = []
    for fraction in (0.33337, 0.66671):
        cut = max(1, int(audit["読取行数"] * fraction))
        prefix_quotes = []
        prefix, prefix_audit = raw_features.extract_features(path, symbol, session, max_rows=cut, quotes=prefix_quotes)
        expected = full.loc[full["seq"] < cut].reset_index(drop=True)
        pd.testing.assert_frame_equal(prefix, expected, check_exact=True)
        expected_quotes = quote_frame.loc[quote_frame["seq"] < cut].reset_index(drop=True)
        actual_quotes = pd.DataFrame(prefix_quotes)
        pd.testing.assert_frame_equal(actual_quotes, expected_quotes, check_exact=True)
        assert prefix_audit["読取行数"] == cut
        assert prefix_audit["未解放末尾ブロック行数"] > 0
        records.append({
            "銘柄": symbol,
            "セッション": session,
            "生行打切り数": cut,
            "特徴照合行数": len(prefix),
            "特徴照合列数": len(prefix.columns),
            "気配照合行数": len(actual_quotes),
            "気配照合列数": len(actual_quotes.columns),
            "未解放末尾行数": prefix_audit["未解放末尾ブロック行数"],
            "一致": True,
        })
    return records


def verify_future_change() -> dict:
    """9月23日日中NKの未来行だけを改変し、改変前の出力が同じことを確認する。

    引数: なし。
    返り値: dict。改変境界、特徴と気配の照合件数、結果。
    """
    source = raw_features.ROOT / "book/NK225/2026-09-23_Day.jsonl"
    quotes = []
    full, audit = raw_features.extract_features(source, "NK225", "2026-09-23_Day", quotes=quotes)
    cut = int(audit["読取行数"] * 0.50003)
    temporary = OUT / "未来改変_監査専用.jsonl"
    with source.open(encoding="utf-8") as source_stream, temporary.open("w", encoding="utf-8", newline="\n") as destination:
        for seq, line in enumerate(source_stream):
            if seq < cut:
                destination.write(line)
                continue
            row = json.loads(line)
            for side in ("Buy", "Sell"):
                for level in range(1, 11):
                    item = row.get(f"{side}{level}") or {}
                    if isinstance(item.get("Price"), (int, float)):
                        item["Price"] += 1000
                    if isinstance(item.get("Qty"), (int, float)):
                        item["Qty"] *= 3
            if isinstance(row.get("CurrentPrice"), (int, float)):
                row["CurrentPrice"] += 1000
            destination.write(json.dumps(row, ensure_ascii=False) + "\n")
    altered_quotes = []
    altered, _ = raw_features.extract_features(temporary, "NK225", "2026-09-23_Day", quotes=altered_quotes)
    expected = full.loc[full["seq"] < cut].reset_index(drop=True)
    observed = altered.loc[altered["seq"] < cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(observed, expected, check_exact=True)
    quote_frame = pd.DataFrame(quotes)
    altered_quote_frame = pd.DataFrame(altered_quotes)
    pd.testing.assert_frame_equal(
        altered_quote_frame.loc[altered_quote_frame["seq"] < cut].reset_index(drop=True),
        quote_frame.loc[quote_frame["seq"] < cut].reset_index(drop=True),
        check_exact=True,
    )
    future = full.loc[full["seq"] >= cut, "source_mid_last"].to_numpy()
    altered_future = altered.loc[altered["seq"] >= cut, "source_mid_last"].to_numpy()
    assert not np.array_equal(future, altered_future)
    temporary.unlink()
    return {"銘柄": "NK225", "セッション": "2026-09-23_Day", "未来改変開始seq": cut, "過去特徴照合行数": len(observed), "一致": True}


def main() -> None:
    """全12ファイルの途中打切りと未来改変を実行し、監査記録を保存する。

    引数: なし。
    返り値: None。日本語JSONとして監査記録を保存する。
    """
    feature_file = Path(raw_features.__file__)
    initial_hash = hashlib.sha256(feature_file.read_bytes()).hexdigest()
    records = []
    for path, symbol, session in raw_features.sources():
        current = verify_prefix(path, symbol, session)
        records.extend(current)
        print(f"途中打切り一致: {symbol} {session}、{sum(row['特徴照合行数'] for row in current)} 特徴行", flush=True)
    future = verify_future_change()
    final_hash = hashlib.sha256(feature_file.read_bytes()).hexdigest()
    result = {
        "抽出コードSHA256": initial_hash,
        "監査中コード変更なし": initial_hash == final_hash,
        "入力原本を変更していない": True,
        "途中打切り": records,
        "未来価格数量改変": future,
        "検証の範囲": "原本を読み切ってから表を切るだけでなく、extract_featuresの原本読取りそのものをseqの途中で停止した。通常セッション終端は変更せず、未解放末尾の情報を使用しないことも検査した。注文再生と利益の因果性は別監査。",
    }
    (OUT / "生板未来非依存監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert result["監査中コード変更なし"], "抽出コードが監査中に変更されたため最終コードで再実行が必要"
    print("生板特徴と気配系列の独立監査に合格しました。", flush=True)


if __name__ == "__main__":
    main()
