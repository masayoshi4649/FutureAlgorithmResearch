"""原板を全行保持し、時計・板・出来高を分けた非金融特徴と原文位置を保存する。"""

from __future__ import annotations

import argparse
from array import array
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import pickle
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATA = ROOT.parent / "JP_OSE_Data" / "future"
SCENES = ["2026-10-22_Night", "2026-10-23_Day", "2026-10-23_Night"]
JST = timezone(timedelta(hours=9))
TICKS = {"NK225": 10.0, "TOPIX": 0.5}


def save_json(path: Path, value: dict) -> None:
    """新規JSONをUTF-8で保存する。

    引数: path(Path)は保存先、value(dict)は有限値だけを含む内容。
    返り値: None。既存の資料は上書きしない。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def file_hash(path: Path) -> str:
    """ファイル全体のSHA256を取得する。

    引数: path(Path)は読み取り専用の対象。
    返り値: strはSHA256の16進表示。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def number(value: object) -> float:
    """原値が有限数の場合だけその数値を使う。

    引数: value(object)はJSON由来の値。
    返り値: float。欠測・真偽値・不正値はNaN。
    """
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else math.nan


def clock(value: object, cache: dict) -> float:
    """元のタイムゾーン付き時計を変更せずepoch秒へ変換する。

    引数: value(object)は時計、cache(dict)は反復時計の変換キャッシュ。
    返り値: float。不明な時計を推定せずNaNとする。
    """
    if not isinstance(value, str) or not value:
        return math.nan
    if value not in cache:
        try:
            parsed = datetime.fromisoformat(value)
            cache[value] = parsed.timestamp() if parsed.tzinfo is not None else math.nan
        except (ValueError, OverflowError, OSError):
            cache[value] = math.nan
    return cache[value]


def bounds(session: str) -> tuple[float, float]:
    """原板資格を分ける公式場内窓を返す。

    引数: session(str)は日付_Day又は日付_Night。
    返り値: tuple[float,float]は開始を含み終了を含まないepoch秒。
    """
    day = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("_Day"):
        return day.replace(hour=8, minute=45).timestamp(), day.replace(hour=15, minute=45).timestamp()
    return day.replace(hour=17).timestamp(), (day + timedelta(days=1)).replace(hour=6).timestamp()


