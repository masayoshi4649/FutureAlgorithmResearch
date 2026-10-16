"""完成した三源を独立の有理数会計・予約期待へ接続する。"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import hashlib
import importlib
import json
import shutil
import sys
import traceback

import numpy as np

from cash_reference import PRODUCTS, order_fee, pure_expectations
from execution_expectations import event_eligible, fixtures, reference_checks

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
EXPECTED = {
    "catalog.py": "504b1a57c336c53f9431b66755eab6db05a29e5ad4e35e90d78416be45dba2dd",
    "engine.py": "7947a59dd7c9704acc31b5caa429722808e76cfd1c21f1354bd8bef375b47dec",
    "artificial.py": "9ca54f431478e656592e92c2f3d23da6af4dd34bc8b66e6d7090f50d8d1c2156",
}
FIELDS = ["type", "episode", "pub_i", "d", "opposite_q0", "opposite_min_q", "bid_q_at_public", "ask_q_at_public"]


def digest(path: Path) -> str:
    """
    機能: 小さな源の SHA256 を取得する。
    引数: path(Path) 源ファイル。
    返り値: str SHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def product_of(symbol: str):
    """
    機能: 実装から独立した商品条件を選ぶ。
    引数: symbol(str) 商品。
    返り値: Product 純参照の商品条件。
    """
    return next(p for p in PRODUCTS if p.symbol == symbol)


def materialize(symbol: str, side: int, ticks: list[int]) -> tuple[dict, dict, dict]:
    """
    機能: 実新規後の返済可能気配を指定呼値で作る。
    引数: symbol(str)、side(int)、ticks(list[int]) 各行の気配順行幅。
    返り値: tuple[dict,dict,dict] 人工原配列・保存信号・時間方針。
    """
    p = product_of(symbol)
    values = list(ticks) + [ticks[-1]]
    n = len(values)
    entry = p.base + p.tick if side == 1 else p.base
    bid, ask = [], []
    for row, gross in enumerate(values):
        if row == 0:
            b, a = p.base, p.base + p.tick
        elif side == 1:
            b = entry + gross * p.tick
            a = b + p.tick
        else:
            a = entry - gross * p.tick
            b = a - p.tick
        bid.append(float(b))
        ask.append(float(a))
    times = np.arange(n, dtype=np.float64) + 1000.0
    times[-1] = 1700.0
    arrays = {
        "raw_seq": np.arange(100, 100 + n, dtype=np.int64),
        "price_time_s": times,
        "bid": np.array(bid), "ask": np.array(ask),
        "bid_qty": np.full(n, 10.0), "ask_qty": np.full(n, 10.0),
        "best_quantity_valid": np.ones(n, dtype=np.bool_),
    }
    events = np.array([[typ, 0, 0, side, 10, 10, 10, 10] for typ in (0, 1)], dtype=np.float64)
    signal = {"events": events, "fields": list(FIELDS), "price_valid_mask": np.ones(n, dtype=np.bool_)}
    policy = {"entry_start_s": 0.0, "entry_end_s": 1400.0, "force_start_s": 1700.0, "quiet_windows": np.empty((0, 2))}
    return arrays, signal, policy


def select_config(catalog, entry: int, exit_mode: int) -> dict:
    """
    機能: 固定済み十二条件から入口と出口を選ぶ。
    引数: catalog(module)、entry(int)、exit_mode(int)。
    返り値: dict 固定条件。
    """
    return next(c for c in catalog.configs() if c["entry_mode"] == entry and c["exit_mode"] == exit_mode)


def run_case(engine, catalog, fixture: dict, entry_mode: int, finish: bool = True):
    """
    機能: 独立経路を完成源へ一回接続する。
    引数: engine/catalog(module)、fixture(dict)、entry_mode(int)、finish(bool)。
    返り値: tuple[dict,dict,dict,dict] 結果と人工入力。
    """
    a, s, t = materialize(fixture["symbol"], fixture["side"], fixture["ticks"])
    result = engine.simulate(a, s, fixture["symbol"], 0.0, 2000.0, float(product_of(fixture["symbol"]).tick), t,
                             select_config(catalog, entry_mode, fixture["mode"]), finish=finish)
    return result, a, s, t


