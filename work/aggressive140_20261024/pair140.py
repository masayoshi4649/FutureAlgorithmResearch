"""二市場の相対価格の収束を、整数数量と非同期の両脚約定を含めて検証する。"""

import numpy as np
from numba import njit


SYMBOLS = ('NK225', 'TOPIX')
ORDER_COLUMNS = ('イベント行', '原行', '判断時刻', '判断時点の原行', '親ID', '脚',
                 '売買方向', '枚数', '価格', '手数料', '新規', '理由', '実現粗損益', '純損益')
CAMPAIGN_COLUMNS = ('親ID', '判断時刻', '比率方向', '入口対数比率', '固定平均', '固定標準偏差',
                    '日経枚数', 'TOPIX枚数', '判断時元本差円', '判断時元本差割合',
                    '日経純損益', 'TOPIX純損益', '片脚保有秒', '完結時刻', '返済理由',
                    '実約定元本差円')
REASONS = {1: '相対価格の収束へ新規', 2: '固定平均へ収束', 3: '歪みが損切り幅まで拡大',
           4: '片脚待機が上限を超過', 5: '気配の同期鮮度を喪失', 6: '場末の全返済'}


def configurations():
    """
    機能: 過去帯の長さと入口根拠が異なる9条件を金融再生前に固定する。
    引数: なし。
    返り値: list[dict]は時系列処理・数量・費用を共有する候補。
    """
    result = []
    names = ('相対価格の偏りから収束', '偏りの戻り始めを確認', '二市場の逆行の回復')
    for window in (20, 40, 60):
        for mode in range(3):
            result.append(dict(id=f'P{len(result)+1:02d}', name=names[mode], window=window,
                mode=mode, entry_z=2. if mode == 0 else 1.5, target_z=.25, stop_z=1.5,
                turn_z=.2, hold_seconds=15., cooldown_seconds=300., freshness_seconds=15.,
                leg_timeout_seconds=15., entry_cutoff_seconds=600., minimum_edge_cost=3.,
                maximum_mismatch=.10, nk_min=5, nk_max=10, topix_min=1, topix_max=10,
                multipliers=(100., 1000.), fee_tenths=(385, 418), publish_delay_seconds=60.))
    return result


def _valid(bid, ask, known):
    """
    機能: 正常な両側気配を約定時計の有無から独立に識別する。
    引数: bid/ask(ndarray)、known(ndarray[bool])は価格と保存済み品質。
    返り値: ndarray[bool]は0より大きい非交差気配。
    """
    return known & np.isfinite(bid) & np.isfinite(ask) & (bid > 0.) & (ask > bid)


def _last_at(times, targets):
    """
    機能: 指定時刻より厳密に前の原行を求める。
    引数: times/targets(ndarray)は昇順の原時刻と参照時刻。
    返り値: ndarray[int]は原行番号。先行行なしは-1。
    """
    return np.searchsorted(times, targets, side='left') - 1


