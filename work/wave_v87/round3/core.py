"""公開済み支持を、追跡極値との時間順で判定する共通処理。"""
import numpy as np
from numba import njit


@njit(cache=True)
def supported(mode,side,extreme_row,row,seq,time,self_value,self_valid,self_source,peer_value,peer_valid,peer_source_time):
    """
    機能: 同じ観測までに公開された支持だけから次観測の注文許可を判定する。
    引数: mode/side/extreme_row/row(int)、原本・支持列(ndarray)。
    返り値: bool。欠測は反対方向と呼ばず許可しない。
    """
    if mode==0: return True
    if not self_valid[row] or side*self_value[row]<=.05: return False
    if mode in (2,4) and (extreme_row<0 or self_source[row]<=seq[extreme_row]): return False
    if mode in (3,4):
        if not peer_valid[row] or side*peer_value[row]<=.05: return False
        if mode==4 and (extreme_row<0 or peer_source_time[row]<=time[extreme_row]): return False
    return True
