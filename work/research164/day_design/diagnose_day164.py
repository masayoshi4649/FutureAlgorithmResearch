"""保存済み日中会計を読み、四つの不満を原行と実所有IDで再集計する。新金融再生はしない。"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np

JST=timezone(timedelta(hours=9))


def read(path: Path):
    """JSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
    """内容SHAをストリーム計算する。

    引数: path(Path)。返り値: str。
    """
    h=hashlib.sha256()
    with path.open("rb") as f:
        while block:=f.read(1<<20): h.update(block)
    return h.hexdigest()


def stamp(at: float) -> str:
    """日本時刻へ変換する。

    引数: at(float)。返り値: str。
    """
    return datetime.fromtimestamp(at,JST).isoformat(timespec="milliseconds")


def raw_rows(scene: dict) -> dict:
    """旧loadBoardsと同じ採用条件でNK原行を再読し、金銭注文なしで価格配列を作る。

    引数: scene(dict)。返り値: dict。IndexはNK内の採用順、異常BBOも行番号を消費する。
    """
    path=Path(scene["books"]["NK225"])
    expected=next(x["sha256"] for x in scene["fingerprints"] if Path(x["path"])==path)
    assert digest(path)==expected, "原資料指紋差"
    times=[];bids=[];asks=[];lines=[];previous=scene["start"]
    with path.open(encoding="utf-8-sig") as f:
        for physical,line in enumerate(f,1):
            x=json.loads(line);clock=x.get("CurrentPriceTime")
            if not clock: continue
            try: at=datetime.fromisoformat(clock.replace("Z","+00:00")).timestamp()
            except (ValueError,TypeError): continue
            if at<scene["start"] or at>scene["end"] or (scene["cutoff"]>0 and at>=scene["cutoff"]): continue
            if at<previous: continue
            price=x.get("CurrentPrice") or 0
            if price<=0 or not math.isfinite(price): continue
            previous=at
            bid=(x.get("Buy1") or {}).get("Price") or 0;ask=(x.get("Sell1") or {}).get("Price") or 0
            times.append(at);bids.append(bid);asks.append(ask);lines.append(physical)
    time=np.asarray(times);bid=np.asarray(bids);ask=np.asarray(asks)
    valid=np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid)
    assert digest(path)==expected, "原資料処理中変化"
    return dict(time=time,bid=bid,ask=ask,line=np.asarray(lines),valid=valid,path=str(path),sha256=expected)


def category(case: dict, event: dict) -> tuple[str,list[dict]]:
    """00のprojectionをCanonical注文へ遡り、役割とSourceIDを確定する。

    引数: case(dict)、event(dict)。返り値: (役割str,対応list)。混在は混在のまま記録する。
    """
    order=event["Order"]
    if order["Kind"]!="projection": return order["Kind"],[dict(kind=order["Kind"],source_id=order.get("SourceID",""),quantity=order["Quantity"])]
    canonical={x["Order"]["ID"]:x["Order"] for x in case["canonical"]["Events"] or []}
    refs=[]
    for cid in order.get("CanonicalOrderIDs") or []:
        x=canonical.get(cid)
        if x and not x.get("Targets"): refs.append(dict(kind=x["Kind"],source_id=x.get("SourceID",""),quantity=x["Quantity"]))
    assert refs and sum(x["quantity"] for x in refs)==order["Quantity"], "00の実新規を元数量へ対応できない"
    kinds={x["kind"] for x in refs}
    return next(iter(kinds)) if len(kinds)==1 else "複数役割混在",refs


