"""00157の原板支持・全場時価を売買条件の再実行なしで独立検算する。"""

from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import hashlib
import json
import math
import numpy as np


def close(a: float, b: float, label: str, tolerance: float = 1e-5) -> None:
    """有限数値の不一致を黙認せず停止する。

    引数: a/b/tolerance(float)、label(str)。返り値: None。
    """
    if not math.isfinite(a) or not math.isfinite(b) or abs(a-b)>tolerance:
        raise AssertionError((label,a,b))


def read_market(scene: dict, reference: str) -> tuple[np.ndarray, dict]:
    """原板の採番条件だけを再構築し、指紋と全行読取を確認する。

    引数: scene(dict)、reference(str)。返り値: ndarray(time,last,bid,ask,bq,aq)と読取根拠dict。
    """
    path=Path(scene["books"][reference]); digest=hashlib.sha256(); rows=[]; count=defaultdict(int); previous=scene["start"]
    with path.open("rb") as stream:
        for line in stream:
            digest.update(line); count["physical"]+=1; obj=json.loads(line)
            try:
                clock=obj.get("CurrentPriceTime")
                if not isinstance(clock,str): raise ValueError("時計不明")
                at=datetime.fromisoformat(clock).timestamp()
            except (TypeError,ValueError): count["clock_missing"]+=1; continue
            if at<scene["start"] or at>scene["end"] or (scene.get("cutoff",0)>0 and at>=scene["cutoff"]): count["outside"]+=1; continue
            if at<previous: count["backwards"]+=1; continue
            last=float(obj.get("CurrentPrice") or 0)
            if last<=0 or not math.isfinite(last): count["last_missing"]+=1; continue
            previous=at; bid=obj.get("Buy1") or {}; ask=obj.get("Sell1") or {}
            rows.append((at,last,float(bid.get("Price") or 0),float(ask.get("Price") or 0),float(bid.get("Qty") or 0),float(ask.get("Qty") or 0)))
            count["adopted"]+=1
    expected=next(x["sha256"] for x in scene["fingerprints"] if Path(x["path"])==path)
    assert digest.hexdigest()==expected, "原資料指紋不一致"
    result=np.asarray(rows,dtype=np.float64)
    assert result.ndim==2 and result.shape[1]==6 and len(result)>0
    return result,{"path":str(path),"sha256":digest.hexdigest(),"matches_input":True,"counts":dict(count)}


def normal_mask(raw: np.ndarray) -> np.ndarray:
    """有限で正しい順序のラージ気配だけを有効にする。

    引数: raw(ndarray)。返り値: bool ndarray。
    """
    return np.isfinite(raw[:,2])&np.isfinite(raw[:,3])&(raw[:,2]>0)&(raw[:,3]>raw[:,2])


def support_arrays(raw: np.ndarray) -> dict:
    """支持の原板差分と既知区間を独立の配列演算で準備する。

    引数: raw(ndarray)。返り値: dictは時計・中値・異常累積・OFI累積。
    """
    valid=normal_mask(raw); n=len(raw); goodq=valid&np.isfinite(raw[:,4])&np.isfinite(raw[:,5])&(raw[:,4]>0)&(raw[:,5]>0)
    gaps=np.r_[False,np.diff(raw[:,0])>15]; bad=np.cumsum((~valid)|gaps,dtype=np.int64)
    ofi=np.zeros(n); counted=np.zeros(n,dtype=bool)
    for i in range(1,n):
        if not(goodq[i] and goodq[i-1]) or raw[i,0]-raw[i-1,0]>15: continue
        b,a,bq,aq=raw[i,2:6]; pb,pa,pbq,paq=raw[i-1,2:6]
        numerator=(bq if b>=pb else 0)-(pbq if b<=pb else 0)-(aq if a<=pa else 0)+(paq if a>=pa else 0)
        denominator=bq+pbq+aq+paq
        if not math.isfinite(numerator) or not math.isfinite(denominator): continue
        value=numerator/denominator
        if math.isfinite(value): ofi[i]=value;counted[i]=True
    return {"raw":raw,"time":raw[:,0],"mid":raw[:,2]+(raw[:,3]-raw[:,2])/2,"valid":valid,"goodq":goodq,"ofi_valid":counted,"bad":bad,"sum":np.cumsum(ofi),"count":np.cumsum(counted,dtype=np.int64)}


