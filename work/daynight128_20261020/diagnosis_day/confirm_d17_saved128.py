"""第三巡D17を保存注文から再集計し、既存親の拒否との差を照合する。"""

import hashlib
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
SOURCES = []


def digest(path: Path) -> str:
    """
    機能: 保存ファイルのSHA256をストリーム計算する。
    引数: path(Path)は読取対象。
    返り値: strは十六進の指紋。
    """
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_json(path: Path) -> dict:
    """
    機能: 元資料を読み、今回使った内容の指紋を記録する。
    引数: path(Path)はUTF-8のJSON資料。
    返り値: dictは資料内容。
    """
    SOURCES.append(dict(path=str(path.relative_to(ROOT)), sha256=digest(path)))
    return json.loads(path.read_text(encoding="utf-8"))


def saved_arrays(ref: dict, method: str) -> tuple:
    """
    機能: 会計資料に固定された保存配列から注文と完結親を読む。
    引数: ref(dict)は保存場所と指紋、method(str)は手法ID。
    返り値: tuple[ndarray, ndarray]は注文と完結親。金融再生しない。
    """
    path = ROOT / ref["path"]
    assert digest(path) == ref["sha256"]
    SOURCES.append(dict(path=ref["path"], sha256=ref["sha256"]))
    with np.load(path, allow_pickle=False) as stored:
        return stored[f"{method}__orders"].copy(), stored[f"{method}__cycles"].copy()


