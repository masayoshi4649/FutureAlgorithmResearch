"""中期の価格位置を保有仮説とし、短期符号の往復だけで入れ替えない判断層。"""

import numpy as np
from numba import njit
from patrol_selector142 import activity


REASONS={10:'中期又は活動資料が欠測',11:'活動レンジ不足',12:'二市場の中期支持位置が不一致',
         20:'中期合議と価格位置で参加',21:'支持状態の押しを待つ',22:'押し後の再進行とMA5回復を確認',
         23:'前の同方向失敗後は新しい押しを待つ',30:'中期支持状態を維持',
         31:'二市場のMA20支持を喪失し短平均も逆行',36:'二市場の活動レンジ不足',37:'中期管理資料が欠測'}


@njit(cache=True)
def medium_known(a):
    """
    機能: 公開平均・当時中値・Rが利用可能かを確認する。
    引数: a(ndarray[48])は当時特徴。
    返り値: bool。平均線は約定原価ではなく公開済み中値終値の平均である。
    """
    for c in (9,10,18,19,28,29,36,37,42,43):
        if not np.isfinite(a[c]):return False
    return a[9]>0. and a[18]>0.


@njit(cache=True)
def supported_side(a):
    """
    機能: 二市場20分差・MA5位置・現在価格のMA20上下一致を確認する。
    引数: a(ndarray[48])は当時公開済み特徴。
    返り値: intは買い1・売り-1・未成立0。新規にはMA20から方向側0.1Rの余裕を要求する。
    """
    if not medium_known(a):return 0
    for side in (1,-1):
        if (side*a[28]>0. and side*a[29]>0. and side*(a[36]-a[37])>0.
                and side*(a[42]-a[43])>0. and side*(a[10]-a[37])>=.1*a[9]
                and side*(a[19]-a[43])>=.1*a[18]):return side
    return 0


@njit(cache=True)
def entry_step(a,policy,locked_side,setup_side,stage,peak,trough,arm_risk):
    """
    機能: 状態参加・全入口の押し待ち・失敗後だけの再進行確認を選ぶ。
    引数: a(ndarray[48])、policy/locked_side/setup_side/stage(int)、peak/trough/arm_risk(float)は当時資料と明示状態。
    返り値: tupleは候補方向・入口状態・理由・確認秒・次setup方向・段階・極値・押し極値・固定準備R。

    極値は準備開始後の観測だけで逐次更新する。将来の転換点・確定後の波ラベルは入力しない。
    locked_sideは候補内の完結仮想会計が赤字だった直前親方向。現在玉の将来収支を使わない。
    """
    assert len(a)>=48 and 1<=policy<=3
    clear=(0,0,0.,0.,0.)
    if not medium_known(a):return (0,0,10,5.)+clear
    known,own,peer=activity(a)
    if not known:return (0,0,10,5.)+clear
    if not own or not peer:return (0,0,11,5.)+clear
    direction=supported_side(a)
    if not direction:return (0,0,12,5.)+clear
    must_wait=policy==2 or (policy==3 and locked_side==direction)
    if not must_wait:return (direction,1,20,5.)+clear
    mid=a[10]
    if setup_side!=direction:
        setup_side,stage,peak,trough,arm_risk=direction,0,mid,mid,a[9]
    if stage==0:
        peak=max(peak,mid) if direction>0 else min(peak,mid)
        if direction*(peak-mid)>=.25*arm_risk:
            stage,trough=1,mid
    else:
        trough=min(trough,mid) if direction>0 else max(trough,mid)
        recovered=(direction*(mid-trough)>=.125*arm_risk and direction*(mid-a[36])>=0.
                   and direction*(a[19]-a[42])>=0.)
        if recovered:return direction,2,22,5.,setup_side,stage,peak,trough,arm_risk
    return 0,2,23 if policy==3 else 21,5.,setup_side,stage,peak,trough,arm_risk


@njit(cache=True)
def management(a,side,policy,entry_regime):
    """
    機能: 短期120秒の符号を退出根拠にせず、二市場の支持価格位置の喪失を確認する。
    引数: a(ndarray[48])、side/policy/entry_regime(int)は当時特徴と保有状態。
    返り値: tuple[int,int]は0維持/1返済候補/3無動意候補と理由。固定停止と追尾は売買層が優先する。

    出口は両市場がMA20の反対側0.1Rへ出て、少なくとも一市場のMA5もMA20を割った場合。
    新規の方向側0.1Rと別に反対側0.1Rを使い、同じ境界で小刻みに往復しない。
    """
    if not medium_known(a):return 0,37
    known,own,peer=activity(a)
    if known and not own and not peer:return 3,36
    lost=(side*(a[10]-a[37])<=-.1*a[9] and side*(a[19]-a[43])<=-.1*a[18])
    short_average_lost=side*(a[36]-a[37])<0. or side*(a[42]-a[43])<0.
    return (1,31) if lost and short_average_lost else (0,30)


@njit(cache=True)
def initial_quantity(policy,regime):
    """
    機能: P04と同じ初回2枚を保ち、入替回数の変更を数量変更と分離する。
    引数: policy/regime(int)は政策と入口状態。
    返り値: intは2枚。
    """
    return 2


@njit(cache=True)
def allow_add(a,side,policy,stop_floor):
    """
    機能: この対照では追撃を行わず、同じ初回2枚の入口・継続差だけを比較する。
    引数: a(ndarray[48])、side/policy(int)、stop_floor(float)は同一売買層の入力。
    返り値: boolは常にFalse。
    """
    return False
