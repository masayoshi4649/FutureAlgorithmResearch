"""夜間の保存約定と旧日中会計を集計し、全場・時間帯・方向の比較を作る。"""

from collections import defaultdict
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "work/allocation_157"))
from report157_common import attach_cumulative, summarize


def read(path: Path) -> object:
    """保存済みJSONを読み取る。

    引数: path(Path)。返り値: objectはJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: object) -> None:
    """集計成果を有限JSONで保存する。

    引数: path(Path)、value(object)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def direction(scene: dict) -> str:
    """正常ラージ原行の場初と終端のLast差を事後分類する。

    引数: scene(dict)は入力資格目録。返り値: strは上昇・下落・横ばい。
    """
    q = scene["qualification"]["NK225"]["book"]
    start = q["first"]["last"]
    end = q["last"]["last"]
    return "上昇" if end > start else "下落" if end < start else "横ばい"


def load_account_module() -> object:
    """既存の独立約定再会計を読み込む。

    引数: なし。返り値: objectは集計モジュール。mainは実行しない。
    """
    path = ROOT / "work/allocation_157/round2/analyze1572.py"
    spec = importlib.util.spec_from_file_location("保存会計159", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def phase_accounts(details: dict) -> dict:
    """完結親を担当名の時間帯へ分け、全夜収支との一致を確認する。

    引数: details(dict)は実台帳の再会計。返り値: dictは時間帯別利益・損失・収支。
    """
    groups = defaultdict(lambda: {"profit": 0., "loss": 0., "net": 0., "parents": 0})
    for parent in details["actual"]["parents"]:
        owner = parent.get("owner", parent.get("id", ""))
        phase = owner.split("/")[0]
        if phase not in ("前半", "後半", "日中"):
            key = parent.get("parent", parent.get("id", ""))
            phase = key.split("/")[0]
        if phase not in ("前半", "後半", "日中"):
            raise ValueError(f"親の時間帯を特定できない: {parent}")
        assert parent["completed"] and parent["remaining"] == 0
        value = parent["realized"]
        groups[phase]["profit"] += max(0, value)
        groups[phase]["loss"] += max(0, -value)
        groups[phase]["net"] += value
        groups[phase]["parents"] += 1
    return dict(groups)


def main() -> None:
    """再生完了の全314条件場を再会計して報告資料を構築する。

    引数: なし。返り値: None。注文生成・金融再生は行わない。
    """
    done = read(HERE / "金融実行159.json")
    assert done["exit_code"] == 0
    manifest = read(ROOT / "work/audit159/inputs159.json")
    scenes = {s["session"]: s for s in manifest["sessions"]}
    account = load_account_module()
    configs = {c["id"]: c for c in read(ROOT / "work/night159/configs159.json")}
    grouped, day_new, checks = defaultdict(list), {}, []
    raw = sorted((ROOT / "work/night159/results_go").glob("*.json"))
    assert len(raw) == len(scenes) == 27
    for path in raw:
        saved = read(path)
        scene = saved["scene"]
        inputs = scenes[scene["session"]]
        assert saved["exact_checks"] > 0
        for case in saved["cases"]:
            row, details = account.make_row(case, {"direction": direction(inputs)})
            row["sample_group"] = "追加完了版" if scene["session"] in ("2026-10-26_Night", "2026-10-27_Day") else "旧完了場"
            row["phases"] = phase_accounts(details)
            assert abs(sum(p["net"] for p in row["phases"].values()) - row["net"]) < 1e-6
            save(HERE / "accounts" / scene["session"] / (row["id"] + ".json"), details)
            checks.append({"session": row["session"], "method": row["id"], "ledger_reconciled": True, "remaining": row["remaining_qty"]})
            if scene["kind"] == "Day":
                day_new[{"N00": "S01", "N02": "J02"}[row["id"]]] = row
            else:
                grouped[row["id"]].append(row)
    assert len(checks) == 26 * 12 + 2
    methods = []
    for key, values in sorted(grouped.items()):
        rows = attach_cumulative(values)
        assert len(rows) == 26
        methods.append({"id": key, "kind": "Night", "description": configs[key]["description"], "rows": rows,
                        "summary": summarize(rows), "old25": summarize([r for r in rows if r["sample_group"] == "旧完了場"]),
                        "additional": [r for r in rows if r["sample_group"] == "追加完了版"],
                        "by_direction": {v: summarize([r for r in rows if r["direction"] == v]) for v in ("上昇", "下落", "横ばい")}})
    # ----------------------------------------
    # 既存26日中は再生せず引用し、返済配賦が違う追加版を別条件として示します。
    previous = read(ROOT / "work/comparison_158/report158.json")
    for key in ("S01", "J02"):
        old = next(m for m in previous["methods"] if m["id"] == key)
        new = dict(day_new[key], id=key)
        rows = attach_cumulative([dict(r, sample_group="旧完了場") for r in old["rows"]])
        methods.append({"id": key, "kind": "Day", "description": old["description"], "rows": rows,
                        "summary": summarize(rows), "old26": summarize(rows), "additional": [new]})
        added_id = "S01完了確認" if key == "S01" else "J02型完了確認"
        added = attach_cumulative([dict(new, id=added_id)])
        methods.append({"id": added_id, "kind": "Day", "description": "10/27完了版の確認。" + ("S01源の旧prefix一致。" if key == "S01" else "返済対象追従版。旧J02はFIFO投影で確定/含み配賦が違うため合算しない。"),
                        "rows": added, "summary": summarize(added), "additional_only": True, "engine_id": {"S01": "N00", "J02": "N02"}[key]})
    report = {"created_at": datetime.now().astimezone().isoformat(), "scope": "夜26場、昼は旧26場のS01/J02と追加10/27の2経路を分離。既知開発と既知途中場の完了確認。", "methods": methods,
              "definition": {"fees": 0, "quantity": "micro片方向100枚相当=mini10枚相当", "account": "完結親の全返済純額を正負に分類", "fill": "判断後の次正常ラージBid/Ask", "day_reused": 26, "night_source": "共通指標保持・米国前P05／後D07を新状態開始", "direction": "正常ラージ原行の場初と終端6分内Lastを始終代理として比較。正式終値ではない。過去Dayは同じLast基準の保存済み分類を維持"}}
    save(HERE / "report159.json", report)
    save(HERE / "会計照合159.json", {"passed": True, "cases": len(checks), "checks": checks})
    print(json.dumps([{k: m[k] for k in ("id", "kind", "summary")} for m in methods], ensure_ascii=False))


if __name__ == "__main__":
    main()
