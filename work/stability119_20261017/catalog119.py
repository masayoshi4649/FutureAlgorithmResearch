"""六つの既存仮説を三尺度で切り分け、未来を見ず新規事象と仮説撤回を作る。"""

import math

import numpy as np


SCALES = (10, 20, 40)
TICKS = {'TOPIX': .5, 'NK225': 10.}
FAMILIES = (
    ('COMMON', '共同方向追従', '自身と厳密に過去の相手が、費用に比べ十分な幅を同じ方向へ進む。'),
    ('OPEN', '開始帯離脱', '場の最初の固定時間帯を観測し、その外へ確定価格と現在値が進む。'),
    ('CENTER', '加重価格への戻り', '安定した公表出来高加重価格からの乖離が、進行停止後に戻り始める。'),
    ('FAIL', '失敗離脱', '過去帯を一度越えた確定足が帯内へ戻り、公開現在値も戻り側を維持する。'),
    ('LAG', '二市場遅行追随', '相手の持続的な進行に対し、まだ進行の小さい自身が追随し始める。'),
    ('GAP', '前セッション乖離解消', '前場の最終採用Lastとの乖離が残り、当場価格がその方向へ戻り始める。'))


# ----------------------------------------


def inspect_bars(bars: dict) -> int:
    """
    機能: 118型分足の最低限の型・順序・公開資格を確認する。
    引数: bars(dict[str,ndarray]) は当該商品の分足。
    返り値: int は全minutegridの長さ。原価格を補完しない。
    """
    required = ('t_s', 'open', 'high', 'low', 'close', 'volume', 'volume_known',
                'valid', 'anchor', 'pub_raw_row', 'pub_price_time_s')
    n = len(bars['t_s'])
    for key in required:
        assert isinstance(bars[key], np.ndarray) and bars[key].shape == (n,), key
    assert bars['valid'].dtype == bars['volume_known'].dtype == np.bool_
    assert bars['pub_raw_row'].dtype == np.int64
    assert np.isfinite(bars['t_s']).all() and np.all(np.diff(bars['t_s']) == 60)
    valid = bars['valid']
    for key in ('open', 'high', 'low', 'close'):
        assert np.isfinite(bars[key][valid]).all() and np.all(bars[key][valid] > 0), key
    assert np.all(bars['low'][valid] <= bars['high'][valid])
    assert np.all(bars['low'][valid] <= bars['open'][valid]) and np.all(bars['open'][valid] <= bars['high'][valid])
    assert np.all(bars['low'][valid] <= bars['close'][valid]) and np.all(bars['close'][valid] <= bars['high'][valid])
    pub = valid & np.isfinite(bars['anchor']) & (bars['pub_raw_row'] >= 0) & np.isfinite(bars['pub_price_time_s'])
    assert np.all(bars['anchor'][pub] > 0) and np.all(bars['pub_price_time_s'][pub] >= bars['t_s'][pub])
    assert np.all(np.diff(bars['pub_price_time_s'][pub]) >= 0) and np.all(np.diff(bars['pub_raw_row'][pub]) >= 0)
    return n


def runs(valid: np.ndarray) -> np.ndarray:
    """
    機能: 直近から連続した正常価格足の本数を求める。
    引数: valid(ndarray[bool]) は足の価格資格。
    返り値: ndarray[int64] は連続本数。空足で0へ戻す。
    """
    result = np.zeros(len(valid), np.int64)
    for i in range(len(valid)):
        result[i] = (result[i - 1] + 1 if i else 1) if valid[i] else 0
    return result


