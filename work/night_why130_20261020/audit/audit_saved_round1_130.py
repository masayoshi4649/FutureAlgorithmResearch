"""第一巡の保存注文を独立した現金・保有量台帳で再集計する。金融核は呼ばない。"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def read(path):
    """
    機能: 保存済みJSONを読み込む。
    引数: path(Path)は対象。
    返り値: dict又はlistは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: 入力の内容指紋を計算する。
    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference(path):
    """
    機能: 内容指紋付きの相対位置を返す。
    引数: path(Path)は対象。
    返り値: dictは位置と指紋。
    """
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(path))


def inspect(ready, quotes, orders, trades, curve, row, config):
    """
    機能: 保存注文だけから全行の資金・数量・費用・親損益を独立に復元する。
    引数: ready/quotes/row/config(dict)、orders/trades/curve(ndarray)は入力と保存出力。
    返り値: dictは親台帳・確認件数・最大差。新たな売買判断は行わない。
    """
    top = ready["symbol"] == "TOPIX"
    cap, multiplier, fee = (5, 1000., 418) if top else (10, 10., 110)
    ts = ready["time_s"]
    bid, ask = quotes["bid"], quotes["ask"]
    good = quotes["quote_valid"] & np.isfinite(bid) & np.isfinite(ask) & (bid > 0.) & (ask > bid)
    valid_rows = np.flatnonzero(good)
    n = len(ts)
    assert curve.shape == (n, 4) and orders.shape[1] == 8 and trades.shape[1] == 15
    assert np.all(np.diff(ts) >= 0.)
    assert np.all(np.isfinite(orders)) and np.all(np.isfinite(trades))
    assert np.all(np.diff(orders[:, 0]) >= 0.)
    deltas = np.zeros((n, 4))
    parents = {}
    inventory, parent_id, exits, checks = 0, -1, 0, 4
    for order in orders:
        for col in (0, 1, 2, 3, 4, 6, 7):
            assert order[col] == int(order[col])
        fill, decision, cid, direction, qty = map(int, order[:5])
        price, reason, is_new = order[5], int(order[6]), int(order[7])
        assert 0 <= decision < fill < n and direction in (-1, 1) and 0 < qty <= cap
        assert is_new in (0, 1)
        assert good[fill] and valid_rows[np.searchsorted(valid_rows, decision, side="right")] == fill
        assert price == (ask[fill] if direction > 0 else bid[fill])
        assert ts[fill] >= ts[decision]
        cost = qty*fee//10
        # ----------------------------------------
        # 売買代金そのものを現金へ出し入れし、別列に保有原価を積み上げる。
        deltas[fill, 0] -= direction*qty*price*multiplier + cost
        deltas[fill, 1] += direction*qty
        deltas[fill, 2] += cost
        if is_new:
            assert inventory == 0 and cid not in parents and qty == cap and reason == 1
            parent_id = cid
            parent = dict(parent=cid, direction=direction, initial=qty, entry=price,
                          entry_row=fill, entry_fee=cost, allocated_entry_fee=0,
                          remaining=qty, gross=0., fees=cost, closed=0, parts=[],
                          partials=0, width=None)
            parents[cid] = parent
            basis_price = price
        else:
            assert cid == parent_id and inventory*direction < 0 and qty <= abs(inventory)
            parent = parents[cid]
            assert qty <= parent["remaining"]
            basis_price = parent["entry"]
            gross = parent["direction"]*(price-basis_price)*qty*multiplier
            allocated = (parent["entry_fee"]-parent["allocated_entry_fee"] if qty == parent["remaining"]
                         else parent["entry_fee"]*qty//parent["initial"])
            parent["allocated_entry_fee"] += allocated
            expected = [parent["entry_row"], fill, parent["direction"], qty,
                        basis_price, price, gross, allocated+cost, gross-allocated-cost]
            np.testing.assert_array_equal(trades[exits, :9], expected)
            moves = parent["direction"]*((bid if parent["direction"] > 0 else ask)[parent["entry_row"]:fill+1]
                                        -basis_price)
            moves = moves[good[parent["entry_row"]:fill+1]]
            np.testing.assert_array_equal(trades[exits, 9:11], [max(0., moves.max()), min(0., moves.min())])
            assert trades[exits, 11] > 0. and trades[exits, 12] == reason and trades[exits, 14] == cid
            if parent["width"] is None:
                parent["width"] = float(trades[exits, 11])
            else:
                assert parent["width"] == trades[exits, 11]
            if reason == 76:
                assert config["exit_style"] in (2, 3) and qty == cap//2 and parent["partials"] == 0
                parent["partials"] += 1
            else:
                assert qty == parent["remaining"]
            parent["gross"] += gross
            parent["fees"] += cost
            parent["closed"] += qty
            parent["remaining"] -= qty
            parent["parts"].append(dict(fill_row=fill, decision_row=decision, quantity=qty,
                                        gross=float(gross), fees=allocated+cost,
                                        net=float(gross-allocated-cost), reason=reason))
            if parent["remaining"] == 0:
                assert parent["allocated_entry_fee"] == parent["entry_fee"]
            exits += 1
        deltas[fill, 3] += direction*qty*basis_price*multiplier
        inventory += direction*qty
        assert abs(inventory) <= cap
        checks += 12
    assert inventory == 0 and exits == len(trades)
    ledger = np.cumsum(deltas, axis=0)
    last_good = np.maximum.accumulate(np.where(good, np.arange(n), -1))
    indices = np.maximum(last_good, 0)
    mark = np.where(ledger[:, 1] > 0., bid[indices], ask[indices])
    holding_value = np.where(ledger[:, 1] != 0., ledger[:, 1]*mark*multiplier, 0.)
    independent = np.column_stack((ledger[:, 0]+holding_value, ledger[:, 1],
                                   ledger[:, 2], ledger[:, 0]+ledger[:, 3]))
    np.testing.assert_allclose(curve, independent, rtol=0., atol=1e-7)
    maximum_difference = float(np.max(np.abs(curve-independent)))
    assert curve[-1, 1] == 0.
    for parent in parents.values():
        assert parent["remaining"] == 0 and parent["closed"] == parent["initial"]
        parent["net"] = parent["gross"]-parent["fees"]
        assert sum(p["net"] for p in parent["parts"]) == parent["net"]
        assert trades[trades[:, 14] == parent["parent"], 8].sum() == parent["net"]
        parent["partial_profit_but_parent_loss"] = bool(parent["net"] < 0 and
            any(p["net"] > 0 and p["reason"] == 76 for p in parent["parts"]))
    nets = np.array([p["net"] for p in parents.values()])
    expected = dict(profit=float(nets[nets > 0].sum()), loss=float(-nets[nets < 0].sum()),
        net=float(nets.sum()), gross=sum(p["gross"] for p in parents.values()),
        fees=sum(p["fees"] for p in parents.values()), entries=len(parents),
        quantity=sum(p["initial"] for p in parents.values()), parent_wins=int((nets > 0).sum()),
        parent_losses=int((nets < 0).sum()), max_quantity=int(np.abs(ledger[:, 1]).max()),
        partial_exits=sum(p["partials"] for p in parents.values()))
    for field, value in expected.items():
        assert row[field] == value, (row["method"], row["session"], row["symbol"], field, row[field], value)
    assert expected["net"] == curve[-1, 0]
    assert expected["fees"] == curve[-1, 2]
    assert trades[:, 6].sum() == expected["gross"] and trades[:, 7].sum() == expected["fees"]
    checks += len(expected)+7+len(parents)*4
    return dict(method=row["method"], session=row["session"], symbol=row["symbol"],
                source_rows=n, checks=checks, orders=len(orders), exit_parts=len(trades),
                max_curve_difference=maximum_difference, **expected, parents=list(parents.values()))


def statistics(rows):
    """
    機能: 保存注文から復元した場損益を、表示関数に依存せず集計する。
    引数: rows(list[dict])は同じ手法・商品の場会計。
    返り値: dictは全場・上位3場除外などの指標。
    """
    values = [r["net"] for r in rows]
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    return dict(sessions=len(rows), profit=sum(r["profit"] for r in rows),
        loss=sum(r["loss"] for r in rows), fees=sum(r["fees"] for r in rows), net=sum(values),
        black=len(wins), red=len(losses), flat=sum(r["entries"] == 0 for r in rows),
        active=sum(r["entries"] > 0 for r in rows), median=float(np.median(values)),
        worst=min(values), mean_black=sum(wins)/len(wins) if wins else 0.,
        mean_red=-sum(losses)/len(losses) if losses else 0.,
        without_top3=sum(values)-sum(sorted(wins, reverse=True)[:3]),
        entries=sum(r["entries"] for r in rows),
        breakeven=sum(r["entries"] > 0 and r["net"] == 0 for r in rows))


def main():
    """
    機能: 第一巡252商品場を原packetと照合し、独立会計の証拠を保存する。
    引数: なし。
    返り値: None。取引核・特徴生成・API・実注文は実行しない。
    """
    folder = WORK/"round1_final"
    measurements = read(folder/"全条件の会計.json")
    fixed = read(folder/"固定計画.json")
    comparison_path = WORK/"第一巡比較.json"
    comparison = read(comparison_path)
    sources = fixed["sources"]
    for path, digest in sources.items():
        assert sha(ROOT/path) == digest, path
    for ref in fixed["artificial"]+fixed["input_references"]:
        assert sha(ROOT/ref["path"]) == ref["sha256"], ref
    input_ref = measurements["input_manifest"]
    assert sha(ROOT/input_ref["path"]) == input_ref["sha256"]
    manifest = read(ROOT/input_ref["path"])
    packets = {r["session"]: r for r in manifest["packets"] if r["session"].endswith("_Night")}
    caches = {(r["session"], r["symbol"]): r for r in measurements["cache"]}
    rows = {(r["method"], r["session"], r["symbol"]): r for r in measurements["rows"]}
    displayed = {(r["method"], r["session"], r["symbol"]): r for r in comparison["rows"]}
    configs = {c["id"]: c for c in measurements["configs"]}
    assert len(configs) == 6 and len(packets) == 21 and len(caches) == 42 and len(rows) == 252
    audited = []
    for scene, packet_ref in packets.items():
        assert sha(ROOT/packet_ref["path"]) == packet_ref["sha256"]
        packet = pickle.loads((ROOT/packet_ref["path"]).read_bytes())
        for symbol in ("TOPIX", "NK225"):
            ref = caches[scene, symbol]
            assert sha(ROOT/ref["path"]) == ref["sha256"]
            with np.load(ROOT/ref["path"], allow_pickle=False) as saved:
                for method, config in configs.items():
                    key = method, scene, symbol
                    row = rows[key]
                    for field, value in row.items():
                        assert displayed[key][field] == value, (key, field)
                    result = inspect(packet["inputs"][scene, symbol], packet["quotes"][scene, symbol],
                        saved[method+"__orders"], saved[method+"__trades"], saved[method+"__curve"], row, config)
                    result["regime"] = displayed[key]["regime"]
                    result["half_within_kind"] = displayed[key]["half_within_kind"]
                    audited.append(result)
        print(scene, len(audited), "商品場監査済み", flush=True)
    summary_checks = 0
    for stat in comparison["summary"]:
        if stat["method"] not in configs:
            continue
        selected = [r for r in audited if r["method"] == stat["method"] and r["symbol"] == stat["symbol"]]
        targets = [(selected, stat)]
        targets += [([r for r in selected if r["regime"] == key], value) for key, value in stat["regimes"].items()]
        targets += [([r for r in selected if r["half_within_kind"] == key], value) for key, value in stat["halves"].items()]
        for group, shown in targets:
            for field, value in statistics(group).items():
                assert np.isclose(shown[field], value, rtol=0., atol=1e-9), (stat["method"], stat["symbol"], field)
                summary_checks += 1
    for path, digest in sources.items():
        assert sha(ROOT/path) == digest, path
    hidden_losses = [dict(method=r["method"], session=r["session"], symbol=r["symbol"], parent=p)
                     for r in audited for p in r["parents"] if p["partial_profit_but_parent_loss"]]
    target = HERE/f"第一巡252商品場の独立注文会計_{time.time_ns()}.json"
    output = dict(passed=True, financial_replays=0, API=0, accounts=len(audited),
        orders=sum(r["orders"] for r in audited), parents=sum(r["entries"] for r in audited),
        closed_parts=sum(r["exit_parts"] for r in audited), rows=sum(r["source_rows"] for r in audited),
        checks=sum(r["checks"] for r in audited)+summary_checks, summary_checks=summary_checks,
        max_curve_difference=max(r["max_curve_difference"] for r in audited),
        partial_profit_parent_losses=len(hidden_losses), partial_profit_parent_loss_examples=hidden_losses,
        source=reference(Path(__file__)), fixed=reference(folder/"固定計画.json"),
        measurement=reference(folder/"全条件の会計.json"), comparison=reference(comparison_path),
        packet_manifest=input_ref, numeric_sources=sources, measurement_files=measurements["cache"],
        scope="保存注文の数量・次正常原行気配・独立売買代金台帳・全行時価・親配賦・全場表示集計。売買判断の再生ではない。",
        rows_audit=audited)
    assert not target.exists()
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf8")
    print(target, "合格", output["checks"], "親", output["parents"], "部分利益後親赤字", len(hidden_losses), flush=True)


if __name__ == "__main__":
    main()
