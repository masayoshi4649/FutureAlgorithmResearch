"""新規基準から両市場が逆行した最初の時点を、保存親区間の中だけで分類する。"""

import hashlib
import json
from pathlib import Path
import pickle
import sys
from datetime import datetime,timezone,timedelta

import numpy as np

HERE=Path(__file__).resolve().parent
TASK=HERE.parent
ROOT=HERE.parents[2]
OLD=ROOT/"work/daynight128_20261020"
sys.dont_write_bytecode=True
sys.path.insert(0,str(TASK))
import features129
JST=timezone(timedelta(hours=9))


def read(path: Path) -> dict:
    """
    機能: 保存入力参照又は比較資料を読む。
    引数: path(Path)は保存位置。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def stamp(value: float) -> str:
    """
    機能: 原資料の価格時計を日本時刻で表示する。
    引数: value(float)はＵｎｉｘ秒。
    返り値: strは日本時刻。実受信時計を意味しない。
    """
    return datetime.fromtimestamp(float(value),JST).isoformat()


def summarize(rows: list[dict]) -> dict:
    """
    機能: 保存親の分類ごとの件数と元損益を集計する。
    引数: rows(list[dict])は判定や約定を変更しない元親群。
    返り値: dictは件数・勝敗・元利益損失。除外再運転の収支ではない。
    """
    return dict(count=len(rows),wins=sum(r["net"]>0 for r in rows),losses=sum(r["net"]<0 for r in rows),
                saved_profit=sum(max(0.,r["net"]) for r in rows),
                saved_loss=-sum(min(0.,r["net"]) for r in rows),saved_net=sum(r["net"] for r in rows))


def main() -> None:
    """
    機能: 全二十一夜間Ｎ３６／ＮＶ０２を固定し二幅の新規根拠撤回を分類する。
    引数: なし。
    返り値: None。新たな注文・損益運転を行わず判断候補時刻を保存する。
    """
    original=read(TASK/"停止時の相手支持と共通失敗の保存分類.json")
    references=read(OLD/"入力準備.json")["packets"]
    rows=[]
    for ref in references:
        scene=ref["session"]
        if not scene.endswith("_Night"):
            continue
        packet=pickle.loads((ROOT/ref["path"]).read_bytes())
        midinputs=features129.prices_for(packet,"mid")
        midmarkets=features129.markets(midinputs)
        for symbol in ("TOPIX","NK225"):
            key=scene,symbol
            ready,q=packet["inputs"][key],packet["quotes"][key]
            times=ready["time_s"]
            for method,folder,market in (("N36",OLD/"round5",packet["markets"][key]),
                                         ("NV02",TASK/"round1",midmarkets[key])):
                with np.load(folder/"measurement"/f"{symbol}_{scene}.npz",allow_pickle=False) as a:
                    orders,trades=a[method+"__orders"],a[method+"__trades"]
                for number,tr in enumerate(trades):
                    e,x,side,qty=map(int,tr[:4]);width=float(tr[11]);entry=float(tr[4])
                    closes=orders[(orders[:,2]==number)&(orders[:,7]==0)]
                    assert len(closes)==1 and int(closes[0,0])==x
                    exit_source=int(closes[0,1])
                    anchor_known=market[e,11]==1 and np.isfinite(market[e,[1,3]]).all() and market[e,3]>0.
                    record=dict(method=method,session=scene,symbol=symbol,parent=number,side=side,
                        quantity=qty,entry_row=e,exit_row=x,exit_decision_row=exit_source,
                        entry_time=stamp(times[e]),exit_time=stamp(times[x]),exit_decision_time=stamp(times[exit_source]),
                        entry=entry,exit=float(tr[5]),net=float(tr[8]),mfe=float(tr[9]),mae=float(tr[10]),
                        width=width,reason=int(tr[12]),entry_peer_known=bool(anchor_known),
                        entry_peer_price=float(market[e,1]) if anchor_known else None,
                        entry_peer_atr=float(market[e,3]) if anchor_known else None,
                        entry_peer_time=stamp(market[e,8]) if anchor_known else None,hits={})
                    for threshold in (.25,.5):
                        hit=None
                        if anchor_known:
                            ids=np.arange(e+1,x+1)
                            known=(market[ids,11]==1.)&np.isfinite(market[ids,1])
                            fresh=market[ids,8]>times[e]
                            good=q["quote_valid"][ids]&np.isfinite(q["bid"][ids])&np.isfinite(q["ask"][ids])
                            good&=(q["bid"][ids]>0.)&(q["ask"][ids]>q["bid"][ids])
                            ownmark=q["bid"][ids] if side>0 else q["ask"][ids]
                            ownchange=side*(ownmark-entry)/width
                            peerchange=side*(market[ids,1]-market[e,1])/market[e,3]
                            found=np.flatnonzero(known&fresh&good&(ownchange<=-threshold)&(peerchange<=-threshold))
                            if len(found):
                                j=int(found[0]);i=int(ids[j])
                                subsequent=np.flatnonzero(good[j+1:])
                                nextrow=int(ids[j+1+subsequent[0]]) if len(subsequent) else None
                                hit=dict(row=i,time=stamp(times[i]),own_change_R=float(ownchange[j]),
                                    peer_change_R=float(peerchange[j]),peer_time=stamp(market[i,8]),
                                    before_original_exit_decision=i<exit_source,
                                    next_normal_row=nextrow,
                                    next_normal_time=stamp(times[nextrow]) if nextrow is not None else None,
                                    next_normal_before_original_exit=nextrow is not None and nextrow<x,
                                    seconds_before_exit_decision=float(times[exit_source]-times[i]))
                        record["hits"][str(threshold)]=hit
                    rows.append(record)
        print(scene,"固定親の基準撤回分類",flush=True)
    # ----------------------------------------
    # 最初の条件成立から次正常行で元返済より前に動けるものだけを早期候補と数える。
    groups={}
    for method in ("N36","NV02"):
        for symbol in ("TOPIX","NK225"):
            allrows=[r for r in rows if r["method"]==method and r["symbol"]==symbol]
            for threshold in (.25,.5):
                hit=[r for r in allrows if r["hits"][str(threshold)] is not None]
                early=[r for r in hit if r["hits"][str(threshold)]["before_original_exit_decision"]
                       and r["hits"][str(threshold)]["next_normal_before_original_exit"]]
                late=[r for r in hit if r not in early]
                label=f"{method}_{symbol}_{threshold}"
                groups[label]=dict(all=summarize(allrows),hit=summarize(hit),early=summarize(early),
                    coincident_or_later=summarize(late),
                    unknown_entry_peer=sum(not r["entry_peer_known"] for r in allrows),
                    early_members=[dict(session=r["session"],parent=r["parent"],entry_time=r["entry_time"],
                        exit_time=r["exit_time"],side=r["side"],net=r["net"],entry=r["entry"],exit=r["exit"],
                        **r["hits"][str(threshold)]) for r in early])
    result=dict(passed=True,financial_replays=0,API=0,rows=rows,groups=groups,
        definitions=dict(own="自己清算BBO−実建値を方向付きにし、保存初期widthで割る。",
                         peer="相手の現在価格−実新規行で既知の相手価格を方向付きにし、実新規行の相手ATRで割る。",
                         freshness="新規原時計より相手sourceが厳密に後、現在known、自己正常BBO。",
                         observation="N36は旧Last二市場、NV02は正常気配中心の二市場。値幅ATRは旧公開済み値。",
                         early="条件成立が元返済判断より前、かつ次正常行も元約定より前。",
                         outcome="元勝ち/元負けは分類ラベル。ここに仮想退出の収支や再参加は計算しない。"),
        prior_classification=dict(path="work/visual_pdca129_20261020/停止時の相手支持と共通失敗の保存分類.json",
                                  rows=len(original["rows"])),
        source_hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (Path(__file__),TASK/"features129.py",OLD/"入力準備.json")})
    target=HERE/"夜間の両市場新規基準撤回と元勝ち反例.json"
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    print(json.dumps({k:{g:v[g] for g in ("all","early","coincident_or_later","unknown_entry_peer")}
                      for k,v in groups.items()},ensure_ascii=False,indent=2))
    print(target)


if __name__=="__main__":
    main()
