"""同時刻・同枚数の事後逆売買を、保存された反対側BBOだけで参考計算する。"""

from __future__ import annotations

from collections import defaultdict
import hashlib
from io import BytesIO
import json
from pathlib import Path
import statistics

import numpy as np


HERE = Path(__file__).resolve().parent
OWNER = HERE.parent
ROOT = HERE.parents[2]
RESULT = OWNER / "十二条件と二商品全四十一場の会計.json"
RESULT_SHA = "2ef627501c50359baadc6bbfa343d372c882f2b0f39fdbb1de8019fb02fdf19b"
CHECKS = 0
READS = {"完成小結果": 0, "125保存入力": 0, "125結果NPZ": 0, "原市場": 0, "旧cache": 0, "金融再実行": 0}


def check(condition: bool, note: str) -> None:
    """
    機能: 同時刻の反対BBO再会計と独立恒等式の一致を検査する。
    引数: condition (bool) 条件、note (str) 検査名。
    返り値: None。
    """
    global CHECKS
    assert bool(condition), note
    CHECKS += 1


def near(left: float, right: float, note: str) -> None:
    """
    機能: 計算経路の異なる有限損益を比較する。
    引数: left/right (float) 比較値、note (str) 検査名。
    返り値: None。
    """
    check(abs(left - right) <= 1e-5 + 1e-11 * max(abs(left), abs(right)), note)


def load(info: dict, kind: str, keys: list[str]) -> dict:
    """
    機能: 指定された125保存NPZを各一回だけ読み必要配列を展開する。
    引数: info (dict) path/sha256、kind (str) 入力区分、keys (list[str]) 必要列。
    返り値: dict 同一性確認済みの配列。
    """
    path = (ROOT / info["path"]).resolve()
    expected = OWNER / ("prepared" if kind == "125保存入力" else "measurement")
    check(path.is_relative_to(expected), "125所有保存だけを参照")
    stat = path.stat()
    payload = path.read_bytes()
    READS[kind] += 1
    check(hashlib.sha256(payload).hexdigest() == info["sha256"] and (stat.st_size, stat.st_mtime_ns) == (path.stat().st_size, path.stat().st_mtime_ns), "保存NPZの同一性")
    with np.load(BytesIO(payload), allow_pickle=False) as archive:
        return {key: archive[key].copy() for key in keys}


