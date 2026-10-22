"""第三巡の追い過ぎ制限を純人工で独立検査する。"""

import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
os.environ["NUMBA_CACHE_DIR"]=str(HERE/"jit_round3")
import numba
numba.config.CACHE_DIR=os.environ["NUMBA_CACHE_DIR"]
from check_engines128 import load, night_fixture, check_night_account


def fixture(prices, reflected=False, cap=np.inf):
    """
    機能: 帯外追従の人工入力へ判断行距離上限を加える。
    引数: prices(list[float])、reflected(bool)、cap(float)は距離上限倍率。
    返り値: listは第三巡夜間核の全引数。
    """
    args=list(night_fixture(prices,reflected=reflected))
    args[6][:,5]=.5
    args[-1][0]=2.
    args[-1]=np.r_[args[-1],1.,2.,0.,cap]
    return args


def main():
    """
    機能: 旧核との同値、閾値境界、因果性、専用JIT同値を検査して保存する。
    引数: なし。
    返り値: None。金融素材と保存成績を読み込まない。
    """
    sources=[WORK/"night3.py",WORK/"night2.py",WORK/"adapter3.py"]
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    old=load(WORK/"night2.py","r3_oldnight").simulate.py_func
    new=load(WORK/"night3.py","r3_newnight").simulate.py_func
    results=[]

    def check(name,action):
        """
        機能: 一つの検査を例外も含めて記録する。
        引数: name(str)、action(callable)。
        返り値: None。
        """
        try:
            action()
            results.append(dict(確認=name,合格=True))
        except Exception as exc:
            results.append(dict(確認=name,合格=False,内容=f"{type(exc).__name__}: {exc}"))

    for reflected in (False,True):
        for quantity,multiplier,fee in ((5,1000.,418),(10,10.,110)):
            for cap in (np.inf,1.e9):
                def same(reflected=reflected,quantity=quantity,multiplier=multiplier,fee=fee,cap=cap):
                    """
                    機能: 距離上限無効で第二巡の全配列が一致することを確認する。
                    引数: reflected(bool)、数量/倍率/料率(int|float)、cap(float)。
                    返り値: None。
                    """
                    args=fixture([110.5,112,112.5,117.5,114.5,113.5,113.5,113.5,113.5],reflected,cap)
                    args[12:15]=quantity,multiplier,fee
                    a=new(*args)
                    before=list(args)
                    before[-1]=before[-1][:-1]
                    b=old(*before)
                    for x,y in zip(a,b):
                        np.testing.assert_array_equal(x,y)
                    check_night_account(args,a)
                check(f"距離無効の第二巡同値_{reflected}_{quantity}_{cap}",same)

        def boundary(reflected=reflected):
            """
            機能: 判断行の気配距離が閾値と一致すれば許可し僅かに超えれば拒否する。
            引数: reflected(bool)は上下対称の指定。
            返り値: None。
            """
            args=fixture([110.5,112,112.5,112.5,112.5,112.5,112.5,112.5,112.5],reflected,.625)
            # 元境界110、判断ask112.5、初期幅4なので距離倍率は厳密に0.625。
            accepted=new(*args)
            assert accepted[0][0,0]==2. and accepted[0][0,1]==1.
            args[-1][-1]=np.nextafter(.625,-np.inf)
            refused=new(*args)
            assert len(refused[0])==0
        check(f"距離上限の厳密境界_{reflected}",boundary)

        def fill_jump(reflected=reflected):
            """
            機能: 既に判断した後の約定気配の飛びを理由に遡及取消しないことを確認する。
            引数: reflected(bool)は上下対称の指定。
            返り値: None。
            """
            args=fixture([110.5,112,112.5,112.5,112.5,112.5,112.5,112.5,112.5],reflected,.625)
            if reflected:
                args[2][2]=70.
            else:
                args[3][2]=130.
            actual=new(*args)
            assert actual[0][0,0]==2. and actual[0][0,1]==1.
            assert actual[0][0,5]==(70. if reflected else 130.)
            check_night_account(args,actual)
        check(f"距離外へ飛んだ実約定を保持_{reflected}",fill_jump)

        def fixed_boundary(reflected=reflected):
            """
            機能: 待機後の新しい帯で距離条件を緩めず最初の突破線を使うことを確認する。
            引数: reflected(bool)は上下対称の指定。
            返り値: None。
            """
            args=fixture([110.5,112,112.5,112.5,112.5,112.5,112.5,112.5,112.5],reflected,.5)
            # 更新された表示帯を使えば距離が小さく見えるが、元境界では見送り。
            args[6][1:,4 if reflected else 3]=88. if reflected else 112.
            assert len(new(*args)[0])==0
        check(f"待機後も元の突破線を固定_{reflected}",fixed_boundary)

    def future():
        """
        機能: 将来価格と将来資料を変えても過去注文と時価が変わらないことを確認する。
        引数: なし。
        返り値: None。
        """
        args=fixture([110.5,112,112.5,117.5,114.5,113.5,113.5,113.5,113.5],cap=.625)
        a=new(*args)
        for field in (1,2,3):
            args[field]=args[field].copy()
            args[field][6:]+=30.
        args[6]=args[6].copy()
        args[6][6:,:]=np.nan
        b=new(*args)
        np.testing.assert_array_equal(a[0][a[0][:,0]<6],b[0][b[0][:,0]<6])
        np.testing.assert_array_equal(a[2][:6],b[2][:6])
    check("第三巡未来改変の接頭不変",future)

    def jit():
        """
        機能: 第三巡JITと純Pythonを専用キャッシュで比較する。
        引数: なし。
        返り値: None。
        """
        sys.path.insert(0,str(WORK))
        import night3
        args=fixture([110.5,112,112.5,117.5,114.5,113.5,113.5,113.5,113.5],cap=.625)
        a=night3.simulate(*args)
        b=new(*args)
        for x,y in zip(a,b):
            np.testing.assert_array_equal(x,y)
    check("第三巡JIT同値",jit)

    for p in sources:
        assert hashes[p.name]==hashlib.sha256(p.read_bytes()).hexdigest()
    result=dict(全合格=all(r["合格"] for r in results),確認数=len(results),確認=results,
                数値源SHA256=hashes,新金融=0,市場素材読取=0)
    path=HERE/"第三巡の距離上限と因果及びJITの独立人工.json"
    assert not path.exists()
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