def parent_accounts(orders: np.ndarray, cycles: np.ndarray, symbol: str) -> dict:
    """
    機能: 保存注文の現金と注文別費用から各親の最終損益を独立計算する。
    引数: orders/cycles(ndarray)は完成配列、symbol(str)は商品。
    返り値: dict[int, dict]は親番号ごとの粗損益・費用・収支。
    """
    multiplier, fee_tenths = (1000, 418) if symbol == "TOPIX" else (10, 110)
    result = {}
    assert np.all(orders[:, 0] > orders[:, 1])
    assert np.array_equal(orders[:, 4], orders[:, 4].astype(np.int64))
    for cid in sorted(set(int(value) for value in orders[:, 2])):
        selected = orders[orders[:, 2] == cid]
        quantity = selected[:, 4].astype(np.int64)
        entry = selected[:, 7] == 1
        assert entry.sum() == 1
        assert quantity[entry].sum() == quantity[~entry].sum()
        assert np.dot(selected[:, 3], quantity) == 0
        gross = float(-np.sum(selected[:, 3] * quantity * selected[:, 5]) * multiplier)
        fees = int(np.sum(quantity * fee_tenths // 10))
        cycle = cycles[cycles[:, 0] == cid]
        assert len(cycle) == 1
        assert np.isclose(gross, cycle[0, 3] * multiplier)
        result[cid] = dict(gross=gross, fees=fees, net=gross-fees,
                           orders=len(selected), initial_quantity=int(quantity[entry][0]))
    assert set(result) == set(cycles[:, 0].astype(int))
    return result


def aggregate(rows: list) -> dict:
    """
    機能: 保存会計の場別値から勝敗・最大損失・主要利益指標を再集計する。
    引数: rows(list[dict])は指定区間の場会計。
    返り値: dictは同値・無取引を分けた集計。
    """
    values = np.array([r["net"] for r in rows], dtype=float)
    wins = values[values > 0]
    return dict(
        sessions=len(rows), net=float(values.sum()),
        profit=sum(r["profit"] for r in rows), loss=sum(r["loss"] for r in rows),
        fees=sum(r["fees"] for r in rows), black=int((values > 0).sum()),
        red=int((values < 0).sum()), flat=int((values == 0).sum()),
        active=sum(r["entries"] > 0 for r in rows),
        median=float(np.median(values)), worst=float(values.min()),
        mean_black=float(wins.mean()) if len(wins) else 0.,
        without_top3=float(values.sum() - np.sort(wins)[-3:].sum()),
        entries=sum(r["entries"] for r in rows),
    )


def main() -> None:
    """
    機能: D17の全44商品場をD11と保存注文単位で照合し診断を保存する。
    引数: なし。
    返り値: None。原本不変、金融再生・原板読取・API利用は0回。
    """
    second = read_json(TASK / "round2/全条件の会計.json")
    third = read_json(TASK / "round3/全条件の会計.json")
    analysis = read_json(TASK / "round3/前後半と方向別の比較.json")
    initial = read_json(HERE / "第二巡D11の残存赤字と短期支持条件の取捨.json")
    final_rule = read_json(HERE / "第三巡kind5実定義と初期分類の差.json")
    earlier_audit = read_json(TASK / "audit/round3_全注文と全行会計の独立照合.json")
    assert earlier_audit["passed"]
    refs = [{(r["symbol"], r["session"]): r for r in d["cache"]} for d in (second, third)]
    old_rows = {(r["symbol"], r["session"]): r for r in second["rows"] if r["method"] == "D11"}
    new_rows = {(r["symbol"], r["session"]): r for r in third["rows"] if r["method"] == "D17"}
    assert set(old_rows) == set(new_rows) and len(new_rows) == 44
    classifications = {(r["symbol"], r["session"], r["parent"]): r for r in initial["all_parents"]}
    accounts, selected_parents, rejected_parents = [], [], []
    for key in sorted(new_rows):
        symbol, session = key
        old_orders, old_cycles = saved_arrays(refs[0][key], "D11")
        new_orders, new_cycles = saved_arrays(refs[1][key], "D17")
        old = parent_accounts(old_orders, old_cycles, symbol)
        new = parent_accounts(new_orders, new_cycles, symbol)
        accepted, rejected = [], []
        for cid, account in old.items():
            p = classifications[symbol, session, cid]
            assert account["net"] == p["net"]
            market = p["source_market"]
            known = market[11] == 1 and all(market[c] is not None and np.isfinite(market[c]) for c in (4, 6))
            ok = known and all(p["direction"] * market[c] >= -.05 for c in (4, 6))
            target = accepted if ok else rejected
            target.append(cid)
            (selected_parents if ok else rejected_parents).append(
                dict(symbol=symbol, session=session, parent=cid, **account))
        assert set(new) == set(accepted)
        # ----------------------------------------
        # 採用親の時刻・方向・数量・価格・部分返済を同じ元親番号で比較する。
        old_kept_orders = old_orders[np.isin(old_orders[:, 2].astype(int), accepted)]
        old_kept_cycles = old_cycles[np.isin(old_cycles[:, 0].astype(int), accepted)]
        assert np.array_equal(old_kept_orders, new_orders, equal_nan=True)
        assert np.array_equal(old_kept_cycles, new_cycles, equal_nan=True)
        calculated = dict(
            net=sum(v["net"] for v in new.values()),
            gross=sum(v["gross"] for v in new.values()),
            fees=sum(v["fees"] for v in new.values()),
            profit=sum(max(v["net"], 0) for v in new.values()),
            loss=sum(max(-v["net"], 0) for v in new.values()),
            entries=len(new),
        )
        for field, value in calculated.items():
            assert np.isclose(value, new_rows[key][field])
        removed = sum(old[cid]["net"] for cid in rejected)
        assert calculated["net"] - old_rows[key]["net"] == -removed
        accounts.append(dict(symbol=symbol, session=session, **calculated,
            old_net=old_rows[key]["net"], actual_net_difference=calculated["net"]-old_rows[key]["net"],
            rejected_net=removed, rejected_parents=rejected, kept_parents=accepted,
            kept_orders_exactly_equal=True, kept_cycles_exactly_equal=True))
    products = []
    for symbol in ("TOPIX", "NK225"):
        rows = [r for r in analysis["rows"] if r["method"] == "D17" and r["symbol"] == symbol]
        summary = next(s for s in analysis["summary"] if s["method"] == "D17" and s["symbol"] == symbol)
        sections = dict(
            all=(rows, summary),
            **{f"half_{h}": ([r for r in rows if r["half_within_kind"] == h], target)
               for h, target in summary["halves"].items()},
            **{f"regime_{g}": ([r for r in rows if r["regime"] == g], target)
               for g, target in summary["regimes"].items()},
        )
        checked = {}
        for section, (selected, expected) in sections.items():
            result = aggregate(selected)
            for field, value in result.items():
                assert np.isclose(value, expected[field])
            checked[section] = result
        rejected = [r for r in rejected_parents if r["symbol"] == symbol]
        known = next(p for p in final_rule["products"] if p["symbol"] == symbol)
        assert len(rejected) == known["actual_kind5_rejected_count"]
        assert sum(p["net"] for p in rejected) == known["actual_kind5_rejected_net"]
        products.append(dict(symbol=symbol, sections=checked,
            worst_three=[dict(session=r["session"], net=r["net"], entries=r["entries"])
                         for r in sorted(rows, key=lambda r: r["net"])[:3]],
            no_trade_sessions=[r["session"] for r in rows if not r["entries"]],
            rejected_count=len(rejected), rejected_net=sum(p["net"] for p in rejected),
            kept_count=sum(r["symbol"] == symbol for r in selected_parents),
            actual_net_difference=sum(r["actual_net_difference"] for r in accounts if r["symbol"] == symbol)))
    proof = dict(
        passed=True, products=products, accounts=accounts,
        rejected_parents=rejected_parents, kept_parents=selected_parents,
        selection={k: analysis["selected"]["Day"][k]
                   for k in ("frozen_on_first_half", "full_development_reference")},
        source_hashes=SOURCES, auditor_sha256=digest(Path(__file__)),
        financial_replays=0, original_market_reads=0, API=0,
        explanation="全44商品場でD17注文と完結親が、D11から実kind5拒否親を除いた配列と完全一致。新規親も残存親の時刻・数量・価格の変化もなし。今回は差額が拒否旧親の逆符号と一致した。",
        limitation="固定したGQ通知列・通常影再参加を維持した条件下の照合。即時再参加やセッション損失停止を加える別運転へ単純差額を一般化しない。全場参考選定と前半選定を分ける。",
    )
    target = HERE / "第三巡D17の保存注文と拒否親差の独立確認.json"
    assert not target.exists()
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, products=products, output=str(target), sha256=digest(target)), ensure_ascii=True))


if __name__ == "__main__":
    main()
