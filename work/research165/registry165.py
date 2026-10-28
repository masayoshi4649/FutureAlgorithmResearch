"""既存照合器を使い、当研究の追加・状態更新だけを安全に保存する。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

from control165 import ROOT, HERE, IDENT, read, record, sha, canonical, save, module, verify, verify_receipt


def manager():
    """共通管理器の構造検査・照合・表示生成関数を読む。

    引数: なし。返り値: module。
    """
    return module(ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py", "共通登録165")


def old_rows(rows: list[dict], excluded: set[str]) -> dict:
    """対象外の全行を内容指紋で固定する。

    引数: rows(list[dict])、excluded(set[str])。返り値: dict[str,str]。
    """
    return {r["id"]: canonical(r) for r in rows if r["id"] not in excluded}


def write_registry(m, value: dict, expected_sha: str, affected: list[dict], others: dict) -> dict:
    """対象行の全根拠と対象外の不変性を確認し、旧正本を保全して保存する。

    引数: m(module)、value(dict)、expected_sha(str)、affected(list[dict])、others(dict)。返り値: dict。
    """
    lock = m.DATA / "trials.json.write165.lock"
    # 同じ保存関数の競合は排他的作成で止める。別の管理器による変更は前後SHAでも検出する。
    with lock.open("x", encoding="utf-8") as stream:
        try:
            stream.write(IDENT+"\n")
            stream.flush()
            return write_locked(m,value,expected_sha,affected,others)
        finally:
            stream.close()
            lock.unlink()


def write_locked(m, value: dict, expected_sha: str, affected: list[dict], others: dict) -> dict:
    """一時保存と二つの置換を実行し、ビュー失敗時には旧正本を復元する。

    引数: m(module)、value(dict)、expected_sha(str)、affected(list[dict])、others(dict)。返り値: 保存証跡(dict)。
    """
    target=m.DATA/"trials.json"; view=m.DATA/"view-data.js"
    staged=m.DATA/"trials.json.tmp"; staged_view=m.DATA/"view-data.js.tmp"
    rollback=m.DATA/"trials.json.rollback165.tmp"
    assert not any(p.exists() for p in (staged,staged_view,rollback)), "別の保存又は未完了の一時ファイル"
    ids={r["id"] for r in affected}
    assert ids and len(ids)==len(affected), "対象IDが空又は重複"
    assert sha(target)==expected_sha, "並行更新を検出"
    rows=value["trials"]["trials"]
    actual={r["id"]:canonical(r) for r in rows if r["id"] in ids}
    assert actual=={r["id"]:canonical(r) for r in affected}, "厳密検査行と保存対象行が不一致"
    assert old_rows(rows,ids)==others, "対象外の行が変更された"
    m.validate(value,deep=False)
    # ----------------------------------------
    # 旧索引のSHAは書き換えず、今の対象行だけ全根拠まで検査する。
    scoped=dict(rules=dict(rules=[]),knowledge=dict(findings=[]),
                trials=dict(trials=affected,repetition_audit=[]),studies=dict(studies=[]))
    m.validate(scoped,deep=True)
    value["trials"]["updated_at"]=datetime.now().astimezone().isoformat()
    serialized=json.dumps(value["trials"],ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    new_sha=hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    value["source_sha256"]["trials.json"]=new_sha
    rendered=m.bundle(value)
    assert sha(target)==expected_sha, "ビュー準備中の並行更新"
    view_sha=hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    old_view_sha=sha(view) if view.exists() else None
    snapshot=m.DATA/"history"/("trials_"+expected_sha+".json")
    snapshot.parent.mkdir(exist_ok=True)
    if not snapshot.exists(): shutil.copyfile(target,snapshot)
    assert sha(snapshot)==expected_sha, "旧正本退避の内容不一致"
    old_view=m.DATA/"history"/("view_"+old_view_sha+".js") if old_view_sha else None
    if old_view is not None:
        if not old_view.exists(): shutil.copyfile(view,old_view)
        assert sha(old_view)==old_view_sha, "旧ビュー退避の内容不一致"
    created=[];committed=False
    try:
        for path,text in ((staged,serialized),(staged_view,rendered)):
            with path.open("x",encoding="utf-8",newline="\n") as stream:
                created.append(path);stream.write(text)
        assert sha(target)==expected_sha, "保存直前の並行更新"
        assert (sha(view) if view.exists() else None)==old_view_sha, "ビューの並行更新"
        staged.replace(target);committed=True
        staged_view.replace(view)
        assert sha(target)==new_sha and sha(view)==view_sha, "置換後の内容不一致"
    except BaseException:
        if committed:
            assert sha(target)==new_sha, "置換後に別更新を検出したため旧版で上書きしない"
            with rollback.open("xb") as output, snapshot.open("rb") as source:
                created.append(rollback);shutil.copyfileobj(source,output)
            assert sha(rollback)==expected_sha
            rollback.replace(target)
            # 通常のビュー置換失敗なら旧ビューのまま。置換後検査の失敗にも復元を対応させる。
            if view.exists() and sha(view)==view_sha:
                if old_view is None: view.unlink()
                else: shutil.copyfile(old_view,view)
            assert sha(target)==expected_sha
        raise
    finally:
        for path in created:
            if path.exists(): path.unlink()
    return dict(previous_sha256=expected_sha,new_sha256=new_sha,affected_ids=sorted(ids),
                view_sha256=view_sha,other_rows_unchanged=True,other_row_count=len(others),
                validation_scope="全行構造・対象行の全根拠SHA・対象外の内容不変。過去索引の当時指紋は保持。",
                concurrency_scope="本保存関数は排他ファイル、他の書込器は置換直前/直後のSHAで検出。外部書込器の原子的な排他を保証するものではない。")


def register_plan(plan: dict) -> dict:
    """共通checkで重複を照合し、結果全文を外部根拠として新試行を登録する。

    引数: plan(dict)。返り値: dictは事前照合証跡のパスと指紋。
    """
    m = manager()
    assert plan["id"] == IDENT
    assert plan.get("name") and plan.get("purpose") in ("新仮説","新データ","不具合修正","独立再検証","条件比較")
    assert all(plan.get(k) for k in ("question","change","repeat_reason"))
    check_sha=sha(m.DATA/"trials.json")
    # manage.py check --proposal が呼ぶ同一関数を使用する。
    print("共通の試行照合を実行します。金融再生はまだ開始しません。", flush=True)
    result = m.check(plan)
    assert sha(m.DATA/"trials.json")==check_sha, "重複照合中の並行更新"
    assert result["proposal_complete"]
    exact = [item for item in result["matches"] if item["kind"] == "完全同一"]
    assert not exact, "同じ条件と入力の保存結果は再利用する"
    result_path = HERE / "事前照合165.json"
    save(result_path, result)
    value = m.load(deep=False)
    target = m.DATA / "trials.json"
    old_sha = value["source_sha256"]["trials.json"]
    assert old_sha==check_sha, "重複照合と読込の間の並行更新"
    rows = value["trials"]["trials"]
    assert IDENT not in {r["id"] for r in rows}
    assert set(plan["compares_to"]) <= {r["id"] for r in rows}
    others = old_rows(rows, set())
    # ----------------------------------------
    # 詳細照合は独立JSONに残す。巨大な過去照合本文を台帳内へ再帰的に複製しない。
    row = dict(plan, status="未実行", preflight=dict(proposal_complete=True,
        complete_result=record(result_path), match_count=len(result["matches"]), exact_count=0),
        evidence=[record(result_path)])
    rows.append(row)
    outcome = write_registry(m, value, old_sha, [row], others)
    save(HERE / "登録更新証跡165.json", dict(passed=True, registration=True, spec_sha256=canonical(plan["spec"]), **outcome))
    return record(result_path)


def complete(public_check: Path) -> None:
    """公開成果・独立監査を確認し、この試行だけ検証済みへ更新する。

    引数: public_check(Path)。返り値: None。
    """
    verify_receipt()
    checked = read(public_check)
    assert checked["passed"] and checked["sessions"] == 27 and checked["cases"] == 378
    assert checked["method_count"] == 14 and checked["new_app_deployment"] is False
    assert checked["financial_audit_passed"] and checked["workbook_audit_passed"] and checked["manual_render_review_passed"]
    for source in checked["files"]:
        verify(source)
    done = read(HERE / "再生全完了165.json")
    assert done["completed"] and done["returncode"] == 0 and not done["reselection_after_confirmation"]
    for source in done["proofs"]+[done["freeze"]]:
        verify(source)
    m = manager()
    value = m.load(deep=False)
    old_sha = value["source_sha256"]["trials.json"]
    rows = value["trials"]["trials"]
    row = next(r for r in rows if r["id"] == IDENT)
    assert row["status"] == "未実行"
    others = old_rows(rows, {IDENT})
    spec_sha = canonical(row["spec"])
    row["status"] = "検証済み"
    row["evidence"] = list(row.get("evidence",[]))+checked["files"]+[record(public_check),record(HERE/"再生全完了165.json"),record(Path(__file__))]
    row["readme"] = checked["readme"]["path"]
    row["report"] = checked["workbook"]["path"]
    row["result_note"] = checked["conclusion"]
    assert canonical(row["spec"]) == spec_sha
    outcome = write_registry(m, value, old_sha, [row], others)
    save(HERE / "試行完了証跡165.json", dict(passed=True,status="検証済み",spec_changed=False,**outcome))
    print("00165を検証済みへ更新しました。条件と他試行は変更していません。", flush=True)


def main() -> None:
    """公開検算後の試行状態更新を行う。

    引数: CLI --public-check(Path)。返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-check", type=Path, default=HERE/"公開照合165.json")
    args = parser.parse_args()
    complete(args.public_check)


if __name__ == "__main__":
    main()
