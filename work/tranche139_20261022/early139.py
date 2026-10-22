"""確定した短い足だけで早期候補を作る。約定後の損益管理は別の状態機械が行う。"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
from numba import njit


@njit(cache=True)
def _minute_features(times, price, good, start, tick):
    """
    機能: 現在原行を含まない確定一分足から短ATR・EMA・直近五足の帯を作る。
    引数: times/price/good(ndarray)、start/tick(float)は開始時刻と観測呼値。
    返り値: ndarrayの九列はATR、EMA3/8/5/20、高5、安5、連続確定足数、最終足確定時刻。
    """
    result = np.full((len(times), 9), np.nan)
    highs = np.zeros(5)
    lows = np.zeros(5)
    trs = np.zeros(5)
    count = 0
    slot = -1
    high = -np.inf
    low = np.inf
    close = np.nan
    previous = np.nan
    ema3 = ema8 = ema5 = ema20 = np.nan
    closed_at = np.nan
    for i in range(len(times)):
        if times[i] < start:
            continue
        current = int(np.floor((times[i] - start) / 60.))
        if current != slot:
            if slot >= 0 and np.isfinite(close):
                tr = high - low
                if np.isfinite(previous):
                    tr = max(tr, abs(high - previous), abs(low - previous))
                index = count % 5
                highs[index] = high
                lows[index] = low
                trs[index] = tr
                if count == 0:
                    ema3 = ema8 = ema5 = ema20 = close
                else:
                    ema3 += .5 * (close - ema3)
                    ema8 += (2. / 9.) * (close - ema8)
                    ema5 += (2. / 6.) * (close - ema5)
                    ema20 += (2. / 21.) * (close - ema20)
                count += 1
                previous = close
                closed_at = start + (slot + 1) * 60.
            elif slot >= 0:
                count = 0
                previous = np.nan
                closed_at = np.nan
            if slot >= 0 and current - slot > 1:
                count = 0
                previous = np.nan
                closed_at = np.nan
            slot = current
            high = -np.inf
            low = np.inf
            close = np.nan

        # ----------------------------------------
        # 現行足の値を更新する前に、確定済みだけを現在の判断へ公開する。
        result[i, 7] = count
        result[i, 8] = closed_at
        if count >= 3:
            result[i, 0] = max(2. * tick, np.mean(trs[:min(count, 5)]))
        if count >= 5:
            result[i, 5] = np.max(highs)
            result[i, 6] = np.min(lows)
        if count >= 8:
            result[i, 1] = ema3
            result[i, 2] = ema8
        if count >= 20:
            result[i, 3] = ema5
            result[i, 4] = ema20
        if good[i]:
            high = max(high, price[i])
            low = min(low, price[i])
            close = price[i]
    return result


def _changes(times, price, atr, seconds):
    """
    機能: 観測窓の端より厳密に古い価格との差を、現在公開済みの短ATRで正規化する。
    引数: times/price/atr(ndarray)、seconds(float)は観測窓秒数。
    返り値: tuple[ndarray,ndarray]は正規化差と使用した過去価格の時刻。
    """
    index = np.searchsorted(times, times - seconds, side='left') - 1
    safe = np.maximum(index, 0)
    valid = (index >= 0) & (times - seconds - times[safe] <= 30.)
    valid &= np.isfinite(price) & np.isfinite(price[safe]) & np.isfinite(atr) & (atr > 0.)
    value = np.full(len(times), np.nan)
    source = np.full(len(times), np.nan)
    value[valid] = (price[valid] - price[safe[valid]]) / atr[valid]
    source[valid] = times[safe[valid]]
    return value, source


def _phase(ready):
    """
    機能: 既存の市場時計区分を値動きから独立に再現する。
    引数: ready(dict)はsession/time_s/us_openを持つ原行情報。
    返り値: ndarray[int64]は既存00137と同じ時間区分。
    """
    times = ready['time_s']
    date = datetime.fromisoformat(ready['session'].split('_')[0]).date()
    if ready['session'].endswith('_Day'):
        midnight = datetime.combine(date, time(), ZoneInfo('Asia/Tokyo')).timestamp()
        minutes = (times - midnight) / 60.
        return np.select([minutes < 540, minutes < 690, minutes < 750, minutes < 930],
                         [0, 1, 2, 3], default=4).astype(np.int64)
    start19 = datetime.combine(date, time(19), ZoneInfo('Asia/Tokyo')).timestamp()
    london = datetime.combine(date, time(16, 30), ZoneInfo('Europe/London')).timestamp()
    us = ready['us_open']
    return np.select([times < start19, times < us - 4500, times < us - 2700,
                      times < us - 900, times < us + 900, times < london],
                     [5, 6, 7, 8, 9, 10], default=11).astype(np.int64)


def prepare(packet):
    """
    機能: 一場の両市場に、未確定足を使わない早期判断資料を作る。
    引数: packet(dict)は既存形式のinputs/quotesを持つ一場分。
    返り値: dict[str,dict]は銘柄別の原行時刻、短ATR、二市場十二列、確定EMA等。
    """
    assert len(packet['inputs']) == 2
    assert len({key[0] for key in packet['inputs']}) == 1
    result = {}
    for key, ready in packet['inputs'].items():
        symbol = key[1]
        assert symbol in ('NK225', 'TOPIX')
        quotes = packet['quotes'][key]
        times = np.asarray(ready['time_s'], dtype=np.float64)
        good = np.asarray(quotes['quote_valid'], dtype=bool).copy()
        good &= np.isfinite(quotes['bid']) & np.isfinite(quotes['ask'])
        good &= (quotes['bid'] > 0.) & (quotes['ask'] > quotes['bid'])
        price = np.full(len(times), np.nan)
        price[good] = (quotes['bid'][good] + quotes['ask'][good]) * .5
        assert np.all(np.diff(times) >= 0.) and len(times) > 0
        start = float(ready['start'])
        raw = _minute_features(times, price, good, start, float(ready['tick']))
        day = ready['session'].endswith('_Day')
        until = start + 3600. if day else float(ready['us_open']) - 1200.
        end = start + 3900. if day else float(ready['us_open']) - 900.
        assert end > until > start
        result[symbol] = dict(time_s=times, atr=raw[:, 0], minute_features=raw,
                              closed_bars=raw[:, 7], phase=_phase(ready), price=price, quotes=quotes,
                              good=good, window_start=start, candidate_until=until, window_end=end)

    # ----------------------------------------
    # 相手市場の同時刻行を排除し、十五秒以内の既知行だけを接続する。
    changes = {symbol: {seconds: _changes(v['time_s'], v['price'], v['atr'], seconds)
                        for seconds in (30., 120.)} for symbol, v in result.items()}
    for symbol, ready in result.items():
        other_symbol = 'TOPIX' if symbol == 'NK225' else 'NK225'
        other = result[other_symbol]
        times, peer_times = ready['time_s'], other['time_s']
        index = np.searchsorted(peer_times, times, side='left') - 1
        safe = np.maximum(index, 0)
        valid = (index >= 0) & (times - peer_times[safe] <= 15.)
        valid &= ready['good'] & other['good'][safe]
        valid &= np.isfinite(ready['atr']) & np.isfinite(other['atr'][safe])
        market = np.full((len(times), 12), np.nan)
        market[:, 0] = ready['price']
        market[:, 2] = ready['atr']
        market[:, 4], market[:, 9] = changes[symbol][30.]
        market[:, 5] = changes[symbol][120.][0]
        for column, values in ((1, other['price']), (3, other['atr']),
                               (6, changes[other_symbol][30.][0]),
                               (7, changes[other_symbol][120.][0]),
                               (8, peer_times), (10, changes[other_symbol][30.][1])):
            market[valid, column] = values[safe[valid]]
        market[:, 11] = valid.astype(float)
        peer_features = np.full((len(times), 9), np.nan)
        peer_features[valid] = other['minute_features'][safe[valid]]
        ready['market'] = market
        ready['peer_minute_features'] = peer_features
    return result


@njit(cache=True)
def _candidates(times, bid, ask, good, price, atr, market, own_features, peer_features,
                phase, start, until, window_end, mechanism, threshold30, threshold120, hold,
                cooldown, retest_tolerance, retest_failure, breakout_pad, setup_timeout):
    """
    機能: 新しい支持成立又は突破後の戻り確認を、次の正常気配で候補新規へ変換する。
    引数: 原行配列(ndarray)、mechanism(int)、開始・終了・閾値・待機条件(float)。
    返り値: ndarrayは既存形式の十二列新規通知だけ。返済と他候補の採否は呼出側で決める。
    """
    out = np.zeros((int((until - start) / max(1., cooldown)) + 5, 12))
    count = 0
    pending = -1
    pending_side = 0
    last_candidate = -np.inf
    signal_side = 0
    since = -np.inf
    consumed = False
    state = 0
    setup_side = 0
    band = 0.
    setup_start = -np.inf
    previous_price = np.nan
    for i in range(len(times)):
        if times[i] < start:
            continue
        if times[i] >= window_end:
            break
        if pending >= 0 and i > pending and good[i]:
            fill = ask[i] if pending_side > 0 else bid[i]
            assert count < len(out)
            out[count] = np.array([i, pending, count + 1, pending_side, 5, fill,
                                   13910 + mechanism, 1, 0, times[i], times[pending], phase[pending]])
            count += 1
            pending = -1
        # 発注判断の期限を過ぎても、発注済み候補は返済予定時刻より前の次正常気配へ渡す。
        if times[i] >= until:
            continue
        gap = i > 0 and times[i] - times[i - 1] > 15.
        if not good[i] or gap:
            signal_side = 0
            since = -np.inf
            consumed = False
            state = 0
            previous_price = np.nan
            if not good[i]:
                continue
        common = 0
        if market[i, 11] == 1.:
            if market[i, 4] >= threshold30 and market[i, 6] >= threshold30 and market[i, 5] >= threshold120 and market[i, 7] >= threshold120:
                common = 1
            elif market[i, 4] <= -threshold30 and market[i, 6] <= -threshold30 and market[i, 5] <= -threshold120 and market[i, 7] <= -threshold120:
                common = -1
        signal = common
        if mechanism == 1 or mechanism == 2:
            fast = 1 if mechanism == 1 else 3
            slow = fast + 1
            if common == 0 or not (common * (own_features[i, fast] - own_features[i, slow]) > 0.
                                   and common * (peer_features[i, fast] - peer_features[i, slow]) > 0.):
                signal = 0
        elif mechanism == 3:
            signal = 0
            if state and (times[i] - setup_start > setup_timeout or setup_side * (price[i] - band) < -retest_failure * atr[i]):
                state = 0
            if state == 0:
                upper, lower = own_features[i, 5], own_features[i, 6]
                if common == 1 and np.isfinite(previous_price) and previous_price <= upper and price[i] > upper:
                    state = 1
                    setup_side = 1
                    band = upper
                    setup_start = times[i]
                elif common == -1 and np.isfinite(previous_price) and previous_price >= lower and price[i] < lower:
                    state = 1
                    setup_side = -1
                    band = lower
                    setup_start = times[i]
            elif state == 1:
                if setup_side * (price[i] - band) <= retest_tolerance * atr[i]:
                    state = 2
            elif state == 2:
                # 戻り許容帯の外へ再進行した場合だけを再突破とする。帯内の横ばいを数えない。
                if common == setup_side and setup_side * (price[i] - band) >= (retest_tolerance + breakout_pad) * atr[i]:
                    signal = setup_side

        # ----------------------------------------
        # 一度成立した支持を継続中に繰り返し数えない。休止中の成立も消費する。
        if signal != signal_side:
            signal_side = signal
            since = times[i] if signal else -np.inf
            consumed = False
        if signal and not consumed and times[i] - since >= hold:
            consumed = True
            if times[i] - last_candidate >= cooldown and pending < 0:
                pending = i
                pending_side = signal
                last_candidate = times[i]
            if mechanism == 3:
                state = 0
        previous_price = price[i]
    return out[:count]


def candidates(prepared, config):
    """
    機能: 再利用可能な早期特徴へ固定条件を適用し、新規候補通知を付加する。
    引数: prepared(dict)はprepareの返り値、config(dict)はmechanism・threshold30/120・hold・cooldown等。
    返り値: dict[str,dict]は特徴配列を共有し、core_candidatesだけを新しく持つ。
    """
    kinds = {'support': 0, 'ema38': 1, 'ema520': 2, 'retest': 3}
    mechanism = kinds[config.get('mechanism', 'support')]
    threshold30 = float(config.get('threshold30', .05))
    threshold120 = float(config.get('threshold120', .2))
    hold = float(config.get('hold', 15.))
    cooldown = float(config.get('cooldown', 300.))
    assert threshold30 > 0. and threshold120 > 0. and hold >= 0. and cooldown >= 30.
    result = {}
    for symbol, ready in prepared.items():
        quotes = ready['quotes']
        orders = _candidates(ready['time_s'], quotes['bid'], quotes['ask'], ready['good'],
                             ready['price'], ready['atr'], ready['market'], ready['minute_features'],
                             ready['peer_minute_features'], ready['phase'], ready['window_start'],
                             ready['candidate_until'], ready['window_end'], mechanism, threshold30, threshold120, hold, cooldown,
                             float(config.get('retest_tolerance', .25)), float(config.get('retest_failure', .5)),
                             float(config.get('breakout_pad', .1)), float(config.get('setup_timeout', 600.)))
        result[symbol] = dict(ready, core_candidates=orders)
    return result


def build(packet, config):
    """
    機能: 保存済み一場の原行から、確定足だけを使う早期候補を一括生成する。
    引数: packet(dict)は既存入力、config(dict)は事前固定した候補条件。
    返り値: dict[str,dict]は短ATR・二市場特徴・新規候補・早期窓終端。
    """
    return candidates(prepare(packet), config)