def check_parent(result: dict, fixture: dict) -> int:
    """
    機能: 約定行・量・料金・粗損益と完結親会計を独立に照合する。
    引数: result(dict) 完成源結果、fixture(dict) 先に固定した期待。
    返り値: int 確認数。
    """
    p = product_of(fixture["symbol"])
    assert result["completed"] and len(result["parent"]) == 1
    actual = result["parent"][0]
    assert actual["quantity"] == p.quantity and actual["side"] == fixture["side"]
    assert actual["entry_row"] == 1 and actual["exit_row"] == fixture["fills"][-1][1]
    assert actual["gross_yen"] == float(fixture["gross"])
    assert actual["fee_yen"] == fixture["fees"]
    assert actual["net_yen"] == float(fixture["net"])
    orders = result["orders"]
    assert len(orders) == len(fixture["fills"]) + 1
    assert orders[0, 0] == 1 and orders[0, 1] == 0 and orders[0, 6] == p.quantity
    assert orders[0, 10] == order_fee(p, p.quantity)
    assert orders[0, 3] == 0 and orders[0, 4] == -1
    checks = 10
    for order, (judgment, fill, fraction, gross_ticks) in zip(orders[1:], fixture["fills"]):
        q = int(p.quantity * fraction)
        assert order[0] == fill and order[1] == judgment
        assert order[3] == -1 and order[4] == 0
        assert order[5] == -fixture["side"] and order[6] == q
        assert order[10] == order_fee(p, q)
        assert abs(fixture["side"] * (order[7] - orders[0, 7]) / float(p.tick) - float(gross_ticks)) < 1e-9
        checks += 5
    assert np.all(result["orders"][:, 0] > result["orders"][:, 1])
    assert result["summary"]["収支"] == float(fixture["net"])
    assert result["summary"]["費用"] == fixture["fees"]
    assert sum(l["net_yen"] for l in result["actual_legs"]) == float(fixture["net"])
    assert result["final_state"]["cash_yen"] == float(fixture["net"])
    assert result["final_state"]["held_quantity"] == result["final_state"]["reserved_quantity"] == 0
    return checks + 6


def prefix_checks(engine, catalog, fixture: dict, original: dict, arrays: dict, signal: dict, policy: dict) -> int:
    """
    機能: 未来を切った未完了接頭が、先に作った注文と曲線を変更しないことを照合する。
    引数: engine/catalog(module)、fixture/original/arrays/signal/policy(dict)。
    返り値: int 配列照合数。
    """
    checks = 0
    for size in range(1, len(arrays["raw_seq"])):
        a = {k: v[:size].copy() for k, v in arrays.items()}
        s = {"fields": signal["fields"], "events": signal["events"][signal["events"][:, 2] < size].copy(), "price_valid_mask": signal["price_valid_mask"][:size].copy()}
        out = engine.simulate(a, s, fixture["symbol"], 0.0, 2000.0, float(product_of(fixture["symbol"]).tick), policy,
                              select_config(catalog, 2, fixture["mode"]), finish=False)
        for key in ("orders", "publication_events", "execution_events", "control_events"):
            np.testing.assert_equal(out[key], original[key][original[key][:, 0] < size])
            checks += 1
        np.testing.assert_equal(out["parents"], original["parents"][original["parents"][:, 4] < size])
        np.testing.assert_equal(out["curve"], original["curve"][:size])
        assert not out["completed"]
        checks += 3
    return checks


