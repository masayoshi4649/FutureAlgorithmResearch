"""保存日中注文を独立会計へ読み直す。売買判断の核は呼ばない。"""

import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

HERE=Path(__file__).resolve().parent
TASK=HERE.parent
ROOT=HERE.parents[2]
OLD=ROOT/"work/daynight128_20261020"
CHECKS=[]


def read(path: Path) -> dict:
    """
    機能: 保存会計又は入力参照を読む。
    引数: path(Path)は資料位置。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def equal(name: str, actual: object, expected: object) -> None:
    """
    機能: 独立計算との数値一致を確認する。
    引数: name(str)、actual/expected(object)は名称と二つの数値群。
    返り値: None。不一致は停止する。
    """
    np.testing.assert_allclose(actual,expected,rtol=0.,atol=1.e-8,err_msg=name)
    CHECKS.append(name)


def audit(ready: dict, quotes: dict, arrays: dict, row: dict) -> dict:
    """
    機能: 保存注文から全行現金・枚数・時価と完結親の手数料後収支を独立に作る。
    引数: ready/quotes/arrays/row(dict)は原入力・気配・保存出力・保存要約。
    返り値: dictは一商品一場一条件の独立会計。売買判断は再実行しない。
    """
    orders,trades,curve,cycles,links=(arrays[k] for k in ("orders","trades","curve","cycles","parent_mapping"))
    n=len(ready["time_s"])
    symbol=row["symbol"];mult,rate=(1000.,418) if symbol=="TOPIX" else (10.,110)
    prefix=f"{row['method']}_{row['session']}_{symbol}"
    qty=orders[:,4].astype(np.int64)
    erow=orders[:,0].astype(np.int64)
    side=orders[:,3].astype(np.int64)
    equal(prefix+"_整数数量",qty,orders[:,4])
    equal(prefix+"_次原行",np.all(orders[:,0]>orders[:,1]),True)
    good=quotes["quote_valid"]&np.isfinite(quotes["bid"])&np.isfinite(quotes["ask"])
    good&=(quotes["bid"]>0.)&(quotes["ask"]>quotes["bid"])
    equal(prefix+"_正常気配注文",np.all(good[erow]),True)
    fills=np.where(side>0,quotes["ask"][erow],quotes["bid"][erow])
    equal(prefix+"_実売買側気配",orders[:,5],fills)
    cashdelta=np.zeros(n);positiondelta=np.zeros(n);realizeddelta=np.zeros(n)
    np.add.at(cashdelta,erow,-side*qty*fills)
    np.add.at(positiondelta,erow,side*qty)
    np.add.at(realizeddelta,trades[:,7].astype(np.int64),trades[:,10])
    cash=np.cumsum(cashdelta);position=np.cumsum(positiondelta);realized=np.cumsum(realizeddelta)
    prior=np.maximum.accumulate(np.where(good,np.arange(n),0))
    mark=np.where(position>0,quotes["bid"][prior],quotes["ask"][prior])
    equity=cash+np.where(position!=0,position*mark,0.)
    dd=np.maximum.accumulate(np.maximum.accumulate(np.r_[0.,equity])[1:]-equity)
    wanted=np.column_stack([equity,realized,np.maximum(position,0.),np.maximum(-position,0.),
                            dd,cash,position])
    equal(prefix+"_全原行会計",curve[:,:7],wanted)
    equal(prefix+"_期末現金決済一致",cash[-1],realized[-1])
    equal(prefix+"_残玉なし",position[-1],0.)
    equal(prefix+"_上限",np.max(np.abs(position))<=(10 if symbol=="TOPIX" else 20),True)
    equal(prefix+"_初回再参加数量",qty[orders[:,7]==1],np.full(int(np.sum(orders[:,7]==1)),5 if symbol=="TOPIX" else 10))
    parents=[]
    fees=qty*rate//10
    for cid in np.unique(orders[:,2]):
        own=orders[orders[:,2]==cid]
        begin=own[own[:,7]==1]
        exits=own[own[:,7]==0]
        equal(prefix+f"_親{cid}一新規",len(begin),1)
        equal(prefix+f"_親{cid}数量保存",begin[:,4].sum(),exits[:,4].sum())
        sign=begin[0,3];entry=begin[0,5]
        gross=float(np.sum(sign*exits[:,4]*(exits[:,5]-entry))*mult)
        fee=int(fees[orders[:,2]==cid].sum());net=gross-fee
        saved=cycles[cycles[:,0]==cid]
        equal(prefix+f"_親{cid}完結会計",saved[:,3]*mult,[gross])
        mapping=links[links[:,0]==cid]
        equal(prefix+f"_親{cid}影対応",len(mapping),1)
        parents.append(dict(parent=int(cid),shadow=int(mapping[0,1]),attempt=int(mapping[0,2]),
            entry_row=int(begin[0,0]),exit_row=int(exits[-1,0]),side=int(sign),qty=int(begin[0,4]),
            entry=float(entry),exit=float(exits[-1,5]),gross=gross,fee=fee,net=net,
            last_reason=int(exits[-1,6])))
    net=sum(p["net"] for p in parents);profit=sum(max(0.,p["net"]) for p in parents)
    loss=sum(max(0.,-p["net"]) for p in parents)
    equal(prefix+"_要約損益",[row["profit"],row["loss"],row["net"],row["gross"],row["fees"]],
          [profit,loss,net,sum(p["gross"] for p in parents),sum(p["fee"] for p in parents)])
    equal(prefix+"_親件数",[row["parent_wins"],row["parent_losses"],row["entries"],row["quantity"]],
          [sum(p["net"]>0. for p in parents),sum(p["net"]<0. for p in parents),len(parents),
           int(qty[orders[:,7]==1].sum())])
    for shadow in np.unique(links[:,1]):
        equal(prefix+f"_影{shadow}再参加上限",len(links[links[:,1]==shadow])<=2,True)
    return dict(method=row["method"],session=row["session"],symbol=symbol,profit=profit,loss=loss,
                net=net,parents=parents)


def main() -> None:
    """
    機能: 完成済み日中第一巡の全保存会計を独立に検算する。
    引数: なし。
    返り値: None。指紋付き監査証拠と親別内訳を新規保存する。
    """
    folder=TASK/"day_round1"
    account=read(folder/"全条件の会計.json")
    refs={r["session"]:r for r in read(OLD/"入力準備.json")["packets"]}
    results=[]
    sources={str((folder/"全条件の会計.json").relative_to(ROOT)):
             hashlib.sha256((folder/"全条件の会計.json").read_bytes()).hexdigest()}
    for scene in sorted({r["session"] for r in account["rows"]}):
        ref=refs[scene]
        assert hashlib.sha256((ROOT/ref["path"]).read_bytes()).hexdigest()==ref["sha256"]
        packet=pickle.loads((ROOT/ref["path"]).read_bytes())
        for symbol in ("TOPIX","NK225"):
            path=folder/"measurement"/f"{symbol}_{scene}.npz"
            sources[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
            with np.load(path,allow_pickle=False) as saved:
                for row in [r for r in account["rows"] if r["session"]==scene and r["symbol"]==symbol]:
                    arrays={name:saved[row["method"]+"__"+name] for name in
                            ("orders","trades","curve","cycles","parent_mapping")}
                    results.append(audit(packet["inputs"][scene,symbol],packet["quotes"][scene,symbol],arrays,row))
        print(scene,"保存会計検算",flush=True)
    output=dict(passed=True,checks=CHECKS,rows=results,source_hashes=sources,financial_replays=0,
                API=0,scope="保存注文の全行会計再構築。注文判断の再運転なし。")
    target=HERE/f"日中第一巡の保存全行会計と親別照合_{time.time_ns()}.json"
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(passed=True,checks=len(CHECKS),rows=len(results),path=str(target)),ensure_ascii=False))


if __name__=="__main__":
    main()
