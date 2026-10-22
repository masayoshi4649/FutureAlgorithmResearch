"""部分返済の待機で救えた額・失った額を旧親の同一入口へ対応させる。"""

from datetime import datetime
import json
from pathlib import Path
import pickle
import time
from zoneinfo import ZoneInfo

import numpy as np
from audit_saved_round1_130 import read, reference, sha, statistics
from audit_saved_round3_130 import quoted_prices, strict_change

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PRIOR = ROOT/"work/visual_pdca129_20261020"


def clock(value):
    """
    機能: 原行の時刻を日本時間表記にする。
    引数: value(float)はUnix秒。
    返り値: strはISO形式。
    """
    return datetime.fromtimestamp(float(value), ZoneInfo("Asia/Tokyo")).isoformat()


def account_parent(orders, trades, parent_id, ready):
    """
    機能: 保存注文から一親の初回・部分・最終返済と全費用後収支を取り出す。
    引数: orders/trades(ndarray)、parent_id(int)、ready(dict)は保存会計と原行時刻。
    返り値: dictは親会計。取引核は呼ばない。
    """
    rows = orders[orders[:,2] == parent_id]
    new = rows[rows[:,7] == 1]
    exits = rows[rows[:,7] == 0]
    assert len(new) == 1 and len(exits) > 0
    opening = new[0]
    entry_row, side, qty = int(opening[0]), int(opening[3]), int(opening[4])
    top = ready["symbol"] == "TOPIX"
    multiplier, rate = (1000.,418) if top else (10.,110)
    assert exits[:,4].sum() == qty
    fees = sum(int(row[4])*rate//10 for row in rows)
    gross = sum(side*(row[5]-opening[5])*row[4]*multiplier for row in exits)
    parent_trades = trades[trades[:,0] == entry_row]
    assert np.isclose(parent_trades[:,8].sum(), gross-fees)
    partial = []
    all_exits = []
    for row in exits:
        event = dict(fill_row=int(row[0]), decision_row=int(row[1]), quantity=int(row[4]),
            price=float(row[5]), reason=int(row[6]), fill_time=clock(ready["time_s"][int(row[0])]),
            decision_time=clock(ready["time_s"][int(row[1])]))
        all_exits.append(event)
        if row[6] == 76:
            partial.append(event)
    assert len(partial) <= 1
    return dict(parent=parent_id, entry_row=entry_row, direction=side, quantity=qty,
        entry_price=float(opening[5]), entry_time=clock(ready["time_s"][entry_row]),
        width=float(parent_trades[0,11]), gross=float(gross), fees=int(fees), net=float(gross-fees),
        partial=partial[0] if partial else None, final_exit=all_exits[-1], exits=all_exits)


def snapshot(packet, scene, symbol, kind, decision, side):
    """
    機能: 旧又は新の部分返済判断時点の二市場方向を独立に照会する。
    引数: packet(dict)、scene/symbol/kind(str)、decision/side(int)は資料と方向。
    返り値: dictは当時の既知状態と短期変化。
    """
    ready = packet["inputs"][scene,symbol]
    peer_symbol = "NK225" if symbol == "TOPIX" else "TOPIX"
    peer = packet["inputs"][scene,peer_symbol]
    price = quoted_prices(packet,scene,symbol,kind)
    peer_price = quoted_prices(packet,scene,peer_symbol,kind)
    t = ready["time_s"][decision]
    index = int(np.searchsorted(peer["time_s"],t,side="left")-1)
    own = strict_change(ready,price,decision)
    other = strict_change(peer,peer_price,index) if index >= 0 else None
    known = index >= 0 and t-peer["time_s"][index] <= 15.
    known = known and np.isfinite(price[decision]) and np.isfinite(peer_price[index])
    known = known and np.isfinite(ready["atr"][decision]) and ready["atr"][decision] > 0.
    known = known and np.isfinite(peer["atr"][index]) and peer["atr"][index] > 0.
    both = bool(known and own["known"] and other is not None and other["known"] and
                side*own["change"] < 0. and side*other["change"] < 0.)
    return dict(market_known=bool(known), both_opposite=both, own=own, peer=other)


def main():
    """
    機能: 全145親を二つの元手法へ対応し、表示集計と待機による増減を保存する。
    引数: なし。
    返り値: None。金融再生せず旧注文・判定原行だけを照合する。
    """
    audit_path = HERE/"第三巡84商品場の独立会計と両市場部分判断_1792496635905406000.json"
    audit = read(audit_path)
    assert audit["passed"] and audit["accounts"] == 84
    comparison_path = WORK/"第三巡比較.json"
    comparison = read(comparison_path)
    rows = audit["rows_audit"]
    displayed = {(r["method"],r["session"],r["symbol"]):r for r in comparison["rows"]}
    display_checks = 0
    numeric = ("profit","loss","net","gross","fees","entries","quantity","parent_wins","parent_losses",
               "max_quantity","partial_exits")
    for row in rows:
        shown = displayed[row["method"],row["session"],row["symbol"]]
        for field in numeric:
            assert row[field] == shown[field]
            display_checks += 1
        row["regime"],row["half_within_kind"] = shown["regime"],shown["half_within_kind"]
    for summary in comparison["summary"]:
        if summary["method"] not in ("W09","W10"):
            continue
        selected = [r for r in rows if r["method"] == summary["method"] and r["symbol"] == summary["symbol"]]
        targets = [(selected,summary)]
        targets += [([r for r in selected if r["regime"] == label],s) for label,s in summary["regimes"].items()]
        targets += [([r for r in selected if r["half_within_kind"] == label],s) for label,s in summary["halves"].items()]
        for group, shown in targets:
            for field,value in statistics(group).items():
                assert np.isclose(shown[field],value,rtol=0.,atol=1e-9)
                display_checks += 1
    datasets = {
        "new": WORK/"round3/全条件の会計.json",
        "partial": WORK/"round1_final/全条件の会計.json",
        "NV01": PRIOR/"round1/全条件の会計.json",
        "NV25": PRIOR/"round7/全条件の会計.json",
    }
    stores = {name:read(path) for name,path in datasets.items()}
    indices = {name:{(r["session"],r["symbol"]):r for r in data["cache"]} for name,data in stores.items()}
    new_configs = {c["id"]:c for c in stores["new"]["configs"]}
    manifest_ref = stores["new"]["input_manifest"]
    assert sha(ROOT/manifest_ref["path"]) == manifest_ref["sha256"]
    packet_refs = {r["session"]:r for r in read(ROOT/manifest_ref["path"])["packets"]
                   if r["session"].endswith("_Night")}
    correspondence = []
    for scene, packet_ref in packet_refs.items():
        assert sha(ROOT/packet_ref["path"]) == packet_ref["sha256"]
        packet = pickle.loads((ROOT/packet_ref["path"]).read_bytes())
        for symbol in ("TOPIX","NK225"):
            arrays = {}
            for name,index in indices.items():
                ref = index[scene,symbol]
                assert sha(ROOT/ref["path"]) == ref["sha256"]
                with np.load(ROOT/ref["path"],allow_pickle=False) as saved:
                    arrays[name] = dict(saved)
            ready = packet["inputs"][scene,symbol]
            for method, prior_partial, base in (("W09","W02","NV01"),("W10","W05","NV25")):
                configs = new_configs[method]
                by_entry = {}
                for store,label in (("new",method),("partial",prior_partial),(base,base)):
                    orders = arrays[store][label+"__orders"]
                    trades = arrays[store][label+"__trades"]
                    result = {}
                    for opening in orders[orders[:,7] == 1]:
                        parent = account_parent(orders,trades,int(opening[2]),ready)
                        identity = parent["entry_row"],parent["direction"],parent["quantity"],parent["entry_price"]
                        assert identity not in result
                        result[identity] = parent
                    by_entry[label] = result
                assert set(by_entry[method]) == set(by_entry[prior_partial]) == set(by_entry[base])
                for identity,new in by_entry[method].items():
                    old, original = by_entry[prior_partial][identity], by_entry[base][identity]
                    same_final = new["final_exit"]["fill_row"] == old["final_exit"]["fill_row"] == original["final_exit"]["fill_row"]
                    same_final = same_final and new["final_exit"]["price"] == old["final_exit"]["price"] == original["final_exit"]["price"]
                    assert same_final
                    assert (new["partial"] is None) == (old["partial"] is None)
                    rec = dict(method=method, previous_partial=prior_partial, base=base,
                        session=scene,symbol=symbol,new=new,previous=old,original=original,
                        delta_waiting=float(new["net"]-old["net"]),
                        delta_original=float(new["net"]-original["net"]),final_same=True,
                        decision_changed=False,fill_changed=False)
                    if new["partial"]:
                        npart,opart = new["partial"],old["partial"]
                        assert npart["quantity"] == opart["quantity"]
                        rec["decision_changed"] = npart["decision_row"] != opart["decision_row"]
                        rec["fill_changed"] = npart["fill_row"] != opart["fill_row"]
                        rec["waiting_seconds"] = float(ready["time_s"][npart["decision_row"]]-ready["time_s"][opart["decision_row"]])
                        rec["previous_partial_market"] = snapshot(packet,scene,symbol,configs["price_source"],
                                                                  opart["decision_row"],new["direction"])
                        rec["new_partial_market"] = snapshot(packet,scene,symbol,configs["price_source"],
                                                             npart["decision_row"],new["direction"])
                        assert rec["new_partial_market"]["both_opposite"]
                        multiplier = 1000. if symbol == "TOPIX" else 10.
                        gap = new["direction"]*(npart["price"]-opart["price"])*npart["quantity"]*multiplier
                        assert rec["delta_waiting"] == gap+old["fees"]-new["fees"]
                        baseline_gap = new["direction"]*(npart["price"]-original["final_exit"]["price"])*npart["quantity"]*multiplier
                        assert rec["delta_original"] == baseline_gap+original["fees"]-new["fees"]
                    correspondence.append(rec)
    assert len(correspondence) == 145
    summaries = []
    for method in ("W09","W10"):
        for symbol in ("TOPIX","NK225"):
            selected = [r for r in correspondence if r["method"] == method and r["symbol"] == symbol]
            p = [r for r in selected if r["new"]["partial"]]
            summaries.append(dict(method=method,symbol=symbol,parents=len(selected),partials=len(p),
                old_partial_already_confirmed=sum(r["previous_partial_market"]["both_opposite"] for r in p),
                decision_changed=sum(r["decision_changed"] for r in p),
                fill_changed=sum(r["fill_changed"] for r in p),
                improved=sum(r["delta_waiting"] > 0 for r in selected),
                worsened=sum(r["delta_waiting"] < 0 for r in selected),
                unchanged=sum(r["delta_waiting"] == 0 for r in selected),
                delta_waiting=sum(r["delta_waiting"] for r in selected),
                delta_original=sum(r["delta_original"] for r in selected),
                new_net=sum(r["new"]["net"] for r in selected),
                previous_net=sum(r["previous"]["net"] for r in selected),
                original_net=sum(r["original"]["net"] for r in selected),
                maximum_wait_seconds=max((r["waiting_seconds"] for r in p),default=0.)))
    examples = dict(best=max(correspondence,key=lambda r:r["delta_waiting"]),
                    worst=min(correspondence,key=lambda r:r["delta_waiting"]),
                    october16=[r for r in correspondence if r["session"] == "2026-10-16_Night"
                               and r["symbol"] == "TOPIX" and r["new"]["parent"] == 1])
    output = dict(passed=True,financial_replays=0,API=0,display_checks=display_checks,
                  parents=145,entry_matches=145,final_exit_matches=145,partial_count_same=97,
                  source=reference(Path(__file__)),source_helpers=[
                      reference(HERE/"audit_saved_round1_130.py"),reference(HERE/"audit_saved_round3_130.py")],
                  accounting=reference(audit_path),comparison=reference(comparison_path),
                  measurements={k:reference(v) for k,v in datasets.items()},summary=summaries,
                  examples=examples,parents_correspondence=correspondence,
                  note="同じ入口と最終返済の保存経路を対応した増減。部分売却の後続判断は実運転保存結果を用い、新金融は実行しない。")
    target = HERE/f"第三巡の全親対応と部分待機の増減_{time.time_ns()}.json"
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    print(target,flush=True)
    print(json.dumps(summaries,ensure_ascii=False,indent=2),flush=True)
    print(json.dumps(examples,ensure_ascii=False,indent=2),flush=True)


if __name__ == "__main__":
    main()
