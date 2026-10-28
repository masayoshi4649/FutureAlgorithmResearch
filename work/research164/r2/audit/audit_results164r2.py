"""第二巡の完了許可後だけ保存約定を独立再会計する。金融戦略は実行しない。"""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import sys
import traceback
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
FIRST = ROOT / "work/research164"
WORK = FIRST / "r2"
HERE = WORK / "audit"
sys.path.insert(0, str(FIRST / "audit"))
from audit_results164 import read, save, record, close, read_market, normal_mask, raw_risk, reserved_cap, reconcile, overlap


def without_known_metadata(value):
    """売買に使わない既知履歴表示だけを除外する。

    引数: value(JSON値)。返り値: JSON値。
    """
    if isinstance(value, dict):
        return {k:without_known_metadata(v) for k,v in value.items() if k != "previously_used"}
    if isinstance(value, list):
        return [without_known_metadata(v) for v in value]
    return value


def verify_short(raw, good, index, value):
    """当時までの正常過去端と窓内異常から5/15秒速度を独立算出する。

    引数: raw/good(ndarray)、index(int)、value(dict)。返り値: int。
    """
    at = float(raw[index, 0])
    close(value["Time"], at, "短期判断時計")
    valid_now = bool(normal_mask(raw[index:index+1])[0])
    if valid_now:
        close(value["Mid"], float(np.mean(raw[index,2:4])), "短期現在中値")
    for name, span in (("Five",5),("Fifteen",15)):
        w=value[name]
        candidates=good[(good<=index)&(raw[good,0]<=at-span)]
        known=False
        if valid_now and len(candidates):
            old=int(candidates[-1])
            elapsed=at-float(raw[old,0]); delay=elapsed-span
            known=delay<=15 and elapsed>0 and bool(np.all(normal_mask(raw[old:index+1]))) and not bool(np.any(np.diff(raw[old:index+1,0])>15))
            close(w["Endpoint"],raw[old,0],"短期端点")
            close(w["Elapsed"],elapsed,"実経過")
            close(w["Delay"],delay,"端点遅れ")
            if known:
                move=float(np.mean(raw[index,2:4])-np.mean(raw[old,2:4]))
                close(w["Move"],move,"短期円幅")
                close(w["Speed"],move/elapsed,"短期円毎秒")
        assert w["Known"] == known, (index,name,w,known)
    return 1


