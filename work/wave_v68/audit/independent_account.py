"""損失低減比較の台帳を、エンジンを呼ばずに注文・FIFO・整数料金から検算する。"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from hashlib import sha256
import gzip
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
POINT = {"TOPIX": 1000, "NK225": 10}
INITIAL = {"TOPIX": 5, "NK225": 10}
CAP = {"TOPIX": 10, "NK225": 20}


def close(left: float, right: float, label: str) -> None:
    """機能: 料金配分の小数誤差だけを許容して独立値を照合する。

    引数: left/right(float)、label(str)。返り値: なし(None)。
    """
    assert abs(left - right) < 1.0e-5, (label, left, right)


def fee(symbol: str, quantity: int) -> int:
    """機能: 注文合計の税込料金を整数計算で求める。

    引数: symbol(str)、quantity(int)。返り値: 切捨て済み料金(int)。
    """
    return 418 * quantity // 10 if symbol == "TOPIX" else 11 * quantity


def account(ledger: dict, row: dict) -> dict:
    """機能: 元建値をFIFOで保持して全実約定・料金・組損益を独立再計算する。

    引数: ledger/row(dict)。返り値: 独立会計と件数(dict)。
    """
    symbol = ledger["symbol"]
    point = POINT[symbol]
    cfg = ledger["config"]
    assert int(cfg["initial_qty"]) == INITIAL[symbol]
    assert int(cfg["audit_cap"]) == CAP[symbol]
    orders = ledger["orders"]
    trades = ledger["trades"]
    assert len(orders) == len(ledger["fees"])
    queue = defaultdict(deque)
    entry_info = {}
    exit_info = {}
    group_gross = defaultdict(float)
    group_fee = defaultdict(int)
    maximum = {1: 0, -1: 0}
    held = {1: 0, -1: 0}
    gross = 0.0
    total_fee = 0
    last_row = -1
    entries = exits = 0
    for order, recorded_fee in zip(orders, ledger["fees"]):
        r, source, campaign, side, quantity, price, reason, new = order
        r, source, campaign, side, quantity, reason, new = map(int, (r, source, campaign, side, quantity, reason, new))
        assert side in (-1, 1) and quantity > 0 and 0 <= source < r
        assert r >= last_row
        last_row = r
        charge = fee(symbol, quantity)
        assert charge == recorded_fee
        group_fee[campaign] += charge
        total_fee += charge
        if new:
            assert quantity == INITIAL[symbol], ("初回以外の追加／復元は禁止", order)
            assert not held[1] and not held[-1], ("新規時の既存玉", order)
            entries += 1
            key = (campaign, r)
            assert key not in entry_info
            entry_info[key] = (quantity, charge, price, side)
            queue[(campaign, side)].append([r, quantity, price, charge / quantity])
            held[side] += quantity
            maximum[side] = max(maximum[side], held[side])
        else:
            exits += 1
            assert held[-side] >= quantity
            key = (campaign, r)
            assert key not in exit_info, ("同組同時刻の複数注文は再対応が必要", order)
            exit_info[key] = (quantity, charge, price, reason)
            held[-side] -= quantity
            remain = quantity
            while remain:
                assert queue[(campaign, -side)]
                lot = queue[(campaign, -side)][0]
                take = min(remain, lot[1])
                gain = take * (-side) * (price - lot[2]) * point
                gross += gain
                group_gross[campaign] += gain
                lot[1] -= take
                remain -= take
                if lot[1] == 0:
                    queue[(campaign, -side)].popleft()
        assert held[1] <= CAP[symbol] and held[-1] <= CAP[symbol]
    assert not held[1] and not held[-1]
    assert all(not q for q in queue.values())
    assert maximum[1] == row["max_long"] and maximum[-1] == row["max_short"]
    close(gross, row["gross"], "料金前損益")
    assert total_fee == row["fees"]
    close(gross - total_fee, row["net"], "料金後収支")

    # ----------------------------------------
    # 取引脚へ元新規と該当返済注文の料金を数量比例で配分する。
    exit_quantities = defaultdict(int)
    entry_quantities = defaultdict(int)
    nets = []
    quantities = []
    group_net = defaultdict(float)
    for t in trades:
        cid, er, xr, qty, direction = t["組"], t["新規行"], t["返済行"], t["枚数"], t["方向"]
        eq, ef, ep, ed = entry_info[cid, er]
        xq, xf, xp, reason = exit_info[cid, xr]
        assert direction == ed and reason == t["理由"]
        assert ep == t["建値"] and xp == t["返済値"]
        assert t["新規原本行"] < t["返済原本行"]
        assert t["新規時刻"] <= t["返済時刻"]
        entry_quantities[cid, er] += qty
        exit_quantities[cid, xr] += qty
        gain = qty * direction * (xp - ep) * point
        charge = qty * (ef / eq + xf / xq)
        net = gain - charge
        close(gain, t["利益損失前"], "脚料金前損益")
        close(charge, t["手数料"], "脚料金配分")
        close(net, t["収支"], "脚料金後収支")
        group_net[cid] += net
        nets.append(net)
        quantities.append(qty)
    assert all(q == entry_info[k][0] for k, q in entry_quantities.items())
    assert set(entry_quantities) == set(entry_info)
    assert all(q == exit_info[k][0] for k, q in exit_quantities.items())
    assert set(exit_quantities) == set(exit_info)
    close(sum(nets), row["net"], "全脚合計")
    assert sum(quantities) == entries * INITIAL[symbol]

    # ----------------------------------------
    # 部分脚の勝敗と全数量返済済み組の勝敗を別々に照合する。
    checks = {
        "profit": sum(x for x in nets if x > 0),
        "loss": -sum(x for x in nets if x < 0),
        "wins": sum(x > 0 for x in nets),
        "losses": sum(x < 0 for x in nets),
        "flats": sum(x == 0 for x in nets),
        "winning_lots": sum(q for q, x in zip(quantities, nets) if x > 0),
        "losing_lots": sum(q for q, x in zip(quantities, nets) if x < 0),
        "flat_lots": sum(q for q, x in zip(quantities, nets) if x == 0),
        "campaigns": entries,
        "campaign_wins": sum(x > 0 for x in group_net.values()),
        "campaign_losses": sum(x < 0 for x in group_net.values()),
        "campaign_profit": sum(x for x in group_net.values() if x > 0),
        "campaign_loss": -sum(x for x in group_net.values() if x < 0),
    }
    for name, value in checks.items():
        close(value, row[name], name)
    if "max_campaign_loss" in row:
        close(max((-x for x in group_net.values() if x < 0), default=0.0),
              row["max_campaign_loss"], "最大実組損失")
        close(checks["campaign_loss"] / max(1, checks["campaign_losses"]),
              row["average_campaign_loss"], "負け組の平均損失")
        close(checks["loss"] / max(1, checks["losing_lots"]),
              row["average_losing_lot"], "損失1枚平均")
    sum_r = 0.0
    assert len(ledger["cycles"]) == entries
    for cycle in ledger["cycles"]:
        cid = int(cycle[0])
        close(group_gross[cid] / point, cycle[3], "実組料金前損益")
        close(INITIAL[symbol] * cycle[5], cycle[4], "固定1ATRの分母")
        close(group_gross[cid] - group_fee[cid], group_net[cid], "組料金一致")
        sum_r += group_net[cid] / (cycle[4] * point)
    close(sum_r, row["sum_r"], "R合計")
    return dict(session=ledger["session"], symbol=symbol, 新規注文=entries, 返済注文=exits,
                決済脚=len(trades), 返済枚数=sum(quantities), 料金前=gross,
                手数料=total_fee, 収支=gross - total_fee, 最大買い=maximum[1], 最大売り=maximum[-1])


def main() -> None:
    """機能: 指定価格・観測価格の保存済み全条件を独立会計し監査結果を保存する。

    引数: --model(str)、--files(list[str])。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("specified", "observed", "both"), default="both")
    parser.add_argument("--files", nargs="*")
    args = parser.parse_args()
    paths = [Path(p).resolve() for p in args.files] if args.files else sorted(
        p for model in (("specified", "observed") if args.model == "both" else (args.model,))
        for p in (WORK / model).glob("*.json.gz")
    )
    assert paths, "検査する保存台帳がありません"
    records = []
    for path in paths:
        packet = json.loads(gzip.decompress(path.read_bytes()))
        rows = {(r["session"], r["symbol"]): r for r in packet["rows"]}
        assert len(rows) == len(packet["rows"])
        assert len(packet["ledgers"]) == len(rows)
        results = [account(l, rows[l["session"], l["symbol"]]) for l in packet["ledgers"]]
        session_names = sorted({r["session"] for r in results})
        segments = {"前16": session_names[:16], "後12": session_names[16:], "全28": session_names}
        for label, period in packet.get("periods", {}).items():
            for symbol, value in period.items():
                if label in segments:
                    selected = [r for r in results if r["symbol"] == symbol and r["session"] in segments[label]]
                    close(sum(r["収支"] for r in selected), value["net"], "期間合計収支")
                    assert sum(r["手数料"] for r in selected) == value["fees"]
                    for name in ("gross", "profit", "loss", "wins", "losses", "flats", "winning_lots",
                                 "losing_lots", "flat_lots", "campaigns", "campaign_wins", "campaign_losses",
                                 "campaign_profit", "campaign_loss", "sum_r"):
                        subset = [r for r in rows.values() if r["symbol"] == symbol and r["session"] in segments[label]]
                        close(sum(r[name] for r in subset), value[name], "期間合計" + name)
        location = str(path.relative_to(WORK)) if path.is_relative_to(WORK) else str(path)
        records.append(dict(ファイル=location, SHA256=sha256(path.read_bytes()).hexdigest(),
                            全合格=True, 口座=len(results), 結果=results))
        print(path.parent.name, path.stem, "独立会計合格", len(results), flush=True)
    target = HERE / ("台帳独立会計_" + args.model + ".json")
    target.write_text(json.dumps(dict(全合格=True, 保存条件数=len(records),
        総口座数=sum(r["口座"] for r in records), 記録=records,
        実装SHA256=sha256(Path(__file__).read_bytes()).hexdigest()), ensure_ascii=False,
        allow_nan=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
