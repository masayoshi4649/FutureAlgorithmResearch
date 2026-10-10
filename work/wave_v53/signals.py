"""一般的なチャートと板読みの候補を、同一セッションの確定情報で機械化する。"""

from __future__ import annotations

import numpy as np
import pandas as pd


FAMILIES = [
    ('T01', '支持抵抗での反発', '過去20分の端に触れて内側へ戻ったら、レンジ中央への戻りを狙う。', '反復'),
    ('T02', '突破後の戻り試し', '過去20分の端を突破した線を固定し、10分以内の再接触で線の外を保てば追う。', '追従'),
    ('T03', '開始30分レンジ突破', '最初の30分の高安を固定し、その外で終わった方向へ追う。', '追従'),
    ('T04', 'VWAPからの乖離回帰', '当場の近似VWAPから1ATR以上離れ、戻り始めたら平均への回帰を狙う。', '反復'),
    ('T05', 'VWAPの回復', '近似VWAPを跨いで戻り、平均線とVWAPの傾きも同方向なら追う。', '追従'),
    ('T06', '移動平均への押し戻し', '8分・21分EMAが整列する方向に、8分EMAを跨ぐ押し戻しから再開したら追う。', '追従'),
    ('T07', 'RSIの極端域から復帰', 'RSI14が30未満から30以上、または70超から70以下へ戻ったら反転を狙う。', '反復'),
    ('T08', 'ボリンジャー帯の内側へ復帰', '20分平均の2標準偏差の外で終わった後、帯内へ戻ったら中央への回帰を狙う。', '反復'),
    ('T09', '突破失敗からの逆方向', '過去20分線を突破後、5分以内に元の内側へ戻ったら失敗と読み逆へ入る。', '反復'),
    ('T10', '確定した高安構造の突破', '左右2本で遅れて確定した高値・安値が両方切り上がり／切り下がり、端を超えたら追う。', '追従'),
    ('T11', '板の回復と価格反転', '同価格数量の回復が片側へ偏り、直前の値動きもその側へ反転したら入る。', '反復'),
    ('T12', '強い執行偏りの直後に逆張り', '買い又は売りの代理偏りが0.6以上で、同方向に値動きが出た時点で逆へ入る。', '反復'),
]
LAYERS = [('A', '基本保護', False, False), ('B', '高度管理', True, False),
          ('C', '板・相手の確認', False, True), ('D', '確認＋高度管理', True, True)]


def finite(*values: float) -> bool:
    """機能: 必要な過去値がすべて利用可能か確認する。

    引数: values(floatの可変長列)。返り値: 利用可能(bool)。
    """
    return all(np.isfinite(x) for x in values)


def mode(row) -> tuple[int, int]:
    """機能: 価格の効率・平均線乖離・VWAP位置から、場内の状況を判定する。

    引数: row(確定観測行)。返り値: 状況0不明/1追従/2反復・追従方向(tuple[int,int])。
    """
    if not finite(row.er15, row.ema8, row.ema21, row.atr5):
        return 0, 0
    d = int(np.sign(row.ema8 - row.ema21))
    if d and row.er15 >= .4 and abs(row.ema8-row.ema21) >= .25*row.atr5 and finite(row.vwap_proxy) and d*(row.close-row.vwap_proxy) > 0:
        return 1, d
    return (2, 0) if row.er15 <= .25 else (0, 0)


def peer_direction(row) -> int:
    """機能: 60秒以上遅らせた相手市場が明確に傾いている時だけ方向を返す。

    引数: row(確定観測行)。返り値: 方向(int)、不明は0。
    """
    if not finite(row.peer_ema8, row.peer_ema21, row.peer_atr5, row.peer_er15) or row.peer_can_trade != 1:
        return 0
    if row.peer_er15 >= .4 and abs(row.peer_ema8-row.peer_ema21) >= .25*row.peer_atr5:
        return int(np.sign(row.peer_ema8-row.peer_ema21))
    return 0


def book_direction(row) -> int:
    """機能: 同価格回復と提示価格変更が一致した時だけ、保有中の板方向を返す。

    引数: row(確定観測行)。返り値: 方向(int)、不明/不一致は0。
    """
    if row.board_valid != 1 or not finite(row.recovery, row.repricing):
        return 0
    if row.recovery * row.repricing > 0:
        return int(np.sign(row.recovery))
    return 0