def historical(bars: dict, length: int, tick: float) -> dict:
    """
    機能: 既に確定した自身の価格窓だけで幅・方向・中心・過去帯を作る。
    引数: bars(dict)、length(int)、tick(float) は分足・尺度・観測呼値。
    返り値: dict[str,ndarray] は未知をNaNで保つ過去特徴。未来足を参照しない。
    """
    n = len(bars['close'])
    out = {key: np.full(n, np.nan) for key in ('width', 'delta', 'short', 'mean', 'efficiency',
        'prior_high', 'prior_low', 'weighted', 'weighted_change', 'opening_high', 'opening_low')}
    close, valid = bars['close'], bars['valid']
    run = runs(valid)
    weighted = out['weighted']
    volume_valid = valid & bars['volume_known'] & np.isfinite(bars['volume']) & (bars['volume'] >= 0)
    volume_run = runs(volume_valid)
    for i in range(n):
        if run[i] >= length + 1:
            section = close[i - length:i + 1]
            changes = np.abs(np.diff(section))
            out['width'][i] = max(5 * tick, close[i] * .0005, float(np.median(changes)) * math.sqrt(length) * 2)
            out['delta'][i] = close[i] - close[i - length]
            out['mean'][i] = float(np.mean(close[i - length + 1:i + 1]))
            total = float(np.sum(changes))
            if total > 0:
                out['efficiency'][i] = abs(out['delta'][i]) / total
            out['prior_high'][i] = float(np.max(bars['high'][i - length:i]))
            out['prior_low'][i] = float(np.min(bars['low'][i - length:i]))
        if run[i] >= 4:
            out['short'][i] = close[i] - close[i - 3]
        if volume_run[i] >= length:
            quantities = bars['volume'][i - length + 1:i + 1]
            total = float(np.sum(quantities))
            if total > 0 and math.isfinite(total):
                weighted[i] = float(np.dot(close[i - length + 1:i + 1], quantities / total))
                if i > 0 and math.isfinite(weighted[i - 1]):
                    out['weighted_change'][i] = weighted[i] - weighted[i - 1]
        if i >= length and bool(np.all(valid[:length])):
            out['opening_high'][i] = float(np.max(bars['high'][:length]))
            out['opening_low'][i] = float(np.min(bars['low'][:length]))
    return out


def peer_index(own: dict, peer: dict) -> np.ndarray:
    """
    機能: 自己より1分以上前かつ自己公開価格時計以前に公開済みの相手足だけを選ぶ。
    引数: own/peer(dict) は自己と相手の118型分足。
    返り値: ndarray[int64] は相手足の位置又は−1。実受信順の証明ではない。
    """
    result = np.full(len(own['t_s']), -1, np.int64)
    candidates = np.flatnonzero(peer['valid'] & np.isfinite(peer['anchor']) & (peer['pub_raw_row'] >= 0) & np.isfinite(peer['pub_price_time_s']))
    if not len(candidates):
        return result
    times, published = peer['t_s'][candidates], peer['pub_price_time_s'][candidates]
    for i in np.flatnonzero(own['valid'] & np.isfinite(own['anchor']) & (own['pub_raw_row'] >= 0) & np.isfinite(own['pub_price_time_s'])):
        by_time = int(np.searchsorted(times, own['t_s'][i] - 60, side='right'))
        by_publication = int(np.searchsorted(published, own['pub_price_time_s'][i], side='right'))
        position = min(by_time, by_publication) - 1
        if position >= 0:
            result[i] = candidates[position]
    return result


