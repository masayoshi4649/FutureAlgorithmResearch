"""00164夜間の無取引を、売買を作らず当時の入口条件だけで分解する。"""
from __future__ import annotations
from collections import Counter, defaultdict
import json
from pathlib import Path
import math
import numpy as np
import diagnose_night164 as d


def observations(scene: dict):
    """正常観測標本からGoと同じ端点・効率・範囲を独立に生成する。

    引数: scene(dict)。返り値: list[dict]。原板順序を維持し未来列を取らない。
    """
    raw=list(d.raw_quotes(scene))
    normal=[q for q in raw if q["normal"]]
    times=np.array([q["time"] for q in normal]);mids=np.array([(q["bid"]+q["ask"])/2 for q in normal]);path=np.r_[0.,np.cumsum(np.abs(np.diff(mids)))]
    indices=np.flatnonzero(np.r_[True,times[1:]!=times[:-1]])
    endpoints={h:np.searchsorted(times,times[indices]-h,side="right")-1 for h in (5,15,60,120,300)}
    out=[]
    for j,current in enumerate(indices):
        q=normal[current];f=dict(q,mid=float(mids[current]),spread=q["ask"]-q["bid"])
        for h in (5,15,60,120,300):
            k=int(endpoints[h][j]);known=k>=0 and times[current]-h-times[k] <= (1 if h<60 else 15)
            f[f"known{h}"]=bool(known)
            if not known:continue
            assert k<current
            elapsed=times[current]-times[k];change=mids[current]-mids[k];f[f"own{h}"]=float(change*h/elapsed if h<60 else change);f[f"elapsed{h}"]=float(elapsed);f[f"endpoint{h}"]=normal[k]["index"]
            if h in (15,120):f[f"er{h}"]=float(abs(change)/(path[current]-path[k])) if path[current]>path[k] else 0.
            if h in (60,300):f[f"range{h}"]=float(np.max(mids[k:current+1])-np.min(mids[k:current+1]))
        out.append(f)
    return out


