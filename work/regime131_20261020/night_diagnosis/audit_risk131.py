"""固定リスク配分後の保存注文から、数量と全原行会計を独立に検証する。"""

import argparse
import ast
from datetime import datetime, time
from decimal import Decimal, ROUND_FLOOR
import json
import math
from pathlib import Path
import pickle
import sys
import time as clock
from zoneinfo import ZoneInfo

import numpy as np

from audit_accounts131 import equal, independent_phases, PHASES, read, reference, require

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
BASE = ROOT / "work/daynight128_20261020"


def charge(quantity, fee):
    """
    機能: 注文別に税込料金を十進数で切り捨てる。
    引数: quantity(int)、fee(float)は枚数と一枚料金。
    返り値: intは注文の円料金。
    """
    return int((Decimal(str(fee))*quantity).to_integral_value(rounding=ROUND_FLOOR))


def activation(ready, schedule):
    """
    機能: 追加の開始時計を独立に算出する。
    引数: ready(dict)、schedule(int)は場時刻と条件番号。
    返り値: floatは日本・米国・欧州予定に基づく開始時刻。
    """
    if schedule == 0:
        return ready["start"]+2700.
    day = datetime.fromisoformat(ready["session"].split("_")[0]).date()
    if ready["session"].endswith("_Day"):
        local = time(12, 30) if schedule == 1 else time(14)
        return datetime.combine(day, local, ZoneInfo("Asia/Tokyo")).timestamp()
    if schedule == 1:
        return datetime.combine(day, time(10), ZoneInfo("America/New_York")).timestamp()
    return datetime.combine(day, time(16, 30), ZoneInfo("Europe/London")).timestamp()


