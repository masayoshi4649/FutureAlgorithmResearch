"""追加二場の完成注文だけから、現金・ＦＩＦＯ・全行清算額を独立に復元する。"""

import argparse
from collections import defaultdict
from copy import deepcopy
from io import BytesIO
import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np


HERE = Path(__file__).resolve().parent
UPDATE = HERE.parent
ROOT = UPDATE.parents[2]
SESSIONS = ("2026-10-19_Night", "2026-10-20_Day")
IDS = {"observed": ("E01", "E01_G", "E01_G_U"),
       "next_normal_bbo": ("GU_Q", "G_Q", "E01", "G_E01", "GU_E01")}
FIELDS = ("orders", "trades", "cycles", "curve", "stats")
READS = {}


def equal(actual: object, expected: object, label: str) -> None:
    """
    機能: 独立した算術と被監査値を厳しい誤差範囲で照合する。
    引数: actual/expected(object)は数又は配列、label(str)は検査項目。
    返り値: None。不一致は例外。
    """
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-6, err_msg=label)


def read_once(reference: dict) -> bytes:
    """
    機能: 明示された所有資料を監査内で一読し、同じｂｙｔｅｓで指紋を照合する。
    引数: reference(dict)はpathとsha256を持つ参照。
    返り値: bytesは照合済み保存内容。原市場と通信は使わない。
    """
    path = (ROOT/reference["path"]).resolve()
    assert path.is_relative_to(UPDATE) and reference["path"] not in READS
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    assert digest == reference["sha256"], reference["path"]
    READS[reference["path"]] = dict(sha256=digest, reads=1, bytes=len(payload))
    return payload


