"""許可された原板末尾の部分読込だけで、前保存場参照を独立照合する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from independent_account import save


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def fresh(line: bytes, start: float, end: float) -> tuple[float, float] | None:
    """機能: 当該監視区間に入る正のCurrentPriceとその時計を確認する。

    引数: line(bytes)、start/end(float)。返り値: 価格と時刻(tuple)又は欠測(None)。
    """
    raw = json.loads(line)
    value, stamp = raw.get("CurrentPrice"), raw.get("CurrentPriceTime")
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 or not isinstance(stamp, str):
        return None
    try:
        time = datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return None
    return (float(value), time) if start <= time < end else None


def tail_value(path: Path, row_count: int, start: float, end: float) -> dict:
    """機能: 最大8MiBの後端から最後の場内約定価格を検索する。

    引数: path(Path)、row_count(int)、start/end(float)。返り値: 価格/時計/原本序数等(dict)。
    原本序数は原板の埋込IDでなく、指紋照合済み総行数と末尾の物理行数から求める。
    """
    size = path.stat().st_size
    for budget in (2 * 1024 * 1024, 8 * 1024 * 1024):
        with path.open("rb") as stream:
            offset = max(0, size - budget)
            stream.seek(offset)
            chunk = stream.read()
        if offset:
            newline = chunk.find(b"\n")
            assert newline >= 0
            chunk = chunk[newline + 1:]
        lines = chunk.splitlines()
        for index in range(len(lines) - 1, -1, -1):
            if not lines[index].strip():
                continue
            value = fresh(lines[index], start, end)
            if value is not None:
                return dict(value=value[0], source_time=value[1], source_seq=row_count - len(lines) + index,
                    最終読込byte数=min(size, budget), 原本サイズ=size, 読込開始offset=offset,
                    照合した後端行数=len(lines), tail_SHA256=hashlib.sha256(chunk).hexdigest())
    raise AssertionError(("8MiBの後端に当該保存区間の末値がない", str(path)))


def main() -> None:
    """機能: 全56前場参照を原板末尾から別の検索実装で確認する。

    引数: なし。返り値: なし(None)。APIと全原本走査は行わない。
    """
    meta = json.loads((HERE.parent / "inputs/refmetadata.json").read_text(encoding="utf-8"))
    source_rows = {(row["session"], row["symbol"]): row for row in meta["rows"]}
    checked = []
    for name, refs in meta["references"].items():
        previous = refs["ref_prev"]
        if previous["value"] is None:
            continue
        source_key = (previous["source_session"], refs["symbol"])
        row = source_rows[source_key]
        path = ROOT / "book" / source_key[1] / (source_key[0] + ".jsonl")
        result = tail_value(path, row["raw_rows"], row["start"], row["end"])
        assert result["source_seq"] == previous["source_seq"] and result["source_time"] == previous["source_time"] and result["value"] == previous["value"], (name, previous, result)
        assert result["source_time"] < source_rows[(refs["session"], refs["symbol"])]["start"]
        checked.append(dict(参照先=name, 元保存場="|".join(source_key), 準備配列外seq=previous["source_ready_i"] is None,
            value=result["value"], source_time=result["source_time"], source_seq=result["source_seq"],
            原本指紋=row["raw_SHA256"], **{field: value for field, value in result.items() if field not in ("value", "source_time", "source_seq")}))
    assert len(checked) == 56 and sum(row["準備配列外seq"] for row in checked) == 47
    save(HERE / "前場参照価格の原本末尾による独立監査.json", dict(合格=True, 検査前値数=len(checked),
        準備配列外seq直接照合数=sum(row["準備配列外seq"] for row in checked),
        末尾読込最終合計byte数=sum(row["最終読込byte数"] for row in checked),
        原本全走査=0, API取得=0, 実注文=0,
        連番の定義="元コード・metadataでseqはJSONL観測の0始まり序数。埋込市場IDや受信番号とは同一視しない。指紋照合済みの総行数を前提に、部分末尾の物理行数から序数を独立算出。",
        原本価格直接照合=True, 記録=checked))
    print("56前値（準備外47含む）の原本末尾直接照合が合格しました", flush=True)


if __name__ == "__main__":
    main()
