"""数量試験の保存注文だけから、現金・建玉・追加寄与を独立照合する。"""

import hashlib
import json
from pathlib import Path
import pickle
from datetime import datetime, timedelta, timezone

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
JST = timezone(timedelta(hours=9))
READS = []
CHECKS = []


def read(path: Path) -> dict:
    """
    機能: 保存JSONを読み、指紋を記録する。
    引数: path(Path)は資料の位置。
    返り値: dictは保存内容。
    """
    raw = path.read_bytes()
    READS.append(dict(path=path.relative_to(ROOT).as_posix(),
                      sha256=hashlib.sha256(raw).hexdigest()))
    return json.loads(raw)


def verified(ref: dict) -> Path:
    """
    機能: 指紋付き保存資料が変更されていないか照合する。
    引数: ref(dict)はpathとsha256。
    返り値: Pathは照合した資料位置。
    """
    path = ROOT/ref["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"]
    READS.append(dict(path=ref["path"], sha256=ref["sha256"]))
    return path


def clock(value: float) -> str:
    """
    機能: 原価格時計を日本時間で表す。
    引数: value(float)はUTC秒。
    返り値: strは日付と時分秒。
    """
    return datetime.fromtimestamp(float(value), JST).strftime("%Y-%m-%d %H:%M:%S")


def check(name: str, condition: bool) -> None:
    """
    機能: 独立照合の成否を記録する。
    引数: name(str)、condition(bool)は検査名と成否。
    返り値: None。
    """
    assert condition, name
    CHECKS.append(name)


def near(name: str, actual, expected) -> float:
    """
    機能: 計算結果を円未満の丸め誤差許容で照合する。
    引数: name(str)、actual/expected(object)は数値又は配列。
    返り値: floatは最大絶対誤差。
    """
    error = float(np.max(np.abs(np.asarray(actual)-np.asarray(expected)), initial=0.))
    check(name, error <= .00001)
    return error


