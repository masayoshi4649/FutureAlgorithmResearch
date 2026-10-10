"""解放済み価格だけの準備区間を、出来高代理・先着反応・相手情報で採否判定する。"""

from __future__ import annotations

from collections import Counter, deque
from copy import deepcopy
import json
import math

import numpy as np
import pandas as pd

import band_design


_CACHE = {}
SOURCE_EMPTY = -1


def catalog() -> list[dict]:
    """機能: 結果前に決めた90条件を返す。

    引数: なし。返り値: 条件の独立コピー (list[dict])。
    """
    return band_design.catalog()


def clear_cache() -> None:
    """機能: 入力を差し替える前に共通準備の再利用を解除する。

    引数: なし。返り値: なし (None)。接頭部・未来改変検査では必ず呼ぶ。
    """
    _CACHE.clear()


def _prefix(values: np.ndarray) -> np.ndarray:
    """機能: 区間内の不正・診断件数を過去方向に累積する。

    引数: values (ndarray)。返り値: 先頭0付き累積値 (ndarray)。
    """
    return np.r_[0, np.cumsum(values, dtype=np.int64)]


def price_model(ready: dict, frame: pd.DataFrame, params: dict,
                clock_scale: float = 1.) -> dict:
    """機能: 公開済み価格窓の可用性・準備条件・相手の進行方向を計算する。

    引数: ready (dict、原本行配列)、frame (DataFrame、解放特徴)、params (dict)、
    clock_scale (float、Wだけの倍率)。返り値: 原本seqを保持した特徴列 (dict)。
    source_last_seqは当該ブロックの参照上限で、価格の厳密な素材行とは限らない。
    """
    rawseq = np.asarray(ready['seq'], dtype=np.int64)
    rawtime = np.asarray(ready['time_s'], dtype=float)
    rawatr = np.asarray(ready['atr'], dtype=float)
    assert len(rawseq) == len(rawtime) == len(rawatr)
    assert np.all(np.diff(rawseq) > 0) and np.all(np.diff(rawtime) >= 0)
    assert np.isfinite(rawtime).all() and np.isfinite(clock_scale) and clock_scale > 0
    tick = float(ready['tick'])
    assert tick > 0 and np.isfinite(tick)
    frame = frame.loc[(frame.seq <= rawseq[-1]) & (frame.time_s <= rawtime[-1])].copy() if len(rawseq) else frame.iloc[:0].copy()
    time = frame.time_s.to_numpy(float)
    seq = frame.seq.to_numpy(np.int64)
    mid = frame.source_mid_last.to_numpy(float)
    bid = frame.source_bid_last.to_numpy(float)
    ask = frame.source_ask_last.to_numpy(float)
    source_time = frame.source_time_s.to_numpy(float)
    source_first = frame.source_first_seq.to_numpy(np.int64)
    source_last = frame.source_last_seq.to_numpy(np.int64)
    assert np.isfinite(time).all() and np.all(np.diff(time) >= 0) and np.all(np.diff(seq) > 0)
    assert np.all(source_first <= source_last) and np.all(source_last < seq)
    n = len(frame)
    window = float(params['window_seconds']) * float(clock_scale)
    short = window * float(params['stall_fraction'])
    freshness = float(params['freshness_seconds'])
    current_atr = np.full(n, np.nan)
    atr_row = np.searchsorted(rawseq, seq, side='right') - 1
    good = atr_row >= 0
    current_atr[good] = rawatr[atr_row[good]]
    good &= np.where(atr_row >= 0, rawtime[np.maximum(atr_row, 0)] <= time, False) if len(rawtime) else False
    current_atr[~good] = np.nan
    delay = time - source_time
    endpoint_valid = (np.isfinite(mid) & np.isfinite(bid) & np.isfinite(ask)
        & (mid > 0) & (bid > 0) & (ask > bid)
        & (frame.valid_event_count.to_numpy(float) > 0)
        & np.isfinite(source_time) & (delay >= 0) & (delay <= freshness))
    # ----------------------------------------
    # 有効価格endpointを採る。途中の不正板リセットは価格窓の一律排除に使用しない。
    bad = _prefix(~endpoint_valid)
    gap_bad = _prefix(np.r_[False, np.diff(time) > freshness])
    reset_values = frame.continuity_reset_count.to_numpy(np.int64) if 'continuity_reset_count' in frame else np.zeros(n, np.int64)
    resets = _prefix(reset_values)
    anchor = np.searchsorted(time, time - window, side='right') - 1
    short_anchor = np.searchsorted(time, time - short, side='right') - 1
    left = np.searchsorted(time, time - window, side='left')
    valid = np.zeros(n, dtype=bool)
    stall_range = np.full(n, np.nan)
    direction = np.zeros(n, dtype=np.int8)
    peer_direction = np.zeros(n, dtype=np.int8)
    predicate = np.zeros(n, dtype=bool)
    reset_window = np.zeros(n, dtype=np.int64)
    minq, maxq = deque(), deque()
    for i in range(n):
        a, b = int(anchor[i]), int(short_anchor[i])
        while minq and minq[0] < max(0, b):
            minq.popleft()
        while maxq and maxq[0] < max(0, b):
            maxq.popleft()
        if np.isfinite(mid[i]):
            while minq and mid[minq[-1]] >= mid[i]:
                minq.pop()
            while maxq and mid[maxq[-1]] <= mid[i]:
                maxq.pop()
            minq.append(i); maxq.append(i)
        if b >= 0 and minq and maxq:
            stall_range[i] = mid[maxq[0]] - mid[minq[0]]
        if a < 0 or b < 0:
            continue
        reset_window[i] = resets[i + 1] - resets[a]
        valid[i] = ((time[i] - window - time[a]) <= freshness
            and (time[i] - short - time[b]) <= freshness
            and i - left[i] + 1 >= int(params['minimum_events'])
            and bad[i + 1] == bad[a]
            and gap_bad[i + 1] == gap_bad[a + 1]
            and np.isfinite(current_atr[i]) and current_atr[i] > 0)
        if not valid[i]:
            continue
        change = mid[i] - mid[a]
        long_threshold = max(float(params['progress_atr']) * current_atr[i], float(params['progress_ticks']) * tick)
        s = 1 if change >= long_threshold else -1 if change <= -long_threshold else 0
        direction[i] = s
        stall_limit = max(float(params['stall_atr']) * current_atr[i], float(params['stall_ticks']) * tick)
        predicate[i] = s != 0 and stall_range[i] <= stall_limit
        recent = mid[i] - mid[b]
        recent_limit = max(float(params['peer_recent_atr']) * current_atr[i], float(params['peer_recent_ticks']) * tick)
        peer_direction[i] = s if s and recent * s >= recent_limit else 0
    return dict(time=time, seq=seq, mid=mid, bid=bid, ask=ask, atr=current_atr,
        atr_row=atr_row, source_time=source_time, source_first=source_first, source_last=source_last,
        valid=valid, endpoint_valid=endpoint_valid, predicate=predicate, direction=direction,
        peer_direction=peer_direction, anchor=anchor, short_anchor=short_anchor,
        stall_range=stall_range, reset_window=reset_window, tick=tick, window=window,
        start=float(ready['start']))


