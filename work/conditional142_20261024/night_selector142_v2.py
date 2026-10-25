"""日経夜間補完の入口経路と退出資格を、当時の時間軸・価格位置・原板で選ぶ。"""

import numpy as np
from numba import njit


ROUTES = {0: '候補方向なし', 1: '旧方向で即時', 2: '初回方向を固定して支持待ち',
          3: '直近合議方向を固定して支持待ち', 4: '旧方向への多時間軸反証で新方向へ即時'}
REASONS = {10: '公開履歴又は価格が未知', 11: '旧方向が不成立',
           19: '強い直近反証が揃わないため旧方向で即時参加',
           20: '20分合議が旧方向を支持', 21: '直近20分への転換を複数時間軸で支持',
           22: '時間軸が混在し初回方向を維持', 23: '価格と平均線が旧方向を支持',
           24: '直近方向への平均線位置を確認', 25: '平均線位置が未確認',
           26: '価格構造と原板が旧方向を否定していない', 27: '直近方向への原板支持を確認',
           28: '原板が未知又は直近方向を確認できない',
           29: '双方20分・5分・120秒が旧方向を反証',
           30: '固定方向に5分支持が揃わない', 31: '20分合議が固定方向を否定',
           32: '直近方向への短期支持が消失', 33: '平均線位置が固定方向を否定',
           34: '原板支持が消失又は未知', 35: '入口資格成立',
           40: '短期逆行が未成立又は未知', 41: '短期逆行だけで中期は未否定',
           42: '短期と双方20分が逆行', 43: '短期と双方5分が逆行し20分平均を喪失',
           44: '中期否定と双方原板の逆行を確認', 45: '退出の原板裏付けが不足',
           46: '追加退出を使わず元停止と追尾だけで管理'}


def configurations():
    """
    機能: 時間軸・価格位置・原板の3案と、待機を行わない2案を比較前に固定する。
    引数: なし。
    返り値: list[dict]は入口と出口を一組で切り替えるZ01～Z03とZ04/Z05。
    """
    return [dict(id='Z01', name='時間軸の合議で入口と出口を切り替える', selector_mode=1),
            dict(id='Z02', name='時間軸と平均線位置で入口と出口を切り替える', selector_mode=2),
            dict(id='Z03', name='時間軸・平均線位置・二市場原板で切り替える', selector_mode=3),
            dict(id='Z04', name='強い直近反証だけ方向変更し即時参加・中期否定で退出', selector_mode=4),
            dict(id='Z05', name='強い直近反証だけ方向変更し即時参加・元停止追尾のみ', selector_mode=5)]


@njit(cache=True)
def original_direction(h, mid):
    """
    機能: 旧U06の始値優先・相殺時の代替方向を再現する。
    引数: h(ndarray[15])は公開履歴、mid(float)は当該原行中値。
    返り値: intは買い1・売り-1・未成立0。
    """
    score = np.sign(mid-h[8])+np.sign(h[13])
    if score == 0.:
        score = np.sign(h[7])+np.sign(h[11])
    if score == 0.:
        score = h[7]
    if score == 0.:
        score = mid-h[8]
    return 1 if score > 0. else (-1 if score < 0. else 0)


@njit(cache=True)
def consensus(h):
    """
    機能: 両市場の公開20分差が同じ非零方向かを判定する。
    引数: h(ndarray[15])は公開済み履歴。
    返り値: intは両市場一致方向、不一致又は同値は0。
    """
    own, peer = np.sign(h[7]), np.sign(h[11])
    return int(own) if own != 0. and own == peer else 0


@njit(cache=True)
def short_support(market, side):
    """
    機能: 新鮮な二市場の120秒変化が同方向かを確認する。
    引数: market(ndarray[12])、side(int)は厳密過去接続特徴と方向。
    返り値: bool。未測定・相手古い・同値はいずれも支持としない。
    """
    return (market[11] == 1. and np.isfinite(market[5]) and np.isfinite(market[7])
            and side*market[5] > 0. and side*market[7] > 0.)


@njit(cache=True)
def flow_support(raw, side):
    """
    機能: 原板の30秒OFI平均が双方同方向かを確認する。
    引数: raw(ndarray[4])は自己OFI・自己距離加重偏り・相手OFI・相手距離加重偏り、side(int)は方向。
    返り値: bool。OFIは約定方向や参加者意図ではなく、表示最良気配変化の指標。
    """
    return (np.isfinite(raw[0]) and np.isfinite(raw[2])
            and side*raw[0] > 0. and side*raw[2] > 0.)


@njit(cache=True)
def average_support(h, mid, side):
    """
    機能: 現在価格と5分平均が20分平均の同じ方向側にあるかを確認する。
    引数: h(ndarray[15])、mid(float)、side(int)は公開履歴・中値・方向。
    返り値: bool。平均線の形から将来を断定せず、既知価格の維持位置だけを見る。
    """
    return side*(mid-h[1]) > 0. and side*(h[0]-h[1]) > 0.


