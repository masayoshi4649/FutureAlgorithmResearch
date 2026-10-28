"""00156の保存実約定を、初回・同親追撃・別担当へ分けて再会計する。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "work/s01_156"
OUT = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
NAMES = {"core": "主担当", "addon": "追加担当", "episode": "別入口担当"}


def stamp(value: float) -> str:
    """価格時計の秒を日本時間へ表示変換する。

    引数: value(float)はUNIX秒。返り値: strは日本時間の時分秒。
    """
    return datetime.fromtimestamp(value, JST).strftime("%H:%M:%S")


def load(path: Path) -> dict:
    """UTF-8の保存結果を読み、計算へ渡す。

    引数: path(Path)は読取先。返り値: dictは元内容。原資料は変更しない。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def account(case: dict, moment: dict | None = None) -> dict:
    """保存約定だけをHoldID別に配賦し、指定断面の寄与を算出する。

    引数: case(dict)は保存ケース、moment(dict|None)は当時の原行・気配。
    返り値: dictは玉・担当・初回追加分類ごとの確定、含み、時価。
    同親の後続新規と、別担当が独立して開始する初回を区別する。
    """
    lots, seen, parent_quantity = {}, set(), defaultdict(int)
    point = 100.0
    for number, event in enumerate(case["events"]):
        if moment is not None:
            index, phase = moment["index"], moment["phase"]
            if event["fill_index"] > index:
                break
            if event["fill_index"] == index:
                if not phase.startswith("約定後:") or number > int(phase.split(":")[1]):
                    break
        signal, fill = event["signal"], event["fill"]
        parent = f'{signal["owner"]}/{signal["campaign"]}'
        if signal["action"] == "new":
            kind = ("初回" if parent not in seen else
                    "同親追加" if parent_quantity[parent] > 0 else "同親再新規")
            obs = case["decision_evidence"][signal["id"]]
            evidence = signal.get("evidence") or {}
            initial_state = {
                "decision_time": signal["time"], "decision_at": stamp(signal["time"]),
                "decision_index": event["decision_index"], "bid": obs["Bid"], "ask": obs["Ask"],
                "fixed_r": evidence.get("fixed_r"), "signal_risk": signal.get("risk"),
                "parent_quantity_before": parent_quantity[parent],
                "total_quantity_before": sum(x["remaining"] for x in lots.values()),
                "net_quantity_before": sum(x["side"] * x["remaining"] for x in lots.values()),
                "realized_before": sum(x["realized"] for x in lots.values()),
                "mid_market": obs.get("MidMarket"), "e01": obs.get("E01"),
            }
            lots[fill["HoldID"]] = {
                "id": fill["HoldID"], "parent": parent, "owner": signal["owner"],
                "owner_name": NAMES[signal["owner"]], "kind": kind, "side": signal["side"],
                "initial_quantity_mini": fill["Quantity"], "remaining": fill["Quantity"],
                "entry_price": fill["Price"], "entry_time": fill["Time"], "entry_at": stamp(fill["Time"]),
                "entry_index": event["fill_index"], "entry_reason_code": signal["reason_code"],
                "known_at_decision": initial_state, "realized": 0.0, "closes": [],
            }
            seen.add(parent)
            parent_quantity[parent] += fill["Quantity"]
        else:
            allocated = 0.0
            for target in fill["Closed"]:
                lot = lots[target["id"]]
                q = target["quantity"]
                assert 0 < q <= lot["remaining"]
                gross = lot["side"] * q * (fill["Price"] - lot["entry_price"]) * point
                lot["remaining"] -= q
                lot["realized"] += gross
                parent_quantity[lot["parent"]] -= q
                lot["closes"].append({"time": fill["Time"], "at": stamp(fill["Time"]),
                                      "index": event["fill_index"], "quantity": q,
                                      "price": fill["Price"], "gross": gross,
                                      "reason_code": signal["reason_code"]})
                allocated += gross
            assert abs(allocated - event["gross"]) < 1e-6
    groups, parents = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
    for lot in lots.values():
        mark = (moment["bid"] if lot["side"] == 1 else moment["ask"]) if moment else lot["entry_price"]
        assert moment or lot["remaining"] == 0
        lot["unrealized"] = lot["side"] * lot["remaining"] * (mark - lot["entry_price"]) * point
        lot["equity"] = lot["realized"] + lot["unrealized"]
        for group in (groups[f'{lot["owner"]}/{lot["kind"]}'], parents[lot["parent"]]):
            for key in ("realized", "unrealized", "equity", "remaining"):
                group[key] += lot[key]
            group["entries"] += 1
            group["entry_quantity_mini"] += lot["initial_quantity_mini"]
    total = {key: sum(x[key] for x in lots.values()) for key in ("realized", "unrealized", "equity")}
    if moment:
        for key in total:
            assert abs(total[key] - moment[key]) < 1e-6, (key, total, moment)
    else:
        assert abs(total["realized"] - case["Gross"]) < 1e-6
    return {"moment": moment, "total": total, "groups": dict(groups), "parents": dict(parents),
            "lots": list(lots.values())}