def volume_index(frame: pd.DataFrame) -> dict:
    """機能: 価格と側を混ぜず、解放順の出来高代理を保持する。

    引数: frame (DataFrame、個別正増分イベント)。返り値: 側・価格別参照表 (dict)。
    側不明0は保存資料に残るが、方向付き代理スコアには足さない。
    """
    result = {}
    if not len(frame):
        return result
    assert np.all(np.diff(frame.release_seq.to_numpy(np.int64)) >= 0)
    assert np.all(np.diff(frame.release_time_s.to_numpy(float)) >= 0)
    assert (frame.current_seq < frame.release_seq).all()
    for (side, price), group in frame.loc[frame.side.ne(0)].groupby(['side', 'current_price'], sort=False):
        ratios = group.volume_to_side_qty.to_numpy(float)
        assert side in (-1, 1) and np.isfinite(price) and price > 0
        assert np.isfinite(ratios).all() and (ratios > 0).all()
        stable = group.stable.to_numpy(bool)
        result[(int(side), float(price))] = dict(seq=group.release_seq.to_numpy(np.int64),
            time=group.release_time_s.to_numpy(float), count=_prefix(np.ones(len(group), np.int64)),
            stable_count=_prefix(stable), ratios=ratios, stable=stable)
    return result


def volume_score(index: dict, side: int, price: float, time: float,
                 seq: int, window: float) -> dict:
    """機能: 準備時点に既に解放された同じ価格帯の代理量を凍結する。

    引数: index (dict)、side/seq (int)、price/time/window (float)。
    返り値: 全量・安定部分の比率合計と観測件数 (dict)。区間は[time-W,time]。
    """
    group = index.get((side, price))
    if group is None:
        return dict(all_volume_score=0., stable_volume_score=0., volume_count=0, stable_volume_count=0)
    left = int(np.searchsorted(group['time'], time - window, side='left'))
    right = min(int(np.searchsorted(group['time'], time, side='right')),
                int(np.searchsorted(group['seq'], seq, side='right')))
    assert right >= left
    ratios = group['ratios'][left:right]
    stable = group['stable'][left:right]
    # 窓外の大きな累積値との差を取らず、正の窓内項だけを精密に合計する。
    all_score = math.fsum(ratios)
    stable_score = math.fsum(ratios[stable])
    assert 0. <= stable_score <= all_score
    return dict(all_volume_score=all_score, stable_volume_score=stable_score,
        volume_count=int(group['count'][right] - group['count'][left]),
        stable_volume_count=int(group['stable_count'][right] - group['stable_count'][left]))


