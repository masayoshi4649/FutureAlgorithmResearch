"""第三巡の保存約定だけから、比較差と利益の帰属を診断する。金融再生なし。"""

from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import json

BASE = Path(__file__).resolve().parents[1]


def read(path: Path) -> dict:
    """UTF-8保存値を読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def pairs(a: dict, b: dict) -> dict:
    """同じ場同士の純差と、改善上位場を除外した差を計算する。

    引数: a/b(dict)は候補/対照の手法。返り値: dict。
    """
    base = {r["session"]: r for r in b["rows"]}
    rows = [{"session": r["session"], "candidate": r["net"], "control": base[r["session"]]["net"], "difference": r["net"] - base[r["session"]]["net"]} for r in a["rows"]]
    best = sorted(rows, key=lambda r: r["difference"], reverse=True)[:3]
    diff = sum(r["difference"] for r in rows)
    base_best = {r["session"] for r in sorted(b["rows"], key=lambda r: r["net"], reverse=True)[:3]}
    return {"candidate": a["id"], "control": b["id"], "net_difference": diff, "better": sum(r["difference"] > 0 for r in rows), "worse": sum(r["difference"] < 0 for r in rows), "equal": sum(r["difference"] == 0 for r in rows), "difference_without_best_three_improvements": diff - sum(r["difference"] for r in best), "best_three_improvements": best, "new_negative_sessions": [r for r in rows if r["control"] >= 0 and r["candidate"] < 0], "rescued_negative_sessions": [r for r in rows if r["control"] < 0 and r["candidate"] >= 0], "same_control_best_three_removed": {"sessions": sorted(base_best), "candidate": sum(r["candidate"] for r in rows if r["session"] not in base_best), "control": sum(r["control"] for r in rows if r["session"] not in base_best)}, "rows": rows}


def jst(at: float) -> str:
    """保存秒を日本時間へ変換する。

    引数: at(float)。返り値: str。
    """
    return datetime.fromtimestamp(at, timezone(timedelta(hours=9))).isoformat()


def main() -> None:
    """比較差、役割別の中値移動とBBO差を保存約定から恒等分解する。

    引数: なし。返り値: None。
    """
    report = read(BASE / "report1573.json")
    methods = {m["id"]: m for m in report["methods"]}
    c00 = next(m for m in read(BASE.parent / "report157.json")["methods"] if m["id"] == "C00")
    comparisons = [pairs(methods[a], methods[b]) for a, b in (("O01", "O00"), ("O02", "O01"), ("O03", "O02"), ("O04", "O03"), ("O05", "O03"), ("O06", "O03"), ("O07", "O05"), ("O08", "O05"), ("O09", "O05"), ("O10", "O03"), ("O11", "O05"))]
    comparisons += [pairs(methods[i], c00) for i in ("O00", "O01", "O05")]
    roles = defaultdict(lambda: defaultdict(float))
    trails = []
    source_exits = defaultdict(int)
    for path in sorted((BASE / "results_go").glob("*.json")):
        saved = read(path)
        if saved["scene"]["partial"]:
            continue
        session = saved["scene"]["session"]
        for case in saved["cases"]:
            identifier = case["config"]["id"]
            ledger = case["canonical"]
            firsts = {}
            for event in ledger["Events"] or []:
                order = event["Order"]
                if not order["Targets"]:
                    firsts[event["HoldID"]] = event
                    key = identifier + "/" + order["Kind"]
                    roles[key]["entries"] += 1
                    roles[key]["quantity"] += order["Quantity"]
                    continue
                for piece in event["Pieces"]:
                    entry = firsts[piece["ID"]]
                    key = identifier + "/" + entry["Order"]["Kind"]
                    quantity = piece["Quantity"]
                    side = entry["Order"]["Side"]
                    entry_mid = (entry["Bid"] + entry["Ask"]) / 2
                    exit_mid = (event["Bid"] + event["Ask"]) / 2
                    move = side * (exit_mid - entry_mid) * quantity * 10
                    spread = ((entry["Ask"] - entry["Bid"]) + (event["Ask"] - event["Bid"])) / 2 * quantity * 10
                    assert abs(move - spread - piece["Gross"]) < 1e-6
                    roles[key]["mid_move_yen"] += move
                    roles[key]["bbo_spread_yen"] += spread
                    roles[key]["realized_yen"] += piece["Gross"]
                    if piece["Best"] < 40:
                        roles[key]["quantity_never_40pt"] += quantity
                    if piece["Best"] <= 0:
                        roles[key]["quantity_never_positive"] += quantity
                    if order["Reason"] == "cover_trail":
                        trails.append({"id": identifier, "session": session, "parent": order["Parent"], "entry_time": jst(entry["FillTime"]), "decision_time": jst(order["DecisionTime"]), "fill_time": jst(event["FillTime"]), "side": side, "quantity": quantity, "entry_price": entry["Price"], "exit_price": event["Price"], "gross": piece["Gross"], "maximum_gain_pt": piece["Best"]})
                    if order["Reason"] == "長短支持崩壊":
                        source_exits[identifier + "/collapse_orders"] += 1
            for key, entry in firsts.items():
                lot = ledger["Lots"][key]
                role = identifier + "/" + lot["Kind"]
                if lot["Best"] < 40:
                    roles[role]["lots_never_40pt"] += 1
                if lot["Best"] <= 0:
                    roles[role]["lots_never_positive"] += 1
                assert lot["Remaining"] == 0
    out = {"financial_replays": 0, "completed_sessions": 26, "comparisons": comparisons, "canonical_role_identity": dict(roles), "cover_trails": trails, "collapse_close_counts": dict(source_exits)}
    (BASE / "audit/保存結果の差分診断1573.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"comparisons": len(comparisons), "role_groups": len(roles), "trail_pieces": len(trails)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
