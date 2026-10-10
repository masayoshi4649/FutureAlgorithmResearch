"""生板を次の約定時刻まで遅延させて集約する、保存データ専用の特徴量抽出。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
FIELDS = [
    "instrument", "session", "time", "available_at", "book_mid_last",
    "microprice_last", "spread_median", "imbalance1_mean", "imbalance5_mean",
    "imbalance10_mean", "ofi_sum", "ofi_abs_sum", "ofi_norm", "top_depth_mean",
    "bid_up", "bid_down", "ask_up", "ask_down", "quote_direction",
    "mid_move_ticks", "signed_volume", "volume_delta", "signed_volume_ratio",
    "event_count", "quote_count", "price_change_count", "block_count",
    "anchor_delay_mean_seconds", "anchor_delay_max_seconds", "invalid_quote_count",
]


def number(value: object) -> float | None:
    """数値へ変換し有限性を確認する。

    引数: value（object）検査対象。
    返り値: float | None。有限値、または欠落を示す None。
    """
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def quote_values(row: dict) -> tuple | None:
    """売買十段の価格と数量を固定順序で取り出す。

    引数: row（dict）生板一行。
    返り値: tuple | None。買十段、売十段の価格数量、または欠落。
    """
    values = []
    for side in ("Buy", "Sell"):
        for level in range(1, 11):
            item = row.get(f"{side}{level}") or {}
            price, qty = number(item.get("Price")), number(item.get("Qty"))
            if price is None or qty is None or price <= 0 or qty < 0:
                return None
            values.extend((price, qty))
    return tuple(values)


def empty_minute() -> dict:
    """一分集約の初期状態を作る。

    引数: なし。
    返り値: dict。数値カウンターと標本配列を保持する状態。
    """
    state = defaultdict(float)
    for key in ("spread", "imbalance1", "imbalance5", "imbalance10", "depth", "delay"):
        state[key] = []
    state["book_mid_last"] = None
    state["microprice_last"] = None
    return state


class Extractor:
    """セッション内の順序と約定時刻による利用可能性を管理する。"""

    def __init__(self, start: datetime, end: datetime, tick: float):
        """抽出器をセッション単位で初期化する。

        引数: start・end（datetime）観測範囲の始端と排他的終端、tick（float）刻み。
        返り値: None。
        """
        self.start, self.end, self.tick = start, end, tick
        self.minutes = defaultdict(empty_minute)
        self.audit = Counter()
        self.block = []
        self.anchor = None
        self.previous_signature = None
        self.previous_quote = None
        self.previous_price = None
        self.previous_volume = None
        self.tick_direction = 0
        self.delays = []

    def accept(self, row: dict) -> None:
        """時刻が進んだ時点で前ブロックのみを利用可能にする。

        引数: row（dict）ファイル順の生板一行。
        返り値: None。
        """
        self.audit["raw_rows"] += 1
        value = row.get("CurrentPriceTime")
        if not value:
            self.audit["null_time_rows"] += 1
            return
        try:
            stamp = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            self.audit["bad_time_rows"] += 1
            return
        if stamp.tzinfo is None or not self.start <= stamp < self.end:
            self.audit["outside_session_rows"] += 1
            return
        if self.anchor is not None and stamp < self.anchor:
            raise ValueError("約定時刻の逆行を検出したため、先読み防止として抽出を停止")
        if self.anchor is not None and stamp > self.anchor:
            self.release(stamp)
            self.block = []
        self.anchor = stamp
        self.block.append(row)

    def release(self, available: datetime) -> None:
        """確定した一ブロックを次の約定時刻の一分枠へ集約する。

        引数: available（datetime）次ブロックの先頭約定時刻。
        返り値: None。
        """
        assert available > self.anchor
        minute = available.replace(second=0, microsecond=0)
        state = self.minutes[minute]
        delay = (available - self.anchor).total_seconds()
        state["block_count"] += 1
        state["delay"].append(delay)
        self.delays.append(delay)
        self.audit["released_blocks"] += 1
        for row in self.block:
            state["event_count"] += 1
            self.audit["released_rows"] += 1

            # ----------------------------------------
            # 約定方向推定と累積出来高差分。板数量とは独立して処理する。
            price = number(row.get("CurrentPrice"))
            volume = number(row.get("TradingVolume"))
            volume_time = row.get("TradingVolumeTime")
            if volume_time and datetime.fromisoformat(volume_time) > available:
                raise ValueError("累積出来高の時刻が利用可能時刻より未来")
            if price is not None and self.previous_price is not None and price != self.previous_price:
                self.tick_direction = 1 if price > self.previous_price else -1
                state["price_change_count"] += 1
            if price is not None:
                self.previous_price = price
            if volume is not None:
                if self.previous_volume is not None:
                    change = volume - self.previous_volume
                    if change >= 0:
                        state["volume_delta"] += change
                        state["signed_volume"] += change * self.tick_direction
                    else:
                        self.audit["volume_resets"] += 1
                        self.tick_direction = 0
                self.previous_volume = volume

            # ----------------------------------------
            # 同じ板の連続行は重複として除き、有効な売買十段を観測する。
            signature = quote_values(row)
            if signature is not None and signature == self.previous_signature:
                self.audit["consecutive_quote_duplicates"] += 1
                continue
            self.previous_signature = signature
            if signature is None:
                self.audit["missing_quote_rows"] += 1
                state["invalid_quote_count"] += 1
                self.previous_quote = None
                continue
            bid, bid_qty, ask, ask_qty = signature[0], signature[1], signature[20], signature[21]
            if ask <= bid or bid_qty + ask_qty <= 0:
                self.audit["locked_or_crossed_quotes"] += 1
                state["invalid_quote_count"] += 1
                self.previous_quote = None
                continue
            state["quote_count"] += 1
            self.audit["valid_quote_events"] += 1
            state["book_mid_last"] = (bid + ask) / 2
            state["microprice_last"] = (ask * bid_qty + bid * ask_qty) / (bid_qty + ask_qty)
            state["spread"].append(ask - bid)
            state["depth"].append(bid_qty + ask_qty)
            for depth in (1, 5, 10):
                buys = sum(signature[level * 2 + 1] for level in range(depth))
                sells = sum(signature[20 + level * 2 + 1] for level in range(depth))
                if buys + sells > 0:
                    state[f"imbalance{depth}"].append((buys - sells) / (buys + sells))

            # ----------------------------------------
            # 最良気配の変化と標準的な注文フロー不均衡を計算する。
            if self.previous_quote is not None:
                old_bid, old_bqty, old_ask, old_aqty = self.previous_quote
                ofi = ((bid >= old_bid) * bid_qty - (bid <= old_bid) * old_bqty
                       - (ask <= old_ask) * ask_qty + (ask >= old_ask) * old_aqty)
                state["ofi_sum"] += ofi
                state["ofi_abs_sum"] += abs(ofi)
                state["bid_up"] += bid > old_bid
                state["bid_down"] += bid < old_bid
                state["ask_up"] += ask > old_ask
                state["ask_down"] += ask < old_ask
                state["mid_move_ticks"] += ((bid + ask) - (old_bid + old_ask)) / (2 * self.tick)
            self.previous_quote = bid, bid_qty, ask, ask_qty

    def rows(self, instrument: str, session: str) -> list[dict]:
        """一分ごとの結果を出し、末尾の未確定ブロックを破棄する。

        引数: instrument（str）銘柄名、session（str）セッション識別子。
        返り値: list[dict]。時刻順の特徴量行。
        """
        result = []
        for minute, state in sorted(self.minutes.items()):
            end = minute + timedelta(minutes=1)
            if end > self.end:
                raise ValueError("特徴量の利用可能時刻が保存セッションを越えた")
            movement = sum(state[key] for key in ("bid_up", "bid_down", "ask_up", "ask_down"))
            row = {key: state[key] for key in FIELDS if key in state}
            row.update({
                "instrument": instrument, "session": session,
                "time": minute.isoformat(), "available_at": end.isoformat(),
                "spread_median": median(state["spread"]) if state["spread"] else None,
                "top_depth_mean": mean(state["depth"]) if state["depth"] else None,
                "ofi_norm": state["ofi_sum"] / state["ofi_abs_sum"] if state["ofi_abs_sum"] else 0,
                "quote_direction": (state["bid_up"] + state["ask_up"] - state["bid_down"] - state["ask_down"]) / movement if movement else 0,
                "signed_volume_ratio": state["signed_volume"] / state["volume_delta"] if state["volume_delta"] else 0,
                "anchor_delay_mean_seconds": mean(state["delay"]),
                "anchor_delay_max_seconds": max(state["delay"]),
            })
            for depth in (1, 5, 10):
                values = state[f"imbalance{depth}"]
                row[f"imbalance{depth}_mean"] = mean(values) if values else None
            for key in FIELDS:
                if key not in row:
                    row[key] = 0
            result.append(row)
        self.audit["discarded_final_block_rows"] = len(self.block)
        self.audit["feature_minutes"] = len(result)
        return result


def bounds(path: Path) -> tuple[datetime, datetime]:
    """対応する保存一分足から観測時間の範囲を得る。

    引数: path（Path）生板ファイルのパス。
    返り値: tuple[datetime, datetime]。始端と排他的終端。
    """
    candle = ROOT / "candle_1min" / path.parent.name / (path.stem + ".csv")
    with candle.open(encoding="utf-8-sig", newline="") as stream:
        times = [datetime.fromisoformat(row["time"]) for row in csv.DictReader(stream)]
    return min(times), max(times) + timedelta(minutes=1)


def extract(path: Path) -> tuple[list[dict], dict]:
    """一つの保存生板を逐次読み込み、特徴量と監査を返す。

    引数: path（Path）読み取り専用の生板ファイル。
    返り値: tuple[list[dict], dict]。特徴量行と品質情報。
    """
    start, end = bounds(path)
    processor = Extractor(start, end, 10 if path.parent.name == "NK225" else .5)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for line in stream:
            digest.update(line)
            processor.accept(json.loads(line))
    rows = processor.rows(path.parent.name, path.stem)
    audit = dict(processor.audit)
    delays = sorted(processor.delays)
    audit.update({
        "source_sha256": digest.hexdigest(), "source": str(path.relative_to(ROOT)),
        "start": start.isoformat(), "end_exclusive": end.isoformat(),
        "anchor_delay_median_seconds": median(delays),
        "anchor_delay_p95_seconds": delays[int(.95 * (len(delays) - 1))],
        "anchor_delay_max_seconds": max(delays),
    })
    return rows, audit


def synthetic_row(stamp: str, bid: float, volume: float, price: float) -> dict:
    """時刻と板価格が明確な検証用の生板行を作る。

    引数: stamp（str）約定時刻、bid・volume・price（float）買気配、累積出来高、価格。
    返り値: dict。十段の売買板を含む検証データ。
    """
    row = {"CurrentPriceTime": stamp, "CurrentPrice": price, "TradingVolume": volume}
    for level in range(1, 11):
        row[f"Buy{level}"] = {"Price": bid - level + 1, "Qty": 10}
        row[f"Sell{level}"] = {"Price": bid + level, "Qty": 10}
    return row


def self_test() -> None:
    """未来のブロック混入、重複、セッション境界の基本条件を検証する。

    引数: なし。
    返り値: None。不整合時は AssertionError または ValueError。
    """
    start = datetime.fromisoformat("2026-09-21T09:00:00+09:00")
    processor = Extractor(start, start + timedelta(minutes=10), 1)
    processor.accept(synthetic_row(start.isoformat(), 100, 10, 100))
    processor.accept(synthetic_row(start.isoformat(), 101, 12, 101))
    processor.accept(synthetic_row(start.isoformat(), 101, 12, 101))
    assert not processor.minutes
    later = start + timedelta(minutes=2, seconds=30)
    processor.accept(synthetic_row(later.isoformat(), 999, 999, 999))
    rows = processor.rows("試験", "試験")
    assert len(rows) == 1
    assert rows[0]["available_at"] == (start + timedelta(minutes=3)).isoformat()
    assert rows[0]["book_mid_last"] == 101.5
    assert rows[0]["quote_count"] == 2
    assert rows[0]["event_count"] == 3
    assert rows[0]["signed_volume"] == 2
    assert rows[0]["ofi_sum"] == 20
    assert rows[0]["anchor_delay_max_seconds"] == 150
    assert processor.audit["discarded_final_block_rows"] == 1
    try:
        processor.accept(synthetic_row(start.isoformat(), 100, 10, 100))
    except ValueError:
        pass
    else:
        raise AssertionError("逆行時刻を拒否できていない")
    fresh = Extractor(start, start + timedelta(minutes=10), 1)
    fresh.accept(synthetic_row((start - timedelta(minutes=1)).isoformat(), 100, 10, 100))
    assert not fresh.block and fresh.audit["outside_session_rows"] == 1


def write_audit(audits: list[dict]) -> None:
    """時刻の限界、列定義、全ファイルの品質情報を日本語で記録する。

    引数: audits（list[dict]）各ファイルの監査結果。
    返り値: None。板特徴監査.md を生成する。
    """
    lines = [
        "# 生板特徴量の抽出と時刻監査", "",
        "保存済み六ファイルのみを読み、現在セッションＡＰＩと前回の現在キャッシュは読んでいない。元データは変更していない。", "",
        "## 利用可能時刻", "",
        "各行に受信時刻がないため、CurrentPriceTime を板更新の実時刻としては扱わない。同じ CurrentPriceTime が続くブロック全体を、次の異なる CurrentPriceTime が現れた時点で初めて利用可能とする。さらに、その時刻が属する一分間の終了後にだけ特徴量を利用する。time はこの集計枠の開始、available_at は使用可能な一分後の時刻。末尾の次時刻が来ないブロックは全て破棄する。", "",
        "セッションごとに状態を初期化し、保存一分足の最初から最後の足の終了時刻までに約定時刻が入る行だけを採用する。夜間先頭に残る前の日中の約定時刻は除外。約定時刻の逆行や未来の出来高時刻は即時エラーにする。", "",
        "これは保存順で次の約定が届くまで待つ保守的な近似であり、ネットワーク遅延や実受信時刻の正確な復元ではない。表示時刻の先読みを避けても、受信遅延がゼロだったと証明はできない。無約定時間が長いほど板特徴量は遅れる。遅延列はブロックの二つの約定時刻の差であり、実際の通信遅延ではない。", "",
        "## 列の定義", "",
        "- book_mid_last: 最後の有効な最良売買気配の中間値。Sell1 が売気配、Buy1 が買気配。", 
        "- microprice_last: (売値×買数量＋買値×売数量)÷(買数量＋売数量)。", 
        "- spread_median: 重複除去後の売値－買値の中央値。売買同値・交差・数量不正を除外する。", 
        "- imbalance1_mean・imbalance5_mean・imbalance10_mean: 各深さの(買数量－売数量)÷(買数量＋売数量)のイベント平均。受信時刻がないため時間加重平均ではない。", 
        "- ofi_sum: 最良板の標準的注文フロー不均衡の和。前の最良買値 b0・数量 qb0、現在 b・qb、前の最良売値 a0・数量 qa0、現在 a・qa とすると、1[b≧b0]qb－1[b≦b0]qb0－1[a≦a0]qa＋1[a≧a0]qa0。取消と約定の区別はできない。", 
        "- ofi_abs_sum: 上記のイベントごとの絶対値の和。ofi_norm は ofi_sum÷ofi_abs_sum、変化なしは0。複数分の比率は分子分母を別々に合算して再計算する。", 
        "- top_depth_mean: 最良買数量＋最良売数量のイベント平均。", 
        "- bid_up・bid_down・ask_up・ask_down: 最良気配が直前の有効板より上昇・下降したイベント数。quote_direction は(買上昇＋売上昇－買下降－売下降)÷全価格変化数。", 
        "- mid_move_ticks: 有効板間の中間値差の和を銘柄の刻みで割った値。交差板や欠損板の直後は差を接続しない。", 
        "- volume_delta: TradingVolume の非負差分の和。初回の累積値は基準として消費するだけで足さず、減少時はリセットする。", 
        "- signed_volume: 価格上昇は＋、下降は－、同値は直前方向を継承するティックルールによる出来高差分。これは推定であり、成行買い・成行売りの真の約定分類ではない。方向が未確定なら0。", 
        "- signed_volume_ratio: signed_volume÷volume_delta、出来高なしは0。", 
        "- event_count: 利用可能になった元の行数。quote_count: 十段の価格数量が直前と異なり、最良板が有効だった板イベント数。連続する同一板のみ除き、後で同じ状態に戻った板は除かない。", 
        "- price_change_count: 最終約定価格が直前と変わった回数。block_count: その分に利用可能となったブロック数。", 
        "- anchor_delay_mean_seconds・anchor_delay_max_seconds: 次の約定時刻へ帰属させる際のブロック遅延の平均・最大。invalid_quote_count: 重複除去後の同値・交差・欠損板の件数。", 
        "", "特徴のない分は出力行を作らない。時間軸を埋める場合、mid・microprice 等の状態値と、出来高・注文フロー等の増分値を同じ前方補完で扱わない。将来値による後方補完は禁止。", "",
        "## ファイル別監査", "",
        "|銘柄・セッション|元行数|時刻なし|範囲外|板重複|有効板|出力分数|末尾破棄行|遅延中央値秒|遅延95%秒|最大秒|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for audit in audits:
        keys = ["raw_rows", "null_time_rows", "outside_session_rows", "consecutive_quote_duplicates", "valid_quote_events", "feature_minutes", "discarded_final_block_rows", "anchor_delay_median_seconds", "anchor_delay_p95_seconds", "anchor_delay_max_seconds"]
        lines.append("|" + audit["source"] + "|" + "|".join(str(audit.get(key, 0)) for key in keys) + "|")
    lines.extend(["", "## 再現と基本検証", "", "`python work/wave_v2/book_features.py` で全六ファイルを再作成。`python work/wave_v2/book_features.py --self-test` は、次ブロック待ち・一分確定待ち・末尾破棄・板重複・出来高差・注文フロー式・時刻逆行拒否・範囲外拒否を合成データで確認する。抽出実行前にも同じ検証を実施した。", "", "## 監査詳細", "", "```json", json.dumps(audits, ensure_ascii=False, indent=2), "```", ""])
    (OUT / "板特徴監査.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """保存済み生板の特徴量ファイルを再現可能な形で生成する。

    引数: なし。コマンド行の --self-test は基本検証のみ実行する。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="生板特徴量の保守的な時刻集約")
    parser.add_argument("--self-test", action="store_true", help="合成データの基本検証のみ実施")
    args = parser.parse_args()
    self_test()
    if args.self_test:
        print("基本検証に成功しました。")
        return
    audits = []
    for path in sorted((ROOT / "book").glob("*/*.jsonl")):
        rows, audit = extract(path)
        output = OUT / f"板特徴_{path.parent.name}_{path.stem}.csv"
        with output.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        audits.append(audit)
        print(f"抽出完了: {output.name}、{len(rows)} 分", flush=True)
    write_audit(audits)


if __name__ == "__main__":
    main()