def common_episodes(model: dict, index: dict, params: dict) -> list[dict]:
    """機能: 出来高・相手・望む反応に依存しない価格準備母集団を作る。

    引数: model (dict、price_model)、index (dict、volume_index)、params (dict)。
    返り値: 準備から初回確認又は失効までの一覧 (list[dict])。未解決末尾を将来で埋めない。
    """
    episodes = []
    active = None
    waiting_reset = False
    window = model['window']
    for i, t in enumerate(model['time']):
        seq = int(model['seq'][i])
        if active is not None:
            reason, branch, b = None, None, 0
            if t >= active['expiry_time_s']:
                reason = 'expired'
            elif not model['valid'][i]:
                reason = 'data_unavailable'
            else:
                progress = (model['mid'][i] - active['setup_mid']) * active['setup_side']
                if progress <= -active['confirmation_width']:
                    reason, branch, b = 'confirmed', 'reversal', -active['setup_side']
                elif (progress >= active['confirmation_width']
                      and (model['mid'][i] - active['band_price']) * active['setup_side'] >= model['tick']):
                    reason, branch, b = 'confirmed', 'breakout', active['setup_side']
            if reason is not None:
                active.update(resolution=reason, response_branch=branch, response_direction=int(b),
                    resolution_feature_row=i, resolution_seq=seq, resolution_time_s=float(t),
                    resolution_mid=float(model['mid'][i]) if np.isfinite(model['mid'][i]) else None,
                    confirmation_seq=seq if b else None, confirmation_time_s=float(t) if b else None,
                    resolution_source_last_seq=int(model['source_last'][i]))
                active = None
                waiting_reset = True
            continue
        if waiting_reset:
            if model['valid'][i] and not model['predicate'][i]:
                waiting_reset = False
            continue
        if t < model['start'] + float(params['warmup_seconds']):
            continue
        if not model['predicate'][i]:
            continue
        s = int(model['direction'][i])
        band = float(model['ask'][i] if s > 0 else model['bid'][i])
        a, b = int(model['anchor'][i]), int(model['short_anchor'][i])
        active = dict(episode_id=len(episodes), setup_feature_row=i, setup_seq=seq,
            setup_time_s=float(t), setup_side=s, setup_mid=float(model['mid'][i]),
            setup_bid=float(model['bid'][i]), setup_ask=float(model['ask'][i]), band_price=band,
            setup_atr=float(model['atr'][i]), setup_atr_ready_row=int(model['atr_row'][i]),
            setup_source_time_s=float(model['source_time'][i]),
            setup_source_first_seq=int(model['source_first'][i]), setup_source_last_seq=int(model['source_last'][i]),
            long_anchor_seq=int(model['seq'][a]), long_anchor_time_s=float(model['time'][a]),
            short_anchor_seq=int(model['seq'][b]), short_anchor_time_s=float(model['time'][b]),
            stall_range=float(model['stall_range'][i]), continuity_reset_count=int(model['reset_window'][i]),
            window_seconds=float(window),
            confirmation_width=float(max(float(params['confirmation_atr']) * model['atr'][i], float(params['confirmation_ticks']) * model['tick'])),
            expiry_time_s=float(t + max(float(params['setup_lifetime_min']), float(params['setup_lifetime_windows']) * window)),
            resolution='pending', response_branch=None, response_direction=0,
            resolution_feature_row=None, resolution_seq=None, resolution_time_s=None, resolution_mid=None,
            confirmation_seq=None, confirmation_time_s=None, resolution_source_last_seq=None,
            **volume_score(index, s, band, float(t), seq, window))
        episodes.append(active)
    return episodes


