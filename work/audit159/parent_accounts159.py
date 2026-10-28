"""全返済配賦の親別純額と報告値を独立に照合する。原板再生は行わない。"""
from collections import defaultdict
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work/audit159"


def read(path: Path) -> dict:
    """JSONを読む。

    引数: path(Path)。返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    """実約定から全親損益を作り、夜間報告・原台帳合計を検算する。

    引数: なし。返り値: None。源・候補結果・root報告は変更しない。
    """
    manifest = read(WORK / "inputs159.json")
    report_path = ROOT / "work/research159/report159.json"
    report = read(report_path)
    reported = {(m["id"], r["session"]): r for m in report["methods"] if m["kind"] == "Night" for r in m["rows"]}
    rows = []
    for scene in manifest["sessions"]:
        saved = read(ROOT / "work/night159/results_go" / (scene["session"]+".json"))
        for case in saved["cases"]:
            parents = defaultdict(float)
            for event in case["actual"]["Events"] or []:
                parents[event["Order"]["Parent"]] += event["Gross"]
            values = {"profit": sum(max(0, v) for v in parents.values()), "loss": sum(max(0, -v) for v in parents.values()), "net": sum(parents.values())}
            assert values["net"] == case["actual"]["Realized"]
            phases = defaultdict(float)
            for parent, value in parents.items():
                phases[parent.split("/")[0]] += value
            row = {"id":case["config"]["id"], "session":scene["session"], "kind":scene["kind"], **values, "phases":dict(phases), "parents":dict(parents)}
            if scene["kind"] == "Night":
                expected = reported[(row["id"], row["session"])]
                for key, value in values.items():
                    assert value == expected[key], (row["id"],row["session"],key)
                for phase, value in phases.items():
                    assert value == expected["phases"][phase]["net"]
            rows.append(row)
    assert len(rows) == 314
    output = {"passed":True, "cases":len(rows), "night_report_rows":len(reported), "new_financial_replays":0, "report_sha256":hashlib.sha256(report_path.read_bytes()).hexdigest(), "rows":rows}
    (WORK / "完結親損益の独立照合159.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    proof_path = WORK / "金融結果の独立監査159.json"
    proof = read(proof_path)
    assert proof["passed"]
    proof["parent_account_checks"] = {"cases":314,"night_report_rows":len(reported),"evidence":"work/audit159/完結親損益の独立照合159.json"}
    proof["audit_correction"] = "監査初稿の確定最小は同原行の終点集約だった。10/20夜の同原行中間−14100円で検知し、各約定順に訂正して全314件再検査。元エンジン・金融結果は初めから逐次保存で変更なし。旧失敗記録を別保存。"
    proof["audit_sources"] = [{"path":str(p.relative_to(ROOT)),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in (Path(__file__),WORK/"result_audit159.py",ROOT/"work/allocation_157/audit/raw_result157.py",ROOT/"work/allocation_157/round2/audit/raw_result1572.py")]
    proof_path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":True,"totals":proof["totals"],"proof_sha256":hashlib.sha256(proof_path.read_bytes()).hexdigest()},ensure_ascii=False))


if __name__ == "__main__":
    main()
