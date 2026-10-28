"""保存済み約定だけを読む00156の具体診断。原板再生・戦略実行・金融条件追加は行わない。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
PROTECTIVE = {15601, 15602}
ENTRY_PAIRS = {
    "E01": "S01", "E04": "S01", "E07": "S01",
    "E02": "F05", "E05": "F05", "E08": "F05",
    "E03": "F09", "E06": "F09", "E09": "F09",
}


def clock(value: float) -> str:
    """UNIX秒を日本時間表示へ変える。

    引数: value(float)。返り値: str は年月日付き秒表示。
    """
    return datetime.fromtimestamp(value, JST).isoformat(timespec="seconds")


def event_record(case: dict, event: dict) -> dict:
    """判断と実約定を分けた小型の証跡を作る。

    引数: case(dict)、event(dict)。返り値: dict は当時の記録だけ。
    """
    sig, fill = event["signal"], event["fill"]
    obs = case["decision_evidence"][sig["id"]]
    evidence = sig.get("evidence") or {}
    return {
        "signal_id": sig["id"], "owner": sig["owner"],
        "campaign": sig["campaign"], "action": sig["action"],
        "side": sig["side"], "quantity": fill["Quantity"],
        "decision_time": sig["time"], "decision_jst": clock(sig["time"]),
        "decision_index": event["decision_index"],
        "decision_bid": obs["Bid"], "decision_ask": obs["Ask"],
        "fill_time": fill["Time"], "fill_jst": clock(fill["Time"]),
        "fill_index": event["fill_index"], "fill_price": fill["Price"],
        "reason": sig["reason"], "reason_code": sig["reason_code"],
        "gross": event["gross"], "targets": fill.get("Closed"),
        "parent_cash_at_decision": evidence.get("strategy_cash"),
        "parent_budget_at_decision": evidence.get("profit_budget"),
    }


def parent_record(case: dict, owner: str, campaign: int) -> dict | None:
    """担当と仮想親に対応する実玉・返済の小型証跡を作る。

    引数: case(dict)、owner(str)、campaign(int)。返り値: dict又はNone。
    """
    parent = (case["parents"] or {}).get(f"{owner}/{campaign}")
    if parent is None:
        return None
    events = [e for e in (case["events"] or [])
              if e["signal"]["owner"] == owner and e["signal"]["campaign"] == campaign]
    entries = [e for e in events if e["signal"]["action"] == "new"]
    assert entries, (case["config"]["id"], owner, campaign)
    lot_ids = [e["fill"]["HoldID"] for e in entries]
    lots = [case["entries"][key] for key in lot_ids]
    assert abs(sum(l["Gross"] for l in lots) - parent["Realized"]) < 1e-7
    return {
        "owner": owner, "campaign": campaign, "metrics": parent,
        "entries": [event_record(case, e) for e in entries],
        "exits": [event_record(case, e) for e in events if e["signal"]["action"] == "close"],
        "lots": lots,
    }


def diagnose_entries(scene: str, cases: dict[str, dict], partial: bool) -> list[dict]:
    """同じ出口で入口だけを拒否した親の、比較側勝ち負けを対応させる。

    引数: scene(str)、cases(dict)、partial(bool)。返り値: list[dict]。
    """
    out = []
    for candidate, control in ENTRY_PAIRS.items():
        case, base = cases[candidate], cases[control]
        for rejected in case["protection156"].get("EntryRejected") or []:
            owner, campaign = rejected["Owner"], rejected["Campaign"]
            expected = parent_record(base, owner, campaign)
            actual = parent_record(case, owner, campaign)
            assert actual is None, (scene, candidate, "拒否親に実玉")
            if expected:
                first = expected["entries"][0]
                assert first["decision_index"] == rejected["Index"], (scene, candidate, "親の対応差")
                assert first["side"] == rejected["Side"]
            minutes = rejected["Minutes"] or []
            sign = rejected["Side"]
            slopes = {}
            if len(minutes) >= 3:
                closes = [x["Close"] for x in minutes]
                slopes = {
                    "signed_recent_two": sign * (closes[-1] - closes[-3]),
                    "signed_recent_one": sign * (closes[-1] - closes[-2]),
                    "signed_prior_one": sign * (closes[-2] - closes[-3]),
                }
                if len(closes) >= 6:
                    slopes["signed_before_three"] = sign * (closes[-3] - closes[-6])
            out.append({
                "session": scene, "partial": partial, "candidate": candidate,
                "control": control, "rejection": rejected, "slopes": slopes,
                "control_parent": expected,
                "control_parent_net": expected["metrics"]["Realized"] if expected else None,
                "control_parent_complete": expected["metrics"]["Remaining"] == 0 if expected else False,
                "whole_session_difference": case["Gross"] - base["Gross"],
            })
    return out


def diagnose_pieces(scene: str, case: dict, partial: bool) -> list[dict]:
    """各返済の赤字を起動前・元返済・判断前後の飛びへ分ける。

    引数: scene(str)、case(dict)、partial(bool)。返り値: list[dict]。
    """
    out = []
    case_gross = 0
    for event in (case["events"] or []):
        if event["signal"]["action"] != "close":
            continue
        pieces = event["pieces"]
        assert abs(sum(p["Gross"] for p in pieces) - event["gross"]) < 1e-7
        case_gross += event["gross"]
        detail = event_record(case, event)
        for p in pieces:
            price = detail["decision_bid"] if p["Side"] > 0 else detail["decision_ask"]
            gain = p["Side"] * (price - p["Entry"])
            assert abs(p["Gross"] - p["Side"] * p["Quantity"] * (p["Exit"] - p["Entry"]) * 100) < 1e-7
            if p["Gross"] >= 0:
                continue
            if p["Reason"] in PROTECTIVE:
                category = "保護判断時点で既に赤字" if gain < 0 else "保護判断後の次板で赤字"
            elif p["Protected"]:
                category = "起動済みだが元返済目標を優先"
            elif case["config"]["width"] > 0:
                category = "玉別保護の起動前"
            else:
                category = "玉別保護なしの元出口"
            out.append({
                "session": scene, "partial": partial, "method": case["config"]["id"],
                "category": category, "piece": p, "event": detail,
                "decision_gain_points": gain,
                "decision_to_fill_change_points": p["Side"] * (p["Exit"] - price),
                "parent": case["parents"][f'{p["Owner"]}/{p["Campaign"]}'],
            })
    assert abs(case_gross - case["Gross"]) < 1e-7
    return out


def diagnose_reentry(scene: str, case: dict, partial: bool) -> list[dict]:
    """利益保護後の同担当新規を、同親回転と別親へ分ける。

    引数: scene(str)、case(dict)、partial(bool)。返り値: list[dict]。
    前後関係の記録であり、後続損失を全て利確の因果効果とはしない。
    """
    out, last_guard = [], {}
    for event in (case["events"] or []):
        s = event["signal"]
        owner = s["owner"]
        if s["action"] == "close" and s["reason_code"] in PROTECTIVE:
            last_guard[owner] = event
        if s["action"] != "new" or owner not in last_guard:
            continue
        prior = last_guard[owner]
        if prior["fill_index"] > event["decision_index"]:
            continue
        lot = case["entries"][event["fill"]["HoldID"]]
        out.append({
            "session": scene, "partial": partial, "method": case["config"]["id"],
            "same_campaign": prior["signal"]["campaign"] == s["campaign"],
            "prior_protective_exit": event_record(case, prior),
            "new_entry": event_record(case, event), "new_lot": lot,
            "new_lot_exits": [event_record(case, e) for e in (case["events"] or [])
                              if any(p["ID"] == lot["ID"] for p in e.get("pieces") or [])],
            "parent": case["parents"][f'{owner}/{s["campaign"]}'],
        })
    return out


def virtual_quantity(diagnostic: dict) -> int:
    """保存診断の仮想源数量を実玉と区別して取り出す。

    引数: diagnostic(dict)。返り値: int は保存時点で確認できる仮想数量。
    """
    for key in ("episode_exit", "active_exit", "core_exit_shadow"):
        if key in diagnostic:
            return diagnostic[key]["virtual_quantity"]
    return diagnostic.get("virtual_quantity", 0)


def diagnose_virtual_wait(scene: str, case: dict, base: dict, partial: bool) -> list[dict]:
    """保護完済後も元仮想源だけが保有する実観測時点を抽出する。

    引数: scene(str)、case/base(dict)、partial(bool)。返り値: list[dict]。
    疎な診断間を補間して継続秒数や最大値を創作しない。
    """
    out = []
    for e in case["events"] or []:
        s = e["signal"]
        if s["action"] != "close" or s["reason_code"] not in PROTECTIVE:
            continue
        owner, campaign = s["owner"], s["campaign"]
        points = []
        for snap in case["snapshots"] or []:
            if snap["Index"] < e["fill_index"]:
                continue
            diag = next(d for d in snap["Diagnostics"] if d["owner"] == owner)
            if diag["campaign"] != campaign:
                break
            points.append({"index":snap["Index"],"time":snap["Time"],"jst":clock(snap["Time"]),
                           "actual_quantity":diag["actual_quantity"],
                           "virtual_quantity":virtual_quantity(diag),
                           "bid":snap["Bid"],"ask":snap["Ask"],
                           "blocked":diag["blocked"],"force_reason":diag["force_reason"]})
        if not points or points[0]["index"] != e["fill_index"]:
            raise AssertionError((scene, case["config"]["id"], "返済時診断なし"))
        if points[0]["actual_quantity"] != 0 or points[0]["virtual_quantity"] <= 0:
            continue
        next_new = next((x for x in case["events"] or [] if x["signal"]["action"] == "new"
                         and x["signal"]["owner"] == owner and x["decision_index"] >= e["fill_index"]), None)
        observed_zero = next((p for p in points[1:] if p["virtual_quantity"] == 0), None)
        positive_points = [p for p in points if p["virtual_quantity"] > 0
                           and (observed_zero is None or p["index"] < observed_zero["index"])]
        expected = parent_record(base, owner, campaign)
        out.append({
            "session":scene,"partial":partial,"method":case["config"]["id"],
            "owner":owner,"campaign":campaign,"protective_exit":event_record(case,e),
            "after_exit_snapshot":points[0],
            "last_saved_virtual_positive":positive_points[-1],
            "first_saved_virtual_zero":observed_zero,
            "next_new":event_record(case,next_new) if next_new else None,
            "same_campaign_reentry":any(x["signal"]["action"] == "new" and x["signal"]["owner"] == owner
                                        and x["signal"]["campaign"] == campaign and x["decision_index"] >= e["fill_index"]
                                        for x in case["events"] or []),
            "candidate_parent":parent_record(case,owner,campaign),"baseline_parent":expected,
            "parent_difference":case["parents"][f"{owner}/{campaign}"]["Realized"]-expected["metrics"]["Realized"] if expected else None,
        })
    return out


def main() -> None:
    """完了ログに記載された結果だけを読んで中間又は全件診断を保存する。

    引数: --final はrootの全件正常完了通知後だけ指定するbool。
    返り値: なし。既存金融結果・凍結資料への書込みはしない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    log = (ROOT / "金融実行156.log").read_text(encoding="utf-8-sig")
    sessions = sorted(set(re.findall(r"完了 (\d{4}-\d{2}-\d{2}_Day) 条件26", log)))
    if args.final and len(sessions) != 27:
        raise RuntimeError("全27場の完了前")
    result = {"status": "全件" if args.final else "完了済み部分の構造検査", "sessions": sessions,
              "sources": [], "entry_rejections": [], "negative_pieces": [], "after_protection_entries": [],
              "virtual_wait": []}
    for session in sessions:
        path = ROOT / "results_go" / f"{session}_S01.json"
        raw = path.read_bytes()
        doc = json.loads(raw)
        cases = {c["config"]["id"]: c for c in doc["cases"]}
        assert len(cases) == 26
        partial = doc["scene"]["partial"]
        result["sources"].append({"file": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
        result["entry_rejections"] += diagnose_entries(session, cases, partial)
        for case in cases.values():
            result["negative_pieces"] += diagnose_pieces(session, case, partial)
            result["after_protection_entries"] += diagnose_reentry(session, case, partial)
            if case["config"]["width"] > 0:
                result["virtual_wait"] += diagnose_virtual_wait(session,case,cases["S01"],partial)
    name = "具体診断156.json" if args.final else "具体診断の構造確認156.json"
    (ROOT / name).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sessions":len(sessions), "entry_rejections":len(result["entry_rejections"]),
                      "negative_pieces":len(result["negative_pieces"]),
                      "after_protection_entries":len(result["after_protection_entries"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
