"""第三巡の保存会計と、各部分返済判断時点の二市場資格を独立照合する。"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import pickle
import time
from zoneinfo import ZoneInfo

import numpy as np
from audit_saved_round1_130 import inspect, read, reference, sha, statistics

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def quoted_prices(packet, scene, symbol, kind):
    """
    機能: 正常気配中値又は保存現在値を、原行を変えず独立に取り出す。
    引数: packet(dict)、scene/symbol/kind(str)は保存素材と価格区分。
    返り値: ndarrayは各原行の価格。欠測は補完しない。
    """
    if kind == "last":
        return packet["inputs"][scene, symbol]["last"]
    assert kind == "mid"
    q = packet["quotes"][scene, symbol]
    valid = q["quote_valid"] & np.isfinite(q["bid"]) & np.isfinite(q["ask"])
    valid &= (q["bid"] > 0.) & (q["ask"] > q["bid"])
    result = np.full(len(q["bid"]), np.nan)
    result[valid] = (q["bid"][valid]+q["ask"][valid])/2.
    return result


def strict_change(ready, price, index):
    """
    機能: 指定原行の30秒前より厳密に過去の原行との差を計算する。
    引数: ready(dict)、price(ndarray)、index(int)は自己又は相手の資料。
    返り値: dictは差・窓始端・既知。後続同時計原行は参照しない。
    """
    times = ready["time_s"]
    anchor = int(np.searchsorted(times, times[index]-30., side="left")-1)
    known = anchor >= 0
    known = known and times[index]-30.-times[anchor] <= 30.
    known = known and np.isfinite(price[index]) and np.isfinite(price[anchor])
    known = known and np.isfinite(ready["atr"][index]) and ready["atr"][index] > 0.
    result = dict(known=bool(known), source_row=index, anchor_row=anchor,
                  source_time=float(times[index]),
                  anchor_time=float(times[anchor]) if anchor >= 0 else None, change=None)
    if known:
        assert anchor < index and times[anchor] < times[index]-30.
        result["change"] = float((price[index]-price[anchor])/ready["atr"][index])
    return result


def inspect_partial(packet, scene, symbol, orders, trades, config):
    """
    機能: 各保存半返済の判断原行で、値幅と両市場30秒の逆行を確認する。
    引数: packet(dict)、scene/symbol(str)、orders/trades(ndarray)、config(dict)。
    返り値: list[dict]は判断時点の根拠。注文核の再実行や新しい売買は行わない。
    """
    assert config["exit_style"] == 4 and "activity_mode" not in config
    ready = packet["inputs"][scene, symbol]
    peer_symbol = "NK225" if symbol == "TOPIX" else "TOPIX"
    peer = packet["inputs"][scene, peer_symbol]
    price = quoted_prices(packet, scene, symbol, config["price_source"])
    peer_price = quoted_prices(packet, scene, peer_symbol, config["price_source"])
    quotes = packet["quotes"][scene, symbol]
    good = quotes["quote_valid"] & np.isfinite(quotes["bid"]) & np.isfinite(quotes["ask"])
    good &= (quotes["bid"] > 0.) & (quotes["ask"] > quotes["bid"])
    observations = []
    for order in orders[orders[:, 6] == 76]:
        fill, decision, parent = map(int, order[:3])
        enters = orders[(orders[:, 2] == parent) & (orders[:, 7] == 1)]
        assert len(enters) == 1
        opening = enters[0]
        entry_row, direction, quantity = int(opening[0]), int(opening[3]), int(opening[4])
        entry = opening[5]
        records = trades[trades[:, 14] == parent]
        assert len(records) >= 2 and np.all(records[:, 11] == records[0, 11])
        width = float(records[0, 11])
        assert entry_row <= decision < fill and good[decision]
        assert order[4] == quantity//2
        marks = quotes["bid"] if direction > 0 else quotes["ask"]
        movement = direction*(marks[decision]-entry)
        prior_moves = direction*(marks[entry_row:decision+1]-entry)
        prior_moves = prior_moves[good[entry_row:decision+1]]
        peak = max(0., float(np.max(prior_moves)))
        assert peak >= .5*width and movement <= peak-.25*width
        floor = -config["stop"]*width
        if peak >= config["trail_start"]*width:
            floor = max(floor, peak-config["trail_width"]*width)
        assert movement > floor, "先に全返済となる価格条件と競合しています"
        t = ready["time_s"][decision]
        assert t < ready["limit"]
        assert not (ready["us_open"]-config["opening_buffer"] <= t
                    < ready["us_open"]+config["opening_buffer"])
        own_change = strict_change(ready, price, decision)
        peer_row = int(np.searchsorted(peer["time_s"], t, side="left")-1)
        assert peer_row >= 0
        peer_t = peer["time_s"][peer_row]
        market_known = peer_t < t and t-peer_t <= 15.
        market_known = market_known and np.isfinite(price[decision]) and np.isfinite(peer_price[peer_row])
        market_known = market_known and np.isfinite(ready["atr"][decision]) and ready["atr"][decision] > 0.
        market_known = market_known and np.isfinite(peer["atr"][peer_row]) and peer["atr"][peer_row] > 0.
        peer_change = strict_change(peer, peer_price, peer_row)
        assert market_known and own_change["known"] and peer_change["known"]
        assert direction*own_change["change"] < 0. and direction*peer_change["change"] < 0.
        observations.append(dict(method=config["id"], session=scene, symbol=symbol, parent=parent,
            decision_row=decision, fill_row=fill, entry_row=entry_row, direction=direction,
            decision_time=datetime.fromtimestamp(float(t), ZoneInfo("Asia/Tokyo")).isoformat(),
            fill_time=datetime.fromtimestamp(float(ready["time_s"][fill]), ZoneInfo("Asia/Tokyo")).isoformat(),
            entry_price=float(entry), liquidation_price=float(marks[decision]), width=width,
            peak=float(peak), peak_R=float(peak/width), movement=float(movement),
            giveback_R=float((peak-movement)/width), normal_full_exit_floor=float(floor),
            market_known=bool(market_known), own30=own_change, peer30=peer_change,
            peer_age=float(t-peer_t), partial_quantity=int(order[4]), price_source=config["price_source"]))
    return observations


def main():
    """
    機能: 第三巡84商品場の独立会計と半返済判断の根拠を保存する。
    引数: --comparison(str任意)は完成済み表示比較JSONのファイル名。
    返り値: None。保存会計を読むだけで金融再生・API取得は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison")
    args = parser.parse_args()
    folder = WORK/"round3"
    measurement_path = folder/"全条件の会計.json"
    measurement = read(measurement_path)
    fixed = read(folder/"固定計画.json")
    for path, digest in fixed["sources"].items():
        assert sha(ROOT/path) == digest, path
    for ref in fixed["artificial"]+fixed["input_references"]:
        assert sha(ROOT/ref["path"]) == ref["sha256"]
    input_ref = measurement["input_manifest"]
    assert sha(ROOT/input_ref["path"]) == input_ref["sha256"]
    manifest = read(ROOT/input_ref["path"])
    packets = {r["session"]: r for r in manifest["packets"] if r["session"].endswith("_Night")}
    caches = {(r["session"], r["symbol"]): r for r in measurement["cache"]}
    rows = {(r["method"], r["session"], r["symbol"]): r for r in measurement["rows"]}
    configs = {c["id"]: c for c in measurement["configs"]}
    assert set(configs) == {"W09","W10"} and len(rows) == 84 and len(packets) == 21 and len(caches) == 42
    audited, partials = [], []
    for scene, packet_ref in packets.items():
        assert sha(ROOT/packet_ref["path"]) == packet_ref["sha256"]
        packet = pickle.loads((ROOT/packet_ref["path"]).read_bytes())
        for symbol in ("TOPIX","NK225"):
            ref = caches[scene, symbol]
            assert sha(ROOT/ref["path"]) == ref["sha256"]
            with np.load(ROOT/ref["path"], allow_pickle=False) as saved:
                for method, config in configs.items():
                    assert config["exit_style"] == 4
                    orders = saved[method+"__orders"]
                    trades = saved[method+"__trades"]
                    curve = saved[method+"__curve"]
                    # ----------------------------------------
                    # 会計だけは旧半返済と同じ数量・料金配賦。売買資格は下で別途独立に照合する。
                    result = inspect(packet["inputs"][scene,symbol], packet["quotes"][scene,symbol],
                                     orders, trades, curve, rows[method,scene,symbol],
                                     dict(config, exit_style=2))
                    audited.append(result)
                    partials += inspect_partial(packet, scene, symbol, orders, trades, config)
        print(scene, len(audited), "商品場・部分判断照合済み", flush=True)
    comparison_ref, summary_checks = None, 0
    if args.comparison:
        comparison_path = WORK/args.comparison
        comparison = read(comparison_path)
        comparison_ref = reference(comparison_path)
        displayed = {(r["method"],r["session"],r["symbol"]):r for r in comparison["rows"]}
        for result in audited:
            key = result["method"],result["session"],result["symbol"]
            for field, value in rows[key].items():
                assert displayed[key][field] == value
                summary_checks += 1
            result["regime"] = displayed[key]["regime"]
            result["half_within_kind"] = displayed[key]["half_within_kind"]
        for stat in comparison["summary"]:
            if stat["method"] not in configs:
                continue
            selected = [r for r in audited if r["method"] == stat["method"] and r["symbol"] == stat["symbol"]]
            targets = [(selected,stat)]
            targets += [([r for r in selected if r["regime"] == name],value) for name,value in stat["regimes"].items()]
            targets += [([r for r in selected if r["half_within_kind"] == name],value) for name,value in stat["halves"].items()]
            for group, shown in targets:
                for field,value in statistics(group).items():
                    assert np.isclose(shown[field],value,rtol=0.,atol=1e-9)
                    summary_checks += 1
    for path, digest in fixed["sources"].items():
        assert sha(ROOT/path) == digest
    assert len(partials) == sum(r["partial_exits"] for r in audited)
    hidden_losses = [dict(method=r["method"],session=r["session"],symbol=r["symbol"],parent=p)
                     for r in audited for p in r["parents"] if p["partial_profit_but_parent_loss"]]
    output = dict(passed=True, financial_replays=0, API=0, accounts=len(audited),
        orders=sum(r["orders"] for r in audited), parents=sum(r["entries"] for r in audited),
        closed_parts=sum(r["exit_parts"] for r in audited), rows=sum(r["source_rows"] for r in audited),
        accounting_checks=sum(r["checks"] for r in audited), summary_checks=summary_checks,
        partial_decisions=len(partials), max_curve_difference=max(r["max_curve_difference"] for r in audited),
        partial_profit_parent_losses=len(hidden_losses), partial_profit_parent_loss_examples=hidden_losses,
        source=reference(Path(__file__)), accounting_source=reference(HERE/"audit_saved_round1_130.py"),
        fixed=reference(folder/"固定計画.json"), measurement=reference(measurement_path),
        comparison=comparison_ref, packet_manifest=input_ref, numeric_sources=fixed["sources"],
        measurement_files=measurement["cache"], rows_audit=audited, decision_audit=partials,
        scope="保存注文会計と判断原行の先行30秒資格。売買核・金融再生・特徴全体の再生成は行わず、必要原行を独立照会。",
        caution="延べ原行数は2条件による同一素材の重複を含む。市場時計を共通受信時計の保証と解釈しない。")
    target = HERE/f"第三巡84商品場の独立会計と両市場部分判断_{time.time_ns()}.json"
    assert not target.exists()
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    print(target, "合格", len(audited), "親", output["parents"], "部分判断", len(partials), flush=True)


if __name__ == "__main__":
    main()
