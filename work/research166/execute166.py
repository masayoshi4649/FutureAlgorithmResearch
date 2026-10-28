"""初回登録源を照合してから、固定三手法の検査だけを起動する。"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import subprocess

from control166 import ROOT,HERE,read,record,verify,verify_receipt,save,check_smoke


def main() -> None:
    """実行許可と源を確認し、別保存先へ一度だけ再生する。

    引数: CLI --stage(str)、--cap(int)。返り値: None。実サービス通信はしない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument("--stage",choices=["smoke","full"],required=True)
    parser.add_argument("--cap",type=int,choices=[100,10],required=True)
    args=parser.parse_args()
    receipt=verify_receipt()
    permission=HERE/("実行許可166_"+args.stage+".json")
    permitted=read(permission)
    assert permitted["registered"] and permitted["returncode"]==0 and permitted["stage"]==args.stage
    verify(permitted["registration"])
    if args.stage=="full":check_smoke()
    out=HERE/("results_"+args.stage+"_cap"+str(args.cap))
    assert not out.exists(), "既存出力は上書きせず、新ラウンドへ保存する"
    proof=HERE/("初回実行_"+args.stage+"_cap"+str(args.cap)+".json")
    assert not proof.exists()
    started=datetime.now().astimezone().isoformat()
    command=[str(HERE/"parity166.exe"),"-root",str(ROOT),"-cap",str(args.cap),"-out",str(out),"-workers","3"]
    if args.stage=="smoke":command += ["-session","2026-09-24"]
    log=HERE/("初回実行_"+args.stage+"_cap"+str(args.cap)+".log")
    with log.open("x",encoding="utf-8") as stream:
        run=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=False)
    unchanged=True;failure=None
    try: verify_receipt()
    except (AssertionError,OSError) as error: unchanged=False;failure=str(error)
    results=sorted(out.glob("*.json"))
    expected=2 if args.stage=="smoke" else 54
    save(proof,dict(completed=run.returncode==0 and unchanged and len(results)==expected,
        returncode=run.returncode,started_at=started,finished_at=datetime.now().astimezone().isoformat(),
        stage=args.stage,cap=args.cap,product="NK225micro" if args.cap==100 else "NK225mini",
        sources_unchanged=unchanged,source_error=failure,registration=permitted["registration"],permission=record(permission),
        command=command,log=record(log),results=[record(p) for p in results],expected_result_files=expected,
        parameter_search=False,independent_unseen=False))
    print("移植照合終了: "+str(run.returncode)+" / 原資料・源の不変="+str(unchanged),flush=True)
    raise SystemExit(0 if run.returncode==0 and unchanged and len(results)==expected else 1)


if __name__=="__main__":main()