def measure_lots(scene: dict,case: dict,raw: dict|None) -> list[dict]:
    """Actualの実建値・返済・原行から順行消失と追加直後の逆行を測る。

    引数: scene/case(dict)、raw(dict又はNone)。返り値: list[dict]。
    """
    events=case["actual"]["Events"] or [];lots=case["actual"]["Lots"] or {};closes=defaultdict(list)
    for e in events:
        for p in e.get("Pieces") or []: closes[p["ID"]].append((e,p))
    result=[]
    for e in events:
        if e["Order"].get("Targets"): continue
        l=lots[e["HoldID"]];role,refs=category(case,e);parts=closes[l["ID"]]
        gain=sum(p["Gross"] for _,p in parts);first_close=min((x["FillIndex"] for x,_ in parts),default=None)
        row=dict(session=scene["session"],method=case["config"]["id"],id=l["ID"],parent=l["Parent"],role=role,source_allocations=refs,
                 side=l["Side"],quantity=l["Quantity"],entry=l["Entry"],entry_index=l["EntryIndex"],entry_time=stamp(l["At"]),gross=gain,
                 best=l["Best"],worst=l["Worst"],best_time=stamp(l["BestAt"]),worst_time=stamp(l["WorstAt"]),
                 positive_then_final_loss=(l["Best"]>0 and gain<0),small_initial=(role in ("initial","delayed_initial") and l["Quantity"]<=20),
                 protection_state=(case.get("lot_states") or {}).get(l["ID"],{}),
                 first_close_index=first_close,first_close_time=stamp(min((x["FillTime"] for x,_ in parts),default=l["At"])),
                 close_pieces=[dict(time=stamp(x["FillTime"]),index=x["FillIndex"],decision_index=x["Order"]["DecisionIndex"],
                                    reason=x["Order"]["Reason"],price=x["Price"],quantity=p["Quantity"],gross=p["Gross"],best_at_close=p["Best"],
                                    positive_then_loss=(p["Best"]>0 and p["Gross"]<0)) for x,p in parts],support=e["Order"]["Support"])
        if raw is not None:
            start=l["EntryIndex"];stop=first_close if first_close is not None else len(raw["time"])-1
            assert abs(raw["time"][start]-l["At"])<1e-5
            price=raw["ask"][start] if l["Side"]>0 else raw["bid"][start]
            assert price==l["Entry"], "新規実気配と原行不一致"
            row["entry_physical_line"]=int(raw["line"][start])
            idx=np.arange(start,stop+1);valid=raw["valid"][idx];values=l["Side"]*((raw["bid"] if l["Side"]>0 else raw["ask"])[idx]-l["Entry"])
            row["first_close_prefix_bad_bbo"]=int((~valid).sum())
            row["first_close_prefix_gap_gt15"]=bool((np.diff(raw["time"][idx])>15).any())
            for seconds in (5,15,60):
                use=valid&(raw["time"][idx]-l["At"]<=seconds)
                row[f"worst_before_first_close_{seconds}s"]=float(values[use].min()) if use.any() else None
            hit=np.flatnonzero(valid&(values<=-50))
            row["first_50_before_first_close"]=None if not len(hit) else dict(index=int(idx[hit[0]]),physical_line=int(raw["line"][idx[hit[0]]]),
                 time=stamp(float(raw["time"][idx[hit[0]]])),seconds=float(raw["time"][idx[hit[0]]]-l["At"]),gain=float(values[hit[0]]))
        result.append(row)
    assert abs(sum(x["gross"] for x in result)-case["actual"]["Realized"])<1e-7
    return result


def summarize(rows:list[dict]) -> dict:
    """玉単位の回数と金額を役割別に集計する。

    引数: rows(list[dict])。返り値: dict。玉数とmicro枚数を区別する。
    """
    roles={}
    for role in sorted({x["role"] for x in rows}):
        use=[x for x in rows if x["role"]==role];bad=[x for x in use if x["positive_then_final_loss"]]
        roles[role]=dict(lots=len(use),micro=sum(x["quantity"] for x in use),gross=sum(x["gross"] for x in use),
                        positive_then_loss_lots=len(bad),positive_then_loss_micro=sum(x["quantity"] for x in bad),positive_then_loss_gross=sum(x["gross"] for x in bad),
                        first50_within15s=(sum(x.get("first_50_before_first_close") is not None and x["first_50_before_first_close"]["seconds"]<=15 for x in use) if all("first_50_before_first_close" in x for x in use) else None))
    return dict(lots=len(rows),gross=sum(x["gross"] for x in rows),roles=roles,
                small_initial_positive_then_loss=[x for x in rows if x["small_initial"] and x["positive_then_final_loss"]],
                lost_profit_examples=sorted((x for x in rows if x["positive_then_final_loss"]),key=lambda x:x["gross"])[:12])


