"""追加取得済みデータを再通信せず監査し、凍結・区分・途中打切りを照合する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
LIVE = OUT / "live"
sys.dont_write_bytecode = True
sys.path.insert(0, str(OUT.parent / "wave_v8"))
import raw_features
sys.path.insert(0, str(OUT))
import execution
import turning_signals


def digest(path: Path) -> str:
    """保存ファイルを変更せずSHA256を求める。

    引数: path（Path）対象ファイル。
    返り値: str。SHA256の十六進表現。
    """
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def clean(value: object) -> object:
    """欠測だけを等値比較可能にする。

    引数: value（object）イベントまたは取引属性。
    返り値: object。数値精度を変えずNaNをNoneへ変換した値。
    """
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return None
    return value


def read_json(name: str) -> object:
    """調査ルートにある保存済みJSONを読む。

    引数: name（str）ファイル名。
    返り値: object。JSONの内容。
    """
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def verify_freeze() -> tuple[dict, dict, dict]:
    """凍結が通信より前で、コード・七条件・取得保存物が不変なことを確認する。

    引数: なし。
    返り値: tuple[dict, dict, dict]。凍結記録、取得記録、監査記録。
    """
    frozen, acquired = read_json("現在照合_凍結記録.json"), read_json("現在照合_取得記録.json")
    assert acquired == json.loads((LIVE / "取得記録.json").read_text(encoding="utf-8"))
    assert frozen == json.loads((LIVE / "凍結記録の写し.json").read_text(encoding="utf-8"))
    assert digest(OUT / "現在照合_凍結記録.json") == acquired["manifest_sha256"]
    fixed = datetime.fromisoformat(frozen["fixed_at"])
    assert fixed < datetime.fromisoformat(acquired["started_at"])
    for path, expected in frozen["files_sha256"].items():
        assert digest(ROOT / path) == expected, f"凍結不一致: {path}"
    configurations = {config["id"]: config for config in execution.configs()}
    assert [configurations[key] for key in frozen["selected_ids"]] == frozen["selected_configs"]
    selected = read_json("既知５セッション選択.json")
    expected_ids = {item["採用"]["方式"] for item in selected.values() if item["採用"]}
    expected_ids |= {f"{family}_追跡0.25ATR_追跡2ATR" for family in ("T01", "T06", "T12")}
    assert sorted(expected_ids) == frozen["selected_ids"] == acquired["selected_ids"]
    requests = acquired["requests"]
    assert len(requests) == len({row["name"] for row in requests}) == 6
    for row in requests:
        assert row["attempts"] == 1 and row["ok"] and row["http_status"] == 200
        assert fixed < datetime.fromisoformat(row["started_at"])
        query = parse_qs(urlparse(row["url"]).query)
        assert query["from"] == [frozen["starts_at"]] and query["to"] == [acquired["cutoff"]]
        assert digest(ROOT / row["path"]) == row["sha256"]
    for row in acquired["candles"]:
        assert digest(ROOT / row["path"]) == row["sha256"]
    return frozen, acquired, dict(凍結時刻=frozen["fixed_at"], 最初の要求時刻=min(row["started_at"] for row in requests),
                                 凍結対象ファイル数=len(frozen["files_sha256"]), 全ハッシュ一致=True,
                                 条件数=len(expected_ids), 条件再選択なし=True, 要求数=6, 各要求一回=True,
                                 保存取得物ハッシュ一致=True, 本監査ネットワーク要求数=0)


def inspect_raw(path: Path, cutoff: float, known: float) -> tuple[int, str, int]:
    """生板を走査して中間打切り行と既知区間の内容ハッシュを求める。

    引数: path（Path）原本。cutoff/known（float）中間・既知境界のUnix秒。
    返り値: tuple[int, str, int]。打切り行番号、既知行の正規化ハッシュ、既知行数。
    """
    hasher, known_count, cut = hashlib.sha256(), 0, None
    for index, line in enumerate(path.open(encoding="utf-8-sig")):
        row = json.loads(line)
        stamp = row.get("CurrentPriceTime")
        if not stamp:
            continue
        time = datetime.fromisoformat(stamp).timestamp()
        if time < known:
            hasher.update(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            known_count += 1
        if cut is None and time >= cutoff:
            cut = index
    assert cut is not None
    return cut, hasher.hexdigest(), known_count


def verify_known_prefix(old: Path, current: Path, start: float, known: float) -> dict:
    """既知原本の不変性と、同じ最終約定時刻を持つ末尾追加を区別する。

    引数: old/current（Path）旧・今回原本。start/known（float）対象開始・既知境界。
    返り値: dict。既知prefix一致と境界追加行の記録。
    """
    old_bytes = old.read_bytes()
    with current.open("rb") as stream:
        byte_prefix_equal = stream.read(len(old_bytes)) == old_bytes
    old_rows, new_rows = [], []
    for path, target in ((old, old_rows), (current, new_rows)):
        with path.open(encoding="utf-8-sig") as stream:
            for line in stream:
                row = json.loads(line)
                if row.get("CurrentPriceTime"):
                    stamp = datetime.fromisoformat(row["CurrentPriceTime"]).timestamp()
                    if start <= stamp < known:
                        target.append(row)
    assert new_rows[:len(old_rows)] == old_rows, "旧原本の既知行が改訂されている"
    extra = new_rows[len(old_rows):]
    last_stamp = old_rows[-1]["CurrentPriceTime"]
    assert all(row["CurrentPriceTime"] == last_stamp for row in extra), "同秒末尾以外に追加がある"
    return dict(旧原本バイト数=len(old_bytes), 旧原本のバイトprefix一致=byte_prefix_equal,
                旧既知対象行数=len(old_rows), 今回既知時刻対象行数=len(new_rows), 旧全行の内容prefix一致=True,
                同秒末尾追加行数=len(extra), 同秒末尾時刻=last_stamp, 過去行改訂なし=True,
                注意="今回初めて読んだ末尾追加行にも旧締切より前の最終約定時刻が付く。実受信時刻がないため、既知時刻の区間と既読行の集合は完全には同じではない。")


def audit_metrics(trades: list[dict], frozen: dict) -> dict:
    """転換起源の区分と、確定損益・未返済評価の分離を独立に再集計する。

    引数: trades（list[dict]）保存全取引。frozen（dict）凍結記録。
    返り値: dict。区分件数と再集計結果。
    """
    known = datetime.fromisoformat(frozen["known_cutoff"]).timestamp()
    sections = [("現在照合_セッション集計.csv", "追加区間の新規転換"), ("現在照合_既知起源集計.csv", "既知区間の転換")]
    for trade in trades:
        expected = "追加区間の新規転換" if trade["signal_time_s"] >= known else "既知区間の転換"
        assert trade["評価区分"] == expected
    cells = 0
    for filename, section in sections:
        for cell in pd.read_csv(OUT / filename).to_dict("records"):
            selected = [trade for trade in trades if trade["方式"] == cell["方式"] and trade["銘柄"] == cell["銘柄"] and trade["評価区分"] == section]
            closed = [trade for trade in selected if trade["closed"]]
            opened = [trade for trade in selected if not trade["closed"]]
            multiplier = execution.MULTIPLIERS[cell["銘柄"]]
            gains = [trade["net_points"] * multiplier for trade in closed]
            assert cell["取引数"] == len(closed) and cell["未返済数"] == len(opened)
            assert cell["利益円"] == sum(value for value in gains if value > 0)
            assert cell["損失円"] == -sum(value for value in gains if value < 0)
            assert cell["収支円"] == sum(gains)
            assert cell["評価損益円"] == sum(trade["net_points"] * multiplier for trade in opened)
            assert all(trade.get("exit_reason") != "セッション内返済" for trade in selected)
            cells += 1
    return dict(全取引記録数=len(trades), 追加起源取引数=sum(trade["signal_time_s"] >= known for trade in trades),
                既知起源取引数=sum(trade["signal_time_s"] < known for trade in trades),
                未返済取引数=sum(not trade["closed"] for trade in trades), 再集計セル数=cells,
                起源区分一致=True, 確定収支と未返済評価の分離一致=True, 途中締切で人工返済なし=True)


def verify_previous_closed(trades: list[dict], frozen: dict) -> list[dict]:
    """同秒末尾追加が既知区間の確定済み売買を変えていないことを確認する。

    引数: trades（list[dict]）今回全取引。frozen（dict）凍結記録。
    返り値: list[dict]。銘柄別の旧確定取引照合数。
    """
    old_trades = read_json("全取引.json")
    known = datetime.fromisoformat(frozen["known_cutoff"]).timestamp()
    keys = ["方式", "event_id", "entry_seq", "entry_price", "exit_seq", "exit_price", "net_points"]
    records = []
    for symbol in execution.SYMBOLS:
        old = [{key: row[key] for key in keys} for row in old_trades
               if row["銘柄"] == symbol and row["セッション"] == frozen["session"]
               and row["方式"] in frozen["selected_ids"] and row["closed"]]
        new = [{key: row[key] for key in keys} for row in trades
               if row["銘柄"] == symbol and row["closed"] and row["exit_time_s"] < known]
        old.sort(key=lambda row: (row["方式"], row["entry_seq"]))
        new.sort(key=lambda row: (row["方式"], row["entry_seq"]))
        assert old == new
        records.append(dict(銘柄=symbol, 既知区間の確定取引数=len(old),
                            イベントと入出場行価格収支一致=True, 同秒追加による既知確定売買変更なし=True))
    return records


def main() -> None:
    """保存した現在照合を一回だけ独立再生し、21時原本打切りも検査する。

    引数: なし。
    返り値: None。新しい監査JSONだけを書き出す。
    """
    frozen, acquired, frozen_audit = verify_freeze()
    session = frozen["session"]
    known = datetime.fromisoformat(frozen["known_cutoff"]).timestamp()
    middle = pd.Timestamp("2026-09-23T21:00:00+09:00").timestamp()
    assert known < middle < datetime.fromisoformat(acquired["cutoff"]).timestamp()
    saved_trades = read_json("現在照合_全取引.json")
    metrics = audit_metrics(saved_trades, frozen)
    previous_closed = verify_previous_closed(saved_trades, frozen)
    frames, tapes, prefixes, prefix_tapes, cuts = {}, {}, {}, {}, {}
    known_checks, prefix_checks, full_checks = [], [], []
    for symbol in execution.SYMBOLS:
        path = LIVE / "book" / symbol / f"{session}.jsonl"
        cut, known_hash, known_rows = inspect_raw(path, middle, known)
        old = ROOT / "work/wave_v7/live/book" / symbol / f"{session}.jsonl"
        # 旧原本の終端より手前の時刻を指定し、同じ既知区間の内容だけを比較する。
        _, old_hash, old_rows = inspect_raw(old, known - 60, known)
        boundary = verify_known_prefix(old, path, datetime.fromisoformat(frozen["starts_at"]).timestamp(), known)
        known_checks.append(dict(銘柄=symbol, 既知生板行数=known_rows, 旧既知生板行数=old_rows,
                                 既知時刻全行ハッシュ一致=known_hash == old_hash, 新既知SHA256=known_hash,
                                 旧既知SHA256=old_hash, **boundary))
        for interval in (1, 5):
            old_candles = pd.read_csv(ROOT / "work/wave_v7/live" / f"candle_{interval}min" / symbol / f"{session}.csv")
            new_candles = pd.read_csv(LIVE / "work/wave_v7/live" / f"candle_{interval}min" / symbol / f"{session}.csv")
            new_candles = new_candles.loc[pd.to_datetime(new_candles.time) + pd.Timedelta(minutes=interval) <= pd.Timestamp(known, unit="s", tz="Asia/Tokyo")].reset_index(drop=True)
            pd.testing.assert_frame_equal(old_candles, new_candles, check_exact=True)
        frames[symbol] = pd.read_csv(LIVE / "features" / f"{symbol}_{session}.csv")
        with np.load(LIVE / "features" / f"約定系列_{symbol}_{session}.npz") as saved:
            tapes[symbol] = {key: saved[key] for key in saved.files if key != "tick"}
        quotes = []
        prefix, _ = raw_features.extract_features(path, symbol, session, max_rows=cut, quotes=quotes)
        prefixes[symbol] = pd.read_csv(io.StringIO(prefix.to_csv(index=False)))
        quote_frame = pd.DataFrame(quotes)
        prefix_tapes[symbol] = {key: quote_frame[key].to_numpy() for key in quote_frame}
        cuts[symbol] = cut
        pd.testing.assert_frame_equal(prefixes[symbol], frames[symbol].loc[frames[symbol].seq < cut].reset_index(drop=True), check_exact=True)

    # ----------------------------------------
    # 凍結ソースは編集せず、メモリ上のデータ参照先だけ今回の保存物へ切り替える。
    original_roots = execution.ROOT, turning_signals.ROOT
    execution.ROOT = turning_signals.ROOT = LIVE
    try:
        for symbol, peer_symbol in (("NK225", "TOPIX"), ("TOPIX", "NK225")):
            tape, prefix_tape = tapes[symbol], prefix_tapes[symbol]
            tape["atr"] = execution.atr_at(session, symbol, tape["time_s"])
            prefix_tape["atr"] = execution.atr_at(session, symbol, prefix_tape["time_s"], cutoff=float(prefix_tape["time_s"][-1]))
            full_events, _ = turning_signals.build_events(session, symbol, frames[symbol], frames[peer_symbol])
            prefix_events, _ = turning_signals.build_events(session, symbol, prefixes[symbol], frames[peer_symbol], cutoff=float(prefixes[symbol].time_s.iloc[-1]))
            expected_events = full_events.loc[full_events.seq < cuts[symbol]].reset_index(drop=True)
            pd.testing.assert_frame_equal(prefix_events, expected_events, check_exact=True)
            for config in frozen["selected_configs"]:
                full = execution.simulate(tape, full_events, config, session, symbol)
                saved = [row for row in saved_trades if row["銘柄"] == symbol and row["方式"] == config["id"]]
                normalized_saved = [{key: row[key] for key in observed} for observed, row in zip(full, saved)]
                assert len(full) == len(saved) and clean(full) == clean(normalized_saved)
                full_checks.append(dict(銘柄=symbol, 条件=config["id"], 保存取引照合数=len(full), 全属性一致=True))
                prefix = execution.simulate(prefix_tape, prefix_events, config, session, symbol)
                observed = [row for row in prefix if row["closed"]]
                expected = [row for row in full if row["closed"] and row["exit_seq"] < cuts[symbol]]
                assert clean(observed) == clean(expected)
                prefix_checks.append(dict(銘柄=symbol, 条件=config["id"], 原本打切り行=cuts[symbol],
                                          中間境界="2026-09-23T21:00:00+09:00", イベント照合数=len(prefix_events),
                                          確定取引照合数=len(observed), 全属性一致=True))
    finally:
        execution.ROOT, turning_signals.ROOT = original_roots
    verify_freeze()
    result = dict(凍結と取得=frozen_audit, 区分と損益=metrics, 既知範囲不変確認=known_checks, 既知確定売買不変確認=previous_closed,
                  保存結果再生=full_checks, 原本途中打切り=prefix_checks,
                  原本打切り比較数=len(prefix_checks), 確定取引照合延べ数=sum(row["確定取引照合数"] for row in prefix_checks),
                  監査中凍結コード変更なし=True, 再通信なし=True,
                  限界="未読追加分の固定条件による再生照合であり、実時間の前向き取引ではない。CurrentPriceTimeは実受信時刻ではない。")
    execution.save(OUT / "現在照合_独立監査.json", result)
    print("現在照合の凍結・区分・保存再生・中間原本打切りが一致しました。", flush=True)


if __name__ == "__main__":
    main()