def time_text(value: float) -> str | None:
    """有限epoch秒を日本時間の文字列にする。

    引数: value(float)はepoch秒。
    返り値: str又はNone。時計欠測はNone。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat() if np.isfinite(value) else None


def previous(values: np.ndarray) -> np.ndarray:
    """配列を原行順で一行だけ遅らせる。

    引数: values(ndarray)は浮動小数の1又は2次元配列。
    返り値: ndarray。先頭行はNaNとし、未来行は参照しない。
    """
    result = np.empty_like(values)
    result[0] = np.nan
    result[1:] = values[:-1]
    return result


def changed(values: np.ndarray) -> np.ndarray:
    """連続する原行の値変化を欠測同士の一致を考慮して判定する。

    引数: values(ndarray)は1又は2次元の数値配列。
    返り値: ndarray[bool]。先頭行はFalse。
    """
    old = previous(values)
    result = ~((values == old) | (np.isnan(values) & np.isnan(old)))
    if result.ndim == 2:
        result = np.any(result, axis=1)
    result[0] = False
    return result


def common_price_changes(prices: np.ndarray, quantities: np.ndarray, valid: np.ndarray) -> dict[str, np.ndarray]:
    """連続二行の両方に見える同一価格の数量差だけを集計する。

    引数: prices/quantities(ndarray[N,10])は板、valid(ndarray[N])は両行の板資格。
    返り値: dict[str,ndarray]。増減は補充・撤退の代理であり、約定や注文取消の断定ではない。
    """
    old_price, old_quantity = previous(prices), previous(quantities)
    n = len(prices)
    inc, dec, count = np.zeros(n), np.zeros(n), np.zeros(n, dtype=np.int16)
    for level in range(10):
        current_valid = np.isfinite(prices[:, level]) & (prices[:, level] > 0) & np.isfinite(quantities[:, level]) & (quantities[:, level] >= 0)
        match = (old_price == prices[:, level, None]) & np.isfinite(old_quantity) & (old_quantity >= 0)
        matched = valid & current_valid & np.any(match, axis=1)
        old_qty = np.sum(np.where(match, old_quantity, 0.0), axis=1)
        delta = np.where(matched, quantities[:, level] - old_qty, 0.0)
        inc += np.maximum(delta, 0.0)
        dec += np.maximum(-delta, 0.0)
        count += matched.astype(np.int16)
    inc[~valid], dec[~valid] = np.nan, np.nan
    return {"increase": inc, "decrease": dec, "matched_levels": count}


def features(arrays: dict, symbol: str, session: str) -> None:
    """原行だけから板・時計・出来高の独立特徴を付加する。

    引数: arrays(dict)は全原行配列、symbol/session(str)は銘柄と場名。
    返り値: None。入力辞書へ配列を追加する。売買判断はしない。
    """
    bid, ask = arrays["buy_price"][:, 0], arrays["sell_price"][:, 0]
    bq, aq = arrays["buy_qty"][:, 0], arrays["sell_qty"][:, 0]
    good = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid) & np.isfinite(bq) & np.isfinite(aq) & (bq > 0) & (aq > 0)
    both = good & np.r_[False, good[:-1]]
    arrays.update(bid=bid.copy(), ask=ask.copy(), book_valid=good, adjacent_book_valid=both)
    arrays["mid"] = np.where(good, (bid + ask) / 2, np.nan)
    arrays["spread"] = np.where(good, ask - bid, np.nan)
    arrays["spread_ticks"] = arrays["spread"] / TICKS[symbol]
    arrays["book_changed"] = changed(arrays["buy_price"]) | changed(arrays["sell_price"]) | changed(arrays["buy_qty"]) | changed(arrays["sell_qty"])
    arrays["bbo_price_changed"] = changed(bid) | changed(ask)
    arrays["bbo_changed"] = arrays["bbo_price_changed"] | changed(bq) | changed(aq)
    arrays["last_changed"] = changed(arrays["last"])
    t = arrays["time_s"]
    pt = previous(t)
    arrays["price_clock_valid"] = np.isfinite(t)
    arrays["price_clock_same"] = np.isfinite(t) & np.isfinite(pt) & (t == pt)
    arrays["price_clock_backward"] = np.isfinite(t) & np.isfinite(pt) & (t < pt)
    arrays["price_clock_step_seconds"] = np.where(np.isfinite(t) & np.isfinite(pt), t - pt, np.nan)
    start, end = bounds(session)
    arrays["in_session"] = np.isfinite(t) & (t >= start) & (t < end)
    vt = arrays["volume_time_s"]
    arrays["volume_clock_same"] = np.isfinite(vt) & (vt == previous(vt))
    arrays["volume_time_lead_seconds"] = np.where(np.isfinite(t) & np.isfinite(vt), vt - t, np.nan)
    vol_diff = arrays["volume"] - previous(arrays["volume"])
    arrays["volume_delta_signed"] = vol_diff
    arrays["volume_reset"] = np.isfinite(vol_diff) & (vol_diff < 0)
    arrays["volume_delta"] = np.where(np.isfinite(vol_diff) & (vol_diff >= 0), vol_diff, np.nan)

    # ----------------------------------------
    # 価格距離で加重した可視数量と、BBOの価格移動を含む数量圧力を計算する。
    weighted = {}
    for side in ("buy", "sell"):
        prices, quantities = arrays[f"{side}_price"], arrays[f"{side}_qty"]
        level_valid = np.isfinite(prices) & (prices > 0) & np.isfinite(quantities) & (quantities >= 0)
        distance = np.abs(prices - arrays["mid"][:, None]) / TICKS[symbol]
        amount = np.sum(np.where(level_valid, quantities / (1 + distance), 0.0), axis=1)
        amount[~good] = np.nan
        weighted[side] = amount
        arrays[f"weighted_{side}_depth"] = amount
        arrays[f"valid_{side}_levels"] = np.sum(level_valid, axis=1).astype(np.int16)
        for name, result in common_price_changes(prices, quantities, both).items():
            arrays[f"same_price_{side}_{name}"] = result
    total = weighted["buy"] + weighted["sell"]
    arrays["distance_imbalance"] = np.divide(weighted["buy"] - weighted["sell"], total, out=np.full(len(t), np.nan), where=total > 0)
    pb, pa, pbq, paq = previous(bid), previous(ask), previous(bq), previous(aq)
    ofi = np.where(bid >= pb, bq, 0) - np.where(bid <= pb, pbq, 0) - np.where(ask <= pa, aq, 0) + np.where(ask >= pa, paq, 0)
    arrays["ofi"] = np.where(both, ofi, np.nan)
    denom = bq + pbq + aq + paq
    arrays["ofi_normalized"] = np.divide(arrays["ofi"], denom, out=np.full(len(t), np.nan), where=both & (denom > 0))
    arrays["mid_change_ticks"] = np.where(both, (arrays["mid"] - previous(arrays["mid"])) / TICKS[symbol], np.nan)


def row_point(arrays: dict, index: int) -> dict:
    """一行の位置と主要時計だけを監査用に取り出す。

    引数: arrays(dict)は原行配列、index(int)は0始まり行位置。
    返り値: dictは原文へ戻れる位置情報。
    """
    return {"seq": int(index), "line_no": int(index + 1), "byte_offset": int(arrays["byte_offset"][index]),
            "time": time_text(arrays["time_s"][index]), "volume_time": time_text(arrays["volume_time_s"][index])}


def packet_paths() -> dict[str, Path]:
    """既存50場の保存packet目録だけを読む。

    引数: なし。
    返り値: dict[str,Path]は場名から保存packetへの対応。数式再計算はしない。
    """
    found = {}
    for name in (ROOT / "work/aggressive140_20261024/known_manifest140.json", ROOT / "work/aggressive140_20261024/inputs/input_manifest.json"):
        if name.exists():
            for item in json.loads(name.read_text(encoding="utf-8-sig"))["packets"]:
                p = Path(item["path"])
                found[item["session"]] = p if p.is_absolute() else ROOT / p
    return found


def align_packet(arrays: dict, symbol: str, session: str, packet_path: Path, destination: Path) -> dict:
    """保存packetを0始まり原seqで全件照合し、同じ順序の特徴を保存する。

    引数: arrays(dict)、symbol/session(str)、packet_path/destination(Path)は原配列と入出力。
    返り値: dictは全件照合と時計重複の証跡。金融処理は呼ばない。
    """
    with packet_path.open("rb") as stream:
        packet = pickle.load(stream)
    key = (session, symbol)
    ready, quote = packet["inputs"][key], packet["quotes"][key]
    seq = np.asarray(ready["seq"], dtype=np.int64)
    assert len(seq) and np.all(np.diff(seq) > 0) and np.all(seq >= 0) and np.all(seq < len(arrays["seq"])), (session, symbol)
    checks = {}
    for name, expected in [("time_s", ready["time_s"]), ("last", ready["last"]), ("bid", quote["bid"]), ("ask", quote["ask"])]:
        actual = arrays[name][seq]
        expected = np.asarray(expected)
        mismatch = ~np.isclose(actual, expected, rtol=0, atol=1e-9, equal_nan=True)
        checks[name] = {"compared": len(seq), "mismatches": int(np.count_nonzero(mismatch))}
        assert not np.any(mismatch), (session, symbol, name, seq[np.flatnonzero(mismatch)[:8]])
    assert np.array_equal(seq, quote["seq"])
    assert np.all(np.asarray(quote["quote_valid"], dtype=bool) == arrays["book_valid"][seq])
    aligned = {name: value[seq] for name, value in arrays.items() if isinstance(value, np.ndarray) and value.ndim == 1 and len(value) == len(arrays["seq"])}
    aligned.update(packet_index=np.arange(len(seq), dtype=np.int64), packet_atr=np.asarray(ready["atr"]),
                   packet_quote_valid=np.asarray(quote["quote_valid"], dtype=bool), source_path=arrays["source_path"], source_sha256=arrays["source_sha256"])
    np.savez_compressed(destination, **aligned)
    eligible = arrays["in_session"] & arrays["book_valid"] & np.isfinite(arrays["last"]) & (arrays["last"] > 0)
    t = arrays["time_s"]
    beginning = ~np.r_[False, np.isfinite(t[1:]) & np.isfinite(t[:-1]) & (t[1:] == t[:-1])]
    ending = ~np.r_[np.isfinite(t[1:]) & np.isfinite(t[:-1]) & (t[1:] == t[:-1]), False]
    atr = np.flatnonzero(np.isfinite(ready["atr"]) & (ready["atr"] > 0))
    dt = np.diff(ready["time_s"])
    return {"packet_path": str(packet_path), "packet_sha256": file_hash(packet_path), "rows": len(seq), "sequence_is_zero_based_raw_line": True,
            "checks": checks, "quote_valid_equal_raw_book_valid": True, "raw_eligible_rows": int(eligible.sum()),
            "raw_eligible_not_in_packet": int(np.count_nonzero(eligible & ~np.isin(arrays["seq"], seq))),
            "packet_time_duplicate_steps": int(np.count_nonzero(dt == 0)), "packet_time_backward_steps": int(np.count_nonzero(dt < 0)),
            "same_clock_run_first_rows_selected": int(beginning[seq].sum()), "same_clock_run_last_rows_selected": int(ending[seq].sum()),
            "same_clock_run_middle_rows_selected": int((~beginning[seq] & ~ending[seq]).sum()),
            "first_packet": row_point(arrays, int(seq[0])), "last_packet": row_point(arrays, int(seq[-1])),
            "first_positive_atr": row_point(arrays, int(seq[atr[0]])) if len(atr) else None,
            "aligned_path": str(destination), "aligned_sha256": file_hash(destination)}


def scan_one(data_root: Path, output: Path, symbol: str, session: str, packets: dict) -> dict:
    """一ファイルを末尾まで全行読み、原位置と特徴・カバレッジを保存する。

    引数: data_root/output(Path)は原本と所有出力、symbol/session(str)は対象、packets(dict)は保存packet位置。
    返り値: dictは原本指紋・全行読取証跡・欠測と時計資格の集計。
    """
    started = time.monotonic()
    stem = f"{symbol}_{session}"
    destination = output / "raw_features" / (stem + ".npz")
    coverage_path = output / "coverage" / (stem + ".json")
    assert not destination.exists() and not coverage_path.exists(), "既存出力は上書きしません"
    source = data_root / symbol / session / "book.jsonl"
    if not source.exists():
        source = source.with_suffix(source.suffix + ".gz")
    assert source.exists(), source
    before = source.stat()
    scalar = {name: array("d") for name in ["time_s", "volume_time_s", "last", "volume", "trading_value", "top_bid_price", "top_ask_price"]}
    level_arrays = {name: array("d") for name in ["buy_price", "buy_qty", "sell_price", "sell_qty"]}
    offsets, lengths, hashes, valid_json = array("q"), array("q"), bytearray(), bytearray()
    digest = hashlib.sha256()
    cache, first_two, time_fields = {}, [], set()
    invalid, byte_offset = [], 0
    opener = gzip.open if source.suffix == ".gz" else open
    with opener(source, "rb") as stream:
        for seq, raw in enumerate(stream):
            digest.update(raw)
            offsets.append(byte_offset)
            lengths.append(len(raw))
            hashes.extend(hashlib.sha256(raw).digest())
            byte_offset += len(raw)
            if seq < 2:
                first_two.append(raw)
            try:
                row = json.loads(raw)
                assert isinstance(row, dict)
                valid_json.append(1)
            except (ValueError, AssertionError):
                row = {}
                invalid.append(seq)
                valid_json.append(0)
            time_fields.update(name for name in row if "time" in name.lower())
            scalar["time_s"].append(clock(row.get("CurrentPriceTime"), cache))
            scalar["volume_time_s"].append(clock(row.get("TradingVolumeTime"), cache))
            for name, field in [("last", "CurrentPrice"), ("volume", "TradingVolume"), ("trading_value", "TradingValue"), ("top_bid_price", "BidPrice"), ("top_ask_price", "AskPrice")]:
                scalar[name].append(number(row.get(field)))
            for side, prefix in [("buy", "Buy"), ("sell", "Sell")]:
                for level in range(1, 11):
                    item = row.get(f"{prefix}{level}") or {}
                    level_arrays[f"{side}_price"].append(number(item.get("Price")))
                    level_arrays[f"{side}_qty"].append(number(item.get("Qty")))
            if (seq + 1) % 100000 == 0:
                print(f"{stem}: {seq + 1:,}行読取", flush=True)
    after = source.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "読取中に原本が変更されました"
    n = len(offsets)
    assert n and byte_offset == int(offsets[-1] + lengths[-1])
    if source.suffix != ".gz":
        assert byte_offset == before.st_size
    arrays = {name: np.frombuffer(values, dtype=np.float64) for name, values in scalar.items()}
    arrays.update({name: np.frombuffer(values, dtype=np.float64).reshape(n, 10) for name, values in level_arrays.items()})
    source_sha = digest.hexdigest() if source.suffix != ".gz" else file_hash(source)
    arrays.update(seq=np.arange(n, dtype=np.int64), line_no=np.arange(1, n + 1, dtype=np.int64),
                  byte_offset=np.frombuffer(offsets, dtype=np.int64), byte_length=np.frombuffer(lengths, dtype=np.int64),
                  line_sha256=np.frombuffer(hashes, dtype=np.uint8).reshape(n, 32), json_valid=np.frombuffer(valid_json, dtype=np.uint8).astype(bool),
                  source_path=np.array(str(source.resolve())), source_sha256=np.array(source_sha),
                  source_size=np.array(before.st_size, dtype=np.int64), source_mtime_ns=np.array(before.st_mtime_ns, dtype=np.int64),
                  offset_is_uncompressed=np.array(source.suffix == ".gz"), tick=np.array(TICKS[symbol]))
    features(arrays, symbol, session)
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(destination, **arrays)
    aligned_path = output / "packet_aligned" / (stem + ".npz")
    aligned_path.parent.mkdir(parents=True, exist_ok=True)
    packet_proof = align_packet(arrays, symbol, session, packets[session], aligned_path) if session in packets else None
    t, same = arrays["time_s"], arrays["price_clock_same"]
    normal_session = arrays["book_valid"] & arrays["in_session"]
    first_normal = np.flatnonzero(normal_session)
    finite = np.isfinite(t)
    step_positive = arrays["price_clock_step_seconds"][arrays["price_clock_step_seconds"] > 0]
    group_starts = np.flatnonzero(~same)
    group_lengths = np.diff(np.r_[group_starts, n])
    finite_group = finite[group_starts]
    volume_lead = arrays["volume_time_lead_seconds"]
    same_normal = same & arrays["adjacent_book_valid"] & arrays["in_session"]
    coverage = {"symbol": symbol, "session": session, "source_path": str(source.resolve()), "source_sha256": source_sha,
        "all_uncompressed_lines_sha256": digest.hexdigest(), "source_bytes": before.st_size, "source_mtime_ns": before.st_mtime_ns,
        "uncompressed_bytes_read": byte_offset, "rows_read": n, "all_lines_parsed_or_recorded": len(valid_json) == n,
        "offset_contiguous": bool(np.all(arrays["byte_offset"][1:] == arrays["byte_offset"][:-1] + arrays["byte_length"][:-1])),
        "unchanged_during_read": True, "invalid_json_count": len(invalid), "invalid_json_seq": invalid[:50],
        "clock_fields_found": sorted(time_fields), "independent_receive_clock_present": False,
        "price_clock_null_rows": int((~finite).sum()), "volume_clock_null_rows": int((~np.isfinite(arrays["volume_time_s"])).sum()),
        "normal_book_rows": int(arrays["book_valid"].sum()), "normal_book_with_null_price_clock": int((arrays["book_valid"] & ~finite).sum()),
        "in_session_price_clock_rows": int(arrays["in_session"].sum()), "normal_in_session_rows": int(normal_session.sum()),
        "first_normal_in_session_board": row_point(arrays, int(first_normal[0])) if len(first_normal) else None,
        "last_normal_in_session_board": row_point(arrays, int(first_normal[-1])) if len(first_normal) else None,
        "same_price_clock_steps": int(same.sum()), "same_price_clock_book_changed": int((same & arrays["book_changed"]).sum()),
        "same_price_clock_bbo_changed": int((same & arrays["bbo_changed"]).sum()),
        "same_price_clock_bbo_price_changed": int((same & arrays["bbo_price_changed"]).sum()),
        "same_price_clock_volume_increased": int((same & (arrays["volume_delta"] > 0)).sum()),
        "normal_session_same_clock_steps": int(same_normal.sum()),
        "normal_session_same_clock_book_changes": int((same_normal & arrays["book_changed"]).sum()),
        "normal_session_same_clock_book_change_fraction": float((same_normal & arrays["book_changed"]).sum() / same_normal.sum()) if same_normal.any() else None,
        "max_same_price_clock_consecutive_rows": int(group_lengths[finite_group].max()) if finite_group.any() else 0,
        "price_clock_backward_steps": int(arrays["price_clock_backward"].sum()),
        "price_clock_positive_step_seconds": {str(q): float(np.quantile(step_positive, q)) for q in [0.5, 0.9, 0.99, 1.0]} if len(step_positive) else {},
        "volume_clock_newer_than_price_clock_rows": int(np.count_nonzero(volume_lead > 0)),
        "volume_clock_older_than_price_clock_rows": int(np.count_nonzero(volume_lead < 0)), "volume_resets": int(arrays["volume_reset"].sum()),
        "packet": packet_proof, "raw_features": str(destination), "raw_features_sha256": file_hash(destination),
        "seconds": time.monotonic() - started, "financial_replays": 0,
        "limitations": ["価格時計は最終価格の公表時刻であり、板受信時刻ではない。時計不変の板は原行順のみ保証できる。",
          "同一価格数量の増減は可視板の差分。新規注文・取消・約定・隠れた補充を区別できない。",
          "10段から見えなくなった価格を撤退と数えない。増減は両行で同一価格が見える部分だけ。",
          "出来高増分は公表累計の差分であり、同時行の買い・売り約定数量ではない。",
          "原文0始まりseqと人間向け1始まりline_noを併記する。日付・価格時計の補正や並べ替えはしていない。"]}
    save_json(coverage_path, coverage)
    excerpt_path = output / "excerpts" / (stem + "_first2.jsonl")
    excerpt_path.parent.mkdir(parents=True, exist_ok=True)
    with excerpt_path.open("xb") as stream:
        stream.writelines(first_two)
    print(f"{stem}: 全{n:,}行保存・packet照合完了 ({coverage['seconds']:.1f}秒)", flush=True)
    return coverage


def excerpt(npz: Path, seq: int, count: int, destination: Path | None) -> None:
    """原位置から指定行の全文を取り出し、各行SHAで同一性を確認する。

    引数: npz(Path)、seq/count(int)は原配列と0始まり開始・行数、destination(Path|None)は保存先。
    返り値: None。保存先なしなら標準出力へ原文を出す。
    """
    with np.load(npz, allow_pickle=False) as data:
        source = Path(str(data["source_path"]))
        assert source.stat().st_size == int(data["source_size"])
        assert source.stat().st_mtime_ns == int(data["source_mtime_ns"])
        assert 0 <= seq < len(data["seq"]) and count > 0
        opener = gzip.open if bool(data["offset_is_uncompressed"]) else open
        chunks = []
        with opener(source, "rb") as stream:
            for index in range(seq, min(seq + count, len(data["seq"]))):
                stream.seek(int(data["byte_offset"][index]))
                raw = stream.read(int(data["byte_length"][index]))
                assert hashlib.sha256(raw).digest() == data["line_sha256"][index].tobytes(), index
                chunks.append(raw)
        if destination is None:
            sys.stdout.buffer.write(b"".join(chunks))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.writelines(chunks)


def main() -> None:
    """全原板走査又は原文抜粋をCLIから実行する。

    引数: CLIのscan/excerptサブコマンド。
    返り値: None。原板と過去成果は読み取り専用。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="指定原板を全行走査")
    scan.add_argument("--data-root", type=Path, default=DATA)
    scan.add_argument("--output", type=Path, default=HERE)
    scan.add_argument("--sessions", nargs="+", default=SCENES)
    scan.add_argument("--symbols", nargs="+", default=["NK225", "TOPIX"], choices=list(TICKS))
    extract = sub.add_parser("excerpt", help="0始まりseqから原文取得")
    extract.add_argument("--npz", type=Path, required=True)
    extract.add_argument("--seq", type=int, required=True)
    extract.add_argument("--count", type=int, default=1)
    extract.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "excerpt":
        excerpt(args.npz, args.seq, args.count, args.output)
        return
    packets = packet_paths()
    records = []
    for session in args.sessions:
        for symbol in args.symbols:
            records.append(scan_one(args.data_root, args.output, symbol, session, packets))
    save_json(args.output / "coverage_all141.json", {"complete": True, "files": len(records), "rows_read": sum(row["rows_read"] for row in records),
        "uncompressed_bytes_read": sum(row["uncompressed_bytes_read"] for row in records), "financial_replays": 0,
        "script_sha256": file_hash(Path(__file__)), "records": records})


if __name__ == "__main__":
    main()
