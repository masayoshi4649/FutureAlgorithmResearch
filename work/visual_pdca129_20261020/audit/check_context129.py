"""一時間文脈の追加分岐と旧核互換を市場データなしで独立監査する。"""

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
PREV=ROOT/"work/daynight128_20261020"
sys.path.insert(0,str(PREV/"audit"))
from check_engines128 import load, night_fixture, check_night_account
os.environ["NUMBA_CACHE_DIR"]=str(HERE/"jit_context129")
import numba
numba.config.CACHE_DIR=os.environ["NUMBA_CACHE_DIR"]


def fixture(reflected=False,top=True,steady=True):
    """
    機能: 文脈判定を準備後だけ変えられる人工突破経路を作る。
    引数: reflected/top/steady(bool)は上下反転、商品料金、平坦な後続。
    返り値: tuple[list,ndarray]は旧核引数と六列文脈。
    """
    qty,mult,fee=(5,1000.,418) if top else (10,10.,110)
    prices=[110.5,112.,112.5,112.5,112.5,112.5,112.5,112.5,112.5] if steady else [110.5,112.,112.5,117.5,114.5,113.5,113.5,113.5,113.5]
    args=list(night_fixture(prices,qty,mult,fee,reflected))
    args[6][:,5]=.5
    args[-1][0]=2.
    args[-1]=np.r_[args[-1],3.,2.,0.,1.e9]
    c=np.tile(np.array([1.,150.,50.,1.,-60.,-120.]),(len(prices),1))
    if reflected:c[:,[0,3]]*=-1
    return args,c