def main() -> None:
    """
    機能: 全12条件・両商品41場について固定時刻逆売買の参考と気配差分解を保存する。
    引数: なし。
    返り値: None。未来の出口時刻を借りた事後参考であり、戦略選択・金融再生・新成功標本ではない。
    """
    raw = RESULT.read_bytes()
    READS["完成小結果"] += 1
    check(hashlib.sha256(raw).hexdigest() == RESULT_SHA, "正式完成結果の固定SHA")
    result = json.loads(raw)
    manifest_path = OWNER / "保存済み気配と先行確定足の八十二入力.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    source_inputs = {(item["session"], item["symbol"]): item for item in manifest["inputs"]}
    lookup = {(row["session"], row["symbol"], row["method"]): row for row in result["rows"]}
    check(len(lookup) == 984 and len(result["cache"]) == 82 and len(source_inputs) == 82, "新対象984会計と82保存対")
    oi = {name: i for i, name in enumerate(result["order_columns"])}
    ti = {name: i for i, name in enumerate(result["trade_columns"])}
    all_rows = []
    group_rows = []
    for info in result["cache"]:
        scene, symbol = info["session"], info["symbol"]
        multiplier, cap = (1000., 10) if symbol == "TOPIX" else (10., 20)
        q = load(source_inputs[scene, symbol], "125保存入力", ["row", "time", "last", "bid", "ask"])
        arrays = load(info, "125結果NPZ", [spec["id"] + "__" + kind for spec in result["specs"] for kind in ("orders", "trades")])
        for spec in result["specs"]:
            method = spec["id"]
            original = lookup[scene, symbol, method]
            orders, trades = arrays[method + "__orders"], arrays[method + "__trades"]
            by_group = defaultdict(list)
            for entry in orders[orders[:, oi["kind"]] == 1]:
                by_group[int(entry[oi["group_id"]])].append(entry)
            parts = []
            for trade in trades:
                gid = int(trade[ti["group_id"]])
                entries = by_group[gid]
                side = int(trade[ti["side"]])
                quantity = int(trade[ti["quantity"]])
                reference = int(trade[ti["reference_row"]])
                exit_index = int(np.searchsorted(q["row"], reference))
                check(exit_index < len(q["row"]) and int(q["row"][exit_index]) == reference, "通常/代理の返済参照原row実在")
                exit_bid, exit_ask = q["bid"][exit_index], q["ask"][exit_index]
                opposite_exit = exit_ask if side == 1 else exit_bid
                original_exit = exit_bid if side == 1 else exit_ask
                near(original_exit, trade[ti["exit_price"]], "元退出BBOを保持")
                opposite_entry_basis = original_entry_basis = mid_entry_basis = entry_spreads = 0.
                total_quantity = 0
                for entry in entries:
                    fill_row = int(entry[oi["fill_row"]])
                    fill_index = int(np.searchsorted(q["row"], fill_row))
                    check(fill_index < len(q["row"]) and int(q["row"][fill_index]) == fill_row, "新規参照原row実在")
                    amount = int(entry[oi["quantity"]])
                    total_quantity += amount
                    bid, ask = q["bid"][fill_index], q["ask"][fill_index]
                    original_entry = ask if side == 1 else bid
                    opposite_entry = bid if side == 1 else ask
                    near(original_entry, entry[oi["price"]], "元新規BBOを保持")
                    check(entry[oi["fee"]] == 0, "元新規料金0")
                    opposite_entry_basis += opposite_entry * amount
                    original_entry_basis += original_entry * amount
                    mid_entry_basis += (bid + ask) / 2 * amount
                    entry_spreads += (ask - bid) * amount * multiplier
                check(total_quantity == quantity, "追加を含む同枚数と群完了を保持")
                check(trade[ti["entry_fees"]] == trade[ti["exit_fee"]] == 0, "元群両道料金0")
                opposite_net = -side * (opposite_exit * quantity - opposite_entry_basis) * multiplier
                original_gross = side * (original_exit * quantity - original_entry_basis) * multiplier
                exit_spreads = (exit_ask - exit_bid) * quantity * multiplier
                mid_directional = side * ((exit_bid + exit_ask) / 2 * quantity - mid_entry_basis) * multiplier
                spread_total = entry_spreads + exit_spreads
                near(original_gross, trade[ti["gross"]], "元粗損益の独立値")
                near(original_gross, trade[ti["net"]], "元料金なし純損益")
                near(opposite_net, -original_gross - spread_total, "逆売買と元損益・全気配差の恒等式")
                near(original_gross, mid_directional - spread_total / 2, "元方向の中値移動と半気配差")
                near(opposite_net, -mid_directional - spread_total / 2, "逆方向の中値移動と半気配差")
                part = {"session": scene, "symbol": symbol, "method": method, "group_id": gid, "original_side": side, "reverse_side": -side, "quantity": quantity, "entry_orders": len(entries), "first_entry_time": float(trade[ti["first_entry_time"]]), "exit_time": float(trade[ti["exit_time"]]), "exit_reference_row": reference, "proxy_flag": bool(trade[ti["proxy_flag"]]), "entry_reason": int(trade[ti["entry_reason"]]), "original_net": float(original_gross), "reverse_reference_net": float(opposite_net), "mid_directional_gross": float(mid_directional), "entry_full_spread_penalty": float(entry_spreads), "exit_full_spread_penalty": float(exit_spreads), "total_full_spread_penalty": float(spread_total), "spread_drag_each_direction": float(spread_total / 2)}
                parts.append(part)
                group_rows.append(part)
            original_net = sum(row["original_net"] for row in parts)
            reversed_net = sum(row["reverse_reference_net"] for row in parts)
            spread = sum(row["total_full_spread_penalty"] for row in parts)
            near(original_net, original["net"], "各場元損益一致")
            near(reversed_net, -original_net - spread, "各場固定反転の恒等式")
            capacity = original["rate_components"]["capacity_notional"]
            near(capacity, q["last"][0] * cap * multiplier, "価格比の固定容量元本")
            all_rows.append({"session": scene, "symbol": symbol, "method": method, "groups": len(parts), "entry_orders": original["entry_orders"], "entry_quantity": original["entry_quantity"], "original_net": original_net, "reverse_reference_net": reversed_net, "reverse_reference_profit": sum(max(0., row["reverse_reference_net"]) for row in parts), "reverse_reference_loss": sum(max(0., -row["reverse_reference_net"]) for row in parts), "reverse_positive_groups": sum(row["reverse_reference_net"] > 0 for row in parts), "reverse_negative_groups": sum(row["reverse_reference_net"] < 0 for row in parts), "mid_directional_gross": sum(row["mid_directional_gross"] for row in parts), "entry_full_spread_penalty": sum(row["entry_full_spread_penalty"] for row in parts), "exit_full_spread_penalty": sum(row["exit_full_spread_penalty"] for row in parts), "total_full_spread_penalty": spread, "spread_drag_each_direction": spread / 2, "reference_price": float(q["last"][0]), "capacity_notional": capacity, "original_price_ratio_percent": original_net / capacity * 100, "reverse_reference_price_ratio_percent": reversed_net / capacity * 100, "original_capacity_equivalent_points": original_net / (cap * multiplier), "reverse_capacity_equivalent_points": reversed_net / (cap * multiplier)})
        print(scene, symbol, "固定時刻の参考十二会計", flush=True)
    # ----------------------------------------
    totals = []
    for spec in result["specs"]:
        for symbol in ("TOPIX", "NK225"):
            rows = [row for row in all_rows if row["method"] == spec["id"] and row["symbol"] == symbol]
            check(len(rows) == 41, "各条件各商品41場")
            reverse_values = [row["reverse_reference_net"] for row in rows]
            totals.append({"method": spec["id"], "symbol": symbol, "sessions": 41, "activity": sum(row["entry_orders"] > 0 for row in rows), "original_net": sum(row["original_net"] for row in rows), "reverse_reference_net": sum(reverse_values), "reverse_black": sum(value > 0 for value in reverse_values), "reverse_red": sum(value < 0 for value in reverse_values), "reverse_zero": sum(value == 0 for value in reverse_values), "reverse_mean_session_net": statistics.mean(reverse_values), "reverse_median_session_net": statistics.median(reverse_values), "original_mean_price_ratio_percent": statistics.mean(row["original_price_ratio_percent"] for row in rows), "reverse_reference_mean_price_ratio_percent": statistics.mean(row["reverse_reference_price_ratio_percent"] for row in rows), "reverse_reference_median_price_ratio_percent": statistics.median(row["reverse_reference_price_ratio_percent"] for row in rows), "mid_directional_gross": sum(row["mid_directional_gross"] for row in rows), "total_full_spread_penalty": sum(row["total_full_spread_penalty"] for row in rows), "entry_full_spread_penalty": sum(row["entry_full_spread_penalty"] for row in rows), "exit_full_spread_penalty": sum(row["exit_full_spread_penalty"] for row in rows), "spread_drag_each_direction": sum(row["spread_drag_each_direction"] for row in rows), "groups": sum(row["groups"] for row in rows)})
    both = [spec["id"] for spec in result["specs"] if all(row["reverse_reference_net"] > 0 for row in totals if row["method"] == spec["id"])]
    check(len(all_rows) == 984 and READS == {"完成小結果": 1, "125保存入力": 82, "125結果NPZ": 82, "原市場": 0, "旧cache": 0, "金融再実行": 0}, "984参考行と所有入力出力の各一読")
    proof = {"passed": True, "source_result": {"path": RESULT.relative_to(ROOT).as_posix(), "sha256": RESULT_SHA}, "source_manifest": {"path": manifest_path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(manifest_raw).hexdigest()}, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "purpose": "価格方向の逆効果と気配差負けを分離する事後対照。", "repeat_reason": "00116は小幅・料金ありで全赤だった元対象。今回は00125の中幅・純方向・料金0・追加を含む新対象に対する保存算術であり、旧116金融を再実行しない。", "definition": "元の全エントリー/追加/退出時刻・枚数・群完了を借り、買売だけ逆にして反対BBOを採用。通常返済と六分窓代理の区分も元のまま。", "identity": "reverse_net = -original_gross - entry_full_spread_penalty - exit_full_spread_penalty。元/逆はそれぞれ ±mid_directional_gross - total_full_spread_penalty/2。fee=0。", "ratio_definition": "各場net÷(場初保存Last×片方向上限枚数×商品倍率)×100。41場の平均は各場比率の単純平均で、価格自体0.5%目標と比較するための固定容量換算。", "totals": totals, "rows": all_rows, "groups": group_rows, "両商品で参考合計が黒字のmethod": both, "checks": CHECKS, "reads": READS, "financial_replays": 0, "original_market_reads": 0, "new_success_samples": 0, "strategy_goal_achieved": None, "limitation": "元方向を基に決まった未来の退出時刻と追加数量を借りた事後参考。逆方向に実行すれば初期損切り・追尾・追加・持替え・後続入口が変わるため、実行可能な反転戦略の成績や新しい金融成功標本と呼ばない。参考が黒字でも収益性の証明ではない。"}
    target = HERE / "同時刻同枚数の逆売買参考会計と気配差分解.json"
    check(not target.exists(), "元結果と参考結果を上書きしない")
    payload = (json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    target.write_bytes(payload)
    print(json.dumps({"path": target.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(payload).hexdigest(), "both": both, "totals": totals}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
