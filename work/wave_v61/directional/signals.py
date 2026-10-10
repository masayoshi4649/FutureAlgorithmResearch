"""五入口・六期限・三幅・三積極度の270条件を、成績前に固定する。"""

import math

import numpy as np
import pandas as pd


FAMILIES = {'D1': '開始30分レンジの突破', 'D2': '傾向方向への押し戻しから復帰',
            'D3': 'レンジ内の行き過ぎから復帰', 'D4': '失敗した突破への逆張り',
            'D5': '効率比で押し目と回帰を自動選択'}
WIDTHS = {'W05': .0005, 'W10': .001, 'W20': .002}
AGGRESSIONS = {'A0': {'initial_fraction': .2, 'pyramid': False, 'cooldown_minutes': 30},
               'A1': {'initial_fraction': .5, 'pyramid': False, 'cooldown_minutes': 10},
               'A2': {'initial_fraction': .5, 'pyramid': True, 'cooldown_minutes': 0}}


def methods() -> list[dict]:
    """機能: 入口、最大保有時間、固定幅、運用方針の全270条件を列挙する。

    引数: なし。
    返り値: 条件辞書の一覧(list[dict])。積極度は複数要素をまとめた運用方針である。
    """
    return [dict(id=f'{family}_H{minutes}_{width}_{aggression}', family=family, minutes=minutes,
                 width_id=width, fraction=fraction, aggression=aggression, **policy,
                 name=f'{name}・最大{minutes}分・始値{fraction * 100:g}%・{aggression}',
                 primary=minutes == 60 and width == 'W10' and aggression == 'A1')
            for family, name in FAMILIES.items() for minutes in (5, 15, 30, 60, 120, 240)
            for width, fraction in WIDTHS.items() for aggression, policy in AGGRESSIONS.items()]


def failed_breakout(frame: pd.DataFrame, tick: float) -> np.ndarray:
    """機能: 過去箱を突破した境界を固定し、次1〜3足で戻った場合だけ逆張りを判定する。

    引数: frame(pd.DataFrame) は公開済み5分足、tick(float) は大口契約の呼値。
    返り値: 各公開足の方向配列(np.ndarray)。空白足・3足超過で待機状態を破棄する。
    """
    found = np.zeros(len(frame), dtype=np.int8)
    armed_side, armed_bucket, boundary = 0, -1, np.nan
    previous_bucket = None
    for n, row in enumerate(frame.itertuples(index=False)):
        bucket = int(row.source_bucket)
        if previous_bucket is not None and bucket != previous_bucket + 1:
            armed_side = 0
        previous_bucket = bucket
        if not row.can_trade or row.prior_observed_fraction < .8:
            armed_side = 0
            continue
        if armed_side and bucket - armed_bucket > 3:
            armed_side = 0
        if armed_side:
            if armed_side > 0 and row.close <= boundary - tick:
                found[n] = -1
                armed_side = 0
            elif armed_side < 0 and row.close >= boundary + tick:
                found[n] = 1
                armed_side = 0
            # 同足を返済後に別の突破の起点へ再利用しない。
            continue
        if row.close > row.prior_high + tick:
            armed_side, armed_bucket, boundary = 1, bucket, row.prior_high
        elif row.close < row.prior_low - tick:
            armed_side, armed_bucket, boundary = -1, bucket, row.prior_low
    return found


def candidates(frame: pd.DataFrame, opening_mid: float, tick: float, fraction: float) -> dict[str, np.ndarray]:
    """機能: 将来値を使わず確定足から入口候補を作り、次原本行の約定器へ渡す。

    引数: frame(pd.DataFrame)、opening_mid/tick/fraction(float)。
    返り値: 系統ごとのNx3[判断行位置,方向,固定幅](dict[str,np.ndarray])。
    """
    width = max(2 * tick, math.ceil(opening_mid * fraction / tick - 1e-10) * tick)
    close, prev, short, long = (frame[name] for name in ('close', 'close_lag1', 'short', 'long'))
    z, previous_z = (close - long) / frame['std'], (prev - frame['long_lag1']) / frame['std_lag1']
    std_ok = frame['std'].gt(0) & frame['std_lag1'].gt(0)
    range_ok = frame['er'].le(.30) & (long - frame['long_lag3']).abs().le(width)
    masks = {
        'D1': (frame['can_opening'] & prev.le(frame['opening_high'] + tick) & close.gt(frame['opening_high'] + tick),
               frame['can_opening'] & prev.ge(frame['opening_low'] - tick) & close.lt(frame['opening_low'] - tick)),
        'D2': (frame['can_trade'] & short.gt(long) & long.gt(frame['long_lag2'])
               & prev.le(frame['short_lag1']) & close.gt(short),
               frame['can_trade'] & short.lt(long) & long.lt(frame['long_lag2'])
               & prev.ge(frame['short_lag1']) & close.lt(short)),
        'D3': (frame['can_trade'] & std_ok & range_ok & previous_z.le(-2) & z.gt(-2) & close.lt(long),
               frame['can_trade'] & std_ok & range_ok & previous_z.ge(2) & z.lt(2) & close.gt(long)),
    }
    failure = failed_breakout(frame, tick)
    masks['D4'] = (pd.Series(failure > 0, index=frame.index), pd.Series(failure < 0, index=frame.index))
    masks['D5'] = ((frame['er'].ge(.45) & masks['D2'][0]) | (frame['er'].le(.25) & masks['D3'][0]),
                   (frame['er'].ge(.45) & masks['D2'][1]) | (frame['er'].le(.25) & masks['D3'][1]))
    output = {}
    for family, (buy, sell) in masks.items():
        chosen = buy ^ sell
        output[family] = np.column_stack((frame.loc[chosen, 'i'], np.where(buy[chosen], 1., -1.),
                                          np.full(int(chosen.sum()), width))).astype(float)
    return output


def audit(frame: pd.DataFrame, opening_mid: float, tick: float, fraction: float, full: dict) -> int:
    """機能: 途中公開までの表を切り出しても候補履歴が変わらないことを検査する。

    引数: frame(pd.DataFrame)、opening_mid/tick/fraction(float)、full(dict)。
    返り値: 比較回数(int)。売買損益は使用しない。
    """
    checks = 0
    for size in (0, 1, len(frame) // 3, len(frame) * 2 // 3):
        part = frame.iloc[:size]
        actual = candidates(part, opening_mid, tick, fraction)
        for family, values in full.items():
            expected = values[:0] if part.empty else values[values[:, 0] <= part.iloc[-1]['i']]
            np.testing.assert_array_equal(actual[family], expected)
            checks += 1
    return checks
