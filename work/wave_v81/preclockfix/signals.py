"""既読の価格転換と板更新イベントから、保有時間を指定しない方向状態を作る。"""
from pathlib import Path
import numba
import numpy as np
from numba import njit


HERE = Path(__file__).resolve().parent
numba.config.CACHE_DIR = str(HERE / 'prepared/numba_cache')
TURN_TICKS = (1, 2, 4, 8)
SPANS = (8, 32, 128)
THRESHOLDS = (.15, .30)
COMBINATIONS = ((2, 32, .15), (4, 32, .15), (4, 128, .30))
MODELS = ([dict(id=f'D1_K{k:02d}', family='価格転換', ticks=k) for k in TURN_TICKS]
          + [dict(id=f'D2_N{n:03d}_T{int(round(t*100)):02d}', family='板フロー', span=n, threshold=t)
             for n in SPANS for t in THRESHOLDS]
          + [dict(id=f'D3_K{k:02d}_N{n:03d}_T{int(round(t*100)):02d}', family='価格と板の一致', ticks=k, span=n, threshold=t)
             for k, n, t in COMBINATIONS])


@njit(cache=True)
def event_features(times, bid, ask, bid_qty, ask_qty, usable, resets, tick):
    """
    機能: 各既読原板行を処理し、価格反転・非ゼロOFIイベントEMAを更新する。
    引数: times/bid/ask/bid_qty/ask_qty (ndarray)、usable/resets (bool ndarray)、tick (float)。
    返り値: tuple の方向・極値・反転行・正規化OFI・準備数・最終更新行等。
    """
    size = len(times)
    directions = np.zeros((4, size), np.int8)
    extremes = np.full((4, size), np.nan, np.float32)
    turn_rows = np.full((4, size), -1, np.int32)
    flow = np.full((3, size), np.nan, np.float32)
    flow_counts = np.zeros(size, np.int32)
    last_flow_rows = np.full(size, -1, np.int32)
    last_quote_rows = np.full(size, -1, np.int32)
    raw_ofi = np.full(size, np.nan, np.float32)
    reset_event = np.zeros(size, np.bool_)
    anchor = 0.
    direction = np.zeros(4, np.int8)
    extreme = np.zeros(4)
    turn_at = np.full(4, -1, np.int32)
    numerator = np.zeros(3); denominator = np.zeros(3)
    alphas = np.array([2./9., 2./33., 2./129.])
    widths = np.array([1., 2., 4., 8.]) * tick
    count = 0; previous = -1; last_flow = -1; last_quote = -1
    for i in range(size):
        gap = i > 0 and times[i] - times[i-1] > 10.
        if not usable[i] or resets[i] or gap:
            direction[:] = 0; turn_at[:] = -1
            numerator[:] = 0.; denominator[:] = 0.
            count = 0; previous = -1; last_flow = -1; last_quote = -1
            reset_event[i] = True
        if not usable[i] or resets[i]:
            continue
        mid = (bid[i]+ask[i]) / 2.
        if previous < 0:
            anchor = mid; extreme[:] = mid
            previous = i; last_quote = i
        else:
            changed = (bid[i] != bid[previous] or ask[i] != ask[previous]
                       or bid_qty[i] != bid_qty[previous] or ask_qty[i] != ask_qty[previous])
            if changed:
                last_quote = i
                e = 0.
                if bid[i] >= bid[previous]: e += bid_qty[i]
                if bid[i] <= bid[previous]: e -= bid_qty[previous]
                if ask[i] <= ask[previous]: e -= ask_qty[i]
                if ask[i] >= ask[previous]: e += ask_qty[previous]
                raw_ofi[i] = e
                if e != 0.:
                    count += 1; last_flow = i
                    for s in range(3):
                        numerator[s] = (1.-alphas[s])*numerator[s] + alphas[s]*e
                        denominator[s] = (1.-alphas[s])*denominator[s] + alphas[s]*abs(e)
                for k in range(4):
                    if direction[k] == 0:
                        if mid-anchor >= widths[k]-1e-8:
                            direction[k] = 1; extreme[k] = mid; turn_at[k] = i
                        elif anchor-mid >= widths[k]-1e-8:
                            direction[k] = -1; extreme[k] = mid; turn_at[k] = i
                    elif direction[k] == 1:
                        if mid > extreme[k]: extreme[k] = mid
                        if extreme[k]-mid >= widths[k]-1e-8:
                            direction[k] = -1; extreme[k] = mid; turn_at[k] = i
                    else:
                        if mid < extreme[k]: extreme[k] = mid
                        if mid-extreme[k] >= widths[k]-1e-8:
                            direction[k] = 1; extreme[k] = mid; turn_at[k] = i
            else:
                raw_ofi[i] = 0.
            previous = i
        for k in range(4):
            directions[k, i] = direction[k]
            extremes[k, i] = extreme[k]
            turn_rows[k, i] = turn_at[k]
        for s in range(3):
            if denominator[s] > 0.:
                flow[s, i] = numerator[s]/denominator[s]
        flow_counts[i] = count
        last_flow_rows[i] = last_flow
        last_quote_rows[i] = last_quote
    return directions, extremes, turn_rows, flow, flow_counts, last_flow_rows, last_quote_rows, raw_ofi, reset_event


