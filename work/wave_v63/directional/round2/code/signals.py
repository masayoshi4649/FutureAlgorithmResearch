"""損失原因に対応する入口の対照を固定し、二指数の時計限界を参考区分へ分ける。"""

import math

import numpy as np
import pandas as pd


FAMILIES = {'P1': '方向が続いた後の押し戻しから再開', 'P2': '前レンジ外の拒否から内側へ復帰',
            'P3': '二指数の向き確認付き押し戻し再開', 'O2': '旧5分押し目対照', 'O4': '旧5分失敗突破対照'}
EXITS = {'T': 0, 'C': 1, 'R': 2}


def methods() -> list[dict]:
    """機能: 第1ラウンドの21条件を損益前に列挙する。

    引数: なし。
    返り値: 条件一覧(list[dict])。P3は受信時計不明のため厳密な主候補から除く。
    """
    entries = [(family, filtered) for family in ('P1', 'P2') for filtered in (False, True)]
    entries += [('P3', True), ('O2', False), ('O4', False)]
    return [dict(id=f'R1_{family}_{"F" if filtered else "N"}_{exit_id}', family=family, spread_filter=filtered,
                 exit_id=exit_id, exit_mode=mode, minutes=60, fraction=.001, width_id='W10',
                 initial_fraction=.5, pyramid=False, cooldown_minutes=10,
                 reference_only=family == 'P3', primary=family in ('P1', 'P2') and filtered and exit_id == 'R',
                 name=f'{FAMILIES[family]}・気配幅制限{filtered}・出口{exit_id}')
            for family, filtered in entries for exit_id, mode in EXITS.items()]


def width_of(opening_mid: float, tick: float) -> float:
    """機能: セッション観測始値から固定幅を求める。

    引数: opening_mid/tick(float)。
    返り値: 呼値切上げかつ最低2呼値の幅(float)。
    """
    return max(2 * tick, math.ceil(opening_mid * .001 / tick - 1e-10) * tick)


def join_partner(frame: pd.DataFrame, other: pd.DataFrame) -> pd.DataFrame:
    """機能: 他指数の60秒以前の公開行を参考情報として過去側に結合する。

    引数: frame/other(pd.DataFrame)。
    返り値: 相手変位と鮮度を付加した表(pd.DataFrame)。受信時計が無く厳密同時性は証明できない。
    """
    result = frame.copy()
    positions = np.searchsorted(other['time_s'].to_numpy(), frame['time_s'].to_numpy() - 60., side='right') - 1
    valid = positions >= 0
    chosen = np.maximum(positions, 0)
    if len(other) == 0:
        result['partner_ret10'], result['partner_valid'] = np.nan, False
        return result
    age = frame['time_s'].to_numpy() - other['time_s'].to_numpy()[chosen]
    valid &= (age >= 60.) & (age <= 180.) & other['can_trade'].to_numpy()[chosen]
    result['partner_ret10'] = np.where(valid, other['ret10'].to_numpy()[chosen], np.nan)
    result['partner_valid'] = valid
    return result


def candidates(frame: pd.DataFrame, opening_mid: float, tick: float) -> dict[str, np.ndarray]:
    """機能: 確定1分足だけで方向再開と前箱拒否の入口を判定する。

    引数: frame(pd.DataFrame)、opening_mid/tick(float)。
    返り値: P1_N/P1_F/P2_N/P2_F/P3_F別Nx3[判断行,方向,W](dict[str,ndarray])。
    """
    width = width_of(opening_mid, tick)
    quality = frame['can_trade'] & frame['observed_lag2'].eq(True)
    p1buy = quality & frame['ret10'].ge(width) & frame['er10'].ge(.5)
    p1buy &= frame['close_lag1'].le(frame['close_lag2']) & frame['close'].gt(frame['high_lag1'] + tick)
    p1sell = quality & frame['ret10'].le(-width) & frame['er10'].ge(.5)
    p1sell &= frame['close_lag1'].ge(frame['close_lag2']) & frame['close'].lt(frame['low_lag1'] - tick)
    box_ok = quality & frame['prior_observed_fraction'].ge(.8)
    p2buy = box_ok & frame['low'].lt(frame['prior_low'] - tick) & frame['close'].ge(frame['prior_low'] + tick)
    p2buy &= frame['close'].gt(frame['open'])
    p2sell = box_ok & frame['high'].gt(frame['prior_high'] + tick) & frame['close'].le(frame['prior_high'] - tick)
    p2sell &= frame['close'].lt(frame['open'])
    spread_ok = frame['spread'].le(.15 * width)
    masks = {'P1_N': (p1buy, p1sell), 'P1_F': (p1buy & spread_ok, p1sell & spread_ok),
             'P2_N': (p2buy, p2sell), 'P2_F': (p2buy & spread_ok, p2sell & spread_ok),
             'P3_F': (p1buy & spread_ok & frame['partner_ret10'].gt(0),
                      p1sell & spread_ok & frame['partner_ret10'].lt(0))}
    output = {}
    for family, (buy, sell) in masks.items():
        use = buy ^ sell
        output[family] = np.column_stack((frame.loc[use, 'i'], np.where(buy[use], 1., -1.), np.full(int(use.sum()), width))).astype(float)
    return output