def account(scene: str, symbol: str, method: str, packet: dict, arrays: dict,
            saved: dict) -> tuple:
    """
    機能: 売買代金の現金勘定と親別各建玉損益から保存会計を再計算する。
    引数: scene/symbol/method(str)、packet/arrays/saved(dict)は保存資料。
    返り値: tuple[dict,list[dict]]は口座照合と親別分解。売買条件は運転しない。
    """
    ready = packet["inputs"][scene, symbol]
    quote = packet["quotes"][scene, symbol]
    times, bid, ask = ready["time_s"], quote["bid"], quote["ask"]
    good = quote["quote_valid"] & np.isfinite(bid) & np.isfinite(ask)
    good &= (bid > 0.) & (ask > bid)
    normal = np.flatnonzero(good)
    n = len(times)
    top = symbol == "TOPIX"
    rate, mult, initial, maximum = (418, 1000., 2, 5) if top else (110, 10., 4, 10)
    orders, parents, curve, events = (arrays[method+"__"+k] for k in ("orders", "parents", "curve", "events"))
    label = f"{method}/{symbol}/{scene}"
    # ----------------------------------------
    # 元核の平均建値式を使わず、売買代金を現金に出し入れして全行時価を再構成。
    cash_delta, quantity_delta, fee_delta = (np.zeros(n) for _ in range(3))
    realized_delta = np.zeros(n)
    for order in orders:
        row, decision, cid, side, qty, price, reason, new = order
        row, decision, cid, qty, side = int(row), int(decision), int(cid), int(qty), int(side)
        check(label+"/次正常行", row == normal[np.searchsorted(normal, decision, side="right")])
        near(label+"/実気配", price, ask[row] if side > 0 else bid[row])
        fee = qty*rate//10
        cash_delta[row] += -side*qty*price*mult-fee
        quantity_delta[row] += side*qty
        fee_delta[row] += fee
        realized_delta[row] -= fee
    quantity = np.cumsum(quantity_delta)
    check(label+"/数量上限", np.max(np.abs(quantity), initial=0) <= maximum and quantity[-1] == 0)
    last_good = np.maximum.accumulate(np.where(good, np.arange(n), -1))
    safe_last = np.maximum(last_good, 0)
    marks = np.where(quantity >= 0, bid[safe_last], ask[safe_last])
    marks = np.where(quantity == 0, 0., marks)
    equity = np.cumsum(cash_delta)+quantity*marks*mult
    records = []
    reconstructed_parents = []
    for parent in parents:
        cid = int(parent[0])
        own = orders[orders[:, 2] == cid]
        entries, exits = own[own[:, 7] == 1], own[own[:, 7] == 0]
        check(label+"/親の全返済", len(exits) == 1 and entries[:, 4].sum() == exits[0, 4])
        first, final = entries[0], exits[0]
        side = int(first[3])
        quantity_sum = int(entries[:, 4].sum())
        check(label+"/初期数量", first[4] == initial)
        entry_fees = np.floor(entries[:, 4]*rate/10)
        exit_fee = int(final[4])*rate//10
        legs_gross = side*(final[5]-entries[:, 5])*entries[:, 4]*mult
        gross = float(legs_gross.sum())
        all_fees = float(entry_fees.sum()+exit_fee)
        realized_delta[int(final[0])] += gross
        net = gross-all_fees
        initial_fee = initial*rate//10
        initial_net = float(legs_gross[0]-2*initial_fee)
        addition_net = net-initial_net
        expected = np.array([cid, first[0], final[0], side, initial, quantity_sum,
            first[5], parent[7], gross, all_fees, net, quantity_sum-initial,
            len(entries)-1, final[6], 0., np.dot(entries[:, 4], entries[:, 5])/quantity_sum])
        near(label+"/親会計全列", parent, expected)
        reconstructed_parents.append(expected)
        add_records = []
        cumulative_qty = initial
        for entry in entries[1:]:
            match = events[(events[:, 0] == entry[1]) & (events[:, 1] == 3) & (events[:, 2] == cid)]
            check(label+"/追加判断対応", len(match) == 1)
            event = match[0]
            decision, actual = int(entry[1]), int(entry[0])
            previous_entries = entries[entries[:, 0] <= decision]
            prior_qty = int(previous_entries[:, 4].sum())
            prior_cost = float(np.dot(previous_entries[:, 4], previous_entries[:, 5]))
            prior_fees = int(np.floor(previous_entries[:, 4]*rate/10).sum())
            quantity_add = int(entry[4])
            future_fees = quantity_add*rate//10+(prior_qty+quantity_add)*rate//10
            budget = side*((prior_qty+quantity_add)*event[5]-prior_cost-quantity_add*event[4])*mult-prior_fees-future_fees
            near(label+"/予算再計算", [event[6], event[7], event[8], event[9], event[10]],
                 [prior_qty, quantity_add, prior_fees, future_fees, budget])
            check(label+"/予算非負", budget >= -1e-8)
            incremental_exit_fee = (cumulative_qty+quantity_add)*rate//10-cumulative_qty*rate//10
            leg_net = side*(final[5]-entry[5])*quantity_add*mult-quantity_add*rate//10-incremental_exit_fee
            cumulative_qty += quantity_add
            exit_decision = int(final[1])
            exit_quote_at_decision = bid[exit_decision] if side > 0 else ask[exit_decision]
            add_records.append(dict(
                decision=clock(times[decision]), fill=clock(times[actual]),
                decision_row=decision, fill_row=actual, qty=quantity_add,
                budget_entry=float(event[4]), actual_entry=float(entry[5]),
                entry_adverse_gap=float(side*(entry[5]-event[4])),
                budget_floor=float(event[3]), budget_exit=float(event[5]),
                actual_exit=float(final[5]), exit_adverse_gap=float(side*(event[5]-final[5])),
                exit_decision_mark=float(exit_quote_at_decision),
                exit_decision_to_fill_adverse=float(side*(exit_quote_at_decision-final[5])),
                budget_net=float(event[10]), unit_points=float(side*(final[5]-entry[5])),
                leg_gross=float(side*(final[5]-entry[5])*quantity_add*mult),
                leg_net=float(leg_net), floor_R=float(event[12]/parent[7]),
                entry_budget_price_delta_R=float(side*(event[4]-first[5])/parent[7]),
                delay_seconds=float(times[actual]-times[decision])))
        near(label+"/追加部分会計", addition_net, sum(a["leg_net"] for a in add_records))
        budget_bridge = None
        if add_records:
            last = add_records[-1]
            fill_gap_cash = -side*(last["actual_entry"]-last["budget_entry"])*last["qty"]*mult
            exit_gap_cash = side*(float(final[5])-last["budget_exit"])*quantity_sum*mult
            near(label+"/最後の予算から実収支", net, last["budget_net"]+fill_gap_cash+exit_gap_cash)
            budget_bridge = dict(last_budget=last["budget_net"], added_fill_change=fill_gap_cash,
                                all_exit_change=exit_gap_cash, actual_net=net)
        records.append(dict(method=method, symbol=symbol, session=scene, shadow_id=cid,
            side="買い" if side > 0 else "売り", entry=clock(times[int(first[0])]),
            entry_price=float(first[5]), exit=clock(times[int(final[0])]), exit_price=float(final[5]),
            exit_decision=clock(times[int(final[1])]), exit_reason=int(final[6]),
            initial_quantity=initial, final_quantity=quantity_sum, initial_R=float(parent[7]),
            gross=gross, fees=all_fees, net=net, initial_net=initial_net, addition_net=addition_net,
            additions=add_records, budget_to_actual=budget_bridge))
    expected_curve = np.column_stack((equity, quantity, np.cumsum(fee_delta), np.cumsum(realized_delta)))
    max_error = near(label+"/全行現金時価", curve, expected_curve)
    net_values = np.array([p["net"] for p in records])
    expected_summary = dict(profit=float(net_values[net_values > 0].sum()),
        loss=float(-net_values[net_values < 0].sum()), net=float(net_values.sum()),
        gross=sum(p["gross"] for p in records), fees=sum(p["fees"] for p in records),
        entries=len(records), parent_wins=int((net_values > 0).sum()),
        parent_losses=int((net_values < 0).sum()),
        quantity=int(orders[orders[:, 7] == 1, 4].sum()), entry_orders=int((orders[:, 7] == 1).sum()),
        max_quantity=int(np.max(np.abs(quantity), initial=0)),
        additions=sum(len(p["additions"]) for p in records))
    for key, value in expected_summary.items():
        near(label+"/"+key, saved[key], value)
    return dict(method=method, symbol=symbol, session=scene, max_curve_error=max_error,
                **expected_summary), records