def rebuild(orders, trades, ready, quotes, phase, old):
    """
    機能: 価格判断を生成せず、保存注文と親の全会計を独立に再構成する。
    引数: orders/trades/phase(ndarray)、ready/quotes(dict)、old(bool)は旧親の未測定欄許容。
    返り値: dictは全原行の円曲線・長短在庫・親別損益・集計。
    """
    t, bid, ask = ready["time_s"], quotes["bid"], quotes["ask"]
    n = len(t)
    top = ready["symbol"] == "TOPIX"
    mult, fee, cap = (1000., 41.8, 10) if top else (10., 11., 20)
    good = quotes["quote_valid"] & np.isfinite(bid) & np.isfinite(ask) & (ask > bid) & (bid > 0.)
    normal = np.flatnonzero(good)
    require(orders.ndim == 2 and orders.shape[1] == 12, "注文12列")
    require(trades.ndim == 2 and trades.shape[1] == 17, "親17列")
    require(np.isfinite(orders).all(), "保存注文は有限")
    integercols = [0, 1, 2, 3, 4, 6, 7, 8, 11]
    equal(orders[:, integercols], orders[:, integercols].astype(np.int64), "注文整数項目")
    fills, sources = orders[:, 0].astype(int), orders[:, 1].astype(int)
    require(np.all((sources >= 0) & (sources < fills) & (fills < n)), "先行判断と後続約定")
    require(np.all(np.diff(fills) >= 0), "保存注文の原行順")
    require(np.isin(orders[:, 3], (-1, 1)).all(), "注文方向")
    require(np.isin(orders[:, 7], (0, 1)).all() and (orders[:, 4] > 0).all(), "新規返済旗と正整数枚数")
    ix = np.searchsorted(normal, sources, side="right")
    require(np.all(ix < len(normal)), "後続正常気配あり")
    equal(fills, normal[ix], "次正常原行での実行")
    equal(orders[:, 5], np.where(orders[:, 3] > 0, ask[fills], bid[fills]), "方向別約定気配")
    equal(orders[:, 8], np.array([charge(int(q), fee) for q in orders[:, 4]], dtype=float), "注文別費用")
    equal(orders[:, 9], t[fills], "約定時刻")
    equal(orders[:, 10], t[sources], "判断時刻")
    equal(orders[:, 11], phase[fills], "約定時区分")
    ld, sd, lb, sb, cash, closefee = [np.zeros(n) for _ in range(6)]
    parents = {}
    for order in orders:
        row, source, cid, side, qty = map(int, order[:5])
        price, reason, opening, paid = order[5], int(order[6]), bool(order[7]), order[8]
        cash[row] -= paid
        if opening:
            require(cid not in parents, "一親一新規と親集合の重複なし")
            require(t[row] < ready["limit"], "終端後に新規なし")
            parents[cid] = dict(side=side, quantity=qty, remaining=qty, entry=price, a=row,
                                b=-1, entryreason=reason, exitreason=0, gross=0., fees=paid,
                                close_value=0., close_quantity=0, closed=False)
            (ld if side > 0 else sd)[row] += qty
            (lb if side > 0 else sb)[row] += qty*price
            closefee[row] += charge(qty, fee)
        else:
            require(cid in parents, "返済親が存在")
            p = parents[cid]
            require(not p["closed"] and p["side"] == -side, "返済方向と未完結親")
            require(qty <= p["remaining"], "親在庫超過返済なし")
            oldqty = p["remaining"]
            gain = p["side"]*(price-p["entry"])*qty*mult
            cash[row] += gain
            p["remaining"] -= qty
            p["gross"] += gain
            p["fees"] += paid
            p["close_value"] += qty*price
            p["close_quantity"] += qty
            p["b"], p["exitreason"] = row, reason
            p["closed"] = p["remaining"] == 0
            (ld if p["side"] > 0 else sd)[row] -= qty
            (lb if p["side"] > 0 else sb)[row] -= qty*p["entry"]
            closefee[row] += charge(p["remaining"], fee)-charge(oldqty, fee)
    require(len(parents) == len(trades), "注文と親数")
    require(len(set(trades[:, 0])) == len(trades), "保存親IDの一意性")
    require(set(parents) == set(trades[:, 0]), "注文と保存親の集合一致")
    for trade in trades:
        cid = int(trade[0])
        p = parents[cid]
        require(p["closed"] and p["close_quantity"] == p["quantity"], "親の全返済")
        equal(trade[:10], np.array([cid, p["a"], p["b"], p["side"], p["quantity"], p["entry"],
              p["close_value"]/p["quantity"], p["gross"], p["fees"], p["gross"]-p["fees"]]), "親の部分返済と加重返済値")
        equal(trade[13], phase[p["a"]], "親の入口区分")
        equal(trade[15:17], [p["entryreason"], p["exitreason"]], "親の新規返済理由")
        if old:
            require(np.isnan(trade[10:13]).all(), "旧親のR順行逆行は未測定NaN")
            equal(trade[14], -1., "旧親の未分類手法")
        else:
            require(np.isfinite(trade[10:13]).all() and trade[10] > 0., "追加親の幅順行逆行")
            equal(trade[14], 1., "追加親の手法")
    longs, shorts, longbasis, shortbasis, realized, closecost = (
        np.cumsum(v) for v in (ld, sd, lb, sb, cash, closefee))
    require(np.all(longs >= 0) and np.all(shorts >= 0), "長短在庫の非負")
    require(max(longs.max(), shorts.max()) <= cap, "方向別保有上限")
    require(longs[-1] == 0 and shorts[-1] == 0, "終場両側ゼロ")
    markrow = np.maximum.accumulate(np.where(good, np.arange(n), -1))
    active = (longs+shorts) > 0
    require(np.all(markrow[active] >= 0), "保有中の正常気配持越し")
    unrealized = np.zeros(n)
    unrealized[active] = mult*(longs[active]*bid[markrow[active]]-longbasis[active]
                              -shorts[active]*ask[markrow[active]]+shortbasis[active])
    equity = realized+unrealized-closecost
    peak = np.maximum.accumulate(np.maximum(equity, 0.))
    dd = np.maximum.accumulate(peak-equity)
    nets = np.array([p["gross"]-p["fees"] for p in parents.values()])
    equal(equity[-1], nets.sum(), "親合計と最終清算価値")
    return dict(curve=np.column_stack((equity, longs-shorts, realized, dd, np.zeros(n))),
                long_quantity=longs, short_quantity=shorts, parents=parents,
                profit=float(nets[nets > 0].sum()), loss=float(-nets[nets < 0].sum()), net=float(nets.sum()),
                gross=float(sum(p["gross"] for p in parents.values())),
                fees=float(sum(p["fees"] for p in parents.values())), entries=len(parents),
                quantity=sum(p["quantity"] for p in parents.values()),
                parent_wins=int((nets > 0).sum()), parent_losses=int((nets < 0).sum()),
                max_quantity=int(max(longs.max(), shorts.max())), max_long=int(longs.max()),
                max_short=int(shorts.max()), max_gross_quantity=int((longs+shorts).max()),
                max_drawdown=float(dd[-1]))


