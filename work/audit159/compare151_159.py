"""旧00151 P05と現159 N00の既知25夜を保存約定だけで比較する。"""
from collections import defaultdict
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work/audit159"


def read(path: Path) -> dict:
    """保存JSONを読む。

    引数: path(Path)。返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def old_events(row: dict) -> dict:
    """旧151の独立新規玉・返済から同額microの経済経路を復元する。

    引数: row(dict)。返り値: dictは原行・時刻・担当・方向・価格別数量。
    """
    out = defaultdict(int)
    for lot in row["lot_details"]:
        key = (lot["phase"],lot["owner"],lot["entry_index"],lot["entry_time"],"new",lot["side"],lot["price"])
        out[key] += lot["original_quantity"]*10
        for close in lot["closes"]:
            key = (lot["phase"],lot["owner"],close["index"],close["time"],"close",-lot["side"],close["price"])
            out[key] += close["quantity"]*10
    return dict(out)


def new_events(case: dict) -> dict:
    """159の保存約定を同じ経済経路へ集約する。

    引数: case(dict)。返り値: dictは比較列。
    """
    out = defaultdict(int)
    for event in case["actual"]["Events"] or []:
        order=event["Order"]
        phase,owner=order["Owner"].split("/",1)
        key=(phase,owner,event["FillIndex"],event["FillTime"],"close" if order.get("Targets") else "new",order["Side"],event["Price"])
        out[key]+=order["Quantity"]
    return dict(out)


def main() -> None:
    """旧25夜の前後収支と全時刻経済経路を比較する。

    引数: なし。返り値: None。新たな金融再生を行わない。
    """
    done=read(ROOT/"work/research159/金融実行159.json")
    assert done["exit_code"]==0
    old_path=ROOT/"work/hedge151/report151.json"
    old=next(m for m in read(old_path)["methods"] if m["id"]=="P05")
    rows=[]
    for row in old["rows"]:
        path=ROOT/"work/night159/results_go"/(row["session"]+".json")
        case=next(c for c in read(path)["cases"] if c["config"]["id"]=="N00")
        a,b=old_events(row),new_events(case)
        diffs=[{"key":k,"old_quantity":a.get(k,0),"new_quantity":b.get(k,0)} for k in sorted(a.keys()|b.keys()) if a.get(k,0)!=b.get(k,0)]
        phases=defaultdict(float)
        for e in case["actual"]["Events"] or []:
            phases[e["Order"]["Owner"].split("/")[0]]+=e["Gross"]
        pre,post=phases["前半"],phases["後半"]
        same_net=pre==row["target_net"] and post==row["post"]["net"] and pre+post==row["net"]
        rows.append({"session":row["session"],"same_economic_path":not diffs,"same_pre_post_net":same_net,"old_pre_net":row["target_net"],"new_pre_net":pre,"old_post_net":row["post"]["net"],"new_post_net":post,"old_net":row["net"],"new_net":pre+post,"economic_groups":len(a),"first_differences":diffs[:5],"result_sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    report={"passed":all(r["same_economic_path"]and r["same_pre_post_net"]for r in rows),"sessions":len(rows),"old_net":sum(r["old_net"]for r in rows),"new_net":sum(r["new_net"]for r in rows),"new_financial_replays":0,"scope":"00151 P05と159 N00の25既知夜・元mini数量をmicro10倍へ換算。同一原行/時刻/方向/担当/約定価格の全売買数量と前後収支。親/玉の利益損失分類は一致対象外。追加有効性の証拠に数えない。","old_report_sha256":hashlib.sha256(old_path.read_bytes()).hexdigest(),"rows":rows}
    (WORK/"旧151と159夜間基準の照合.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items()if k not in ("rows","scope")},ensure_ascii=False))


if __name__=="__main__":
    main()