def main():
    """
    機能: mode0互換・各文脈の境界・未来非参照・JITと接続を検査する。
    引数: なし。
    返り値: None。失敗も含む新規証跡を監査領域へ保存する。
    """
    sources=[WORK/"night_context129.py",WORK/"run_context129.py",WORK/"features129.py",
             WORK/"第二巡条件.json",PREV/"night5.py",Path(__file__)]
    initial={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    old=load(PREV/"night5.py","文脈129の旧核").simulate.py_func
    module=load(WORK/"night_context129.py","文脈129の新核")
    new=module.simulate.py_func
    tests=[]

    def check(name,fn):
        """
        機能: 一件の検査の成否を保存する。
        引数: name(str)、fn(callable)は名称と検査。
        返り値: None。
        """
        try:
            fn();tests.append({"確認":name,"合格":True})
        except Exception as exc:
            tests.append({"確認":name,"合格":False,"詳細":type(exc).__name__+": "+str(exc)})

    def code_difference():
        """
        機能: 構文木上で追加が二引数と文脈の一判断だけであることを検査する。
        引数: なし。
        返り値: None。
        """
        a=ast.parse((PREV/"night5.py").read_text(encoding="utf-8"))
        b=ast.parse((WORK/"night_context129.py").read_text(encoding="utf-8"))
        fa=next(x for x in a.body if isinstance(x,ast.FunctionDef) and x.name=="simulate")
        fb=next(x for x in b.body if isinstance(x,ast.FunctionDef) and x.name=="simulate")
        assert [x.arg for x in fb.args.args[-2:]]==["context","context_mode"]
        fb.args.args=fb.args.args[:-2]
        fa.body=fa.body[1:];fb.body=fb.body[1:]
        removed=[]
        for node in ast.walk(fb):
            for field,value in ast.iter_fields(node):
                if not isinstance(value,list):continue
                kept=[]
                for child in value:
                    if isinstance(child,ast.If) and isinstance(child.test,ast.BoolOp) and any(isinstance(x,ast.Name) and x.id=="context_mode" for x in ast.walk(child.test)):
                        removed.append(child)
                    else:kept.append(child)
                setattr(node,field,kept)
        assert len(removed)==1
        assert ast.dump(fa,include_attributes=False)==ast.dump(fb,include_attributes=False)
    check("追加差分は二引数と発注前文脈判断だけ",code_difference)

    for top in (True,False):
        for reflected in (False,True):
            for steady in (True,False):
                def compatible(top=top,reflected=reflected,steady=steady):
                    """
                    機能: 文脈無効なら不明文脈でも旧全配列と一致することを検査する。
                    引数: top/reflected/steady(bool)は人工条件。
                    返り値: None。
                    """
                    args,c=fixture(reflected,top,steady);c[:]=np.nan
                    a,b=old(*args),new(*args,c,0)
                    for x,y in zip(a,b):np.testing.assert_array_equal(x,y)
                    check_night_account(args,b)
                check(f"mode0旧互換_商品{top}_上下{reflected}_平坦{steady}",compatible)

    for reflected in (False,True):
        side=-1 if reflected else 1
        for mode,column in ((1,0),(2,0),(2,3)):
            for label,value,allowed in (("正",side,True),("零",0.,True),("逆",-side,False),("未知",np.nan,False)):
                def sign(mode=mode,column=column,value=value,allowed=allowed,reflected=reflected):
                    """
                    機能: 自己又は相手一時間差の正・零・逆・不明の仕様を検査する。
                    引数: mode/column(int)、value(float)、allowed/reflected(bool)。
                    返り値: None。
                    """
                    args,c=fixture(reflected);c[1:,column]=value
                    result=new(*args,c,mode)
                    assert bool(len(result[0]))==allowed
                    if allowed:
                        assert result[0][0,1]==1 and result[0][0,0]==2
                        check_night_account(args,result)
                check(f"mode{mode}列{column}{label}_上下{reflected}",sign)

        def own_only(reflected=reflected):
            """
            機能: 自己方向限定は相手一時間の未知を追加要件にしない。
            引数: reflected(bool)は上下反転。
            返り値: None。
            """
            args,c=fixture(reflected);c[:,3]=np.nan
            assert len(new(*args,c,1)[0])==2
            assert len(new(*args,c,2)[0])==0
        check(f"自己だけと両市場を分離_上下{reflected}",own_only)

        for label,room,allowed in (("既突破",-1.,True),("境界一致",0.,True),("余地不足",3.999999,False),("保護開始幅一致",4.,True),("余地十分",5.,True),("未知",np.nan,False)):
            def room_check(label=label,room=room,allowed=allowed,reflected=reflected,side=side):
                """
                機能: 境界までの新規側気配距離と保護起動幅の厳密境界を検査する。
                引数: label(str)、room(float)、allowed/reflected(bool)、side(int)。
                返り値: None。
                """
                args,c=fixture(reflected)
                quoted=args[3][1] if side>0 else args[2][1]
                c[1:,1 if side>0 else 2]=quoted+side*room
                result=new(*args,c,3)
                assert bool(len(result[0]))==allowed
                if allowed:check_night_account(args,result)
            check(f"mode3{label}_上下{reflected}",room_check)

        for mode in (1,2,3):
            def recovery(mode=mode,reflected=reflected,side=side):
                """
                機能: 拒否時は準備を保持し文脈回復後の次行で約定することを検査する。
                引数: mode(int)、reflected(bool)、side(int)は人工条件。
                返り値: None。
                """
                args,c=fixture(reflected)
                if mode<3:c[1:3,0]=-side
                else:
                    quoted=args[3][1] if side>0 else args[2][1]
                    c[1:3,1 if side>0 else 2]=quoted+side*2.
                out=new(*args,c,mode)
                assert out[0][0,1]==3 and out[0][0,0]==4
                check_night_account(args,out)
            check(f"mode{mode}回復で後から発注_上下{reflected}",recovery)

            def after_decision(mode=mode,reflected=reflected):
                """
                機能: 判断後の文脈消失と気配悪化で待機注文を取消さないことを検査する。
                引数: mode(int)、reflected(bool)は人工条件。
                返り値: None。
                """
                args,c=fixture(reflected)
                args[4][2:4]=False;c[2:]=np.nan
                args[2][4]+=(-10 if reflected else 10);args[3][4]+=(-10 if reflected else 10)
                out=new(*args,c,mode)
                assert out[0][0,1]==1 and out[0][0,0]==4
                check_night_account(args,out)
            check(f"mode{mode}判断後未知と値飛びでも約定_上下{reflected}",after_decision)

    def future():
        """
        機能: 将来文脈を極端に変えても過去の注文と曲線が変化しないことを検査する。
        引数: なし。
        返り値: None。
        """
        args,c=fixture(False,True,False)
        for mode in (1,2,3):
            a=new(*args,c,mode);other=c.copy();other[4:,:4]=-9999.
            b=new(*args,other,mode)
            np.testing.assert_array_equal(a[0][a[0][:,0]<4],b[0][b[0][:,0]<4])
            np.testing.assert_array_equal(a[2][:4],b[2][:4])
    check("将来文脈毒化で過去不変",future)

    def runner():
        """
        機能: 実行接続の先頭十六引数を旧接続と照合し追加二引数と六条件を確認する。
        引数: なし。
        返り値: None。
        """
        trees=[ast.parse((WORK/name).read_text(encoding="utf-8")) for name in ("run_night129.py","run_context129.py")]
        calls=[next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="simulate") for tree in trees]
        assert len(calls[0].args)==16 and len(calls[1].args)==18
        for a,b in zip(calls[0].args,calls[1].args[:16]):
            assert ast.dump(a,include_attributes=False)==ast.dump(b,include_attributes=False)
        assert ast.unparse(calls[1].args[16])=="context[key]"
        assert ast.unparse(calls[1].args[17])=="config['context_mode']"
        configs=json.loads((WORK/"第二巡条件.json").read_text(encoding="utf-8-sig"))
        base=json.loads((WORK/"第一巡条件.json").read_text(encoding="utf-8-sig"))[0]
        assert [(c["price_source"],c["context_mode"]) for c in configs]==[(s,m) for s in ("last","mid") for m in (1,2,3)]
        for c in configs:
            assert c["peer_delay"]==0
            for key,value in base.items():
                if key not in ("id","name","price_source"):assert c[key]==value
    check("第二巡接続は既検査十六引数と文脈二引数のみ",runner)

    def compiled():
        """
        機能: 専用キャッシュでJITとPythonの全出力配列を比較する。
        引数: なし。
        返り値: None。
        """
        args,c=fixture(False,False,False)
        for mode in (0,1,2,3):
            for a,b in zip(new(*args,c,mode),module.simulate(*args,c,mode)):
                np.testing.assert_array_equal(a,b)
    check("専用JITとPythonの全四文脈同値",compiled)

    current={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    assert initial==current,"人工監査中に源が変わった"
    result={"passed":all(x["合格"] for x in tests),"件数":len(tests),"確認":tests,
            "数値源SHA256":current,"金融再生":0,"原市場読取":0,
            "前提":"文脈の公開時刻・鮮度はfeatures129人工25ケースで別確認。ここでは発注時の追加機構と接続だけを確認。"}
    target=HERE/f"第二巡一時間文脈と旧核互換の独立人工_{time.time_ns()}.json"
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False));print(target.relative_to(ROOT).as_posix())


if __name__=="__main__":
    main()