@njit(cache=True)
def entry_policy(h, market, mid, risk, tick, raw, selector_mode):
    """
    機能: 最初の候補時点で入口経路と固定方向を選ぶ。保有損益や未来は受け取らない。
    引数: h(ndarray[15])、market(ndarray[12])、mid/risk/tick(float)、raw(ndarray[4])、selector_mode(int)。
    返り値: tuple[int,int,int]は経路・固定方向・理由。経路と方向は売買側で一度だけ保存する。
    """
    assert selector_mode in (1, 2, 3, 4, 5)
    if (not np.isfinite(h).all() or not np.isfinite(mid) or not np.isfinite(risk)
            or not np.isfinite(tick) or risk <= 0. or tick <= 0.):
        return 0, 0, 10
    old = original_direction(h, mid)
    if old == 0:
        return 0, 0, 11
    medium = consensus(h)
    if selector_mode in (4, 5):
        strong_rebuttal = (medium == -old and medium*h[6] > 0. and medium*h[10] > 0.
                           and short_support(market, medium))
        return (4, medium, 29) if strong_rebuttal else (1, old, 19)
    # ----------------------------------------
    # 中期が旧判断を支持する場合は、短い逆行だけで旧方向を破棄しない。
    if selector_mode == 1:
        if medium == old:
            return 1, old, 20
        if medium == -old and medium*h[6] > 0. and medium*h[10] > 0. and short_support(market, medium):
            return 3, medium, 21
        return 2, old, 22
    if medium == old and average_support(h, mid, old):
        if selector_mode == 2:
            return 1, old, 23
        if np.isfinite(raw[0]) and np.isfinite(raw[2]) and not (flow_support(raw, -old) and short_support(market, -old)):
            return 1, old, 26
    recent = (medium == -old and average_support(h, mid, medium)
              and medium*h[6] >= 0. and medium*h[10] >= 0.
              and (h[6] != 0. or h[10] != 0.))
    if recent:
        if selector_mode == 2:
            return 3, medium, 24
        if short_support(market, medium) and flow_support(raw, medium):
            return 3, medium, 27
    return 2, old, 25 if selector_mode == 2 else 28


@njit(cache=True)
def entry_ready(h, market, mid, raw, selector_mode, route, side):
    """
    機能: 選択済み経路の支持が揃ったかを再確認し、待機中に反対方向へ変更しない。
    引数: h(ndarray[15])、market(ndarray[12])、mid(float)、raw(ndarray[4])、selector_mode/route/side(int)。
    返り値: tuple[bool,int]は新規資格と理由。主担当優先・次原行約定は売買側で扱う。
    """
    if route in (1, 4):
        return True, 35
    medium = consensus(h)
    if medium == -side:
        return False, 31
    if route == 2:
        if side*h[6] <= 0. or side*h[10] <= 0.:
            return False, 30
    elif route == 3:
        if medium != side or side*h[6] < 0. or side*h[10] < 0. or (h[6] == 0. and h[10] == 0.):
            return False, 30
        if selector_mode == 1 and not short_support(market, side):
            return False, 32
    else:
        return False, 30
    if selector_mode >= 2 and not average_support(h, mid, side):
        return False, 33
    if selector_mode == 3 and not (short_support(market, side) and flow_support(raw, side)):
        return False, 34
    return True, 35


@njit(cache=True)
def exit_policy(h, market, side, entry, risk, mid, raw, selector_mode):
    """
    機能: 短期逆行が中期判断の否定も伴う場合だけ追加退出を許可する。
    引数: h(ndarray[15])、market(ndarray[12])、side(int)、entry/risk/mid(float)、raw(ndarray[4])、selector_mode(int)。
    返り値: tuple[bool,int]は退出資格と理由。15秒の継続・時計空白リセット・固定停止は売買側。
    """
    if selector_mode == 5:
        return False, 46
    inverse = market[11] == 1.
    for col in (4, 5, 6, 7):
        inverse = inverse and np.isfinite(market[col]) and side*market[col] < 0.
    if not inverse or not np.isfinite(h).all():
        return False, 40
    medium_broken = side*h[7] < 0. and side*h[11] < 0.
    average_lost = side*h[6] < 0. and side*h[10] < 0. and side*(mid-h[1]) < 0.
    enabled = medium_broken or (selector_mode in (2, 3) and average_lost)
    if not enabled:
        return False, 41
    if selector_mode == 3:
        return (True, 44) if flow_support(raw, -side) else (False, 45)
    return True, 42 if medium_broken else 43


@njit(cache=True)
def initial_conflict(market, side, raw):
    """
    機能: 初回方向に対し二市場120秒と原板OFIがともに逆向きか確認する。
    引数: market(ndarray[12])、side(int)、raw(ndarray[4])は当時特徴と確定した方向。
    返り値: bool。必要値欠測又は相手鮮度不足は逆行確認不成立であり、縮小しない。
    """
    return short_support(market, -side) and flow_support(raw, -side)
