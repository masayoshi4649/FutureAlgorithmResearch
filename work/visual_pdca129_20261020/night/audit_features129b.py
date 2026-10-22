"""六十分差の両端資格と全区間価格帯を、原市場なしで独立検算する。"""

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE=Path(__file__).resolve().parent
TASK=HERE.parent
ROOT=HERE.parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(TASK))
import features129
import features129b

CHECKS=[]


def same(name: str, actual: object, expected: object) -> None:
    """
    機能: 独立期待値との一致を記録する。
    引数: name(str)、actual/expected(object)は名称・観測・期待。
    返り値: None。不一致では停止する。
    """
    np.testing.assert_allclose(actual,expected,atol=1.e-10,rtol=0.,err_msg=name)
    CHECKS.append(name)


def fixture() -> dict:
    """
    機能: 同時計の三原行を含む二時間の独立価格・気配を作る。
    引数: なし。
    返り値: dictは人工二市場。元Lastと気配中心は意図的に異なる。
    """
    packet=dict(inputs={},quotes={})
    for symbol,base,scale in (("TOPIX",1000.,.01),("NK225",2000.,.02)):
        ts=np.repeat(np.arange(0.,7201.,10.),3)
        mid=base+scale*ts+np.tile([0.,.1,.2],len(ts)//3)
        key=("人工_Night",symbol)
        packet["inputs"][key]=dict(start=0.,time_s=ts,seq=np.arange(len(ts)),last=mid+3.,
            atr=np.full(len(ts),2. if symbol=="TOPIX" else 4.),symbol=symbol,session=key[0])
        packet["quotes"][key]=dict(bid=mid-.5,ask=mid+.5,quote_valid=np.ones(len(ts),bool))
    return packet


def expected_long(inputs: dict) -> dict:
    """
    機能: 各分末を逐次照合し、差は二端、高安は六十一値から別々に作る。
    引数: inputs(dict)は人工二市場の選択済み価格。
    返り値: dictは被監査の列探索を呼ばない六列期待値。
    """
    records={}
    for key,r in inputs.items():
        ends=np.arange(r["start"]+60.,r["time_s"][-1]+.001,60.)
        closes={}
        rowdata={}
        for end in ends:
            choices=np.flatnonzero((r["time_s"]<end)&np.isfinite(r["last"])&(r["last"]>0))
            close=np.nan
            if len(choices):
                j=int(choices[-1])
                if end-r["time_s"][j]<=90.:
                    close=float(r["last"][j])
            closes[end]=close
            out=[np.nan]*4
            if end-3600. in closes:
                first=closes[end-3600.]
                if np.isfinite(first) and np.isfinite(close):
                    out[0]=close-first;out[3]=end
                values=[closes[e] for e in np.arange(end-3600.,end+.001,60.)]
                if all(np.isfinite(values)):
                    out[1],out[2]=max(values),min(values)
            rowdata[end]=out
        records[key]=(ends,rowdata)
    result={}
    for key,r in inputs.items():
        other=(key[0],"NK225" if key[1]=="TOPIX" else "TOPIX")
        output=np.full((len(r["time_s"]),6),np.nan)
        for i,t in enumerate(r["time_s"]):
            own_candidates=[e for e in records[key][0] if e+60.<=t]
            peer_candidates=[e for e in records[other][0] if e+120.<=t]
            if not own_candidates or not peer_candidates:
                continue
            own=records[key][1][own_candidates[-1]]
            peer=records[other][1][peer_candidates[-1]]
            if t-own[3]>=120. or t-peer[3]>=180.:
                continue
            output[i]=own[:3]+[peer[0],own[3],peer[3]]
        result[key]=output
    return result


def cut(packet: dict, count: int) -> dict:
    """
    機能: 同時計の途中でも原行を接頭切断する。
    引数: packet(dict)、count(int)は人工素材と残す行数。
    返り値: dictは独立した接頭素材。
    """
    out=deepcopy(packet)
    for group in out.values():
        for entry in group.values():
            for name,value in entry.items():
                if isinstance(value,np.ndarray):
                    entry[name]=value[:count].copy()
    return out


def main() -> None:
    """
    機能: 欠測資格・公開時刻・上下対称・接頭不変・新旧源差分を確認する。
    引数: なし。
    返り値: None。合格時だけ passed:true の人工証拠を保存する。
    """
    paths=[TASK/n for n in ("features129.py","features129b.py","run_context129.py",
                           "run_context129b.py","night_context129.py","common129.py")]
    paths += [ROOT/"work/daynight128_20261020/features128.py",Path(__file__)]
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    original=fixture()
    scenarios={"欠測なし":original}
    for name,start,end in (("内部欠測",3900.,4200.),("後端欠測",5840.,6000.),("前端欠測",2240.,2340.)):
        p=deepcopy(original)
        for key,r in p["inputs"].items():
            missing=(r["time_s"]>=start)&(r["time_s"]<end)
            r["last"][missing]=np.nan
            p["quotes"][key]["quote_valid"][missing]=False
        scenarios[name]=p
    for label,packet in scenarios.items():
        for kind in ("mid","last"):
            for delay in (0.,60.):
                actual=features129b.build(packet,kind,delay)
                old=features129.build(packet,kind,delay)
                expected=expected_long(actual[0])
                for key,r in actual[0].items():
                    prefix=f"{label}_{kind}_{delay}_{key[1]}"
                    same(prefix+"_長期別計算",actual[3][key],expected[key])
                    same(prefix+"_短期源不変",actual[1][key],old[1][key])
                    same(prefix+"_中期源不変",actual[2][key],old[2][key])
                    same(prefix+"_旧ATR不変",r["atr"],packet["inputs"][key]["atr"])
                    same(prefix+"_原行順不変",r["seq"],packet["inputs"][key]["seq"])
                    t=r["time_s"];i=int(np.flatnonzero(t==6000.)[0])
                    if label=="内部欠測":
                        same(prefix+"_差だけ既知",np.isfinite(actual[3][key][i,[0,3,4,5]]),[True]*4)
                        same(prefix+"_価格帯は不明",np.isnan(actual[3][key][i,[1,2]]),[True]*2)
                        same(prefix+"_旧差は不明",np.isnan(old[3][key][i,0]),True)
                    elif label in ("前端欠測","後端欠測"):
                        same(prefix+"_自己差端欠測は不明",np.isnan(actual[3][key][i,[0,1,2,4]]),[True]*4)
                    else:
                        same(prefix+"_完全区間は旧同値",actual[3][key],old[3][key])
                    finite=np.isfinite(actual[3][key][:,0])
                    same(prefix+"_自己公開遅延",np.all(actual[3][key][finite,4]+60.<=t[finite]),True)
                    finite=np.isfinite(actual[3][key][:,3])
                    same(prefix+"_相手公開遅延",np.all(actual[3][key][finite,5]+120.<=t[finite]),True)
                    known=actual[1][key][:,11]==1.
                    same(prefix+"_相手厳密過去",np.all(actual[1][key][known,8]<t[known]-delay),True)
                    same(prefix+"_相手鮮度",np.all(t[known]-delay-actual[1][key][known,8]<=15.),True)
                # ----------------------------------------
                # 価格の後続同秒と将来を書き換えても過去の三種類の特徴は不変。
                count=1801
                shortened=features129b.build(cut(packet,count),kind,delay)
                poisoned=deepcopy(packet)
                for key,r in poisoned["inputs"].items():
                    r["last"][count:]+=5000.
                    r["atr"][count:]*=100.
                    poisoned["quotes"][key]["bid"][count:]+=5000.
                    poisoned["quotes"][key]["ask"][count:]+=5000.
                changed=features129b.build(poisoned,kind,delay)
                for key in actual[0]:
                    for component in (1,2,3):
                        same(f"{label}_{kind}_{delay}_{key[1]}_接頭{component}",
                             shortened[component][key],actual[component][key][:count])
                        same(f"{label}_{kind}_{delay}_{key[1]}_未来毒化{component}",
                             changed[component][key][:count],actual[component][key][:count])
    # ----------------------------------------
    # 中値は正常気配だけを採り、上下鏡像で差の符号と価格帯上下が対称になる。
    packet=scenarios["内部欠測"]
    mirrored=deepcopy(packet)
    for key in packet["inputs"]:
        center=3000. if key[1]=="TOPIX" else 6000.
        mirrored["inputs"][key]["last"]=center-packet["inputs"][key]["last"]
        mirrored["quotes"][key]["bid"]=center-packet["quotes"][key]["ask"]
        mirrored["quotes"][key]["ask"]=center-packet["quotes"][key]["bid"]
    for kind in ("mid","last"):
        a=features129b.build(packet,kind,60.)
        b=features129b.build(mirrored,kind,60.)
        for key in a[0]:
            own=3000. if key[1]=="TOPIX" else 6000.
            expected=a[3][key].copy()
            expected[:,0]*=-1.;expected[:,3]*=-1.
            expected[:,1],expected[:,2]=own-a[3][key][:,2],own-a[3][key][:,1]
            same(f"{kind}_{key[1]}_上下長期",b[3][key],expected)
            if kind=="mid":
                q=packet["quotes"][key]
                wanted=np.where(q["quote_valid"],(q["bid"]+q["ask"])/2.,np.nan)
                same(f"{key[1]}_正常中値",a[0][key]["last"],wanted)
    # ----------------------------------------
    # 源差分は変更した長期関数とrunner参照・巡名に限定される。
    old_ast=ast.parse((TASK/"features129.py").read_text(encoding="utf8"))
    new_ast=ast.parse((TASK/"features129b.py").read_text(encoding="utf8"))
    old_nodes={n.name:ast.dump(n,include_attributes=False) for n in old_ast.body if isinstance(n,ast.FunctionDef)}
    new_nodes={n.name:ast.dump(n,include_attributes=False) for n in new_ast.body if isinstance(n,ast.FunctionDef)}
    assert {k for k in old_nodes if old_nodes[k]!=new_nodes[k]}=={"long_history"}
    CHECKS.append("特徴源は長期関数だけ変更")
    old_runner=(TASK/"run_context129.py").read_text(encoding="utf8")
    new_runner=(TASK/"run_context129b.py").read_text(encoding="utf8")
    expected_runner=old_runner.replace("features129","features129b").replace("run_context129.py","run_context129b.py").replace('default="round2"','default="round3"')
    assert new_runner==expected_runner
    CHECKS.append("注文runnerは参照指紋と既定巡名だけ変更")
    assert hashes=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    result=dict(passed=True,checks=CHECKS,source_hashes=hashes,financial_replays=0,
                original_market_reads=0,API=0,
                limitation="因果的な端点定義と実装の一致。実受信時計と実市場有効性の保証ではない。")
    target=HERE/f"六十分差両端資格の独立人工監査_{time.time_ns()}.json"
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(passed=True,checks=len(CHECKS),path=str(target)),ensure_ascii=False))


if __name__=="__main__":
    main()
