"""固定突破線の再試験を、作成者の純人工で確認する。"""

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
os.environ["NUMBA_CACHE_DIR"]=str(HERE/"retest_jit")
sys.dont_write_bytecode=True
sys.path[:0]=[str(TASK),str(OLD),str(OLD/"audit")]
import numba
numba.config.CACHE_DIR=os.environ["NUMBA_CACHE_DIR"]
import night5
import night_retest129
from check_engines128 import check_night_account

CHECKS=[]


def same(name: str, actual: object, expected: object) -> None:
    """
    機能: 人工の期待値に一致することを記録する。
    引数: name(str)、actual/expected(object)は名称と比較値。
    返り値: None。不一致は停止する。
    """
    np.testing.assert_array_equal(actual,expected,err_msg=name)
    CHECKS.append(name)


def fixture(quantity: int=5, reflected: bool=False, confirm: float=3.) -> list:
    """
    機能: 固定線100から進行・戻り・再進行する独立人工を作る。
    引数: quantity(int)、reflected(bool)、confirm(float)は数量・上下・確認種別。
    返り値: listは夜間核の旧十六引数。
    """
    price=np.array([101.,103.,102.,101.,100.5,101.5,102.,102.5,102.,102.,102.,102.])
    n=len(price);times=np.arange(n,dtype=float)*30.
    bid,ask=price-.25,price+.25
    history=np.ones((n,15))
    history[:,0:2]=95.
    history[:,2]=2.;history[:,3]=100.;history[:,4]=90.;history[:,5]=.6
    history[:,8]=95.;history[:,9]=times-60.;history[:,14]=times-120.
    market=np.ones((n,12))
    market[:,0]=price;market[:,1]=200.;market[:,2:4]=4.;market[:,4:8]=.2
    market[:,8]=times-1.;market[:,9]=times-31.;market[:,10]=times-32.
    if reflected:
        price=220.-price;bid,ask=220.-ask,220.-bid
        history[:,[0,1,8]]=220.-history[:,[0,1,8]]
        high=history[:,3].copy();history[:,3]=220.-history[:,4];history[:,4]=220.-high
        history[:,[6,7,10,11,13]]*=-1.
        market[:,0]=price;market[:,1]=220.-market[:,1];market[:,4:8]*=-1.
    parameters=np.array([2.,1.,1.,.75,1.,300.,.25,900.,.35,.25,confirm,2.,0.,1.e9])
    return [times,price,bid,ask,np.ones(n,bool),np.full(n,4.),history,market,
            0.,times[-2],-3600.,.5,quantity,1000. if quantity==5 else 10.,
            418 if quantity==5 else 110,parameters]


def alter_price(args: list, prices: list[float]) -> None:
    """
    機能: 人工の判断価格と気配だけを整合的に変更する。
    引数: args(list)、prices(list[float])は人工と新価格列。
    返り値: None。元データは扱わない。
    """
    args[1]=np.asarray(prices,float)
    args[2],args[3]=args[1]-.25,args[1]+.25
    args[7][:,0]=args[1]


def run(args: list, mode: int=1, compiled: bool=False) -> tuple:
    """
    機能: 人工核の出力を独立の注文会計で確認する。
    引数: args(list)、mode(int)、compiled(bool)は人工・入口・ＪＩＴ指定。
    返り値: tupleは保存形式の三配列。
    """
    fn=night_retest129.simulate if compiled else night_retest129.simulate.py_func
    result=fn(*args,retest_mode=mode)
    check_night_account(tuple(args),result)
    CHECKS.append("人工の独立注文会計")
    return result


