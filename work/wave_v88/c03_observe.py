"""旧52の観測採否を保持し、未来ラベル生成部分だけ除外した今回のコピー。"""
import numpy as np
import pandas as pd

def imbalance(up: float, down: float) -> float:
    """機能: 非負二量の方向差を総量で割り、無事象を欠測にする。

    引数: up/down(float)。返り値: 偏りまたはNaN(float)。
    """
    return (up - down) / (up + down) if up + down > 0 else np.nan


def build_account(frame: pd.DataFrame, ready: dict) -> tuple[pd.DataFrame, dict]:
    """機能: 旧観測品質を維持し、現在までの観測だけを作る。

    引数: frame(DataFrame)、ready(dict)。返り値: 特徴・品質集計(tuple)。将来価格の読取を含まない。
    """
    a = {c: frame[c].to_numpy(dtype=float) for c in frame.columns}
    t = a['time_s']
    prefix = {c: np.r_[0., np.cumsum(a[c])] for c in (
        'exec_buy', 'exec_sell', 'exec_unknown', 'source_volume_delta',
        'noexec_ask_remove', 'noexec_bid_remove', 'noexec_bid_add', 'noexec_ask_add',
        'refill_bid_fixed_quote', 'refill_ask_fixed_quote', 'both_up', 'both_down', 'quote_ticks',
        'raw_events', 'valid_events', 'continuity_resets', 'volume_resets', 'unavailable_volume_events',
        'depth_incomplete_events', 'depth_disordered_events', 'depth_duplicate_events')}
    rows = []
    quality = dict(起点候補=0, 過去価格不足=0, ATR不足=0, 現在品質不良=0, 採用起点=0)
    for origin in np.arange(ready['start'] + 1200., ready['limit'], 60.):
        quality['起点候補'] += 1
        at = np.searchsorted(t, [origin - 300, origin - 60, origin], side='right') - 1
        if min(at) < 0 or any(q - t[ix] > 60. for q, ix in zip([origin - 300, origin - 60, origin], at)):
            quality['過去価格不足'] += 1
            continue
        k5, k1, k = at
        atr = a['atr'][k]
        if not np.isfinite(atr) or atr <= 0:
            quality['ATR不足'] += 1
            continue
        left = max(np.searchsorted(t, origin - 60., side='right'),
                   np.searchsorted(a['source_time_s'], origin - 60., side='left'))
        right = k + 1
        get = lambda name: prefix[name][right] - prefix[name][left]
        if (right - left < 2 or get('valid_events') < 2 or
            a['source_age'][left:right].max(initial=0) > 60 or
            a['source_time_s'][left:right].min(initial=origin) < origin - 60 or
            get('continuity_resets') > 0 or get('volume_resets') > 0 or get('unavailable_volume_events') > 0 or
            get('depth_incomplete_events') > 0 or get('depth_disordered_events') > 0 or get('depth_duplicate_events') > 0):
            quality['現在品質不良'] += 1
            continue
        quality['採用起点'] += 1
        price = a['mid'][k]
        buy, sell, unknown = (get(x) for x in ('exec_buy', 'exec_sell', 'exec_unknown'))
        vol = buy + sell + unknown
        weights = a['valid_events'][left:right]
        near_bid = np.average(a['supply_bid_near'][left:right], weights=weights)
        near_ask = np.average(a['supply_ask_near'][left:right], weights=weights)
        r1, r5 = (price - a['mid'][k1]) / atr, (price - a['mid'][k5]) / atr
        checkpoints = np.arange(origin - 300., origin + .1, 60.)
        cp = np.searchsorted(t, checkpoints, side='right') - 1
        if np.any(checkpoints - t[cp] > 60.):
            quality['採用起点'] -= 1
            quality['過去価格不足'] += 1
            continue
        rv5 = np.sqrt(np.sum(np.diff(a['mid'][cp]) ** 2)) / atr
        row = dict(time_s=float(origin), observed_time=float(t[k]), seq=int(a['seq'][k]),
                   mid=float(price), atr=float(atr), r1=float(r1), r5=float(r5),
                   last_r1=float((a['last'][k] - a['last'][k1]) / atr), quote_ticks_60=float(get('quote_ticks')),
                   abs_r1=abs(r1), abs_r5=abs(r5), rv5=float(rv5), log_volume=float(np.log1p(vol)),
                   spread_atr=float((a['ask'][k] - a['bid'][k]) / atr),
                   log_depth=float(np.log1p(near_bid + near_ask)),
                   night=int('Night' in ready['session']),
                   elapsed_fraction=float((origin - ready['start']) / (ready['limit'] - ready['start'])),
                   execution=(buy - sell) / vol if vol > 0 else np.nan,
                   withdrawal=imbalance(get('noexec_ask_remove'), get('noexec_bid_remove')),
                   addition=imbalance(get('noexec_bid_add'), get('noexec_ask_add')),
                   recovery=imbalance(get('refill_bid_fixed_quote'), get('refill_ask_fixed_quote')),
                   supply=imbalance(near_bid, near_ask), repricing=imbalance(get('both_up'), get('both_down')),
                   volume=float(vol), unknown_fraction=unknown / vol if vol else np.nan,
                   valid_events=int(get('valid_events')), blocks=right - left,
                   source_max_age=float(a['source_age'][left:right].max(initial=0)),
                   nonoverlap=bool(round((origin - ready['start'] - 1200.) / 60.) % 15 == 0))
        rows.append(row)
    return pd.DataFrame(rows), quality