def parent_deltas(scene:dict,cases:list[dict],lots:dict[str,list[dict]]) -> list[dict]:
    """同じSource親単位で改善と消失した利益を比較する。

    引数: scene(dict)、cases(list)、lots(dict)。返り値: list[dict]。
    """
    baseline=next(x for x in cases if x["config"]["id"]=="NK225_D164_00")
    base=defaultdict(float)
    for x in lots[baseline["config"]["id"]]: base[x["parent"]]+=x["gross"]
    result=[]
    for c in cases:
        method=c["config"]["id"]
        if method==baseline["config"]["id"]: continue
        now=defaultdict(float)
        for x in lots[method]: now[x["parent"]]+=x["gross"]
        deferred={x["Parent"] for x in (c.get("decisions") or []) if x["Action"]=="初回延期"}
        for p in sorted(set(base)|set(now)):
            delta=now[p]-base[p]
            if delta or p in deferred:
                result.append(dict(session=scene["session"],method=method,parent=p,baseline=base[p],candidate=now[p],delta=delta,
                                   delayed_initial=p in deferred,lost_baseline_winner=(base[p]>0 and delta<0),
                                   baseline_lots=[x for x in lots[baseline["config"]["id"]] if x["parent"]==p],
                                   candidate_lots=[x for x in lots[method] if x["parent"]==p],
                                   decisions=[x for x in (c.get("decisions") or []) if x["Parent"]==p]))
    return result


def main() -> None:
    """全金融完了証跡がある場合だけ保存結果の診断を実行する。

    引数: CLIの研究ルート/out/raw。返り値: None。
    """
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument("--out",type=Path);parser.add_argument("--raw",action="store_true");args=parser.parse_args()
    root=args.root;proof_path=root/"再生全完了164.json";proof=read(proof_path);assert proof["completed"] is True and proof["returncode"]==0
    project=root.resolve().parents[1];result_hashes={}
    for item in proof["proofs"]:
        path=Path(item["path"]);path=path if path.is_absolute() else project/path
        assert digest(path)==item["sha256"], "完了証跡指紋差"
        stage=read(path);assert stage["completed"] is True and stage["sources_unchanged"] is True
        for ref in stage["results"]:
            rp=Path(ref["path"]);rp=rp if rp.is_absolute() else project/rp;result_hashes[rp.resolve()]=ref["sha256"]
    out=args.out or root/"day_design/diagnosis";assert not out.exists(),"診断を上書きしません";out.mkdir(parents=True)
    records=[];sources=[];all_rows=[];all_deltas=[]
    for folder in (root/"results/train_validation",root/"results/confirmation"):
        for path in sorted(folder.glob("*_Day.json")):
            assert digest(path)==result_hashes[path.resolve()], "保存会計の指紋差"
            data=read(path);scene=data["scene"];assert scene["kind"]=="Day";cases=data["cases"];raw=raw_rows(scene) if args.raw else None
            lots={c["config"]["id"]:measure_lots(scene,c,raw) for c in cases};deltas=parent_deltas(scene,cases,lots);all_deltas.extend(deltas)
            for c in cases:
                rows=lots[c["config"]["id"]];all_rows.extend(rows);records.append(dict(session=scene["session"],method=c["config"]["id"],summary=summarize(rows),risk=c["actual"]["Risk"]))
            sources.append(dict(path=str(path),sha256=digest(path),raw_sha256=raw["sha256"] if raw else None))
    assert len(records)==27*12
    summary={m:summarize([x for x in all_rows if x["method"]==m]) for m in sorted({x["method"] for x in all_rows})}
    output=dict(purpose="保存済みActual会計と原板の原因診断。売買条件の再評価・再選択ではない。",new_financial_replays=0,completion_sha256=digest(proof_path),sources=sources,
                definitions=dict(positive_then_loss="Actual玉の保有中最高返済側値幅>0かつその玉全返済の合計<0。部分返済の勝ち負けも別列。",small_initial="初回20micro以下。mini2枚相当以下。",early_adverse="実新規から最初の実返済までの原行で−50円。5/15/60秒は診断窓で保有時間条件ではない。"),
                summary=summary,sessions=records,parent_changes=sorted(all_deltas,key=lambda x:x["delta"]),lots=all_rows)
    (out/"日中四問題の診断164.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# 日中のActual所有IDによる診断","", "保存会計の再集計。新しい金融再生は0。原板診断="+str(args.raw),"", "|手法|収支|利益を見た後に赤字の玉数|同玉損益|","|---|---:|---:|---:|"]
    for m,s in summary.items(): lines.append(f"|{m}|{s['gross']:,.0f}|{sum(x['positive_then_loss_lots'] for x in s['roles'].values())}|{sum(x['positive_then_loss_gross'] for x in s['roles'].values()):,.0f}|")
    lines += ["", "主要悪化と改善はJSONのparent_changesで同じSource親へ対応。初回延期の元勝ちを消した例、追加玉・再参加玉の損益を別々に確認する。"]
    (out/"日中四問題の診断164.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(dict(sessions=27,method_cases=len(records),new_financial_replays=0),ensure_ascii=False))

if __name__=="__main__": main()