def publish(long: np.ndarray, short: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """
    機能: 当時条件が同じ方向へ新たに成立した行だけを新規事象にする。
    引数: long/short/valid(ndarray[bool]) は方向条件と新規判定資格。
    返り値: ndarray[int8] は買1・売−1・新事象なし0。0を返済指示にしない。
    """
    state = np.zeros(len(valid), np.int8)
    state[valid & long & ~short] = 1
    state[valid & short & ~long] = -1
    previous = np.concatenate(([0], state[:-1])) if len(state) else state.copy()
    return np.where(state != previous, state, 0).astype(np.int8)


# ----------------------------------------


def build(own: dict, peer: dict, symbol: str, previous_close: float | None) -> dict:
    """
    機能: 六family×三尺度の新規・仮説撤回・価格リスク幅を当時情報だけで作る。
    引数: own/peer(dict) は118型自己/相手足、symbol(str) はTOPIX/NK225、
          previous_close(float|None) は直前保存場の最終採用Last。公式終値ではない。
    返り値: dict はspecsとentry(int8[K,N])、exit_long/exit_short/valid(bool[K,N])、width(float64[K,N])。
    validは新規の情報資格。exitはそれと独立した具体的撤回で、欠測やentry0だけでは退出しない。
    """
    assert symbol in TICKS
    n = inspect_bars(own)
    inspect_bars(peer)
    tick = TICKS[symbol]
    other_symbol = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    anchor, close, high, low = (own[key] for key in ('anchor', 'close', 'high', 'low'))
    available = own['valid'] & np.isfinite(anchor) & (anchor > 0) & (own['pub_raw_row'] >= 0) & np.isfinite(own['pub_price_time_s'])
    indexes = peer_index(own, peer)
    first = np.flatnonzero(own['valid'])
    first_open = float(own['open'][first[0]]) if len(first) else math.nan
    previous_known = (isinstance(previous_close, (int, float, np.integer, np.floating))
                      and not isinstance(previous_close, (bool, np.bool_)) and math.isfinite(previous_close) and previous_close > 0)
    gap = first_open - float(previous_close) if previous_known and math.isfinite(first_open) else math.nan
    own_history = {length: historical(own, length, tick) for length in SCALES}
    peer_history = {length: historical(peer, length, TICKS[other_symbol]) for length in SCALES}
    specifications, entries, long_exits, short_exits, widths, valids = [], [], [], [], [], []
    for family, name, thought in FAMILIES:
        for length in SCALES:
            hist = own_history[length]
            other = peer_history[length]
            width, delta, short, mean, efficiency = (hist[key] for key in ('width', 'delta', 'short', 'mean', 'efficiency'))
            pdelta, pwidth, peff = (np.full(n, np.nan) for _ in range(3))
            matched = indexes >= 0
            pdelta[matched] = other['delta'][indexes[matched]]
            pwidth[matched] = other['width'][indexes[matched]]
            peff[matched] = other['efficiency'][indexes[matched]]
            valid = available & np.isfinite(width) & (width > 0)
            long = np.zeros(n, np.bool_)
            short_side = long.copy()
            exit_long = long.copy()
            exit_short = long.copy()
            if family == 'COMMON':
                valid &= np.isfinite(efficiency) & np.isfinite(pdelta) & np.isfinite(pwidth) & np.isfinite(peff)
                long = (delta >= .75 * width) & (efficiency >= .35) & (pdelta >= .75 * pwidth) & (peff >= .25) & (anchor > mean)
                short_side = (delta <= -.75 * width) & (efficiency >= .35) & (pdelta <= -.75 * pwidth) & (peff >= .25) & (anchor < mean)
                exit_long = available & np.isfinite(mean) & (anchor <= mean - .5 * width)
                exit_short = available & np.isfinite(mean) & (anchor >= mean + .5 * width)
                rule = '自他のL分変化>=各0.75幅、経路効率が自己.35/相手.25以上、公開Lastが自己L分平均の同方向側。退出は自己平均の反対.5幅へ到達。'
                difference = '00071共同追従と00118の対照系統。現在票・小利益終了は使わず、幅を一意化して実quote費用を別に測る。新しい独立収益源と断定しない。'
            elif family == 'OPEN':
                upper, lower = hist['opening_high'], hist['opening_low']
                valid &= np.isfinite(upper) & np.isfinite(lower)
                long = (close > upper + tick) & (anchor > upper + tick)
                short_side = (close < lower - tick) & (anchor < lower - tick)
                exit_long = available & np.isfinite(upper) & (anchor < upper - tick)
                exit_short = available & np.isfinite(lower) & (anchor > lower + tick)
                rule = '最初L本の全価格足が正常な場合だけ、その高安を固定。以後closeと公開Lastが帯外1観測tick超。退出は抜けた側境界から帯内1tick超へ戻る。'
                difference = '00118 B03の開始帯系統の対照。固定15分からL10/20/40へ一般化し、価格方向採点でなく実出口/全場会計へ接続する。'
            elif family == 'CENTER':
                center, change = hist['weighted'], hist['weighted_change']
                previous_center = np.concatenate(([np.nan], center[:-1])) if n else center.copy()
                previous_width = np.concatenate(([np.nan], width[:-1])) if n else width.copy()
                previous_price = np.concatenate(([np.nan], close[:-1])) if n else close.copy()
                valid &= np.isfinite(center) & np.isfinite(change) & np.isfinite(previous_center) & np.isfinite(previous_width) & np.isfinite(efficiency)
                stable = (np.abs(change) <= .25 * width) & (efficiency <= .45)
                long = stable & (previous_price <= previous_center - previous_width) & (close > previous_price) & (anchor <= center - .5 * width)
                short_side = stable & (previous_price >= previous_center + previous_width) & (close < previous_price) & (anchor >= center + .5 * width)
                exit_long = available & np.isfinite(center) & ((anchor >= center) | (change <= -.5 * width))
                exit_short = available & np.isfinite(center) & ((anchor <= center) | (change >= .5 * width))
                rule = 'L連続のvolume_known足でclose×公表volume近似中心。前closeは中心から1幅以上乖離、現在closeが反転、公開Lastも中心から.5幅以上。中心変化<=.25幅・効率<=.45。退出は現在中心へ到達又は中心が不利.5幅移動。'
                difference = '既存平均回帰の対照。真VWAP・残存建玉の平均原価ではない。中心は現在のローリング値であり入口固定目標と異なる。量未知はこの族だけ未知。'
            elif family == 'FAIL':
                upper, lower = hist['prior_high'], hist['prior_low']
                middle = (upper + lower) / 2
                valid &= np.isfinite(upper) & np.isfinite(lower) & (upper > lower)
                long = (low < lower - tick) & (close > lower) & (anchor > lower)
                short_side = (high > upper + tick) & (close < upper) & (anchor < upper)
                both = long & short_side
                long[both] = False
                short_side[both] = False
                exit_long = available & np.isfinite(middle) & ((anchor >= middle) | (anchor < lower - tick))
                exit_short = available & np.isfinite(middle) & ((anchor <= middle) | (anchor > upper + tick))
                rule = '現足を含めない過去L高安を1tick超だけ外へ破り、確定closeと公開Lastが帯内へ戻った側へ。両端を同時に破る曖昧行は見送り。退出は現在過去帯の中点到達又は反対端の再突破。'
                difference = '旧C03と00118 R01の失敗離脱の対照。既に失敗した系統でもあり、板代理を外した価格反応と実quote費用で再点検する。未発見の必勝反転とはしない。'
            elif family == 'LAG':
                valid &= np.isfinite(pdelta) & np.isfinite(pwidth) & np.isfinite(peff) & np.isfinite(short)
                long = (pdelta >= pwidth) & (peff >= .4) & (delta >= -.25 * width) & (delta <= .5 * width) & (short >= tick) & (anchor > close - .25 * width)
                short_side = (pdelta <= -pwidth) & (peff >= .4) & (delta <= .25 * width) & (delta >= -.5 * width) & (short <= -tick) & (anchor < close + .25 * width)
                exit_long = available & np.isfinite(short) & ((short <= -.5 * width) | ((pdelta <= -.5 * pwidth) & (short < 0)))
                exit_short = available & np.isfinite(short) & ((short >= .5 * width) | ((pdelta >= .5 * pwidth) & (short > 0)))
                rule = '相手L変化>=1幅・効率>=.4、自身L変化は−.25～+.5幅で遅れ、直近3分が相手方向へ1tick以上。退出は自己3分が反対.5幅又は相手が反対.5幅で自己も反対。'
                difference = '00071先行追随と00118 M03の対照。共同追従とは自己のL変化範囲を分ける。相手は1分以上前かつ公開価格時計以前だけで、物理的先行を証明しない。'
            else:
                valid &= math.isfinite(gap)
                if math.isfinite(gap):
                    reference = float(previous_close)
                    if gap < 0:
                        long = (abs(gap) >= 2 * width) & (anchor < reference - .25 * width) & (short >= tick)
                    elif gap > 0:
                        short_side = (abs(gap) >= 2 * width) & (anchor > reference + .25 * width) & (short <= -tick)
                    exit_long = available & ((anchor >= reference) | (anchor < first_open - .5 * width))
                    exit_short = available & ((anchor <= reference) | (anchor > first_open + .5 * width))
                rule = '直前保存場の最終採用Lastと当場最初valid足openの差が2幅以上。乖離が.25幅以上残り、自己3分が前場価格へ1tick以上回復。退出は前場参照到達又は当場openから不利.5幅。'
                difference = '前場情報を用いる別参照の比較。前場参照は公式終値ではない。最初の保存場/NaN参照は無信号。過去の一日損益で採用日を決めない。'
            entry = publish(long, short_side, valid)
            specifications.append(dict(id=f'{family}_L{length:02d}', name=f'{name}・{length}分尺度', family=family,
                description=thought + ' ' + rule + ' 過去との差分：' + difference,
                scale=length, width_definition='max(観測5tick,当該確定close×0.0005,過去L価格差絶対値中央値×sqrt(L)×2)。L+1連続正常足。ATRではない。',
                neutral='entry0は新規事象なし。中立/欠測だけで返済しない。exit boolは保有仮説撤回として別判定。',
                reuse='系統は既存研究と重なる。金融前の全仕様照合・保存結果の再利用判定はrootで行う。'))
            entries.append(entry)
            long_exits.append(exit_long.astype(np.bool_))
            short_exits.append(exit_short.astype(np.bool_))
            widths.append(width.copy())
            valids.append(valid.astype(np.bool_))
    result = dict(specs=specifications, entry=np.asarray(entries, np.int8),
        exit_long=np.asarray(long_exits, np.bool_), exit_short=np.asarray(short_exits, np.bool_),
        width=np.asarray(widths, np.float64), valid=np.asarray(valids, np.bool_))
    assert len(result['specs']) == len(FAMILIES) * len(SCALES) == 18
    for name in ('entry', 'exit_long', 'exit_short', 'width', 'valid'):
        assert result[name].shape == (18, n)
    assert np.isin(result['entry'], (-1, 0, 1)).all()
    assert not np.any((result['entry'] != 0) & ~result['valid'])
    assert np.isfinite(result['width'][result['valid']]).all() and np.all(result['width'][result['valid']] > 0)
    return result