def audit_one(arrays, ready, quotes, history, phase, config, summary, original):
    """
    機能: 旧核・追加・合算を別々に検算して保存集計と照合する。
    引数: arrays(dict)、ready/quotes/config/summary(dict)、history/phase/original(ndarray)。
    返り値: dictは検査件数と最大曲線誤差、実参加。
    """
    co, ct = arrays["core_orders"], arrays["core_trades"]
    eo, et, ec = arrays["extra_orders"], arrays["extra_trades"], arrays["extra_curve"]
    orders, trades, curve = arrays["orders"], arrays["trades"], arrays["curve"]
    equal(co[:, :8], original, "旧核保存注文の完全保持")
    require(np.all(co[:, 2] < 1000000), "旧核の親ID領域")
    require(np.all(eo[:, 2] >= 1000000), "追加の親ID領域")
    joined = np.concatenate((co, eo))
    joined = joined[np.argsort(joined[:, 0], kind="stable")]
    equal(orders, joined, "全注文の安定連結")
    expected_trades = np.concatenate((ct, et))
    require(trades.shape == expected_trades.shape, "連結親の形")
    require(np.array_equal(trades, expected_trades, equal_nan=True), "連結親の一致")
    core = rebuild(co, ct, ready, quotes, phase, True)
    extra = rebuild(eo, et, ready, quotes, phase, False)
    # ----------------------------------------
    # 合算側は同じ列を丸め直さず、全注文を独立台帳へ通す。
    old_indices = trades[:, 0] < 1000000
    prepared = trades.copy()
    prepared[old_indices, 10:13] = 1.
    prepared[old_indices, 14] = 1.
    total = rebuild(orders, prepared, ready, quotes, phase, False)
    for name in ("long_quantity", "short_quantity"):
        equal(arrays[name], total[name], "全行:"+name)
    maxgap = equal(curve, total["curve"], "連結注文からの全行円会計")
    equal(curve[:, :3], core["curve"][:, :3]+extra["curve"][:, :3], "単独曲線の合算")
    expected_extra = extra["curve"].copy()
    expected_extra[:, 4] = (extra["long_quantity"]+extra["short_quantity"] > 0).astype(float)
    equal(ec, expected_extra, "追加の単独曲線")
    for name in ("profit", "loss", "net", "gross", "fees", "entries", "quantity",
                 "parent_wins", "parent_losses", "max_quantity", "max_long", "max_short",
                 "max_gross_quantity", "max_drawdown"):
        equal(summary[name], total[name], "合算集計:"+name)
    for name, part in (("旧核", core), ("追加", extra)):
        for field in ("entries", "profit", "loss", "net", "gross", "fees"):
            equal(summary["components"][name][field], part[field], name+"の独立損益:"+field)
    require(len(et) <= 1, "追加は一親以下")
    equal(summary["deadline_entries"], len(et), "追加参加件数")
    active_at = activation(ready, config["schedule"])
    equal(summary["activation_time"], active_at, "開始時計")
    for opening in eo[eo[:, 7] == 1]:
        row = int(opening[1])
        t = ready["time_s"][row]
        require(active_at <= t < ready["limit"]-600., "予定以後かつ終端10分前")
        require(not np.any((co[:, 7] == 1) & (co[:, 0] <= row)), "判断時まで旧核未参加")
        require(np.isfinite(history[row]).all() and np.isfinite(ready["atr"][row]), "追加時の資料既知")
        require(ready["atr"][row] > 0., "追加時の正のATR")
        h = history[row]
        mid = (quotes["bid"][row]+quotes["ask"][row])*.5
        score = np.sign(h[7])+np.sign(h[11])+.5*(np.sign(h[6])+np.sign(h[10]))
        if config["style"] == 1:
            score = np.sign(mid-h[8])+np.sign(h[13])
            if score == 0:
                score = np.sign(h[7])+np.sign(h[11])
        if score == 0:
            score = h[7]
        if score == 0:
            score = mid-h[8]
        equal(opening[3], np.sign(score), "追加の当時方向")
        risk = max(ready["atr"][row], .5*(h[3]-h[4]), 8.*ready["tick"])
        equal(et[0, 10], risk, "追加の初期尺度")
        require(quotes["ask"][row]-quotes["bid"][row] <= .5*risk, "追加の気配幅")
        equal(opening[6], 82.+config["style"], "追加の理由")
        base_quantity = 5 if ready["symbol"] == "TOPIX" else 10
        expected_quantity = max(1, min(base_quantity, math.floor(
            base_quantity*config["budget_ticks"]*ready["tick"]/risk)))
        equal(opening[4], expected_quantity, "発注時のリスク予算による追加枚数")
    # ----------------------------------------
    # 新規時区分と値洗いの観測時区分をそれぞれ照合する。
    nets = trades[:, 9]
    delta = np.diff(np.r_[0., total["curve"][:, 0]])
    for p, name in enumerate(PHASES):
        chosen = trades[:, 13] == p
        equal(summary["phases"][name]["entries"], chosen.sum(), "入口区分件数:"+name)
        equal(summary["phases"][name]["net"], nets[chosen].sum(), "入口区分金額:"+name)
        equal(summary["phase_equity_changes"][name], delta[phase == p].sum(), "観測区分金額:"+name)
    for side, name in ((1, "買い"), (-1, "売り")):
        chosen = trades[:, 3] == side
        equal(summary["direction"][name]["entries"], chosen.sum(), "方向件数:"+name)
        equal(summary["direction"][name]["net"], nets[chosen].sum(), "方向収支:"+name)
    return dict(method=config["id"], session=ready["session"], symbol=ready["symbol"],
                orders=len(orders), parents=len(trades), source_rows=len(ready["time_s"]),
                core_parents=len(ct), extra_parents=len(et), net=total["net"],
                max_long=total["max_long"], max_short=total["max_short"],
                entered=len(trades) > 0, maximum_curve_error=maxgap)