def main() -> None:
    """全26完了場と2具体場を再配賦し、次研究の対照指標を保存する。

    引数: なし。返り値: None。新規の売買判断・金融再生・API取得は行わない。
    """
    report = load(SOURCE / "report156_all.json")
    method = next(x for x in report["methods"] if x["id"] == "S01")
    fingerprints = []
    sessions, totals = [], defaultdict(lambda: defaultdict(float))
    details = {}
    for row in method["rows"]:
        path = SOURCE / "results_go" / f'{row["session"]}_S01.json'
        fingerprints.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        case = next(x for x in load(path)["cases"] if x["config"]["id"] == "S01")
        final = account(case)
        assert final["total"]["realized"] == row["net"]
        for key, group in final["groups"].items():
            for field, value in group.items():
                totals[key][field] += value
        sessions.append({"session": row["session"], "net": row["net"], "groups": final["groups"]})
        if row["session"] in ("2026-10-20_Day", "2026-10-21_Day"):
            risk = row["intraday_risk"]
            selected = {key: account(case, risk[key]) for key in
                        ("min_equity_at", "drawdown_peak", "drawdown_trough")}
            before, after = selected["drawdown_peak"], selected["drawdown_trough"]
            deltas = {}
            for key in before["groups"].keys() | after["groups"].keys():
                deltas[key] = after["groups"].get(key, {}).get("equity", 0) - before["groups"].get(key, {}).get("equity", 0)
            assert sum(deltas.values()) == -risk["max_drawdown"]
            parent_deltas = {key: after["parents"].get(key, {}).get("equity", 0) - before["parents"].get(key, {}).get("equity", 0)
                             for key in before["parents"].keys() | after["parents"].keys()}
            selected["drawdown_contribution"] = {"groups": deltas, "parents": parent_deltas}
            selected["final"] = final
            details[row["session"]] = selected
    scalings = []
    for alpha in (1.0, 0.5, 0.2, 0.1):
        scalings.append({"scale": alpha, "cap_micro": int(100 * alpha),
                         "core_first_micro": int(50 * alpha),
                         "profit": method["summary"]["profit"] * alpha,
                         "loss": method["summary"]["loss"] * alpha,
                         "net": method["summary"]["net"] * alpha,
                         "min_equity": min(r["intraday_risk"]["min_equity"] for r in method["rows"]) * alpha,
                         "max_drawdown": max(r["intraday_risk"]["max_drawdown"] for r in method["rows"]) * alpha,
                         "red_sessions": sum(r["net"] < 0 for r in method["rows"]),
                         "rows": [{"session": r["session"], "profit": r["profit"] * alpha,
                                   "loss": r["loss"] * alpha, "net": r["net"] * alpha,
                                   "min_equity": r["intraday_risk"]["min_equity"] * alpha,
                                   "max_drawdown": r["intraday_risk"]["max_drawdown"] * alpha,
                                   "min_realized": r["intraday_risk"]["min_realized"] * alpha,
                                   "min_equity_at": r["intraday_risk"]["min_equity_at"]["at"],
                                   "drawdown_peak_at": r["intraday_risk"]["drawdown_peak"]["at"],
                                   "drawdown_trough_at": r["intraday_risk"]["drawdown_trough"]["at"]}
                                  for r in method["rows"]],
                         "note": "同じ約定日時・価格・部分返済割合を固定した算術比例。新手法の再生ではない。"})
    frozen = {str(SOURCE / n): hashlib.sha256((SOURCE / n).read_bytes()).hexdigest()
              for n in ("report156_all.json", "場内リスク156.json")}
    result = {"purpose": "00157の数量配分研究に使う既存S01場内赤字の寄与", "method": "S01",
              "complete_sessions": len(sessions), "point_yen": 100, "source_product": "NK225mini",
              "target_equivalent": "NK225micro 10円/pt・片側100枚はmini 10枚と同じ最大名目曝露",
              "new_financial_replays": 0, "fees": 0, "input_fingerprints": fingerprints,
              "frozen_source_sha256": frozen, "groups_all_sessions": dict(totals),
              "session_groups": sessions, "details": details, "pure_scalings": scalings,
              "interpretation": [
                  "追加担当addonの初回2枚と、同じ親の後続1枚追加は異なる。担当名で追撃と決めない。",
                  "初回の大小は元の5/3/2担当配分であり、当時の確信度を表す事実ではない。",
                  "極値の時刻選択は事後診断。known_at_decisionだけを当時の観測値として分離。",
                  "極値における寄与はその玉を消した戦略の改善額ではない。出口・後続入口は再判定していない。",
                  "一律減枚は金額を比例縮小するが赤字場数と同経路の利益損失比を変えない。",
                  "固定1micro開始は現50microの1/50。全担当を1/50へ縮めると0.4/0.2microを要し実行不能。"
              ]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "比較元の場内赤字.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"complete_sessions": len(sessions), "sum_net": sum(r["net"] for r in sessions),
                      "groups": dict(totals),
                      "scaled": [{k: v for k, v in x.items() if k not in ("rows", "note")} for x in scalings]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