def confirmed(row, direction: int, kind: str, regime: int, trend: int) -> bool:
    """機能: 仮説の種類に応じて板の反応を確認し、相手が逆行中なら新規を見送る。

    引数: row(確定観測行)、direction/regime/trend(int)、kind(str)。返り値: 新規許可(bool)。
    相手不明は一致と数えず、明確な反対だけを拒否する。板不明は新規確認不成立。
    """
    if not direction or row.board_valid != 1 or peer_direction(row) == -direction:
        return False
    if kind == '追従':
        if regime == 1 and trend == -direction:
            return False
        flow = finite(row.execution, row.unknown_fraction) and row.unknown_fraction < 1 and direction * row.execution >= 0
        quote = finite(row.repricing) and direction * row.repricing > 0
        return (flow or quote) and finite(row.supply) and direction * row.supply >= -.1
    recovery = finite(row.recovery) and direction * row.recovery > 0
    turn = finite(row.execution, row.unknown_fraction) and row.unknown_fraction < 1 and direction * row.execution >= 0 and direction * (row.close-row.prev_close) > 0
    return recovery or turn


def candidates(frame: pd.DataFrame) -> tuple[dict, list]:
    """機能: 12入口の信号・失敗線・回帰目標を、過去の状態だけで作る。

    引数: frame(DataFrame)。返り値: 手法別候補配列と観測行(list)の組。
    現在足を含まない高安を使い、突破線は発生時に固定して後から引き直さない。
    """
    frame = frame.copy()
    frame['vwap_same_previous'] = frame.vwap_anchor_time == frame.vwap_anchor_time.shift(1)
    frame['vwap_same_lag5'] = frame.vwap_anchor_time == frame.vwap_anchor_time.shift(5)
    for side in ('high', 'low'):
        current, previous, stamp = np.nan, np.nan, np.nan
        values = []
        for level, confirmed_seq in zip(frame[f'swing_{side}'], frame[f'swing_{side}_confirmed_seq']):
            if np.isfinite(confirmed_seq) and confirmed_seq != stamp:
                previous, current, stamp = current, level, confirmed_seq
            values.append(previous)
        frame[f'swing_{side}_previous'] = values
    rows = list(frame.itertuples())
    result = {f[0]: np.full((len(rows), 3), np.nan) for f in FAMILIES}
    for values in result.values():
        values[:, 0] = 0
    breaks = {1: None, -1: None}
    failures = {1: None, -1: None}
    previous_time = None
    for i, r in enumerate(rows):
        if not r.can_trade or (previous_time is not None and r.time_s-previous_time > 120):
            breaks, failures = {1: None, -1: None}, {1: None, -1: None}
            previous_time = r.time_s
            continue
        previous_time = r.time_s
        a, c, p = r.atr5, r.close, r.prev_close
        choices = {f[0]: [] for f in FAMILIES}
        midpoint = (r.prior20_high+r.prior20_low)/2 if finite(r.prior20_high, r.prior20_low) else np.nan
        for d in (1, -1):
            edge = r.prior20_low if d > 0 else r.prior20_high
            outside = r.low if d > 0 else r.high
            pivot = r.swing_low if d > 0 else r.swing_high
            stop = min(r.low, r.prev_low)-.1*a if d > 0 else max(r.high,r.prev_high)+.1*a
            # ----------------------------------------
            # 既に知られていた水平線と、その線への反応。
            if finite(edge, midpoint) and d*(outside-edge) <= .1*a and d*(c-edge) >= .1*a and d*(c-p)>0 and d*(midpoint-c) >= .25*a:
                choices['T01'].append((d, min(outside,edge)-.1*a if d>0 else max(outside,edge)+.1*a, midpoint))
            event = breaks[d]
            if event is not None:
                at, line = event
                if r.time_s-at > 600:
                    breaks[d] = None
                elif d*(outside-line) <= .1*a and d*(c-line) > .1*a and d*(c-r.open) > 0:
                    choices['T02'].append((d, outside-d*.1*a, np.nan))
                    breaks[d] = None
            event = failures[d]
            if event is not None:
                at, line = event
                if r.time_s-at > 300:
                    failures[d] = None
                elif d*(c-line) < -.1*a:
                    reverse = -d
                    reverse_stop = r.high+.1*a if reverse < 0 else r.low-.1*a
                    choices['T09'].append((reverse, reverse_stop, midpoint))
                    failures[d] = None
            upper = r.prior20_high if d > 0 else r.prior20_low
            if finite(upper) and d*(c-upper) > .1*a and d*(p-upper) <= 0:
                if breaks[d] is None:
                    breaks[d] = (r.time_s, upper)
                if failures[d] is None:
                    failures[d] = (r.time_s, upper)
            opening_edge = r.or30_high if d > 0 else r.or30_low
            if finite(opening_edge) and d*(p-opening_edge) <= 0 and d*(c-opening_edge) > .1*a:
                choices['T03'].append((d, opening_edge-d*.25*a, np.nan))
            # ----------------------------------------
            # 当場の平均価格・平均線に対する行き過ぎと回復。
            if r.vwap_same_previous and finite(r.vwap_proxy, r.prev_vwap_proxy) and d*(p-r.prev_vwap_proxy) < -a and d*(c-p)>0 and d*(r.vwap_proxy-c)>.25*a:
                choices['T04'].append((d, stop, r.vwap_proxy))
            if r.vwap_same_previous and r.vwap_same_lag5 and finite(r.vwap_proxy, r.prev_vwap_proxy, r.vwap_proxy_lag5, r.ema21_lag5) and d*(p-r.prev_vwap_proxy)<=0 and d*(c-r.vwap_proxy)>0 and d*(r.ema8-r.ema21)>0 and d*(r.ema21-r.ema21_lag5)>0 and d*(r.vwap_proxy-r.vwap_proxy_lag5)>=0:
                choices['T05'].append((d, stop, np.nan))
            if finite(r.ema21_lag5) and d*(r.ema8-r.ema21)>0 and d*(r.ema21-r.ema21_lag5)>0 and d*(p-r.prev_ema8)<=0 and d*(c-r.ema8)>0:
                choices['T06'].append((d, stop, np.nan))
            rsi_cross = r.prev_rsi14 < 30 <= r.rsi14 if d>0 else r.prev_rsi14 > 70 >= r.rsi14
            if rsi_cross and d*(c-p)>0:
                choices['T07'].append((d, stop, r.mean20))
            old_band = r.prev_mean20-d*2*r.prev_std20
            band = r.mean20-d*2*r.std20
            if finite(old_band,band) and d*(p-old_band)<0 and d*(c-band)>=0:
                choices['T08'].append((d, stop, r.mean20))
            # ----------------------------------------
            # 後から確定する高安は、公開された時点からだけ利用する。
            if finite(r.swing_high, r.swing_low, r.swing_high_previous, r.swing_low_previous):
                line = r.swing_high if d > 0 else r.swing_low
                if d*(r.swing_high-r.swing_high_previous)>0 and d*(r.swing_low-r.swing_low_previous)>0 and d*(p-line)<=0 and d*(c-line)>0:
                    choices['T10'].append((d, pivot-d*.1*a, np.nan))
            if r.board_valid == 1 and finite(r.recovery, r.supply, r.prev_close, r.prev_open):
                if d*r.recovery >= .1 and d*r.supply >= 0 and d*(r.prev_close-r.prev_open)<0 and d*(c-p)>0:
                    choices['T11'].append((d, stop, r.mean20))
            if r.board_valid == 1 and finite(r.execution, r.unknown_fraction) and r.unknown_fraction < 1 and -d*r.execution >= .6 and -d*(c-p)>0:
                choices['T12'].append((d, stop, r.mean20))
        for name, signals in choices.items():
            if len(signals) == 1:
                result[name][i] = signals[0]
    return result, rows


