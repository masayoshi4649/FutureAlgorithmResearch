"""保存生板から、次の取引時刻を待って解放する因果的特徴を作成する。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "features"
JST = timezone(timedelta(hours=9))
TICKS = {"NK225": 10.0, "TOPIX": 0.5}
SUM_COLUMNS = [
    "ofi_signed", "ofi_abs", "quote_up", "quote_down", "quote_move_ticks",
    "added_bid", "removed_bid", "added_ask", "removed_ask",
    "trade_pos", "trade_neg", "trade_unknown",
]
MEAN_COLUMNS = ["imb1", "imb5", "imb10", "micro_bias"]
COLUMNS = [
    "time", "time_s", "seq", "source_time", "source_time_s",
    "source_first_seq", "source_last_seq", "source_mid_last", "source_bid_last", "source_ask_last",
    "bid", "ask", "bid_qty", "ask_qty",
    "mid", "spread_ticks", "raw_event_count", "valid_event_count",
    *MEAN_COLUMNS, *SUM_COLUMNS, "block_delay_seconds", "continuity_reset_count",
]


def session_bounds(session: str) -> tuple[datetime, datetime]:
    """対象セッションの通常監視区間を求める。

    引数: session (str): 日付と Day/Night を含む識別子。
    返り値: tuple[datetime, datetime]: 日本時間の開始時刻と排他的終了時刻。
    """
    date_text, kind = session.rsplit("_", 1)
    day = datetime.fromisoformat(date_text).replace(tzinfo=JST)
    if kind == "Day":
        return day + timedelta(hours=8, minutes=45), day + timedelta(hours=15, minutes=40)
    if kind == "Night":
        return day + timedelta(hours=17), day + timedelta(days=1, hours=5, minutes=55)
    raise ValueError(f"未知のセッション種別: {session}")


def number(value: object, default: float = 0.0) -> float:
    """JSON値を有限の数値へ変換する。

    引数: value (object): 変換対象。default (float): 欠損・不正値の代替値。
    返り値: float: 有限の数値または代替値。
    """
    try:
        result = float(value)
        return result if np.isfinite(result) else default
    except (TypeError, ValueError):
        return default


@dataclass
class Snapshot:
    """有効な現在板と、数量差分に必要な最小項目を保持する。"""

    bid: float
    ask: float
    bid_qty: float
    ask_qty: float
    bids: dict[float, float]
    asks: dict[float, float]
    imb1: float
    imb5: float
    imb10: float
    micro_bias: float
    last: float
    volume: float


def parse_snapshot(raw: dict) -> tuple[Snapshot | None, str]:
    """Buy1を買い気配、Sell1を売り気配として有効な板を抽出する。

    引数: raw (dict): 生板JSONの一行。
    返り値: tuple[Snapshot | None, str]: 有効板と空文字、またはNoneと除外理由。
    """
    bid_levels = []
    ask_levels = []
    for side, target in (("Buy", bid_levels), ("Sell", ask_levels)):
        for depth in range(1, 11):
            value = raw.get(f"{side}{depth}") or {}
            price, qty = number(value.get("Price")), number(value.get("Qty"))
            target.append((price, qty) if price > 0 and qty >= 0 else (0.0, 0.0))
    bid, bid_qty = bid_levels[0]
    ask, ask_qty = ask_levels[0]
    if bid <= 0 or ask <= 0 or bid_qty <= 0 or ask_qty <= 0:
        return None, "価格または最良数量不正"
    if bid == ask:
        return None, "ロック板"
    if bid > ask:
        return None, "交差板"
    imbalances = []
    for depth in (1, 5, 10):
        buy = sum(q for p, q in bid_levels[:depth] if p > 0)
        sell = sum(q for p, q in ask_levels[:depth] if p > 0)
        imbalances.append((buy - sell) / (buy + sell) if buy + sell else 0.0)
    mid = (bid + ask) / 2
    microprice = (ask * bid_qty + bid * ask_qty) / (bid_qty + ask_qty)
    return Snapshot(
        bid, ask, bid_qty, ask_qty,
        {p: q for p, q in bid_levels[:5] if p > 0},
        {p: q for p, q in ask_levels[:5] if p > 0},
        *imbalances, (microprice - mid) / (ask - bid),
        number(raw.get("CurrentPrice")), number(raw.get("TradingVolume")),
    ), ""


@dataclass
class Block:
    """同一取引時刻の連続ブロック内で、後続時刻まで封印する特徴を保持する。"""

    time: datetime
    first_seq: int
    last_seq: int
    raw_count: int = 0
    valid_count: int = 0
    resets: int = 0
    last_snapshot: Snapshot | None = None
    latest_volume_time: datetime | None = None
    values: dict[str, float] = field(default_factory=lambda: {k: 0.0 for k in MEAN_COLUMNS + SUM_COLUMNS})


def quantity_changes(previous: dict[float, float], current: dict[float, float]) -> tuple[float, float]:
    """上位五段に共通して存在する価格の数量増加と減少を合計する。

    引数: previous (dict[float, float]): 前回板。current (dict[float, float]): 今回板。
    返り値: tuple[float, float]: 増加数量と減少数量の非負合計。
    """
    differences = [current[p] - previous[p] for p in previous.keys() & current.keys()]
    return sum(max(d, 0) for d in differences), sum(max(-d, 0) for d in differences)


def add_snapshot(block: Block, current: Snapshot, previous: Snapshot | None, tick: float, direction: int) -> int:
    """現在行をブロックの集計へ加算し、最終の非ゼロ価格変化方向を更新する。

    引数: block (Block): 集計先。current (Snapshot): 現在板。previous (Snapshot | None): 直前有効板。
    tick (float): 呼値。direction (int): tick-ruleの直近非ゼロ方向。
    返り値: int: 更新されたtick-rule方向。出来高分類は真の買い手・売り手主導情報ではない。
    """
    block.valid_count += 1
    block.last_snapshot = current
    for key in MEAN_COLUMNS:
        block.values[key] += getattr(current, key)
    if previous is None:
        return 0

    # ----------------------------------------
    # 最良気配の標準OFIと、同じ価格に残っている数量の増減を集計する。
    ofi = (
        (current.bid >= previous.bid) * current.bid_qty
        - (current.bid <= previous.bid) * previous.bid_qty
        - (current.ask <= previous.ask) * current.ask_qty
        + (current.ask >= previous.ask) * previous.ask_qty
    )
    block.values["ofi_signed"] += ofi
    block.values["ofi_abs"] += abs(ofi)
    block.values["quote_up"] += int(current.bid > previous.bid) + int(current.ask > previous.ask)
    block.values["quote_down"] += int(current.bid < previous.bid) + int(current.ask < previous.ask)
    block.values["quote_move_ticks"] += (current.bid + current.ask - previous.bid - previous.ask) / (2 * tick)
    for side, previous_map, current_map in (("bid", previous.bids, current.bids), ("ask", previous.asks, current.asks)):
        added, removed = quantity_changes(previous_map, current_map)
        block.values[f"added_{side}"] += added
        block.values[f"removed_{side}"] += removed

    # ----------------------------------------
    # 累積出来高増分を直近非ゼロ約定価格変化で分類する。
    if current.last > 0 and previous.last > 0:
        price_change = current.last - previous.last
        if price_change:
            direction = 1 if price_change > 0 else -1
        volume_change = current.volume - previous.volume
        if volume_change > 0:
            key = "trade_pos" if direction > 0 else "trade_neg" if direction < 0 else "trade_unknown"
            block.values[key] += volume_change
        elif volume_change < 0:
            direction = 0
    return direction


def release_row(block: Block, time: datetime, seq: int, current: Snapshot, tick: float) -> dict:
    """次時刻の先頭行で、過去ブロック特徴と現在の発注評価用気配を出力する。

    引数: block (Block): 解放する過去集計。time (datetime): 次時刻。seq (int): 次時刻の先頭行番号。
    current (Snapshot): 次時刻の先頭板。tick (float): 呼値。
    返り値: dict: 特徴最終参照行が発注評価行より前となる一行。
    """
    assert block.last_seq < seq and block.time < time
    assert block.last_snapshot is not None
    if block.latest_volume_time is not None and block.latest_volume_time > time:
        raise ValueError(f"出来高時刻が特徴解放時刻より未来: {block.latest_volume_time} > {time}, 行={seq}")
    result = {
        "time": time.isoformat(), "time_s": time.timestamp(), "seq": seq,
        "source_time": block.time.isoformat(), "source_time_s": block.time.timestamp(),
        "source_first_seq": block.first_seq, "source_last_seq": block.last_seq,
        "source_mid_last": (block.last_snapshot.bid + block.last_snapshot.ask) / 2,
        "source_bid_last": block.last_snapshot.bid, "source_ask_last": block.last_snapshot.ask,
        "bid": current.bid, "ask": current.ask, "bid_qty": current.bid_qty, "ask_qty": current.ask_qty,
        "mid": (current.bid + current.ask) / 2, "spread_ticks": (current.ask - current.bid) / tick,
        "raw_event_count": block.raw_count, "valid_event_count": block.valid_count,
        "block_delay_seconds": (time - block.time).total_seconds(), "continuity_reset_count": block.resets,
    }
    for key in MEAN_COLUMNS:
        result[key] = block.values[key] / block.valid_count
    for key in SUM_COLUMNS:
        result[key] = block.values[key]
    return result


def extract_features(path: Path, symbol: str, session: str, max_rows: int | None = None, quotes: list[dict] | None = None) -> tuple[pd.DataFrame, dict]:
    """生板を一方向に走査し、未確定末尾ブロックを捨てて特徴を返す。

    引数: path (Path): 保存生板パス。symbol (str): 銘柄。session (str): セッション識別子。
    max_rows (int | None): 原本の先頭から読む最大行数。Noneなら全件。
    quotes (list[dict] | None): 指定時に全有効raw気配を追記する出力用リスト。
    返り値: tuple[pd.DataFrame, dict]: 因果的特徴表と原本ハッシュ・除外件数などの監査情報。
    """
    start, end = session_bounds(session)
    tick = TICKS[symbol]
    rows = []
    previous_time = None
    previous_snapshot = None
    previous_direction = 0
    block = None
    hasher = hashlib.sha256()
    audit = {
        "銘柄": symbol, "セッション": session, "原本": str(path.resolve()),
        "読取行数": 0, "対象時間外行数": 0, "時刻欠損行数": 0,
        "対象内行数": 0, "ブロック数": 0, "有効板行数": 0,
        "直前有効行と同じ抽出snapshot数": 0,
        "出来高時刻が同じ行の取引時刻より未来の行数": 0,
        "出来高時刻が同じ行の取引時刻より未来の最大秒": 0.0,
        "不正板理由": {}, "解放時板不正で省略": 0, "過去ブロック全行不正で省略": 0,
        "途中打切り最大行数": max_rows,
    }
    with path.open("rb") as handle:
        for seq, line in enumerate(handle):
            if max_rows is not None and seq >= max_rows:
                break
            hasher.update(line)
            audit["読取行数"] += 1
            raw = json.loads(line)
            stamp = raw.get("CurrentPriceTime")
            if not stamp:
                audit["時刻欠損行数"] += 1
                previous_snapshot = None
                previous_direction = 0
                continue
            time = datetime.fromisoformat(stamp)
            if time.tzinfo is None:
                raise ValueError(f"タイムゾーンのない時刻: {path}:{seq + 1}")
            time = time.astimezone(JST)
            if previous_time is not None and time < previous_time:
                raise ValueError(f"時刻逆行: {path}:{seq + 1}: {previous_time} → {time}")
            previous_time = time
            if not start <= time < end:
                audit["対象時間外行数"] += 1
                previous_snapshot = None
                previous_direction = 0
                continue
            audit["対象内行数"] += 1
            current, reason = parse_snapshot(raw)
            if block is None or time != block.time:
                if block is not None:
                    if block.valid_count == 0:
                        audit["過去ブロック全行不正で省略"] += 1
                    elif current is None:
                        audit["解放時板不正で省略"] += 1
                    else:
                        rows.append(release_row(block, time, seq, current, tick))
                block = Block(time, seq, seq)
                audit["ブロック数"] += 1
            block.last_seq = seq
            block.raw_count += 1
            volume_stamp = raw.get("TradingVolumeTime")
            if volume_stamp:
                volume_time = datetime.fromisoformat(volume_stamp)
                if volume_time.tzinfo is None:
                    raise ValueError(f"タイムゾーンのない出来高時刻: {path}:{seq + 1}")
                volume_time = volume_time.astimezone(JST)
                if block.latest_volume_time is None or volume_time > block.latest_volume_time:
                    block.latest_volume_time = volume_time
                if volume_time > time:
                    audit["出来高時刻が同じ行の取引時刻より未来の行数"] += 1
                    audit["出来高時刻が同じ行の取引時刻より未来の最大秒"] = max(
                        audit["出来高時刻が同じ行の取引時刻より未来の最大秒"],
                        (volume_time - time).total_seconds(),
                    )
            if current is None:
                audit["不正板理由"][reason] = audit["不正板理由"].get(reason, 0) + 1
                block.resets += 1
                previous_snapshot = None
                previous_direction = 0
                continue
            audit["有効板行数"] += 1
            if previous_snapshot == current:
                audit["直前有効行と同じ抽出snapshot数"] += 1
            if quotes is not None:
                quotes.append({
                    "seq": seq, "time_s": time.timestamp(),
                    "bid": current.bid, "ask": current.ask, "bid_qty": current.bid_qty, "ask_qty": current.ask_qty,
                    "mid": (current.bid + current.ask) / 2, "spread_ticks": (current.ask - current.bid) / tick,
                })
            previous_direction = add_snapshot(block, current, previous_snapshot, tick, previous_direction)
            previous_snapshot = current

    # ----------------------------------------
    # 最終ブロックは同じ時刻の行が追加される可能性があるため、出力しない。
    frame = pd.DataFrame(rows, columns=COLUMNS)
    audit.update({
        "原本SHA256": hasher.hexdigest(), "特徴行数": len(frame),
        "未解放末尾ブロック時刻": block.time.isoformat() if block is not None else None,
        "未解放末尾ブロック行数": block.raw_count if block is not None else 0,
        "最初の解放時刻": frame["time"].iloc[0] if len(frame) else None,
        "最後の解放時刻": frame["time"].iloc[-1] if len(frame) else None,
        "最大解放遅延秒": float(frame["block_delay_seconds"].max()) if len(frame) else None,
        "中央値解放遅延秒": float(frame["block_delay_seconds"].median()) if len(frame) else None,
        "特徴参照行が評価行より前": bool((frame["source_last_seq"] < frame["seq"]).all()),
        "特徴参照時刻が評価時刻より前": bool((frame["source_time_s"] < frame["time_s"]).all()),
        "時刻単調増加": bool(frame["time_s"].is_monotonic_increasing),
        "出来高時刻が解放時刻以下": True,
        "気配用途": "bid/ask等は解放時の先頭板。方向特徴はその前の確定ブロックのみ。",
        "平均の重複処理": "imb1/5/10とmicro_biasは有効raw行のイベント平均であり同じsnapshotの再出現も含む。時間平均ではない。同一snapshotはOFIや数量差分を増やさない。",
        "独立でない特徴": "micro_biasは定義上imb1の半分であり、別の独立した情報ではない。",
        "不正板処理": "locked/crossed/最良気配数量不正を除外し、差分とtick-rule方向をリセット。不正行を跨いだ数量差分を作らない。解放時板不正ではその過去ブロックの出力を省略。",
        "時刻の限界": "受信時刻がなくCurrentPriceTimeを時間の近似に用いる。同じ時刻の連続ブロックは次時刻先頭まで封印し、最後のブロックは破棄する。",
        "出来高と数量の限界": "trade_pos/negはtick-rule推定で真のaggressorではない。板数量減少を取消と約定に分離できない。上位5段で共通して見える同じ価格だけ数量差分を計算する。",
    })
    if len(frame):
        numeric = frame.select_dtypes(include="number").to_numpy()
        if not np.isfinite(numeric).all():
            raise AssertionError("非有限の特徴値を検出")
    return frame, audit


def sources() -> Iterable[tuple[Path, str, str]]:
    """保存済み五セッションと前回保存した未完了ナイトの入力を列挙する。

    引数: なし。
    返り値: Iterable[tuple[Path, str, str]]: 原本パス・銘柄・セッションの列。
    """
    for symbol in TICKS:
        for path in sorted((ROOT / "book" / symbol).glob("*.jsonl")):
            yield path, symbol, path.stem
        live = ROOT / "work" / "wave_v7" / "live" / "book" / symbol / "2026-09-23_Night.jsonl"
        if live.exists():
            yield live, symbol, live.stem


def write_features(frame: pd.DataFrame, audit: dict, directory: Path = OUT, quotes: list[dict] | None = None) -> None:
    """特徴CSV・NPZと監査JSONを指定された作業ディレクトリに保存する。

    引数: frame (pd.DataFrame): 因果的特徴。audit (dict): 監査情報。directory (Path): 保存先。
    quotes (list[dict] | None): 全有効raw気配。指定時は既存注文監視用の別NPZを保存する。
    返り値: None。各NPZキーはCSV列名と同じで、銘柄ごとの呼値をtickに追加する。
    """
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{audit['銘柄']}_{audit['セッション']}"
    csv_path = directory / f"{stem}.csv"
    npz_path = directory / f"{stem}.npz"
    frame.to_csv(csv_path, index=False, encoding="utf-8")
    arrays = {column: frame[column].to_numpy(dtype=str) if column in ("time", "source_time") else frame[column].to_numpy() for column in frame.columns}
    arrays["tick"] = np.array(TICKS[audit["銘柄"]])
    np.savez_compressed(npz_path, **arrays)
    audit["特徴CSV_SHA256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    audit["特徴NPZ_SHA256"] = hashlib.sha256(npz_path.read_bytes()).hexdigest()
    if quotes is not None:
        quote_path = directory / f"約定系列_{stem}.npz"
        quote_frame = pd.DataFrame(quotes)
        np.savez_compressed(quote_path, **{key: quote_frame[key].to_numpy() for key in quote_frame.columns}, tick=np.array(TICKS[audit["銘柄"]]))
        audit["約定系列行数"] = len(quote_frame)
        audit["約定系列NPZ_SHA256"] = hashlib.sha256(quote_path.read_bytes()).hexdigest()
        audit["約定系列説明"] = "対象時間内の全有効raw気配を原本順で保存。未解放末尾block内の気配も含み、既存注文の監視に利用可能。新しい方向特徴の解放は特徴表のseqに限定する。"
    (directory / f"{stem}_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    """任意の銘柄・セッション条件で保存データだけから特徴を生成する。

    引数: なし。CLIの--symbol/--session/--outputで対象と保存先を指定できる。
    返り値: None。原本を変更せずAPIへ接続しない。
    """
    parser = argparse.ArgumentParser(description="保存板を未来参照せずブロック特徴へ変換")
    parser.add_argument("--symbol", choices=list(TICKS))
    parser.add_argument("--session")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    summaries = []
    for path, symbol, session in sources():
        if args.symbol and symbol != args.symbol or args.session and session != args.session:
            continue
        quotes = []
        frame, audit = extract_features(path, symbol, session, quotes=quotes)
        write_features(frame, audit, args.output, quotes=quotes)
        summaries.append(audit)
        print(json.dumps({"銘柄": symbol, "セッション": session, "原本行数": audit["読取行数"], "特徴行数": len(frame), "不正板": audit["不正板理由"]}, ensure_ascii=False), flush=True)
    if not args.symbol and not args.session:
        (args.output / "全入力監査.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
