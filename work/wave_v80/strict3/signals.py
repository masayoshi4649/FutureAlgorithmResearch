"""保存板の厳密過去だけから、秒単位の八つの入口状態を作る。"""
from pathlib import Path
import numba
import numpy as np
from numba import njit


HERE = Path(__file__).resolve().parent
numba.config.CACHE_DIR = str(HERE / 'numba_cache')
FAMILIES = ('S1_単独OFI先行', 'S2_二市場OFI先行', 'S3_共同価格追随', 'S4_先行追随',
            'S5_押し戻し後フロー反転', 'S6_失速逆張', 'S7_同価格表示回復', 'S8_無方向交互')


def asof(targets, times, endpoint, reset):
    """
    機能: 期限より厳密過去の最新時計の先頭行を採用する。
    引数: targets/times (ndarray)、endpoint/reset (bool ndarray)。
    返り値: tuple(ndarray, ndarray) の行番号と期限からの古さ。3秒超は無効。
    """
    out = np.full(len(targets), -1, np.int32)
    age = np.full(len(targets), np.nan, np.float32)
    last = np.searchsorted(times, targets, side='left') - 1
    positions = np.flatnonzero(last >= 0)
    first = np.searchsorted(times, times[last[positions]], side='left')
    elapsed = targets[positions] - times[first]
    good = endpoint[first] & ~reset[first] & (elapsed > 0) & (elapsed <= 3.)
    out[positions[good]] = first[good]
    age[positions[good]] = elapsed[good]
    return out, age


# ----------------------------------------
@njit(cache=True)
def ranges_and_recovery(times, mid, bid, ask, bq, aq, valid, reset, now, old10, old30):
    """
    機能: 既往二窓の高安と、同一最良価格の表示数量減少後回復を求める。
    引数: 原本の時刻/気配/数量/品質と現在・過去の参照行 (ndarray)。
    返り値: ndarray 六系列。数量回復は成行約定や補充の原因を断定しない。
    """
    size = len(now)
    older_high = np.full(size, np.nan)
    older_low = older_high.copy()
    recent_high = older_high.copy()
    recent_low = older_high.copy()
    bid_recovered = np.zeros(size, np.bool_)
    ask_recovered = np.zeros(size, np.bool_)
    for g in range(size):
        n, a, b = now[g], old10[g], old30[g]
        if n < 0 or a < 0 or b < 0 or not b < a < n:
            continue
        hi, lo = -np.inf, np.inf
        for j in range(b, a + 1):
            hi = max(hi, mid[j]); lo = min(lo, mid[j])
        older_high[g], older_low[g] = hi, lo
        hi, lo = -np.inf, np.inf
        for j in range(a + 1, n + 1):
            hi = max(hi, mid[j]); lo = min(lo, mid[j])
        recent_high[g], recent_low[g] = hi, lo
        for side in range(2):
            prices, quantity = (bid, bq) if side == 0 else (ask, aq)
            left = n
            while left > a and prices[left - 1] == prices[n] and valid[left - 1] and not reset[left]:
                left -= 1
            peak = 0.
            reduced = False
            recovered = False
            for j in range(left, n + 1):
                q = quantity[j]
                if not np.isfinite(q) or q <= 0 or not valid[j] or reset[j]:
                    peak, reduced, recovered = 0., False, False
                    continue
                if reduced and q >= .8 * peak:
                    recovered = True
                if q > peak:
                    peak = q
                    if not recovered:
                        reduced = False
                if peak > 0 and q <= .5 * peak:
                    reduced = True
                if recovered and q < .8 * peak:
                    recovered = False
            if side == 0:
                bid_recovered[g] = recovered
            else:
                ask_recovered[g] = recovered
    return older_high, older_low, recent_high, recent_low, bid_recovered, ask_recovered


