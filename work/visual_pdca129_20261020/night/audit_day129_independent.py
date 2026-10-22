"""日中新核を独立人工で監査する。原市場ファイル・金融再生は使用しない。"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

HERE=Path(__file__).resolve().parent
TASK=HERE.parent
ROOT=HERE.parents[2]
OLD=ROOT/"work/daynight128_20261020"
os.environ["NUMBA_CACHE_DIR"]=str(HERE/"audit_jit")
sys.dont_write_bytecode=True
sys.path[:0]=[str(TASK),str(OLD)]
import numba
numba.config.CACHE_DIR=os.environ["NUMBA_CACHE_DIR"]
import day129
import day_core2
import adapter5
import bbo_order_kernel126

NAMES=("orders","trades","curve","stats","cycles","order_uids","execution_events",
       "execution_states","actual_parents","parent_mapping")
CHECKS=[]


def check(name: str, actual: object, expected: object) -> None:
    """
    機能: 独立に定めた期待値と配列又は値を厳密比較する。
    引数: name(str)、actual/expected(object)は説明・観測・期待。
    返り値: None。不一致は直ちに停止する。
    """
    np.testing.assert_array_equal(actual,expected,err_msg=name)
    CHECKS.append(name)


def fixture(qty: int=5, partial: bool=False, second: bool=False) -> dict:
    """
    機能: 二市場逆行・撤退・その後の回復を一秒刻みの独立人工で作る。
    引数: qty(int)、partial/second(bool)は数量、部分返済、後続影の有無。
    返り値: dictは被監査入力。実データは読まない。
    """
    n=95
    times=np.arange(n,dtype=float)
    bid=np.full(n,100.5)
    bid[:3]=100.
    bid[3:6]=98.
    bid[40:]=102.
    ask=bid+1.
    market=np.zeros((n,12))
    market[:,:2]=((bid+ask)/2.)[:,None]
    market[:,2:4]=4.
    market[:,4:8]=.2
    market[:,8]=times-.5
    market[:,9]=times-30.
    market[:,10]=times-30.5
    market[:,11]=1.
    feed=[[1,0,0,1,qty,100.5,20,1,0,4.]]
    if partial:
        first=2 if qty==5 else 5
        later=1 if qty==5 else 2
        feed.extend([[3,2,0,-1,first,99.5,7,0,0,0],
                     [50,49,0,-1,later,102.5,7,0,0,0],
                     [70,69,0,-1,qty-first-later,102.5,9,0,0,0]])
    else:
        first=2 if qty==5 else 5
        feed.extend([[50,49,0,-1,first,102.5,7,0,0,0],
                     [70,69,0,-1,qty-first,102.5,9,0,0,0]])
    if second:
        feed.extend([[80,79,9,-1,qty,102.5,20,1,0,4.],
                     [90,89,9,1,qty,102.5,9,0,0,0]])
    return dict(times=times,prices=(bid+ask)/2.,bid=bid,ask=ask,qok=np.ones(n,bool),
                feed=np.array(feed,float),end=94.,cap=10 if qty==5 else 20,
                market=market,policy=np.array([0.,.5,0.,0.,.75,.5]),
                current_atr=np.full(n,4.),history=np.full((n,15),np.nan),exit_rule=1)


def run(v: dict, width: float, retry: bool, compiled: bool=False) -> dict:
    """
    機能: 人工だけを被監査核へ入力する。
    引数: v(dict)、width(float)、retry/compiled(bool)は入力・撤退幅・再参加・ＪＩＴ。
    返り値: dictは出力配列。
    """
    fn=day129.simulate if compiled else day129.simulate.py_func
    return dict(zip(NAMES,fn(**v,withdrawal_width=width,allow_reentry=retry)))


def ledger(v: dict, result: dict, qty: int) -> dict:
    """
    機能: 注文から親別数量・損益・料金と全行時価を核の会計を使わず再計算する。
    引数: v/result(dict)、qty(int)は人工入力・出力・一回新規枚数。
    返り値: dictは独立の親別手数料後会計。
    """
    lots={}
    cash=0.
    realized=0.
    peak=0.
    maxdd=0.
    fees={}
    gains={}
    mult,rate=(1000.,418) if qty==5 else (10.,110)
    markbid=markask=np.nan
    for i in range(len(v["times"])):
        if v["qok"][i] and 0<v["bid"][i]<v["ask"][i]:
            markbid,markask=v["bid"][i],v["ask"][i]
        for o in result["orders"][result["orders"][:,0]==i]:
            _,source,cid,side,quantity=map(int,o[:5])
            check(f"次行_{qty}_{i}_{cid}",source<i,True)
            check(f"注文気配_{qty}_{i}_{cid}",o[5],v["ask"][i] if side>0 else v["bid"][i])
            cash-=side*quantity*o[5]
            fees[cid]=fees.get(cid,0)+quantity*rate//10
            if o[7]:
                check(f"別親新規_{qty}_{cid}",cid not in lots,True)
                lots[cid]=[side,quantity,o[5]]
                gains[cid]=0.
            else:
                s,left,p=lots[cid]
                check(f"返済反対方向_{qty}_{i}_{cid}",side,-s)
                check(f"過剰返済なし_{qty}_{i}_{cid}",quantity<=left,True)
                gain=s*quantity*(o[5]-p)
                realized+=gain
                gains[cid]+=gain
                lots[cid][1]-=quantity
        long=sum(l[1] for l in lots.values() if l[0]>0)
        short=sum(l[1] for l in lots.values() if l[0]<0)
        equity=cash+long*markbid-short*markask
        peak=max(peak,equity);maxdd=max(maxdd,peak-equity)
        check(f"行会計_{qty}_{i}",result["curve"][i,:7],
              [equity,realized,long,short,maxdd,cash,long-short])
    check(f"最終数量_{qty}",sum(l[1] for l in lots.values()),0)
    check(f"現金と決済一致_{qty}",cash,realized)
    independent={cid:gain*mult-fees[cid] for cid,gain in gains.items()}
    ready=dict(symbol="TOPIX" if qty==5 else "NK225",session="人工_Day")
    config=dict(id="人工",name="人工",kind="Day",engine="day")
    official=adapter5.summarize(result,ready,config)
    check(f"円利益_{qty}",official["profit"],sum(max(x,0.) for x in independent.values()))
    check(f"円損失_{qty}",official["loss"],sum(max(-x,0.) for x in independent.values()))
    check(f"円収支_{qty}",official["net"],sum(independent.values()))
    check(f"注文費用_{qty}",official["fees"],sum(fees.values()))
    return dict(parents=independent,summary=official)


def main() -> None:
    """
    機能: 未登録の人工だけで互換・時点・別親・返済・会計を独立照合する。
    引数: なし。
    返り値: None。成功時だけ指紋付き passed:true 証跡を作る。
    """
    paths=[TASK/"day129.py",TASK/"run_day129.py",TASK/"日中第一巡条件.json",
           TASK/"日中第一巡の変更根拠.json",OLD/"day_core2.py",OLD/"adapter5.py",
           Path(bbo_order_kernel126.__file__),Path(__file__)]
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    cases=[]
    for qty in (5,10):
        for partial in (False,True):
            value=fixture(qty,partial)
            baseline=run(value,0.,False)
            original=day_core2.simulate.py_func(**value)
            for field,wanted in zip(NAMES[:9],original):
                check(f"旧核互換_{qty}_{partial}_{field}",baseline[field],wanted)
            for width in (.25,.5):
                for retry in (False,True):
                    result=run(value,width,retry)
                    accounts=ledger(value,result,qty)
                    cases.append(dict(qty=qty,partial=partial,width=width,retry=retry,**accounts))
                    mirrored=deepcopy(value)
                    mirrored["prices"]=220.-value["prices"]
                    mirrored["bid"],mirrored["ask"]=220.-value["ask"],220.-value["bid"]
                    mirrored["market"][:,:2]=220.-value["market"][:,:2]
                    mirrored["market"][:,4:8]*=-1.
                    mirrored["feed"][:,3]*=-1.
                    mirrored["feed"][:,5]=220.-value["feed"][:,5]
                    reflected=run(mirrored,width,retry)
                    check(f"上下時価_{qty}_{partial}_{width}_{retry}",result["curve"][:,:5],reflected["curve"][:,[0,1,3,2,4]])
                    check(f"上下方向_{qty}_{partial}_{width}_{retry}",result["orders"][:,3],-reflected["orders"][:,3])
                    check(f"同一影高々二回_{qty}_{partial}_{width}_{retry}",
                          max(np.unique(result["parent_mapping"][:,1],return_counts=True)[1]),2 if retry else 1)
                    if retry:
                        anchors=result["execution_events"][result["execution_events"][:,1]==16]
                        exits=result["orders"][result["orders"][:,6]==75]
                        for anchor,ex in zip(anchors,exits):
                            row=int(anchor[0]);closed=int(ex[0])
                            check(f"返済後自己アンカー_{qty}_{partial}_{width}",value["times"][row]>value["times"][closed],True)
                            check(f"返済後相手アンカー_{qty}_{partial}_{width}",value["market"][row,8]>value["times"][closed],True)
                    compiled=run(value,width,retry,True)
                    for field in NAMES:
                        check(f"JIT_{qty}_{partial}_{width}_{retry}_{field}",compiled[field],result[field])
            # ----------------------------------------
            # 将来の影親IDを足しても、過去の注文ID・数量・価格を変えてはいけない。
            base=run(value,.25,True)
            future=run(fixture(qty,partial,True),.25,True)
            check(f"未来別親追加の注文接頭_{qty}_{partial}",
                  future["orders"][future["orders"][:,0]<70],base["orders"][base["orders"][:,0]<70])
            poisoned=deepcopy(value)
            cut=45
            for name in ("prices","bid","ask"):
                poisoned[name][cut:]+=30.
            poisoned["market"][cut:,:2]-=30.
            altered=run(poisoned,.25,True)
            check(f"未来価格毒化の時価接頭_{qty}_{partial}",altered["curve"][:cut],base["curve"][:cut])
            check(f"未来価格毒化の注文接頭_{qty}_{partial}",
                  altered["orders"][altered["orders"][:,0]<cut],base["orders"][base["orders"][:,0]<cut])
    # ----------------------------------------
    # 登録候補とrunnerの固定接続を照合し、金融mainは呼ばない。
    configs=json.loads((TASK/"日中第一巡条件.json").read_text(encoding="utf-8-sig"))
    check("登録四条件",[(c["id"],c["withdrawal_width"],c["allow_reentry"]) for c in configs],
          [("DV01",.25,False),("DV02",.25,True),("DV03",.5,False),("DV04",.5,True)])
    check("実注文会計核の固定写し",hashlib.sha256((TASK/"bbo_order_kernel126.py").read_bytes()).hexdigest(),
          hashlib.sha256((OLD/"bbo_order_kernel126.py").read_bytes()).hexdigest())
    check("監査中の源無変更",hashes,{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    output=dict(passed=True,checks=CHECKS,cases=cases,source_hashes=hashes,
                financial_replays=0,original_market_reads=0,API=0)
    path=HERE/f"日中新核の独立人工監査_{time.time_ns()}.json"
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(passed=True,checks=len(CHECKS),cases=len(cases),path=str(path)),ensure_ascii=False))


if __name__=="__main__":
    main()