def prepare(packet, window, publish_delay_seconds=60., freshness_seconds=15.):
    """
    機能: 二市場の原行を結合し、厳密過去の気配と確定比率帯を作る。
    引数: packet(dict)は一場二市場、window(int)は確定分足数、残り(float)は公開遅延と鮮度。
    返り値: dictは同期を捏造しないイベント列。時刻同値の両市場行は当時の判断へ入れない。
    """
    assert window >= 5
    session = packet['session']
    ready = [packet['inputs'][(session, s)] for s in SYMBOLS]
    quotes = [packet['quotes'][(session, s)] for s in SYMBOLS]
    times = [np.asarray(r['time_s'], dtype=float) for r in ready]
    assert all(len(t) and np.isfinite(t).all() and np.all(np.diff(t) >= 0.) for t in times)
    start = max(float(r['start']) for r in ready)
    end = min(float(r['limit']) for r in ready)
    events = np.unique(np.concatenate(times))
    n = len(events)
    decision = np.full((n, 6), np.nan)
    fill = np.full((n, 4), np.nan)
    marking = np.full((n, 4), np.nan)
    fill_row = np.full((n, 2), -1, dtype=np.int64)
    source_row = np.full((n, 2), -1, dtype=np.int64)
    prior = []
    valid = []
    for leg in range(2):
        t, q = times[leg], quotes[leg]
        b, a = np.asarray(q['bid']), np.asarray(q['ask'])
        good = _valid(b, a, np.asarray(q['quote_valid'], dtype=bool))
        valid.append(good)
        before = _last_at(t, events)
        safe = np.maximum(before, 0)
        ok = (before >= 0) & good[safe] & (events-t[safe] <= freshness_seconds)
        decision[ok, 2*leg] = b[safe[ok]]
        decision[ok, 2*leg+1] = a[safe[ok]]
        decision[ok, 4+leg] = t[safe[ok]]
        source_row[:, leg] = np.searchsorted(t, events, side='right')-1
        prior.append(before)
        # 同一時刻の複数原行のうち、既発注が最初に受ける正常行だけを使う。
        indices = np.flatnonzero(good)
        if len(indices):
            positions = np.searchsorted(events, t[indices])
            first = np.r_[True, positions[1:] != positions[:-1]]
            k, raw = positions[first], indices[first]
            fill_row[k, leg] = raw
            fill[k, 2*leg], fill[k, 2*leg+1] = b[raw], a[raw]
            last = np.r_[positions[1:] != positions[:-1], True]
            k, raw = positions[last], indices[last]
            marking[k, 2*leg], marking[k, 2*leg+1] = b[raw], a[raw]

    # ----------------------------------------
    # 足確定時に両脚とも15秒以内の原行がある場合だけ比率を作る。欠測の前方補完はしない。
    ends = np.arange(start+60., events[-1]+.001, 60.)
    close = np.full((len(ends), 2), np.nan)
    for leg in range(2):
        ix = _last_at(times[leg], ends)
        safe = np.maximum(ix, 0)
        ok = (ix >= 0) & valid[leg][safe] & (ends-times[leg][safe] <= freshness_seconds)
        q = quotes[leg]
        close[ok, leg] = (np.asarray(q['bid'])[safe[ok]]+np.asarray(q['ask'])[safe[ok]])*.5
    with np.errstate(divide='ignore', invalid='ignore'):
        ratio = np.log(close[:, 0]/close[:, 1])
    bars = np.full((len(ends), 5), np.nan)
    for j in range(window-1, len(ends)):
        block = ratio[j-window+1:j+1]
        if np.isfinite(block).all():
            bars[j, 0], bars[j, 1] = block.mean(), block.std(ddof=1)
            bars[j, 2:4] = np.log(close[j]/close[j-window+1])
            bars[j, 4] = ends[j]
    which = np.searchsorted(ends+publish_delay_seconds, events, side='right')-1
    history = np.full((n, 5), np.nan)
    known = which >= 0
    history[known] = bars[which[known]]
    history[events-history[:, 4] >= publish_delay_seconds+60.] = np.nan
    # 30秒前もその時点より前の原行を使い、後から届く同時刻の相手行を利用しない。
    old = np.full((n, 2), np.nan)
    for leg in range(2):
        ix = _last_at(times[leg], events-30.)
        safe = np.maximum(ix, 0)
        ok = (ix >= 0) & valid[leg][safe] & (events-30.-times[leg][safe] <= freshness_seconds)
        q = quotes[leg]
        old[ok, leg] = (np.asarray(q['bid'])[safe[ok]]+np.asarray(q['ask'])[safe[ok]])*.5
    with np.errstate(divide='ignore', invalid='ignore'):
        old_ratio = np.log(old[:, 0]/old[:, 1])
    return dict(session=session, times=events, decision=decision, fill=fill, marking=marking, fill_row=fill_row,
                source_row=source_row, history=history, old_ratio=old_ratio, start=start, end=end,
                window=int(window), publication=float(publish_delay_seconds), freshness=float(freshness_seconds))


