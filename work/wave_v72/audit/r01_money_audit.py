"""R01の注文台帳から全玉決済と料金を独立に再計算し、金額で評価する。"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

import loss_rank


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ("TOPIX", "NK225")
CONFIG_PATH = ROOT / "work/wave_v70/results/T1L1_R01.json"
LEDGER_PATH = ROOT / "work/wave_v70/ledgers/T1L1_R01.pkl"


def read(path: Path) -> object:
    """機能: 凍結済みJSON又は台帳を読取専用で取得する。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == ".pkl" else json.loads(path.read_text(encoding="utf8"))


def save_new(path: Path, value: object) -> None:
    """機能: 新しい監査だけを保存し、過去の監査を上書きしない。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    if path.exists():
        assert path.read_text(encoding="utf8") == text, ("過去監査の上書き禁止", path)
        return
    path.write_text(text, encoding="utf8")


def fee(symbol: str, quantity: int) -> int:
    """機能: 約定一注文の片道手数料を整数で切り捨てる。

    引数: symbol(str)、quantity(int)。返り値: 円額(int)。
    """
    return quantity * 418 // 10 if symbol == "TOPIX" else quantity * 11


def account(key: tuple, ledger: dict) -> dict:
    """機能: 注文だけから役割別FIFO、部分料金、全玉決済を再構成する。

    引数: key(tuple[str,str])、ledger(dict)。返り値: 金額・枚数・勝敗・最大損失(dict)。
    原本やAPIは参照せず、判断後約定という保存注文の順序だけを再確認する。
    """
    session, symbol = key
    cap, point = (10, 1000) if symbol == "TOPIX" else (20, 10)
    fifo = defaultdict(deque)
    held, maximum = {1: 0, -1: 0}, {1: 0, -1: 0}
    group_gross, group_fees = defaultdict(float), defaultdict(int)
    total_fees = prior_row = entries = exits = 0
    orders = ledger["orders"]
    details = []
    for order in orders:
        assert len(order) == 9
        fill_i, decision_i, cid, side, quantity, price, reason, new, role = order
        fill_i, decision_i, cid, side, quantity, reason, new, role = map(int, (fill_i, decision_i, cid, side, quantity, reason, new, role))
        assert 0 <= decision_i < fill_i and fill_i >= prior_row
        assert side in (-1, 1) and new in (0, 1) and role == 0 and quantity > 0
        assert np.isfinite(price) and price > 0
        charge = fee(symbol, quantity)
        total_fees += charge
        group_fees[cid] += charge
        if new:
            assert quantity == cap
            fifo[(cid, side, role)].append([fill_i, quantity, float(price), charge, quantity, 0])
            held[side] += quantity
            entries += 1
        else:
            assert held[-side] >= quantity
            held[-side] -= quantity
            remaining, exit_cumulative = quantity, 0
            exits += 1
            while remaining:
                lots = fifo[(cid, -side, role)]
                assert lots
                lot = lots[0]
                take = min(remaining, lot[1])
                gross = take * (-side) * (float(price) - lot[2]) * point
                entry_fee = lot[3] * (lot[5] + take) // lot[4] - lot[3] * lot[5] // lot[4]
                exit_fee = charge * (exit_cumulative + take) // quantity - charge * exit_cumulative // quantity
                net = gross - entry_fee - exit_fee
                details.append([cid, lot[0], fill_i, -side, take, lot[2], float(price), entry_fee, exit_fee, gross, net, role])
                group_gross[cid] += gross
                lot[1] -= take
                lot[5] += take
                remaining -= take
                exit_cumulative += take
                if not lot[1]:
                    lots.popleft()
        assert held[1] <= cap and held[-1] <= cap
        maximum[1] = max(maximum[1], held[1])
        maximum[-1] = max(maximum[-1], held[-1])
        prior_row = fill_i
    assert held[1] == held[-1] == 0 and all(not q for q in fifo.values())
    expected = np.asarray(details, dtype=float).reshape((-1, 12))
    np.testing.assert_allclose(expected, ledger["trades"], rtol=0, atol=1.e-6)
    assert sum(t[7] + t[8] for t in details) == total_fees
    group_net = [group_gross[cid] - group_fees[cid] for cid in sorted(group_fees)]
    nets = [t[10] for t in details]
    assert abs(sum(group_net) - sum(nets)) < 1.e-6
    result = dict(session=session, symbol=symbol,
        profit=sum(v for v in nets if v > 0), loss=-sum(v for v in nets if v < 0), net=sum(nets),
        gross=sum(t[9] for t in details), fees=total_fees,
        wins=sum(v > 0 for v in nets), losses=sum(v < 0 for v in nets), flats=sum(v == 0 for v in nets), trades=len(nets),
        winning_lots=sum(int(t[4]) for t in details if t[10] > 0), losing_lots=sum(int(t[4]) for t in details if t[10] < 0),
        flat_lots=sum(int(t[4]) for t in details if t[10] == 0),
        campaign_profit=sum(v for v in group_net if v > 0), campaign_loss=-sum(v for v in group_net if v < 0),
        campaigns=len(group_net), campaign_wins=sum(v > 0 for v in group_net), campaign_losses=sum(v < 0 for v in group_net),
        campaign_flats=sum(v == 0 for v in group_net), max_campaign_loss=max((max(0, -v) for v in group_net), default=0),
        core_net=sum(nets), cover_net=0, max_long=maximum[1], max_short=maximum[-1],
        entry_orders=entries, exit_orders=exits, entry_lots=sum(int(o[4]) for o in orders if o[7] == 1),
        exit_lots=sum(int(o[4]) for o in orders if o[7] == 0))
    # ----------------------------------------
    # R01は単独満額の新規と全返済だけで、一組と一明細の利益・損失が一致する。
    assert result["campaigns"] == result["trades"] == entries == exits
    assert result["profit"] == result["campaign_profit"] and result["loss"] == result["campaign_loss"]
    assert result["entry_lots"] == result["exit_lots"] == cap * entries
    return result


def indicators(rows: list[dict], symbol: str) -> dict:
    """機能: 同じ銘柄だけの総利益・絶対損失・損失割合・PFを集計する。

    引数: rows(list[dict])、symbol(str)。返り値: 商品別の金額評価(dict)。
    """
    records = [r for r in rows if r["symbol"] == symbol]
    names = ("profit", "loss", "net", "gross", "fees", "wins", "losses", "flats", "trades",
             "winning_lots", "losing_lots", "flat_lots", "campaigns", "campaign_wins", "campaign_losses",
             "campaign_profit", "campaign_loss", "entry_orders", "exit_orders", "entry_lots", "exit_lots")
    out = {name: sum(r[name] for r in records) for name in names}
    profit, loss = out["profit"], out["loss"]
    out.update(symbol=symbol, sessions=len(records), active_sessions=sum(r["campaigns"] > 0 for r in records),
        金額損失割合=loss / (profit + loss) if profit + loss else None,
        PF=profit / loss if loss else None, 平均勝ち=profit / out["wins"] if out["wins"] else None,
        平均負け=loss / out["losses"] if out["losses"] else None,
        平均勝負比=(profit / out["wins"]) / (loss / out["losses"]) if out["wins"] and out["losses"] and loss else None,
        敗率=out["campaign_losses"] / out["campaigns"] if out["campaigns"] else None,
        最大負組=max((r["max_campaign_loss"] for r in records), default=0),
        最大一場損失=-min([0] + [r["net"] for r in records]),
        最大買=max((r["max_long"] for r in records), default=0), 最大売=max((r["max_short"] for r in records), default=0))
    assert abs(out["profit"] - out["loss"] - out["net"]) < 1.e-6
    return out


def audit_packet(packet: dict, ledger: dict) -> list[dict]:
    """機能: 保存結果の全場行を注文から独立再会計し全指標を確認する。

    引数: packet/ledger(dict)。返り値: 全場の独立会計(list[dict])。
    """
    reported = {(r["session"], r["symbol"]): r for r in packet["rows"]}
    assert set(reported) == set(ledger)
    independent = []
    for key in sorted(ledger):
        a = account(key, ledger[key])
        for field, value in a.items():
            if field in reported[key] and field not in ("session", "symbol"):
                assert abs(value - reported[key][field]) < 1.e-6, (key, field)
        independent.append(a)
    return independent


def monetary_rank() -> dict:
    """機能: 既存846条件の組損失割合でR01の位置を銘柄別に確認する。

    引数: なし。返り値: 同率、件数条件、順位と非最少の結論(dict)。
    """
    records = loss_rank.collect()
    result = {}
    for symbol in SYMBOLS:
        result[symbol] = {}
        for label, minimum, active in (("1組以上", 1, 0), ("20組以上", 20, 0), ("20組8場以上", 20, 8)):
            rows = [m for m in records if m["商品"][symbol]["組数"] >= minimum and m["商品"][symbol]["活動場数"] >= active]
            def ratio(item: dict) -> Fraction:
                """機能: 丸め前の組利益・損失から金額割合を作る。

                引数: item(dict)。返り値: 正確な比較用分数(Fraction)。
                """
                a = item["商品"][symbol]
                return Fraction(str(a["負組損失"])) / Fraction(str(a["勝組利益"] + a["負組損失"]))
            rows.sort(key=lambda m: (ratio(m), m["版"], m["ID"]))
            target = next(m for m in rows if m["版"] == 70 and m["ID"] == "T1L1_R01")
            place = next(i + 1 for i, m in enumerate(rows) if m is target)
            r = ratio(target)
            strictly_better = sum(ratio(m) < r for m in rows)
            tied = sum(ratio(m) == r for m in rows)
            best = rows[0]
            result[symbol][label] = dict(対象条件数=len(rows), R01_ID順順位=place,
                R01同率最前順位=strictly_better + 1, R01同率件数=tied, R01金額損失割合=float(r),
                金額損失割合最少ではない=strictly_better > 0,
                首位=dict(版=best["版"], ID=best["ID"], 比率=float(ratio(best)), 商品=best["商品"][symbol]))
    return dict(合格=True, 条件数=846, 指標="料金後の組損失/(組利益+組損失)。二商品は円合算しない",
        対象="同じ既知全28場、追加デイ除外", 商品別=result,
        結論="R01は敗組頻度の少ない条件だが、金額損失割合では損失最少ではない")


def main() -> None:
    """機能: 既存28場と任意の追加台帳を別証跡で検算する。

    引数: --extra-results/--extra-ledgers(str|None)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--extra-results", type=Path)
    parser.add_argument("--extra-ledgers", type=Path)
    args = parser.parse_args()
    packet, ledger = read(CONFIG_PATH), read(LEDGER_PATH)
    rows = audit_packet(packet, ledger)
    sessions = sorted({r["session"] for r in rows})
    assert len(sessions) == 28 and len(rows) == 56
    fixed = read(ROOT / "work/wave_v70/事前固定.json")
    assert sessions == sorted(fixed["全セッション"])
    totals = {s: indicators(rows, s) for s in SYMBOLS}
    for symbol in SYMBOLS:
        for field, value in totals[symbol].items():
            if field in packet["periods"]["全28"][symbol]:
                assert abs(value - packet["periods"]["全28"][symbol][field]) < 1.e-6
    proof = dict(合格=True, ID="T1L1_R01", 条件=packet["config"], セッション数=28, 口座数=56,
        全場独立会計=rows, 商品別全28=totals,
        一組定義="同cidの全玉・全新規返済料金を合算。単独満額返済のR01では一組と一決済明細が一致",
        複数商品円合算=False, 金額損失割合="絶対損失/(利益+絶対損失)", PF="利益/絶対損失",
        注文台帳_SHA256=hashlib.sha256(LEDGER_PATH.read_bytes()).hexdigest(), 結果_SHA256=hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest(),
        原本読取=False, API取得=0, 実注文=0)
    save_new(HERE / "R01既存28場の金額会計独立監査.json", proof)
    save_new(HERE / "R01金額損失割合順位の独立確認.json", monetary_rank())
    print("R01旧28場・56口座・全注文/部分料金/勝敗枚数と金額順位: 合格", flush=True)
    if args.extra_results or args.extra_ledgers:
        assert args.extra_results and args.extra_ledgers
        extra_packet, extra_ledger = read(args.extra_results), read(args.extra_ledgers)
        assert extra_packet["config"] == packet["config"]
        assert not set(extra_ledger) & set(ledger)
        extra_rows = audit_packet(extra_packet, extra_ledger)
        combined = rows + extra_rows
        extra_sessions = sorted({r["session"] for r in extra_rows})
        combined_sessions = sorted({r["session"] for r in combined})
        assert len(combined) == len(combined_sessions) * 2
        save_new(HERE / f"R01追加{len(extra_sessions)}場と全{len(combined_sessions)}場の金額会計独立監査.json",
            dict(合格=True, ID="T1L1_R01", 追加場=extra_sessions, 追加口座数=len(extra_rows),
                追加独立会計=extra_rows, 追加商品別={s: indicators(extra_rows, s) for s in SYMBOLS},
                全場商品別={s: indicators(combined, s) for s in SYMBOLS}, 全場独立会計=combined,
                複数商品円合算=False, 既存条件一致=True,
                追加結果_SHA256=hashlib.sha256(args.extra_results.read_bytes()).hexdigest(),
                追加台帳_SHA256=hashlib.sha256(args.extra_ledgers.read_bytes()).hexdigest()))
        print(f"R01追加{len(extra_sessions)}場・全{len(combined_sessions)}場の独立会計: 合格", flush=True)


if __name__ == "__main__":
    main()
