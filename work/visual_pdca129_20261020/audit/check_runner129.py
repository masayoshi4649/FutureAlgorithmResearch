"""第一巡の接続を人工素材・代用核で確認し、旧核のBBO約定も人工再確認する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import tempfile
import time

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
PREV=ROOT/"work/daynight128_20261020"
sys.path.insert(0,str(WORK))
sys.path.insert(0,str(HERE))
from check_features129 import fixture
sys.path.insert(0,str(PREV/"audit"))
from check_engines128 import load, night_fixture, check_night_account


def main():
    """
    機能: 実行接続の引数対応と旧数値核の純人工約定を確認する。
    引数: なし。
    返り値: None。原市場素材は読まず新しい証跡だけを保存する。
    """
    source=WORK/"run_night129.py"
    spec=importlib.util.spec_from_file_location("接続129独立人工",source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    configs=json.loads((WORK/"第一巡条件.json").read_text(encoding="utf-8-sig"))
    feature_proof=max(HERE.glob("中値と窓端及び相手遅延の独立人工_*.json"))
    proof=json.loads(feature_proof.read_text(encoding="utf-8-sig"))
    assert proof["全合格"]
    for path,digest in proof["数値源SHA256"].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    checks=[]

    def check(name,fn):
        """
        機能: 一件の検査を失敗理由とともに保存する。
        引数: name(str)、fn(callable)は名称と検査。
        返り値: None。
        """
        try:
            fn();checks.append({"確認":name,"合格":True})
        except Exception as exc:
            checks.append({"確認":name,"合格":False,"詳細":type(exc).__name__+": "+str(exc)})

    def controlled():
        """
        機能: 三条件がN36と同じ売買規則で価格源・相手遅延だけ異なることを確認する。
        引数: なし。
        返り値: None。
        """
        old=json.loads((PREV/"第五巡条件.json").read_text(encoding="utf-8-sig"))
        n36=next(c for c in old if c["id"]=="N36")
        assert [(c["price_source"],c["peer_delay"]) for c in configs]==[("last",0.),("mid",0.),("mid",60.)]
        for c in configs:
            for key in module.PARAMETERS:
                assert c[key]==n36[key]
        assert hashlib.sha256((PREV/"night5.py").read_bytes()).hexdigest()=="8478131779b79252269342c1d79148bc04283db8abc52518fc6dcf2582a5b1c4"
    check("三条件は価格と時計以外N36を保持",controlled)

    def connection():
        """
        機能: mainを人工packetと代用核で通し原行・ATR・気配・料金の接続を検査する。
        引数: なし。
        返り値: None。金融状態機械は呼ばない。
        """
        packet=fixture()
        for (scene,symbol),r in packet["inputs"].items():
            r.update(limit=5350.,us_open=0.,tick=.5 if symbol=="TOPIX" else 10.)
        expected={(c["price_source"],c["peer_delay"]):module.build(packet,c["price_source"],c["peer_delay"]) for c in configs}
        calls=[];saves={};archives=[]
        fixed_sources=module.sources()
        old=(module.HERE,module.ROOT,module.read,module.save,module.night5.simulate,np.savez_compressed,sys.argv[:])
        with tempfile.TemporaryDirectory(prefix="runner人工_",dir=HERE) as temp:
            temp=Path(temp);payload=pickle.dumps(packet)
            input_path=temp/"人工packet.pkl";input_path.write_bytes(payload)
            ref={"session":"人工_Night","path":input_path.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(payload).hexdigest()}
            fixed=dict(sources=fixed_sources,configs=configs,artificial=[],input_references=[])
            def reader(path):
                """
                機能: 実行計画と素材目録だけを人工資料へ差し替える。
                引数: path(Path)は読み取る位置。
                返り値: dictは人工計画又は目録。
                """
                if path.name=="固定計画.json":return fixed
                if path.name=="登録.json":return {"returncode":0}
                if path.name=="入力準備.json":return {"packets":[{"session":"人工_Day"},ref]}
                raise AssertionError(path)
            def store(path,value):
                """
                機能: mainの出力をファイルにせず検査用メモリに保存する。
                引数: path(Path)、value(dict)は予定出力。
                返り値: None。
                """
                saves[path.name]=deepcopy(value)
            def archive(path,**values):
                """
                機能: 圧縮保存の代わりに人工配列の出力名を記録する。
                引数: path(Path)、values(dict[str,ndarray])は予定出力。
                返り値: None。
                """
                archives.append((path,deepcopy(values)))
            def fake_core(*args):
                """
                機能: 数値核を実行せず入力対応を検査し固定二注文を返す。
                引数: args(tuple)は実接続から渡された十六引数。
                返り値: tupleは人工の注文・完結親・曲線。
                """
                index=len(calls);c=configs[index//2];symbol=("TOPIX","NK225")[index%2]
                key=("人工_Night",symbol);inputs,market,history,_=expected[c["price_source"],c["peer_delay"]]
                r,q=inputs[key],packet["quotes"][key]
                for actual,wanted in zip(args[:8],(r["time_s"],r["last"],q["bid"],q["ask"],q["quote_valid"],r["atr"],history[key],market[key])):
                    np.testing.assert_array_equal(actual,wanted)
                assert len(args[0])==len(packet["inputs"][key]["seq"])
                assert tuple(args[8:15])==(r["start"],r["limit"],r["us_open"],r["tick"],5 if symbol=="TOPIX" else 10,1000. if symbol=="TOPIX" else 10.,418 if symbol=="TOPIX" else 110)
                np.testing.assert_array_equal(args[15],[c[k] for k in module.PARAMETERS])
                calls.append((c["id"],symbol))
                qty,mult,rate=args[12:15];side=1 if symbol=="TOPIX" else -1
                new=args[3][2] if side>0 else args[2][2]
                close=args[2][4] if side>0 else args[3][4]
                gross=side*(close-new)*qty*mult;fee=2*(qty*rate//10);net=gross-fee
                orders=np.array([[2,1,0,side,qty,new,1,1],[4,3,0,-side,qty,close,99,0]],float)
                trades=np.array([[2,4,side,qty,new,close,gross,fee,net,0,0,2,99,2]],float)
                curve=np.zeros((len(args[0]),4));curve[-1,0]=net;curve[-1,2]=fee
                return orders,trades,curve
            try:
                module.HERE=temp;module.read=reader;module.save=store
                module.sources=lambda:fixed_sources
                module.reference=lambda path:{"path":str(path),"sha256":"人工の未保存配列"}
                module.night5.simulate=fake_core
                np.savez_compressed=archive;sys.argv=["runner人工","--round","round人工"]
                module.main()
                assert calls==[(c["id"],s) for c in configs for s in ("TOPIX","NK225")]
                result=saves["全条件の会計.json"]
                assert len(result["rows"])==6 and len(archives)==2
                assert all(row["entries"]==1 and row["quantity"]==(5 if row["symbol"]=="TOPIX" else 10) for row in result["rows"])
                assert all(row["fees"]==(418 if row["symbol"]=="TOPIX" else 220) for row in result["rows"])
                assert all(set(v)=={c["id"]+"__"+n for c in configs for n in ("orders","trades","curve")} for _,v in archives)
            finally:
                module.HERE,module.ROOT,module.read,module.save,module.night5.simulate,np.savez_compressed,sys.argv=old
    check("実mainの三条件二商品を代用核で原行BBO料金接続",connection)

    core=load(PREV/"night5.py","夜間129接続の旧核人工").simulate.py_func
    for top in (True,False):
        for reflected in (False,True):
            for gap in (False,True):
                def execution(top=top,reflected=reflected,gap=gap):
                    """
                    機能: 旧核の次正常原行・上下対称・価格飛び・整数手数料を再確認する。
                    引数: top/reflected/gap(bool)は商品と人工経路。
                    返り値: None。
                    """
                    qty,mult,fee=(5,1000.,418) if top else (10,10.,110)
                    args=list(night_fixture([110.5,112.,112.5,117.5,114.5,113.5,113.5,113.5,113.5],qty,mult,fee,reflected))
                    args[6][:,5]=.5
                    args[-1]=np.array([configs[0][name] for name in module.PARAMETERS],float)
                    args[10]=-5000.
                    if gap:
                        args[4][2:4]=False
                    output=core(*args)
                    check_night_account(args,output)
                    assert len(output[0])>=2
                    assert output[0][0,0]==(4 if gap else 2)
                    assert output[0][0,1]==1
                    f=int(output[0][0,0]);side=output[0][0,3]
                    assert output[0][0,5]==(args[3][f] if side>0 else args[2][f])
                check(f"旧核次気配と料金_TOPIX{top}_上下反転{reflected}_欠測待ち{gap}",execution)
    result={"passed":all(x["合格"] for x in checks),"件数":len(checks),"確認":checks,
            "特徴人工":{"path":feature_proof.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(feature_proof.read_bytes()).hexdigest(),"合格数":proof["件数"]},
            "数値源SHA256":{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in
                          (source,WORK/"features129.py",WORK/"common129.py",WORK/"第一巡条件.json",PREV/"night5.py",PREV/"features128.py",Path(__file__))},
            "金融再生":0,"原市場読取":0,
            "範囲":"mainは代用核、旧注文核は人工経路だけ。実市場に対する注文再生成や成績探索は行っていない。"}
    path=HERE/f"第一巡価格源対照と接続の独立人工_{time.time_ns()}.json"
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False));print(path.relative_to(ROOT).as_posix())


if __name__=="__main__":
    main()
