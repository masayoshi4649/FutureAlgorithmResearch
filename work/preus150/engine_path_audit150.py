"""保存済み注文と段階件数だけで、前半の活動増と注文分岐を調べる。"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
OWNERS = ("core", "addon", "episode")


def clock(value):
    """保存された時刻を日本時間へ整形する。

    引数: value(float)はUNIX秒。返り値: strは日付と秒を含む表示。
    """
    return datetime.fromtimestamp(value, JST).isoformat()


def compact(event):
    """保存注文を比較用の事実と当時の指標へ絞る。

    引数: event(dict)は既存約定。返り値: dictは再計算を含まない引用。
    """
    signal, fill = event["signal"], event["fill"]
    observation = signal.get("evidence", {}).get("observation", {})
    history = observation.get("MidHistory", {})
    research = observation.get("Research", {})
    result = {
        "owner": signal["owner"], "action": signal["action"], "side": signal["side"],
        "decision": clock(signal["time"]), "fill": clock(fill["Time"]),
        "decision_index": event["decision_index"], "fill_index": event["fill_index"],
        "quantity": fill["Quantity"], "price": fill["Price"], "gross": event["gross"],
        "reason_code": signal["reason_code"], "reason": signal["reason"],
        "campaign": signal["campaign"], "risk": signal["risk"],
    }
    if signal["action"] == "new":
        result["known_at_entry"] = {
            "bid": observation.get("Bid"), "ask": observation.get("Ask"),
            "atr": observation.get("ATR"), "mid_history": history,
            "research": research,
        }
    return result


def semantic(event):
    """運転IDを除く実際の注文経路を厳密比較する。

    引数: event(dict)は既存約定。返り値: tupleは方向・原行・価格・枚数等。
    """
    s, f = event["signal"], event["fill"]
    return (s["owner"], s["action"], s["side"], s["time"], f["Time"],
            event["decision_index"], event["fill_index"], f["Quantity"], f["Price"],
            s["reason_code"], event["gross"])


def role_summary(case, owner):
    """一条件の前半担当別の段階件数と親収支を取り出す。

    引数: case(dict)、owner(str)。返り値: dictは保存値のみの集計。
    """
    events = [e for e in case["events"] or []
              if e["phase"] == "前半" and e["signal"]["owner"] == owner]
    parent_map = {}
    for event in events:
        s = event["signal"]
        parent = parent_map.setdefault(s["campaign"], {"events": [], "net": 0, "first": None})
        parent["events"].append(event)
        parent["net"] += event["gross"]
        if parent["first"] is None and s["action"] == "new":
            parent["first"] = event
    return {
        "events": events, "new": sum(e["signal"]["action"] == "new" for e in events),
        "new_quantity": sum(e["fill"]["Quantity"] for e in events if e["signal"]["action"] == "new"),
        "net": sum(e["gross"] for e in events), "parents": parent_map,
        "diagnostics": case["diagnostics"].get("前半/" + owner, {}),
    }


def first_difference(left, right):
    """同じ順番の保存注文で最初に異なった箇所を返す。

    引数: left/right(list[dict])は元と変更後の注文。返り値: dict又はNone。
    """
    for i in range(max(len(left), len(right))):
        a = left[i] if i < len(left) else None
        b = right[i] if i < len(right) else None
        if a is None or b is None or semantic(a) != semantic(b):
            return {"order_index": i, "baseline": compact(a) if a else None,
                    "candidate": compact(b) if b else None}
    return None


def parent_records(parents):
    """親ごとの全約定を、保存時点の入口情報と合わせて表示する。

    引数: parents(dict)は担当内の親。返り値: list[dict]は収支と注文列。
    """
    return [{"campaign": key, "net": p["net"], "events": [compact(e) for e in p["events"]]}
            for key, p in parents.items()]


def main():
    """完成した全26結果の読取診断を保存する。

    引数: なし。返り値: None。原板読取・新規シグナル生成・金融再生を行わない。
    """
    paths = sorted((HERE / "results_go").glob("*.json"))
    if len(paths) != 26:
        raise RuntimeError(f"全26場の保存完了待ちです: {len(paths)}場")
    summaries = defaultdict(lambda: {o: {"new": 0, "new_quantity": 0, "net": 0,
                                         "parents": 0, "diagnostics": Counter()} for o in OWNERS})
    differences = defaultdict(lambda: {o: [] for o in OWNERS})
    identical = defaultdict(lambda: {o: [] for o in OWNERS})
    partial = []
    for path in paths:
        packet = json.loads(path.read_text(encoding="utf-8"))
        scene = packet["scene"]
        if scene["partial"]:
            partial.append(scene["session"])
            continue
        cases = {c["config"]["id"]: c for c in packet["cases"]}
        assert len(cases) == 17
        bases = {o: role_summary(cases["A00"], o) for o in OWNERS}
        for cid, case in cases.items():
            for owner in OWNERS:
                role = role_summary(case, owner)
                target = summaries[cid][owner]
                for key in ("new", "new_quantity", "net"):
                    target[key] += role[key]
                target["parents"] += len(role["parents"])
                target["diagnostics"].update(role["diagnostics"])
                base = bases[owner]
                diff = first_difference(base["events"], role["events"])
                if diff is None:
                    identical[cid][owner].append(scene["session"])
                else:
                    differences[cid][owner].append({
                        "session": scene["session"], "baseline_net": base["net"], "candidate_net": role["net"],
                        "net_delta": role["net"] - base["net"], "new_delta": role["new"] - base["new"],
                        "first_difference": diff, "baseline_diagnostics": base["diagnostics"],
                        "candidate_diagnostics": role["diagnostics"],
                        "baseline_parents": parent_records(base["parents"]),
                        "candidate_parents": parent_records(role["parents"]),
                    })
    result = {"summary": summaries, "identical_sessions": identical, "differences": differences,
              "partial_excluded": partial, "sessions": 25,
              "scope": "保存約定と段階件数の読取集計のみ。源の再生・売買条件の再評価なし。"}
    (HERE / "engine_前半担当別診断150.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("前半25夜・17条件・3担当の保存経路を集計しました。")


if __name__ == "__main__":
    main()
