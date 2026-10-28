"""登録源を変更せず、原資料の事前実 SHA と各実行前後の属性を監査する。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import re
import subprocess
import sys

from control166 import ROOT,HERE,MANIFEST,read,record,save,sha,verify

AUDIT=HERE/"audit/raw_inputs"
INITIAL=AUDIT/"全324原資料の事前SHA166.json"


def stat_value(path: Path) -> dict:
    """読取対象のサイズ・更新時刻・ファイル識別情報を返す。

    引数: path(Path)。返り値: dict。アクセス時刻は読取で変わり得るため比較しない。
    """
    s=path.stat()
    return dict(size=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns,device=s.st_dev,inode=s.st_ino)


def expected_sources() -> list[dict]:
    """登録済み目録の二市場・板と足の全 324 資料を確認する。

    引数: なし。返り値: list[dict]。
    """
    receipt=read(HERE/"登録受領166.json")
    verify(receipt["manifest"])
    scenes=read(MANIFEST)["sessions"]
    refs={}
    for scene in scenes:
        required={str(Path(p).resolve()) for p in scene["books"].values()}
        required.update(str(Path(p).resolve()) for intervals in scene["candles"].values() for p in intervals.values())
        fingerprints={str(Path(f["path"]).resolve()):f for f in scene["fingerprints"]}
        assert required==set(fingerprints) and len(required)==6,scene["session"]
        for path,f in fingerprints.items():
            assert path not in refs
            refs[path]=dict(path=path,session=scene["session"],sha256=f["sha256"],
                expected_bytes=f["bytes"],recorded_mtime_ns=f["mtime_ns"])
    assert len(scenes)==54 and len(refs)==324
    return [refs[p] for p in sorted(refs)]


def read_fingerprint(source: dict) -> dict:
    """1 資料を実ハッシュし、読取中も属性が変わらなかったか確認する。

    引数: source(dict)。返り値: dict。原資料を開くモードは rb だけ。
    """
    path=Path(source["path"])
    try:
        before=stat_value(path);actual=sha(path);after=stat_value(path)
        return dict(**source,actual_sha256=actual,stat=after,unchanged_during_read=before==after,
            matches_registered_sha=actual==source["sha256"],matches_recorded_size=after["size"]==source["expected_bytes"],
            matches_recorded_mtime=after["mtime_ns"]==source["recorded_mtime_ns"],error=None)
    except OSError as error:return dict(**source,error=str(error),unchanged_during_read=False,matches_registered_sha=False)


def initial() -> None:
    """全原資料を一度実ハッシュし、その後の属性比較の基準を作る。

    引数: なし。返り値: None。
    """
    assert not INITIAL.exists()
    started=datetime.now().astimezone().isoformat()
    sources=expected_sources();records=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for row in pool.map(read_fingerprint,sources):
            records.append(row)
            if len(records)%54==0:print(f"原資料SHA {len(records)}/324",flush=True)
    passed=all(r["matches_registered_sha"] and r["unchanged_during_read"] and r["matches_recorded_size"] for r in records)
    save(INITIAL,dict(passed=passed,files=324,started_at=started,finished_at=datetime.now().astimezone().isoformat(),
        manifest=record(MANIFEST),implementation=record(Path(__file__)),financial_runs=0,original_files_written=False,
        historical_mtime_equal=sum(r.get("matches_recorded_mtime",False) for r in records),records=records,
        limit="属性が変わらない内容の外部改変までは属性比較だけで保証しない。原資料への書込操作はない。"))
    assert passed,"原資料の事前指紋が不一致"
    print("324 原資料の実 SHA が全て一致しました。",flush=True)


def check(phase: str,label: str) -> Path:
    """実行前後の属性を比較し、変化分は再ハッシュして不採用と記録する。

    引数: phase(str) は before/after、label(str) は実行名。返り値: 証跡 Path。
    """
    assert re.fullmatch(r"[A-Za-z0-9_-]+",label)
    base=read(INITIAL);assert base["passed"] and base["files"]==324
    verify(base["manifest"])
    reference=base
    before_path=AUDIT/(label+"_before.json")
    if phase=="after":
        reference=read(before_path);assert reference["passed"]
        verify(reference["initial"])
    expected={r["path"]:r for r in base["records"]}
    current=expected_sources();assert {r["path"] for r in current}==set(expected)
    old={r["path"]:r["stat"] for r in reference["records"]}
    records=[]
    for row in current:
        path=Path(row["path"])
        try:
            now=stat_value(path)
            equal=now==old[str(path)] and now==expected[str(path)]["stat"]
            actual=sha(path) if not equal else None
            records.append(dict(path=str(path),stat=now,stat_unchanged=equal,
                rehashed_sha256=actual,rehash_matches_expected=actual==row["sha256"] if actual else None,error=None))
        except OSError as error:records.append(dict(path=str(path),stat_unchanged=False,error=str(error)))
    passed=all(r["stat_unchanged"] for r in records)
    output=AUDIT/(label+"_"+phase+".json")
    save(output,dict(passed=passed,result_usable=passed,phase=phase,label=label,files=324,
        created_at=datetime.now().astimezone().isoformat(),initial=record(INITIAL),
        before=record(before_path) if phase=="after" else None,implementation=record(Path(__file__)),
        changed_files=sum(not r["stat_unchanged"] for r in records),records=records,original_files_written=False,
        rule="属性変化が 1 件でもあれば再ハッシュが同値でもこの実行結果は不採用。元資料と出力は上書きしない。"))
    assert passed,"原資料属性の変化を検出。この実行結果は不採用"
    return output


def main() -> None:
    """原資料監査と、必要時だけ登録済み実行器を前後監査付きで起動する。

    引数: CLI action/label/stage/cap。返り値: None。金融起動は run の明示指定だけ。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["initial","before","after","run"])
    parser.add_argument("--label")
    parser.add_argument("--stage",choices=["smoke","full"])
    parser.add_argument("--cap",type=int,choices=[10,100])
    args=parser.parse_args()
    if args.action=="initial":initial();return
    if args.action in {"before","after"}:check(args.action,args.label);return
    assert args.stage and args.cap
    label=args.stage+"_cap"+str(args.cap)
    check("before",label)
    code=1
    try:
        code=subprocess.run([sys.executable,"-X","utf8",str(HERE/"execute166.py"),"--stage",args.stage,"--cap",str(args.cap)],cwd=ROOT).returncode
    finally:check("after",label)
    raise SystemExit(code)


if __name__=="__main__":main()
