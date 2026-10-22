"""10月22日デイの保存済みTOPIX注文を独立検算する。金融判断は再生しない。"""

from datetime import datetime
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
AUDITOR_PATH = ROOT / "work/update132_20261021/audit_selected132.py"
RESULT_PATH = HERE / "results/追加セッションの会計.json"
MANIFEST_PATH = HERE / "inputs/input_manifest.json"
OUTPUT_PATH = HERE / "audit/独立注文会計と約定明細.json"
SESSION = "2026-10-22_Day"


def load_auditor():
    """既存の独立会計検算モジュールを読み込む。

    引数: なし。
    返り値: ModuleType は00132の注文会計検算。売買再生処理は呼ばない。
    """
    spec = importlib.util.spec_from_file_location("audit_selected132_for_134", AUDITOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def order_details(orders: np.ndarray, independent: dict, auditor) -> list:
    """保存注文へ日本時刻と各返済の粗損益を付加する。

    引数: orders (ndarray) は検算済み注文、independent (dict) は独立親会計、auditor (ModuleType) は検算補助。
    返り値: list[dict] は全注文明細。新規時には料金だけを累計へ反映する。
    """
    parents = {parent["parent_id"]: parent for parent in independent["parents"]}
    details = []
    net = Decimal(0)
    holdings = {1: 0, -1: 0}
    for order in orders:
        parent_id, side, quantity, opening = (int(order[column]) for column in (2, 3, 4, 7))
        parent = parents[parent_id]
        price = auditor.decimal(order[5])
        fee = auditor.decimal(order[8])
        move = Decimal(0) if opening else (price - auditor.decimal(parent["entry_price"])) * parent["side"]
        gross = move * quantity * 1000
        net += gross - fee
        holdings[parent["side"]] += quantity if opening else -quantity
        details.append({
            "parent_id": parent_id,
            "component": "主担当" if parent_id < 1000000 else "未参加補完",
            "decision_time": datetime.fromtimestamp(float(order[10]), auditor.JST).isoformat(),
            "time": datetime.fromtimestamp(float(order[9]), auditor.JST).isoformat(),
            "action": "新規" if opening else "返済",
            "opening": bool(opening),
            "side": side,
            "side_label": "買い" if side > 0 else "売り",
            "quantity": quantity,
            "price": float(price),
            "entry_price": parent["entry_price"],
            "move_per_contract_pt": None if opening else float(move),
            "gross_pnl": float(gross),
            "fee": float(fee),
            "cumulative_realized_net": float(net),
            "long_quantity_after": holdings[1],
            "short_quantity_after": holdings[-1],
            "reason_code": int(order[6]),
            "source_index": int(order[1]),
            "fill_index": int(order[0]),
        })
    auditor.equal(float(net), independent["net"], "明細の最終累計収支")
    auditor.equal(sum(detail["gross_pnl"] for detail in details), independent["gross"], "明細の返済粗損益合計")
    auditor.equal(sum(detail["fee"] for detail in details), independent["fees"], "明細の全注文料金")
    assert holdings == {1: 0, -1: 0}, "明細末尾に未返済あり"
    return details


def main() -> None:
    """完成した一商品場の注文・数量・料金・次原行気配を検算して新規JSONへ保存する。

    引数: なし。固定された当作業の結果と入力目録を読み込む。
    返り値: None。未完成結果、不一致、既存出力は拒否する。
    """
    auditor = load_auditor()
    result = auditor.read(RESULT_PATH)
    manifest = auditor.read(MANIFEST_PATH)
    assert result["passed"] is True
    assert result["input_manifest"] == auditor.fingerprint(MANIFEST_PATH)
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert (row["session"], row["symbol"], row["kind"]) == (SESSION, "TOPIX", "Day")
    assert row["method"] == "T06" and row["core_method"] == "DV07"

    # ----------------------------------------
    # 保存結果の参照と実ファイルの指紋が同一であることを先に確認する。
    packet_ref = next(item for item in manifest["packets"] if item["session"] == SESSION)
    assert packet_ref == next(item for item in result["input_packets"] if item["session"] == SESSION)
    packet_path = ROOT / packet_ref["path"]
    assert auditor.fingerprint(packet_path)["sha256"] == packet_ref["sha256"]
    packet = pickle.loads(packet_path.read_bytes())
    cache = next(item for item in result["cache"] if (item["session"], item["symbol"]) == (SESSION, "TOPIX"))
    cache_path = ROOT / cache["path"]
    assert auditor.fingerprint(cache_path)["sha256"] == cache["sha256"]
    with np.load(cache_path, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}

    # ----------------------------------------
    # 注文会計を独立に再構成し、保存された集計・親取引・枚数曲線と照合する。
    independent = auditor.audit_measurement(row, arrays, packet)
    details = order_details(arrays["orders"], independent, auditor)
    output = {
        "passed": True,
        "session": SESSION,
        "symbol": "TOPIX",
        "product": "TOPIXmini",
        "max_per_side": 10,
        "account": independent,
        "summary": {key: value for key, value in independent.items() if key not in ("parents", "next_row_checks")},
        "parents": independent["parents"],
        "orders": details,
        "next_row_checks": independent["next_row_checks"],
        "source": auditor.fingerprint(RESULT_PATH),
        "manifest": auditor.fingerprint(MANIFEST_PATH),
        "packet": auditor.fingerprint(packet_path),
        "cache": auditor.fingerprint(cache_path),
        "auditor": auditor.fingerprint(Path(__file__)),
        "independent_accounting_source": auditor.fingerprint(AUDITOR_PATH),
        "financial_replays": 0,
        "API": 0,
        "real_orders": 0,
        "notes": [
            "利益・損失は親取引の手数料後損益を正負別集計。",
            "各返済のgross_pnlは新規価格との差額×枚数×1000円。新規料金の返済別按分は行わない。",
            "decision_timeとtimeは日本時間の原データ価格時計。同時刻でも別原行の場合がある。",
            "ラージ気配による代理約定。TOPIXminiの実気配・実受信時刻・実注文を再現するものではない。",
        ],
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("x", encoding="utf-8") as target:
        json.dump(output, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write("\n")
    print(json.dumps({"passed": True, "summary": output["summary"], "output": str(OUTPUT_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
