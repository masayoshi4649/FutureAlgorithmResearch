"""第五巡の相手だけの再確認を、既存分岐との対照付きで独立検査する。"""

import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
os.environ["NUMBA_CACHE_DIR"]=str(HERE/"jit_peerconfirm5")
import numba
numba.config.CACHE_DIR=os.environ["NUMBA_CACHE_DIR"]
from check_engines128 import load, night_fixture, check_night_account


def fixture(reflected=False, confirmation=3.):
    """
    機能: 発注時の支持を差し替えるための人工入力を作る。
    引数: reflected(bool)、confirmation(float)は売買対称と確認条件。
    返り値: listは夜間核の全引数。
    """
    args=list(night_fixture([110.5,112,112.5,112.5,112.5,112.5,112.5,112.5,112.5],reflected=reflected))
    args[6][:,5]=.5
    args[-1][0]=2.
    args[-1]=np.r_[args[-1],confirmation,2.,0.,1.e9]
    return args


def main():
    """
    機能: 第五巡の追加分岐と旧分岐の同値を純人工で確認し保存する。
    引数: なし。
    返り値: None。市場素材と保存金融成績は読み込まない。
    """
    sources=[WORK/"night5.py",WORK/"night3.py",WORK/"adapter5.py"]
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    old=load(WORK/"night3.py","peer5_old").simulate.py_func
    new=load(WORK/"night5.py","peer5_new").simulate.py_func
    checks=[]

    def check(name,action):
        """
        機能: 一人工確認を例外も含めて保存する。
        引数: name(str)、action(callable)。
        返り値: None。
        """
        try:
            action()
            checks.append(dict(確認=name,合格=True))
        except Exception as exc:
            checks.append(dict(確認=name,合格=False,内容=f"{type(exc).__name__}: {exc}"))

    def only_branch():
        """
        機能: 新数値源の差分が確認3の相手支持分岐だけであることを確認する。
        引数: なし。
        返り値: None。
        """
        a=(WORK/"night5.py").read_text(encoding="utf-8")
        b=(WORK/"night3.py").read_text(encoding="utf-8")
        extra="                        elif entry_confirm == 3.:\n                            trigger = trigger and arm*history[i,10] > 0. and arm*history[i,11] > 0.\n"
        assert a.count(extra)==1
        assert a.replace(extra,"")==b
    check("数値源差分は確認3の一分岐のみ",only_branch)

    for reflected in (False,True):
        factor=-1. if reflected else 1.
        for confirm in (0.,1.,2.):
            for column in (None,7,11):
                def compatible(reflected=reflected,factor=factor,confirm=confirm,column=column):
                    """
                    機能: 旧確認0/1/2の全配列が新旧で同値なことを確認する。
                    引数: reflected(bool)、factor/confirm(float)、column(int|None)。
                    返り値: None。
                    """
                    args=fixture(reflected,confirm)
                    if column is not None:
                        args[6][1:,column]=-factor
                    a,b=old(*args),new(*args)
                    for x,y in zip(a,b):
                        np.testing.assert_array_equal(x,y)
                    check_night_account(args,b)
                check(f"確認{confirm}互換_列{column}_反射{reflected}",compatible)

        for column in (10,11):
            for label,value in (("逆", -factor),("零",0.),("未知",np.nan)):
                def peer_fail(reflected=reflected,column=column,value=value):
                    """
                    機能: 準備後に相手の必要支持が失効すれば建てないことを確認する。
                    引数: reflected(bool)、column(int)、value(float)。
                    返り値: None。
                    """
                    args=fixture(reflected)
                    args[6][1:,column]=value
                    assert len(new(*args)[0])==0
                check(f"相手列{column}{label}は拒否_反射{reflected}",peer_fail)

            def recovery(reflected=reflected,factor=factor,column=column):
                """
                機能: 相手支持の回復を観測した次原行で建てることを確認する。
                引数: reflected(bool)、factor(float)、column(int)。
                返り値: None。
                """
                args=fixture(reflected)
                args[6][1:3,column]=-factor
                result=new(*args)
                assert result[0][0,1]==3. and result[0][0,0]==4.
                check_night_account(args,result)
            check(f"相手列{column}の回復_反射{reflected}",recovery)

            def no_cancel(reflected=reflected,column=column):
                """
                機能: 発注後の相手支持欠落で先行注文を取消さないことを確認する。
                引数: reflected(bool)、column(int)。
                返り値: None。
                """
                args=fixture(reflected)
                args[4][2:4]=False
                args[6][2:,column]=np.nan
                result=new(*args)
                assert result[0][0,1]==1. and result[0][0,0]==4.
                check_night_account(args,result)
            check(f"発注後相手列{column}欠落で取消さない_反射{reflected}",no_cancel)

        for column in (6,7):
            for label,value in (("逆",-factor),("零",0.)):
                def own_weak(reflected=reflected,column=column,value=value):
                    """
                    機能: 自己の五・二十分が逆か零でも相手だけ確認3は発注する。
                    引数: reflected(bool)、column(int)、value(float)。
                    返り値: None。
                    """
                    args=fixture(reflected)
                    args[6][1:,column]=value
                    result=new(*args)
                    assert result[0][0,1]==1. and result[0][0,0]==2.
                    args[-1][10]=2.
                    assert len(new(*args)[0])==0
                check(f"自己列{column}{label}は確認3で許可_反射{reflected}",own_weak)

        def own_unknown(reflected=reflected):
            """
            機能: 自己方向が未取得の場合は入口資料の資格がないことを確認する。
            引数: reflected(bool)。
            返り値: None。
            """
            args=fixture(reflected)
            args[6][1:,7]=np.nan
            assert len(new(*args)[0])==0
        check(f"自己未知は支持不足と混同せず停止_反射{reflected}",own_unknown)

        def short_required(reflected=reflected,factor=factor):
            """
            機能: 確認3でも両市場二分支持が必要なことを確認する。
            引数: reflected(bool)、factor(float)。
            返り値: None。
            """
            args=fixture(reflected)
            args[7][1:,5]=-factor
            assert len(new(*args)[0])==0
        check(f"確認3でも二分支持は必要_反射{reflected}",short_required)

    def mirror():
        """
        機能: 新確認3の上下反転で損益・注文時計が一致することを確認する。
        引数: なし。
        返り値: None。
        """
        a=new(*fixture(False))
        b=new(*fixture(True))
        np.testing.assert_array_equal(a[0][:,[0,1,2,4,6,7]],b[0][:,[0,1,2,4,6,7]])
        np.testing.assert_array_equal(a[0][:,3],-b[0][:,3])
        np.testing.assert_array_equal(a[1][:,6:],b[1][:,6:])
    check("確認3の上下鏡像",mirror)

    def future():
        """
        機能: 将来支持の変更が既知注文・時価を変えないことを確認する。
        引数: なし。
        返り値: None。
        """
        args=fixture()
        a=new(*args)
        args[6][5:,[6,7,10,11]]=-1000.
        b=new(*args)
        np.testing.assert_array_equal(a[0][a[0][:,0]<5],b[0][b[0][:,0]<5])
        np.testing.assert_array_equal(a[2][:5],b[2][:5])
    check("確認3の未来支持変更で接頭不変",future)

    def jit():
        """
        機能: 確認3の相手回復と自己逆向きが共存する経路をJIT照合する。
        引数: なし。
        返り値: None。
        """
        sys.path.insert(0,str(WORK))
        import night5
        args=fixture()
        args[6][1:,7]=-1.
        args[6][1:3,10]=-1.
        a,b=night5.simulate(*args),new(*args)
        assert a[0][0,0]==4.
        for x,y in zip(a,b):
            np.testing.assert_array_equal(x,y)
    check("確認3のJIT同値",jit)

    for p in sources:
        assert hashes[p.name]==hashlib.sha256(p.read_bytes()).hexdigest()
    result=dict(全合格=all(c["合格"] for c in checks),確認数=len(checks),確認=checks,
                数値源SHA256=hashes,新金融=0,市場素材読取=0)
    output=HERE/"第五巡の相手だけ再確認と既存互換の独立人工.json"
    assert not output.exists()
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
