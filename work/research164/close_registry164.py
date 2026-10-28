"""成果・独立監査・報告の確定後に00164の試行状態だけを更新する。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

from control164 import ROOT,HERE,IDENT,FREEZE,RECEIPT,read,sha,record,save,canonical,manager,verify_receipt,verify,module
from catalog164 import OUT


def other_rows(rows: list[dict], ids: set[str]) -> dict:
    """対象以外の試行の内容指紋を保存する。

    引数: rows(list[dict])、ids(set[str])。返り値: dict[str,str]。
    """
    return {x["id"]:canonical(x) for x in rows if x["id"] not in ids}


def snapshot_mutable(sources: list[dict]) -> tuple[list[dict], list[dict]]:
    """今後更新される共通知見・索引は、今回時点の不変コピーで根拠を保存する。

    引数: sources(list[dict])は照合済み根拠。返り値: tuple[list[dict],list[dict]]は保存根拠とコピー対応。
    """
    names = {"README.md", "AGENTS.md", "アルゴリズム調査/調査方針.md", "アルゴリズム調査/README.md", "アルゴリズム調査/index.html"}
    names.update("アルゴリズム調査/共通/知見台帳/" + name for name in ("README.md", "入口.md", "継続.md", "出口.md", "売買の工夫.md"))
    result, mapping = [], []
    for source in sources:
        if source["path"] not in names:
            result.append(source)
            continue
        target = HERE / "公開時点の共通文書" / source["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with target.open("xb") as stream:
                stream.write((ROOT / source["path"]).read_bytes())
        assert sha(target) == source["sha256"]
        copied = record(target)
        result.append(copied)
        mapping.append(dict(original=source, snapshot=copied))
    return result, mapping


def evidence(path: Path) -> list[dict]:
    """最終公開検算と固定再生証跡を検査する。

    引数: path(Path)は公開確認JSON。返り値: list[dict]。
    """
    verify_receipt()
    public=read(path)
    assert public["passed"] is True
    assert public["sessions"] == 54 and public["cases"] == 864
    assert public["method_count"] == 32 and public["new_app_deployment"] is False
    assert public["financial_audit_passed"] is True and public["workbook_audit_passed"] is True
    assert public["manual_render_review_passed"] is True
    for source in public["files"]: verify(source)
    complete=read(HERE/"再生全完了164.json")
    frozen=read(FREEZE)
    assert complete["completed"] is True and complete["returncode"] == 0
    assert complete["sessions"] == 54 and complete["cases"] == 540
    assert complete["selected"] == frozen["selected"] == public["first_round_selected"]
    assert complete["reselection_after_confirmation"] is False
    verify(complete["freeze"])
    for source in complete["proofs"]: verify(source)
    second=module(HERE/"r2/control164r2.py","第二巡完了制御164")
    second.verify_receipt()
    complete2=read(second.HERE/"再生全完了164r2.json")
    frozen2=read(second.FREEZE)
    assert complete2["completed"] is True and complete2["returncode"] == 0
    assert complete2["sessions"] == 54 and complete2["cases"] == 324
    assert complete2["selected"] == frozen2["selected"] == public["selected"]
    assert complete2["reselection_after_confirmation"] is False
    verify(complete2["freeze"])
    for source in complete2["proofs"]: verify(source)
    files=public["files"]+[record(path),record(RECEIPT),record(FREEZE),record(HERE/"再生全完了164.json"),record(Path(__file__)),record(second.RECEIPT),record(second.FREEZE),record(second.HERE/"再生全完了164r2.json")]
    return list({x["path"]:x for x in files}.values())


def main() -> None:
    """根拠の確定後に限り管理器を通し、対象の状態を検証済みへ変更する。

    引数: CLI --apply、--public-check(Path)。返り値: None。売買条件は変更しない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true",required=True)
    parser.add_argument("--public-check",type=Path,default=HERE/"公開照合164.json")
    args=parser.parse_args()
    proof_path=HERE/"試行完了証跡164.json"
    assert not proof_path.exists()
    sources=evidence(args.public_check)
    sources, snapshots=snapshot_mutable(sources)
    public=read(args.public_check)
    m=manager()
    target=m.DATA/"trials.json"
    old_hash=sha(target)
    print("全成果の確定を確認。00164の状態だけを更新します。",flush=True)
    value=m.load(deep=False)
    assert value["source_sha256"]["trials.json"] == old_hash
    rows=value["trials"]["trials"]
    id2=read(HERE/"r2/登録受領164r2.json")["id"]
    ids={IDENT,id2}
    selected=[x for x in rows if x["id"] in ids]
    assert len(selected) == 2
    old_rows={x["id"]:canonical(x) for x in selected}
    old_specs={x["id"]:canonical(x["spec"]) for x in selected}
    others=other_rows(rows,ids)
    for row in selected:
        assert row["status"] == "未実行"
        row["status"]="検証済み"
        row["evidence"]=sources
        row["readme"]=(OUT/"README.md").relative_to(ROOT).as_posix()
        row["report"]=public["workbook"]["path"]
        row["result_note"]=("第一巡はJ02基準の日中12、米国前後各4の20独立ID・54場540条件場。" if row["id"]==IDENT else "第二巡は第一巡の診断後、待機量上限の日中4、元夜間入口の保護各4の12新ID・54場324条件場。全場既知の追加開発。")+"各巡で前40場の候補を固定し後14場で再選択しない。第一巡の源/条件/結果は保持。各mini10枚相当の片側100micro、手数料0、ラージ次正常板。全32手法の損益・実玉利益返し・追撃・具体原板を報告。運用時間割と手法IDを分離し、App変更なし。"
        assert canonical(row["spec"]) == old_specs[row["id"]]
    assert other_rows(rows,ids) == others
    value["trials"]["updated_at"]=datetime.now().astimezone().isoformat()
    # ----------------------------------------
    # 過去試行には更新される索引の当時指紋があり、現時点の索引とは一致しない。
    # 全体の構造を管理器で検査し、今回変更する2行だけ全根拠と実装を厳密照合する。
    # 過去の条件・根拠指紋は書き換えず、全行の不変性を上の内容指紋で確認する。
    m.validate(value,deep=False)
    scope=dict(rules=dict(rules=[]),knowledge=dict(findings=[]),trials=dict(trials=selected,repetition_audit=[]),studies=dict(studies=[]))
    m.validate(scope,deep=True)
    serialized=json.dumps(value["trials"],ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    new_hash=hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    value["source_sha256"]["trials.json"]=new_hash
    rendered=m.bundle(value)
    assert sha(target) == old_hash,"別の登録と競合"
    history=m.DATA/"history"/("trials_"+old_hash+".json")
    history.parent.mkdir(exist_ok=True)
    if not history.exists(): shutil.copyfile(target,history)
    staged=m.DATA/"trials.json.tmp"
    staged_view=m.DATA/"view-data.js.tmp"
    staged.write_text(serialized,encoding="utf-8",newline="\n")
    staged_view.write_text(rendered,encoding="utf-8",newline="\n")
    assert sha(target) == old_hash,"保存直前に別の登録と競合"
    staged.replace(target)
    try:
        staged_view.replace(m.DATA/"view-data.js")
    except OSError:
        shutil.copyfile(history,target)
        raise
    assert sha(target) == new_hash
    save(proof_path,dict(passed=True,ids=sorted(ids),status="二巡とも検証済み",spec_changes=False,other_trial_changes=False,
        previous_sha256=old_hash,new_sha256=new_hash,previous_target_row_sha256=old_rows,
        updated_target_row_sha256={x["id"]:canonical(x) for x in selected},other_trial_count=len(others),evidence=sources,
        mutable_document_snapshots=snapshots,
        validation_scope="全行構造・対象2行の実装と全根拠SHA・対象外行の内容不変。過去の共通索引は当時のSHAを保持。",
        previous_global_deep_check=dict(passed=False,reason="過去試行が保持するアルゴリズム調査/index.htmlの当時指紋と、00164追加後の索引が異なる。保存前に停止。")))
    print("00164の二巡を検証済みへ更新。固定条件と他試行は不変です。",flush=True)


if __name__ == "__main__":
    main()