def peer_information(model: dict | None, time: float, params: dict) -> dict:
    """機能: 成立時点より60秒前までに公開された相手窓だけを参照する。

    引数: model (dict|None)、time (float、自市場確認時刻)、params (dict)。
    返り値: 情報可用性と有効中立を分離した証拠 (dict)。
    """
    empty = dict(peer_available=False, peer_direction=0, peer_seq=None, peer_time_s=None,
        peer_available_time_s=None, peer_age_seconds=None, peer_source_last_seq=None,
        peer_long_anchor_seq=None, peer_short_anchor_seq=None)
    if model is None or not len(model['time']):
        return empty
    delay = float(params['peer_delay_seconds'])
    i = int(np.searchsorted(model['time'], time - delay, side='right') - 1)
    if i < 0:
        return empty
    age = time - (model['time'][i] + delay)
    valid = bool(age <= float(params['freshness_seconds']) and model['valid'][i])
    a, b = int(model['anchor'][i]), int(model['short_anchor'][i])
    return dict(peer_available=valid, peer_direction=int(model['peer_direction'][i]) if valid else 0,
        peer_seq=int(model['seq'][i]), peer_time_s=float(model['time'][i]),
        peer_available_time_s=float(model['time'][i] + delay), peer_age_seconds=float(age),
        peer_source_last_seq=int(model['source_last'][i]),
        peer_long_anchor_seq=int(model['seq'][a]) if a >= 0 else None,
        peer_short_anchor_seq=int(model['seq'][b]) if b >= 0 else None)


