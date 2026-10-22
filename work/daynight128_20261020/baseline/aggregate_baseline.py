"""ＧＵ＿Ｑの保存済み完結親を、注文別手数料後の正負で再集計する。"""

import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / "work/stability126_20261019"


def read(path: Path, sources: list) -> bytes:
    """
    機能: 保存資料を読み、その内容指紋を出典へ加える。
    引数: path(Path)は保存資料、sources(list[dict])は出典記録。
    返り値: bytesは保存内容。
    """
    raw = path.read_bytes()
    sources.append(dict(path=path.relative_to(ROOT).as_posix(),
                        sha256=hashlib.sha256(raw).hexdigest()))
    return raw


def totals(rows: list[dict]) -> dict:
    """
    機能: 親単位で分けた利益・損失を商品ごとに合算する。
    引数: rows(list[dict])は同じ商品の一場一行会計。
    返り値: dictは親別正負の全場合計と黒字赤字場数。
    """
    keys = ("profit", "loss", "net", "gross_profit", "gross_loss", "gross_net",
            "fees", "parents", "winning_parents", "losing_parents", "flat_parents",
            "entry_quantity", "closed_quantity")
    result = {key: sum(row[key] for row in rows) for key in keys}
    result.update(sessions=len(rows), black=sum(row["net"] > 0 for row in rows),
                  red=sum(row["net"] < 0 for row in rows),
                  zero=sum(row["net"] == 0 for row in rows))
    assert result["profit"] - result["loss"] == result["net"]
    assert result["gross_net"] - result["fees"] == result["net"]
    return result


