"""第2巡の隔離実装をコピーし、金融前の人工検査と指紋を確定する。"""

from pathlib import Path
from datetime import datetime
import hashlib
import json
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parents[1]
ROOT=HERE.parents[2]


def fingerprint(path: Path) -> dict:
    """対象ファイルの内容と相対位置を記録する。

    引数: path(Path)。返り値: dictは位置とSHA256。
    """
    return {"path":path.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> None:
    """凍結予定の実装を実市場へ接続せず検査し、登録ゲートを保存する。

    引数: なし。返り値: None。不一致ではpassed:falseを保存して停止する。
    """
    proof={"passed":False,"financial_replays":0,"created_at":datetime.now().astimezone().isoformat()}
    target=HERE/"人工監査確定1572.json"
    try:
        source=HERE/"engine_go";copy=HERE/"audit_engine_go"
        originals=sorted(p for p in source.rglob("*") if p.is_file() and (p.suffix in (".go",".toml") or p.name in ("go.mod","go.sum")))
        specifications=[HERE/x for x in ("spec1572.json","spec1572.md","configs1572.json")]
        before=[fingerprint(p) for p in originals+specifications]
        for p in originals:
            dest=copy/p.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        for p in (HERE/"audit_tests").glob("*.go"):shutil.copy2(p,copy/p.name)
        for p in originals:assert p.read_bytes()==(copy/p.relative_to(source)).read_bytes()
        # ----------------------------------------
        # 元S01、原資料読取、台帳と注文政策のうち変更対象外の源を初巡へ照合します。
        unchanged=sorted((source/"internal").rglob("*.go"))+[source/x for x in ("ledger157.go","replay.go","jobs.go")]
        for p in unchanged:assert p.read_bytes()==(HERE.parent/"engine_go"/p.relative_to(source)).read_bytes(),str(p)
        run=subprocess.run(["go","test","./...","-count=1","-json"],cwd=copy,capture_output=True,text=True,encoding="utf-8")
        log=HERE/"audit/独立人工検査1572.jsonl";log.write_text(run.stdout,encoding="utf-8")
        assert run.returncode==0,run.stderr+run.stdout
        names=[x["Test"] for line in run.stdout.splitlines() if (x:=json.loads(line)).get("Action")=="pass" and "Test" in x]
        independent=[x for x in names if x.startswith("TestAudit")]
        assert len(names)==23 and len(independent)==9
        raw=subprocess.run([sys.executable,"-X","utf8",str(HERE/"audit/test_raw_support1572.py")],capture_output=True,text=True,encoding="utf-8")
        rawlog=HERE/"audit/支持検算器の人工1572.txt";rawlog.write_text(raw.stdout+raw.stderr,encoding="utf-8")
        assert raw.returncode==0 and "Ran 4 tests" in raw.stderr,raw.stderr
        configurations=json.loads((HERE/"configs1572.json").read_text(encoding="utf-8-sig"))
        assert len(configurations)==40 and len({x["id"] for x in configurations})==40
        after=[fingerprint(p) for p in originals+specifications];assert before==after
        proof.update(passed=True,configuration_count=40,planned_case_count=1080,tests={"shared_go":14,"independent_go":9,"go_total":23,"independent_raw_support":4,"total":27},test_names=names,sources=after,source_copy_matches=True,unchanged_source_files=[fingerprint(p) for p in unchanged],previous_audit=fingerprint(HERE.parent/"金融監査157.json"))
        evidence=[log,rawlog,HERE/"audit/raw_support1572.py",HERE/"audit/test_raw_support1572.py",HERE/"audit/金融前の反証157r2.md",Path(__file__)]+list((HERE/"audit_tests").glob("*.go"))
        proof["evidence"]=[fingerprint(p) for p in evidence]
    except Exception as error:
        proof["error"]=repr(error)
        target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        raise
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":True,"source_files":len(originals),"tests":proof["tests"],"sha256":hashlib.sha256(target.read_bytes()).hexdigest()},ensure_ascii=False))


if __name__=="__main__":
    main()
