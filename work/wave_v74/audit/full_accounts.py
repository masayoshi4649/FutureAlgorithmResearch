"""凍結480条件の全台帳・全清算曲線・期間会計・前半選定を独立集計する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from adapters import clearing_curve, orders9, trades12
from causality import ROOT, study
from independent_account import near, reconstruct, save


HERE = Path(__file__).resolve().parent
SUM_FIELDS = ("profit", "loss", "net", "gross", "fees", "wins", "losses", "flats", "trades",
    "winning_lots", "losing_lots", "flat_lots", "pause_count", "resume_count", "paused_seconds",
    "resumed_trades", "resumed_net", "hold_seconds", "spread_drag")


def metrics(a: dict) -> dict:
    """機能: 期間指標を合計金額から独立に計算する。

    引数: a(dict)。返り値: 比率等を追加した会計(dict)。
    """
    profit, loss, count = a["profit"], a["loss"], a["trades"]
    a.update(money_loss_share=loss / (profit + loss) if profit + loss else None,
        profit_loss_ratio=profit / loss if loss else None,
        average_win=profit / a["wins"] if a["wins"] else None,
        average_loss=loss / a["losses"] if a["losses"] else None,
        average_net=a["net"] / count if count else None,
        win_rate=a["wins"] / count if count else None,
        payoff=(profit / a["wins"]) / (loss / a["losses"]) if a["wins"] and a["losses"] else None,
        average_hold_seconds=a["hold_seconds"] / count if count else None)
    return a


def row_account(key: tuple, c: dict, r: dict, f: dict, p: dict, ledger: dict) -> dict:
    """機能: 注文から全金額を再構成し、料金後連敗と追跡返済理由を検査する。

    引数: key(tuple)、c/r/f/p/ledger(dict)。返り値: 独立場会計(dict)。
    """
    symbol = key[1]
    data = dict(time_s=r["time_s"], seq=r["seq"], bid=f["bid"], ask=f["ask"])
    a, equity = reconstruct(data, dict(symbol=symbol, session=key[0], orders=orders9(ledger["orders"])), True)
    curve = clearing_curve(symbol, ledger["orders"], equity)
    assert hashlib.sha256(curve.tobytes()).hexdigest() == ledger["curve_hash"], ("全行清算曲線指紋", key, c["id"])
    expected = np.asarray([[d["campaign"], d["entry_row"], d["exit_row"], d["side"], d["quantity"], d["entry"], d["exit"],
        d["entry_fee"], d["exit_fee"], d["gross"], d["net"], 0] for d in a["details"]], dtype=float).reshape((-1, 12))
    np.testing.assert_allclose(trades12(ledger["trades"]), expected, rtol=0, atol=1.e-4)
    orders, trades, pauses, stats = ledger["orders"], ledger["trades"], ledger["pauses"], ledger["stats"]
    assert stats[0] == 0 and stats[1] in (0, 1) and len(orders) == 2 * len(trades)
    qty = 10 if symbol == "TOPIX" else 20
    multiplier = 1000. if symbol == "TOPIX" else 10.
    width = max(2., np.ceil(p["open_price"] * c["width_fraction"] / r["tick"] - 1.e-10)) * r["tick"]
    entry_width = max(1., np.ceil(p["open_price"] * c["entry_fraction"] / r["tick"] - 1.e-10)) * r["tick"]
    direct = p["direction"][(c["reference"], c["band"])] * (-1 if c["inverse"] else 1)
    qok = np.isfinite(f["bid"]) & np.isfinite(f["ask"]) & (f["bid"] > 0) & (f["ask"] >= f["bid"])
    by_cid = {int(trade[0]): trade for trade in trades}
    for order in orders:
        row, decision, cid, side, quantity, _, reason, opened = order
        row, decision, cid, side, reason = map(int, (row, decision, cid, side, reason))
        assert quantity == qty
        if opened:
            assert qok[decision] and p["quality"][decision] and not f["reset"][decision]
            assert int(direct[decision]) == side
            assert r["start"] + 300. <= r["time_s"][decision] < r["limit"] - 300. and r["time_s"][row] < r["limit"] - 300.
            assert reason == (10 if c["entry_type"] == 0 else 11)
        else:
            trade = by_cid[cid]
            entry_i, held_side, entry = int(trade[1]), int(trade[3]), float(trade[5])
            assert row > decision > entry_i and r["time_s"][row] < r["limit"] + 300., ("返済の監視区間境界", c["id"], key, order.tolist(), entry_i, r["time_s"][row], r["limit"])
            if reason == 4:
                assert r["time_s"][decision] >= r["limit"] - 60.
            elif reason == 3:
                assert r["time_s"][decision] - r["time_s"][entry_i] >= c["hold_seconds"]
            elif reason in (1, 2):
                indices = np.arange(entry_i + 1, decision + 1)[qok[entry_i + 1:decision + 1]]
                quote = f["bid"] if held_side == 1 else f["ask"]
                extreme = max(entry, float(np.max(quote[indices]))) if held_side == 1 else min(entry, float(np.min(quote[indices])))
                assert held_side * (quote[decision] - extreme) <= -width + r["tick"] * 1.e-8
                assert reason == (1 if abs(extreme - entry) < r["tick"] * 1.e-8 else 2)
            else:
                assert reason == 5 and c["exit_on_reverse"] and direct[decision] == -held_side
    starts = list(pauses[pauses[:, 1] == 0, 0].astype(int))
    ends = list(pauses[pauses[:, 1] == 1, 0].astype(int))
    assert len(starts) == stats[5] and len(ends) == stats[6]
    assert len(starts) in (len(ends), len(ends) + 1)
    pause_span = []
    for index, began in enumerate(starts):
        ended = ends[index] if index < len(ends) else len(r["time_s"])
        assert ended > began and (index == 0 or began > ends[index - 1])
        for order in orders[orders[:, 7] == 1]:
            assert not began <= int(order[1]) < ended, ("休止中の入口", key, c["id"], order)
        pause_span.append(max(0., min(r["time_s"][ended] if ended < len(r["time_s"]) else r["limit"] - 60., r["limit"] - 60.) - r["time_s"][began]))
        if ended < len(r["time_s"]) and c["pause_mode"] in (1, 2, 4, 5):
            wait = 600. if c["pause_mode"] in (1, 4) else 1800.
            assert r["time_s"][ended] - r["time_s"][began] >= wait
    events = {int(event[0]): event for event in pauses}
    exiting = {int(trade[2]): float(trade[10]) for trade in trades}
    streak = 0
    for row in sorted(set(events) | set(exiting)):
        if row in exiting:
            streak = streak + 1 if exiting[row] < 0 else 0 if exiting[row] > 0 else streak
        if row in events:
            event = events[row]
            assert int(event[4]) == streak and int(event[2]) == c["pause_mode"]
            if event[1] == 0:
                assert row in exiting and exiting[row] < 0 and streak >= (3 if c["pause_mode"] == 5 else 2)
            else:
                streak = 0
    assert int(stats[4]) == streak
    resumed = set()
    for ended in ends:
        candidates = np.flatnonzero(trades[:, 1] > ended)
        if len(candidates):
            resumed.add(int(candidates[0]))
    mid = (f["bid"] + f["ask"]) / 2.
    ideal_gross = sum(t[3] * (mid[int(t[2])] - mid[int(t[1])]) * qty * multiplier for t in trades)
    a.update(pause_count=len(starts), resume_count=len(ends), paused_seconds=float(sum(pause_span)),
        resumed_trades=len(resumed), resumed_net=float(sum(trades[j, 10] for j in resumed)),
        hold_seconds=float(sum(r["time_s"][int(t[2])] - r["time_s"][int(t[1])] for t in trades)),
        width=float(width), entry_width=float(entry_width), spread_drag=float(ideal_gross - a["gross"]),
        missing_reference=p["missing_previous"] and c["reference"] in (1, 2),
        max_trade_loss=max((-t["net"] for t in a["details"]), default=0.),
        drawdown=float(np.max(np.maximum.accumulate(np.maximum(curve, 0.)) - curve)), equity_min=float(curve.min()), equity_max=float(curve.max()),
        reasons={str(code): int(((orders[:, 6] == code) & (orders[:, 7] == 0)).sum()) for code in study.engine.REASONS})
    a["予定撤収時刻超過返済数"] = int(sum(r["time_s"][int(order[0])] >= r["limit"] for order in orders if order[7] == 0))
    a["予定撤収超過最大秒"] = max((max(0., r["time_s"][int(order[0])] - r["limit"]) for order in orders if order[7] == 0), default=0.)
    a["判断から約定の最大秒"] = max((r["time_s"][int(order[0])] - r["time_s"][int(order[1])] for order in orders), default=0.)
    a["max_trade_loss"] = max(0., a["max_trade_loss"])
    return metrics(a)


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """機能: 商品別全場損益を再合計し、黒字場除外や期間下落も独立に求める。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 期間会計(dict)。
    """
    subset = sorted((r for r in rows if r["symbol"] == symbol and r["session"] in sessions), key=lambda r: r["session"])
    a = {field: sum(row[field] for row in subset) for field in SUM_FIELDS}
    a.update(active_sessions=sum(row["trades"] > 0 for row in subset), positive_sessions=sum(row["net"] > 0 for row in subset),
        max_trade_loss=max((row["max_trade_loss"] for row in subset), default=0.),
        without_best_session=a["net"] - max((row["net"] for row in subset), default=0.),
        max_long=max((row["max_long"] for row in subset), default=0), max_short=max((row["max_short"] for row in subset), default=0),
        missing_reference_sessions=sum(row["missing_reference"] for row in subset))
    total = peak = dd = 0.
    for row in subset:
        dd = max(dd, row["drawdown"], peak - total - row["equity_min"])
        peak = max(peak, total + row["equity_max"])
        total += row["net"]
    a["drawdown"] = dd
    return metrics(a)


def same_fields(actual: dict, expected: dict, label: object) -> int:
    """機能: 保存された全項目を独立会計に照合する。

    引数: actual/expected(dict)、label(object)。返り値: 比較項目数(int)。
    """
    for field, value in expected.items():
        assert field in actual, ("独立値に項目がない", field, label)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            near(actual[field], value, str((label, field)))
        else:
            assert actual[field] == value, (label, field, actual[field], value)
    return len(expected)


def main() -> None:
    """機能: 凍結した全条件を独立会計し、前半のみの選択を再現する。

    引数: --extension(bool)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--extension", action="store_true")
    cli = parser.parse_args()
    original = study.load(HERE.parent / "事前固定.json")
    assert all(study.digest(ROOT / name) == expected for name, expected in original["SHA256"].items())
    area = HERE.parent / "extension" if cli.extension else HERE.parent
    fixed = study.load(area / "追記固定.json") if cli.extension else original
    assert all(study.digest(ROOT / name) == expected for name, expected in fixed["SHA256"].items())
    ready, features, meta = study.material()
    prepared = study.prepare(ready, features, meta)
    configurations = fixed.get("再利用条件", []) + fixed["条件"]
    configured_total = 288 if cli.extension else 480
    assert len(configurations) == configured_total and len({c["id"] for c in configurations}) == configured_total
    assert len(list((area / "results").glob("*.json"))) == (240 if cli.extension else 480)
    reused_ids = {c["id"] for c in fixed.get("再利用条件", [])}
    if cli.extension:
        assert fixed["事後追加"] and fixed["第1段階結果を閲覧済み"] and fixed["第2段階結果を見る前に固定"]
        old_by_id = {c["id"]: c for c in original["条件"]}
        assert all(old_by_id[c["id"]] == c for c in fixed["再利用条件"])
        assert len(reused_ids) == 48 and len(fixed["条件"]) == 240
    total_accounts = fields = trades = orders = intervals = late_exits = late_accounts = 0
    max_late = max_fill_delay = 0.
    independent_periods = {}
    for index, c in enumerate(configurations):
        source = HERE.parent if c["id"] in reused_ids else area
        packet = study.load(source / "results" / (c["id"] + ".json"))
        ledger_file = source / "ledgers" / (c["id"] + ".pkl")
        assert packet["config"] == c and packet["ledger_SHA256"] == study.digest(ledger_file)
        ledger = study.load(ledger_file)
        assert set(ledger) == set(ready) and len(packet["rows"]) == 58
        saved_rows = {(row["session"], row["symbol"]): row for row in packet["rows"]}
        rows = []
        for key in sorted(ready):
            actual = row_account(key, c, ready[key], features[key], prepared[key], ledger[key])
            fields += same_fields(actual, saved_rows[key], (c["id"], key))
            rows.append(actual)
            total_accounts += 1
            trades += actual["trades"]
            orders += len(ledger[key]["orders"])
            late_exits += actual["予定撤収時刻超過返済数"]
            late_accounts += int(actual["予定撤収時刻超過返済数"] > 0)
            max_late = max(max_late, actual["予定撤収超過最大秒"])
            max_fill_delay = max(max_fill_delay, actual["判断から約定の最大秒"])
        periods = {}
        for period in ("前16", "後13", "全29"):
            periods[period] = {}
            for symbol in ("TOPIX", "NK225"):
                actual = aggregate(rows, symbol, fixed[period])
                fields += same_fields(actual, packet["periods"][period][symbol], (c["id"], period, symbol))
                periods[period][symbol] = actual
                intervals += 1
        independent_periods[c["id"]] = periods
        if (index + 1) % 24 == 0:
            print(f"全会計の独立監査: {index + 1}/{configured_total}条件", flush=True)
    expected_choices = []
    for reference in range(3):
        group = "基準跨ぎ返済なし" if cli.extension else "主案"
        pool = [c for c in configurations if c["group"] == group and c["reference"] == reference]
        qualified = [c for c in pool if all(independent_periods[c["id"]]["前16"][s]["trades"] >= 20 and independent_periods[c["id"]]["前16"][s]["active_sessions"] >= 8 for s in ("TOPIX", "NK225"))]
        eligible = bool(qualified)
        qualifying_count = len(qualified)
        if not qualified:
            qualified = [c for c in pool if all(independent_periods[c["id"]]["前16"][s]["trades"] > 0 for s in ("TOPIX", "NK225"))]
        def score(c: dict) -> tuple:
            """機能: 両商品の損失割合を前半だけから比較する。

            引数: c(dict)。返り値: 比較値(tuple)。
            """
            a = [independent_periods[c["id"]]["前16"][s] for s in ("TOPIX", "NK225")]
            return (max(row["money_loss_share"] for row in a), sum(row["money_loss_share"] for row in a), -sum(row["trades"] for row in a), c["id"])
        selected = min(qualified, key=score)
        follow = independent_periods[selected["id"]]["後13"]
        passed = all(follow[s]["net"] > 0 and follow[s]["payoff"] is not None and follow[s]["payoff"] > 1 and follow[s]["without_best_session"] > 0 for s in ("TOPIX", "NK225"))
        expected_choices.append(dict(id=selected["id"], reference=reference, eligible=eligible, score=list(score(selected)), 後13有望条件=passed, 最低件数充足条件数=qualifying_count))
    selected = study.load(area / ("選定.json" if cli.extension else "前半選定.json"))
    for independent, actual in zip(expected_choices, selected["代表"]):
        for field, value in actual.items():
            assert independent[field] == value, ("前半選定", field, independent, actual)
    output_name = "純トレール追加240と再利用48の独立監査.json" if cli.extension else "全480条件の会計と前半選定の独立監査.json"
    save(HERE / output_name, dict(合格=True, 固定SHA256=fixed["SHA256"],
        条件数=configured_total, 追加条件数=240 if cli.extension else 0, 再利用条件数=len(reused_ids),
        口座会計数=total_accounts, 決済明細数=trades, 注文数=orders, 全行清算曲線指紋照合数=total_accounts,
        期間商品会計数=intervals, 会計項目比較数=fields, 前半選定=expected_choices,
        選定代表の期間={c["id"]: independent_periods[c["id"]] for c in expected_choices},
        主指標="全決済の料金後損失/(全決済の料金後利益+全決済の料金後損失)。商品別集計、買玉・売玉の全損失を含む。",
        予定撤収limit超過返済数=late_exits, 予定撤収limit超過口座数=late_accounts,
        予定撤収limit超過最大秒=max_late, 判断から次有効原本行約定の最大秒=max_fill_delay,
        時刻境界="limitは安全撤収の目安（Day15:35/Night05:50）。limit-60秒で判断を開始し、実約定は次有効気配のためlimit超過はあり得る。全返済は保存監視end=limit+300（Day15:40/Night05:55）未満。観測欠損時に架空価格で返済していない。",
        検査=["全注文次有効行", "新規返済floor料金", "全玉全明細会計", "清算予定料金込み全行曲線", "場内全返済", "片方向10枚/20枚上限", "方向条件", "返済理由", "料金後連敗と再開待ち", "全期間金額合計", "前半のみで代表選定"],
        原本取得=0, API取得=0, 実注文=0, 既知データの前後分割=True))
    print(json.dumps(dict(合格=True, 口座会計数=total_accounts, 選定=[c["id"] for c in expected_choices]), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
