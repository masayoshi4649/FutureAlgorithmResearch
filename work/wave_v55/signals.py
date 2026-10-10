"""始値割合・ボリンジャーバンド・高安・移動平均だけの入口。"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd


FAMILIES = [('P01', '始値から0.10%の方向へ'), ('P02', 'ボリンジャーバンド突破'),
            ('P03', 'ボリンジャーバンド内へ復帰'), ('P04', '直前20分の高安を突破'),
            ('P05', '移動平均8・21の交差')]
WIDTHS = [('W05', '始値の0.05%', .0005), ('W10', '始値の0.10%', .001),
          ('W20', '始値の0.20%', .002), ('S1', '判断時の標準偏差1倍', 0.)]


def methods() -> list[dict]:
    """機能: 成績を参照せず、5入口と4管理幅の20条件を列挙する。

    引数: なし。返り値: 手法仕様(list[dict])。
    """
    return [dict(id=f'{family}_{width}', family=family, width=width, fraction=fraction,
                 name=f'{name}／{label}', entry_name=name, width_name=label)
            for family, name in FAMILIES for width, label, fraction in WIDTHS]


def decisions(frame: pd.DataFrame, family: str, width_id: str, tick: float) -> np.ndarray:
    """機能: 確定足の入口交差と、その時点で固定できる管理幅だけを取り出す。

    引数: frame(DataFrame)、family/width_id(str)、tick(float)。
    返り値: 公開行番号・方向・固定幅の3列(ndarray)。銘柄名は使用しない。
    """
    fraction = dict((w, rate) for w, _, rate in WIDTHS)[width_id]
    output, initialized = [], False
    previous = None
    for row in frame.to_dict('records'):
        if not row['can_trade']:
            previous = row
            continue
        close, opening = float(row['close']), float(row['session_open'])
        mean, std = float(row['mean20']), float(row['std20'])
        if not np.isfinite([close, opening, mean, std]).all():
            previous = row
            continue
        continuous = previous is not None and row['bar_start'] - previous['bar_start'] == 60.
        side = 0
        if family == 'P01':
            upper, lower = opening * 1.001, opening * .999
            if not initialized:
                side = 1 if close > upper else (-1 if close < lower else 0)
            elif continuous:
                side = 1 if close > upper and previous['close'] <= upper else (-1 if close < lower and previous['close'] >= lower else 0)
        elif family in ('P02', 'P03'):
            upper, lower = mean + 2. * std, mean - 2. * std
            previous_ready = continuous and np.isfinite([previous['mean20'], previous['std20']]).all()
            if family == 'P02' and not initialized:
                side = 1 if close > upper else (-1 if close < lower else 0)
            elif previous_ready:
                old_upper = previous['mean20'] + 2. * previous['std20']
                old_lower = previous['mean20'] - 2. * previous['std20']
                if family == 'P02':
                    side = 1 if close > upper and previous['close'] <= old_upper else (-1 if close < lower and previous['close'] >= old_lower else 0)
                elif lower <= close <= upper:
                    side = -1 if previous['close'] > old_upper else (1 if previous['close'] < old_lower else 0)
        elif family == 'P04':
            high, low = row['prior20_high'], row['prior20_low']
            if np.isfinite([high, low]).all():
                side = 1 if close > high else (-1 if close < low else 0)
        elif family == 'P05':
            difference = row['ema8'] - row['ema21']
            if not initialized:
                side = int(np.sign(difference))
            elif continuous:
                old_difference = previous['ema8'] - previous['ema21']
                side = 1 if difference > 0 and old_difference <= 0 else (-1 if difference < 0 and old_difference >= 0 else 0)
        else:
            raise ValueError('未定義の入口です')
        initialized = True
        if side:
            raw_width = opening * fraction if width_id != 'S1' else std
            width = max(2., math.ceil(raw_width / tick - 1e-10)) * tick
            output.append([row['ready_index'], side, width])
        previous = row
    return np.asarray(output, float).reshape(-1, 3)