def support_at(own: dict, peer: dict, index: int, side: int) -> dict:
    """保存判断と同じ時点の過去窓だけから支持を再計算する。

    引数: own/peer(dict)、index/side(int)。返り値: dictは既知・各方向値。
    """
    at=own["time"][index]; out={"Known":False,"OwnAt":float(at),"PeerAt":0.0}
    if not own["goodq"][index] or not own["ofi_valid"][index]: return out
    j=int(np.searchsorted(peer["time"],at,side="left"))-1
    if j<0 or at-peer["time"][j]>15: return out
    out["PeerAt"]=float(peer["time"][j])
    for key,market,i,window,tolerance in (("Own5",own,index,5,2),("Own15",own,index,15,2),("Own120",own,index,120,15),("Own300",own,index,300,15),("Peer120",peer,j,120,15)):
        end=market["time"][i]-window;k=int(np.searchsorted(market["time"],end,side="right"))-1
        if k<0 or not market["valid"][i] or not market["valid"][k] or end-market["time"][k]>tolerance or market["bad"][i]!=market["bad"][k]: return out
        value=10000*(market["mid"][i]/market["mid"][k]-1)
        if not math.isfinite(value): return out
        out[key]=float(value)
    k=int(np.searchsorted(own["time"],at-30,side="left"))-1
    if k<0 or own["bad"][index]!=own["bad"][k] or own["count"][index]-own["count"][k]<2: return out
    out["OFI30"]=float((own["sum"][index]-own["sum"][k])/(own["count"][index]-own["count"][k]))
    clip=lambda x:max(-1,min(1,x))
    out["M"]=max(0,.45*clip(side*out["Own120"]/8)+.35*clip(side*out["Own300"]/16)+.20*clip(side*out["Peer120"]/8))
    short=.45*clip(side*out["Own15"]/3)+.35*clip(side*out["Own5"]/1.5)+.20*clip(side*out["OFI30"]/.05)
    out["T"]=max(0,short);out["Opp"]=max(0,-short);out["Known"]=True
    return out


