"""同一最終約定時刻の内部にある気配変動を、独立に数える監査。"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


def inspect(path: Path) -> dict:
    """生板一ファイルの同時刻ブロック内で有効気配が動く頻度を調べる。

    引数: path（Path）読み取り専用のJSONLファイル。
    返り値: dict。ブロック数、変動幅、初回気配以降の不利方向変動など。
    """
    date = datetime.fromisoformat(path.stem[:10]).date()
    start = datetime.combine(date, time(8, 45) if path.stem.endswith("Day") else time(17), JST)
    end = datetime.combine(date, time(15, 40), JST) if path.stem.endswith("Day") else datetime.combine(date + timedelta(days=1), time(5, 55), JST)
    tick = 10.0 if path.parent.name == "NK225" else 0.5
    counts = Counter()
    anchor = None
    block = []
    maximum = {"bid_range_ticks": 0, "ask_range_ticks": 0, "first_bid_drop_ticks": 0, "first_ask_rise_ticks": 0}
    example = None

    def release() -> None:
        """直前までの有効板ブロックを監査カウンターへ加える。

        引数: なし。外側のスコープの有効板ブロックを読む。
        返り値: None。
        """
        nonlocal example
        if not block:
            return
        counts["valid_blocks"] += 1
        counts["multiple_row_blocks"] += len(block) > 1
        bids = [item[1] for item in block]
        asks = [item[2] for item in block]
        values = {
            "bid_range_ticks": (max(bids) - min(bids)) / tick,
            "ask_range_ticks": (max(asks) - min(asks)) / tick,
            "first_bid_drop_ticks": (bids[0] - min(bids)) / tick,
            "first_ask_rise_ticks": (max(asks) - asks[0]) / tick,
        }
        for key, value in values.items():
            maximum[key] = max(maximum[key], value)
            for threshold in (1, 2, 5):
                counts[f"{key}_ge_{threshold}"] += value >= threshold
        if example is None and values["first_bid_drop_ticks"] >= 2:
            lowest = min(block, key=lambda item: item[1])
            example = {"time": anchor.isoformat(), "first": block[0], "lowest_bid": lowest}

    # ----------------------------------------
    # 原本の記録順を維持し、監査以外の売買処理を行わない。
    with path.open(encoding="utf-8") as stream:
        for seq, line in enumerate(stream):
            counts["raw_rows"] += 1
            row = json.loads(line)
            raw_stamp = row.get("CurrentPriceTime")
            if not isinstance(raw_stamp, str):
                counts["missing_time_rows"] += 1
                continue
            stamp = datetime.fromisoformat(raw_stamp)
            if not start <= stamp < end:
                counts["outside_session_rows"] += 1
                continue
            if anchor is not None and stamp != anchor:
                if stamp < anchor:
                    raise ValueError("最終約定時刻の逆行")
                release()
                block = []
            anchor = stamp
            buy, sell = row["Buy1"], row["Sell1"]
            bid, ask = buy["Price"], sell["Price"]
            if bid > 0 and ask > bid and buy["Qty"] >= 1 and sell["Qty"] >= 1:
                block.append((seq, bid, ask))
                counts["valid_quote_rows"] += 1
            else:
                counts["invalid_quote_rows"] += 1
    release()
    return {"source": str(path.relative_to(ROOT)), "counts": dict(counts), "maximum": maximum, "example": example}


def main() -> None:
    """全保存ファイルと既知の夜間保存分の監査値をJSONに出力する。

    引数: なし。
    返り値: None。検証資料を本作業フォルダに保存する。
    """
    paths = sorted((ROOT / "book").glob("*/*.jsonl")) + sorted((ROOT / "work/wave_v7/live/book").glob("*/*.jsonl"))
    results = []
    for path in paths:
        result = inspect(path)
        results.append(result)
        print(path.parent.name, path.stem, result["counts"]["valid_blocks"], result["maximum"], flush=True)
    (OUT / "同時刻ブロック内気配監査.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
