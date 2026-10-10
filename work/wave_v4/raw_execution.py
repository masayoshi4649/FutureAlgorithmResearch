"""受信時刻を持たない保存生板から保守的な利用可能観測系列を作る。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
FIELDS = [
    "instrument", "session", "available_at", "source_trade_time", "source_row",
    "release_sequence", "last_price", "bid", "ask", "bid_qty", "ask_qty",
    "spread", "quote_valid", "volume", "volume_delta", "staleness_seconds",
]


def finite(value: object) -> float | None:
    """有限な数値だけを観測値として受け入れる。

    引数: value（object）検査対象。
    返り値: float | None。有限値または欠損。
    """
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def session_bounds(path: Path) -> tuple[datetime, datetime]:
    """保存一分足に対応する範囲を取得する。

    引数: path（Path）保存生板のパス。
    返り値: tuple[datetime, datetime]。開始と排他的終了。
    """
    candle_path = ROOT / "candle_1min" / path.parent.name / (path.stem + ".csv")
    with candle_path.open(encoding="utf-8-sig", newline="") as stream:
        stamps = [datetime.fromisoformat(row["time"]) for row in csv.DictReader(stream)]
    return min(stamps), max(stamps) + timedelta(minutes=1)


class ObservationExtractor:
    """同約定時刻のブロックを次の時刻で解放し、保存順序を保持する。"""

    def __init__(self, start: datetime, end: datetime):
        """セッションごとに抽出状態を初期化する。

        引数: start・end（datetime）開始と排他的終了。
        返り値: None。
        """
        self.start, self.end = start, end
        self.anchor = None
        self.block = []
        self.counts = Counter()
        self.delays = []
        self.previous_signature = None
        self.previous_volume = None
        self.sequence = 0

    def accept(self, row: dict, source_row: int) -> list[dict]:
        """一行を追加し、次時刻の到来時だけ既存ブロックを返す。

        引数: row（dict）元の生板一行、source_row（int）一始まりの元行番号。
        返り値: list[dict]。今回利用可能になった観測行。
        """
        self.counts["raw_rows"] += 1
        value = row.get("CurrentPriceTime")
        if not value:
            self.counts["missing_time"] += 1
            return []
        try:
            stamp = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            self.counts["invalid_time"] += 1
            return []
        if stamp.tzinfo is None or not self.start <= stamp < self.end:
            self.counts["outside_session"] += 1
            return []
        if self.anchor is not None and stamp < self.anchor:
            raise ValueError("約定時刻が逆行したため、観測系列の生成を停止")
        observations = []
        if self.anchor is not None and stamp > self.anchor:
            observations = self.release(stamp)
            self.block = []
        self.anchor = stamp
        self.block.append((source_row, row))
        return observations

    def release(self, available: datetime) -> list[dict]:
        """旧ブロックの全観測を新時刻へ遅延させ、変化した行を順番に返す。

        引数: available（datetime）次ブロックの約定時刻。
        返り値: list[dict]。同じ利用可能時刻内も保存順を保った観測列。
        """
        assert available > self.anchor
        stale = (available - self.anchor).total_seconds()
        self.delays.append(stale)
        self.counts["released_blocks"] += 1
        result = []
        for source_row, row in self.block:
            price, volume = finite(row.get("CurrentPrice")), finite(row.get("TradingVolume"))
            volume_time = row.get("TradingVolumeTime")
            if volume_time and datetime.fromisoformat(volume_time) > available:
                raise ValueError("累積出来高の時刻が利用可能時刻より未来")
            buy, sell = row.get("Buy1") or {}, row.get("Sell1") or {}
            bid, ask = finite(buy.get("Price")), finite(sell.get("Price"))
            bid_qty, ask_qty = finite(buy.get("Qty")), finite(sell.get("Qty"))
            valid = (None not in (bid, ask, bid_qty, ask_qty)
                     and 0 < bid < ask and bid_qty > 0 and ask_qty > 0)
            signature = (price, bid, ask, bid_qty, ask_qty, volume)
            self.counts["released_rows"] += 1
            if signature == self.previous_signature:
                self.counts["unchanged_observation"] += 1
                continue
            self.previous_signature = signature
            change = 0.0
            if volume is not None:
                if self.previous_volume is not None:
                    if volume >= self.previous_volume:
                        change = volume - self.previous_volume
                    else:
                        self.counts["volume_resets"] += 1
                self.previous_volume = volume
            self.sequence += 1
            result.append({
                "available_at": available.isoformat(),
                "source_trade_time": self.anchor.isoformat(), "source_row": source_row,
                "release_sequence": self.sequence, "last_price": price,
                "bid": bid, "ask": ask, "bid_qty": bid_qty, "ask_qty": ask_qty,
                "spread": ask - bid if valid else None, "quote_valid": valid,
                "volume": volume, "volume_delta": change, "staleness_seconds": stale,
            })
            self.counts["valid_quotes" if valid else "invalid_quotes"] += 1
        return result

    def audit(self) -> dict:
        """末尾未確定ブロックと遅延分布を含む監査情報を返す。

        引数: なし。
        返り値: dict。行数と時刻解放に伴う遅延の情報。
        """
        delays = sorted(self.delays)
        return {
            **dict(self.counts), "discarded_final_rows": len(self.block),
            "observations": self.sequence,
            "delay_median_seconds": median(delays) if delays else None,
            "delay_p95_seconds": delays[int(.95 * (len(delays) - 1))] if delays else None,
            "delay_max_seconds": max(delays) if delays else None,
            "delay_over_60_seconds_blocks": sum(value > 60 for value in delays),
        }


def extract(path: Path, destination: Path) -> dict:
    """元ファイルを変更せず、観測系列を指定ＣＳＶへストリーム保存する。

    引数: path（Path）元生板、destination（Path）work配下の出力先。
    返り値: dict。入力ハッシュと出力範囲を含む監査。
    """
    start, end = session_bounds(path)
    extractor = ObservationExtractor(start, end)
    digest = hashlib.sha256()
    destination.parent.mkdir(parents=True, exist_ok=True)
    first_available, last_available = None, None
    with path.open("rb") as stream, destination.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        for source_row, line in enumerate(stream, 1):
            digest.update(line)
            for event in extractor.accept(json.loads(line), source_row):
                event.update({"instrument": path.parent.name, "session": path.stem})
                writer.writerow(event)
                first_available = first_available or event["available_at"]
                last_available = event["available_at"]
    return {
        "instrument": path.parent.name, "session": path.stem,
        "source": str(path.relative_to(ROOT)), "source_sha256": digest.hexdigest(),
        "output": str(destination.relative_to(ROOT)), "start": start.isoformat(),
        "end_exclusive": end.isoformat(), "first_available": first_available,
        "last_available": last_available, **extractor.audit(),
    }


def read_observations(path: Path) -> list[dict]:
    """利用可能時刻順の観測系列を型付きで読み込む。

    引数: path（Path）extractが生成したＣＳＶ。
    返り値: list[dict]。datetime、float、boolへ変換済みの観測行。
    """
    result = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            for key in ("available_at", "source_trade_time"):
                row[key] = datetime.fromisoformat(row[key])
            for key in ("source_row", "release_sequence"):
                row[key] = int(row[key])
            row["quote_valid"] = row["quote_valid"].lower() == "true"
            for key in ("last_price", "bid", "ask", "bid_qty", "ask_qty", "spread", "volume", "volume_delta", "staleness_seconds"):
                row[key] = float(row[key]) if row[key] else None
            result.append(row)
    return result


def quote_near_time(events: list[dict], stamp: datetime, max_stale_seconds: float = 60) -> dict | None:
    """指定時刻以前に利用可能になった最新の有効気配を探す。

    引数: events（list[dict]）観測列、stamp（datetime）照合時刻、max_stale_seconds（float）許容する価格時刻からの経過秒。
    返り値: dict | None。利用可能な最新気配または該当なし。実約定可能性は保証しない。
    """
    result = None
    for event in events:
        if event["available_at"] > stamp:
            break
        if event["quote_valid"] and (stamp - event["source_trade_time"]).total_seconds() <= max_stale_seconds:
            result = event
    if result and (stamp - result["source_trade_time"]).total_seconds() > max_stale_seconds:
        return None
    return result


def fixed_trail_observation(events: list[dict], entry_time: datetime, side: int, entry_price: float,
                            distance: float, end_time: datetime, trigger: str = "last_price") -> dict:
    """既知の新規時刻以後の保存順で固定幅トレーリング条件の初回成立を監査する。

    引数: events（list[dict]）観測列、entry_time・end_time（datetime）範囲、side（int）買い１・売り－１、entry_price・distance（float）基準価格と追跡幅、trigger（str）last_priceまたはquote。
    返り値: dict。初回成立、古い気配の程度、該当なしの状態。条件成立の観測であり実約定ではない。
    """
    if side not in (-1, 1) or distance <= 0 or trigger not in ("last_price", "quote"):
        raise ValueError("方向・追跡幅・条件参照価格が不正")
    extreme, count, max_stale = entry_price, 0, 0.0
    for event in events:
        if event["available_at"] <= entry_time:
            continue
        if event["available_at"] > end_time:
            break
        value = event["last_price"] if trigger == "last_price" else event["bid" if side == 1 else "ask"]
        if value is None or (trigger == "quote" and not event["quote_valid"]):
            continue
        count += 1
        max_stale = max(max_stale, event["staleness_seconds"])
        stop = extreme - side * distance
        if side * (value - stop) <= 0:
            return {"triggered": True, "trigger": trigger, "observed_at": event["available_at"].isoformat(),
                    "source_trade_time": event["source_trade_time"].isoformat(),
                    "source_row": event["source_row"], "trigger_price": value, "stop_price": stop,
                    "bid": event["bid"], "ask": event["ask"], "quote_valid": event["quote_valid"],
                    "staleness_seconds": event["staleness_seconds"], "observations": count,
                    "max_staleness_seconds": max_stale}
        if side * value > side * extreme:
            extreme = value
    return {"triggered": False, "trigger": trigger, "observations": count,
            "final_stop_price": extreme - side * distance, "max_staleness_seconds": max_stale}


def self_test() -> None:
    """次時刻解放・板方向・末尾破棄・先読み拒否と追跡順を検証する。

    引数: なし。
    返り値: None。不整合時は例外を送出する。
    """
    start = datetime.fromisoformat("2026-09-22T17:00:00+09:00")
    extractor = ObservationExtractor(start, start + timedelta(minutes=10))
    row = {"CurrentPriceTime": start.isoformat(), "CurrentPrice": 100.0, "TradingVolume": 1,
           "Buy1": {"Price": 99, "Qty": 2}, "Sell1": {"Price": 101, "Qty": 3}}
    assert extractor.accept(row, 1) == []
    changed = {**row, "CurrentPrice": 102.0, "TradingVolume": 2}
    assert extractor.accept(changed, 2) == []
    next_row = {**row, "CurrentPriceTime": (start + timedelta(seconds=60)).isoformat()}
    events = extractor.accept(next_row, 3)
    assert len(events) == 2 and [item["last_price"] for item in events] == [100, 102]
    assert all(item["available_at"] == next_row["CurrentPriceTime"] for item in events)
    assert events[0]["bid"] == 99 and events[0]["ask"] == 101
    assert extractor.audit()["discarded_final_rows"] == 1
    for event in events:
        event["available_at"] = datetime.fromisoformat(event["available_at"])
        event["source_trade_time"] = datetime.fromisoformat(event["source_trade_time"])
    trail = fixed_trail_observation(events, start, 1, 103, 2, start + timedelta(minutes=2))
    assert trail["triggered"] and trail["source_row"] == 1
    assert quote_near_time(events, start + timedelta(seconds=59)) is None
    assert quote_near_time(events, start + timedelta(seconds=60))["ask"] == 101
    assert quote_near_time(events, start + timedelta(seconds=121)) is None
    try:
        extractor.accept(row, 4)
    except ValueError:
        pass
    else:
        raise AssertionError("時刻逆行を拒否できていない")


def main() -> None:
    """保存夜間の観測系列と監査を生成する。

    引数: なし。コマンド行でセッション、銘柄、試験のみを指定できる。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="保存生板の利用可能時刻と保存順による観測系列")
    parser.add_argument("--session", default="2026-09-22_Night")
    parser.add_argument("--symbols", nargs="+", default=["NK225", "TOPIX"])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    self_test()
    if args.self_test:
        print("生板観測系列の基本検証に成功")
        return
    audits = []
    for symbol in args.symbols:
        audit = extract(ROOT / "book" / symbol / (args.session + ".jsonl"), OUT / f"生板観測_{symbol}_{args.session}.csv")
        audits.append(audit)
        print(f"抽出完了: {symbol} {args.session} {audit['observations']} 観測", flush=True)
    (OUT / f"生板観測監査_{args.session}.json").write_text(json.dumps(audits, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
