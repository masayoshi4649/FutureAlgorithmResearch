"""共通価格進行と、板フロー及び実気配による反対合意を因果的に計算する。"""

import importlib.util
from pathlib import Path
import sys

import numba
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = ('TOPIX', 'NK225')
sys.dont_write_bytecode = True


def legacy_module():
    """
    機能: 旧76信号を読取専用で取り込み、旧JITキャッシュを変更しない。
    引数: なし。
    返り値: object は旧信号モジュール。
    """
    name = '既往板信号76の読取78'
    if name in sys.modules:
        return sys.modules[name]
    previous = numba.config.CACHE_DIR
    spec = importlib.util.spec_from_file_location(name, ROOT / 'work/wave_v76/signals.py')
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    try:
        spec.loader.exec_module(value)
    finally:
        numba.config.CACHE_DIR = previous
    return value


LEGACY = legacy_module()


def confirmation(grid, condition, valid, source_a, source_b, seconds):
    """
    機能: 欠測を跨がず条件の持続時間と開始後の両市場更新を確認する。
    引数: grid (ndarray[float])、condition/valid (ndarray[bool])、
        source_a/source_b (ndarray[int])、seconds (float)。
    返り値: ndarray[bool] は各判断時点で確認が完了したか。
    """
    return LEGACY.confirmation.py_func(grid, condition, valid, source_a, source_b, seconds)


def direction(session, window, sign, threshold, inclusive=True):
    """
    機能: 両商品の過去窓の価格が指定方向と強度を満たすか判定する。
    引数: session (dict)、window/sign (int)、threshold (float、bp)、inclusive (bool)。
    返り値: ndarray[bool] は双方有効かつ同方向進行の判定。
    """
    answer = np.ones(len(session['grid']), dtype=bool)
    for symbol in SYMBOLS:
        w = session['markets'][symbol]['windows'][window]
        signed = sign * w['ret_bp']
        answer &= w['source_valid'] & np.isfinite(signed)
        answer &= signed >= threshold if inclusive else signed > threshold
    return answer


def fd_market(market):
    """
    機能: 価格用素材を旧FD15が要求する十段品質とフロー窓へ接続する。
    引数: market (dict) は保存済みの価格・板特徴。
    返り値: dict は旧76 market_state用の浅いコピー。元資料は変更しない。
    """
    return {'current': dict(market['current'], valid=market['current']['q_valid']),
            'windows': {15: market['flow'][15]}}


def session_state(session):
    """
    機能: 一場の共通進行と反対合意の二段階を計算する。
    引数: session (dict) は損益を含まない5秒判断格子と過去特徴。
    返り値: dict は共通方向、参照行、有効性、ロング/ショートへの撤退旗。
    FD単独とFD＋気配進行は、それぞれ生条件から15秒を測る。
    """
    grid = session['grid']
    a, b = (session['markets'][s] for s in SYMBOLS)
    sa, sb = a['current']['index'], b['current']['index']
    valid = a['current']['valid'] & b['current']['valid']
    valid300 = valid.copy()
    valid30 = valid.copy()
    for m in (a, b):
        valid300 &= m['windows'][300]['source_valid'] & np.isfinite(m['windows'][300]['ret_bp'])
        valid30 &= m['windows'][30]['source_valid'] & np.isfinite(m['windows'][30]['ret_bp'])
    trend = np.zeros(len(grid), dtype=np.int8)
    common = trend.copy()
    for sign in (-1, 1):
        long_condition = valid & direction(session, 300, sign, 3.)
        trend[long_condition] = sign
        common[long_condition & direction(session, 30, sign, 0., False)] = sign

    # ----------------------------------------
    # FD15の強方向は、最良OFIと距離加重板が同時に閾値を超えた方向。
    definition = next(d for d in LEGACY.definitions() if d['id'] == 'FD15')
    ast, _, av, _ = LEGACY.market_state(definition, fd_market(a))
    bst, _, bv, _ = LEGACY.market_state(definition, fd_market(b))
    fd_valid = av & bv
    strong = np.where(fd_valid & (ast == bst), ast, 0).astype(np.int8)
    fd = {}
    fd_price = {}
    price_valid = fd_valid & valid30
    for sign in (-1, 1):
        condition = strong == sign
        fd[sign] = confirmation(grid, condition, fd_valid, sa, sb, 15.)
        progress = condition.copy()
        for market in (a, b):
            w = market['windows'][30]
            progress &= sign * w['bid_change_ticks'] >= 1.-1e-8
            progress &= sign * w['ask_change_ticks'] >= 1.-1e-8
        fd_price[sign] = confirmation(grid, progress, price_valid, sa, sb, 15.)
    return dict(grid=grid, valid=valid, current300_valid=valid300,
                common=common, trend300=trend, source_top=sa, source_nk=sb,
                fd_long=fd[-1], fd_short=fd[1],
                fd_price_long=fd_price[-1], fd_price_short=fd_price[1],
                fd_valid=fd_valid, fd_price_valid=price_valid)


def mapping(grid, ready):
    """
    機能: 判断格子を以後10秒以内の自市場原本行へ対応付ける。
    引数: grid (ndarray[float])、ready (dict、time_sを含む)。
    返り値: ndarray[int32] は各原本行で採用する最新格子番号。
    """
    return LEGACY.mapping(grid, ready)


def build(grids):
    """
    機能: 全場の価格共同方向と二種類の反対合意を作る。
    引数: grids (dict[str,dict]) は保存特徴のみ。
    返り値: dict[str,dict] は場別信号。損益は読み込まない。
    """
    return {key: session_state(value) for key, value in grids.items()}
