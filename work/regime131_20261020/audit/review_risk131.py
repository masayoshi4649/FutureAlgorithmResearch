"""第四巡の数量配分を、赤字場の深さと失う黒字を同時に見て第三巡と対照する。"""

import math
from pathlib import Path
import statistics
import time

import numpy as np

from review_portfolio_comparison131 import (
    WORK, ROOT, HERE, CHECKS, read, reference, check, stats, equal_stats,
)
import json


def metrics(rows):
    """
    機能: 新評価に合わせて赤字場だけの平均・中央値、黒字場だけの平均を追加する。
    引数: rows(list[dict])は商品場の保存会計。
    返り値: dictは参加・黒赤・損失規模・大勝ち依存の指標。
    """
    result = stats(rows)
    losses = [-r["net"] for r in rows if r["net"] < 0]
    result.update(mean_loss=result["mean_red"],
                  median_loss=statistics.median(losses) if losses else 0.,
                  mean_win=result["mean_black"])
    return result


def main():
    """
    機能: 完了済み第四巡と対応する第三巡を照合し、数量効果だけの比較証拠を保存する。
    引数: なし。rootの完了通知後に実行する。
    返り値: None。新しい金融判断や元資料の変更は行わない。
    """
    CHECKS.clear()
    paths = [WORK / n / "全条件の会計.json" for n in ("round3", "round4")]
    prior, current = map(read, paths)
    published = read(WORK / "round4/枚数変更と失う利益の対応.json")
    pub_lookup = {(r["method"], r["symbol"], r["kind"]): r for r in published["summary"]}
    old_rows = {(r["method"], r["session"], r["symbol"]): r for r in prior["rows"]}
    old_refs = {(r["session"], r["symbol"]): r for r in prior["cache"]}
    directions_proof = read(HERE / "round3_候補比較と追加寄与の独立再集計_1792504230554973500.json")
    directions = {(r["session"], r["symbol"]): r["direction"]
                  for r in directions_proof["direction_endpoints"]}
    pairs, sources = [], [reference(p) for p in paths]
    for ref in current["cache"]:
        key = ref["session"], ref["symbol"]
        old_ref = old_refs[key]
        pn, po = ROOT / ref["path"], ROOT / old_ref["path"]
        check("新保存指紋/" + str(key), reference(pn)["sha256"] == ref["sha256"])
        check("旧保存指紋/" + str(key), reference(po)["sha256"] == old_ref["sha256"])
        with np.load(pn) as now, np.load(po) as old:
            for config in current["configs"]:
                method = config["id"]
                base = "T04" if config["schedule"] == 2 else "T05"
                a, b = now[method + "__extra_trades"], old[base + "__extra_trades"]
                ao, bo = now[method + "__extra_orders"], old[base + "__extra_orders"]
                tag = method + "/" + str(key)
                check(tag + "/全取引数", a.shape == b.shape and ao.shape == bo.shape)
                fields = [0, 1, 2, 3, 5, 6, 10, 11, 12, 13, 14, 15, 16]
                check(tag + "/入口出口経路不変", np.array_equal(a[:, fields], b[:, fields]))
                ofields = [0, 1, 2, 3, 5, 6, 7, 9, 10, 11]
                check(tag + "/発注約定行価格不変", np.array_equal(ao[:, ofields], bo[:, ofields]))
                check(tag + "/旧核注文不変", np.array_equal(
                    now[method + "__core_orders"], old[base + "__core_orders"]))
                top = key[1] == "TOPIX"
                base_quantity, tick, fee, multiplier = (5, .5, 41.8, 1000.) if top else (10, 10., 11., 10.)
                for nt, ot in zip(a, b):
                    expected = max(1, min(base_quantity,
                        math.floor(base_quantity * config["budget_ticks"] * tick / nt[10])))
                    quantity = int(nt[4])
                    check(tag + "/過去Rだけの整数配分", quantity == expected)
                    gross = ot[7] * quantity / base_quantity
                    net = gross - 2 * math.floor(quantity * fee)
                    check(tag + "/同経路での数量と全費用", abs(nt[7] - gross) < 1e-7 and abs(nt[9] - net) < 1e-7)
                    target = base_quantity * config["budget_ticks"] * tick * multiplier
                    pairs.append(dict(method=method, base=base, session=key[0], symbol=key[1],
                        kind=key[0].split("_")[1], old_quantity=int(ot[4]), quantity=quantity,
                        old_net=float(ot[9]), net=float(nt[9]), change=float(nt[9] - ot[9]),
                        initial_risk=float(nt[10] * quantity * multiplier), target_risk=target,
                        minimum_over_budget=quantity == 1 and nt[10] * multiplier > target))
    result = []
    for config in current["configs"]:
        method = config["id"]
        base = "T04" if config["schedule"] == 2 else "T05"
        for symbol in ("TOPIX", "NK225"):
            for kind in ("全体", "Day", "Night"):
                rows = sorted([r for r in current["rows"]
                    if r["method"] == method and r["symbol"] == symbol and
                    (kind == "全体" or r["kind"] == kind)], key=lambda r: r["session"])
                before = [old_rows[base, r["session"], symbol] for r in rows]
                for r, old in zip(rows, before):
                    check(method + symbol + kind + r["session"] + "/旧核会計不変",
                          r["components"]["旧核"] == old["components"]["旧核"])
                    check(method + symbol + kind + r["session"] + "/参加不変",
                          r["entries"] == old["entries"] and r["entries"] > 0)
                now_stats, old_stats = metrics(rows), metrics(before)
                pub = pub_lookup[method, symbol, kind]
                equal_stats(method + symbol + kind + "/新集計", now_stats, pub)
                equal_stats(method + symbol + kind + "/旧集計", old_stats, pub["baseline"])
                check(method + symbol + kind + "/赤字中央値", abs(now_stats["median_loss"] - pub["median_loss"]) < 1e-7)
                chosen_pairs = [p for p in pairs if p["method"] == method and p["symbol"] == symbol
                                and (kind == "全体" or p["kind"] == kind)]
                removed = -sum(p["change"] for p in chosen_pairs if p["old_net"] > 0)
                reduced = sum(p["change"] for p in chosen_pairs if p["old_net"] < 0)
                check(method + symbol + kind + "/減る利益", abs(removed - pub["removed_profit"]) < 1e-7)
                check(method + symbol + kind + "/減る損失", abs(reduced - pub["reduced_loss"]) < 1e-7)
                check(method + symbol + kind + "/数量だけの差額", abs(now_stats["net"] - old_stats["net"] - reduced + removed) < 1e-7)
                old_best = sorted([r for r in before if r["net"] > 0], key=lambda r: -r["net"])[:3]
                row_lookup = {r["session"]: r for r in rows}
                old_best_detail = [dict(session=r["session"], before=r["net"],
                                       after=row_lookup[r["session"]]["net"],
                                       delta=row_lookup[r["session"]]["net"] - r["net"]) for r in old_best]
                split = {}
                for d in ("上昇", "下落", "同値"):
                    split[d] = metrics([r for r in rows if directions[r["session"], symbol] == d])
                half = len(rows) // 2
                result.append(dict(method=method, base=base, symbol=symbol, kind=kind,
                    current=now_stats, previous=old_stats, removed_profit=removed, reduced_loss=reduced,
                    old_best3=old_best_detail,
                    old_best3_change=sum(r["delta"] for r in old_best_detail),
                    extra=metrics([r["components"]["追加"] for r in rows]),
                    extra_before=metrics([r["components"]["追加"] for r in before]),
                    newly_black=[r["session"] for r, o in zip(rows, before) if o["net"] <= 0 < r["net"]],
                    newly_red=[r["session"] for r, o in zip(rows, before) if o["net"] >= 0 > r["net"]],
                    directions=split,
                    halves={"前半": metrics(rows[:half]), "後半": metrics(rows[half:])},
                    quantity_range=[min((p["quantity"] for p in chosen_pairs), default=0),
                                    max((p["quantity"] for p in chosen_pairs), default=0)],
                    changed_quantity=sum(p["quantity"] != p["old_quantity"] for p in chosen_pairs),
                    minimum_over_budget=sum(p["minimum_over_budget"] for p in chosen_pairs)))
    sources += [reference(WORK / "round4/枚数変更と失う利益の対応.json"),
                reference(WORK / "第四巡前の評価補足.json"),
                reference(WORK / "第四巡条件.json"), reference(Path(__file__))]
    target = HERE / f"第四巡の赤字規模と失う利益の独立比較_{time.time_ns()}.json"
    target.write_text(json.dumps(dict(passed=True, financial_replays=0,
        check_count=len(CHECKS), checks=CHECKS, sources=sources, summary=result, pairs=pairs,
        limitation="全43場既知。数量調整は予測改善ではない。上位3除外は依存度確認で、大勝ちを捨てる運用ではない。"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target.relative_to(ROOT), len(CHECKS), "合格", flush=True)
    for r in result:
        if r["kind"] != "Night":
            continue
        s = r["current"]
        print(r["method"], r["symbol"], "収支", s["net"], "黒赤", s["black"], s["red"],
              "赤平均/中央", round(s["mean_loss"], 1), s["median_loss"],
              "上3", s["without_top3"], "失う利益/減る損失", r["removed_profit"], r["reduced_loss"], flush=True)


if __name__ == "__main__":
    main()
