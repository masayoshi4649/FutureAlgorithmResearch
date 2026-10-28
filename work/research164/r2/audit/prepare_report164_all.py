"""固定済み両巡の独立会計を連結し、第一巡報告を変更せずExcel入力を作る。"""
from collections import defaultdict
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[4]
FIRST=ROOT/"work/research164"
WORK=FIRST/"r2"
HERE=WORK/"audit"
sys.path.insert(0,str(FIRST/"audit"))
from audit_results164 import read,save,record
from prepare_report164 import groups


def main():
    """全864固有条件場と非重複の時間割だけを表示会計へまとめる。

    引数: なし。返り値: None。新規金融再生はしない。
    """
    first_path=FIRST/"report_data164.json"; prior_fingerprint=record(first_path)
    original=read(first_path)
    a=read(FIRST/"audit/audit164.json"); b=read(HERE/"audit164r2.json")
    assert a["passed"] and a["totals"]["cases"]==540
    assert b["passed"] and b["totals"]["cases"]==324
    for proof in (a,b):
        for item in proof["results"]:
            path=ROOT/item["path"]
            assert record(path)==item,"監査済み場記録の変更"
            checked_source=read(path)["source"]
            assert record(ROOT/checked_source["path"])==checked_source,"監査済み約定成果の変更"
    frozen=read(WORK/"results/selection_frozen164r2.json")
    configs=read(WORK/"engine/configs164r2.json")
    by_method=defaultdict(list); checked={}
    for scene in read(WORK/"inputs164r2.json")["sessions"]:
        result=read(HERE/"結果監査"/(scene["session"]+".json")); assert result["passed"]
        checked[scene["session"]]=result
        for r in result["rows"]:
            row=dict(session=scene["session"],kind=scene["kind"],split=scene["split"],direction=result["direction"],profit=r["profit"],loss=r["loss"],net=r["net"],
                minimum_equity=r["risk"]["min_equity"],maximum_dd=r["risk"]["max_drawdown"],peak_equity=r["peak_equity"],new_orders=r["new_orders"])
            assert abs(row["profit"]-row["loss"]-row["net"])<1e-6
            by_method[r["id"]].append(row)
    new=[]
    for c in configs:
        rows=sorted(by_method[c["id"]],key=lambda x:x["session"]); assert len(rows)==27
        total=0
        for row in rows:
            total+=row["net"]; row["cumulative"]=total
        new.append(dict(id=c["id"],scope=c["scope"],description=c["description"],selected=frozen["selected"][c["scope"]]==c["id"],configuration=c,rows=rows,summary=groups(rows),round="第二巡"))
    second=dict(methods=new,selected=frozen["selected"],sources=[record(HERE/"audit164r2.json"),record(WORK/"results/selection_frozen164r2.json")],accounting=original["accounting"],new_financial_replays=0,known_development=True)
    save(WORK/"report_data164r2.json",second)
    methods=deepcopy(original["methods"])+new
    assert len(methods)==len({m["id"] for m in methods})==32
    for method in methods:
        method.setdefault("round","第一巡")
        method["first_round_selected"]=original["selected"][method["scope"]]==method["id"]
        method["second_round_selected"]=frozen["selected"][method["scope"]]==method["id"]
        method["selected"]=method["second_round_selected"]
    rankings={}
    for scope in ("Day","PreUS","PostUS"):
        candidates=[]
        for method in [m for m in methods if m["scope"]==scope]:
            front=[r for r in method["rows"] if r["split"] in ("train","validation")]
            assert len(front)==20
            losses=[-r["net"] for r in front if r["net"]<0]
            total=sum(r["net"] for r in front)
            average=sum((Fraction(str(x)) for x in losses),Fraction())/max(1,len(losses))
            key=(total<=0,sum(r["new_orders"]==0 for r in front),len(losses),average,max(0,-min(r["minimum_equity"] for r in front)),-total,method["id"])
            candidates.append((key,method["id"]))
        rankings[scope]=[item[1] for item in sorted(candidates)]
        assert rankings[scope]==[r["id"] for r in frozen["ranking"][scope]],"別式の前40順位不一致"
        assert rankings[scope][0]==frozen["selected"][scope]
    indexed={m["id"]:{r["session"]:r for r in m["rows"]} for m in methods}
    schedule_defs=[("基準の時間割","NK225_P164_00","NK225_U164_00"),
        ("第一巡前40で固定",original["selected"]["PreUS"],original["selected"]["PostUS"]),
        ("第二巡前40で固定",frozen["selected"]["PreUS"],frozen["selected"]["PostUS"])]
    schedules=[]
    for name,pre,post in schedule_defs:
        existing=next((s for s in schedules if s["pre"]==pre and s["post"]==post),None)
        if existing:
            existing["aliases"].append(name); continue
        rows=[]; total=0
        for session in sorted(indexed[pre]):
            left,right=indexed[pre][session],indexed[post][session]
            pair=next(x for x in checked[session]["schedule_overlap"] if x["pre"]==pre and x["post"]==post)
            assert pair["no_overlap"] and pair["shared_cap_ok"]
            total+=left["net"]+right["net"]
            rows.append(dict(session=session,split=left["split"],direction=left["direction"],profit=left["profit"]+right["profit"],loss=left["loss"]+right["loss"],net=left["net"]+right["net"],cumulative=total,
                minimum_equity=min(left["minimum_equity"],left["net"]+right["minimum_equity"]),maximum_dd=max(left["maximum_dd"],right["maximum_dd"],left["peak_equity"]-left["net"]-right["minimum_equity"]),
                new_orders=left["new_orders"]+right["new_orders"]))
        schedules.append(dict(name=name,aliases=[name],pre=pre,post=post,synthetic_method_id=None,rows=rows,summary=groups(rows)))
    merged=dict(methods=methods,schedules=schedules,selected=frozen["selected"],first_round_selected=original["selected"],second_round_selected=frozen["selected"],
        sources=[prior_fingerprint,record(WORK/"report_data164r2.json"),record(FIRST/"audit/audit164.json"),record(HERE/"audit164r2.json")],accounting=original["accounting"],
        new_financial_replays=0,known_development=True,independent_unseen=False,
        note="第一巡と第二巡は固定した別ID。第二巡は第一巡全54場を確認後の追加開発。夜合計は構成IDを列挙した時間割であり手法IDではない。")
    save(FIRST/"report_data164_all.json",merged)
    assert record(first_path)==prior_fingerprint
    proof=dict(passed=True,methods=32,sessions=54,distinct_cases=864,first_round_unchanged=True,new_financial_replays=0,
        independently_recounted_front_rankings=rankings,selection_matches=True,
        first_audit=record(FIRST/"audit/audit164.json"),second_audit=record(HERE/"audit164r2.json"),first_report=prior_fingerprint,second_report=record(WORK/"report_data164r2.json"),combined_report=record(FIRST/"report_data164_all.json"),
        schedules=[dict(pre=s["pre"],post=s["post"],aliases=s["aliases"],rows=len(s["rows"])) for s in schedules])
    save(FIRST/"audit/audit164_all.json",proof)
    print("32手法864条件場を連結。第一巡不変・新金融0。")


if __name__=="__main__":
    main()