def main() -> None:
    """
    機能: 全168口座の独立保存会計と追加による黒字喪失を分類する。
    引数: なし。
    返り値: None。新しい金融判断は生成せずJSONへ保存する。
    """
    result = read(TASK/"round5/全条件の会計.json")
    manifest = read(verified(result["input_manifest"]))
    compare = read(TASK/"round5/全場比較.json")
    original_rows = {(r["method"], r["symbol"], r["session"]): r for r in compare["rows"]}
    cache = {(r["session"], r["symbol"]): r for r in result["cache"]}
    saved_rows = {(r["method"], r["symbol"], r["session"]): r for r in result["rows"]}
    audits, records = [], []
    for reference in manifest["packets"]:
        scene = reference["session"]
        if not scene.endswith("_Night"):
            continue
        packet = pickle.loads(verified(reference).read_bytes())
        for symbol in ("TOPIX", "NK225"):
            with np.load(verified(cache[scene, symbol]), allow_pickle=False) as data:
                arrays = {key: data[key] for key in data.files}
            for method in ("NV18", "NV19", "NV20", "NV21"):
                audit, parents = account(scene, symbol, method, packet, arrays,
                                         saved_rows[method, symbol, scene])
                audits.append(audit)
                records.extend(parents)
        print(scene, "保存会計照合", len(audits), flush=True)
    # ----------------------------------------
    # 同じ初期建玉と追加分だけを対照とし、元の全枚数基準とも場単位で比較。
    by_parent = {(p["method"], p["symbol"], p["session"], p["shadow_id"]): p for p in records}
    transitions = []
    differences = []
    for method, control, original in (("NV19", "NV18", "N36"), ("NV21", "NV20", "NV02")):
        for row in audits:
            if row["method"] != method:
                continue
            scene, symbol = row["session"], row["symbol"]
            base = saved_rows[control, symbol, scene]
            full = original_rows[original, symbol, scene]
            own = [p for p in records if p["method"] == method and p["symbol"] == symbol and p["session"] == scene]
            for parent in own:
                old = by_parent[control, symbol, scene, parent["shadow_id"]]
                near("初期建玉は減量対照と同一", parent["initial_net"], old["net"])
                check("入口出口時刻と価格不変", all(parent[k] == old[k] for k in ("entry", "entry_price", "exit", "exit_price")))
            near("場差額は追加分だけ", row["net"]-base["net"], sum(p["addition_net"] for p in own))
            diff = dict(method=method, control=control, original=original, symbol=symbol, session=scene,
                        control_net=base["net"], full_quantity_net=full["net"], actual_net=row["net"],
                        added_net=row["net"]-base["net"])
            differences.append(diff)
            if (base["net"] > 0 or full["net"] > 0) and row["net"] < 0:
                transitions.append(dict(**diff, parents=own))
    aggregates = []
    for method in ("NV18", "NV19", "NV20", "NV21"):
        for symbol in ("TOPIX", "NK225"):
            rows = [r for r in audits if r["method"] == method and r["symbol"] == symbol]
            own = [p for p in records if p["method"] == method and p["symbol"] == symbol]
            added = [p for p in own if p["additions"]]
            legs = [a for p in added for a in p["additions"]]
            aggregates.append(dict(method=method, symbol=symbol, sessions=len(rows),
                wins=sum(r["net"] > 0 for r in rows), losses=sum(r["net"] < 0 for r in rows),
                zero=sum(r["net"] == 0 for r in rows), net=sum(r["net"] for r in rows),
                gross=sum(r["gross"] for r in rows), fees=sum(r["fees"] for r in rows),
                profit=sum(r["profit"] for r in rows), loss=sum(r["loss"] for r in rows),
                max_session_loss=min(r["net"] for r in rows), parents=len(own),
                parents_added=len(added), added_orders=len(legs),
                additional_net=sum(p["addition_net"] for p in added),
                positive_added_parents=sum(p["addition_net"] > 0 for p in added),
                negative_added_parents=sum(p["addition_net"] < 0 for p in added),
                added_parent_net_negative=sum(p["net"] < 0 for p in added),
                entry_worse_than_budget=sum(a["entry_adverse_gap"] > 0 for a in legs),
                exit_worse_than_budget=sum(a["exit_adverse_gap"] > 0 for a in legs)))
    check("全168口座", len(audits) == 168)
    source = Path(__file__)
    output = dict(passed=True, checks=len(CHECKS), accounting_method="売買代金現金＋符号付き現物評価、親別各建玉粗損益と注文別費用",
        financial_replays=0, API=0, account_count=len(audits), aggregates=aggregates,
        audits=audits, positive_to_negative=transitions, differences=differences,
        parents=records, inputs=READS,
        source=dict(path=source.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    path = HERE/"数量変更の独立会計と追加単価診断.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(passed=True, checks=len(CHECKS), aggregates=aggregates,
                         transitions=[{k:v for k,v in p.items() if k!="parents"} for p in transitions]),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