def edge_checks(engine, catalog) -> tuple[int, list[dict]]:
    """
    機能: 直後行取消・到着拡幅・予約競合・同当行再参加を具体的に照合する。
    引数: engine/catalog(module) 完成源。
    返り値: tuple[int,list[dict]] 確認数と限定した具体結果。
    """
    count = 0
    notes = []
    for symbol in ("TOPIX", "NK225"):
        p = product_of(symbol)
        for side in (1, -1):
            case = {"symbol": symbol, "side": side, "mode": 3, "ticks": [-1, -1, 2, -2, -3, -3]}
            a, s, t = materialize(symbol, side, case["ticks"])
            a["best_quantity_valid"][3] = False
            t["quiet_windows"] = np.array([[1003.0, 1005.0]])
            out = engine.simulate(a, s, symbol, 0.0, 2000.0, float(p.tick), t, select_config(catalog, 2, 3))
            expected = -3 * p.tick * p.quantity * p.multiplier - order_fee(p, p.quantity) - 2 * order_fee(p, p.quantity // 2)
            assert out["completed"] and len(out["parent"]) == 1
            assert out["parent"][0]["net_yen"] == float(expected)
            assert out["orders"][1:, 0].tolist() == [4.0, 4.0]
            assert out["orders"][1:, 1].tolist() == [2.0, 3.0]
            assert out["orders"][1:, 6].tolist() == [float(p.quantity // 2)] * 2
            assert out["orders"][1:, 9].tolist() == [143.0, 92.0]
            assert out["counts"]["holding_quantity_unknown_rows"] == 1
            count += 7
            notes.append({"商品": symbol, "方向": side, "半予約後の未知とquiet": float(expected), "約定原行": [4, 4], "判断原行": [2, 3]})

            # 公開済み新規の直後行だけが数量未知。次の正常行へ持越さない。
            for arrival_bad in ("quantity", "price", "seq", "quiet", "force"):
                a, s, t = materialize(symbol, side, [-1, -1, 2, 1, 0, 0])
                if arrival_bad == "quantity":
                    a["best_quantity_valid"][1] = False
                elif arrival_bad == "price":
                    s["price_valid_mask"][1] = False
                elif arrival_bad == "seq":
                    a["raw_seq"][1:] += 1
                elif arrival_bad == "quiet":
                    t["quiet_windows"] = np.array([[1001.0, 1002.0]])
                else:
                    a["price_time_s"][1:] = np.arange(len(a["raw_seq"]) - 1) + 1700.0
                out = engine.simulate(a, s, symbol, 0.0, 2000.0, float(p.tick), t, select_config(catalog, 0, 0))
                assert len(out["orders"]) == len(out["parents"]) == 0
                assert out["counts"]["accepted_reservations"] == 1
                assert out["counts"]["actual_entries"] == 0
                assert not out["final_state"]["pending_new"]
                count += 4

            # 公開幅2Tは拒否。1Tを受理後、到着幅5Tの新規は取消せず実損へ。
            a, s, t = materialize(symbol, side, [-1, -1, -3, -3, -3])
            a["ask"][0] = a["bid"][0] + 2 * float(p.tick)
            out = engine.simulate(a, s, symbol, 0.0, 2000.0, float(p.tick), t, select_config(catalog, 0, 0))
            assert out["counts"]["public_spread_rejections"] == 1 and not len(out["orders"])
            count += 1
            a, s, t = materialize(symbol, side, [-1, -1, -3, -3, -3])
            if side == 1:
                a["bid"][1] = float(p.base - p.tick)
                a["ask"][1] = float(p.base + 4 * p.tick)
            else:
                a["bid"][1] = float(p.base - 3 * p.tick)
                a["ask"][1] = float(p.base + 2 * p.tick)
            out = engine.simulate(a, s, symbol, 0.0, 2000.0, float(p.tick), t, select_config(catalog, 0, 0))
            assert len(out["orders"]) == 2
            assert out["orders"][0, 0] == 1 and out["orders"][1, 0] == 2 and out["orders"][1, 1] == 1
            assert out["orders"][1, 9] == 141
            assert out["counts"]["actual_entries"] == 1
            assert out["parent"][0]["net_yen"] < -2 * float(p.tick) * p.quantity * p.multiplier
            count += 5

            # entry_endは新規公開だけの締切。直前の受理は締切当行に約定可能。
            a, s, t = materialize(symbol, side, [-1, -1, 2, 1, 0, 0])
            a["price_time_s"][:2] = [1399.0, 1400.0]
            a["price_time_s"][2:-1] = np.arange(len(a["raw_seq"]) - 3) + 1401.0
            out = engine.simulate(a, s, symbol, 0.0, 2000.0, float(p.tick), t, select_config(catalog, 0, 0))
            assert out["orders"][0, 0] == 1 and out["counts"]["actual_entries"] == 1
            count += 1

            # 返済を終えた同row候補は新親予約可能、保有中の候補は消費のみ。
            a, s, t = materialize(symbol, side, [-1, -1, 2, 1, -1, -2, -3, -3])
            extra = s["events"][:1].copy()
            extra[0, 1:3] = [1, 3]
            s["events"] = np.vstack([s["events"], extra])
            out = engine.simulate(a, s, symbol, 0.0, 2000.0, float(p.tick), t, select_config(catalog, 0, 0))
            assert out["counts"]["actual_entries"] == 2
            assert out["orders"][out["orders"][:, 8] == 1, 0].tolist() == [1.0, 4.0]
            assert out["orders"][out["orders"][:, 8] == 1, 3].tolist() == [0.0, 1.0]
            assert [x["parent"] for x in out["parent"]] == [0, 1]
            count += 4
            s["events"][-1, 2] = 2
            out = engine.simulate(a, s, symbol, 0.0, 2000.0, float(p.tick), t, select_config(catalog, 0, 0))
            assert out["counts"]["actual_entries"] == 1 and out["counts"]["busy_rejections"] == 1
            count += 1

            # 接頭末尾の利確判断は約定へ昇格しない。
            a, s, t = materialize(symbol, side, [-1, -1, 2, 1, 0, 0])
            a = {k: v[:3].copy() for k, v in a.items()}
            s["price_valid_mask"] = s["price_valid_mask"][:3].copy()
            out = engine.simulate(a, s, symbol, 0.0, 2000.0, float(p.tick), t, select_config(catalog, 0, 0), finish=True)
            assert not out["completed"] and len(out["parents"]) == 0
            assert out["final_state"]["held_quantity"] == p.quantity and out["final_state"]["reserved_quantity"] == p.quantity
            assert len(out["orders"]) == 1
            count += 3
    return count, notes


def main() -> None:
    """
    機能: 完成三源への独立接続だけを実行し所有領域へ証跡を保存する。
    引数: なし。
    返り値: None。実データ・API・金融は実行しない。
    """
    proof = {"全合格": False, "source_SHA256": {}, "読取": {"原NPZ": 0, "保存114事象": 0, "金融結果": 0, "台帳": 0, "API": 0}, "範囲": "完成三源と純人工。正式八部品・登録・実入力への接続は未実施。"}
    output = HERE / "三入口四出口と次原行約定及び予約競合の独立SOURCE_ONLY接続.json"
    try:
        actual = {name: digest(SOURCE / name) for name in EXPECTED}
        proof["source_SHA256"] = actual
        assert actual == EXPECTED
        private = HERE / "完成三源の私有複製"
        private.mkdir(exist_ok=True)
        for name in EXPECTED:
            shutil.copyfile(SOURCE / name, private / name)
        sys.path.insert(0, str(private))
        engine = importlib.import_module("engine")
        catalog = importlib.import_module("catalog")
        assert Path(engine.__file__).resolve().parent == private and Path(catalog.__file__).resolve().parent == private
        assert len(catalog.configs()) == 12
        pure = pure_expectations()
        truth = reference_checks()
        checks = pure["独立確認数"] + truth["確認数"] + 3
        accounts = 0
        arrays_checked = 0
        rows = []
        for fixture in fixtures():
            for entry_mode in range(3):
                out, a, s, t = run_case(engine, catalog, fixture, entry_mode)
                checks += check_parent(out, fixture)
                accounts += 1
                if entry_mode == 2:
                    n = prefix_checks(engine, catalog, fixture, out, a, s, t)
                    checks += n
                    arrays_checked += n - (len(a["raw_seq"]) - 1)
                rows.append({"経路": fixture["name"], "入口": entry_mode, "期待収支": float(fixture["net"]), "実収支": out["summary"]["収支"]})
        n, notes = edge_checks(engine, catalog)
        checks += n
        # 出来高・将来先着を一切受け取らない数量条件の境界。
        for side in (1, -1):
            for mode in range(3):
                for typ in (0, 1):
                    for minimum in (9, 10, 11):
                        for same in (9, 10, 11):
                            a, s, t = materialize("TOPIX", side, [-1, -1, 2, 1, 0, 0])
                            b, ask = (same, 10) if side == 1 else (10, same)
                            s["events"] = np.array([[typ, 0, 0, side, 10, minimum, b, ask]], dtype=float)
                            out = engine.simulate(a, s, "TOPIX", 0.0, 2000.0, 0.5, t, select_config(catalog, mode, 0))
                            expected = event_eligible(mode, typ, side, Fraction(10), Fraction(minimum), Fraction(b), Fraction(ask))
                            assert (len(out["publication_events"]) == 1) == expected
                            checks += 1
        assert {name: digest(SOURCE / name) for name in EXPECTED} == actual
        proof.update(全合格=True, 確認数=checks, 先固定純会計確認数=pure["独立確認数"], 先固定純真偽確認数=truth["確認数"], 独立具体経路口座数=accounts,
                     接頭配列照合数=arrays_checked, 純経路会計=rows, 予約競合の具体結果=notes,
                     独立源_SHA256={p.name: digest(p) for p in (Path(__file__), HERE / "cash_reference.py", HERE / "execution_expectations.py")},
                     最終source一致=True, 金融有効性="未測定。純人工の合格を勝率又は新しい独立市場標本としない。")
    except BaseException:
        proof["失敗"] = traceback.format_exc()
        raise
    finally:
        output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({k: proof.get(k) for k in ("全合格", "確認数", "失敗")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