def make_decisions(frame: pd.DataFrame, choices: dict, rows: list, family: str, confirmation: bool) -> tuple:
    """機能: 固定した入口又は状況別選択を行い、確認前後の方向を分離して渡す。

    引数: frame(DataFrame)、choices(dict)、rows(list)、family(str)、confirmation(bool)。
    返り値: 執行器の指示配列と判断ログ(tuple)。
    """
    names = {f[0]: f for f in FAMILIES}
    output, trace = [], []
    for i, row in enumerate(rows):
        regime, trend = mode(row)
        selected = family
        if family == 'AUTO':
            priority = ['T02','T06','T05','T10','T03'] if regime == 1 else ['T01','T08','T04','T07'] if regime == 2 else ['T09']
            selected = next((key for key in priority if choices[key][i,0] and (regime != 1 or choices[key][i,0] == trend)), '')
        candidate = choices[selected][i] if selected else np.array([0., np.nan, np.nan])
        raw, invalidation, target = int(candidate[0]), candidate[1], candidate[2]
        signal = raw if raw and (not confirmation or confirmed(row, raw, names[selected][3], regime, trend)) else 0
        if not row.can_trade:
            raw = signal = 0
        book = book_direction(row)
        output.append([row.ready_index, signal, raw, invalidation, target, row.atr5, regime, trend, book, row.swing_low, row.swing_high])
        trace.append(dict(時刻=row.time_s, 原本行=int(row.seq), 足の最終原本行=int(row.source_last_seq),
                          選択=selected, 状況=regime, 追従方向=trend, 候補方向=raw, 新規方向=signal,
                          板方向=book, 相手方向=peer_direction(row), 板有効=bool(row.board_valid)))
    return np.asarray(output, float), trace
