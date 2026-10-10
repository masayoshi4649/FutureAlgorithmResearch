"""採用候補の約定仮定と連続追跡条件を保存生板の利用可能系列で監査する。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from engine import rounded
from raw_execution import quote_near_time, read_observations


OUT = Path(__file__).resolve().parent
TICKS = {"NK225": 10.0, "TOPIX": .5}


def time_value(value: str | datetime) -> datetime:
    """保存された時刻をタイムゾーン付き日時へ変換する。

    引数: value（str | datetime）保存時刻。
    返り値: datetime。タイムゾーンなしの場合は例外。
    """
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if stamp.tzinfo is None:
        raise ValueError("タイムゾーンのない時刻です")
    return stamp


def session_deadline(trade: dict) -> datetime:
    """セッション境界前に設定した返済指示時刻を得る。

    引数: trade（dict）候補の仮想取引。
    返り値: datetime。日中15時35分、夜間翌5時50分。
    """
    first = time_value(trade["entry_time"])
    day = datetime.fromisoformat(trade["session"].split("_")[0]).replace(tzinfo=first.tzinfo)
    return day + (timedelta(days=1, hours=5, minutes=50) if trade["session"].endswith("Night") else timedelta(hours=15, minutes=35))


def entry_quote_audit(events: list[dict], times: list[datetime], trade: dict) -> dict:
    """新規分ラベルの直前既知気配と分内の指値条件に適合する気配を調べる。

    引数: events（list[dict]）生板観測、times（list[datetime]）対応する利用可能時刻、trade（dict）候補取引。
    返り値: dict。指値仮定の観測支持と時刻上の限界。実約定の成立判定ではない。
    """
    stamp, price, side = time_value(trade["entry_time"]), trade["entry_price"], trade["side"]
    tick = TICKS[trade["symbol"]]
    latest = quote_near_time(events, stamp, max_stale_seconds=60)
    usable = []
    begin, end = bisect_left(times, stamp), bisect_left(times, stamp + timedelta(minutes=2))
    for event in events[begin:end]:
        if event["quote_valid"] and event["source_trade_time"] >= stamp:
            usable.append(event)
    def compatible(event: dict) -> bool:
        """指値価格で即時反対気配と一致できる側にあるか判定する。

        引数: event（dict）有効な最良売買気配。
        返り値: bool。買いは売気配以下条件、売りは買気配以上条件。
        """
        return event["ask"] <= price if side == 1 else event["bid"] >= price
    minute_events = [event for event in usable if event["available_at"] < stamp + timedelta(minutes=1)]
    matches = [event for event in minute_events if compatible(event)]
    matches_two = [event for event in usable if compatible(event)]
    adverse = (side * ((latest["ask"] if side == 1 else latest["bid"]) - price) / tick) if latest else None
    return {
        "known_quote_at_minute_start": None if latest is None else {
            "available_at": latest["available_at"].isoformat(), "source_trade_time": latest["source_trade_time"].isoformat(),
            "bid": latest["bid"], "ask": latest["ask"], "spread": latest["spread"],
            "price_age_seconds": (stamp - latest["source_trade_time"]).total_seconds(),
            "adverse_ticks_to_cross": adverse,
        },
        "valid_quote_observations_entry_minute": len(minute_events),
        "entry_minute_touch_at_price": bool(matches),
        "entry_plus_one_minute_touch_at_price": bool(matches_two),
        "first_compatible_quote_available": matches_two[0]["available_at"].isoformat() if matches_two else None,
        "first_compatible_quote_source": matches_two[0]["source_trade_time"].isoformat() if matches_two else None,
        "condition_interpretation": "仮想新規価格で反対最良気配を取れる観測があったか。指値注文の待ち行列と実約定は不明。",
    }


def continuous_observation(events: list[dict], times: list[datetime], trade: dict,
                           trail: float, trigger: str, delay_minutes: int = 0) -> dict:
    """新規条件を固定し、保存観測が届くたびに追跡極値を更新する対照を作る。

    引数: events（list[dict]）生板観測、times（list[datetime]）利用可能時刻、trade（dict）一分足の候補取引、trail（float）ＡＴＲ追跡倍数、trigger（str）last_priceまたはquote、delay_minutes（int）開始分を除外する感度条件。
    返り値: dict。連続追跡条件の初回成立観測と一分足返済との先後。実約定損益ではない。
    """
    side, price, atr = trade["side"], trade["entry_price"], trade["atr"]
    tick = TICKS[trade["symbol"]]
    entry = time_value(trade["entry_time"])
    begin = entry + timedelta(minutes=delay_minutes)
    deadline = session_deadline(trade)
    initial = rounded(price - side * min(2.5, trail) * atr, tick, side == -1)
    stop, peak, observations = initial, side * price, 0
    largest_age, skipped_old, invalid_quotes = 0.0, 0, 0
    source_key = "last_price" if trigger == "last_price" else "bid" if side == 1 else "ask"
    result = {"trigger_reference": trigger, "delay_minutes": delay_minutes,
              "assumed_entry_time": entry.isoformat(), "monitor_start": begin.isoformat(),
              "initial_stop": initial, "trail_distance": trail * atr, "triggered": False}
    for event in events[bisect_right(times, begin):]:
        if event["source_trade_time"] < begin:
            skipped_old += 1
            continue
        if trigger == "quote" and not event["quote_valid"]:
            invalid_quotes += 1
            continue
        value = event[source_key]
        if value is None:
            continue
        observations += 1
        largest_age = max(largest_age, event["staleness_seconds"])
        timed_exit = event["available_at"] >= deadline
        if timed_exit or side * (value - stop) <= 0:
            observed_at = event["available_at"]
            baseline_exit = time_value(trade["exit_time"]) if trade["closed"] else None
            delta = (observed_at - baseline_exit).total_seconds() / 60 if baseline_exit else None
            relation = None if baseline_exit is None else "前の分に成立" if observed_at < baseline_exit else "同じ分に成立" if observed_at < baseline_exit + timedelta(minutes=1) else "後の分に成立"
            result.update({
                "triggered": True, "observed_at": observed_at.isoformat(),
                "source_trade_time": event["source_trade_time"].isoformat(), "source_row": event["source_row"],
                "trigger_price": value, "stop_price": stop, "reason": "セッション内の時刻返済" if timed_exit else "連続観測の追跡条件成立",
                "bid": event["bid"], "ask": event["ask"], "staleness_seconds": event["staleness_seconds"],
                "baseline_exit_time": trade["exit_time"], "baseline_exit_price": trade["exit_price"],
                "relative_exit_minute": relation, "minutes_from_baseline_exit": delta,
                "gross_points_at_observed_reference": side * (value - price),
                "difference_from_baseline_gross": side * (value - price) - trade["gross_points"] if trade["closed"] else None,
            })
            break
        peak = max(peak, side * value)
        next_stop = rounded(side * (peak - trail * atr), tick, side == -1)
        stop = max(stop, next_stop) if side == 1 else min(stop, next_stop)
    result.update(observations=observations, max_staleness_seconds=largest_age,
                  ignored_observations_before_monitor=skipped_old, invalid_quote_observations=invalid_quotes,
                  final_stop_price=stop)
    return result


def candidate_configs(candidate: dict) -> dict[str, dict]:
    """共通候補または銘柄別固定設定を同じ参照構造へ揃える。

    引数: candidate（dict）configまたはsymbol_configsを持つ採用結果。
    返り値: dict[str, dict]。銘柄ごとの追跡幅と主モデルの更新方式。
    """
    if "symbol_configs" in candidate:
        configs = candidate["symbol_configs"]
        if not all(symbol in configs for symbol in TICKS):
            raise ValueError("銘柄別設定に対象銘柄が不足しています")
        return {symbol: configs[symbol] for symbol in TICKS}
    if "config" in candidate:
        return {symbol: candidate["config"] for symbol in TICKS}
    raise ValueError("候補ファイルに共通または銘柄別設定がありません")


def summarize(rows: list[dict]) -> list[dict]:
    """同一新規を固定した監査の先後件数を銘柄・価格参照ごとに整理する。

    引数: rows（list[dict]）取引別監査。
    返り値: list[dict]。実戦略損益を合計しない件数表。
    """
    result = []
    for symbol in TICKS:
        selected = [row for row in rows if row["symbol"] == symbol]
        for trigger in ("last_price", "quote"):
            for delay in (0, 1):
                checks = [next(check for check in row["continuous_checks"]
                               if check["trigger_reference"] == trigger and check["delay_minutes"] == delay) for row in selected]
                result.append({
                    "instrument": symbol, "trigger_reference": trigger, "delay_minutes": delay,
                    "trades": len(selected), "before": sum(check.get("relative_exit_minute") == "前の分に成立" for check in checks),
                    "same_minute": sum(check.get("relative_exit_minute") == "同じ分に成立" for check in checks),
                    "after": sum(check.get("relative_exit_minute") == "後の分に成立" for check in checks),
                    "no_observed_exit": sum(not check["triggered"] for check in checks),
                    "entry_minute_quote_support": sum(row["entry_quote"]["entry_minute_touch_at_price"] for row in selected),
                    "entry_two_minutes_quote_support": sum(row["entry_quote"]["entry_plus_one_minute_touch_at_price"] for row in selected),
                })
    return result


def write_report(record: dict, stem: str) -> None:
    """監査明細と離散・連続追跡の差を報告書へ保存する。

    引数: record（dict）監査結果、stem（str）出力名の基部。
    返り値: None。日本語のＪＳＯＮとＭａｒｋｄｏｗｎを生成する。
    """
    (OUT / f"{stem}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 候補の生板観測による注文監査", "",
             f"対象: `{record['candidate']}`。銘柄別設定 `{record['symbol_configs']}`。保存済み四セッションだけを使用し、ＡＰＩには接続していない。候補ファイルの SHA-256 は `{record['candidate_sha256']}`。", "",
             "主モデルは確定一分足の高値・安値を使って次の足のストップ水準を更新する離散追跡である。本監査は同じ新規時刻・新規価格・新規ＡＴＲ・初期保護幅を固定し、利用可能になった各生板観測ごとに極値を更新する固定幅の連続追跡対照。初期保護幅は min(2.5, 銘柄別追跡倍数)×新規ＡＴＲ、対照の追跡幅は銘柄別設定倍数×新規ＡＴＲ、呼値丸めも主モデルと同じ。", "",
             "主モデルの trail_basis が entry の場合、参照する追跡幅は共通だが、足の確定と各観測の違いがある。current や regime の場合、主モデルはその時点のＡＴＲや相場状態で追跡幅を更新する一方、この対照は新規時ＡＴＲの固定幅である。従って current・regime に対する先後差は追跡幅と更新頻度の両方の変更を含み、正本と同一条件の再現でも、連続更新だけの効果でもない。", "",
             "生板に受信時刻はない。同じ最終約定時刻のブロックを次の約定時刻で利用可能とするため、観測条件の成立が実際より遅れる可能性がある。元約定時刻が新規より前の行は追跡に入れない。ただし最終約定時刻が古くても板更新が新規後という可能性は残り、この除外で新しい板も落ち得る。従って実際の連続追跡を再現した成績でも、厳密な有利不利の上限・下限でもない。返済側気配は買い保有なら Buy1、売り保有なら Sell1。新規足内の実約定時点が不明なので、開始を一分遅らせた感度も併記する。", "",
             "新規直前気配は六十秒以内の価格時刻のみ採る。新規分内の反対最良気配が仮想新規価格を満たしたかを調べるが、待ち行列・数量・注文到着遅延が不明なため、支持ありは確実な約定を意味せず、支持なしも不成立の証明ではない。新規価格が保存足の安値・高値だけに接触した場合は、特に約定仮定が楽観的になり得る。", "",
             "同じ新規を固定した取引別対照であり、返済後の再新規・クールダウンを再計算していない。返済時刻の変更で元の別取引と重なる可能性もあるため、対照の損益を実戦略成績として合計しない。", "",
             "## 返済条件成立の先後", "", "|銘柄|参照価格|開始遅延分|件数|主モデルより前の分|同じ分|後の分|未到達|", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in record["summary"]:
        lines.append(f"|{row['instrument']}|{row['trigger_reference']}|{row['delay_minutes']}|{row['trades']}|{row['before']}|{row['same_minute']}|{row['after']}|{row['no_observed_exit']}|")
    lines.extend(["", "## 仮想新規価格と気配の整合", "", "|銘柄|新規件数|新規分内に対応気配あり|次の一分まで含めてあり|", "|---|---:|---:|---:|"])
    for symbol in TICKS:
        row = next(item for item in record["summary"] if item["instrument"] == symbol)
        lines.append(f"|{symbol}|{row['trades']}|{row['entry_minute_quote_support']}|{row['entry_two_minutes_quote_support']}|")
    lines.extend(["", "## 大きな差と観測の限界", ""])
    for row in record["trades"]:
        quote = next(check for check in row["continuous_checks"] if check["trigger_reference"] == "quote" and check["delay_minutes"] == 0)
        prefix = f"{row['symbol']} {row['session']} {row['entry_time']} の{'買い' if row['side'] == 1 else '売り'}"
        if quote.get("minutes_from_baseline_exit", 0) < -5:
            lines.append(f"- {prefix}: 一分足の返済 {row['exit_time']} に対し、返済側気配を追う条件成立は {quote['observed_at']}。約 {-quote['minutes_from_baseline_exit']:.1f} 分前倒しとなり、その参照価格での粗損益差は {quote['difference_from_baseline_gross']:g}。")
        if not row["entry_quote"]["entry_plus_one_minute_touch_at_price"]:
            lines.append(f"- {prefix}: 仮想新規価格 {row['entry_price']:g} で反対最良気配を取れる観測は、新規分と次の一分を合わせても見つからない。指値接触を確実な約定とする前提には注意が必要。")
        if quote.get("staleness_seconds", 0) > 60:
            lines.append(f"- {prefix}: 返済条件を観測した時刻 {quote['observed_at']} の元最終約定時刻との差は {quote['staleness_seconds']:g} 秒。条件成立時刻と価格を現実の約定として確定できない。")
    lines.extend(["", "## 取引別・開始遅延なし", "", "|銘柄・セッション|向き|一分足の新規|一分足の返済|約定値参照の条件成立|返済側気配参照の条件成立|指値の分内気配支持|", "|---|---|---|---|---|---|---|"])
    for row in record["trades"]:
        last = next(check for check in row["continuous_checks"] if check["trigger_reference"] == "last_price" and check["delay_minutes"] == 0)
        quote = next(check for check in row["continuous_checks"] if check["trigger_reference"] == "quote" and check["delay_minutes"] == 0)
        last_text = last.get("observed_at", "未到達")
        quote_text = quote.get("observed_at", "未到達")
        lines.append(f"|{row['symbol']} {row['session']}|{'買い' if row['side'] == 1 else '売り'}|{row['entry_time']}|{row['exit_time']}|{last_text}|{quote_text}|{'あり' if row['entry_quote']['entry_minute_touch_at_price'] else 'なし'}|")
    lines.extend(["", "主モデルを実装する場合は、保有中の逆指値を確定一分ごとに更新する方式と、ＡＰＩの trail による連続追跡を区別する。条件参照価格や取消・変更時の挙動はＡＧＥＮＴＳの表だけでは確定しない。", ""])
    (OUT / f"{stem}.md").write_text("\n".join(lines), encoding="utf-8")


def self_test() -> None:
    """同じ一分内の高値から反落する場合に連続追跡を検出する。

    引数: なし。
    返り値: None。不整合時は例外。
    """
    entry = time_value("2026-09-22T17:00:00+09:00")
    events = []
    for second, price in ((10, 102), (20, 106), (30, 101)):
        stamp = entry + timedelta(seconds=second)
        events.append(dict(available_at=stamp, source_trade_time=stamp-timedelta(seconds=1),
                           source_row=second, last_price=price, bid=price-.5, ask=price+.5,
                           quote_valid=True, staleness_seconds=1.0))
    trade = dict(symbol="TOPIX", session="2026-09-22_Night", side=1, entry_time=entry,
                 entry_price=100.0, atr=1.0, closed=True, exit_time=entry+timedelta(minutes=2), exit_price=99, gross_points=-1)
    result = continuous_observation(events, [event["available_at"] for event in events], trade, 4, "last_price")
    assert result["triggered"] and result["trigger_price"] == 101 and result["stop_price"] == 102
    assert result["relative_exit_minute"] == "前の分に成立"
    reverse = [{**event, "last_price": 200-event["last_price"], "bid": 200-event["ask"], "ask": 200-event["bid"]} for event in events]
    short_trade = {**trade, "side": -1, "exit_price": 101}
    result = continuous_observation(reverse, [event["available_at"] for event in reverse], short_trade, 4, "last_price")
    assert result["triggered"] and result["trigger_price"] == 99 and result["stop_price"] == 98
    config = {"trail": 4, "trail_basis": "current"}
    assert candidate_configs({"config": config})["NK225"] == config
    assert candidate_configs({"symbol_configs": {"NK225": config, "TOPIX": {"trail": 2.5}}})["TOPIX"]["trail"] == 2.5


def main() -> None:
    """候補ファイルを読み、全保存セッションの生板対照を生成する。

    引数: なし。コマンド行で候補ファイル、出力名、基本試験だけの実行を指定可能。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="候補の離散追跡と保存生板の連続追跡観測の比較")
    parser.add_argument("--candidate", default="採用_開発結果.json")
    parser.add_argument("--output", default="採用候補生板監査")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    self_test()
    if args.self_test:
        print("候補の連続追跡監査の基本検証に成功")
        return
    candidate_bytes = (OUT / args.candidate).read_bytes()
    candidate = json.loads(candidate_bytes)
    configs = candidate_configs(candidate)
    groups = defaultdict(list)
    for trade in candidate["trades"]:
        groups[(trade["symbol"], trade["session"])].append(trade)
    rows = []
    for (symbol, session), trades in sorted(groups.items()):
        path = OUT / f"生板観測_{symbol}_{session}.csv"
        events = read_observations(path)
        times = [event["available_at"] for event in events]
        for trade in trades:
            config = configs[symbol]
            rows.append({**trade, "entry_quote": entry_quote_audit(events, times, trade),
                         "baseline_trail_basis": config.get("trail_basis", "entry"),
                         "comparison_trail_basis": "entry", "comparison_trail_multiple": config["trail"],
                         "width_basis_changed": config.get("trail_basis", "entry") != "entry",
                         "continuous_checks": [continuous_observation(events, times, trade, config["trail"], trigger, delay)
                                               for trigger in ("last_price", "quote") for delay in (0, 1)]})
        print(f"生板監査完了: {symbol} {session} {len(trades)} 取引", flush=True)
    record = {"candidate": args.candidate, "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
              "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "symbol_configs": configs, "api_requested": False,
              "model": "元の新規を固定し、固定幅連続追跡の条件成立を観測する対照。current/regime基準の正本とは追跡幅の基準も異なる。新戦略の実約定損益ではない。",
              "trades": rows, "summary": summarize(rows)}
    write_report(record, args.output)
    print(json.dumps(record["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
