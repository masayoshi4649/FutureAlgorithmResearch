"""カバー保持・飽和救済・小幅個別回転を区別する、市場無関係の人工素材。"""

import numpy as np


def material(mid: object,mode: int,cap: int=1,last: object|None=None,half: object=.5,
             multiplier: float=1.,fee: float=0.,tick: float=1.,fraction: float=.01,
             trail: float=1.,entry_end: float|None=None,close: float|None=None) -> tuple:
    """
    機能: 新規参照Lastと実約定BBOを独立に指定できる人工観測を作る。
    引数: mid/last/half(object)、mode/cap(int)、契約・追尾・締切(float|None)。
    返り値: tupleは共通replayの全引数。実市場や保存金融結果を使わない。
    """
    price=np.asarray(mid,float);n=len(price)
    reference=price.copy() if last is None else np.asarray(last,float)
    spread=np.full(n,half) if np.ndim(half)==0 else np.asarray(half,float)
    deadline=float(n-5) if entry_end is None else float(entry_end)
    stop=float(n-3) if close is None else float(close)
    return (np.arange(n,dtype=np.int64),np.arange(n,dtype=float),reference,
            price-spread,price+spread,cap,multiplier,fee,tick,fraction,mode,trail,
            0.,deadline,stop,float(n+1))


def positive_peak_below_old_activation(mode: int) -> tuple:
    """
    機能: 旧二単位起動へ届かない純益peakから、一単位戻っても純益が残る素材を作る。
    引数: mode(int)はKEEP/RESCUE/ROTATE。
    返り値: tuple。TOPIX料金41円ずつならpeak1418円から418円へ戻る。
    """
    mid=[100,103,103,105.5,104.5,104.5,104.5,104.5,104.5,104.5,104.5,104.5]
    last=[100,103,104,105.5,104.5,104.5,104.5,104.5,104.5,104.5,104.5,104.5]
    return material(mid,mode,last=last,multiplier=1000.,fee=41.8,tick=.5,entry_end=7,close=9)


def rescue_realized_loss_is_not_erased(mode: int) -> tuple:
    """
    機能: 飽和救済でショート損失を確定し、ロング単体純益だけでは全組損を回収していない素材を作る。
    引数: mode(int)はKEEP又はRESCUE。
    返り値: tuple。救済後の開玉純益6に対し既実現損失12が残る。
    """
    return material([100,103,103,100,99,99,102,110,109,109,109,109,109,109,109,109],
                    mode,cap=1,entry_end=8,close=12)


def first_phase_only_one(mode: int) -> tuple:
    """
    機能: 一気に多数の段階を越えても初回予約は一枚だけかを確認する。
    引数: mode(int)は三管理のいずれか。
    返り値: tuple。初回fill後は残枠への追加を許す対照素材。
    """
    return material([100,120,121,122,122,122,122,122,122,122,122,122],
                    mode,cap=5,entry_end=6,close=9)