def dissect(saved: dict, stage: str) -> dict:
    """米国後の前提と準備状態を再計測し、保存準備数と一致させる。

    引数: saved(dict)、stage(str)。返り値: dict。注文・金融会計を生成しない。
    """
    scene=saved["scene"];obs=observations(scene)
    states={1:None,-1:None};counts=Counter();journeys=[];known_values=defaultdict(list)
    case=next(c for c in saved["cases"] if c["config"]["id"]=="NK225_U164_01")
    assert not case["actual"]["Events"],"取引発生場は観測器へ追加仕様が必要"
    trace={x["Index"]:x for x in (case["trigger_trace"] or []) if x["Kind"]=="準備"}
    for f in obs:
        if not(scene["us_open"]+900<=f["time"]<scene["force_close"]):continue
        counts["observation"]+=1
        for h in (5,15,60,120,300):counts[f"known{h}"]+=f[f"known{h}"]
        short_known=f["known5"] and f["known15"]
        counts["short_both_known"]+=short_known
        counts["entry_features_unknown"]+=not(f["known300"] and short_known)
        if f["known120"]:known_values["er120"].append(f["er120"]);known_values["abs_own120"].append(abs(f["own120"]))
        if not f["known300"]:
            for side,a in states.items():
                if a is not None:
                    if a["state"]==1:a["peak"]=max(a["peak"],side*f["mid"])
                    else:a["adverse"]=min(a["adverse"],side*f["mid"])
            continue
        risk=math.ceil(max(60,2*f["spread"],f["range300"]/4)/10)*10
        f["R"]=risk;known_values["R"].append(risk)
        for side in (1,-1):
            counts["R_known_side_rows"]+=1
            x=side*f["mid"]
            trend_known=f["known120"]
            large=trend_known and side*f["own120"]>=risk
            efficient=trend_known and f["er120"]>=.35
            both=large and efficient
            short_pos=short_known and side*f["own5"]>0 and side*f["own15"]>0
            accel=short_pos and side*(f["own5"]/5-f["own15"]/15)>=0
            for key,value in (("trend_known_side_rows",trend_known),("direction120_R_side_rows",large),("ER120_035_side_rows",efficient),("trend_and_ER_side_rows",both),("trend_and_ER_short_known",both and short_known),("trend_and_ER_short_positive",both and short_pos),("trend_and_ER_acceleration",both and accel)):
                counts[key]+=bool(value)
            a=states[side]
            if a is None:
                if both:
                    a={"side":side,"state":1,"peak":x,"adverse":x,"start":dict(f),"last":dict(f),"changes":[]}
                    states[side]=a;journeys.append(a);counts["prepared"]+=1
                    old=trace.get(f["index"])
                    assert old and old["Side"]==side, (scene["session"],f["index"],"保存準備なし")
                    original=old["Features"]
                    for key,ours in (("Own120","own120"),("ER120","er120"),("Range300","range300")):
                        assert abs(original[key]-f[ours])<1e-7,(key,original[key],f[ours])
                continue
            a["last"]=dict(f)
            if not trend_known:
                counts["armed_mid_unknown"]+=1
                continue
            if not both:
                reason="中期幅不足" if not large else "効率不足"
                a["changes"].append(dict(index=f["index"],time=f["time"],jst=f["jst"],reason=reason,features=dict(f)))
                a["end_reason"]=reason;states[side]=None;counts["cancel_mid"]+=1;counts["cancel_"+reason]+=1
                continue
            if a["state"]==1:
                a["peak"]=max(a["peak"],x);pull=a["peak"]-x
                if pull>1.5*risk:
                    a["end_reason"]="押戻り上限超過";a["changes"].append(dict(index=f["index"],time=f["time"],reason=a["end_reason"],features=dict(f)));states[side]=None;counts["cancel_pullback"]+=1
                elif pull>=.5*risk:
                    a["state"]=2;a["adverse"]=x;counts["pullback_formed"]+=1;a["changes"].append(dict(index=f["index"],time=f["time"],reason="押戻り成立",features=dict(f)))
                else:counts["armed_waiting_pullback"]+=1
                continue
            a["adverse"]=min(a["adverse"],x)
            if a["peak"]-a["adverse"]>1.5*risk:
                a["end_reason"]="押戻り上限超過";states[side]=None;counts["cancel_pullback"]+=1;continue
            rebound=x-a["adverse"]>=.25*risk
            counts["rebound_formed"]+=rebound
            counts["rebound_short_known"]+=rebound and short_known
            counts["rebound_short_positive"]+=rebound and short_pos
            counts["rebound_acceleration"]+=rebound and accel
            assert not(rebound and accel),(scene["session"],f["index"],"保存0新規に対し条件成立")
    expected=case["counts"]
    assert counts["observation"]==expected.get("入口観測",0)
    assert counts["entry_features_unknown"]==expected.get("入口_特徴未知",0)
    for h in (5,15,60,120,300):
        name=f"特徴未知_{h}秒"+("範囲" if h in (60,300) else "端点")
        assert counts["observation"]-counts[f"known{h}"]==expected.get(name,0),(scene["session"],name)
    assert counts["prepared"]==expected.get("準備_通常入口",0)
    assert counts["cancel_mid"]==expected.get("準備_中期条件解消",0)
    assert counts["cancel_pullback"]==expected.get("準備_押戻り超過",0)
    return {"session":scene["session"],"stage":stage,"counts":dict(counts),"distributions":{k:d.distribution(v) for k,v in known_values.items()},"values":dict(known_values),"journeys":journeys,"saved_counts_exact":True}


def main() -> None:
    """全再生完了後の観測だけを再計測して保存する。

    引数: CLIなし。返り値: None。
    """
    final,items=d.completed_inputs(d.STUDY/"再生全完了164.json")
    rows=[]
    for stage,path in items:
        rows.append(dissect(d.read(path),stage));print("入口分解完了 "+path.stem,flush=True)
    groups={}
    for stage in ("train_validation","confirmation","all"):
        selected=[r for r in rows if stage=="all" or r["stage"]==stage];count=Counter();values=defaultdict(list)
        for r in selected:
            count.update(r["counts"])
            for k,v in r["values"].items():values[k].extend(v)
        groups[stage]={"sessions":len(selected),"counts":dict(count),"distributions":{k:d.distribution(v) for k,v in values.items()}}
    for r in rows:r.pop("values")
    out={"completed":True,"financial_replays":0,"saved_counts_exact":True,"definition":"正常価格時計最初の行。無取引だったU01の入口条件だけ再計測。注文/約定/PLは生成しない。ERは実観測標本経路。","groups":groups,"sessions":rows}
    path=d.HERE/"results/米国後の入口段階分解164.json"
    path.parent.mkdir(exist_ok=True)
    with path.open("x",encoding="utf-8") as stream:json.dump(out,stream,ensure_ascii=False,allow_nan=False,separators=(",",":"));stream.write("\n")


if __name__=="__main__":main()
