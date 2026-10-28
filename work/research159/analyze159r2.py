"""第二巡の全約定を再会計し、第一巡を変更せず最終比較を組み立てる。"""

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from analyze159 import read, save, direction, load_account_module, phase_accounts
from report157_common import attach_cumulative, summarize

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "work/research159"
SECOND = HERE / "round2"


def main() -> None:
    """四案104場と基準26場を確認し全比較JSONを保存する。

    引数: なし。返り値: None。新たな売買判断を生成しない。
    """
    done = read(SECOND / "金融実行159r2.json")
    assert done["exit_code"] == 0 and done["sources_unchanged"]
    manifest = read(ROOT / "work/night159/round2/inputs159r2.json")
    inputs = {s["session"]: s for s in manifest["sessions"]}
    configs = {c["id"]: c for c in read(ROOT / "work/night159/round2/configs159r2.json")}
    account = load_account_module()
    grouped, checks = defaultdict(list), []
    paths = sorted((ROOT / "work/night159/round2/results_go").glob("*.json"))
    assert len(paths) == 26
    for path in paths:
        result = read(path)
        session = result["scene"]["session"]
        old = read(ROOT / "work/night159/results_go" / path.name)
        old_base = next(c for c in old["cases"] if c["config"]["id"] == "N00")
        current = result["control"]
        assert current["actual"] == old_base["actual"], f"基準の実台帳差:{session}"
        assert current["canonical"] == old_base["canonical"], f"基準の判断台帳差:{session}"
        assert result["sources"] == old["sources"], f"元Source差:{session}"
        for case in result["cases"]:
            row, details = account.make_row(case, {"direction": direction(inputs[session])})
            row["sample_group"] = "追加完了版" if session == "2026-10-26_Night" else "旧完了場"
            row["phases"] = phase_accounts(details)
            assert abs(sum(x["net"] for x in row["phases"].values()) - row["net"]) < 1e-6
            grouped[row["id"]].append(row)
            save(SECOND / "accounts" / session / (row["id"] + ".json"), details)
        checks.append({"session": session, "source_exact": True, "base_actual_exact": True, "new_cases": len(result["cases"])})
    assert sum(len(x) for x in grouped.values()) == 104
    first = read(HERE / "report159.json")
    second = []
    for key, values in sorted(grouped.items()):
        rows = attach_cumulative(values)
        second.append({"id": key, "kind": "Night", "round": 2, "description": configs[key]["description"], "rows": rows,
                       "summary": summarize(rows), "old25": summarize([r for r in rows if r["sample_group"] == "旧完了場"]),
                       "additional": [r for r in rows if r["sample_group"] == "追加完了版"],
                       "by_direction": {v: summarize([r for r in rows if r["direction"] == v]) for v in ("上昇", "下落", "横ばい")}})
    first["methods"] += second
    first["created_at"] = datetime.now().astimezone().isoformat()
    first["definition"]["round2"] = "悪化三夜を診断後に固定した四案。全26夜を同じ入力で再検証。既知結果からの追加開発。"
    for method in first["methods"]:
        if method["kind"] == "Night":
            method["summary"]["average_gross_micro"] = sum(r["quantities"]["average_gross"] for r in method["rows"]) / len(method["rows"])
    save(HERE / "report159_all.json", first)
    save(SECOND / "会計照合159r2.json", {"passed": True, "new_cases": 104, "exact_control_cases": 26, "checks": checks})
    print([{ "id": m["id"], "summary": m["summary"]} for m in second])


if __name__ == "__main__":
    main()
