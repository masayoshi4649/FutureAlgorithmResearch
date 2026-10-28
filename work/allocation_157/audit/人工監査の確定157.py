"""金融前の独立人工検査と対象指紋を確定する。金融再生は呼ばない。"""

from datetime import datetime
from pathlib import Path
import hashlib
import json
import subprocess
import sys

BASE=Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]


def fingerprint(path: Path) -> dict:
    """検査したファイルの全内容をハッシュ化する。

    引数: path(Path)。返り値: dictは相対位置・SHA256・バイト数。
    """
    return {"path":path.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"bytes":path.stat().st_size}


def main() -> None:
    """人工結果と監査コピーの完全一致を確認して登録前ゲートを保存する。

    引数: なし。返り値: None。不一致時は例外で停止する。
    """
    events=[json.loads(x) for x in (BASE/"audit/独立人工検査157.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    assert not any(x.get("Action")=="fail" for x in events)
    tests=[x["Test"] for x in events if x.get("Action")=="pass" and x.get("Test")]
    assert len(tests)==28 and len(set(tests))==28
    assert any(x.get("Action")=="pass" and x.get("Package")=="futurealgorithm/sessiontrader" and not x.get("Test") for x in events)
    sources=sorted(x for x in (BASE/"engine_go").rglob("*") if x.is_file() and (x.suffix in (".go",".toml") or x.name in ("go.mod","go.sum")))
    for source in sources:
        copied=BASE/"audit_engine_go"/source.relative_to(BASE/"engine_go")
        assert copied.exists() and source.read_bytes()==copied.read_bytes(),f"検査コピー不一致: {source}"
    sources += [BASE/name for name in ("spec157.json","spec157.md","configs157.json")]
    assert len(json.loads((BASE/"configs157.json").read_text(encoding="utf-8")))==23
    for file in ("会計恒等式の人工検査157.py","test_raw157.py"):
        run=subprocess.run([sys.executable,"-X","utf8",file],cwd=BASE/"audit",capture_output=True,text=True,encoding="utf-8")
        (BASE/"audit"/(Path(file).stem+".txt")).write_text(run.stdout+run.stderr,encoding="utf-8")
        assert run.returncode==0,(file,run.stdout,run.stderr)
    evidence=[BASE/"audit/独立人工検査157.jsonl",BASE/"audit/会計恒等式の人工検査157.json",BASE/"audit/会計恒等式の人工検査157.txt",BASE/"audit/test_raw157.txt",BASE/"audit/raw157.py",BASE/"audit/test_raw157.py"]
    evidence += sorted((BASE/"audit_engine_go").glob("*audit157_test.go"))
    result={"passed":True,"created_at":datetime.now().astimezone().isoformat(),"financial_replays":0,"configuration_count":23,"planned_case_count":621,"tests":{"go_total":28,"shared_go":7,"independent_go":21,"math_accounting":6,"raw_auditor":4,"total":38},"test_names":tests,"sources":[fingerprint(x) for x in sources],"evidence":[fingerprint(x) for x in evidence],"checks":{"source_copy_exact":True,"next_normal_quote_only":True,"reserved_cap":True,"source_parent_rejection_fixed":True,"source_target_partial_mapping":True,"current_stop_before_new":True,"support_endpoint_and_peer_prefix":True,"support_nonfinite_rejected":True,"adverse_extreme_during_low_support":True,"parent_net_bbo_identity":True,"cover_without_base_rejected":True,"unknown_resets_confirmation":True,"minimum_quantity_after_capacity":True,"artificial_reader_cutoff_and_null_volume":True,"artificial_serial_parallel_identical":True},"limits":["金融結果はまだ測定していない。人工PASSは収益性の根拠ではない。","reader直列並列は準備未完成の人工列で売買0。実売買通知・数量・約定経路は別の人工検査。","ラージBBOの次正常原行全量模型。実micro約定の部分約定・遅延は保証しない。","H/Nは親内相殺。Canonical元玉の保有とQ実口座の差引玉を区別。"]}
    (BASE/"人工監査確定157.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"passed":True,"source_files":len(sources),"tests":result["tests"]},ensure_ascii=False))


if __name__=="__main__":
    main()
