"""選択済み後半信号の先着と、その後を含む100円到達を分離する。"""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from diagnose161 import authorize, sha, read_json, load_npz


def aggregate(rows: list[dict]) -> dict:
    """50円逆行先着後に100円へ到達した件数を、元の全分母を残して数える。

    引数: rows(list[dict])。返り値: dict。後からの回復を先着成功へ変更しない。
    """
    total = len(rows)
    failures = [r for r in rows if r["status"] == -1]
    late = [r for r in failures if r["up"] >= 0 and r["down"] >= 0 and r["down"] < r["up"]]
    ever = sum(r["up"] >= 0 for r in rows)
    return {"all_signals": total, "success_first": sum(r["status"] == 1 for r in rows), "adverse_first": len(failures),
            "later_favorable_after_adverse": len(late), "conditional_denominator_adverse_first": len(failures),
            "conditional_rate": len(late)/len(failures) if failures else None,
            "all_signal_rate": len(late)/total if total else None, "ever_favorable": ever,
            "ever_favorable_rate": ever/total if total else None,
            "unresolved": sum(r["status"] == 0 for r in rows), "no_entry": sum(r["status"] == -2 for r in rows)}


def main() -> None:
    """完了許可を確認して固定後信号だけのNPZ最小障壁原行を再集計する。

    引数: CLIのauthorization/locked/freeze/cache/out。返り値: None。
    """
    parser = argparse.ArgumentParser()
    for key in ("authorization", "locked", "freeze", "cache", "out"):
        parser.add_argument("--"+key, type=Path, required=True)
    args = parser.parse_args()
    permission = authorize(args.authorization, args.locked, args.freeze)
    locked = read_json(args.locked)
    freeze = read_json(args.freeze)
    assert locked["selected"] == freeze["selected"] and locked["freeze_sha256"] == sha(args.freeze)
    scenes = defaultdict(list)
    for phase, events in locked["events"].items():
        for event in events:
            assert event["candidate"] == freeze["selected"][phase]
            scenes[event["session"]].append(event)
    access = {a["session"]: a for a in locked["access"]}
    rows, evidence = [], []
    for name, events in sorted(scenes.items()):
        path = args.cache/"labels"/"test"/(name+".npz")
        digest = sha(path)
        assert digest == access[name]["label_sha256"]
        labels = load_npz(path)
        for event in events:
            i, side = event["row"], 0 if event["side"] == 1 else 1
            assert event["decision_index"] == int(labels["decision_index"][i])
            assert event["decision_time"] == float(labels["decision_time"][i])
            assert event["status"] == int(labels["primary_status"][i,side])
            up, down = int(labels["primary_first_up_index"][i,side]), int(labels["primary_first_down_index"][i,side])
            if up >= 0 and down >= 0:
                assert event["status"] == (1 if up < down else -1)
            rows.append({"phase":event["phase"],"session":name,"candidate":event["candidate"],"side":event["side"],
                         "decision_index":event["decision_index"],"status":event["status"],"up":up,"down":down})
        evidence.append({"session":name,"label_sha256":digest})
    result = {"passed":True,"authorization":permission,"selected":freeze["selected"],"financial_replays":0,"reselection":False,
              "phase":[{"phase":p,**aggregate([r for r in rows if r["phase"] == p])} for p in freeze["selected"]],
              "evidence":evidence,"rows":rows,
              "definition":"主100/50を同じ場の末尾まで観測。50先着後の100到達は先着成功へ加算しない。元手法の退出・損切り後の実収支を表さない。"}
    assert permission == authorize(args.authorization,args.locked,args.freeze)
    with args.out.open("x",encoding="utf-8") as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps(result["phase"],ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
