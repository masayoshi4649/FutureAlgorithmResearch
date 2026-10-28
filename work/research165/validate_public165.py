"""公開資料・保存会計・独立検算・知見更新を一つの完了証跡へ結ぶ。"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from control165 import ROOT, HERE, CONFIGS, SPEC, read, sha, record, verify, save, verify_receipt, verified_freeze

OUT = ROOT/"アルゴリズム調査/00165_米国開始後の板追随と損失安定化"
BOOK = OUT/"米国開始後の板判断と全セッション損益.xlsx"


def verify_links(path: Path) -> int:
    """公開Markdownの相対ファイル参照が存在することを確認する。

    引数: path(Path)。返り値: int。外部URLとアンカーだけの参照は開かない。
    """
    count=0
    for link in re.findall(r"\]\(([^)]+)\)",path.read_text(encoding="utf-8")):
        parsed=urlsplit(link)
        if parsed.scheme or not parsed.path:
            continue
        target=path.parent/unquote(parsed.path)
        assert target.exists(), (path,link)
        count+=1
    return count


def main() -> None:
    """金融源不変・公開会計一致・描画確認を確認して試行完了へ渡す。

    引数: なし。返り値: None。巨大試行台帳への書込みは別手順。
    """
    verify_receipt()
    fixed=verified_freeze()
    done=read(HERE/"再生全完了165.json")
    assert done["completed"] and done["cases"]==378 and not done["reselection_after_confirmation"]
    audit=read(HERE/"audit/audit165.json")
    assert audit["passed"] and audit["source_unchanged"] and audit["totals"]["cases"]==405
    assert not audit["saved_snapshot_payload_fully_consistent"] and audit["diagnostic_correction_only"]
    assert audit["totals"]["snapshot_different_cases"]==16 and audit["totals"]["snapshot_different_maps"]==32
    for source in audit["results"]+audit["implementation"]+[audit["complete"],audit["selection"]]:
        verify(source)
    data=read(HERE/"report_data165.json")
    assert len(data["methods"])==15 and data["selected"]==fixed["selected"]
    assert fixed["selected"]=={"PostUS":"NK225_U165_04"}
    assert fixed["shortlist"]==["NK225_U165_04","NK225_U164_00","NK225_U165_03"]
    for method in data["methods"]:
        assert len(method["rows"])==27 and len({r["session"] for r in method["rows"]})==27
        running=0
        for row in method["rows"]:
            assert abs(row["profit"]-row["loss"]-row["net"])<1e-7
            running+=row["net"]
            assert abs(row["cumulative"]-running)<1e-7
    checks=read(HERE/"report/検算165.json")
    visual=read(HERE/"report/全シート目視165.json")
    assert checks["passed"] and checks["sheets"]==16 and checks["tables"]==18 and checks["formula_errors"]==0
    assert visual["passed"] and visual["sheets_checked"]==16 and visual["rendered_ranges"]==18
    assert checks["workbook_sha256"]==visual["workbook_sha256"]==sha(BOOK)
    assert checks["source_sha256"]==visual["source_sha256"]==sha(HERE/"report_data165.json")
    assert checks["audit_sha256"]==sha(HERE/"audit/audit165.json")
    for image in visual["images"]:
        assert image["visually_checked"] and not image["issues"]
        verify(image)
    assert sha(OUT/"手法定義165.json")==sha(CONFIGS)
    assert sha(OUT/"事前の判定仕様.md")==sha(SPEC)
    source_diagnosis=read(HERE/"diagnosis/前20診断確定165.json")
    assert source_diagnosis["passed"] and source_diagnosis["financial_runs"]==0
    for source in source_diagnosis["files"]:
        verify(source)
    knowledge=read(HERE/"知見更新165.json")
    assert knowledge["passed"]
    for source in knowledge["snapshots"]:
        verify(source)
    links=sum(verify_links(p) for p in OUT.glob("*.md"))
    # ----------------------------------------
    # 可変の総索引は公開時点コピーを根拠にし、元の過去試行の指紋は書き換えない。
    files=set(p for p in OUT.iterdir() if p.is_file())
    files.update(HERE/name for name in ("再生全完了165.json","report_data165.json","損失原因と改修差165.json",
        "diagnose165.py","control_empty165.py","空取引の集計互換165.json","publish_knowledge165.py","知見更新165.json",
        "audit/audit165.json","report/検算165.json","report/全シート目視165.json","diagnosis/前20診断確定165.json"))
    files.add(Path(__file__))
    for source in knowledge["snapshots"]+source_diagnosis["files"]+audit["implementation"]:
        files.add(ROOT/source["path"])
    conclusion="米国データ不使用の14条件・27夜。前20固定第一候補U165_04は+1,094,000円/赤字9夜で基準+1,100,000円/9夜とほぼ同じ。事前候補U165_03は+1,181,000円/赤字8夜だが平均赤字31,375円・場内最悪−88,000円で損失の深さは未改善。独立短期入口は気配差と同帯重ね建てで赤字。既知開発、運用未変更。"
    save(HERE/"公開照合165.json",dict(passed=True,sessions=27,cases=378,comparison_cases=405,method_count=14,
        comparison_methods=15,new_app_deployment=False,financial_audit_passed=True,workbook_audit_passed=True,
        manual_render_review_passed=True,saved_snapshot_payload_fully_consistent=False,
        diagnostic_correction_only=True,diagnostic_snapshot_maps=32,aggregation_compatibility_only=True,
        files=[record(p) for p in sorted(files)],readme=record(OUT/"README.md"),workbook=record(BOOK),
        conclusion=conclusion,links_checked=links,selected=fixed["selected"],reselected_after_confirmation=False,
        us_market_data_used=False,known_development=True,independent_unseen=False))
    print("公開資料・全会計・Excel・知見の照合PASS。診断断面の不整合32件は明示。")


if __name__ == "__main__":
    main()
