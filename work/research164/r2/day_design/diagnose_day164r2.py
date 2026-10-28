"""第二巡の保存会計を第一巡へ対応付ける。金融再生や条件選択を行わない。"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
from collections import defaultdict

FIRST_ROOT=Path(__file__).resolve().parents[2]
_spec=importlib.util.spec_from_file_location("day164_diagnosis_fixed",FIRST_ROOT/"day_design/diagnose_day164.py")
first=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(first)


def verify_complete(root:Path,name:str) -> dict:
    """全金融完了と各段階・結果指紋を確認する。

    引数: root(Path)、name(str)。返り値: 絶対結果パス対SHAのdict。
    """
    complete=first.read(root/name);assert complete["completed"] is True and complete["returncode"]==0
    project=FIRST_ROOT.resolve().parents[1];out={}
    for ref in complete["proofs"]:
        p=Path(ref["path"]);p=p if p.is_absolute() else project/p;assert first.digest(p)==ref["sha256"]
        proof=first.read(p);assert proof["completed"] is True and proof["sources_unchanged"] is True
        for item in proof["results"]:
            path=Path(item["path"]);path=path if path.is_absolute() else project/path;out[path.resolve()]=item["sha256"]
    return out


def group_parent(rows:list[dict]) -> dict:
    """実玉を同じ元Source親へ分類する。

    引数: rows(list)。返り値: 親別dict。
    """
    out=defaultdict(list)
    for row in rows:out[row["parent"]].append(row)
    return out


def comparison(session:str,method:str,reference:str,rows:list[dict],oldrows:list[dict]) -> list[dict]:
    """親単位で新旧初回・追加・再参加損益を分ける。

    引数: session/method/reference(str)、rows/oldrows(list)。返り値: list。
    """
    a=group_parent(rows);b=group_parent(oldrows);out=[]
    for parent in sorted(set(a)|set(b)):
        new=sum(x["gross"] for x in a[parent]);old=sum(x["gross"] for x in b[parent]);out.append(dict(session=session,method=method,reference=reference,parent=parent,gross=new,reference_gross=old,delta=new-old,new_lots=a[parent],reference_lots=b[parent]))
    return out


def main()->None:
    """第二巡全完了後だけ第一巡と同じ価格・時価基準で再集計する。

    引数: CLI --raw/--out。返り値: None。
    """
    parser=argparse.ArgumentParser();parser.add_argument("--raw",action="store_true");parser.add_argument("--out",type=Path);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];fixed=verify_complete(FIRST_ROOT,"再生全完了164.json");current=verify_complete(root,"再生全完了164r2.json")
    out=args.out or root/"day_design/diagnosis";assert not out.exists(),"既存診断を上書きしない";out.mkdir(parents=True)
    allrows=[];comparisons=[];caps=[];sessions=[];sources=[]
    refs={"NK225_D164_12":["NK225_D164_00","NK225_D164_01","NK225_D164_09"],"NK225_D164_13":["NK225_D164_07","NK225_D164_00"],"NK225_D164_14":["NK225_D164_12","NK225_D164_13","NK225_D164_00"],"NK225_D164_15":["NK225_D164_14","NK225_D164_08"]}
    for path in sorted(p for p in current if p.name.endswith("_Day.json")):
        assert first.digest(path)==current[path];data=first.read(path);scene=data["scene"]
        prior_path=next(p for p in fixed if p.name==path.name);assert first.digest(prior_path)==fixed[prior_path];prior=first.read(prior_path)
        raw=first.raw_rows(scene) if args.raw else None
        cases={c["config"]["id"]:c for c in prior["cases"]+data["cases"]}
        needed=set(refs)|{m for v in refs.values() for m in v}
        rows={m:first.measure_lots(scene,cases[m],raw) for m in needed}
        for c in data["cases"]:
            method=c["config"]["id"];allrows+=rows[method];sessions.append(dict(session=scene["session"],method=method,summary=first.summarize(rows[method]),risk=c["actual"]["Risk"]))
            for reference in refs[method]:comparisons+=comparison(scene["session"],method,reference,rows[method],rows[reference])
        # ----------------------------------------
        # 13対07は数量だけでなく発注判断時刻・実建値・初回/追加の固有損益を保持します。
        new=cases["NK225_D164_13"];old=cases["NK225_D164_07"]
        for parent,cap in (new.get("delay_quantity_caps") or {}).items():
            a=[x for x in rows[new["config"]["id"]] if x["parent"]==parent];b=[x for x in rows[old["config"]["id"]] if x["parent"]==parent]
            initial=lambda values:[dict(role=x["role"],quantity=x["quantity"],entry=x["entry"],entry_time=x["entry_time"],gross=x["gross"],best=x["best"],worst=x["worst"]) for x in values if x["role"] in ("initial","delayed_initial")]
            parents=new["parents"];p=parents[parent];assert p["Factor"]<=cap["OriginalDesired"]/max(1,cap["NativeInitial"])+1e-9
            caps.append(dict(session=scene["session"],parent=parent,cap=cap,factor=p["Factor"],initial_new=initial(a),initial_old=initial(b),
                             new_role_summary=first.summarize(a),old_role_summary=first.summarize(b),
                             new_decisions=[x for x in new.get("decisions") or [] if x["Parent"]==parent],old_decisions=[x for x in old.get("decisions") or [] if x["Parent"]==parent]))
        sources.append(dict(path=str(path),sha256=current[path],prior_path=str(prior_path),prior_sha256=fixed[prior_path],raw_sha256=raw["sha256"] if raw else None))
    assert len(sessions)==27*4
    summary={m:first.summarize([r for r in allrows if r["method"]==m]) for m in refs}
    content=dict(new_financial_replays=0,purpose="保存済み第一巡と第二巡の数量・実建値・役割損益比較。新しい入口精度の証明とはしない。",sources=sources,summary=summary,sessions=sessions,quantity_cap_pairs=caps,parent_changes=sorted(comparisons,key=lambda x:x["delta"]),lots=allrows)
    (out/"日中数量上限と防御の比較164r2.json").write_text(json.dumps(content,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(dict(sessions=27,method_cases=108,quantity_cap_pairs=len(caps),new_financial_replays=0),ensure_ascii=False))

if __name__=="__main__":main()
