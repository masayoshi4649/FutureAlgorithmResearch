"""第二巡の入口整合・退出・再参加を市場データなしで独立確認する。"""

import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
os.environ["NUMBA_CACHE_DIR"] = str(HERE/"jit_round2")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]

from check_engines128 import load, day_fixture, night_fixture, check_night_account


def setup(prices, reflected=False, entry_confirm=0., exit_mode=0., rearm=0.):
    """
    機能: 第二巡の帯外追従用人工入力を作る。
    引数: prices(list[float])、reflected(bool)、追加三条件(float)。
    返り値: listは夜間数値核への全引数。
    """
    args=list(night_fixture(prices,reflected=reflected))
    args[6][:,5]=.5
    args[-1][0]=2.
    args[-1]=np.r_[args[-1],entry_confirm,exit_mode,rearm]
    return args


def main():
    """
    機能: 第一巡との同値と第二巡の独立手計算を保存する。
    引数: なし。
    返り値: None。金融素材・保存損益の読取は行わない。
    """
    sources=[WORK/"day_core2.py",WORK/"night2.py",WORK/"adapter2.py",
             WORK/"day_core128.py",WORK/"night128.py",WORK/"bbo_order_kernel126.py"]
    fingerprints={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    oldn=load(WORK/"night128.py","r2_oldnight").simulate.py_func
    newn=load(WORK/"night2.py","r2_newnight").simulate.py_func
    oldd=load(WORK/"day_core128.py","r2_oldday").simulate.py_func
    newd=load(WORK/"day_core2.py","r2_newday").simulate.py_func
    records=[]

    def check(name,action):
        """
        機能: 一検査を失敗理由も含めて保存する。
        引数: name(str)、action(callable)。
        返り値: None。
        """
        try:
            action()
            records.append(dict(確認=name,合格=True))
        except Exception as exc:
            records.append(dict(確認=name,合格=False,内容=f"{type(exc).__name__}: {exc}"))

    paths={
        1:[98,100,100.5,103.5,106.5,104.5,104.5,104.5,104.5],
        2:[110.5,112,112.5,117.5,114.5,113.5,113.5,113.5,113.5],
        3:[108,110,107,108,108.5,114.5,111.5,110.5,110.5,110.5],
    }
    for mode in (1,2,3):
        for quantity,multiplier,fee in ((5,1000.,418),(10,10.,110)):
            for reflected in (False,True):
                def same(mode=mode,quantity=quantity,multiplier=multiplier,fee=fee,reflected=reflected):
                    """
                    機能: 追加機構無効時に全第一巡配列が一致することを確認する。
                    引数: mode/quantity(int)、multiplier/fee(float|int)、reflected(bool)。
                    返り値: None。
                    """
                    args=list(night_fixture(paths[mode],quantity,multiplier,fee,reflected))
                    args[-1][0]=mode
                    args[6][:,5]=.5
                    expected=oldn(*args)
                    args[-1]=np.r_[args[-1],0.,0.,0.]
                    actual=newn(*args)
                    for a,b in zip(expected,actual):
                        np.testing.assert_array_equal(a,b)
                    check_night_account(args,actual)
                check(f"夜追加無効の第一巡同値_mode{mode}_{quantity}_{reflected}",same)

    for reflected in (False,True):
        factor=-1. if reflected else 1.

        def entry_reject(reflected=reflected,factor=factor):
            """
            機能: 二分は逆行中という入口・出口矛盾を新規前に拒否する。
            引数: reflected(bool)、factor(float)は上下対称指定。
            返り値: None。
            """
            args=setup([110.5,112,112.5,112.5,112.5,112.5,112.5,112.5,112.5],reflected)
            args[7][:,[5,7]]=-factor
            control=newn(*args)
            assert control[0][:,0].tolist()==[2.,3.]
            assert control[1][0,12]==72.
            args[-1][10]=1.
            actual=newn(*args)
            assert len(actual[0])==0
        check(f"入口二分矛盾の拒否_{reflected}",entry_reject)

        def intermediate_reject(reflected=reflected,factor=factor):
            """
            機能: 二分支持でも二十分の逆向きは強確認で拒否する。
            引数: reflected(bool)、factor(float)は上下対称指定。
            返り値: None。
            """
            args=setup(paths[2],reflected,entry_confirm=1.,exit_mode=1.)
            args[6][:,7]=-factor
            assert len(newn(*args)[0])>0
            args[-1][10]=2.
            assert len(newn(*args)[0])==0
        check(f"入口五二十分を加えた確認_{reflected}",intermediate_reject)

        def no_short_exit(reflected=reflected,factor=factor):
            """
            機能: 短期逆行だけの退出を外したとき保有が続くことを確認する。
            引数: reflected(bool)、factor(float)。
            返り値: None。
            """
            args=setup([110.5,112,112.5,112.5,112.5,112.5,112.5,112.5,112.5],reflected)
            args[7][2:,[5,7]]=-factor
            control=newn(*args)
            args[-1][11]=1.
            actual=newn(*args)
            assert control[0][-1,0]==3. and control[1][0,12]==72.
            assert actual[0][-1,0]==8. and actual[1][0,12]==93.
            check_night_account(args,actual)
        check(f"二分だけの退出を無効_{reflected}",no_short_exit)

        def boundary(reflected=reflected,factor=factor):
            """
            機能: 固定した突破線割れと相手二十分反対の両方で退出する。
            引数: reflected(bool)、factor(float)。
            返り値: None。
            """
            args=setup([110.5,112,112.5,108.5,109.5,110.5,110.5,110.5,110.5],reflected,exit_mode=2.)
            args[-1][1]=2.
            control=newn(*args)
            assert control[0][-1,0]==8.
            args[6][3:,11]=-factor
            # 保有後に表示帯が動いても、入口で保存した境界が使われる。
            args[6][3:,3 if not reflected else 4]=130. if not reflected else 70.
            actual=newn(*args)
            assert actual[0][-1,0]==4. and actual[0][-1,1]==3.
            assert actual[1][0,12]==72.
            check_night_account(args,actual)
        check(f"固定突破線と相手二十分で退出_{reflected}",boundary)

        def rearm_wait(reflected=reflected,factor=factor):
            """
            機能: 赤字後は同方向の前建値に半幅を加えた再進行を待つ。
            引数: reflected(bool)、factor(float)。
            返り値: None。
            """
            prices=[110.5,112,112.5,108.5,109.5,110.5,112,112.5,113.5,114.5,115,115.5,118.5,117.5,117.5,117.5]
            args=setup(prices,reflected,entry_confirm=1.,exit_mode=1.)
            args[-1][5]=0.
            control=newn(*args)
            args[-1][12]=1.
            actual=newn(*args)
            assert control[0][control[0][:,7]==1,0].tolist()==[2.,7.]
            assert actual[0][actual[0][:,7]==1,0].tolist()==[2.,11.]
            check_night_account(args,actual)
            args[7][10,[5,7]]=-factor
            delayed=newn(*args)
            assert delayed[0][delayed[0][:,7]==1,0].tolist()==[2.,12.]
        check(f"損失同方向の再参加と二分支持_{reflected}",rearm_wait)

        def opposite_allowed(reflected=reflected,factor=factor):
            """
            機能: 片方向の失敗制限が反対方向を停止しないことを確認する。
            引数: reflected(bool)、factor(float)。
            返り値: None。
            """
            args=setup([110.5,112,112.5,108.5,109.5,99,98,97.5,97.5,97.5,97.5,97.5],
                       reflected,entry_confirm=1.,exit_mode=1.,rearm=1.)
            args[-1][5]=0.
            args[6][5:,10:12]=-factor
            args[7][5:,4:8]=-factor
            actual=newn(*args)
            entries=actual[0][actual[0][:,7]==1]
            assert entries[:,0].tolist()==[2.,7.]
            assert entries[:,3].tolist()==[factor,-factor]
            check_night_account(args,actual)
        check(f"失敗制限は同方向だけ_{reflected}",opposite_allowed)

        def day_same(reflected=reflected):
            """
            機能: 日中尺度床0.5と旧rule1の全配列同値を確認する。
            引数: reflected(bool)は上下対称指定。
            返り値: None。
            """
            args,extra=day_fixture([100,100,100,99.5,98.5,98,100,101,102],reflected=reflected)
            extra[0][3]=2.
            a=oldd(*args,extra[0],extra[1],1)
            nextargs=list(args)
            nextargs[-1]=np.r_[args[-1],.5,.5]
            b=newd(*nextargs,extra[0],extra[1],1)
            for x,y in zip(a,b):
                np.testing.assert_array_equal(x,y)
        check(f"日中標準尺度床の第一巡同値_{reflected}",day_same)

    def future():
        """
        機能: 二巡目の将来変更が過去注文と時価へ逆流しないことを確認する。
        引数: なし。
        返り値: None。
        """
        args=setup(paths[2],entry_confirm=2.,exit_mode=2.,rearm=1.)
        a=newn(*args)
        for index in (1,2,3):
            args[index]=args[index].copy()
            args[index][6:]+=30.
        args[6]=args[6].copy()
        args[6][6:,:]=np.nan
        b=newn(*args)
        np.testing.assert_array_equal(a[0][a[0][:,0]<6],b[0][b[0][:,0]<6])
        np.testing.assert_array_equal(a[2][:6],b[2][:6])
    check("第二巡未来改変の接頭不変",future)

    def jit():
        """
        機能: 第二巡夜間核のJITと純Pythonを専用キャッシュで比較する。
        引数: なし。
        返り値: None。
        """
        sys.path.insert(0,str(WORK))
        import night2
        args=setup([110.5,112,112.5,108.5,109.5,110.5,112,112.5,113.5,114.5,115,115.5,118.5,117.5,117.5,117.5],
                   entry_confirm=1.,exit_mode=1.,rearm=1.)
        args[-1][5]=0.
        a=night2.simulate(*args)
        b=newn(*args)
        for x,y in zip(a,b):
            np.testing.assert_array_equal(x,y)
    check("第二巡夜間JIT同値",jit)

    for p in sources:
        assert fingerprints[p.name]==hashlib.sha256(p.read_bytes()).hexdigest()
    result=dict(全合格=all(r["合格"] for r in records),確認数=len(records),確認=records,
                数値源SHA256=fingerprints,新金融=0,市場素材読取=0)
    target=HERE/"第二巡の夜間機構と互換及びJITの独立人工.json"
    assert not target.exists()
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