def raw_risk(raw: np.ndarray, ledger: dict, start: float) -> dict:
    """全正常板の約定前後を現金と買売数量から再評価する。

    引数: raw(ndarray)、ledger(dict)、start(float)。返り値: dictは全場極値・次正常約定検査数。
    """
    valid=np.flatnonzero(normal_mask(raw)); n=len(valid); assert n
    changes=np.zeros((n,4)); lots={}; events=ledger.get("Events") or []; checks=0
    for event in events:
        order=event["Order"]; index=event["FillIndex"]; position=int(np.searchsorted(valid,index)); assert position<n and int(valid[position])==index
        decision=order["DecisionIndex"]; assert 0<=decision<index<len(raw)
        assert int(valid[np.searchsorted(valid,decision,side="right")])==index, "次正常板でない"
        close(raw[decision,0],order["DecisionTime"],"判断時計");close(raw[index,0],event["FillTime"],"約定時計")
        close(raw[decision,2],order["DecisionBid"],"判断Bid");close(raw[decision,3],order["DecisionAsk"],"判断Ask")
        close(raw[index,2],event["Bid"],"約定Bid");close(raw[index,3],event["Ask"],"約定Ask")
        q=order["Quantity"];side=order["Side"];price=event["Price"];assert q>0 and side in (-1,1)
        close(price,raw[index,3] if side==1 else raw[index,2],"約定方向価格")
        changes[position,0]+=-side*q*price
        if not order.get("Targets"):
            lots[event["HoldID"]]=(side,q,price,order["Parent"]);changes[position,1 if side==1 else 2]+=q
        else:
            total=0;gross=0
            for target in order["Targets"]:
                old,remaining,entry,parent=lots[target["ID"]];tq=target["Quantity"]
                assert parent==order["Parent"] and old==-side and 0<tq<=remaining
                gross+=old*tq*(price-entry)*10;total+=tq;lots[target["ID"]]=(old,remaining-tq,entry,parent)
                changes[position,1 if old==1 else 2]-=tq
            assert total==q;close(gross,event["Gross"],"独立所有PL")
            changes[position,3]+=gross
        checks+=1
    after=np.cumsum(changes,axis=0);before=after-changes
    bid,ask=raw[valid,2],raw[valid,3]
    before_eq=(before[:,0]+before[:,1]*bid-before[:,2]*ask)*10
    after_eq=(after[:,0]+after[:,1]*bid-after[:,2]*ask)*10
    # ----------------------------------------
    # 同じ気配で返済は清算時価不変、新規は気配差だけ低下するため中間値は両端内です。
    assert np.all(after_eq<=before_eq+1e-5), "同一気配の約定で清算時価が上昇"
    values=np.zeros(2*n+1);values[1::2]=before_eq;values[2::2]=after_eq
    peaks=np.maximum.accumulate(values);dds=peaks-values
    minimum=int(np.argmin(values));dd_to=int(np.argmax(dds));dd_from=int(np.argmax(values[:dd_to+1]))
    def anchor(position: int) -> dict:
        """時価配列の極値を原行と約定前後へ戻す。

        引数: position(int)。返り値: dictは時刻と原行。
        """
        if position==0: return {"time":start,"index":-1,"phase":"開始","equity":0.0}
        row=(position-1)//2;return {"time":float(raw[valid[row],0]),"index":int(valid[row]),"phase":"約定前" if position%2 else "約定後","equity":float(values[position])}
    result={"min_equity":float(values[minimum]),"max_drawdown":float(dds[dd_to]),"min_realized":float(min(0,np.min(after[:,3]))),"minimum_at":anchor(minimum),"dd_from":anchor(dd_from),"dd_to":anchor(dd_to),"normal_rows":n,"event_checks":checks,"final_equity":float(after_eq[-1]),"final_realized":float(after[-1,3]),"final_long":int(after[-1,1]),"final_short":int(after[-1,2])}
    risk=ledger["Risk"]
    close(result["min_equity"],risk["Minimum"],"全原板最小時価")
    close(result["max_drawdown"],risk["MaxDD"],"全原板最大DD")
    close(result["final_realized"],ledger["Realized"],"終端確定")
    close(result["final_equity"],ledger["Last"]["Equity"],"終端時価")
    return result


def reserved_cap(ledger: dict) -> dict:
    """全発注列を約定前後の順で読み、未約定新規込み上限を確認する。

    引数: ledger(dict)。返り値: dictは全判断数と最大買売予約込み枚数。
    """
    decisions=defaultdict(list);fills=defaultdict(list);seen=set()
    for event in ledger.get("Events") or []:
        order=event["Order"];assert order["ID"] not in seen;seen.add(order["ID"])
        decisions[order["DecisionIndex"]].append(order);fills[event["FillIndex"]].append(event)
    for order in ledger.get("Pending") or []:
        assert order["ID"] not in seen;seen.add(order["ID"]);decisions[order["DecisionIndex"]].append(order)
    held={1:0,-1:0};reserved={1:0,-1:0};pending={};maximum={1:0,-1:0}
    for index in sorted(set(decisions)|set(fills)):
        for event in fills[index]:
            order=event["Order"];assert pending.pop(order["ID"])==order
            side=order["Side"];q=order["Quantity"]
            if order.get("Targets"): held[-side]-=q
            else: reserved[side]-=q;held[side]+=q
            assert min(held.values())>=0 and min(reserved.values())>=0
            assert max(held[s]+reserved[s] for s in (1,-1))<=100
        for order in decisions[index]:
            pending[order["ID"]]=order
            if not order.get("Targets"): reserved[order["Side"]]+=order["Quantity"]
            for side in (1,-1):
                amount=held[side]+reserved[side];assert amount<=100;maximum[side]=max(maximum[side],amount)
    assert set(pending)=={x["ID"] for x in ledger.get("Pending") or []}
    return {"orders":len(seen),"max_long_reserved":maximum[1],"max_short_reserved":maximum[-1],"final_pending":len(pending)}