def main() -> None:
    """
    機能: 全四十三場二商品のＧＵ＿Ｑを完結親の手数料後損益へ揃える。
    引数: なし。
    返り値: None。結果を保存する。新金融再生、原市場読取、ＡＰＩ接続は行わない。
    """
    target = HERE / "基準四十三場の親別手数料会計.json"
    assert not target.exists()
    sources = []
    previous = json.loads(read(ROOT / "work/daynight127_20261020/昼夜と方向及び前後半の保存会計再集計_最終.json", sources))
    expected = {(row["session"], row["symbol"]): row for row in previous["rows"]
                if row["method"] == "GU_Q"}
    all_sessions = sorted({scene for scene, symbol in expected})
    assert len(expected) == 86 and len(all_sessions) == 43
    by_kind = {kind: sorted(scene for scene in all_sessions if scene.endswith("_" + kind))
               for kind in ("Day", "Night")}
    source_paths = (
        BASE / "gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json",
        BASE / "update_20261020/追加二場の八公開選択会計.json",
    )
    caches = {}
    for path in source_paths:
        source = json.loads(read(path, sources))
        assert source["passed"]
        for item in source["cache"]:
            if item.get("model", "next_normal_bbo") == "next_normal_bbo":
                key = item["session"], item["symbol"]
                assert key not in caches
                caches[key] = item
    assert caches.keys() == expected.keys()
    rows = []
    for (scene, symbol), item in sorted(caches.items()):
        raw = read(ROOT / item["path"], sources)
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        point_value, initial, cap, unit_tenths = (
            (1000, 5, 10, 418) if symbol == "TOPIX" else (10, 10, 20, 110))
        with np.load(BytesIO(raw), allow_pickle=False) as archive:
            orders = archive["GU_Q__orders"]
            cycles = archive["GU_Q__cycles"]
        assert orders.ndim == 2 and orders.shape[1] == 8
        assert cycles.ndim == 2 and cycles.shape[1] == 10
        parent_rows = []
        for cycle in cycles:
            cid = int(cycle[0])
            selected = orders[orders[:, 2] == cid]
            entry = selected[selected[:, 7] == 1]
            close = selected[selected[:, 7] == 0]
            assert len(entry) == 1 and entry[0, 4] == initial
            assert close[:, 4].sum() == initial
            gross = float(cycle[3]) * point_value
            parent_fees = sum(int(order[4]) * unit_tenths // 10 for order in selected)
            parent_rows.append(dict(parent_id=cid, direction=int(cycle[8]),
                entry_row=int(cycle[1]), exit_row=int(cycle[2]),
                initial_quantity=initial, gross=gross, fees=parent_fees,
                net=gross-parent_fees, order_count=len(selected),
                entry_orders=len(entry), repayment_orders=len(close)))
        assert len({row["parent_id"] for row in parent_rows}) == len(parent_rows)
        assert sum(row["order_count"] for row in parent_rows) == len(orders)
        reference = expected[scene, symbol]
        kind = reference["kind"]
        kind_index = by_kind[kind].index(scene)
        all_index = all_sessions.index(scene)
        result = dict(method="GU_Q", model="next_normal_bbo", session=scene, symbol=symbol,
            kind=kind, regime=reference["regime"], week_start=reference["week_start"],
            half_within_kind="前半" if kind_index < len(by_kind[kind])//2 else "後半",
            half_all_sessions="前半" if all_index < len(all_sessions)//2 else "後半",
            session_index=all_index, kind_session_index=kind_index,
            profit=sum(max(row["net"], 0.) for row in parent_rows),
            loss=sum(max(-row["net"], 0.) for row in parent_rows),
            net=sum(row["net"] for row in parent_rows),
            gross_profit=sum(max(row["gross"], 0.) for row in parent_rows),
            gross_loss=sum(max(-row["gross"], 0.) for row in parent_rows),
            gross_net=sum(row["gross"] for row in parent_rows),
            fees=sum(row["fees"] for row in parent_rows),
            parents=len(parent_rows), winning_parents=sum(row["net"] > 0 for row in parent_rows),
            losing_parents=sum(row["net"] < 0 for row in parent_rows),
            flat_parents=sum(row["net"] == 0 for row in parent_rows),
            initial_quantity=initial, configured_cap=cap,
            entry_quantity=len(parent_rows)*initial, closed_quantity=len(parent_rows)*initial,
            unclosed=0, max_long=reference["max_long"], max_short=reference["max_short"],
            parent_rows=parent_rows)
        assert result["net"] == reference["after_fees"]
        assert result["gross_net"] == reference["before_fees"]
        assert result["fees"] == reference["fees"]
        assert result["profit"] - result["loss"] == result["net"]
        assert result["entry_quantity"] == reference["new_quantity"] == reference["repaid_quantity"]
        rows.append(result)
    aggregates = [dict(symbol=symbol, **totals([row for row in rows if row["symbol"] == symbol]))
                  for symbol in ("TOPIX", "NK225")]
    split = [dict(symbol=symbol, kind=kind,
                  **totals([row for row in rows if row["symbol"] == symbol and row["kind"] == kind]))
             for symbol in ("TOPIX", "NK225") for kind in ("Day", "Night")]
    result = dict(passed=True, rows=rows, totals=aggregates, day_night_totals=split,
        accounting=dict(unit="初回新規から全返済までの完結親",
            profit="手数料後の親収支が正の親だけを合計",
            loss="手数料後の親収支が負の親だけを絶対値で合計",
            net="利益−損失。親の価格損益−全新規返済注文手数料",
            fee_rounding="１注文ごとの数量×片道料金を円未満切捨て。親内の全注文を合算",
            quantities="TOPIXミニ初回５枚、日経マイクロ初回１０枚。追加なし。片方向上限１０枚・２０枚",
            regime="保存原行の最初と最後の価格方向による事後採点。入口には利用しない",
            half_within_kind="00127と同じ。日中２２場の１１／１１、夜間２１場の１０／１１",
            half_all_sessions="全４３場を時系列で２１／２２に分割。昼夜別の前後半とは区別"),
        source=sources, financial_replays=0, original_market_reads=0, API=0, real_orders=0,
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, accounts=len(rows), totals=aggregates, day_night_totals=split),
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
