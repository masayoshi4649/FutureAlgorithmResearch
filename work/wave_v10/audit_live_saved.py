"""一回取得済みの追加照合を、通信せずに凍結・原気配・区分・原本打切りから監査する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

import catalog
import engine
import signals
from audit_raw_prefix import RAW, clean
from audit_results import independent_drawdown

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
LIVE = OUT / "live"


def digest(path: Path) -> str:
    """機能: 保存物を変更せず、一定量ずつ読み込んで SHA256 を計算する。

    引数: path (Path) は対象ファイル。
    返り値: str。SHA256。
    """
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while value := stream.read(1024 * 1024):
            hasher.update(value)
    return hasher.hexdigest()


def verify_saved_contract() -> tuple[dict, dict]:
    """機能: 条件・コードの凍結が取得前であり、６要求が各１回だった記録を照合する。

    引数: なし。
    返り値: tuple[dict, dict]。凍結記録と取得記録。
    """
    frozen = json.loads((OUT / "現在照合_凍結記録.json").read_text(encoding="utf-8"))
    acquired = json.loads((OUT / "現在照合_取得記録.json").read_text(encoding="utf-8"))
    assert frozen == json.loads((LIVE / "凍結記録の写し.json").read_text(encoding="utf-8"))
    assert acquired == json.loads((LIVE / "取得記録.json").read_text(encoding="utf-8"))
    assert digest(OUT / "現在照合_凍結記録.json") == acquired["manifest_sha256"]
    for path, expected in frozen["files_sha256"].items():
        assert digest(ROOT / path) == expected, path
    assert datetime.fromisoformat(frozen["fixed_at"]) < datetime.fromisoformat(acquired["started_at"])
    selected = json.loads((OUT / "最終選択.json").read_text(encoding="utf-8"))
    expected = {config["id"]: config for config in selected["現在照合条件"]}
    assert sorted(expected) == frozen["selected_ids"] == acquired["selected_ids"]
    assert [expected[key] for key in sorted(expected)] == frozen["selected_configs"]
    assert len(acquired["requests"]) == len({row["name"] for row in acquired["requests"]}) == 6
    for row in acquired["requests"]:
        assert row["attempts"] == 1 and row["ok"] and row["http_status"] == 200
        assert datetime.fromisoformat(frozen["fixed_at"]) < datetime.fromisoformat(row["started_at"])
        assert digest(ROOT / row["path"]) == row["sha256"]
        params = parse_qs(urlparse(row["url"]).query)
        assert params["from"] == [frozen["starts_at"]] and params["to"] == [acquired["cutoff"]]
    for row in acquired["candles"]:
        assert digest(ROOT / row["path"]) == row["sha256"]
    return frozen, acquired


def verify_tables(trades: list[dict], known: float) -> int:
    """機能: 新しい転換と既知起源を分け、保存価格から全２４集計行の損益を再計算する。

    引数: trades (list[dict]) は保存した全売買、known (float) は既知上限。
    返り値: int。照合集計行数。
    """
    groups = [("現在照合_セッション集計.csv", True), ("現在照合_既知起源集計.csv", False)]
    count = 0
    for filename, added in groups:
        for cell in pd.read_csv(OUT / filename).to_dict("records"):
            subset = [row for row in trades if row["方式"] == cell["方式"] and row["銘柄"] == cell["銘柄"]
                      and (row["signal_time_s"] >= known) == added]
            closed = [row for row in subset if row["closed"]]
            tick, multiplier = (10., 1000.) if cell["銘柄"] == "NK225" else (.5, 10000.)
            points = [row["side"] * (row["exit_price"] - row["entry_price"]) - 2 * tick for row in closed]
            net = np.array(points) * multiplier
            stress_atr = np.array([(value - 2 * tick) / row["atr"] for value, row in zip(points, closed)])
            expected = dict(取引数=len(closed), 未返済数=len(subset) - len(closed), 勝ち数=int((net > 0).sum()),
                            利益円=float(net[net > 0].sum()), 損失円=float(-net[net < 0].sum()),
                            収支円=float(net.sum()), 費用倍収支円=float(sum(value - 2 * tick for value in points) * multiplier),
                            費用倍ATR収支=float(stress_atr.sum()), 確定最大下落ATR=independent_drawdown(stress_atr),
                            確定最大下落円=independent_drawdown(net),
                            評価損益円=float(sum((row["side"] * (row["mark_price"] - row["entry_price"]) - 2 * tick)
                                                     * multiplier for row in subset if not row["closed"])))
            for key, value in expected.items():
                assert np.isclose(cell[key], value, atol=1e-7, rtol=1e-10), (filename, cell["方式"], key)
            count += 1
    return count


def main() -> None:
    """機能: 保存追加照合の全取引と、追加区間途中の原本打切りを独立監査する。

    引数: なし。
    返り値: None。再通信なしの独立監査 JSON を保存する。
    """
    frozen, acquired = verify_saved_contract()
    known = pd.Timestamp(frozen["known_cutoff"]).timestamp()
    session = frozen["session"]
    trades = json.loads((OUT / "現在照合_全取引.json").read_text(encoding="utf-8"))
    old_trades = json.loads((OUT / "候補全取引.json").read_text(encoding="utf-8"))
    for row in trades:
        assert (row["評価区分"] == "追加区間の新規転換") == (row["signal_time_s"] >= known)
    count = verify_tables(trades, known)
    frames = {symbol: pd.read_csv(LIVE / "features" / f"{symbol}_{session}.csv") for symbol in signals.SYMBOLS}
    roots_before = signals.ROOT
    records = []
    signals.ROOT = LIVE
    try:
        for symbol in signals.SYMBOLS:
            peer = signals.SYMBOLS[1 - signals.SYMBOLS.index(symbol)]
            tape = dict(np.load(LIVE / "features" / f"約定系列_{symbol}_{session}.npz", allow_pickle=False))
            tape["atr"] = signals.atr_at(session, symbol, tape["time_s"])
            events, _ = signals.build_events(session, symbol, frames[symbol], frames[peer])
            state = signals.state_at(tape, frames[symbol], signals.price_grid(session, symbol, float(tape["time_s"][-1])))
            ready = engine.prepare(tape, events, session, symbol, state, catalog.us_open_time(session))
            full_trades = {}
            for config in frozen["selected_configs"]:
                observed = engine.simulate(ready, config)
                wanted = [row for row in trades if row["方式"] == config["id"] and row["銘柄"] == symbol]
                assert len(observed) == len(wanted)
                for actual, saved in zip(observed, wanted):
                    assert clean(actual) == clean({key: saved[key] for key in actual})
                    indices = np.searchsorted(tape["seq"], [saved["entry_seq"], saved.get("exit_seq", tape["seq"][-1])])
                    entry_quote = tape["ask"][indices[0]] if saved["side"] > 0 else tape["bid"][indices[0]]
                    exit_quote = tape["bid"][indices[1]] if saved["side"] > 0 else tape["ask"][indices[1]]
                    assert saved["entry_price"] == entry_quote and saved.get("exit_price", saved.get("mark_price")) == exit_quote
                full_trades[config["id"]] = observed
                old_closed = [row for row in old_trades if row["セッション"] == session and row["銘柄"] == symbol
                              and row["方式"] == config["id"] and row["closed"]]
                by_event = {row["event_id"]: row for row in observed}
                for old in old_closed:
                    current = by_event[old["event_id"]]
                    assert clean(current) == clean({key: old[key] for key in current})

            # ----------------------------------------
            # 新しい原本の先頭が、既知の旧原本と完全に同じバイト列かを照合する。
            old_path = ROOT / "work" / "wave_v9" / "live" / "book" / symbol / f"{session}.jsonl"
            new_path = LIVE / "book" / symbol / f"{session}.jsonl"
            with old_path.open("rb") as old, new_path.open("rb") as new:
                while value := old.read(1024 * 1024):
                    assert new.read(len(value)) == value

            # ----------------------------------------
            # 追加期間の半ば２３時４２分までしか原本を読まず、確定した過去を再構成する。
            cut_at = pd.Timestamp("2026-09-23T23:42:00+09:00").timestamp()
            cut = 0
            with new_path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    stamp = json.loads(line).get("CurrentPriceTime")
                    if stamp and pd.Timestamp(stamp).timestamp() >= cut_at:
                        break
                    cut += 1
            quotes = []
            prefix, _ = RAW.extract_features(new_path, symbol, session, max_rows=cut, quotes=quotes)
            prefix = pd.read_csv(io.StringIO(prefix.to_csv(index=False)))
            quote_frame = pd.DataFrame(quotes)
            short = {key: quote_frame[key].to_numpy() for key in quote_frame}
            cutoff, last_seq = float(short["time_s"][-1]), int(short["seq"][-1])
            short["atr"] = signals.atr_at(session, symbol, short["time_s"], cutoff=cutoff)
            short_events, _ = signals.build_events(session, symbol, prefix, frames[peer], cutoff=cutoff)
            assert clean(short_events.to_dict("records")) == clean(events[events["seq"] <= last_seq].to_dict("records"))
            short_state = signals.state_at(short, prefix, signals.price_grid(session, symbol, cutoff))
            short_ready = engine.prepare(short, short_events, session, symbol, short_state, catalog.us_open_time(session))
            confirmed = 0
            for config in frozen["selected_configs"]:
                observed = [row for row in engine.simulate(short_ready, config) if row["closed"]]
                wanted = [row for row in full_trades[config["id"]] if row["closed"] and row["exit_seq"] <= last_seq]
                assert clean(observed) == clean(wanted)
                confirmed += len(observed)
            records.append(dict(銘柄=symbol, 旧原本が完全な先頭バイト列=True,
                                全取引照合数=sum(len(value) for value in full_trades.values()),
                                原本打切り行数=cut, 打切り転換イベント数=len(short_events),
                                打切り確定取引数=confirmed, 一致=True))
    finally:
        signals.ROOT = roots_before
    verify_saved_contract()
    output = dict(監査時の通信回数=0, 凍結ファイル数=len(frozen["files_sha256"]), 条件数=len(frozen["selected_ids"]),
                  要求６件各１回の記録一致=True, 全取引数=len(trades), 新旧区分の集計照合数=count,
                  新規転換の追加期間取引数=sum(row["signal_time_s"] >= known for row in trades),
                  未返済取引数=sum(not row["closed"] for row in trades),
                  銘柄別検査=records,
                  限界="固定前に発生した未読追加データの事後照合である。短い追加期間は市場法則や実時間約定の証明ではない。")
    (OUT / "現在照合_独立監査.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("追加照合の凍結・６要求・全売買・損益区分・原本途中打切りが一致しました。", flush=True)


if __name__ == "__main__":
    main()
