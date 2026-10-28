"""第三巡の元玉出口と数量管理の分離を、金融前に独立コピーで検査する。"""

from pathlib import Path
from datetime import datetime
import hashlib
import json
import shutil
import subprocess

HERE=Path(__file__).resolve().parents[1]
ROOT=HERE.parents[2]
SECOND=HERE.parent/"round2"


def fingerprint(path: Path) -> dict:
    """対象の相対位置と内容指紋を保存する。

    引数: path(Path)。返り値: dictは位置とSHA256。
    """
    return {"path":path.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> None:
    """共有実装を変更せず人工検査を実行し、登録用証跡を固定する。

    引数: なし。返り値: None。実相場の再生・API接続は行わない。
    """
    target=HERE/"人工監査確定1573.json"
    proof={"passed":False,"financial_replays":0,"created_at":datetime.now().astimezone().isoformat()}
    try:
        prior=json.loads((SECOND/"金融監査1572.json").read_text(encoding="utf-8"))
        assert prior["passed"] and prior["case_count"]==1080
        source=HERE/"engine_go";copy=HERE/"audit_engine_go"
        originals=sorted(p for p in source.rglob("*") if p.is_file() and (p.suffix in (".go",".toml") or p.name in ("go.mod","go.sum")))
        specifications=[HERE/x for x in ("spec1573.json","spec1573.md","configs1573.json")]
        before=[fingerprint(p) for p in originals+specifications]
        for p in originals:
            dest=copy/p.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        for p in (HERE/"audit_tests").glob("*.go"):shutil.copy2(p,copy/p.name)
        for p in originals:assert p.read_bytes()==(copy/p.relative_to(source)).read_bytes()
        unchanged=sorted((source/"internal").rglob("*.go"))+[source/x for x in ("ledger157.go","replay.go","jobs.go","support157.go","input155.go")]
        for p in unchanged:assert p.read_bytes()==(SECOND/"engine_go"/p.relative_to(source)).read_bytes(),str(p)
        result=subprocess.run(["go","test","./...","-count=1","-json"],cwd=copy,capture_output=True,text=True,encoding="utf-8")
        log=HERE/"audit/独立人工検査1573.jsonl";log.write_text(result.stdout,encoding="utf-8")
        assert result.returncode==0,result.stderr+result.stdout
        names=[r["Test"] for line in result.stdout.splitlines() if (r:=json.loads(line)).get("Action")=="pass" and "Test" in r]
        independent=[n for n in names if n.startswith("TestAudit")]
        assert len(names)==27 and len(independent)==7
        configs=json.loads((HERE/"configs1573.json").read_text(encoding="utf-8-sig"))
        assert len(configs)==12 and len({v["id"] for v in configs})==12
        after=[fingerprint(p) for p in originals+specifications];assert before==after
        proof.update(passed=True,configuration_count=12,planned_case_count=324,tests={"shared_go":20,"independent_go":7,"total":27},test_names=names,sources=after,source_copy_matches=True,unchanged_source_files=[fingerprint(p) for p in unchanged],previous_financial_audit=fingerprint(SECOND/"金融監査1572.json"))
        evidence=[log,Path(__file__),HERE/"audit/金融前の反証1573.md"]+list((HERE/"audit_tests").glob("*.go"))
        proof["evidence"]=[fingerprint(p) for p in evidence]
    except Exception as error:
        proof["error"]=repr(error);target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");raise
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":True,"source_files":len(originals),"tests":proof["tests"],"sha256":hashlib.sha256(target.read_bytes()).hexdigest()},ensure_ascii=False))


if __name__=="__main__":
    main()
