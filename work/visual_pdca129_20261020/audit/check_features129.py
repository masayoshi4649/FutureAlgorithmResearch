"""価格源と安全な窓端・相手時計を市場データなしで独立検査する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def fixture():
    """
    機能: 同秒の原行が三つある二市場の人工素材を作る。
    引数: なし。
    返り値: dictは実市場を含まない価格・気配・公開ATR。
    """
    packet = dict(inputs={}, quotes={})
    for symbol, base, scale in (("TOPIX",1000.,.01),("NK225",2000.,.02)):
        times = np.repeat(np.arange(0.,5401.,10.),3)
        duplicate = np.tile(np.arange(3.),len(times)//3)
        mid = base+times*scale+duplicate*.1
        key = ("人工_Night",symbol)
        packet["inputs"][key] = dict(session=key[0],symbol=symbol,start=0.,time_s=times,
            seq=np.arange(len(times)),last=mid+np.sin(times/111.)*.1,atr=np.full(len(times),2. if symbol=="TOPIX" else 4.))
        packet["quotes"][key] = dict(bid=mid-.5,ask=mid+.5,quote_valid=np.ones(len(times),bool))
    return packet


def cut_packet(packet, count):
    """
    機能: 同秒群の途中を含む位置で全市場入力を切る。
    引数: packet(dict)、count(int)は人工素材と残す行数。
    返り値: dictは原行prefix。
    """
    out = deepcopy(packet)
    for category in ("inputs","quotes"):
        for value in out[category].values():
            for name, field in value.items():
                if isinstance(field,np.ndarray):
                    value[name]=field[:count].copy()
    return out


def expected_change(ready, seconds):
    """
    機能: 列探索を使わず、窓端の厳密過去を行ごとに採る。
    引数: ready(dict)、seconds(float)は人工入力と窓幅。
    返り値: tuple[ndarray,ndarray]は差分と元時刻の独立期待値。
    """
    times,price,atr=ready["time_s"],ready["last"],ready["atr"]
    value=np.full(len(times),np.nan);source=np.full(len(times),np.nan)
    for i,t in enumerate(times):
        candidates=np.flatnonzero(times<t-seconds)
        if not len(candidates):
            continue
        j=candidates[-1]
        if t-seconds-times[j]<=30 and np.isfinite([price[i],price[j],atr[i]]).all() and atr[i]>0:
            value[i]=(price[i]-price[j])/atr[i]
            source[i]=times[j]
    return value,source


def expected_market(inputs,delay):
    """
    機能: 相手の厳密過去と遅延後鮮度から十二列の期待値を作る。
    引数: inputs(dict)、delay(float)は人工入力と0又は60秒。
    返り値: dictは独立計算した二市場特徴。
    """
    changes={k:{s:expected_change(v,s) for s in (30.,120.)} for k,v in inputs.items()}
    result={}
    for key, own in inputs.items():
        otherkey=(key[0],"NK225" if key[1]=="TOPIX" else "TOPIX")
        peer=inputs[otherkey]
        value=np.full((len(own["time_s"]),12),np.nan)
        for i,t in enumerate(own["time_s"]):
            value[i,0]=own["last"][i];value[i,2]=own["atr"][i]
            value[i,4]=changes[key][30.][0][i];value[i,5]=changes[key][120.][0][i]
            value[i,9]=changes[key][30.][1][i];value[i,11]=0.
            candidates=np.flatnonzero(peer["time_s"]<t-delay)
            if not len(candidates):
                continue
            j=candidates[-1]
            if t-delay-peer["time_s"][j]>15.:
                continue
            if not np.isfinite([own["last"][i],own["atr"][i],peer["last"][j],peer["atr"][j]]).all():
                continue
            if min(own["atr"][i],peer["atr"][j])<=0:
                continue
            value[i,[1,3,6,7,8,10,11]]=[
                peer["last"][j],peer["atr"][j],changes[otherkey][30.][0][j],
                changes[otherkey][120.][0][j],peer["time_s"][j],changes[otherkey][30.][1][j],1.]
        result[key]=value
    return result


def expected_long(inputs):
    """
    機能: 確定一分終値61個から60分差と価格帯を独立作成する。
    引数: inputs(dict)は人工二市場。
    返り値: dictは公開遅延・鮮度を適用した六列期待値。
    """
    data={}
    for key,r in inputs.items():
        times,prices=r["time_s"],r["last"]
        close={}
        for end in np.arange(r["start"]+60.,times[-1]+.001,60.):
            available=np.flatnonzero((times<end)&np.isfinite(prices)&(prices>0))
            close[end]=prices[available[-1]] if len(available) and end-times[available[-1]]<=90. else np.nan
        values={}
        for end in list(close)[60:]:
            segment=np.array([close[end-i*60.] for i in range(60,-1,-1)])
            values[end]=[segment[-1]-segment[0],np.max(segment),np.min(segment),end] if np.isfinite(segment).all() else [np.nan]*4
        data[key]=(close,values)
    out={}
    for key,r in inputs.items():
        peer=(key[0],"NK225" if key[1]=="TOPIX" else "TOPIX")
        value=np.full((len(r["time_s"]),6),np.nan)
        for i,t in enumerate(r["time_s"]):
            ownends=[e for e in data[key][0] if e+60<=t]
            peerends=[e for e in data[peer][0] if e+120<=t]
            if not ownends or not peerends:
                continue
            oe,pe=max(ownends),max(peerends)
            own=data[key][1].get(oe,[np.nan]*4);other=data[peer][1].get(pe,[np.nan]*4)
            if t-own[3]>=120. or t-other[3]>=180.:
                continue
            value[i]=own[:3]+[other[0],own[3],other[3]]
        out[key]=value
    return out


def main():
    """
    機能: 特徴源を固定複写し手計算・接頭・鏡像・欠測等を検査する。
    引数: なし。
    返り値: None。成功と失敗を新しい監査JSONへ保存する。
    """
    run_id=str(time.time_ns())
    source=WORK/"features129.py"
    snapshot=HERE/f"features129_人工時点_{run_id}.py"
    snapshot.write_bytes(source.read_bytes())
    sys.path.insert(0,str(WORK))
    spec=importlib.util.spec_from_file_location("特徴129人工_"+run_id,snapshot)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    tests=[]

    def check(name, fn):
        """
        機能: 一つの独立人工ケースの例外も証跡へ残す。
        引数: name(str)、fn(callable)は名称と検査処理。
        返り値: None。
        """
        try:
            fn();tests.append({"確認":name,"合格":True})
        except Exception as exc:
            tests.append({"確認":name,"合格":False,"詳細":type(exc).__name__+": "+str(exc)})

    packet=fixture()
    keys=list(packet["inputs"])
    results={}
    for kind in ("mid","last"):
        for delay in (0.,60.):
            full=module.build(packet,kind,delay)
            results[kind,delay]=full

            def independent(full=full,kind=kind,delay=delay):
                """
                機能: 価格選択と全十二列・長期六列を別実装に照合する。
                引数: full(tuple)、kind(str)、delay(float)は実出力と条件。
                返り値: None。
                """
                inputs,market,hist,long=full
                for key in keys:
                    expected=(packet["quotes"][key]["bid"]+packet["quotes"][key]["ask"])*.5 if kind=="mid" else packet["inputs"][key]["last"]
                    np.testing.assert_array_equal(inputs[key]["last"],expected)
                    np.testing.assert_array_equal(inputs[key]["atr"],packet["inputs"][key]["atr"])
                    np.testing.assert_array_equal(inputs[key]["seq"],packet["inputs"][key]["seq"])
                expected=expected_market(inputs,delay)
                longer=expected_long(inputs)
                for key in keys:
                    np.testing.assert_allclose(market[key],expected[key],atol=1e-12,rtol=0)
                    np.testing.assert_allclose(long[key],longer[key],atol=1e-12,rtol=0)
                    times=inputs[key]["time_s"]
                    known=market[key][:,11]==1
                    assert (market[key][known,8]<times[known]-delay).all()
                    assert (times[known]-market[key][known,8]<=delay+15).all()
                    known=np.isfinite(long[key]).all(axis=1)
                    assert (long[key][known,4]+60<=times[known]).all()
                    assert (long[key][known,5]+120<=times[known]).all()
                    assert not np.isfinite(long[key][times<3780]).all(axis=1).any()
            check(f"{kind}・相手{delay:g}秒の独立期待値",independent)

            for count in (398,1157,1442):
                def prefix(count=count,kind=kind,delay=delay,full=full):
                    """
                    機能: 同時計群の途中で切ったprefixが不変か検査する。
                    引数: count(int)、kind(str)、delay(float)、full(tuple)は人工条件。
                    返り値: None。
                    """
                    changed=module.build(cut_packet(packet,count),kind,delay)
                    for key in keys:
                        for component in (1,2,3):
                            np.testing.assert_array_equal(changed[component][key],full[component][key][:count])
                check(f"{kind}・遅延{delay:g}・同秒途中prefix{count}",prefix)

            def poison(kind=kind,delay=delay,full=full):
                """
                機能: 同時計群の後続価格・気配・ATR毒化が既知prefixへ伝わらないことを検査する。
                引数: kind(str)、delay(float)、full(tuple)は条件と元出力。
                返り値: None。
                """
                changed=deepcopy(packet);count=1157
                for key in keys:
                    changed["inputs"][key]["last"][count:]+=5000
                    changed["inputs"][key]["atr"][count:]*=100
                    changed["quotes"][key]["bid"][count:]+=5000
                    changed["quotes"][key]["ask"][count:]+=5000
                output=module.build(changed,kind,delay)
                for key in keys:
                    for component in (1,2,3):
                        np.testing.assert_array_equal(output[component][key][:count],full[component][key][:count])
            check(f"{kind}・遅延{delay:g}・同秒後続未来毒化",poison)

    def boundary():
        """
        機能: 窓端及び相手の遅延境界ちょうどの毒値を除外する。
        引数: なし。
        返り値: None。
        """
        ready={"time_s":np.array([0.,29.,30.,30.,31.,59.,60.,60.,61.]),
               "last":np.array([100.,101.,900.,800.,102.,103.,700.,600.,104.]),
               "atr":np.ones(9)}
        diff,stamp=module.changes(ready,30.)
        assert diff[6]==700.-101. and stamp[6]==29.
        assert diff[8]==104.-800. and stamp[8]==30.
        inputs={("人工_Night",s):deepcopy(ready) for s in ("TOPIX","NK225")}
        m=module.markets(inputs,0.)[("人工_Night","TOPIX")]
        assert m[6,1]==103. and m[6,8]==59.
        m=module.markets(inputs,60.)[("人工_Night","TOPIX")]
        assert m[8,1]==100. and m[8,8]==0.
    check("窓端と相手遅延境界の同秒毒値拒否",boundary)

    def missing():
        """
        機能: 異常気配を中値へ混ぜず長い欠測を有効な静止にしない。
        引数: なし。
        返り値: None。
        """
        altered=deepcopy(packet)
        for key in keys:
            q=altered["quotes"][key];t=altered["inputs"][key]["time_s"]
            q["quote_valid"][(t>=3000)&(t<3300)]=False
            q["bid"][100]=np.nan;q["ask"][101]=q["bid"][101];q["bid"][102]=-1
        prices,m,h,l=module.build(altered,"mid",60.)
        for key in keys:
            t=altered["inputs"][key]["time_s"]
            assert np.isnan(prices[key]["last"][100:103]).all()
            assert np.isnan(prices[key]["last"][(t>=3000)&(t<3300)]).all()
            assert not (m[key][(t>=3000)&(t<3300),11]==1).any()
            assert not np.isfinite(h[key][(t>=3240)&(t<=3540)]).all(axis=1).any()
            assert not np.isfinite(l[key][t>=3780]).all(axis=1).any()
        allmissing=deepcopy(packet)
        for q in allmissing["quotes"].values():q["quote_valid"][:]=False
        prices,m,h,l=module.build(allmissing,"mid",0.)
        for key in keys:
            assert not np.isfinite(prices[key]["last"]).any()
            assert not np.isfinite(h[key]).any() and not np.isfinite(l[key]).any()
            assert not (m[key][:,11]==1).any()
    check("不正常気配・長い欠測・全欠測",missing)

    def stale():
        """
        機能: 片市場の更新終了後に短期・中期・長期が永久有効にならない。
        引数: なし。
        返り値: None。
        """
        changed=deepcopy(packet);peer=keys[1];n=1300
        for category in ("inputs","quotes"):
            for k,v in changed[category][peer].items():
                if isinstance(v,np.ndarray):changed[category][peer][k]=v[:n]
        last=changed["inputs"][peer]["time_s"][-1]
        for delay in (0.,60.):
            _,m,h,l=module.build(changed,"mid",delay)
            t=changed["inputs"][keys[0]]["time_s"]
            assert not (m[keys[0]][t>last+delay+15,11]==1).any()
            assert not np.isfinite(h[keys[0]][t>last+180]).all(axis=1).any()
            assert not np.isfinite(l[keys[0]][t>last+180]).all(axis=1).any()
    check("相手終端後の短中長期鮮度",stale)

    def reflection():
        """
        機能: 正価格の範囲内で上下反転した人工入力の売買対称性を確認する。
        引数: なし。
        返り値: None。
        """
        changed=deepcopy(packet)
        for key in keys:
            base=1000. if key[1]=="TOPIX" else 2000.
            changed["inputs"][key]["last"]=2*base-packet["inputs"][key]["last"]
            changed["quotes"][key]["bid"]=2*base-packet["quotes"][key]["ask"]
            changed["quotes"][key]["ask"]=2*base-packet["quotes"][key]["bid"]
        for kind in ("mid","last"):
            actual=module.build(changed,kind,60.)
            original=results[kind,60.]
            for key in keys:
                own=1000. if key[1]=="TOPIX" else 2000.;peer=3000.-own
                m=original[1][key].copy()
                m[:,0]=2*own-m[:,0];m[:,1]=2*peer-m[:,1];m[:,4:8]*=-1
                np.testing.assert_allclose(actual[1][key],m,rtol=0,atol=1e-10)
                v=original[3][key];expected=v.copy()
                expected[:,0]=-v[:,0];expected[:,1]=2*own-v[:,2];expected[:,2]=2*own-v[:,1]
                expected[:,3]=-v[:,3]
                np.testing.assert_allclose(actual[3][key],expected,rtol=0,atol=1e-10)
    check("Lastとmidの上下鏡像",reflection)

    def unchanged():
        """
        機能: 元入力を変更せず旧ATRの数値と因果的な公開欠測を保持する。
        引数: なし。
        返り値: None。
        """
        changed=deepcopy(packet)
        for r in changed["inputs"].values():
            r["atr"][:90]=np.nan;r["atr"][400:420]=0
        before=deepcopy(changed)
        _,m,_,_=module.build(changed,"mid",60.)
        for key in keys:
            for field in changed["inputs"][key]:
                a,b=changed["inputs"][key][field],before["inputs"][key][field]
                if isinstance(a,np.ndarray):np.testing.assert_array_equal(a,b)
            assert not (m[key][:90,11]==1).any()
            assert not (m[key][400:420,11]==1).any()
    check("旧ATR欠測保持と元入力非変更",unchanged)

    sources=[source,WORK/"common129.py",ROOT/"work/daynight128_20261020/features128.py",Path(__file__),snapshot]
    result={"全合格":all(t["合格"] for t in tests),"件数":len(tests),"確認":tests,
            "数値源SHA256":{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
            "金融再生":0,"原市場読取":0,
            "限界":"純人工上の因果性と仕様一致。保存されていない実受信順や相手遅延の実時間妥当性を証明しない。"}
    target=HERE/f"中値と窓端及び相手遅延の独立人工_{run_id}.json"
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
    print(target.relative_to(ROOT).as_posix())


if __name__=="__main__":
    main()