# ----------------------------------------
def market_features(grid, ready, book):
    """
    機能: 一市場の現在気配、10/30秒の過去価格と10秒OFIを作る。
    引数: grid (ndarray)、ready/book (dict) は保存済みの準備情報。
    返り値: dict の参照行・特徴・有効性。ATRや未来損益は参照しない。
    """
    times, tick = ready['time_s'], float(ready['tick'])
    assert len(times) > 0 and np.all(np.diff(times) >= 0)
    assert np.array_equal(times, book['time_s']) and np.array_equal(ready['seq'], book['seq'])
    endpoint = book['valid'] & np.isfinite(book['bid']) & np.isfinite(book['ask'])
    endpoint &= (book['bid'] > 0) & (book['ask'] > book['bid'])
    endpoint &= (book['ask'] - book['bid'] <= tick + 1e-8)
    endpoint &= np.isfinite(book['bid_qty']) & np.isfinite(book['ask_qty'])
    endpoint &= (book['bid_qty'] > 0) & (book['ask_qty'] > 0)
    now, age = asof(grid - 1., times, endpoint, book['reset'])
    safe = np.maximum(now, 0)
    out = dict(source=now, age=age, source_seq=ready['seq'][safe].copy())
    out['source_seq'][now < 0] = -1
    for field in ('bid', 'ask', 'mid', 'bid_qty', 'ask_qty'):
        values = book[field][safe].astype(np.float32)
        values[now < 0] = np.nan
        out[field] = values
    out['time'] = times[safe].copy(); out['time'][now < 0] = np.nan
    out['spread'] = (out['ask'] - out['bid']) / tick
    out['imbalance'] = (out['bid_qty'] - out['ask_qty']) / (out['bid_qty'] + out['ask_qty'])
    broken = np.r_[0, np.cumsum(~book['valid'] | book['reset'], dtype=np.int64)]
    raw_ofi = book['best_ofi']; finite = np.isfinite(raw_ofi)
    cumulative = np.r_[0., np.cumsum(np.where(finite, raw_ofi, 0.))]
    absolute = np.r_[0., np.cumsum(np.where(finite, np.abs(raw_ofi), 0.))]
    missing = np.r_[0, np.cumsum(~finite, dtype=np.int64)]
    events = np.r_[0, np.cumsum(finite & (raw_ofi != 0), dtype=np.int64)]
    for window in (10, 30):
        old, old_age = asof(grid - 1. - window, times, endpoint, book['reset'])
        safe_old = np.maximum(old, 0)
        valid = (now >= 0) & (old >= 0) & (now > old)
        valid &= broken[safe + 1] == broken[safe_old + 1]
        ret = ((book['mid'][safe] - book['mid'][safe_old]) / tick).astype(np.float32)
        ret[~valid] = np.nan
        out[f'old{window}'] = old; out[f'old_age{window}'] = old_age
        out[f'valid{window}'] = valid; out[f'ret{window}'] = ret
        if window == 10:
            count = (events[safe + 1] - events[safe_old + 1]).astype(np.int32)
            total = cumulative[safe + 1] - cumulative[safe_old + 1]
            denominator = absolute[safe + 1] - absolute[safe_old + 1]
            known = valid & (missing[safe + 1] == missing[safe_old + 1])
            sufficient = known & (denominator > 0) & (count >= 3)
            ratio = np.full(len(grid), np.nan, np.float32)
            ratio[sufficient] = total[sufficient] / denominator[sufficient]
            count[~known] = 0
            out.update(flow10=ratio, flow_count10=count, flow_valid10=sufficient)
    out['valid'] = (now >= 0) & out['valid10'] & out['valid30']
    ranges = ranges_and_recovery(times, book['mid'], book['bid'], book['ask'], book['bid_qty'],
                                book['ask_qty'], book['valid'], book['reset'], now,
                                out['old10'], out['old30'])
    for field, value in zip(('older_high', 'older_low', 'recent_high', 'recent_low',
                             'bid_recovered', 'ask_recovered'), ranges):
        out[field] = value.astype(np.float32) if value.dtype.kind == 'f' else value
    out['tick'] = tick
    return out


# ----------------------------------------
@njit(cache=True)
def recent_flow_cross(grid, flow, valid):
    """
    機能: 有効なOFI比が非正から正、非負から負へ変化した後5秒を示す。
    引数: grid/flow (ndarray)、valid (bool ndarray)。
    返り値: int8 ndarray の直近の反転方向。欠測で反転履歴を捨てる。
    """
    out = np.zeros(len(grid), np.int8)
    previous = np.nan; direction = 0; began = -1e30
    for i in range(len(grid)):
        if not valid[i] or not np.isfinite(flow[i]):
            previous = np.nan; direction = 0; began = -1e30
            continue
        if np.isfinite(previous):
            if previous <= 0 and flow[i] > 0:
                direction, began = 1, grid[i]
            elif previous >= 0 and flow[i] < 0:
                direction, began = -1, grid[i]
        if direction * flow[i] > 0 and grid[i] - began <= 5.:
            out[i] = direction
        previous = flow[i]
    return out


# ----------------------------------------
@njit(cache=True)
def confirm(grid, raw, valid, self_source, peer_source, need_peer):
    """
    機能: 同方向の3秒持続と、開始後の原本参照更新を確認する。
    引数: grid/raw/valid/self_source/peer_source (ndarray)、need_peer (bool)。
    返り値: int8 ndarray の確認済み方向。欠測や方向変更で開始をやり直す。
    """
    out = np.zeros(len(grid), np.int8)
    start = -1; prior = 0
    for i in range(len(grid)):
        direction = raw[i]
        if not valid[i] or direction == 0:
            start, prior = -1, 0
            continue
        if start < 0 or direction != prior or (i > 0 and grid[i] - grid[i - 1] > 1.000001):
            start = i
        prior = direction
        updated = self_source[i] > self_source[start]
        if need_peer:
            updated = updated and peer_source[i] > peer_source[start]
        if updated and grid[i] - grid[start] >= 3.:
            out[i] = direction
    return out