@njit(cache=True)
def quantities(prices, multipliers, nk_min, nk_max, topix_min, topix_max):
    """
    機能: 入力価格だけから両脚の元本差割合を最小にする整数枚数を選ぶ。
    引数: prices/multipliers(ndarray)、各上下限(int)は当時中値・倍率・許容枚数。
    返り値: tuple[int,int,float,float]は枚数2つ、符号付き元本差円と元本差割合。
    """
    best = np.inf
    best_size = np.inf
    q0 = q1 = 0
    mismatch = 0.
    for a in range(nk_min, nk_max+1):
        for b in range(topix_min, topix_max+1):
            n0, n1 = a*prices[0]*multipliers[0], b*prices[1]*multipliers[1]
            size = (n0+n1)*.5
            score = abs(n0-n1)/size
            if score < best-1.e-12 or (abs(score-best) <= 1.e-12 and size < best_size):
                q0, q1, mismatch, best, best_size = a, b, n0-n1, score, size
    return q0, q1, mismatch, best


@njit(cache=True)
def _run(times, quotes, fill, marking, fill_row, source_row, history, old_ratio, start, end, p):
    """
    機能: 非同期約定・両脚損益・片脚リスクを追跡し、相対価格の収束を売買する。
    引数: 原行特徴とp(ndarray)、start/end(float)はセッション範囲と固定設定。
    返り値: tuple[ndarray,ndarray,ndarray]は注文・親完結・清算時価。未清算は例外。
    """
    (mode, entry_z, target_z, stop_z, turn_z, hold, cooldown, freshness, leg_timeout,
     cutoff, edge_cost, max_mismatch, nk_min, nk_max, topix_min, topix_max,
     mult0, mult1, fee0, fee1) = p
    mult = np.array([mult0, mult1])
    fee = np.array([fee0, fee1])
    n = len(times)
    orders = np.zeros((max(1024, n//2), 14))
    campaigns = np.zeros((max(256, n//8), 16))
    equity = np.zeros((n, 3))
    oc = cc = 0
    phase = 0
    parent = -1
    qty = np.zeros(2, np.int64)
    direction = np.zeros(2, np.int64)
    held = np.zeros(2, np.int64)
    pending = np.zeros(2, np.int64)
    decision_time = np.zeros(2)
    decision_row = np.zeros(2, np.int64)
    entry_price = np.zeros(2)
    mark = np.full((2, 2), np.nan)
    cash = np.zeros(2)
    net = np.zeros(2)
    since = -np.inf
    setup_direction = 0
    next_ready = start
    begin = anchor = center = scale = mismatch = mismatch_pct = unhedged = filled_mismatch = 0.
    side = reason = 0
    previous = times[0]
    for i in range(n):
        now = times[i]
        if phase and ((held[0] > 0) != (held[1] > 0)):
            unhedged += now-previous
        if now-previous > freshness:
            since = -np.inf
        previous = now
        # ----------------------------------------
        # 既発注の両脚を別々に約定する。後着脚を消して同時約定に置き換えない。
        for leg in range(2):
            if fill_row[i, leg] < 0:
                continue
            mark[leg, 0], mark[leg, 1] = marking[i, 2*leg], marking[i, 2*leg+1]
            if not pending[leg] or now <= decision_time[leg]:
                continue
            assert fill_row[i, leg] > decision_row[leg]
            new = pending[leg] == 1
            order_side = direction[leg] if new else -direction[leg]
            price = fill[i, 2*leg+1] if order_side > 0 else fill[i, 2*leg]
            cost = qty[leg]*fee[leg]//10.
            gross = 0.
            if new:
                assert held[leg] == 0
                held[leg], entry_price[leg] = qty[leg], price
            else:
                assert held[leg] == qty[leg]
                gross = direction[leg]*qty[leg]*(price-entry_price[leg])*mult[leg]
                held[leg] = 0
            cash[leg] -= order_side*qty[leg]*price*mult[leg]+cost
            net[leg] += gross-cost
            assert oc < len(orders)
            orders[oc] = np.array([i, fill_row[i, leg], decision_time[leg], decision_row[leg],
                parent, leg, order_side, qty[leg], price, cost, 1 if new else 0,
                1 if new else reason, gross, gross-cost])
            oc += 1
            pending[leg] = 0
        if phase == 1 and held[0] and held[1]:
            filled_mismatch = qty[0]*entry_price[0]*mult[0]-qty[1]*entry_price[1]*mult[1]
            if now-begin <= leg_timeout:
                phase = 2
        if phase == 3 and not held.sum() and not pending.sum():
            assert cc < len(campaigns)
            campaigns[cc] = np.array([parent, begin, side, anchor, center, scale,
                qty[0], qty[1], mismatch, mismatch_pct, net[0], net[1], unhedged, now, reason,
                filled_mismatch])
            cc += 1
            phase = 0
            next_ready = now+cooldown
            since = -np.inf
        known = np.isfinite(quotes[i]).all()
        mid = np.zeros(2)
        ratio = np.nan
        if known:
            mid[0] = (quotes[i, 0]+quotes[i, 1])*.5
            mid[1] = (quotes[i, 2]+quotes[i, 3])*.5
            ratio = np.log(mid[0]/mid[1])
        # ----------------------------------------
        # 平均と分散は新規判断時に固定。片脚待機・鮮度喪失・場末は保険返済を優先する。
        if phase in (1, 2):
            exit_reason = 0
            if now >= end:
                exit_reason = 6
            elif phase == 1 and now-begin > leg_timeout:
                exit_reason = 4
            elif phase == 2 and not known:
                exit_reason = 5
            elif phase == 2:
                if side*(ratio-anchor) <= -stop_z*scale:
                    exit_reason = 3
                elif side*(ratio-center) >= -target_z*scale:
                    exit_reason = 2
            if exit_reason:
                phase, reason = 3, exit_reason
        if phase == 3:
            for leg in range(2):
                if held[leg] and not pending[leg]:
                    pending[leg], decision_time[leg], decision_row[leg] = 2, now, source_row[i, leg]
        # ----------------------------------------
        # 新規は固定過去帯と現在までの偏りだけを根拠にし、片脚を抱えたまま追加しない。
        if phase == 0 and now >= next_ready and now < end-cutoff and known and np.isfinite(history[i]).all():
            mu, sd = history[i, 0], history[i, 1]
            candidate = 0
            if sd > 1.e-9:
                z = (ratio-mu)/sd
                if abs(z) >= entry_z:
                    candidate = -1 if z > 0. else 1
                    if mode >= 1:
                        if not np.isfinite(old_ratio[i]) or candidate*(ratio-old_ratio[i]) < turn_z*sd:
                            candidate = 0
                    if mode == 2 and history[i, 2]*history[i, 3] >= 0.:
                        candidate = 0
            if candidate:
                if candidate != setup_direction or not np.isfinite(since):
                    setup_direction, since = candidate, now
                if now-since >= hold:
                    q0, q1, mm, mp = quantities(mid, mult, int(nk_min), int(nk_max), int(topix_min), int(topix_max))
                    nominal = min(q0*mid[0]*mult[0], q1*mid[1]*mult[1])
                    edge = nominal*max(0., abs(ratio-mu)-target_z*sd)
                    costs = q0*(quotes[i,1]-quotes[i,0])*mult[0]+q1*(quotes[i,3]-quotes[i,2])*mult[1]
                    costs += 2.*(q0*fee[0]//10.+q1*fee[1]//10.)
                    if mp <= max_mismatch and edge >= edge_cost*costs:
                        phase, parent, side = 1, parent+1, candidate
                        begin, anchor, center, scale = now, ratio, mu, sd
                        mismatch, mismatch_pct, unhedged, filled_mismatch = mm, mp, 0., np.nan
                        qty[0], qty[1] = q0, q1
                        direction[0], direction[1] = side, -side
                        net[:] = 0.
                        for leg in range(2):
                            pending[leg], decision_time[leg], decision_row[leg] = 1, now, source_row[i, leg]
                    since = -np.inf
            else:
                since = -np.inf
        elif phase == 0:
            since = -np.inf
        for leg in range(2):
            value = cash[leg]
            if held[leg]:
                liquidate = mark[leg, 0] if direction[leg] > 0 else mark[leg, 1]
                value += direction[leg]*held[leg]*liquidate*mult[leg]-held[leg]*fee[leg]//10.
            equity[i, leg+1] = value
        equity[i, 0] = equity[i, 1]+equity[i, 2]
    assert phase == 0 and held.sum() == 0 and pending.sum() == 0, '場末の実行可能な返済原行が不足'
    return orders[:oc], campaigns[:cc], equity


def account(orders, campaigns, equity):
    """
    機能: 各脚とペア完結を別々に集計し、会計一致・数量上限を検証する。
    引数: orders/campaigns/equity(ndarray)は状態機械の記録。
    返り値: dictは利益・損失・費用・純損益と残余元本差・片脚時間。
    """
    per_leg = {}
    for leg, symbol in enumerate(SYMBOLS):
        rows = orders[orders[:, 5] == leg]
        gross = rows[:, 12]
        result = dict(gross_profit=float(gross[gross > 0].sum()), gross_loss=float(-gross[gross < 0].sum()),
                      fees=float(rows[:, 9].sum()), net=float(rows[:, 13].sum()),
                      entries=int(np.count_nonzero(rows[:, 10] == 1)),
                      entry_quantity=int(rows[rows[:, 10] == 1, 7].sum()))
        assert abs(result['net']-equity[-1, leg+1]) < .01
        per_leg[symbol] = result
    net = campaigns[:, 10:12].sum(axis=1)
    result = dict(by_symbol=per_leg, pairs=len(campaigns), orders=len(orders),
                  gross_profit=sum(r['gross_profit'] for r in per_leg.values()),
                  gross_loss=sum(r['gross_loss'] for r in per_leg.values()),
                  fees=sum(r['fees'] for r in per_leg.values()), net=float(net.sum()),
                  pair_net_profit=float(net[net > 0].sum()), pair_net_loss=float(-net[net < 0].sum()),
                  winning_pairs=int(np.count_nonzero(net > 0)), losing_pairs=int(np.count_nonzero(net < 0)),
                  single_leg_seconds=float(campaigns[:, 12].sum()),
                  maximum_notional_mismatch=float(np.abs(campaigns[:, 8]).max()) if len(campaigns) else 0.,
                  maximum_notional_mismatch_ratio=float(campaigns[:, 9].max()) if len(campaigns) else 0.)
    assert abs(result['net']-sum(r['net'] for r in per_leg.values())) < .01
    assert abs(result['net']-equity[-1, 0]) < .01
    assert np.all(orders[:, 7] <= 10)
    return result


def replay(packet, config, prepared=None):
    """
    機能: 計画固定済みのペア条件を一場だけ因果的に再生する。
    引数: packet/config(dict)、prepared(dict|None)は入力・設定・再利用可能な同条件特徴。
    返り値: dictはorders/campaigns/equity/summary/prepared。入力価格はラージ代理気配。
    """
    c = config
    assert 1 <= c['nk_min'] <= c['nk_max'] <= 10 and 1 <= c['topix_min'] <= c['topix_max'] <= 10
    d = prepared if prepared is not None else prepare(packet, c['window'], c['publish_delay_seconds'], c['freshness_seconds'])
    assert d['window'] == c['window'] and d['publication'] == c['publish_delay_seconds'] and d['freshness'] == c['freshness_seconds']
    assert d['session'] == packet['session']
    keys = ('mode', 'entry_z', 'target_z', 'stop_z', 'turn_z', 'hold_seconds', 'cooldown_seconds',
            'freshness_seconds', 'leg_timeout_seconds', 'entry_cutoff_seconds', 'minimum_edge_cost',
            'maximum_mismatch', 'nk_min', 'nk_max', 'topix_min', 'topix_max')
    p = np.array([c[k] for k in keys]+list(c['multipliers'])+list(c['fee_tenths']), dtype=float)
    orders, campaigns, equity = _run(d['times'], d['decision'], d['fill'], d['marking'], d['fill_row'], d['source_row'],
        d['history'], d['old_ratio'], d['start'], d['end'], p)
    return dict(orders=orders, campaigns=campaigns, equity=equity,
                summary=account(orders, campaigns, equity), prepared=d)
