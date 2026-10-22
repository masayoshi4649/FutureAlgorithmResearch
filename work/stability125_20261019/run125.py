"""固定十二条件を各商品・各場へ一回ずつ適用し、注文と清算時価を保存する。"""

from io import BytesIO
from pathlib import Path
import hashlib
import json
import numpy as np
import engine125 as E
from catalog125 import specifications
from prepare125 import ROOT,HERE


def sha(path: Path) -> str:
    """
    機能: 内容の同一性を検査する。
    引数: path(Path)は固定対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: UTF8の固定計画又は保存結果を読む。
    引数: path(Path)はJSON。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path,value: dict) -> None:
    """
    機能: 125所有域だけへ新しいJSONを保存する。
    引数: path(Path)は保存先、value(dict)は保存値。
    返り値: None。既存成果は上書きしない。
    """
    path=path.resolve();assert path.is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")


def execute() -> None:
    """
    機能: 登録・人工・入力指紋を拘束して十二仕様を測り、元会計を保存する。
    引数: なし。
    返り値: None。新たな原本読取・API・実注文は使わない。
    """
    fixed=read(HERE/"固定計画.json");reg=read(HERE/"正式登録の全出力.json")
    assert reg["終了コード"]==0
    assert json.loads(reg["stdout"])["spec"]["implementation"]==fixed["sources"]
    for rel,h in fixed["sources"].items():assert sha(ROOT/rel)==h,rel
    for ref in fixed["bindings"]:
        assert sha(ROOT/ref["path"])==ref["sha256"]
        if ref.get("artificial"):assert read(ROOT/ref["path"])["passed"]
    manifest=read(ROOT/fixed["inputs"]["path"])
    assert manifest["passed"] and len(manifest["inputs"])==82
    out=HERE/"measurement";assert not out.exists();out.mkdir()
    rows=[];caches=[];input_reads=[]
    for item in manifest["inputs"]:
        payload=(ROOT/item["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest()==item["sha256"]
        with np.load(BytesIO(payload),allow_pickle=False) as loaded:
            q={k:loaded[k].copy() for k in ("row","time","last","bid","ask")}
            f={k:loaded[k].copy() for k in ("feature_rows","features")}
        symbol=item["symbol"];scene=item["session"];top=symbol=="TOPIX"
        setting=dict(cap=10 if top else 20,multiplier=1000. if top else 10.,fee=41.8 if top else 11.,observed_tick=.5 if top else 10.,session_start=item["start"],session_end=item["end"],entry_end=item["end"]-1800,close_time=item["end"]-360)
        arrays={}
        for spec in specifications():
            orders,trades,curve,summary=E.evaluate(q,f,setting,spec)
            if not isinstance(summary,dict):summary=dict(zip(E.SUMMARY_COLUMNS,summary.tolist()))
            assert all(np.isfinite(v).all() for v in (orders,trades,curve))
            summary={k:(v.item() if isinstance(v,np.generic) else v) for k,v in summary.items()}
            assert summary["unclosed_quantity"]==0, (symbol,scene,spec["id"],summary)
            assert summary["net"]==summary["cash"]==summary["last_equity"]
            method=spec["id"]
            for name,value in (("orders",orders),("trades",trades),("curve",curve)):arrays[method+"__"+name]=value
            oi={k:i for i,k in enumerate(E.ORDER_COLUMNS)};ti={k:i for i,k in enumerate(E.TRADE_COLUMNS)}
            new=orders[orders[:,oi["kind"]]==1]
            proxy=trades[:,ti["proxy_flag"]]==1
            net=float(trades[:,ti["net"]].sum())
            quantity=int(new[:,oi["quantity"]].sum())
            rates=dict(reference_price=float(q["last"][0]),capacity_notional=float(q["last"][0]*setting["cap"]*setting["multiplier"]),actual_entry_notional=float(np.sum(new[:,oi["quantity"]]*new[:,oi["price"]])*setting["multiplier"]))
            row=dict(symbol=symbol,session=scene,method=method,summary=summary,net=net,profit=float(np.maximum(trades[:,ti["net"]],0).sum()),loss=float(np.maximum(-trades[:,ti["net"]],0).sum()),fees=float(orders[:,oi["fee"]].sum()+trades[proxy,ti["exit_fee"]].sum()),entry_quantity=quantity,entry_orders=len(new),groups=len(trades),wins=int((trades[:,ti["net"]]>0).sum()),losses=int((trades[:,ti["net"]]<0).sum()),proxy_groups=int(proxy.sum()),normal_groups=int((~proxy).sum()),max_long=float(curve[:,5].max()),max_short=float(curve[:,6].max()),rate_components=rates)
            assert row["net"]==row["profit"]-row["loss"]==summary["net"]
            assert row["fees"]==summary["fees_paid"]
            row["max_long"]=summary["max_long"];row["max_short"]=summary["max_short"]
            forced=trades[:,ti["entry_reason"]]==5
            row.update(forced_groups=int(forced.sum()),forced_net=float(trades[forced,ti["net"]].sum()),signal_groups=int((~forced).sum()),signal_net=float(trades[~forced,ti["net"]].sum()),closed_quantity=int(trades[:,ti["quantity"]].sum()),win_quantity=int(trades[trades[:,ti["net"]]>0,ti["quantity"]].sum()),loss_quantity=int(trades[trades[:,ti["net"]]<0,ti["quantity"]].sum()),long_net=float(trades[trades[:,ti["side"]]==1,ti["net"]].sum()),short_net=float(trades[trades[:,ti["side"]]==-1,ti["net"]].sum()))
            rows.append(row)
        path=out/(symbol+"_"+scene+".npz");np.savez_compressed(path,**arrays)
        caches.append(dict(symbol=symbol,session=scene,path=path.relative_to(ROOT).as_posix(),sha256=sha(path)))
        input_reads.append(dict(path=item["path"],sha256=item["sha256"],reads=1))
        print(scene,symbol,"十二条件保存",flush=True)
    for rel,h in fixed["sources"].items():assert sha(ROOT/rel)==h,rel
    assert len(rows)==984 and len(caches)==82
    save(HERE/"十二条件と二商品全四十一場の会計.json",dict(passed=True,rows=rows,cache=caches,input_reads=input_reads,sessions=manifest["sessions"],specs=specifications(),order_columns=list(E.ORDER_COLUMNS),trade_columns=list(E.TRADE_COLUMNS),curve_columns=list(E.CURVE_COLUMNS),summary_columns=list(E.SUMMARY_COLUMNS),sources=fixed["sources"],financial_accounts=len(rows),original_market_reads=0,API=0,real_orders=0,limitations="既知41場の開発。実ミニ・マイクロ板・二市場受信時計・待ち順位は未観測。利益率分母は質問中で合否判定しない。各セッション通常数量参加を比較。"))


if __name__=="__main__":execute()
