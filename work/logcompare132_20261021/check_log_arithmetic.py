"""ユーザー提示の旧二商品版ログを価格・数量・手数料から検算する。金融判断は再生しない。"""

from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "work/update132_20261021/audit/独立注文会計と45場合計.json"
LOG = {
    "TOPIX": [
        {"side": 1, "entry_time": "10:56:28", "entry": "4068.75", "quantity": 5, "closes": [("11:03:00", "4064", 5, -23750)]},
        {"side": -1, "entry_time": "11:14:47", "entry": "4058", "quantity": 5, "closes": [("11:19:18", "4062.5", 5, -22500)]},
        {"side": 1, "entry_time": "12:00:25", "entry": "4070.75", "quantity": 5, "closes": [("12:21:19", "4067.25", 5, -17500)]},
        {"side": -1, "entry_time": "12:34:36", "entry": "4064.5", "quantity": 5, "closes": [("12:47:37", "4061", 2, 7000), ("13:17:40", "4056", 3, 25500)]},
    ],
    "NK225": [
        {"side": -1, "entry_time": "10:19:27", "entry": "64995", "quantity": 10, "closes": [("10:30:25", "65120", 10, -12500)]},
        {"side": 1, "entry_time": "10:50:32", "entry": "65255", "quantity": 10, "closes": [("11:02:36", "65155", 10, -10000)]},
        {"side": 1, "entry_time": "12:03:18", "entry": "65160", "quantity": 10, "closes": [("12:16:45", "65080", 10, -8000)]},
        {"side": -1, "entry_time": "12:37:14", "entry": "64980", "quantity": 10, "closes": [("13:00:00", "64840", 5, 7000), ("13:17:45", "64760", 5, 11000)]},
    ],
}


def fee(quantity, unit):
    """
    機能: 注文ごとの税込手数料を1円未満切捨てで計算する。
    引数: quantity(int) は枚数、unit(Decimal) は片道1枚料金。
    返り値: int は注文料金。
    """
    return int((quantity * unit).to_integral_value(rounding=ROUND_FLOOR))


def calculate(symbol, rows):
    """
    機能: 提示価格から各返済損益と完結親会計を再計算する。
    引数: symbol(str) は参照市場、rows(list[dict]) は提示された全約定親。
    返り値: dict は各約定検算、手数料前後の利益・損失・収支。
    """
    multiplier, unit = (1000, Decimal("41.8")) if symbol == "TOPIX" else (10, Decimal(11))
    parents, close_gross = [], []
    for row in rows:
        entry_fee = fee(row["quantity"], unit)
        closes = []
        for clock, price, quantity, logged in row["closes"]:
            movement = row["side"] * (Decimal(price)-Decimal(row["entry"]))
            pnl = int(movement * quantity * multiplier)
            assert pnl == logged, (symbol, clock, pnl, logged)
            close_gross.append(pnl)
            closes.append({"time": clock, "price": price, "quantity": quantity,
                           "directional_points": str(movement), "gross": pnl, "fee": fee(quantity, unit)})
        assert sum(x["quantity"] for x in closes) == row["quantity"]
        gross = sum(x["gross"] for x in closes)
        fees = entry_fee + sum(x["fee"] for x in closes)
        parents.append({"side": row["side"], "entry_time": row["entry_time"], "entry_price": row["entry"],
                        "quantity": row["quantity"], "entry_fee": entry_fee, "closes": closes,
                        "gross": gross, "fees": fees, "net": gross-fees})
    gross_nets, net_nets = [p["gross"] for p in parents], [p["net"] for p in parents]
    before = {"profit": sum(x for x in gross_nets if x > 0), "loss": -sum(x for x in gross_nets if x < 0), "net": sum(gross_nets)}
    after = {"profit": sum(x for x in net_nets if x > 0), "loss": -sum(x for x in net_nets if x < 0), "net": sum(net_nets)}
    assert before["profit"] == sum(x for x in close_gross if x > 0)
    assert before["loss"] == -sum(x for x in close_gross if x < 0)
    assert before["net"]-sum(p["fees"] for p in parents) == after["net"]
    return {"multiplier": multiplier, "one_way_fee": str(unit), "entries": len(parents),
            "entry_quantity": sum(p["quantity"] for p in parents), "closing_orders": len(close_gross),
            "gross_summary": before, "fee_total": sum(p["fees"] for p in parents),
            "fee_adjusted_parent_summary": after, "parents": parents,
            "qualification": "提示された全約定行だけを検算。手数料後利益損失は新規費用を含む完結親単位。"}


def main():
    """
    機能: 提示ログの算術と、00132全場研究会計との差を保存する。
    引数: なし。
    返り値: None。注文判断・データ入力・戦略の再生は行わない。
    """
    checked = {symbol: calculate(symbol, rows) for symbol, rows in LOG.items()}
    research = json.loads(RESEARCH.read_text(encoding="utf-8"))
    comparisons = {}
    for row in research["new_rows"]:
        if row["session"] != "2026-10-21_Day":
            continue
        symbol = row["symbol"]
        log = checked[symbol]
        same_count = log["entries"]
        common = row["parents"][:same_count]
        additional = row["parents"][same_count:]
        per_parent = [p["gross"]-q["gross"] for p, q in zip(log["parents"], common)]
        difference = log["fee_adjusted_parent_summary"]["net"]-row["net"]
        missing_net = -sum(p["net"] for p in additional)
        assert difference == sum(per_parent) + missing_net
        comparisons[symbol] = {"research_entries": row["entries"], "log_entries": same_count,
            "research_gross": row["gross"], "research_fees": row["fees"], "research_net": row["net"],
            "log_minus_research_gross": log["gross_summary"]["net"]-row["gross"],
            "log_minus_research_net": difference,
            "first_four_parent_gross_differences": per_parent,
            "research_only_later_parents_gross": sum(p["gross"] for p in additional),
            "research_only_later_parents_fees": sum(p["fees"] for p in additional),
            "research_only_later_parents_net": sum(p["net"] for p in additional),
            "qualification": "親の順序対応による損益差の算術分解。価格源や受信順の原因特定は別途照合が必要。"}
    result = {"passed": True, "source": "ユーザーが提示した2026-10-21_Day旧二商品版dryrunログの全約定行",
        "research_source": {"path": RESEARCH.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(RESEARCH.read_bytes()).hexdigest()},
        "symbols": checked, "comparisons": comparisons, "financial_replays": 0, "API": 0, "real_orders": 0}
    target = HERE / "ログ注文の算術検算.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({symbol: {"gross": data["gross_summary"], "fees": data["fee_total"], "net": data["fee_adjusted_parent_summary"]}
                      for symbol, data in checked.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
