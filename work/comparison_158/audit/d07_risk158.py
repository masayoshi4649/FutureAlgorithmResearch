"""D07保存約定をS01以後と同じ原板時価定義で再会計する。売買再生はしない。"""

from pathlib import Path
from datetime import datetime
import importlib.util
import json
import hashlib
import sys
import traceback

BASE = Path(__file__).resolve().parents[1]
WORK = BASE.parent
ROOT = WORK.parent
sys.path.insert(0, str(WORK / "allocation_157/audit"))
from raw_result157 import read_market

spec = importlib.util.spec_from_file_location("risk156_readonly", WORK / "s01_156/intraday_risk156.py")
risk156 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(risk156)


def read(path: Path) -> dict:
    """保存JSONを読み込む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fingerprint(path: Path) -> dict:
    """原資料・会計・検算実装の指紋を作る。

    引数: path(Path)。返り値: dict。
    """
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> None:
    """完了26デイを読取り再会計し、原資料を変更せず新規証跡へ保存する。

    引数: なし。返り値: None。実API・新金融再生は0回。
    """
    out = BASE / "D07の場内リスク定義統一158.json"
    proof = {"passed": False, "purpose": "保存済みD07の約定を156以降と同じ全正常原板・同原行約定逐次評価で再会計する。新しい売買判断を生成しない。", "financial_replays": 0, "live_api_calls": 0, "started_at": datetime.now().astimezone().isoformat()}
    try:
        inputs154 = WORK / "d07_154/inputs154.json"
        inputs156 = WORK / "s01_156/inputs156.json"
        old_scenes = {s["session"]: s for s in read(inputs154)["sessions"]}
        scenes = [s for s in read(inputs156)["sessions"] if not s["partial"] and s["kind"] == "Day"]
        assert len(scenes) == 26
        old_report = WORK / "d07_154/report154.json"
        old_method = next(m for m in read(old_report)["methods"] if m["id"] == "D07")
        old_rows = {r["session"]: r for r in old_method["rows"] if r["kind"] == "Day"}
        old_risk = WORK / "s01_156/場内リスク156.json"
        s01_risks = {r["session"]: r["intraday_risk"] for r in read(old_risk)["rows"] if r["id"] == "S01" and not r["partial"]}
        sources = [inputs154, inputs156, old_report, old_risk]
        for scene in scenes:
            sources += [WORK / "d07_154/results_go" / (scene["session"] + "_D07.json"), WORK / "s01_156/results_go" / (scene["session"] + "_S01.json")]
        before = [fingerprint(p) for p in sources]
        rows, raw_sources = [], []
        for scene in scenes:
            name = scene["session"]
            old_scene = old_scenes[name]
            for key in ("session", "kind", "start", "us_open", "force_close", "end", "cutoff", "partial", "books", "candles", "fingerprints"):
                assert scene[key] == old_scene[key], (name, key, "入力定義不一致")
            raw, raw_proof = read_market(scene, "NK225")
            raw_sources.append(raw_proof)
            case = next(c for c in read(WORK / "d07_154/results_go" / (name + "_D07.json"))["cases"] if c["config"]["id"] == "D07")
            risk = risk156.measure(raw[:, :4], case, scene["start"])
            old = old_rows[name]
            assert risk["final"]["realized"] == old["net"] and risk["final"]["unrealized"] == 0
            baseline = next(c for c in read(WORK / "s01_156/results_go" / (name + "_S01.json"))["cases"] if c["config"]["id"] == "S01")
            comparison = risk156.measure(raw[:, :4], baseline, scene["start"])
            assert comparison == s01_risks[name], (name, "S01の既存定義と不一致")
            rows.append({"id": "D07", "session": name, "partial": False, "net": old["net"], "intraday_risk": risk, "old_minimum_equity": old["minimum_equity"], "old_equity_drawdown": old["equity_drawdown"], "minimum_difference": risk["min_equity"] - old["minimum_equity"], "drawdown_difference": risk["max_drawdown"] - old["equity_drawdown"], "s01_existing_risk_exact": True})
            print(json.dumps({"session": name, "passed": True, "minimum": risk["min_equity"], "drawdown": risk["max_drawdown"]}, ensure_ascii=False), flush=True)
        after = [fingerprint(p) for p in sources]
        assert before == after
        worst = min(rows, key=lambda r: r["intraday_risk"]["min_equity"])
        deepest = max(rows, key=lambda r: r["intraday_risk"]["max_drawdown"])
        proof.update(passed=True, cases=26, s01_existing_risk_exact_cases=26, rows=rows, source_fingerprints=after, raw_fingerprints=raw_sources, source_unchanged=True, summary={"net": sum(r["net"] for r in rows), "min_equity": worst["intraday_risk"]["min_equity"], "min_equity_session": worst["session"], "max_drawdown": deepest["intraday_risk"]["max_drawdown"], "max_drawdown_session": deepest["session"], "changed_minimum_cases": sum(r["minimum_difference"] != 0 for r in rows), "changed_drawdown_cases": sum(r["drawdown_difference"] != 0 for r in rows)}, implementation_fingerprints=[fingerprint(p) for p in (Path(__file__), WORK / "s01_156/intraday_risk156.py", WORK / "allocation_157/audit/raw_result157.py")])
    except Exception as error:
        proof.update(error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        proof["finished_at"] = datetime.now().astimezone().isoformat()
        out.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
