"""二市場の短期方向から早期参加・継続・反転を選ぶ独立判断層。"""

import numpy as np
from numba import njit


REGIMES = {0:'方向未成立',1:'中期合意への追従',2:'中期に逆らう反発',3:'中期未確定又は不一致の短期参加'}
REASONS = {10:'短期又は活動資料が欠測',11:'二市場の活動範囲が不足',12:'120秒方向が不一致又は小さい',
           13:'30秒が新規方向へ逆行',14:'原板支持が不一致又は欠測',15:'中期逆向きの反発確認が不足',
           20:'短期合議成立',21:'反発の強い短期と原板合意',
           30:'保有維持',31:'短期反対方向の合議',32:'中期支持を維持し短期逆行を許容',
           33:'短期と5分が中期支持を反証',34:'短期逆行を原板又は中期も確認',
           35:'反発玉の30秒再失敗',36:'両市場の活動範囲が不足',37:'保有判断資料が欠測'}


@njit(cache=True)
def medium_direction(a):
    """
    機能: 公開20分方向を優先し、未公開の場合だけ40分の二市場合意を参照する。
    引数: a(ndarray[36])は当時特徴。
    返り値: intは買い1・売り-1・不一致又は不明0。中期未公開でも短期新規を禁止しない。
    """
    if np.isfinite(a[28]) and np.isfinite(a[29]):
        return 1 if a[28]>0. and a[29]>0. else (-1 if a[28]<0. and a[29]<0. else 0)
    if np.isfinite(a[4]) and np.isfinite(a[15]):
        return 1 if a[4]>0. and a[15]>0. else (-1 if a[4]<0. and a[15]<0. else 0)
    return 0


@njit(cache=True)
def activity(a):
    """
    機能: 過去300秒の観測レンジが呼値・気配差を上回るかを市場別に調べる。
    引数: a(ndarray[36])はレンジ30/31、気配差32/33、呼値34/35を持つ。
    返り値: tuple[bool,bool,bool]は資料正常・自己活発・相手活発。
    """
    for c in range(30,36):
        if not np.isfinite(a[c]):return False,False,False
    if a[32]<=0. or a[33]<=0. or a[34]<=0. or a[35]<=0.:return False,False,False
    return True,a[30]>=max(4.*a[34],3.*a[32]),a[31]>=max(4.*a[35],3.*a[33])


@njit(cache=True)
def short_known(a):
    """
    機能: 短期と各市場Rが当時利用可能か確認する。
    引数: a(ndarray[36])は厳密過去接続・鮮度検査済み特徴。
    返り値: bool。20/40分や平均線の公開は必須にしない。
    """
    return (np.isfinite(a[9]) and a[9]>0. and np.isfinite(a[18]) and a[18]>0.
            and np.isfinite(a[12]) and np.isfinite(a[13]) and np.isfinite(a[20]) and np.isfinite(a[21]))


@njit(cache=True)
def flow_support(a,side):
    """
    機能: 両市場の過去30秒OFI平均が候補方向を支持するか確認する。
    引数: a(ndarray[36])、side(int)は当時特徴と方向。
    返り値: bool。表示気配の変化であり、約定の買売や意図を断定しない。
    """
    return np.isfinite(a[24]) and np.isfinite(a[26]) and side*a[24]>0. and side*a[26]>0.


@njit(cache=True)
def signal(a,policy):
    """
    機能: 短期合議・中期状態・原板から新規候補を選択する。
    引数: a(ndarray[36])は当時特徴、policy(int)は1～6。
    返り値: tuple[int,int,int,float]は方向・状態・理由・必要確認秒。0方向は新規なし。
    """
    assert len(a)>=36 and 1<=policy<=6
    if not short_known(a):return 0,0,10,5.
    known,own,peer=activity(a)
    if not known:return 0,0,10,5.
    if not own or not peer:return 0,0,11,5.
    side=1 if a[13]>=.1 and a[21]>=.1 else (-1 if a[13]<=-.1 and a[21]<=-.1 else 0)
    if not side:return 0,0,12,5.
    if side*a[12]<-.025 or side*a[20]<-.025:return 0,0,13,5.
    medium=medium_direction(a)
    regime=1 if medium==side else (2 if medium==-side else 3)
    if policy==4 and not flow_support(a,side):return 0,regime,14,5.
    if policy==6 and regime==2:
        strong=side*a[13]>=.2 and side*a[21]>=.2 and side*a[12]>=.05 and side*a[20]>=.05
        if not strong or not flow_support(a,side):return 0,regime,15,15.
        return side,regime,21,15.
    return side,regime,20,5.


@njit(cache=True)
def management(a,side,policy,entry_regime):
    """
    機能: 時間固定で保有せず、短期反証・中期支持・反発失敗を選別する。
    引数: a(ndarray[36])、side/policy/entry_regime(int)は当時特徴と保有状態。
    返り値: tuple[int,int]は0維持/1返済/2反転候補/3無動意候補と理由。確認時計・注文は売買層が担う。
    """
    assert 1<=policy<=6 and side in (-1,1)
    if not short_known(a):return 0,37
    known,own,peer=activity(a)
    if known and not own and not peer:return 3,36
    medium=medium_direction(a)
    opposite=side*a[13]<=-.1 and side*a[21]<=-.1
    five_broken=np.isfinite(a[3]) and np.isfinite(a[14]) and side*a[3]<0. and side*a[14]<0.
    if policy==6 and entry_regime==2:
        if side*a[12]<=-.1 and side*a[20]<=-.1:
            return 1,35
    if not opposite:return 0,30
    if policy in (2,5,6) and medium==side:
        if not five_broken:return 0,32
        return (1 if policy==2 else 2),33
    if policy==4:
        if flow_support(a,-side) or (medium==-side and five_broken):return 2,34
        return 0,30
    return (1 if policy in (1,2) else 2),31


@njit(cache=True)
def initial_quantity(policy,regime):
    """
    機能: 中期支持がある場合だけ初回枚数を増やす政策対照を選ぶ。
    引数: policy/regime(int)は政策と新規判断時状態。
    返り値: intは通常2枚、政策5の中期追従だけ3枚。
    """
    return 3 if policy==5 and regime==1 else 2


@njit(cache=True)
def allow_add(a,side,policy,stop_floor):
    """
    機能: 利益保護後に新しい短期支持がある追撃だけを許す。
    引数: a(ndarray[36])、side/policy(int)、stop_floor(float)は当時特徴・方向・政策・元建値からの停止幅。
    返り値: bool。数量上限と初回損失予算は売買層が別途確認する。
    """
    if policy not in (5,6) or stop_floor<=0. or not short_known(a):return False
    support=side*a[12]>=.05 and side*a[20]>=.05 and side*a[13]>=.1 and side*a[21]>=.1
    return support and (policy!=6 or medium_direction(a)==side)