def main():
    """
    機能: 完成済みリスク配分条件を売買核importなしで独立監査する。
    引数: --round(str)は全条件会計が完成した結果位置。
    返り値: None。時刻付き監査証拠を新規保存する。金融再生0。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", required=True)
    args = parser.parse_args()
    folder = TASK / args.round
    require(folder.resolve().is_relative_to(TASK.resolve()), "結果は今回作業内")
    completed_path = folder / "全条件の会計.json"
    require(completed_path.exists(), "実値監査は金融完了後のみ")
    completed, fixed = read(completed_path), read(folder / "固定計画.json")
    require(completed["passed"] and completed["configs"] == fixed["configs"], "完了と登録条件")
    require(completed["sources"] == fixed["sources"], "登録源一致")
    for path, digest in {**completed["sources"], **completed["saved_core_sources"]}.items():
        require(reference(ROOT / path)["sha256"] == digest, "凍結入力源:"+path)
    # ----------------------------------------
    # 旧核モジュールをimportせず、固定された旧会計の位置だけを静的に読み込む。
    tree = ast.parse((TASK / "baseline131.py").read_text(encoding="utf-8-sig"))
    mapping = next(ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "source_map"
                                                            for t in node.targets))
    accounts = {name: read(ROOT / ref["path"]) for name, ref in mapping.items()}
    summaries = {(r["session"], r["symbol"], r["method"]): r for r in completed["rows"]}
    cache = {(r["session"], r["symbol"]): r for r in completed["cache"]}
    manifest = read(BASE / "入力準備.json")
    require(len(summaries) == len(completed["rows"]), "合算集計の一意性")
    require(len(cache)*len(completed["configs"]) == len(summaries), "全条件保存件数")
    sys.path.insert(0, str(TASK))
    import features131
    forbidden = ("baseline131", "participation131", "participation_risk131", "engine131", "run_portfolio131", "run_risk131")
    require(not any(name in sys.modules for name in forbidden), "売買核と会計核をimportしない")
    successes, errors = [], []
    for ref in manifest["packets"]:
        require(reference(ROOT / ref["path"])["sha256"] == ref["sha256"], "原入力指紋")
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        inputs, _, histories, _ = features131.build(packet)
        scene = ref["session"]
        for symbol in ("TOPIX", "NK225"):
            key = scene, symbol
            ready, q = inputs[key], packet["quotes"][key]
            phase = independent_phases(ready)
            savedref = cache[key]
            require(reference(ROOT / savedref["path"])["sha256"] == savedref["sha256"], "合算保存指紋")
            originals = {}
            with np.load(ROOT / savedref["path"]) as saved:
                for config in completed["configs"]:
                    mid = config["id"]
                    row = summaries[(scene, symbol, mid)]
                    coremethod = row["core_method"]
                    if coremethod not in originals:
                        category = ("day" if scene.endswith("_Day") else
                                    "night_retest" if symbol == "NK225" else
                                    "night_base" if config["core_variant"] == 0 else "night_activity")
                        account = accounts[category]
                        oldref = next(r for r in account["cache"] if r["session"] == scene and r["symbol"] == symbol)
                        require(reference(ROOT / oldref["path"])["sha256"] == oldref["sha256"], "旧実注文指紋")
                        with np.load(ROOT / oldref["path"]) as previous:
                            originals[coremethod] = previous[coremethod+"__orders"].copy()
                    names = ("orders", "trades", "curve", "long_quantity", "short_quantity",
                             "core_orders", "core_trades", "extra_orders", "extra_trades", "extra_curve")
                    arrays = {name: saved[mid+"__"+name] for name in names}
                    try:
                        success = audit_one(arrays, ready, q, histories[key], phase, config, row, originals[coremethod])
                        successes.append(success)
                    except (AssertionError, ValueError, IndexError, KeyError) as exc:
                        errors.append(dict(method=mid, session=scene, symbol=symbol, error=str(exc)))
            print(scene, symbol, len(successes), "独立合算監査", "不一致", len(errors), flush=True)
    require(not any(name in sys.modules for name in forbidden), "終了まで旧核と新核をimportしない")
    zero = [r for r in successes if not r["entered"]]
    proof = dict(passed=not errors and len(successes) == len(summaries),
                 all_accounts_entered=not errors and not zero, financial_replays=0, core_replays=0,
                 real_orders=0, market_API=0, sources=completed["sources"],
                 checker=reference(Path(__file__).resolve()), predecessor_checker=reference(HERE / "audit_portfolio131.py"), completed=reference(completed_path),
                 accounts=len(successes), expected_accounts=len(summaries),
                 source_rows_checked=sum(r["source_rows"] for r in successes),
                 orders_checked=sum(r["orders"] for r in successes),
                 parents_checked=sum(r["parents"] for r in successes),
                 maximum_curve_error=max((r["maximum_curve_error"] for r in successes), default=0.),
                 zero_entry_accounts=zero, errors=errors, rows=successes,
                 limitations="旧核のR/MFE/MAEは未測定NaNとして照合。新旧の売買判断は再生せず、保存注文から独立会計を行った。")
    target = HERE / ("リスク配分注文の独立全原行会計_"+args.round+"_"+str(clock.time_ns())+".json")
    require(not target.exists(), "監査証拠の上書きなし")
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(target.as_posix(), "合格", proof["passed"], "全場参加", proof["all_accounts_entered"], flush=True)
    if not proof["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