# ----------------------------------------
def market_features(ready, book):
    """
    機能: 一市場の全原板行について13種類の方向と有効性を作る。
    引数: ready/book (dict) は時計・原本対応と保存済み気配。
    返り値: dict。時間窓・固定保有時間・利確価格・将来損益は使用しない。
    """
    times = ready['time_s']; tick = float(ready['tick'])
    assert len(times) and np.all(np.diff(times) >= 0)
    assert np.array_equal(times, book['time_s']) and np.array_equal(ready['seq'], book['seq'])
    bid, ask, bq, aq = (book[k] for k in ('bid', 'ask', 'bid_qty', 'ask_qty'))
    usable = (book['valid'] & np.isfinite(bid) & np.isfinite(ask) & np.isfinite(bq) & np.isfinite(aq)
              & (bid > 0) & (ask > bid) & (ask-bid <= tick+1e-8) & (bq > 0) & (aq > 0))
    price_valid = usable & ~book['reset']
    direction, extreme, turns, flow, count, last_flow, last_quote, raw_ofi, resets = event_features(
        times, bid, ask, bq, aq, usable, book['reset'], tick)
    states = np.zeros((len(MODELS), len(times)), np.int8)
    valid = np.zeros_like(states, dtype=np.bool_)
    states[:4] = direction
    valid[:4] = price_valid
    for s, span in enumerate(SPANS):
        sufficient = price_valid & (count >= span) & np.isfinite(flow[s])
        for t, threshold in enumerate(THRESHOLDS):
            model = 4+s*2+t
            states[model, sufficient & (flow[s] >= np.float32(threshold))] = 1
            states[model, sufficient & (flow[s] <= -np.float32(threshold))] = -1
            valid[model] = sufficient
    for i, (width, span, threshold) in enumerate(COMBINATIONS):
        turn_model = TURN_TICKS.index(width)
        flow_model = 4+SPANS.index(span)*2+THRESHOLDS.index(threshold)
        sufficient = valid[turn_model] & valid[flow_model]
        agree = sufficient & (states[turn_model] == states[flow_model])
        states[10+i, agree] = states[turn_model, agree]
        valid[10+i] = sufficient
    return dict(time_s=times, states=states, valid=valid, price_valid=price_valid,
                bid=bid.astype(np.float32), ask=ask.astype(np.float32), bid_qty=bq.astype(np.float32), ask_qty=aq.astype(np.float32),
                flow=flow, flow_count=count, last_flow_update=last_flow, last_quote_update=last_quote,
                turn_extreme=extreme, last_price_turn=turns, raw_ofi=raw_ofi, reset_event=resets, tick=tick)


