"""既存二候補の保存約定へユーザー提示の立会手数料を掛け、売買不変の差引収支を示す。"""

import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
METHODS = ("GU_Q", "G_Q")


def sha(payload: bytes) -> str:
    """
    機能: 読み取った保存会計の内容指紋を求める。
    引数: payload(bytes)は保存内容。
    返り値: strはＳＨＡ２５６。
    """
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    """
    機能: 全四十三場の新規・返済注文ごとの円未満切捨て料金と実保有数量を集計する。
    引数: なし。
    返り値: None。注文や損切り判断を変更せず、保存売買の費用差引だけを新規保存する。
    """
    target = HERE / "二候補の四十三場の注文別手数料と実保有枚数.json"
    assert not target.exists()
    references = (TASK / "gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json",
                  TASK / "update_20261020/追加二場の八公開選択会計.json")
    sources, summaries, reads = [], [], []
    for path in references:
        payload = path.read_bytes()
        source = json.loads(payload)
        assert source["passed"]
        sources.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(payload)))
        rows = {(r["session"], r["symbol"], r["method"]): r for r in source["rows"]
                if r["method"] in METHODS and r.get("model", "next_normal_bbo") == "next_normal_bbo"}
        for item in source["cache"]:
            if item.get("model", "next_normal_bbo") != "next_normal_bbo":
                continue
            raw = (ROOT / item["path"]).read_bytes()
            assert sha(raw) == item["sha256"]
            reads.append(dict(path=item["path"], sha256=item["sha256"], reads=1))
            symbol, scene = item["symbol"], item["session"]
            unit_tenths = 418 if symbol == "TOPIX" else 110
            initial, cap = (5, 10) if symbol == "TOPIX" else (10, 20)
            with np.load(BytesIO(raw), allow_pickle=False) as archive:
                for method in METHODS:
                    row = rows[scene, symbol, method]
                    orders = archive[method + "__orders"]
                    assert orders.ndim == 2 and orders.shape[1] == 8
                    quantities = orders[:, 4].astype(np.int64)
                    assert np.array_equal(quantities, orders[:, 4]) and np.all(quantities > 0)
                    fees = quantities * unit_tenths // 10
                    entry = orders[:, 7] == 1
                    assert np.all(orders[~entry, 7] == 0) and np.all(quantities[entry] == initial)
                    assert int(quantities[entry].sum()) == row["entry_quantity"] == row["closed_quantity"]
                    assert int(quantities[entry].sum()) == int(quantities[~entry].sum())
                    positions, maxima = {1: 0, -1: 0}, {1: 0, -1: 0}
                    for order in orders:
                        side, quantity, opening = int(order[3]), int(order[4]), bool(order[7])
                        position_side = side if opening else -side
                        positions[position_side] += quantity if opening else -quantity
                        assert 0 <= positions[position_side] <= cap
                        maxima[position_side] = max(maxima[position_side], positions[position_side])
                    assert positions == {1: 0, -1: 0}
                    assert maxima[1] == row["max_long"] and maxima[-1] == row["max_short"]
                    summaries.append(dict(method=method, session=scene, symbol=symbol,
                        before_fees=row["net"], fees=int(fees.sum()), after_fees=row["net"] - int(fees.sum()),
                        new_quantity=int(quantities[entry].sum()), repaid_quantity=int(quantities[~entry].sum()),
                        new_orders=int(entry.sum()), repayment_orders=int((~entry).sum()),
                        initial_quantity=initial, configured_cap=cap, max_long=maxima[1], max_short=maxima[-1],
                        new_fees=int(fees[entry].sum()), repayment_fees=int(fees[~entry].sum())))
    assert len(summaries) == 172 and len(reads) == 86
    totals = []
    for method in METHODS:
        for symbol in ("TOPIX", "NK225"):
            selected = [r for r in summaries if r["method"] == method and r["symbol"] == symbol]
            assert len(selected) == len({r["session"] for r in selected}) == 43
            total = {key: sum(r[key] for r in selected) for key in (
                "before_fees", "fees", "after_fees", "new_quantity", "repaid_quantity",
                "new_orders", "repayment_orders", "new_fees", "repayment_fees")}
            total.update(method=method, symbol=symbol, sessions=43,
                red_before=sum(r["before_fees"] < 0 for r in selected),
                red_after=sum(r["after_fees"] < 0 for r in selected),
                initial_quantity=selected[0]["initial_quantity"], configured_cap=selected[0]["configured_cap"],
                maximum_long=max(r["max_long"] for r in selected), maximum_short=max(r["max_short"] for r in selected))
            assert total["before_fees"] - total["fees"] == total["after_fees"]
            totals.append(total)
    result = dict(passed=True, totals=totals, rows=summaries, sources=sources, order_cache_reads=reads,
        fees=dict(TOPIXmini="税込片道1枚41.8円", NK225micro="税込片道1枚11円", rounding="1注文ごとの合計料金で1円未満切捨て。新規・返済の両方。"),
        calculation="保存済みの同じ売買へ手数料を差し引く会計。手数料を理由に入口・出口・停止を再判定した別戦略ではない。",
        financial_replays=0, original_market_reads=0, API=0, real_orders=0,
        producer_sha256=sha(Path(__file__).read_bytes()))
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(totals, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