def main() -> None:
    """
    機能: 旧互換・段階順序・境界・時点・上下・確認3/4・固定出口を確認する。
    引数: なし。
    返り値: None。作成者証跡のみ保存し、独立監査は別担当へ依頼する。
    """
    paths=[TASK/"night_retest129.py",OLD/"night5.py",Path(__file__),OLD/"audit/check_engines128.py"]
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for quantity in (5,10):
        for reflected in (False,True):
            for confirm in (0.,1.,2.,3.):
                for mode in (1.,2.,3.,4.,5.,6.):
                    args=fixture(quantity,reflected,confirm);args[-1][0]=mode
                    old=night5.simulate.py_func(*args);new=run(args,0)
                    for j,(actual,expected) in enumerate(zip(new,old)):
                        same(f"旧全配列互換_{quantity}_{reflected}_{confirm}_{mode}_{j}",actual,expected)
            for confirm in (3.,4.):
                args=fixture(quantity,reflected,confirm)
                actual=run(args)
                same(f"進行戻り再進行の判断と次行_{quantity}_{reflected}_{confirm}",
                     actual[0][0,:2],[6.,5.])
                compiled=run(args,1,True)
                for j in range(3):
                    same(f"JIT一致_{quantity}_{reflected}_{confirm}_{j}",compiled[j],actual[j])
                stale=deepcopy(args)
                stale[4][6:8]=False;stale[6][6:,:]=np.nan
                altered=run(stale)
                same(f"成立後未知でも予約を取消さない_{quantity}_{reflected}_{confirm}",altered[0][0,:2],[8.,5.])
                # 準備開始後に履歴帯が移っても、既に固定した線は差し替えない。
                shifted=deepcopy(args)
                shifted[6][1:,3]+=30.;shifted[6][1:,4]-=30.
                moved=run(shifted)
                for j in range(3):
                    same(f"固定線を事後帯へ更新しない_{quantity}_{reflected}_{confirm}_{j}",moved[j],actual[j])
                future=deepcopy(args)
                future[1][7:]+=50.;future[2][7:]+=50.;future[3][7:]+=50.
                future[6][7:,:]=-1.;future[7][7:,:]=np.nan
                poisoned=run(future)
                same(f"未来毒化接頭曲線_{quantity}_{reflected}_{confirm}",poisoned[2][:7],actual[2][:7])
                same(f"未来毒化接頭注文_{quantity}_{reflected}_{confirm}",
                     poisoned[0][poisoned[0][:,0]<7],actual[0][actual[0][:,0]<7])
                # 120秒だけは確認4で使用しない。30秒支持と相手中期支持は必要。
                for value in (-1.,0.,np.nan):
                    changed=deepcopy(args);changed[7][:,5]=value;changed[7][:,7]=value
                    if reflected and np.isfinite(value):
                        changed[7][:,5:8:2]*=-1.
                    result=run(changed)
                    same(f"二分不足の確認差_{quantity}_{reflected}_{confirm}_{value}",
                         len(result[0]),2 if confirm==4. else 0)
                for target,column in ((7,4),(7,6),(6,10),(6,11)):
                    for value in (0.,np.nan):
                        changed=deepcopy(args);changed[target][:,column]=value
                        same(f"必要支持拒否_{quantity}_{reflected}_{confirm}_{target}_{column}_{value}",len(run(changed)[0]),0)
            a=run(fixture(quantity,False));b=run(fixture(quantity,True))
            same(f"上下注文時計数量_{quantity}",a[0][:,[0,1,2,4,6,7]],b[0][:,[0,1,2,4,6,7]])
            same(f"上下方向_{quantity}",a[0][:,3],-b[0][:,3])
            same(f"上下損益費用_{quantity}",a[1][:,6:],b[1][:,6:])
    # ----------------------------------------
    # 各段階の必要性と境界ちょうど、初回から0.75Rの場合を別経路で確認。
    for label,prices in (
        ("進行不足",[101,102,102,101,100.5,101.5,102,102.5,102,102,102,102]),
        ("戻り不足",[101,103,102,102,102,103,103,103,103,103,103,103]),
        ("再進行不足",[101,103,102,101,100.5,101,101,101,101,101,101,101]),
        ("取消境界ちょうど",[101,103,102,101,99,101.5,102,102.5,102,102,102,102])):
        args=fixture();alter_price(args,prices)
        same(label,len(run(args)[0]),0)
    args=fixture()
    alter_price(args,[103,101,102,102,102,102,102,102,102,102,102,102])
    same("準備原行の0.75Rを観測",run(args)[0][0,:2],[3.,2.])
    args=fixture();args[0][3:]+=1900.;args[9]=args[0][-2]
    same("三十分失効で段階を引き継がない",len(run(args)[0]),0)
    for absent in ("相手現在未知","履歴未知","現在ATR未知"):
        args=fixture()
        alter_price(args,[101,103,102,101,99,101.5,102,102.5,102,102,102,102])
        if absent=="相手現在未知":
            args[7][4,11]=0.
        elif absent=="履歴未知":
            args[6][4,10]=np.nan
        else:
            args[5][4]=np.nan
        same(absent+"でも観測した境界破綻を取消す",len(run(args)[0]),0)
    args=fixture()
    args[1][6]=99.;args[2][6]=98.75;args[3][6]=99.25
    args[6][6,:]=np.nan;args[7][6,11]=0.
    same("発注済は後続境界破綻で取消さない",run(args)[0][0,:2],[6.,5.])
    # 発注と次行約定は同じ価格時計でも原行順を保つ。
    args=fixture();args[0][6]=args[0][5]
    same("同時計でも後続原行で約定",run(args)[0][0,:2],[6.,5.])
    old=(OLD/"night5.py").read_text(encoding="utf8")
    new=(TASK/"night_retest129.py").read_text(encoding="utf8")
    begin="        if pending and good and i > pending_source:"
    end="        # ----------------------------------------\n        # 入り直しの条件"
    assert old[old.index(begin):old.index(end)]==new[new.index(begin):new.index(end)]
    CHECKS.append("新規約定と保有出口の元源完全同文")
    assert hashes=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    result=dict(passed=True,checks=CHECKS,source_hashes=hashes,financial_replays=0,
                original_market_reads=0,API=0,note="作成者の純人工。独立監査・実市場優位性とは別。")
    target=HERE/f"夜間再試験入口の作成者人工_{time.time_ns()}.json"
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(passed=True,checks=len(CHECKS),path=str(target)),ensure_ascii=False))


if __name__=="__main__":
    main()
