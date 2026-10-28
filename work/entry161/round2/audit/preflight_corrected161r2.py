"""登録用sessions欄の補完だけを再監査し、前監査を残して訂正証跡を保存する。"""

import copy
from datetime import datetime
import difflib
import importlib.util
import json
from pathlib import Path
import zipfile
from unittest.mock import patch

from preflight161r2 import BASE, HERE, ROOT, WORK, read, sha


def main():
    """戦略源不変と登録形式を確認し訂正版の事前監査を保存する。

    引数: なし。返り値: None。巨大台帳の読取り、登録、候補採点を行わない。
    """
    destination = HERE / "preflight161r2_corrected.json"
    assert not destination.exists() and not (WORK / "登録受領161r2.json").exists()
    assert not (WORK / "results").exists()
    prior_path = HERE / "preflight161r2.json"
    prior = read(prior_path); assert prior["passed"]
    source_name = (WORK / "register161r2.py").relative_to(ROOT).as_posix()
    changed = []
    for record in prior["sources"]:
        if sha(ROOT / record["path"]) != record["sha256"]:
            changed.append(record["path"])
    assert changed == [source_name], changed
    archived_zip = WORK / "登録失敗記録/評価前実装161r2.zip"
    with zipfile.ZipFile(archived_zip) as archive:
        old = archive.read(source_name).decode("utf-8")
    current = (WORK / "register161r2.py").read_text(encoding="utf-8")
    expected = old.replace('audit/preflight161r2.json', 'audit/preflight161r2_corrected.json')
    expected = expected.replace('"data": {"input_manifests":', '"data": {"sessions": [scene["session"] for scene in read(BASE/"inputs161.json")["sessions"]],\n                     "input_manifests":')
    assert current == expected, "登録コードの差分が事前監査参照とsessions補完だけであること"
    plan_path = WORK / "登録失敗記録/評価計画161r2.json"
    plan = read(plan_path)
    corrected = copy.deepcopy(plan)
    assert "sessions" not in plan["spec"]["data"]
    corrected["spec"]["data"]["sessions"] = [s["session"] for s in read(BASE / "inputs161.json")["sessions"]]
    assert len(set(corrected["spec"]["data"]["sessions"])) == 53
    manager_path = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    spec = importlib.util.spec_from_file_location("登録形式の独立監査161r2", manager_path)
    manager = importlib.util.module_from_spec(spec); spec.loader.exec_module(manager)
    old_local = manager.local_path
    moved_name = (WORK / "評価前実装161r2.zip").relative_to(ROOT).as_posix()
    def archived_local(name):
        """退避した旧zipだけ保存先へ解決する。

        引数: name(str)。返り値: Path。
        """
        return archived_zip if name == moved_name else old_local(name)
    bundle = dict(rules=dict(rules=[]), knowledge=dict(findings=[]), trials=dict(trials=[corrected], repetition_audit=[]), studies=dict(studies=[]))
    with patch.object(manager, "local_path", archived_local):
        manager.validate(bundle, deep=False)
        manager.validate(bundle, deep=True)
    sources = [dict(path=r["path"], sha256=sha(ROOT / r["path"])) for r in prior["sources"]]
    sources.append(dict(path=Path(__file__).relative_to(ROOT).as_posix(), sha256=sha(Path(__file__))))
    sources.append(dict(path=manager_path.relative_to(ROOT).as_posix(), sha256=sha(manager_path)))
    output = copy.deepcopy(prior)
    output.update(created_at=datetime.now().astimezone().isoformat(), sources=sources,
                  supersedes=dict(path=prior_path.relative_to(ROOT).as_posix(), sha256=sha(prior_path)),
                  registration_schema_check=dict(passed=True, deep_false=True, deep_true=True, sessions=53,
                      table_read=False, table_write=False, trial_registered=False,
                      change="spec.data.sessionsの必須欄補完と訂正監査ファイル参照のみ。候補、分位、採点仕様の変更なし。",
                      historical_zip_relocation="退避zipの位置だけ検査中に解決し、計画内容はsessions以外変更しない。",
                      source_diff=list(difflib.unified_diff(old.splitlines(), current.splitlines(), lineterm="")),
                      failed_plan=dict(path=plan_path.relative_to(ROOT).as_posix(), sha256=sha(plan_path)),
                      failed_implementation=dict(path=archived_zip.relative_to(ROOT).as_posix(), sha256=sha(archived_zip))))
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps(dict(passed=True, sources=len(sources), strategy_changes=0, schema_sessions=53, sha256=sha(destination)), ensure_ascii=False))


if __name__ == "__main__":
    main()
