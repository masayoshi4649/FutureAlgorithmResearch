"""全場平均と最低参加の影響を再集計し、最大損失場の注文を具体化する。"""

from pathlib import Path
from io import BytesIO
from datetime import datetime,timezone,timedelta
import json
import hashlib
import numpy as np
from prepare125 import ROOT,HERE


def sha(path: Path) -> str:
    """
    機能: 保存結果を識別する。
    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clock(value: float) -> str:
    """
    機能: 注文の絶対秒を日本時間の表示へ変換する。
    引数: value(float)は絶対秒。
    返り値: strは日本時間。
    """
    return datetime.fromtimestamp(value,timezone(timedelta(hours=9))).isoformat()


def main() -> None:
    """
    機能: 保存会計だけから12条件の統計と赤字上位場の損失内訳を作る。
    引数: なし。
    返り値: None。金融再生・原本・APIは0。
    """
    path=HERE/"十二条件と二商品全四十一場の会計.json";d=json.loads(path.read_text(encoding="utf-8"))
    inputs=json.loads((HERE/"保存済み気配と先行確定足の八十二入力.json").read_text(encoding="utf-8"))
    totals=[]
    for spec in d["specs"]:
        for symbol in ("TOPIX","NK225"):
            rr=[r for r in d["rows"] if r["method"]==spec["id"] and r["symbol"]==symbol]
            a=np.array([r["net"] for r in rr]);positive=a[a>0]
            totals.append(dict(method=spec["id"],symbol=symbol,net=float(a.sum()),mean=float(a.mean()),median=float(np.median(a)),black=int((a>0).sum()),red=int((a<0).sum()),none=sum(r["entry_orders"]==0 for r in rr),activity=sum(r["entry_orders"]>0 for r in rr),profit=sum(r["profit"] for r in rr),loss=sum(r["loss"] for r in rr),fees=sum(r["fees"] for r in rr),entry_quantity=sum(r["entry_quantity"] for r in rr),forced_groups=sum(r["forced_groups"] for r in rr),forced_net=sum(r["forced_net"] for r in rr),signal_groups=sum(r["signal_groups"] for r in rr),signal_net=sum(r["signal_net"] for r in rr),worst=float(a.min()),mean_black=float(positive.mean()) if len(positive) else None,top3_excluded=float(a.sum()-np.sort(positive)[-3:].sum()),normalized_median=float(np.median([r["net"]/r["rate_components"]["capacity_notional"] for r in rr])),normalized_sum=float(sum(r["net"]/r["rate_components"]["capacity_notional"] for r in rr)),minimum_session_entry_quantity=min(r["entry_quantity"] for r in rr)))
    by={(r["method"],r["symbol"]):r for r in totals}
    def score(method: str) -> tuple:
        """
        機能: 両商品を隠さない既知内比較の固定順位を作る。
        引数: method(str)は候補ID。
        返り値: tupleは少赤字・小〜中収益を優先する順位。将来の選択規則ではない。
        """
        p=[by[method,s] for s in ("TOPIX","NK225")]
        return (-max(r["red"] for r in p),min(r["normalized_median"] for r in p),sum(r["normalized_sum"] for r in p))
    ranked=sorted([s["id"] for s in d["specs"]],key=score,reverse=True)
    chosen=ranked[0];family_chosen=[max([s["id"] for s in d["specs"] if s["family"]==f],key=score) for f in ("A","B","C")]
    caches={(r["symbol"],r["session"]):r for r in d["cache"]};input_map={(r["symbol"],r["session"]):r for r in inputs["inputs"]}
    oi={k:i for i,k in enumerate(d["order_columns"])};ti={k:i for i,k in enumerate(d["trade_columns"])}
    details=[]
    for symbol in ("TOPIX","NK225"):
        rr=sorted([r for r in d["rows"] if r["method"]==chosen and r["symbol"]==symbol],key=lambda r:r["net"])[:3]
        for r in rr:
            key=symbol,r["session"];cache=caches[key];source=input_map[key]
            payload=(ROOT/cache["path"]).read_bytes();assert hashlib.sha256(payload).hexdigest()==cache["sha256"]
            with np.load(BytesIO(payload),allow_pickle=False) as z:
                orders=z[chosen+"__orders"].copy();trades=z[chosen+"__trades"].copy()
            payload=(ROOT/source["path"]).read_bytes();assert hashlib.sha256(payload).hexdigest()==source["sha256"]
            with np.load(BytesIO(payload),allow_pickle=False) as z:q={k:z[k].copy() for k in ("row","time","last","bid","ask","feature_rows","features")}
            selected=trades[np.argsort(trades[:,ti["net"]])[:3]];parts=[]
            for t in selected:
                gid=t[ti["group_id"]];entries=orders[(orders[:,oi["group_id"]]==gid)&(orders[:,oi["kind"]]==1)]
                side=int(t[ti["side"]]);quantity=t[ti["quantity"]];mult=1000. if symbol=="TOPIX" else 10.
                exitrow=int(t[ti["reference_row"]]);exi=int(np.searchsorted(q["row"],exitrow));assert q["row"][exi]==exitrow
                exitlast=float(q["last"][exi]);exitprice=t[ti["exit_price"]]
                lastcost=entrydrag=0.
                for e in entries:
                    ix=int(np.searchsorted(q["row"],int(e[oi["fill_row"]])));ep=q["last"][ix];eq=e[oi["quantity"]]
                    lastcost+=eq*ep;entrydrag+=side*(e[oi["price"]]-ep)*eq*mult
                directional=side*(exitlast*quantity-lastcost)*mult;exitdrag=side*(exitlast-exitprice)*quantity*mult
                fees=t[ti["entry_fees"]]+t[ti["exit_fee"]]
                assert abs(directional-entrydrag-exitdrag-fees-t[ti["net"]])<1e-6
                first=entries[0];fidx=int(np.searchsorted(q["feature_rows"],first[oi["decision_row"]],side="right"))-1
                feature=q["features"][fidx] if fidx>=0 else np.full(12,np.nan)
                parts.append(dict(group_id=int(gid),side="買い" if side==1 else "売り",quantity=int(quantity),decision_time=clock(first[oi["decision_time"]]),entry_time=clock(t[ti["first_entry_time"]]),entry_price=t[ti["average_entry"]],exit_time=clock(t[ti["exit_time"]]),exit_price=exitprice,net=t[ti["net"]],gross=t[ti["gross"]],fees=fees,mfe=t[ti["mfe"]],mae=t[ti["mae"]],entry_reason=int(t[ti["entry_reason"]]),exit_reason=int(t[ti["exit_reason"]]),initial_w=t[ti["initial_w"]],initial_stop=t[ti["initial_stop"]],last_directional_gross=directional,entry_drag=entrydrag,exit_drag=exitdrag,decision_last=first[oi["decision_last"]],decision_bid=first[oi["decision_bid"]],decision_ask=first[oi["decision_ask"]],decision_features=[float(v) if np.isfinite(v) else None for v in feature],orders=[dict(zip(d["order_columns"],e.tolist())) for e in orders[orders[:,oi["group_id"]]==gid]]))
            details.append(dict(symbol=symbol,session=r["session"],method=chosen,net=r["net"],forced_net=r["forced_net"],signal_net=r["signal_net"],groups=r["groups"],loss_groups=r["losses"],mfe_positive_loss_groups=int(((trades[:,ti["net"]]<0)&(trades[:,ti["mfe"]]>0)).sum()),never_positive_loss_groups=int(((trades[:,ti["net"]]<0)&(trades[:,ti["mfe"]]<=0)).sum()),trades=parts))
    result=dict(passed=True,source_result=dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path)),totals=totals,ranking=ranked,best_common=chosen,family_chosen=family_chosen,details=details,financial_replays=0,original_market_reads=0,ranking_limit="既知41場からの記述的選択。目標利益率の分母は未確定。選択を未来へ自動適用した成功としない。")
    out=HERE/"diagnosis125.json";assert not out.exists();out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    print("保存比較の先頭",chosen,"家族別",family_chosen,flush=True)
    for r in totals:
        if r["method"] in family_chosen:print(r["method"],r["symbol"],r["net"],r["black"],r["red"],r["activity"],flush=True)


if __name__=="__main__":main()
