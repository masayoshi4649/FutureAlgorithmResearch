"""公開資料、固定定義、会計、Excel、根拠ファイルの一致を最終確認する。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

from control164 import ROOT, HERE, read, record, save, sha, verify
from catalog164 import OUT


def links_in(path: Path) -> int:
    """公開Markdownからローカルリンクの実在を確認する。

    引数: path(Path)は確認対象。返り値: intは確認したリンク数。
    """
    count = 0
    for value in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        value = unquote(value.strip("<>"))
        if value.startswith(("https://", "http://", "#")):
            continue
        target = (path.parent / value.split("#", 1)[0]).resolve()
        assert target.exists(), (path.name, value)
        count += 1
    return count


def nested_records(value: object) -> list[dict]:
    """監査資料の中に記録されたファイル指紋を取り出す。

    引数: value(object)はJSON値。返り値: list[dict]はpathとsha256の組。
    """
    if isinstance(value, dict):
        result = [value] if "path" in value and "sha256" in value else []
        for child in value.values():
            result.extend(nested_records(child))
        return result
    if isinstance(value, list):
        return [record_value for child in value for record_value in nested_records(child)]
    return []


def main() -> None:
    """確定会計に公開表を照合し、試行完了用の証跡を作る。

    引数: なし。返り値: None。売買再生・金融結果の変更は行わない。
    """
    data_path = HERE / "report_data164_all.json"
    data = read(data_path)
    audit_path = HERE / "audit/audit164_all.json"
    audit = read(audit_path)
    workbook_check_path = HERE / "report/xlsx_checks/保存Excelの独立検算164.json"
    workbook_check = read(workbook_check_path)
    visual_path = HERE / "report/目視検証164.json"
    visual = read(visual_path)
    assert audit["passed"] and audit["first_round_unchanged"] and audit["selection_matches"]
    assert (audit["methods"], audit["sessions"], audit["distinct_cases"]) == (32, 54, 864)
    assert workbook_check["passed"] and visual["passed"]
    assert (workbook_check["sheets"], workbook_check["tables"], visual["rendered_sheets"]) == (34, 35, 34)
    assert workbook_check["independent_account_rows"] == 864
    assert workbook_check["formula_errors"] == 0
    assert data["known_development"] and not data["independent_unseen"]
    methods = {m["id"]: m for m in data["methods"]}
    assert len(methods) == len(data["methods"]) == 32
    definitions = read(OUT / "手法定義164.json") + read(OUT / "手法定義164r2.json")
    assert len({d["id"] for d in definitions}) == 32
    assert {d["id"] for d in definitions} == set(methods)
    sessions = set()
    cases = 0
    for definition in definitions:
        method = methods[definition["id"]]
        assert definition == method["configuration"]
        assert method["scope"] in {"Day", "PreUS", "PostUS"}
        rows = method["rows"]
        assert len(rows) == len({row["session"] for row in rows}) == 27
        running = 0
        for row in rows:
            assert row["net"] == row["profit"] - row["loss"]
            assert row["profit"] >= 0 and row["loss"] >= 0
            running += row["net"]
            assert row["cumulative"] == running
            sessions.add(row["session"])
            cases += 1
        total = method["summary"]["全場"]
        for key in ("profit", "loss", "net"):
            assert total[key] == sum(row[key] for row in rows)
        assert total["negative_sessions"] == sum(row["net"] < 0 for row in rows)
        assert total["no_entries"] == sum(row["new_orders"] == 0 for row in rows)
    assert len(sessions) == 54 and cases == 864

    # ----------------------------------------
    # 公開の主要比較表は文字列の数字を読み取り、会計側と一致させる。
    description = (OUT / "README.md").read_text(encoding="utf-8")
    main_rows = [line.split("|")[1:-1] for line in description.splitlines() if re.match(r"\|(日中|米国前|米国後)・", line)]
    assert len(main_rows) == 6
    for columns in main_rows:
        short_id = re.search(r"[DPU]164_\d\d", columns[0]).group()
        total = methods["NK225_" + short_id]["summary"]["全場"]
        amounts = [int(re.sub(r"[^\d-]", "", col)) for col in columns[1:4]]
        assert amounts == [total[key] for key in ("profit", "loss", "net")]
        assert columns[4] == f'{total["negative_sessions"]}/27'
    schedule = next(s for s in data["schedules"] if s["pre"] == "NK225_P164_06" and s["post"] == "NK225_U164_00")
    assert schedule["synthetic_method_id"] is None
    total = schedule["summary"]["全場"]
    assert f'+{total["net"]:,.0f}円、赤字{total["negative_sessions"]}/27場、無取引{total["no_entries"]}場' in description
    assert "未見検証ではない" in description and "App・distは変更していない" in description
    assert data["selected"] == {"Day": "NK225_D164_15", "PreUS": "NK225_P164_06", "PostUS": "NK225_U164_00"}

    # ----------------------------------------
    # 書式・会計・原板診断の根拠を、公開時点の指紋へ固定する。
    workbook = OUT / "J02改修と夜間独立手法の全セッション損益.xlsx"
    workbook_hash = sha(workbook)
    assert workbook_hash == workbook_check["workbook_sha256"] == visual["workbook_sha256"]
    assert sha(data_path) == workbook_check["source_sha256"]
    day_proof = HERE / "r2/day_design/diagnosis/日中診断完了164r2.json"
    night_proof = HERE / "r2/night_design/夜間診断の完了証跡164r2.json"
    assert read(day_proof)["passed"] and read(night_proof)["passed"]
    proof_paths = [audit_path, workbook_check_path, visual_path, day_proof, night_proof]
    verified = {}
    for path in proof_paths:
        for source in nested_records(read(path)):
            source_path = Path(source["path"])
            if not source_path.is_absolute():
                source_path = ROOT / source_path
            assert sha(source_path) == source["sha256"], source_path
            verified[source_path.resolve()] = source_path
    files = list(OUT.glob("*.md")) + list(OUT.glob("*.json")) + [workbook, data_path, *proof_paths, *verified.values(), Path(__file__)]
    files += [HERE / "再生全完了164.json", HERE / "r2/再生全完了164r2.json",
              HERE / "登録受領164.json", HERE / "r2/登録受領164r2.json",
              HERE / "results/selection_frozen164.json", HERE / "r2/results/selection_frozen164r2.json",
              HERE / "r2/audit/preflight164r2_final.json"]
    common = ROOT / "アルゴリズム調査/共通/知見台帳"
    files += [common / name for name in ("README.md", "入口.md", "継続.md", "出口.md", "売買の工夫.md")]
    files += [ROOT / name for name in ("README.md", "AGENTS.md", "アルゴリズム調査/調査方針.md", "アルゴリズム調査/README.md", "アルゴリズム調査/index.html")]
    for name in ("入口.md", "継続.md", "出口.md", "売買の工夫.md"):
        assert OUT.name in (common / name).read_text(encoding="utf-8")
    link_count = sum(links_in(path) for path in OUT.glob("*.md"))
    file_records = sorted({record(path)["path"]: record(path) for path in files}.values(), key=lambda r: r["path"])
    for source in file_records:
        verify(source)
    save(HERE / "公開照合164.json", dict(
        passed=True, sessions=54, cases=864, method_count=32,
        new_app_deployment=False, financial_audit_passed=True,
        workbook_audit_passed=True, manual_render_review_passed=True,
        selected=data["selected"], first_round_selected=data["first_round_selected"],
        workbook=record(workbook), files=file_records,
        checked_public_table_rows=6, checked_markdown_links=link_count,
        independent_unseen=False, new_financial_replays=0,
        note="公開表・全864行・固定定義・独立監査・描画証跡の照合。App変更を伴わない調査成果の確定。"))
    print(json.dumps(dict(passed=True, methods=32, cases=864, files=len(file_records), links=link_count), ensure_ascii=False))


if __name__ == "__main__":
    main()
