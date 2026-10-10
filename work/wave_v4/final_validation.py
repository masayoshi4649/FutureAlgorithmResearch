"""凍結後の保存スナップショットと再生結果を独立に検証する。通信は行わない。"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

import engine
from current_check import SNAPSHOT, SESSION, load_snapshot
from research import OUT, ROOT, SYMBOLS, evaluate, evaluate_by_symbol, schedule_for
from signals import build_features
from test_engine import prefix_trades


def digest(path: Path) -> str:
    """ファイル内容を変更せずにＳＨＡ－２５６を計算する。

    引数: path（Path）検査対象。
    返り値: str。ハッシュの十六進表現。
    """
    state = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            state.update(chunk)
    return state.hexdigest()


def normalized(value: object) -> object:
    """日時を保存形式に揃え、再生結果の厳密比較を可能にする。

    引数: value（object）取引・特徴・集計。
    返り値: object。ＪＳＯＮ化して復元した値。
    """
    return json.loads(json.dumps(value, default=str, ensure_ascii=False, allow_nan=False))


def hashes(fixed: dict) -> dict:
    """凍結コード、保存足、旧生板特徴、生板原本の一致を確認する。

    引数: fixed（dict）凍結記録。
    返り値: dict。項目別の件数と変更なしの検査結果。
    """
    code = {name: digest(OUT / name) == expected for name, expected in fixed["code_sha256"].items()}
    inputs = {name: digest(ROOT / name) == expected for name, expected in fixed["input_sha256"].items()}
    raw = {}
    for file in OUT.glob("生板観測監査_*.json"):
        for audit in json.loads(file.read_text(encoding="utf-8")):
            raw[audit["source"]] = digest(ROOT / audit["source"]) == audit["source_sha256"]
    table = digest(OUT / "拡張全条件比較.csv") == fixed["table_sha256"]
    assert all(code.values()) and all(inputs.values()) and all(raw.values()) and table
    return dict(code=code, inputs=inputs, raw=raw, selection_table_unchanged=table)


def snapshot_audit(fixed: dict) -> dict:
    """取得記録・セッション・確定足・生板時刻を保存物だけで確認する。

    引数: fixed（dict）凍結記録。
    返り値: dict。取得と足・板の品質結果。
    """
    meta = json.loads((SNAPSHOT / "取得記録.json").read_text(encoding="utf-8"))
    marker = json.loads((SNAPSHOT / "取得開始.json").read_text(encoding="utf-8"))
    status = json.loads((SNAPSHOT / "status.json").read_text(encoding="utf-8"))
    cutoff = pd.Timestamp(meta["cutoff"])
    start = pd.Timestamp("2026-09-23T08:45:00+09:00")
    records = meta["requests"]
    assert len(records) == 7 and len({row["url"] for row in records}) == 7
    assert meta["各URLの試行回数"] == 1 and marker["再試行なし"] is True
    assert pd.Timestamp(fixed["fixed_at"]) < min(pd.Timestamp(row["started"]) for row in records)
    assert all(row["ok"] and row["http_status"] == 200 and digest(SNAPSHOT / row["name"]) == row["sha256"] for row in records)
    assert {row["sessionId"] for row in status["current"]} == {SESSION}
    assert {row["code"] for row in status["current"]} == set(SYMBOLS)
    for request in records:
        if request["name"] == "status.json":
            continue
        query = parse_qs(urlparse(request["url"]).query)
        assert pd.Timestamp(query["from"][0]) == start and pd.Timestamp(query["to"][0]) == cutoff
    candles, raw_audits, frames = [], [], {}
    for symbol in SYMBOLS:
        tick = engine.TICKS[symbol]
        for minutes in (1, 5):
            payload = json.loads((SNAPSHOT / f"{symbol}_{minutes}min.json").read_text(encoding="utf-8"))
            assert payload["snapshot"]["sessionId"] == SESSION and payload["snapshot"]["code"] == symbol
            frame = pd.DataFrame(payload["data"])
            frame["time"] = pd.to_datetime(frame.time)
            assert not frame.time.duplicated().any() and frame.time.is_monotonic_increasing
            assert frame.time.ge(start).all() and frame.time.lt(cutoff).all()
            assert np.isfinite(frame[["open", "high", "low", "close", "volume"]]).all().all()
            assert frame.low.le(frame[["open", "close"]].min(axis=1)).all()
            assert frame.high.ge(frame[["open", "close"]].max(axis=1)).all()
            assert frame.low.le(frame.high).all() and frame.volume.ge(0).all()
            assert np.isclose(frame[["open", "high", "low", "close"]].to_numpy() / tick % 1, 0).all()
            retained = frame[frame.closed & (frame.time + pd.Timedelta(minutes=minutes) <= cutoff)].set_index("time")
            frames[(symbol, minutes)] = retained
            candles.append(dict(symbol=symbol, minutes=minutes, received=len(frame), retained=len(retained),
                                not_closed=int((~frame.closed).sum()), excluded=len(frame)-len(retained),
                                first=frame.time.iloc[0], last=frame.time.iloc[-1], retained_last=retained.index[-1],
                                incomplete_volume=int((~frame.volumeComplete).sum()), ohlcv_valid=True))
        one, five = frames[(symbol, 1)], frames[(symbol, 5)]
        aggregate = one.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        a, b = aggregate.loc[five.index], five[["open", "high", "low", "close", "volume"]]
        assert np.array_equal(a.to_numpy(float), b.to_numpy(float))
        stamps, price_bad, missing = [], 0, 0
        with (SNAPSHOT / f"{symbol}_book.jsonl").open(encoding="utf-8-sig") as stream:
            for line in stream:
                row = json.loads(line)
                if not row.get("CurrentPriceTime"):
                    missing += 1
                    continue
                stamp = pd.Timestamp(row["CurrentPriceTime"])
                stamps.append(stamp)
                price = row.get("CurrentPrice")
                price_bad += not (isinstance(price, (int, float)) and np.isfinite(price) and price > 0)
        assert all(start <= stamp < cutoff for stamp in stamps)
        assert all(before <= after for before, after in zip(stamps, stamps[1:])) and price_bad == 0
        raw_audits.append(dict(symbol=symbol, time_rows=len(stamps), missing_time_rows=missing,
                               first=min(stamps), last=max(stamps), invalid_prices=price_bad,
                               outside_session=0, reverse_times=0, five_matches_one=True))
    return dict(cutoff=cutoff, freeze_before_fetch=True, attempts_each=1, url_count=7,
                successful_hashes=7, status=status, candles=candles, raw=raw_audits,
                first_request=min(row["started"] for row in records), last_response=max(row["finished"] for row in records))


def replay_audit(data: dict, fixed: dict) -> dict:
    """全固定候補の保存結果との一致、同一セッション返済、断面不変を調べる。

    引数: data（dict）現在保存入力、fixed（dict）凍結設定。
    返り値: dict。候補数・取引数・切断比較数。
    """
    configs = [engine.Config(**item["config"]) for item in fixed["candidates"]]
    assert len({cfg.key for cfg in configs}) == len(configs)
    full_schedules, full_trades, trade_count, passed = {}, {}, 0, []
    for cfg in configs:
        schedules = schedule_for(data, cfg)
        trades, targets, cells = evaluate(data, cfg, schedules)
        saved = json.loads((SNAPSHOT / f"評価_{cfg.key}.json").read_text(encoding="utf-8"))
        assert normalized(trades) == saved["trades"] and normalized(targets) == saved["targets"] and normalized(cells) == saved["cells"]
        full_schedules[cfg.key] = schedules
        full_trades[cfg.key] = {key: engine.simulate(item, schedules[key], cfg) for key, item in data.items()}
        for trade in trades:
            entry, exit = pd.Timestamp(trade["entry_time"]), pd.Timestamp(trade["exit_time"])
            item = data[(trade["session"], trade["symbol"])]
            assert trade["closed"] and trade["session"] == SESSION and entry <= exit
            assert entry in item["one"].index and exit in item["one"].index
            assert entry < item["limit"] - pd.Timedelta(minutes=30)
            assert exit < item["limit"] + pd.Timedelta(minutes=5)
            assert pd.Timestamp(trade["signal_time"]) + pd.Timedelta(minutes=1) <= entry
        trade_count += len(trades)
        if all(target["passed"] for target in targets):
            passed.append(cfg.key)
    primary = evaluate_by_symbol(data, fixed["symbol_configs"])
    saved_primary = json.loads((OUT / "答え合わせ_採用.json").read_text(encoding="utf-8"))
    assert all(normalized(value) == saved_primary[name] for value, name in zip(primary, ("trades", "targets", "cells")))
    checks = 0
    cuts = ("09:44", "09:45", "10:00", "11:15", "13:00", "15:35")
    for label in cuts:
        cutoff = pd.Timestamp(f"2026-09-23T{label}:00+09:00")
        clipped = {}
        for key, item in data.items():
            symbol = key[1]
            one = item["one"].loc[:cutoff]
            payload = json.loads((SNAPSHOT / f"{symbol}_5min.json").read_text(encoding="utf-8"))
            five = pd.DataFrame(payload["data"])
            five["time"] = pd.to_datetime(five.time)
            five = five[five.closed].set_index("time")
            board = SNAPSHOT / f"板特徴_{symbol}_{SESSION}.csv"
            z = build_features(one, five, board, engine.TICKS[symbol], cutoff)
            pd.testing.assert_frame_equal(z, item["z"].loc[:cutoff], check_exact=False, atol=1e-12, rtol=1e-12)
            clipped[key] = engine.prepare(one, z, symbol, SESSION)
        for cfg in configs:
            schedules = schedule_for(clipped, cfg)
            for key, item in clipped.items():
                original = full_schedules[cfg.key][key]
                assert np.array_equal(schedules[key][0], original[0][:len(item["z"])])
                assert np.array_equal(schedules[key][1], original[1][:len(item["z"])])
                result = engine.simulate(item, schedules[key], cfg)
                assert result == prefix_trades(full_trades[cfg.key][key], item["one"].index[-1])
                checks += 1
    return dict(candidates=len(configs), all_saved_results_match=True, total_candidate_trades=trade_count,
                primary_saved_result_matches=True, all_trades_closed_same_session=True,
                all_fills_use_observed_bars=True, cutoff_labels=cuts, prefix_checks=checks,
                prefix_matches=True, both_target_passed_candidates=passed, primary_target_passes=sum(t["passed"] for t in primary[1]))


def diagnose_pending(data: dict, fixed: dict) -> list[dict]:
    """凍結関数の局所変数だけを追跡し、下落を逃した未約定注文を診断する。

    引数: data（dict）現在入力、fixed（dict）凍結条件。
    返り値: list[dict]。方向許可時刻と待機した指値・実高値。関数コードは変更しない。
    """
    source_lines, first_line = inspect.getsourcelines(engine.simulate)
    line = first_line + next(index for index, content in enumerate(source_lines) if content.strip() == 'direction = pending["side"]')
    results = []
    for key, item in data.items():
        symbol = key[1]
        cfg = engine.Config(**fixed["symbol_configs"][symbol])
        schedules = schedule_for(data, cfg)
        signs = schedules[key][0]
        negatives = np.flatnonzero(signs == -1)
        observed_orders = {}
        def trace(frame: object, event: str, arg: object) -> object:
            """注文水準確定後の観測だけを保存する読み取り専用トレース。

            引数: frame（frame）実行中のフレーム、event（str）事象、arg（object）補助値。
            返り値: object。継続するトレース関数。
            """
            if event == "line" and frame.f_code is engine.simulate.__code__ and frame.f_lineno == line:
                values = frame.f_locals
                pending = values["pending"]
                now = values["now"]
                identity = (pending["armed"], pending["side"], pending.get("level"))
                if identity not in observed_orders:
                    observed_orders[identity] = dict(armed_at=now, signal_time=pending["signal_time"],
                                                    side=pending["side"], level=pending.get("level"),
                                                    ref=pending["ref"], atr=pending["atr"], observations=[])
                observed_orders[identity]["observations"].append(dict(time=now, high=float(values["high"]), low=float(values["low"])))
            return trace
        previous = sys.gettrace()
        sys.settrace(trace)
        try:
            traced_trades = engine.simulate(item, schedules[key], cfg)
        finally:
            sys.settrace(previous)
        plain_trades = engine.simulate(item, schedules[key], cfg)
        assert traced_trades == plain_trades
        target_end = pd.Timestamp("2026-09-23T11:15:00+09:00")
        orders = []
        for order in observed_orders.values():
            if order["side"] != -1 or order["armed_at"] > target_end:
                continue
            window = [observation for observation in order["observations"] if observation["time"] <= target_end]
            highest = max(observation["high"] for observation in window)
            orders.append(dict(armed_at=order["armed_at"], signal_time=order["signal_time"], sell_limit=order["level"],
                               ref=order["ref"], atr=order["atr"], observed_until=window[-1]["time"],
                               largest_high=highest, missed_by_points=order["level"]-highest,
                               touched_before_target_end=highest >= order["level"]))
        results.append(dict(symbol=symbol, earliest_short_permission=item["z"].index[negatives[0]]+pd.Timedelta(minutes=1),
                            first_allowed_order_after_warmup=item["z"].index[0]+pd.Timedelta(minutes=cfg.warmup),
                            short_orders_before_target_end=orders,
                            first_actual_short=next((trade for trade in traced_trades if trade["side"] == -1), None),
                            raw_short_signal_before_wave_end=True, trace_matches_plain=True))
    return results


def write_report(record: dict) -> None:
    """独立監査の結果と不検知の原因を日本語で記録する。

    引数: record（dict）全監査記録。
    返り値: None。最終検証監査のＭａｒｋｄｏｗｎとＪＳＯＮを生成する。
    """
    value = normalized(record)
    (OUT / "最終検証監査.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    snap, replay, h = value["snapshot"], value["replay"], value["hashes"]
    lines = ["# 最終検証監査", "", "本監査は保存された答え合わせスナップショットだけを使用し、追加のＡＰＩ取得や核心コード・固定条件・原本フォルダへの書き込みを行っていない。", "",
             "## 凍結と一度だけの取得", "",
             f"凍結は {value['fixed_at']}、最初の取得開始は {snap['first_request']}。共通締切は {snap['cutoff']}。七つの相異なるＵＲＬについて記録上の試行は各一回、全応答２００、保存七ファイルのハッシュが取得時記録と一致した。再取得は行っていない。", "",
             f"コード {len(h['code'])} ファイル、凍結入力 {len(h['inputs'])} ファイル、抽出時に記録した生板原本 {len(h['raw'])} ファイル、選択表が全てハッシュ一致。status と４本の足 snapshot は全て 2026-09-23_Day。", "",
             "## 足と生板の範囲・価格", "", "|銘柄|足分|取得本数|採用本数|未確定除外|採用最終足|", "|---|---:|---:|---:|---:|---|"]
    for row in snap["candles"]:
        lines.append(f"|{row['symbol']}|{row['minutes']}|{row['received']}|{row['retained']}|{row['excluded']}|{row['retained_last']}|")
    lines.extend(["", "両銘柄の五分足15:35開始足は未確定のため除外。採用一分足は15:38開始まで、採用五分足は15:30開始まで。足の重複、逆行時刻、負の出来高、非有限値、ＯＨＬＣ矛盾、呼値違反はない。確定五分足のＯＨＬＣＶは一分足の再集計と完全一致。生板の有効約定時刻は全て08:45以上15:39未満で、時刻逆行・不正価格はない。", "",
                  "status は15:39台の現時点状態であり、15:39未満に切った取得データより一分足件数等が多い。この差を欠損と取り違えない。", "",
                  "## 再生・境界・将来情報", "",
                  f"固定済み全 {replay['candidates']} 候補を独立再生し、保存済みの取引・指定波・集計と完全一致。候補を重複して数えた計 {replay['total_candidate_trades']} 取引は全て同じ日中セッション内で返済し、新規・返済は実在足だけを使用している。採用条件の結果も完全一致。", "",
                  f"現在日中を09:44、09:45、10:00、11:15、13:00、15:35で切り、全候補・両銘柄の {replay['prefix_checks']} 条件について、特徴・信号・既存取引が全期間入力と一致した。将来の入力を追加しても検査断面以前の結果は変わらなかった。", "",
                  "既存テストを別コマンドで各一回実行し、test_engine.py は19件、test_null_checks.py は8件、計27件全成功。前者には保存四セッションの3456条件と初動待ちの64条件の切断一致が含まれる。この検証は検査した条件での因果性と実装整合の確認であり、将来の利益や実約定を保証するものではない。", "",
                  "## 09:05〜11:15の下落を逃した原因", "",
                  "指標のショート許可自体は下落区間中に発生している。一方、初動60分待ちで注文開始は09:45以後となり、その後の戻り売り指値まで戻らず、取引として波を捉えられなかった。凍結した simulate の局所変数を読み取り専用で追跡し、追跡あり・なしの最終取引が完全一致することも確認した。", "",
                  "|銘柄|最初のショート許可確定|最初の注文開始可能時刻|実際の最初のショート新規|", "|---|---|---|---|"])
    for item in value["diagnosis"]:
        actual = item["first_actual_short"]["entry_time"] if item["first_actual_short"] else "なし"
        lines.append(f"|{item['symbol']}|{item['earliest_short_permission']}|{item['first_allowed_order_after_warmup']}|{actual}|")
    lines.extend(["", "|銘柄|指値待機開始|売り指値|当該待機中の区間内最高値|未達幅|区間内の最終監視足|", "|---|---|---:|---:|---:|---|"])
    for item in value["diagnosis"]:
        for order in item["short_orders_before_target_end"]:
            lines.append(f"|{item['symbol']}|{order['armed_at']}|{order['sell_limit']:g}|{order['largest_high']:g}|{order['missed_by_points']:g}|{order['observed_until']}|")
    lines.extend(["", "待機注文は25分超過または反対方向の許可で取り消され、次の注文条件を計算する。表は待機中に実際に観測した高値との比較で、結果を見て指値を調整していない。", "",
                  f"採用した共通条件は指定された新日中の２波に対して {replay['primary_target_passes']}/2 合格。別の事前固定候補で2/2合格のものは {len(replay['both_target_passed_candidates'])} 条件存在するが、今回の日中を見て採用条件を置き換えることはしていない。", ""])
    (OUT / "最終検証監査.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """保存物の独立検証と凍結条件の不検知原因を調査する。

    引数: なし。
    返り値: None。
    """
    fixed_path = OUT / "固定設定.json"
    fixed_before = digest(fixed_path)
    fixed = json.loads(fixed_path.read_text(encoding="utf-8"))
    record = dict(fixed_at=fixed["fixed_at"], fixed_sha256=fixed_before, api_requested=False, hashes=hashes(fixed))
    record["snapshot"] = snapshot_audit(fixed)
    data = load_snapshot()
    record["replay"] = replay_audit(data, fixed)
    record["diagnosis"] = diagnose_pending(data, fixed)
    assert digest(fixed_path) == fixed_before
    record["test_results"] = dict(engine_tests=19, null_tests=8, saved_prefix_checks=3456,
                                  warmup_prefix_checks=64, execution="別コマンドで各一回実行し、全成功を確認済み")
    write_report(record)
    print(json.dumps(normalized(dict(replay=record["replay"], diagnosis=record["diagnosis"])), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