def adopt(ready: dict, common: list[dict], peer_model: dict | None, params: dict) -> dict:
    """機能: 共通準備の凍結情報だけで採否を決め、成立を原本行へ展開する。

    引数: ready (dict)、common (list[dict])、peer_model (dict|None)、params (dict)。
    返り値: direction(int8)/source_episode/source_row(int64)、明細、活動量 (dict)。
    source_rowは確認解放rawseqであり、ready配列indexではない。方向0の証拠列は-1。
    """
    rawseq = np.asarray(ready['seq'], dtype=np.int64)
    rawtime = np.asarray(ready['time_s'], dtype=float)
    direction = np.zeros(len(rawseq), dtype=np.int8)
    source_episode = np.full(len(rawseq), SOURCE_EMPTY, dtype=np.int64)
    source_row = np.full(len(rawseq), SOURCE_EMPTY, dtype=np.int64)
    records = deepcopy(common)
    accepted = []
    counts = Counter()
    for row in records:
        proxy = params['proxy']
        assert proxy in ('price', 'all_volume', 'stable_volume')
        proxy_pass = proxy == 'price' or row[proxy + '_score'] >= float(params['volume_threshold'])
        branch_pass = (row['resolution'] == 'confirmed'
            and (params['branch'] == 'automatic' or row['response_branch'] == params['branch']))
        peer = peer_information(peer_model, row['confirmation_time_s'], params) if row['resolution'] == 'confirmed' else peer_information(None, 0., params)
        mode = params['peer_mode']
        assert mode in ('none', 'veto', 'confirm')
        peer_pass = (mode == 'none' or (peer['peer_available'] and
            (peer['peer_direction'] != -row['response_direction'] if mode == 'veto'
             else peer['peer_direction'] == row['response_direction'])))
        reasons = []
        if row['resolution'] != 'confirmed':
            reasons.append(row['resolution'])
        if not proxy_pass:
            reasons.append('volume_below_threshold')
        if row['resolution'] == 'confirmed' and not branch_pass:
            reasons.append('opposite_branch_first')
        if row['resolution'] == 'confirmed' and not peer_pass:
            reasons.append('peer_unavailable' if not peer['peer_available'] else 'peer_opposite' if mode == 'veto' else 'peer_not_confirmed')
        ok = bool(row['resolution'] == 'confirmed' and proxy_pass and branch_pass and peer_pass)
        row.update(**peer, proxy_pass=bool(proxy_pass), branch_pass=bool(branch_pass), peer_pass=bool(peer_pass),
            accepted=ok, rejection_reasons=reasons,
            signal_expiry_time_s=float(row['confirmation_time_s'] + params['signal_lifetime_seconds']) if ok else None)
        counts['setups'] += 1
        counts['proxy_pass_setups'] += int(proxy_pass)
        counts[row['resolution']] += 1
        counts['accepted'] += int(ok)
        counts['peer_available_confirmations'] += int(row['resolution'] == 'confirmed' and peer['peer_available'])
        for reason in reasons:
            counts['rejected:' + reason] += 1
        if ok:
            counts['accepted:' + row['response_branch']] += 1
            accepted.append(row)
    # ----------------------------------------
    # 新たに採用した準備だけが期限・根拠を置換する。不採用・同方向観測では延命しない。
    for j, row in enumerate(accepted):
        left = int(np.searchsorted(rawseq, row['confirmation_seq'], side='left'))
        right = int(np.searchsorted(rawtime, row['signal_expiry_time_s'], side='left'))
        if j + 1 < len(accepted):
            right = min(right, int(np.searchsorted(rawseq, accepted[j + 1]['confirmation_seq'], side='left')))
        if right <= left:
            continue
        direction[left:right] = row['response_direction']
        source_episode[left:right] = row['episode_id']
        source_row[left:right] = row['confirmation_seq']
    assert np.isin(direction, [-1, 0, 1]).all()
    assert np.all(source_row[direction != 0] <= rawseq[direction != 0])
    dt = np.r_[np.diff(rawtime), 0.] if len(rawtime) else np.empty(0)
    counts['long_signal_rows'] = int(np.sum(direction == 1))
    counts['short_signal_rows'] = int(np.sum(direction == -1))
    activity = dict(counts)
    activity.update(long_signal_seconds=float(dt[direction == 1].sum()),
        short_signal_seconds=float(dt[direction == -1].sum()))
    return dict(direction=direction, source_episode=source_episode, source_row=source_row,
                episodes=records, activity=activity)


def build(spec: dict, inputs: dict, features: dict, events: dict,
          clock_scale: float = 1.) -> dict:
    """機能: 全入力へ因果的な価格帯の方向・根拠・共通準備明細を返す。

    引数: spec (dict)、inputs/features/events (dict[(session,symbol),内容])、clock_scale (float)。
    返り値: 各キーのadopt出力を持つ辞書 (dict)。売買・損益・現在データ取得は行わない。
    入力は呼出間に変更しない。変更する監査はclear_cacheを先に実行する。
    """
    params = deepcopy(spec['params'])
    assert set(inputs) == set(features) == set(events)
    base_params = {k: v for k, v in params.items() if k not in ('proxy', 'volume_threshold', 'branch', 'peer_mode')}
    key = (id(inputs), id(features), id(events), float(clock_scale), json.dumps(base_params, sort_keys=True))
    if key not in _CACHE:
        models = {k: price_model(ready, features[k], params, clock_scale) for k, ready in inputs.items()}
        common = {k: common_episodes(models[k], volume_index(events[k]), params) for k in inputs}
        _CACHE[key] = dict(refs=(inputs, features, events), models=models, common=common)
    cache = _CACHE[key]
    outputs = {}
    for key_input, ready in inputs.items():
        session, symbol = key_input
        other = 'TOPIX' if symbol == 'NK225' else 'NK225' if symbol == 'TOPIX' else None
        peer = cache['models'].get((session, other))
        outputs[key_input] = adopt(ready, cache['common'][key_input], peer, params)
    return outputs
