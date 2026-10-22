"""v3の保存注文と親会計から資産を独立復元する。新しい金融運転は行わない。"""

from __future__ import annotations

import argparse
import ast
from io import BytesIO
import json
import math
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
V3 = HERE.parent
BASE = V3.parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE / "audit_result119"))
import saved_accounting as audit

READS = dict(結果=0, v3cache=0, 既所有quote=0, 原市場=0, 原cache追加=0, 金融再実行=0)


# ----------------------------------------


def write(path: Path, value: dict) -> dict:
    """
    機能: 新規の独立監査資料を有限JSONとして保存する。
    引数: path(Path)、value(dict) は所有領域と内容。
    返り値: dict は保存位置と同bytes指紋。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return dict(path=path.relative_to(ROOT).as_posix(), SHA256=audit.sha(payload), bytes=len(payload))


def load_cache(path: Path, expected: str, destination: Path | None = None) -> dict:
    """
    機能: 保存cacheを一読し、同bytesとstatを確認して配列を得る。
    引数: path(Path)、expected(str)、destination(Path|None) は許可入力と保全先。
    返り値: dict[str,ndarray]。engineをimport又は再実行しない。
    """
    before = path.stat()
    payload = path.read_bytes()
    after = path.stat()
    audit.check((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "読取前後stat")
    audit.check(audit.sha(payload) == expected, "保存同bytes")
    if destination is not None:
        assert not destination.exists()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    with np.load(BytesIO(payload), allow_pickle=False) as saved:
        return {name: saved[name].copy() for name in saved.files}


def definitions() -> tuple[dict, dict]:
    """
    機能: engineを実行せず、公開されたログ列定義だけをASTから読む。
    引数: なし。
    返り値: tuple[dict,dict] は注文と親の列名index。
    """
    found = {}
    tree = ast.parse((V3 / "engine_v3.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("ORDER_COLUMNS", "PARENT_COLUMNS"):
                    found[target.id] = ast.literal_eval(node.value)
    audit.check(len(found["ORDER_COLUMNS"]) == 15 and len(found["PARENT_COLUMNS"]) == 27, "保存列15/27")
    return ({name: i for i, name in enumerate(found["ORDER_COLUMNS"])},
            {name: i for i, name in enumerate(found["PARENT_COLUMNS"])})


def account(orders: np.ndarray, parents: np.ndarray, bars: dict, quotes: dict,
            cap: int, multiplier: float, fee: float, spec: dict, O: dict, P: dict) -> dict:
    """
    機能: 保存された実約定だけから全費用・親損益・各気配時点の現金と建玉を復元する。
    引数: orders/parents(float2D)、bars/quotes(dict)、固定数量・倍率・費用・spec、列定義O/P(dict)。
    返り値: dict は復元summaryと公開時資産/方向/数量。注文の新規選択や金融運転を行わない。
    """
    nq = len(quotes["row"])
    audit.check(orders.ndim == 2 and orders.shape[1] == 15 and np.isfinite(orders).all(), "注文15列")
    audit.check(parents.ndim == 2 and parents.shape[1] == 27 and np.isfinite(parents).all(), "親27列")
    audit.check(np.all(orders[:, O["fill_raw_row"]] > orders[:, O["decision_raw_row"]]), "全注文のstrict次原row")
    audit.check(np.all(np.diff(orders[:, O["fill_raw_row"]]) > 0), "追加と返済を同rowにしない")
    audit.check(np.isin(orders[:, O["kind"]], (1, 2, 3)).all(), "注文種別")
    audit.near(orders[:, O["fee"]], np.floor(orders[:, O["quantity"]] * fee + 1e-9), "全注文の費用切捨て")
    qindex = np.searchsorted(quotes["row"], orders[:, O["fill_raw_row"]].astype(np.int64))
    audit.check(np.all(qindex < nq) and np.array_equal(quotes["row"][qindex], orders[:, O["fill_raw_row"]]), "全実約定rowは正常BBO")
    audit.near(orders[:, O["fill_time"]], quotes["time"][qindex], "全約定時計")
    audit.near(orders[:, O["price"]], np.where(orders[:, O["side"]] == 1, quotes["ask"][qindex], quotes["bid"][qindex]), "全注文の実反対BBO")
    cash_delta = np.zeros(nq)
    pos_delta = np.zeros(nq)
    basis_delta = np.zeros(nq)
    gross_total = 0.
    closed = []
    max_quantity = add_count = 0
    initial_sizes = []
    parent_ids = np.unique(orders[:, O["parent"]]).astype(int)
    audit.check(np.array_equal(parent_ids, np.arange(1, len(parent_ids) + 1)), "親ID一から欠落なし")
    audit.check(np.array_equal(parents[:, P["parent"]], np.arange(1, len(parents) + 1)), "完結親ID一から欠落なし")
    for parent_id in parent_ids:
        selected = orders[orders[:, O["parent"]] == parent_id]
        entries = selected[selected[:, O["kind"]] != 3]
        closes = selected[selected[:, O["kind"]] == 3]
        audit.check(len(entries) >= 1 and entries[0, O["kind"]] == 1 and np.all(entries[1:, O["kind"]] == 2), "初回後だけ追加")
        audit.check(len(closes) <= 1, "一括全返済のみ")
        first = entries[0]
        d, q0 = int(first[O["side"]]), int(first[O["quantity"]])
        r, origin = first[O["fixed_risk_width"]], first[O["price"]]
        audit.check(d in (-1, 1) and r > 0, "方向と固定幅")
        expected_q0 = cap if spec["allocation_mode"] == 1 else int(.2 * cap)
        audit.near(q0, expected_q0, "各配分の初回枚数")
        initial_sizes.append(q0)
        parent_budget = q0 * r * multiplier + 2 * math.floor(q0 * fee + 1e-9)
        begin = int(np.searchsorted(quotes["row"], int(first[O["fill_raw_row"]])))
        end = int(np.searchsorted(quotes["row"], int(closes[0, O["fill_raw_row"]]))) if len(closes) else nq - 1
        side_prices = quotes["bid"][begin:end + 1] if d == 1 else quotes["ask"][begin:end + 1]
        timeline_qty = np.zeros(end - begin + 1)
        timeline_value = np.zeros(end - begin + 1)
        timeline_fees = np.zeros(end - begin + 1)
        quantity, value, paid = 0, 0., 0.
        previous_level = 0
        for order in entries:
            qi = int(np.searchsorted(quotes["row"], int(order[O["fill_raw_row"]])))
            units = int(order[O["quantity"]])
            audit.check(units > 0 and order[O["quantity"]] == units, "実注文整数枚数")
            audit.check(order[O["side"]] == d and order[O["signed_quantity"]] == d * units, "新規追加の売買符号")
            audit.check(0 <= order[O["fill_time"]] - order[O["decision_time"]] <= 60., "初回追加の60価格秒期限")
            if order[O["kind"]] == 2:
                audit.check(spec["allocation_mode"] == 2, "追加はGROWのみ")
                decision = int(np.searchsorted(quotes["row"], int(order[O["decision_raw_row"]])))
                audit.check(decision < nq and quotes["row"][decision] == order[O["decision_raw_row"]], "追加判断は当時の正常BBO")
                price = quotes["bid"][decision] if d == 1 else quotes["ask"][decision]
                progress = d * (price - origin) / r
                level = 3 if progress >= 1.5 else (2 if progress >= 1. else (1 if progress >= .5 else 0))
                audit.check(level > previous_level, "原実建値からの新しい到達段階")
                expected_total = int(math.floor(cap * (.4 if level == 1 else .7 if level == 2 else 1.) + 1e-9))
                audit.near(units + quantity, expected_total, "到達済み最大累計へ一注文")
                previous_level = level
                add_count += 1
            quantity += units
            value += units * order[O["price"]]
            paid += math.floor(units * fee + 1e-9)
            audit.check(quantity <= cap, "片方向上限")
            audit.near(order[O["basket_quantity_after"]], quantity, "注文後数量")
            audit.near(order[O["wac_after"]], value / quantity, "実約定加重WAC")
            audit.near(order[O["fixed_risk_width"]], r, "初回幅を保持")
            cash_delta[qi] -= order[O["fee"]]
            pos_delta[qi] += d * units
            basis_delta[qi] += d * units * order[O["price"]]
            timeline_qty[qi - begin:] += units
            timeline_value[qi - begin:] += units * order[O["price"]]
            timeline_fees[qi - begin:] += order[O["fee"]]
            max_quantity = max(max_quantity, quantity)
        wac = timeline_value / timeline_qty
        projected_fee = np.floor(timeline_qty * fee + 1e-9)
        local_net = d * (side_prices - wac) * timeline_qty * multiplier - timeline_fees - projected_fee
        stop_end = len(side_prices) - (1 if len(closes) else 0)
        evaluated_prices = side_prices[:stop_end]
        peak = np.maximum.accumulate(evaluated_prices) if d == 1 else np.minimum.accumulate(evaluated_prices)
        be = np.maximum.accumulate(d * (evaluated_prices - origin) >= r)
        budget_line = wac[:stop_end] + d * (timeline_fees[:stop_end] + projected_fee[:stop_end] - parent_budget) / (timeline_qty[:stop_end] * multiplier)
        be_line = wac[:stop_end] + d * (timeline_fees[:stop_end] + projected_fee[:stop_end]) / (timeline_qty[:stop_end] * multiplier)
        trailing = peak - d * spec["trail_multiple"] * r
        candidates = np.maximum(budget_line, np.where(be, np.maximum(be_line, trailing), -np.inf)) if d == 1 else np.minimum(budget_line, np.where(be, np.minimum(be_line, trailing), np.inf))
        stop_series = np.maximum.accumulate(candidates) if d == 1 else np.minimum.accumulate(candidates)
        for order in entries:
            at = int(np.searchsorted(quotes["row"], int(order[O["fill_raw_row"]]))) - begin
            audit.near(order[O["stop_after"]], stop_series[at], "各実注文後の固定予算/BE/追尾stop")
        if len(closes):
            order = closes[0]
            audit.check(order[O["side"]] == -d and order[O["signed_quantity"]] == -d * quantity, "返済売買符号")
            audit.near(order[O["quantity"]], quantity, "全数量一括返済")
            audit.near(order[O["basket_quantity_after"]], 0., "返済後フラット")
            audit.near(order[O["wac_after"]], value / quantity, "返済注文の親WAC")
            audit.near(order[O["fixed_risk_width"]], r, "返済注文も初回幅を保持")
            audit.check(order[O["fill_raw_row"]] > entries[-1, O["fill_raw_row"]], "追加と返済の同row禁止")
            gross = d * (order[O["price"]] * quantity - value) * multiplier
            net = gross - paid - order[O["fee"]]
            gross_total += gross
            cash_delta[end] += gross - order[O["fee"]]
            pos_delta[end] -= d * quantity
            basis_delta[end] -= d * value
            record = parents[parents[:, P["parent"]] == parent_id]
            audit.check(len(record) == 1, "全返済は完結親一つ")
            record = record[0]
            expected = dict(side=d, decision_raw_row=first[O["decision_raw_row"]], entry_raw_row=first[O["fill_raw_row"]],
                exit_raw_row=order[O["fill_raw_row"]], entry_time=first[O["fill_time"]], exit_time=order[O["fill_time"]],
                original_entry_price=origin, wac=value / quantity, initial_quantity=q0, max_quantity=quantity,
                closed_quantity=quantity, add_fills=len(entries) - 1, fixed_risk_width=r, initial_loss_budget=parent_budget,
                entry_fees=paid, exit_fee=order[O["fee"]], gross=gross, net=net,
                be_armed=int(be[-1]), final_stop=stop_series[-1], peak_close_price=max(side_prices) if d == 1 else min(side_prices),
                mae_liquidation_net=min(local_net), mfe_liquidation_net=max(local_net))
            for name, expected_value in expected.items():
                audit.near(record[P[name]], expected_value, "親全会計:" + name)
            audit.near(order[O["stop_after"]], stop_series[-1], "全返済時stop参照")
            closed.append(net)
        else:
            audit.check(parent_id == parent_ids[-1], "未完結は最後の親だけ")
    cash = np.cumsum(cash_delta)
    position = np.cumsum(pos_delta)
    basis = np.cumsum(basis_delta)
    audit.check(np.all(np.abs(position) <= cap), "全quote保有数量上限")
    liquidation = np.where(position > 0, quotes["bid"], quotes["ask"])
    equity = cash + (position * liquidation - basis) * multiplier - np.floor(np.abs(position) * fee + 1e-9)
    high = np.maximum.accumulate(np.concatenate(([0.], equity)))[1:]
    drawdown = float(np.max(high - equity)) if nq else 0.
    pr, pt = bars["pub_raw_row"], bars["pub_price_time_s"]
    qi = np.searchsorted(quotes["row"], pr, side="right") - 1
    good = bars["valid"] & np.isfinite(bars["anchor"]) & (pr >= 0)
    good &= (pt - bars["t_s"] >= 0) & (pt - bars["t_s"] <= 60.) & (qi >= 0)
    if nq:
        good &= (pt - quotes["time"][np.maximum(qi, 0)] >= 0) & (pt - quotes["time"][np.maximum(qi, 0)] <= 60.)
    trace = np.full(len(pr), np.nan)
    directions = np.zeros(len(pr), dtype=np.int8)
    pub_quantity = np.zeros(len(pr), dtype=np.int64)
    trace[good] = equity[qi[good]]
    directions[good] = np.sign(position[qi[good]]).astype(np.int8)
    pub_quantity[good] = np.abs(position[qi[good]]).astype(np.int64)
    summary = dict(net=float(equity[-1]) if nq else 0., realized=float(cash[-1]) if nq else 0.,
        profit=sum(max(x, 0.) for x in closed), loss=sum(max(-x, 0.) for x in closed), parents=len(closed),
        wins=sum(x > 1e-7 for x in closed), losses=sum(x < -1e-7 for x in closed),
        closed_quantity=int(sum(parents[:, P["closed_quantity"]])), fees=float(sum(orders[:, O["fee"]])),
        unclosed=int(abs(position[-1])) if nq else 0, max_drawdown=drawdown, fills=len(orders),
        initial_quantity_min=min(initial_sizes) if initial_sizes else None, initial_quantity_max=max(initial_sizes) if initial_sizes else None,
        max_quantity=max_quantity, add_fills=add_count)
    return dict(summary=summary, equity=trace, position=directions, quantity=pub_quantity)


def main(expected_sha: str) -> None:
    """
    機能: root指定の完成結果と80小cacheを一読保全し、全2880会計を独立照合する。
    引数: expected_sha(str) は完成後に指定されたSHA256。
    返り値: None。原市場・原cache追加・金融再実行は0。
    """
    O, P = definitions()
    owned = HERE / "owned"
    owned.mkdir(exist_ok=False)
    payload = (V3 / "measurement/小試行と順行追加の全四十場.json").read_bytes()
    READS["結果"] += 1
    audit.check(audit.sha(payload) == expected_sha, "完成結果同bytes")
    (owned / "完成結果.json").write_bytes(payload)
    result = json.loads(payload.decode("utf-8"))
    fixed = json.loads((V3 / "固定計画.json").read_text(encoding="utf-8"))
    audit.check(result["source_SHA256"] == fixed["sources"], "固定源と結果一致")
    for path, expected in fixed["sources"].items():
        audit.check(audit.sha((ROOT / path).read_bytes()) == expected, "凍結源不変")
    manifest_bytes = (ROOT / fixed["input_manifest"]["path"]).read_bytes()
    audit.check(audit.sha(manifest_bytes) == fixed["input_manifest"]["sha256"], "固定入力目録")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    (owned / "入力目録.json").write_bytes(manifest_bytes)
    audit.check(len(result["runs"]) == len(result["episodes"]) == 2880 and len(result["cache"]) == 80, "36政策×80会計")
    audit.check(len(result["specs"]) == 36 and len(result["sessions"]) == 40, "36政策40場")
    lookup = {(r["symbol"], r["session"], r["method"]): r for r in result["runs"]}
    diagnostics = {(r["symbol"], r["session"], r["method"]): r for r in result["episodes"]}
    inputs = {(r["symbol"], r["session"]): r for r in manifest["inputs"]}
    audit.check(len(lookup) == len(diagnostics) == 2880, "重複なし")
    unclosed, scenes = [], []
    for cache in result["cache"]:
        symbol, scene = cache["symbol"], cache["session"]
        arrays = load_cache(ROOT / cache["path"], cache["SHA256"], owned / "v3cache" / symbol / (scene + ".npz"))
        READS["v3cache"] += 1
        info = inputs[symbol, scene]
        old_path = ROOT / info["old_owned_path"]
        audit.check(old_path.resolve().is_relative_to(BASE / "audit_result119/recovered_owned/prepared"), "気配は既所有copy")
        previous = load_cache(old_path, info["old_SHA256"])
        READS["既所有quote"] += 1
        bars = {key[6:]: value for key, value in previous.items() if key.startswith("bars__")}
        quotes = {key[8:]: value for key, value in previous.items() if key.startswith("quotes__")}
        audit.check(arrays["orders"].shape[1] == 16 and arrays["parents"].shape[1] == 28, "政策付き16注文/28親列")
        cap, multiplier, fee, _ = audit.CONTRACTS[symbol]
        for k, spec in enumerate(result["specs"]):
            orders = arrays["orders"][arrays["orders"][:, 0] == k, 1:]
            parents = arrays["parents"][arrays["parents"][:, 0] == k, 1:]
            restored = account(orders, parents, bars, quotes, cap, multiplier, fee, spec, O, P)
            saved = lookup[symbol, scene, spec["id"]]
            audit.compare_mapping(saved, restored["summary"], "全2880場の独立会計")
            audit.near(arrays["equity"][k], restored["equity"], "公開MTM")
            audit.near(arrays["position"][k], restored["position"], "公開方向と復元数量")
            record = diagnostics[symbol, scene, spec["id"]]
            audit.near(np.asarray(record["orders"]).reshape((-1, 15)), orders, "JSONとNPZの全注文一致")
            audit.near(np.asarray(record["parents"]).reshape((-1, 27)), parents, "JSONとNPZの全親一致")
            if restored["summary"]["unclosed"]:
                unclosed.append(dict(symbol=symbol, session=scene, method=spec["id"], unclosed=restored["summary"]["unclosed"]))
                print(json.dumps(dict(未返済=unclosed[-1]), ensure_ascii=False), flush=True)
        scenes.append(dict(symbol=symbol, session=scene))
        print(json.dumps(dict(cache組=len(scenes), symbol=symbol, session=scene, 検査数=audit.CHECKS), ensure_ascii=False), flush=True)
    metrics = []
    for symbol in audit.CONTRACTS:
        for spec in result["specs"]:
            rows = [lookup[symbol, scene, spec["id"]] for scene in result["sessions"]]
            metrics.append(dict(symbol=symbol, method=spec["id"], periods={name: audit.metrics([r for r in rows if r["session"] in scenes])
                           for name, scenes in result["splits"].items()}))
    audit.check(READS == dict(結果=1, v3cache=80, 既所有quote=80, 原市場=0, 原cache追加=0, 金融再実行=0), "許可された保存読取のみ")
    outputs = [write(HERE / "全三十六配分と全四十場の独立指標.json", dict(結果SHA256=expected_sha, metrics=metrics))]
    proof = dict(全合格=True, 検査数=audit.CHECKS, counts=READS, 結果SHA256=expected_sha, 未返済=unclosed,
                 未返済成功扱い=False, 全2880会計=True, source_SHA256=fixed["sources"],
                 監査源SHA256=audit.sha(Path(__file__).read_bytes()), 算術源SHA256=audit.sha(Path(audit.__file__).read_bytes()),
                 outputs=outputs, 場確認=scenes,
                 限界="保存注文の独立算術。entry判断を再選択せず金融再実行0・新標本0。公開qty/cash/stopの原配列は未保存なので直接同値を主張せず、注文から復元しposition/MTM/親と照合。")
    write(HERE / "小試行と順行追加の全注文親会計及び全場MTMの独立監査.json", proof)
    print(json.dumps(dict(全合格=True, 検査数=audit.CHECKS, counts=READS, 未返済=len(unclosed)), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    try:
        main(args.expected_sha)
    except BaseException as exc:
        write(HERE / "False.json", dict(全合格=False, 検査数=audit.CHECKS, counts=READS,
                                         型=type(exc).__name__, 例外=str(exc)))
        raise