# ----------------------------------------
def direction_states(grid, own, peer):
    """
    機能: 同じ価格品質条件の上に八入口を定義し、持続確認を加える。
    引数: grid (ndarray)、own/peer (dict) は同じ格子の市場特徴。
    返り値: dict。states は8×格子数のint8配列で、発注パルスではない。
    """
    valid = own['valid'] & peer['valid']
    raw = np.zeros((8, len(grid)), np.int8)
    f, p = own['flow10'], peer['flow10']
    a10, b10 = own['ret10'], peer['ret10']
    a30, b30 = own['ret30'], peer['ret30']
    cross = recent_flow_cross(grid, f, valid & own['flow_valid10'])
    for d in (-1, 1):
        raw[0, valid & (d*f >= .3) & (d*a10 >= 0) & (d*a10 <= 1)] = d
        raw[1, valid & (d*f >= .3) & (d*p >= .3) & (d*a10 >= 0) & (d*a10 <= 1) & (d*b10 >= 0)] = d
        raw[2, valid & (d*a10 >= 1) & (d*b10 >= 1) & (d*f >= .1) & (d*p >= .1)] = d
        raw[3, valid & (d*b10 >= 2) & (d*a10 >= 0) & (d*a10 <= 1) & (d*f >= .1) & (d*p >= .1)] = d
        raw[4, valid & (d*a30 >= 2) & (d*b30 >= 2) & (d*a10 >= -2) & (d*a10 <= -1)
            & (d*f >= .1) & (d*p >= 0) & (cross == d)] = d
        if d == -1:
            stalled = (own['recent_high'] <= own['older_high']) & (own['mid'] < own['older_high'])
        else:
            stalled = (own['recent_low'] >= own['older_low']) & (own['mid'] > own['older_low'])
        raw[5, valid & (-d*a30 >= 3) & stalled & (d*f >= .1) & (d*p >= 0)] = d
        recovered = own['bid_recovered'] if d == 1 else own['ask_recovered']
        raw[6, valid & recovered & (d*p >= .1) & (d*a10 >= -1) & (d*a10 <= 1)] = d
    # 無方向対照は価格・数量の符号を使わず、場開始基準の30秒ごとの交互方向とする。
    raw[7, valid] = np.where((np.floor((grid[valid] - grid[0]) / 30).astype(np.int64) % 2) == 0, 1, -1)
    states = np.stack([confirm(grid, raw[k], valid, own['source'], peer['source'], k != 0)
                       for k in range(8)])
    out = dict(grid=grid, states=states, raw_states=raw, valid=valid,
               source_self=own['source'], source_peer=peer['source'],
               bid=own['bid'], ask=own['ask'], bid_peer=peer['bid'], ask_peer=peer['ask'],
               imbalance=own['imbalance'], imbalance_peer=peer['imbalance'], tick=own['tick'])
    for label, market in (('self', own), ('peer', peer)):
        for name in ('time', 'age', 'source_seq', 'bid_qty', 'ask_qty', 'spread', 'flow10',
                     'flow_count10', 'flow_valid10', 'ret10', 'ret30', 'old10', 'old30',
                     'old_age10', 'old_age30', 'bid_recovered', 'ask_recovered'):
            target = f'{name[:-2]}_{label}10' if name.endswith('10') else f'{name[:-2]}_{label}30' if name.endswith('30') else f'{name}_{label}'
            out[target] = market[name]
    assert np.all(states[:, ~valid] == 0)
    return out


# ----------------------------------------
def build_session(ready, books, session):
    """
    機能: 一場を共通1秒格子で準備し、両商品の八入口を返す。
    引数: ready/books (dict)、session (str)。
    返り値: dict[(session, symbol), dict]。場開始60秒後から期限120秒前まで。
    """
    first = ready[(session, 'TOPIX')]
    grid = np.arange(first['start'] + 60., first['limit'] - 120. + 1e-8, 1.)
    markets = {}
    for symbol in ('TOPIX', 'NK225'):
        r = ready[(session, symbol)]
        assert (r['start'], r['limit']) == (first['start'], first['limit'])
        markets[symbol] = market_features(grid, r, books[(session, symbol)])
    return {(session, s): direction_states(grid, markets[s], markets[p])
            for s, p in (('TOPIX', 'NK225'), ('NK225', 'TOPIX'))}