# ----------------------------------------
def strict_peer_sources(targets, peer_times):
    """
    機能: 相手市場だけを自己現在時計より厳密過去の最新時計先頭へ対応させる。
    引数: targets/peer_times (ndarray) は両市場の代理時計。
    返り値: tuple(ndarray, ndarray) の相手行・古さ。欠測は−1とNaN、古い良板へ遡らない。
    """
    source = np.searchsorted(peer_times, targets, side='left')-1
    source = source.astype(np.int32)
    known = source >= 0
    source[known] = np.searchsorted(peer_times, peer_times[source[known]], side='left')
    age = np.full(len(targets), np.nan, np.float32)
    age[known] = targets[known]-peer_times[source[known]]
    return source, age


# ----------------------------------------
def project(self_frame, peer_frame):
    """
    機能: 自己原板の各行へ双方の状態を写し、欠測と方向不一致を区別する。
    引数: self_frame/peer_frame (dict) は市場別の逐次特徴。
    返り値: dict の自己現在行・相手過去行・方向・有効性・診断系列。
    """
    times = self_frame['time_s']; size = len(times)
    source, age = strict_peer_sources(times, peer_frame['time_s'])
    safe = np.maximum(source, 0)
    fresh = (source >= 0) & (age > 0.) & (age <= 10.)
    peer_valid = peer_frame['valid'][:, safe] & fresh
    self_valid = self_frame['valid']
    both_valid = self_valid & peer_valid
    peer_states = peer_frame['states'][:, safe].copy()
    peer_states[~peer_valid] = 0
    common = np.where(both_valid & (self_frame['states'] == peer_states), peer_states, 0).astype(np.int8)
    peer_time = peer_frame['time_s'][safe].copy(); peer_time[source < 0] = np.nan
    out = dict(time_s=times, source_self=np.arange(size, dtype=np.int32), source_peer=source,
               time_self=times, time_peer=peer_time, age_self=np.zeros(size, np.float32), age_peer=age,
               states_self=self_frame['states'], states_peer=peer_states, states=common,
               valid_self=self_valid, valid_peer=peer_valid, valid=both_valid,
               price_valid_self=self_frame['price_valid'], price_valid_peer=peer_frame['price_valid'][safe] & fresh,
               price_valid=self_frame['price_valid'] & peer_frame['price_valid'][safe] & fresh,
               tick=self_frame['tick'], tick_peer=peer_frame['tick'])
    for name in ('bid', 'ask', 'bid_qty', 'ask_qty'):
        out[name] = self_frame[name]
        peer_value = peer_frame[name][safe].copy(); peer_value[source < 0] = np.nan
        out[name+'_peer'] = peer_value
    for name in ('flow', 'flow_count', 'last_flow_update', 'last_quote_update', 'turn_extreme', 'last_price_turn', 'raw_ofi', 'reset_event'):
        out[name+'_self'] = self_frame[name]
        values = peer_frame[name]
        sampled = values[:, safe].copy() if values.ndim == 2 else values[safe].copy()
        missing = source < 0
        replacement = False if values.dtype.kind == 'b' else np.nan if values.dtype.kind == 'f' else -1
        if values.ndim == 2: sampled[:, missing] = replacement
        else: sampled[missing] = replacement
        out[name+'_peer'] = sampled
    return out


# ----------------------------------------
def build_session(ready, books, session):
    """
    機能: 一場の二市場を独立に逐次計算後、それぞれの原板行へ過去参照で接続する。
    引数: ready/books (dict)、session (str)。
    返り値: dict[(str,str),dict] の2口座の方向状態。
    """
    markets = {s: market_features(ready[(session,s)], books[(session,s)]) for s in ('TOPIX','NK225')}
    return {(session,s):project(markets[s],markets['NK225' if s=='TOPIX' else 'TOPIX']) for s in ('TOPIX','NK225')}
