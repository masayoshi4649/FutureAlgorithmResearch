"""確定した保存会計と独立監査を照合し、Excel用の表示資料を作る。"""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def read(path: Path):
    """保存JSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def record(path: Path) -> dict:
    """内容指紋を返す。

    引数: path(Path)。返り値: dict。
    """
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> None:
    """独立監査済みの53場11手法だけを表示用に整える。

    引数: なし。返り値: None。売買・選択・原会計を書き換えない。
    """
    source = WORK / "diagnosis/比較集計163.json"
    data = read(source)
    audit = read(HERE / "audit163.json")
    assert audit["passed"] and audit["totals"]["cases"] == 530
    manifest = read(WORK / "inputs163.json")
    order = {s["session"]: i for i, s in enumerate(manifest["sessions"])}
    configs = {c["id"]: c for c in read(WORK / "engine/configs163.json")}
    configs["F00"] = {"id": "F00", "description": f"前40場で固定した昼{data['selected']['Day']}・夜{data['selected']['Night']}の組合せ"}
    audited = {}
    for scene in manifest["sessions"]:
        proof = read(HERE / "結果監査" / (scene["session"] + ".json"))
        assert proof["passed"]
        audited[scene["session"]] = {r["id"]: r for r in proof["rows"]}
    methods = []
    ids = ["B00", "F00", "C50", "D40", "D80", "G40", "G80", "R40", "R80", "E40", "E80"]
    for ident in ids:
        rows = sorted([dict(r) for r in data["rows"] if r["id"] == ident], key=lambda r: order[r["session"]])
        assert len(rows) == 53
        cumulative = 0
        for row in rows:
            actual = row.get("selected_component", ident)
            reference = audited[row["session"]][actual]
            for key in ("profit", "loss", "net", "new_orders"):
                assert abs(row[key] - reference[key]) < 1e-7
            assert row["minimum_equity"] == reference["risk"]["min_equity"]
            assert row["maximum_dd"] == reference["risk"]["max_drawdown"]
            assert row["profit"] - row["loss"] == row["net"]
            cumulative += row["net"]
            row.update(cumulative=cumulative, component=actual)
            if ident == "F00":
                assert actual == data["selected"][row["kind"]]
        summaries = {f"{kind}_{split}": data["groups"][f"{ident}_{kind}_{split}"] for kind in ("全場", "Day", "Night") for split in ("全場", "前40", "後13")}
        assert summaries["全場_全場"]["net"] == cumulative
        methods.append({"id": ident, "description": configs[ident]["description"], "configuration": configs[ident], "rows": rows, "summary": summaries})
    out = {"methods": methods, "selected": data["selected"], "sessions": 53, "case_count": 530, "known_development": True,
           "accounting": "利益・損失は返済配賦別の正負合計。F00は固定した昼夜条件の保存行連結で追加金融なし。",
           "sources": [record(source), record(HERE / "audit163.json"), record(WORK / "results/selection_frozen163.json"), record(Path(__file__))]}
    target = WORK / "report_data163.json"
    assert not target.exists(), "確定表示資料を上書きしません"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "methods": len(methods), "rows": 53 * len(methods), "source": record(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