def scene_check(scene):
    """一場の全条件と全正常原板時価・Source不変を検査する。

    引数: scene(dict)。返り値: dict。売買判断の再実行は行わない。
    """
    stage="train_validation" if scene["split"] in ("train","validation") else "confirmation"
    path=WORK/"results"/stage/(scene["session"]+".json")
    original_path=FIRST/"results"/stage/(scene["session"]+".json")
    saved,old=read(path),read(original_path)
    before=record(path)
    source_key="source" if scene["kind"]=="Day" else "sources"
    assert without_known_metadata(saved[source_key])==without_known_metadata(old[source_key]), "独立Sourceの経路変更"
    raw,reference=read_market(scene,"NK225")
    good=np.flatnonzero(normal_mask(raw))
    rows=[]; totals=Counter()
    for case in saved["cases"]:
        ledger=case["actual"]
        start=scene["start"] if scene["kind"]=="Day" else case["Start"]
        account=reconcile(ledger,start,ledger["LastTime"])
        assert not ledger["Pending"] and account["remaining_qty"]==0
        risk=raw_risk(raw,ledger,start)
        cap=reserved_cap(ledger)
        if scene["kind"]=="Day":
            reconcile(case["canonical"],start,case["canonical"]["LastTime"])
            assert case["projection_max_difference"]==0
            for key,fixed in (case["delay_quantity_caps"] or {}).items():
                parent=case["parents"][key]
                assert fixed["Known"] and parent["Factor"]<=fixed["OriginalDesired"]/max(1,fixed["NativeInitial"])+1e-12
                trigger=[d for d in case["decisions"] or [] if d["Parent"]==key and d["Action"]=="初回延期"]
                assert len(trigger)==1 and trigger[0]["Index"]==fixed["CapturedIndex"]
                assert trigger[0]["Desired"]==fixed["OriginalDesired"]
                for decision in case["decisions"] or []:
                    if decision["Parent"]==key and decision["Action"]=="延期解除":
                        assert decision["Accepted"]<=decision["Desired"]<=fixed["OriginalDesired"]
            decisions=case["decisions"] or []
        else:
            decisions=case["trigger_trace"] or []
            assert all(not p["Deferred"] for p in case["parents"].values())
        for decision in decisions:
            s=decision.get("Short")
            if s and s.get("Time"):
                totals["short_decisions"]+=verify_short(raw,good,int(decision["Index"]),s)
        totals.update(cases=1,events=len(ledger["Events"] or []),lots=len(ledger["Lots"]),raw_marks=len(good))
        rows.append(dict(id=case["config"]["id"],profit=account["allocation_profit"],loss=account["allocation_loss"],net=account["net"],
            risk=risk,peak_equity=ledger["Risk"]["Peak"],capacity=cap,quantities=account["quantities"],new_orders=account["entries"]))
    overlaps=[]
    if scene["kind"]=="Night":
        all_cases=old["cases"]+saved["cases"]
        for pre in [c for c in all_cases if c["config"]["scope"]=="PreUS"]:
            for post in [c for c in all_cases if c["config"]["scope"]=="PostUS"]:
                check=overlap([pre["actual"],post["actual"]])
                assert check["no_overlap"] and check["shared_cap_ok"]
                overlaps.append(dict(pre=pre["config"]["id"],post=post["config"]["id"],**check))
    assert record(path)==before
    value=dict(passed=True,session=scene["session"],source=before,raw=reference,original_source=record(original_path),native_source_unchanged=True,
        rows=rows,totals=dict(totals),schedule_overlap=overlaps,
        direction="上昇" if raw[-1,1]>raw[0,1] else "下落" if raw[-1,1]<raw[0,1] else "同値",
        direction_source=dict(first_last=float(raw[0,1]),final_last=float(raw[-1,1]),final_clock=float(raw[-1,0]),formal_close=False))
    save(HERE/"結果監査"/(scene["session"]+".json"),value)
    return value


def main():
    """完了証跡と全登録指紋を条件として324条件場を監査する。

    引数: なし。返り値: None。
    """
    proof=dict(passed=False,new_financial_replays=0,started_at=datetime.now().astimezone().isoformat())
    try:
        complete=read(WORK/"再生全完了164r2.json")
        assert complete["completed"] and complete["returncode"]==0 and complete["cases"]==324
        receipt=read(WORK/"登録受領164r2.json")
        for x in receipt["sources"]:
            assert record(ROOT/x["path"])["sha256"]==x["sha256"]
        totals=Counter(); results=[]
        with ProcessPoolExecutor(max_workers=4) as pool:
            jobs=[pool.submit(scene_check,s) for s in read(WORK/"inputs164r2.json")["sessions"]]
            for future in as_completed(jobs):
                value=future.result(); totals.update(value["totals"])
                results.append(record(HERE/"結果監査"/(value["session"]+".json")))
                print(value["session"],len(results),flush=True)
        assert totals["cases"]==324 and len(results)==54
        for x in receipt["sources"]:
            assert record(ROOT/x["path"])["sha256"]==x["sha256"]
        proof.update(passed=True,totals=dict(totals),results=results,sources_unchanged=True,complete=record(WORK/"再生全完了164r2.json"),finished_at=datetime.now().astimezone().isoformat())
    except Exception:
        proof["error"]=traceback.format_exc(); save(HERE/"audit164r2.json",proof); raise
    save(HERE/"audit164r2.json",proof)


if __name__=="__main__":
    main()
