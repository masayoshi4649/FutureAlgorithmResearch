"""中期候補を、事前固定した五つの単純な価格条件から判定する。"""

import math

import numpy as np
import pandas as pd

from features import SETTINGS


FAMILIES = {'MT1': '短長移動平均の交差', 'MT2': '過去の高安突破', 'MT3': '傾向方向への戻りから再開',
            'MR1': '行き過ぎから平均方向へ復帰', 'MA1': '傾向と反復の自動選択'}
WIDTHS = {'W10': .001, 'W20': .002}
EXITS = {'X1': '損切り1幅・利確1.5幅', 'X2': '1幅順行後に1幅追跡'}


def methods() -> list[dict]:
    """機能: 五入口・二期間・二幅・二出口・三期限の120条件を固定列挙する。

    引数: なし。
    返り値: パラメータ、説明、固定主条件印を持つ一覧(list[dict])。
    """
    return [dict(id=f'{family}_{setting["id"]}_{width}_{exit_id}_T{minutes}', family=family,
                 setting_id=setting['id'], width_id=width, fraction=fraction, exit_id=exit_id,
                 minutes=minutes, name=f'{name}・SMA{setting["short"]}/{setting["long"]}・始値{fraction * 100:g}%・{EXITS[exit_id]}・{minutes}分',
                 primary=setting['id'] == 'P3_9' and width == 'W10' and exit_id == 'X2' and minutes == 45)
            for family, name in FAMILIES.items() for setting in SETTINGS
            for width, fraction in WIDTHS.items() for exit_id in EXITS for minutes in (30, 45, 60)]


def candidates(frame: pd.DataFrame, opening_mid: float, tick: float, fraction: float) -> dict[str, np.ndarray]:
    """機能: 確定足で五入口を判断し、次原本約定に渡す行位置・方向・固定幅を作る。

    引数: frame(pd.DataFrame)、opening_mid/tick/fraction(float)。
    返り値: 入口IDごとの Nx3 [判断原本有効行位置,方向,W] (dict[str,np.ndarray])。
    銘柄名による戦略分岐、最終約定値、将来価格は使わない。
    """
    width = max(2 * tick, math.ceil(opening_mid * fraction / tick - 1e-10) * tick)
    close, previous = frame['close'], frame['close_lag1']
    short, long = frame['short'], frame['long']
    z = (close - long) / frame['std']
    old_z = (previous - frame['long_lag1']) / frame['std_lag1']
    std_ok = frame['std'].gt(0) & frame['std_lag1'].gt(0)
    signals = {
        'MT1': (frame['gap_lag1'].le(0) & frame['gap'].gt(0), frame['gap_lag1'].ge(0) & frame['gap'].lt(0)),
        'MT2': (frame['prior_observed_fraction'].ge(.8) & close.gt(frame['prior_high'] + tick) & short.gt(long),
                frame['prior_observed_fraction'].ge(.8) & close.lt(frame['prior_low'] - tick) & short.lt(long)),
        'MT3': (short.gt(long) & long.gt(frame['long_lag2']) & previous.le(frame['short_lag1']) & close.gt(short),
                short.lt(long) & long.lt(frame['long_lag2']) & previous.ge(frame['short_lag1']) & close.lt(short)),
        'MR1': (std_ok & old_z.le(-2) & z.gt(-2) & close.lt(long) & frame['er'].le(.4)
                & (long - frame['long_lag3']).abs().le(width),
                std_ok & old_z.ge(2) & z.lt(2) & close.gt(long) & frame['er'].le(.4)
                & (long - frame['long_lag3']).abs().le(width)),
    }
    signals['MA1'] = (
        (frame['er'].ge(.4) & signals['MT3'][0]) | (frame['er'].le(.25) & signals['MR1'][0]),
        (frame['er'].ge(.4) & signals['MT3'][1]) | (frame['er'].le(.25) & signals['MR1'][1]),
    )
    output = {}
    for family, (buy, sell) in signals.items():
        chosen = frame['can_trade'] & (buy ^ sell)
        output[family] = np.column_stack((frame.loc[chosen, 'i'], np.where(buy[chosen], 1., -1.),
                                           np.full(int(chosen.sum()), width))).astype(float)
    return output


def audit(frame: pd.DataFrame, opening_mid: float, tick: float, fraction: float, full: dict) -> int:
    """機能: 公開特徴を途中で切っても、既判定の入口候補が変わらないか検査する。

    引数: frame(pd.DataFrame)、opening_mid/tick/fraction(float)、full(dict)。
    返り値: 合格した候補配列の比較数(int)。
    """
    checks = 0
    for size in (0, 1, len(frame) // 2):
        part = frame.iloc[:size]
        results = candidates(part, opening_mid, tick, fraction)
        for family, rows in full.items():
            expected = rows[:0] if part.empty else rows[rows[:, 0] <= part.iloc[-1]['i']]
            np.testing.assert_array_equal(results[family], expected)
            checks += 1
    return checks