def write(path: Path, value: dict) -> None:
    """
    機能: 監査所有域の未使用位置へ有限な結果を保存する。
    引数: path(Path)、value(dict)は保存先と内容。
    返り値: None。既存監査の証拠を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def account(row: dict, arrays: dict, ready: dict, quotes: dict) -> dict:
    """
    機能: 全注文からＦＩＦＯ玉・返済脚・親組・全行現金在庫と清算額を別算術で作る。
    引数: row/arrays/ready/quotes(dict)は完成会計・保存配列・当時価格と気配。
    返り値: dictは独立損益・枚数・全行検算の記録。金融核と実行器関数は呼ばない。
    """
    model, symbol = row["model"], row["symbol"]
    bbo = model == "next_normal_bbo"
    assert model in IDS
    quantity, cap, mult = (5, 10, 1000.) if symbol == "TOPIX" else (10, 20, 10.)
    n = len(ready["last"])
    price = np.asarray(ready["last"], float)
    assert np.isfinite(price).all() and (price > 0.).all()
    orders, trades, cycles, curve, stats = (np.asarray(arrays[name]) for name in FIELDS)
    assert orders.ndim == 2 and orders.shape[1] == 8
    assert trades.ndim == 2 and trades.shape[1] == 11
    assert cycles.ndim == 2 and cycles.shape[1] == 10
    assert curve.shape == (n, 8) and stats.shape == (11,)
    assert all(np.isfinite(v).all() for v in (orders, trades, cycles, curve, stats))
    assert not len(orders) or np.all(np.diff(orders[:, 0]) >= 0)
    if bbo:
        np.testing.assert_array_equal(ready["seq"], quotes["seq"])
        np.testing.assert_array_equal(ready["time_s"], quotes["time_s"])
        bid, ask = np.asarray(quotes["bid"]), np.asarray(quotes["ask"])
        valid = np.asarray(quotes["quote_valid"], bool) & np.isfinite(bid) & np.isfinite(ask) & (bid > 0.) & (ask > bid)
        previous_quote = np.maximum.accumulate(np.where(valid, np.arange(n), -1))
        normal_rows = np.flatnonzero(valid)
        uids = np.asarray(arrays["order_uids"])
        assert uids.shape == (len(orders),)
    cash_delta, long_delta, short_delta, realized_delta = (np.zeros(n) for _ in range(4))
    lots, parents, expected_trades, used_uids = [], {}, [], set()
    new_count, repaid_count = 0, 0
    for index, order in enumerate(orders):
        raw, source, cid, side, qty = map(int, order[:5])
        fill, reason, entry = float(order[5]), int(order[6]), int(order[7])
        assert np.array_equal(order[:5], [raw, source, cid, side, qty])
        assert 0 <= source < raw < n and side in (-1, 1) and qty > 0 and entry in (0, 1)
        if bbo:
            assert valid[raw] and fill == (ask[raw] if side > 0 else bid[raw])
        else:
            equal(fill, price[raw], "観測Last約定")
        cash_delta[raw] -= side*qty*fill
        if entry:
            assert qty == quantity and cid not in parents
            assert not any(lot["qty"] for lot in lots), "旧親の残玉中に別親を開始"
            uid = int(uids[index]) if bbo else new_count
            assert uid >= 0 and uid not in used_uids
            used_uids.add(uid)
            if bbo:
                assert normal_rows[np.searchsorted(normal_rows, source, side="right")] == raw
            lots.append(dict(uid=uid, cid=cid, side=side, qty=qty, fill=fill, row=raw))
            parents[cid] = dict(entry_row=raw, exit_row=-1, side=side, qty=qty, pnl=0., reason=-1)
            new_count += 1
            (long_delta if side > 0 else short_delta)[raw] += qty
        else:
            assert cid in parents and parents[cid]["side"] == -side
            if bbo:
                assert uids[index] == -1
            left = qty
            for lot in lots:
                if not left:
                    break
                if not lot["qty"] or lot["cid"] != cid or lot["side"] != -side:
                    continue
                take = min(left, lot["qty"])
                gain = lot["side"]*take*(fill-lot["fill"])
                expected_trades.append([cid, lot["uid"], lot["side"], take, lot["fill"], fill,
                                        lot["row"], raw, 0., reason, gain])
                realized_delta[raw] += gain
                parents[cid]["pnl"] += gain
                lot["qty"] -= take
                left -= take
            assert left == 0, "保有量を超えた返済"
            parents[cid].update(exit_row=raw, reason=reason)
            repaid_count += qty
            (long_delta if side < 0 else short_delta)[raw] -= qty
    equal(trades, np.asarray(expected_trades, float).reshape((-1, 11)), "注文から別実装で復元した全FIFO返済脚")
    cash, long_qty, short_qty, realized = (np.cumsum(v) for v in (cash_delta, long_delta, short_delta, realized_delta))
    assert np.all((long_qty >= 0) & (long_qty <= cap) & (short_qty >= 0) & (short_qty <= cap))
    assert not np.any((long_qty > 0) & (short_qty > 0))
    assert long_qty[-1] == short_qty[-1] == 0. and not any(lot["qty"] for lot in lots)
    if bbo:
        held = long_qty+short_qty > 0
        assert np.all(previous_quote[held] >= 0)
        liquidation = np.zeros(n)
        longs, shorts = long_qty > 0, short_qty > 0
        liquidation[longs] = long_qty[longs]*bid[previous_quote[longs]]
        liquidation[shorts] = -short_qty[shorts]*ask[previous_quote[shorts]]
    else:
        liquidation = (long_qty-short_qty)*price
    equity = cash+liquidation
    peak = np.maximum.accumulate(np.maximum(equity, 0.))
    drawdown = np.maximum.accumulate(peak-equity)
    expected_curve = np.column_stack((equity, realized, long_qty, short_qty, drawdown, cash, long_qty-short_qty))
    equal(curve[:, :7], expected_curve, "全行の在庫・現金・実現損益・気配清算・最大DD")
    expected_stats = [realized[-1], drawdown.max(initial=0.), long_qty.max(initial=0.), short_qty.max(initial=0.),
                      (long_qty+short_qty).max(initial=0.), np.abs(long_qty-short_qty).max(initial=0.), 0.,
                      min(0., equity.min(initial=0.)), max(0., equity.max(initial=0.)), 0., 0.]
    equal(stats, expected_stats, "全十一統計")
    if bbo:
        states = np.asarray(arrays["execution_states"])
        assert states.shape == (n, 14)
        equal(states[:, 3], long_qty, "実行状態の買い数量")
        equal(states[:, 4], short_qty, "実行状態の売り数量")
        equal(states[:, 9], previous_quote, "最新有効気配の元行")
        equal(states[:, 2], curve[:, 7], "親IDの状態と曲線")
    assert len(cycles) == len(parents)
    assert len(set(cycles[:, 0])) == len(cycles)
    for cycle in cycles:
        cid, entry_row, exit_row = map(int, cycle[:3])
        parent = parents[cid]
        assert entry_row == parent["entry_row"] and exit_row == parent["exit_row"]
        assert cycle[8] == parent["side"] and cycle[9] == parent["reason"]
        assert cycle[5] > 0. and np.isfinite(cycle[5])
        equal(cycle[3], parent["pnl"], "完結親の実注文損益")
        equal(cycle[4], quantity*cycle[5], "初回ATR固定リスク")
        equal(cycle[6:8], [quantity, quantity], "増玉なしの親最大枚数")
    gains = np.asarray([v[10] for v in expected_trades], float)*mult
    parent_pnl = np.asarray([parents[int(c[0])]["pnl"] for c in cycles], float)*mult
    value = dict(model=model, method=row["method"], session=row["session"], symbol=symbol,
        profit=float(np.maximum(gains, 0.).sum()), loss=float(np.maximum(-gains, 0.).sum()),
        net=float(gains.sum()), fees=0., groups=len(parents), entry_orders=new_count,
        entry_quantity=quantity*new_count, closed_quantity=repaid_count, unclosed=0,
        parent_profit=float(np.maximum(parent_pnl, 0.).sum()), parent_loss=float(np.maximum(-parent_pnl, 0.).sum()),
        long_net=float(gains[trades[:, 2] > 0].sum()), short_net=float(gains[trades[:, 2] < 0].sum()),
        max_long=float(long_qty.max(initial=0.)), max_short=float(short_qty.max(initial=0.)),
        curve_rows=n, order_rows=len(orders), trade_rows=len(trades), full_curve_audited=True)
    assert value["entry_quantity"] == value["closed_quantity"]
    equal(value["net"], cash[-1]*mult, "最後の現金収支")
    equal(value["net"], parent_pnl.sum(), "完結親の合計")
    for name, actual in value.items():
        if name in row and name not in ("model", "method", "session", "symbol"):
            equal(row[name], actual, "保存会計欄/"+name)
    return value


def paper_subset(paper: dict, ready: dict, quotes: dict, enabled: bool) -> tuple[np.ndarray, list[dict]]:
    """
    機能: 保存紙上注文から初回ATRと当時気配だけで受付通知を独立に構成する。
    引数: paper/ready/quotes(dict)、enabled(bool)は保存紙上注文とＱ条件の有効化。
    返り値: tuple[ndarray,list[dict]]は十列通知と当時の親採否。金融核を呼ばない。
    """
    atrs = {int(c[0]): float(c[5]) for c in paper["cycles"]}
    decisions, feed, traces = {}, [], []
    for order in paper["orders"]:
        row, source, cid, side, qty = map(int, order[:5])
        assert 0 <= source < row < len(ready["last"])
        if order[7] == 1.:
            assert cid not in decisions
            atr, last = atrs[cid], float(ready["last"][row])
            bid, ask = float(quotes["bid"][row]), float(quotes["ask"][row])
            normal = bool(quotes["quote_valid"][row]) and np.isfinite(bid) and np.isfinite(ask) and 0. < bid < ask
            known = normal and np.isfinite(last) and last > 0. and np.isfinite(atr) and atr > 0.
            accepted = (not enabled) or bool(known and ask-bid <= atr/2. and (ask-last if side > 0 else last-bid) <= atr/2.)
            decisions[cid] = accepted
            traces.append(dict(parent=cid, publication_row=row, accepted=accepted))
        assert cid in decisions
        if decisions[cid]:
            feed.append([*order, 0., atrs[cid] if order[7] == 1. else 0.])
    return np.asarray(feed, float).reshape((-1, 10)), traces


def self_check() -> dict:
    """
    機能: 手計算の正しい部分返済台帳と故意破損を使い監査器の拒否能力を検査する。
    引数: なし。
    返り値: dictは人工検査結果。数値核・原市場・金融再生は使わない。
    """
    price = np.array([9., 10., 11., 12., 12., 11.])
    ready = dict(last=price, seq=np.arange(6), time_s=np.arange(6, dtype=float))
    quotes = dict(seq=ready["seq"], time_s=ready["time_s"],
        bid=np.array([8., 9., 10., 12., np.nan, 11.]),
        ask=np.array([9., 10., 11., 13., np.nan, 12.]),
        quote_valid=np.array([True, True, True, True, False, True]))
    orders = np.array([[1, 0, 0, 1, 5, 10, 20, 1], [3, 2, 0, -1, 2, 12, 7, 0], [5, 4, 0, -1, 3, 11, 9, 0]], float)
    trades = np.array([[0, 0, 1, 2, 10, 12, 1, 3, 0, 7, 4], [0, 0, 1, 3, 10, 11, 1, 5, 0, 9, 3]], float)
    cycles = np.array([[0, 1, 5, 7, 5, 1, 5, 5, 1, 9]], float)
    curve = np.array([[0, 0, 0, 0, 0, 0, 0, -1], [0, 0, 5, 0, 0, -50, 5, 0],
        [5, 0, 5, 0, 0, -50, 5, 0], [10, 4, 3, 0, 0, -26, 3, 0],
        [10, 4, 3, 0, 0, -26, 3, 0], [7, 7, 0, 0, 3, 7, 0, 0]], float)
    original = dict(orders=orders, trades=trades, cycles=cycles, curve=curve,
        stats=np.array([7, 3, 5, 0, 5, 5, 0, 0, 10, 0, 0], float))
    checked = []
    for model in IDS:
        values = deepcopy(original)
        if model == "next_normal_bbo":
            values["trades"][:, 1] = 7.
            values["order_uids"] = np.array([7, -1, -1])
            values["curve"][:, 0] = [0, -5, 0, 10, 10, 7]
            values["curve"][:, 4] = [0, 5, 5, 5, 5, 5]
            values["stats"][[1, 7]] = [5, -5]
            states = np.zeros((6, 14))
            states[:, 2] = values["curve"][:, 7]
            states[:, 3] = values["curve"][:, 2]
            states[:, 9] = [0, 1, 2, 3, 3, 5]
            values["execution_states"] = states
        row = dict(model=model, method="人工", session="人工", symbol="TOPIX")
        verified = account(row, values, ready, quotes)
        assert verified["net"] == 7000. and verified["profit"] == 7000.
        checked.append(model+"の手計算正値")
        mutations = []
        for field, index in (("trades", (0, 10)), ("curve", (2, 0)), ("orders", (0, 4)), ("cycles", (0, 3)), ("stats", (0,))):
            broken = deepcopy(values)
            broken[field][index] += 1.
            mutations.append((field, broken))
        for label, broken in mutations:
            try:
                account(row, broken, ready, quotes)
            except (AssertionError, IndexError):
                checked.append(model+"の故意破損拒否/"+label)
            else:
                raise AssertionError("故意破損を許可/"+model+"/"+label)
    return dict(passed=True, checks=checked, count=len(checked),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        original_market_reads=0, financial_replays=0, API=0, real_orders=0)


def execute(result_path: Path, expected: str) -> None:
    """
    機能: 完成した三十二会計と八ＮＰＺを全注文・全行時価・引用元まで独立監査する。
    引数: result_path(Path)、expected(str)は完成結果と親が固定したＳＨＡ２５６。
    返り値: None。監査結果のみ新規保存し、取引判断の再運転は行わない。
    """
    assert len(expected) == 64
    result_ref = dict(path=result_path.resolve().relative_to(ROOT).as_posix(), sha256=expected)
    completed = json.loads(read_once(result_ref))
    assert completed["passed"] and completed["sessions"] == list(SESSIONS)
    assert completed["displayed_accounts"] == len(completed["rows"]) == 32
    assert len(completed["cache"]) == 8
    stored = {(r["model"], r["method"], r["session"], r["symbol"]): r for r in completed["rows"]}
    expected_keys = {(model, method, scene, symbol) for model, methods in IDS.items()
        for method in methods for scene in SESSIONS for symbol in ("TOPIX", "NK225")}
    assert set(stored) == expected_keys
    manifest = json.loads(read_once(completed["input_manifest"]))
    assert manifest["passed"] and manifest["sessions"] == list(SESSIONS)
    references = {(v["model"], v["session"], v["symbol"]): v for v in completed["cache"]}
    assert len(references) == 8
    independent, q_checks, alias_checks, full_curve_rows = [], [], [], 0
    alias_index = {(v["model"], v["method"], v["session"], v["symbol"]): v for v in completed["aliases"]}
    assert set(alias_index) == expected_keys
    for reference in manifest["packets"]:
        packet = pickle.loads(read_once(reference))
        scene = reference["session"]
        assert packet["session"] == scene
        for symbol in ("TOPIX", "NK225"):
            key = scene, symbol
            ready, quotes = packet["inputs"][key], packet["quotes"][key]
            papers = {}
            for model, methods in IDS.items():
                ref = references[model, scene, symbol]
                with np.load(BytesIO(read_once(ref)), allow_pickle=False) as archive:
                    assert {name.split("__", 1)[0] for name in archive.files} == set(methods)
                    for method in methods:
                        entry = stored[model, method, scene, symbol]
                        fields = FIELDS if model == "observed" else FIELDS+("order_uids", "execution_states", "execution_events", "paper_feed")
                        values = {name: archive[method+"__"+name] for name in fields}
                        independent.append(account(entry, values, ready, quotes))
                        full_curve_rows += len(ready["last"])
                        if model == "observed":
                            papers[{"E01": "E01", "E01_G": "G", "E01_G_U": "GU"}[method]] = {name: values[name] for name in ("orders", "cycles")}
                        else:
                            source = "GU" if method.startswith("GU_") else "G" if method.startswith("G_") else "E01"
                            expected_feed, decisions = paper_subset(papers[source], ready, quotes, method.endswith("_Q"))
                            equal(values["paper_feed"], expected_feed, "原紙上通知と当時気配だけの採否")
                            q_checks.append(dict(method=method, session=scene, symbol=symbol,
                                parents=len(decisions), accepted=sum(v["accepted"] for v in decisions),
                                rejected=sum(not v["accepted"] for v in decisions)))
                        alias = alias_index[model, method, scene, symbol]
                        assert alias["canonical_method"] == entry["canonical_method"]
                        if alias["canonical_method"] != method:
                            canonical = alias["canonical_method"]
                            names = {name[len(method)+2:] for name in archive.files if name.startswith(method+"__")}
                            other_names = {name[len(canonical)+2:] for name in archive.files if name.startswith(canonical+"__")}
                            assert names == other_names
                            for name in names:
                                np.testing.assert_array_equal(archive[method+"__"+name], archive[canonical+"__"+name])
                            alias_checks.append(dict(model=model, method=method, canonical_method=canonical,
                                session=scene, symbol=symbol, compared_arrays=len(names)))
            print(scene+" "+symbol+" の八会計を独立算術で確認", flush=True)
    assert len(independent) == 32 and len(READS) == 12
    assert len(alias_checks) == completed["reused_within_stage_accounts"]
    assert 32-len(alias_checks) == completed["new_financial_accounts"]
    totals = []
    for model, methods in IDS.items():
        for method in methods:
            for symbol in ("TOPIX", "NK225"):
                part = [v for v in independent if v["model"] == model and v["method"] == method and v["symbol"] == symbol]
                assert len(part) == 2
                amounts = {name: sum(v[name] for v in part) for name in ("profit", "loss", "net", "entry_quantity", "closed_quantity")}
                equal(amounts["profit"]-amounts["loss"], amounts["net"], "追加二場累計")
                totals.append(dict(model=model, method=method, symbol=symbol, **amounts))
    write(HERE/"追加二場三十二会計の全注文と全行清算の独立監査.json", dict(
        passed=True, result=result_ref, source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        checked_accounts=32, checked_cache_files=8, full_curve_rows=full_curve_rows,
        rows=independent, totals=totals, q_checks=q_checks, alias_checks=alias_checks, read_log=READS,
        original_market_reads=0, financial_replays=0, API=0, real_orders=0,
        scope="別実装で全注文現金・FIFO返済・数量・親組・全行Last/BBO清算・統計・当時Q採否・全配列引用を照合。取引判断と金融核は呼ばない。"))
    print(json.dumps(dict(passed=True, accounts=32, full_curve_rows=full_curve_rows), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path)
    parser.add_argument("--result-sha")
    parser.add_argument("--self-check", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_check:
        assert arguments.result is None and arguments.result_sha is None
        proof = self_check()
        write(HERE/"人工正値と故意破損の独立会計確認.json", proof)
        print(json.dumps(dict(passed=True, count=proof["count"]), ensure_ascii=False))
    else:
        assert arguments.result is not None and arguments.result_sha is not None
        try:
            execute(arguments.result, arguments.result_sha)
        except Exception as error:
            write(HERE/("会計監査停止_"+str(time.time_ns())+".json"), dict(
                passed=False, error=repr(error), read_log=READS, original_market_reads=0, financial_replays=0))
            raise
