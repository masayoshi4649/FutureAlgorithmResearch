"""第四巡の発注時中期再確認を、未変更の数値核で独立に検査する。"""

import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
os.environ["NUMBA_CACHE_DIR"]=str(HERE/"jit_confirm2")
import numba
numba.config.CACHE_DIR=os.environ["NUMBA_CACHE_DIR"]
from check_engines128 import load, night_fixture, check_night_account


def fixture(reflected=False):
    """
    機能: 突破準備と発注時支持を個別に変更できる人工入力を作る。
    引数: reflected(bool)は売買の上下対称指定。
    返り値: listは第三巡数値核に渡す人工引数。
    """
    prices=[110.5,112,112.5,112.5,112.5,112.5,112.5,112.5,112.5]
    args=list(night_fixture(prices,reflected=reflected))
    args[6][:,5]=.5
    args[-1][0]=2.
    args[-1]=np.r_[args[-1],2.,2.,0.,1.e9]
    return args


def main():
    """
    機能: 四支持列の失効・回復・発注後の変化と過去試行との相違を保存する。
    引数: なし。
    返り値: None。新金融や実市場読取は行わない。
    """
    source=WORK/"night3.py"
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    runner=load(source,"confirm2_independent").simulate.py_func
    checks=[]

    def check(name,action):
        """
        機能: 人工検査一件を結果とともに記録する。
        引数: name(str)、action(callable)。
        返り値: None。
        """
        try:
            action()
            checks.append(dict(確認=name,合格=True))
        except Exception as exc:
            checks.append(dict(確認=name,合格=False,内容=f"{type(exc).__name__}: {exc}"))

    for reflected in (False,True):
        factor=-1. if reflected else 1.
        for column in (6,7,10,11):
            for invalid_name,invalid_value in (("逆向き",-factor),("ゼロ",0.),("未知",np.nan)):
                def rejected(reflected=reflected,factor=factor,column=column,invalid_value=invalid_value):
                    """
                    機能: 準備後に個別支持が失効したら発注しないことを確認する。
                    引数: reflected(bool)、factor(float)、column(int)、invalid_value(float)。
                    返り値: None。
                    """
                    args=fixture(reflected)
                    args[6][1:,column]=invalid_value
                    actual=runner(*args)
                    assert len(actual[0])==0
                    args[-1][10]=1.
                    control=runner(*args)
                    if np.isfinite(invalid_value):
                        assert control[0][0,0]==2. and control[0][0,1]==1.
                    else:
                        # 入口資料が未知のときは旧確認1も止まる。新効果として数えない。
                        assert len(control[0])==0
                check(f"準備後の列{column}_{invalid_name}_反射{reflected}",rejected)

            def renewed(reflected=reflected,factor=factor,column=column):
                """
                機能: 待機中の支持回復を観測した後の次行で新規になることを確認する。
                引数: reflected(bool)、factor(float)、column(int)。
                返り値: None。
                """
                args=fixture(reflected)
                args[6][1:3,column]=-factor
                actual=runner(*args)
                assert actual[0][0,1]==3. and actual[0][0,0]==4.
                check_night_account(args,actual)
            check(f"列{column}の支持回復後に発注_反射{reflected}",renewed)

            def after_decision(reflected=reflected,factor=factor,column=column):
                """
                機能: 発注後に支持が消えても先に成立した注文を遡及取消しない。
                引数: reflected(bool)、factor(float)、column(int)。
                返り値: None。
                """
                args=fixture(reflected)
                args[6][2:,column]=np.nan
                actual=runner(*args)
                assert actual[0][0,1]==1. and actual[0][0,0]==2.
                check_night_account(args,actual)
            check(f"発注後の列{column}欠落は約定取消ししない_反射{reflected}",after_decision)

        def delayed_quote(reflected=reflected):
            """
            機能: 正常気配待ちの途中で支持が消えても最初の正常原行で約定する。
            引数: reflected(bool)は上下対称指定。
            返り値: None。
            """
            args=fixture(reflected)
            args[4][2:4]=False
            args[6][2:,:]=np.nan
            actual=runner(*args)
            assert actual[0][0,1]==1. and actual[0][0,0]==4.
            check_night_account(args,actual)
        check(f"気配待ち中の支持失効で取消さない_反射{reflected}",delayed_quote)

    def candidate_duplicates():
        """
        機能: 第一～三巡の全夜条件に第四巡候補と完全一致がないことを確認する。
        引数: なし。
        返り値: None。過去全研究の未整理条件まで確認したとは扱わない。
        """
        existing=[]
        for name in ("round1","round2","round3"):
            fixed=json.loads((WORK/name/"固定計画.json").read_text(encoding="utf-8"))
            existing += [c for c in fixed["configs"] if c["kind"]=="Night"]
        names=("mode","stop","trail_start","trail_width","phase","cooldown","entry_bounce",
               "opening_buffer","minimum_efficiency","band_distance","entry_confirm","exit_mode",
               "rearm","maximum_extension")

        def signature(config):
            """
            機能: 説明とIDを除いた夜条件の数値署名を作る。
            引数: config(dict)は固定条件。
            返り値: tupleは数値条件。
            """
            defaults=dict(entry_confirm=0,exit_mode=0,rearm=0,maximum_extension=1.e9)
            return tuple(config.get(n,defaults.get(n)) for n in names)

        signatures={signature(c) for c in existing}
        comparisons=[]
        for base_id,new_id in (("N16","N31"),("N23","N32"),("N24","N33")):
            base=next(c for c in existing if c["id"]==base_id)
            proposal=dict(base,entry_confirm=2,maximum_extension=1.e9)
            assert signature(proposal) not in signatures
            changed=[n for n in names if signature(base)[names.index(n)]!=signature(proposal)[names.index(n)]]
            assert changed==["entry_confirm"]
            comparisons.append(dict(候補=new_id,対照=base_id,変更=changed,完全一致なし=True))
        duplicate_result.update(比較範囲="00128第一～三巡の夜30条件。過去全研究の完全照合ではない。",
                                候補=comparisons,既存条件=len(existing))
    duplicate_result={}
    check("第一～三巡夜三十条件との単因子差分確認",candidate_duplicates)

    def future():
        """
        機能: 未来側だけの支持変更が既知注文・時価へ混入しないことを確認する。
        引数: なし。
        返り値: None。
        """
        args=fixture()
        a=runner(*args)
        args[6][5:,[6,7,10,11]]=-1000.
        args[7][5:,4:8]=-1000.
        b=runner(*args)
        np.testing.assert_array_equal(a[0][a[0][:,0]<5],b[0][b[0][:,0]<5])
        np.testing.assert_array_equal(a[2][:5],b[2][:5])
    check("確認2の未来支持変更の接頭不変",future)

    def jit():
        """
        機能: 確認2と支持回復経路をJITと純Pythonで照合する。
        引数: なし。
        返り値: None。
        """
        sys.path.insert(0,str(WORK))
        import night3
        args=fixture()
        args[6][1:3,10]=-1.
        a=night3.simulate(*args)
        b=runner(*args)
        for x,y in zip(a,b):
            np.testing.assert_array_equal(x,y)
    check("確認2の支持回復JIT同値",jit)

    assert source_hash==hashlib.sha256(source.read_bytes()).hexdigest()
    result=dict(全合格=all(v["合格"] for v in checks),確認数=len(checks),確認=checks,
                数値源SHA256={"night3.py":source_hash},候補差分=duplicate_result,
                新金融=0,市場素材読取=0)
    target=HERE/"第四巡の発注時支持再確認と既存差分の独立人工.json"
    assert not target.exists()
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
