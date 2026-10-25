"""保存F1基本枠の通知だけを入口にし、親単位の採否と自己市場の失敗認定を加える。

原注文の将来損益・最終価格は参照しない。通知行で採否を決め、元の予約済み
新規・追加・返済は取消さず執行する。独自返済後の新しい候補生成は行わない。
半減後に届く元の部分返済は、そのUIDの仮想残枚数に対する実残枚数の割合で
数量を縮小する。半減・全返済の判断以降は未発注の同親追加を見送る。
既存F1の深夜注文は消さない。03～06時の除外は保有率の評価で別に行う。
"""

import numpy as np
from numba import njit


TRACE_COLUMNS = [
    '判断行', '親ID', '種類', '方向', '行動', '理由', '枚数',
    '現在進捗R', '最高進捗R', '初回固定幅', '元予約件数', '価格時計',
]
TRACE_KINDS = {1: '親の初回採否', 2: '独自返済の意思決定', 3: '独自返済発注',
               4: '判断後に届いた追加を見送り'}
REASONS = {0: '元通知を採用', 14301: '自己120秒逆流', 14302: '二市場120秒逆流',
           14303: '自己MA20位置と120秒と板の崩れ', 14304: '自己崩れと相手逆流',
           14305: '自己MA20位置と120秒の崩れ', 14306: '自己崩れと利益進捗による減枚',
           14307: '短期逆流だけの対照', 14308: '失敗認定後の追加停止'}


def configurations():
    """
    機能: 入口・途中・利益進捗の各機構を分離した十二条件を返す。
    引数: なし。
    返り値: list[dict]はO00基準と十一の事前固定条件。
    """
    definitions = [
        ('O00', 0, 0, '保存基本枠のまま'),
        ('O01', 1, 0, '自己120秒の強い逆流を新規前に除外'),
        ('O02', 2, 0, '二市場120秒の逆流を新規前に除外'),
        ('O03', 0, 1, '自己MA20位置・120秒・原板の崩れで全返済'),
        ('O04', 0, 2, '自己崩れに相手120秒・原板の逆流も要求'),
        ('O05', 0, 3, '自己MA20位置・120秒の崩れで全返済'),
        ('O06', 0, 4, '自己崩れ時の利益進捗で半減又は全返済'),
        ('O07', 0, 5, '自己30・120秒の逆流だけで全返済する対照'),
        ('O08', 1, 1, '自己入口除外と自己崩れ全返済'),
        ('O09', 2, 1, '二市場入口除外と自己崩れ全返済'),
        ('O10', 1, 4, '自己入口除外と利益進捗による減枚'),
        ('O11', 2, 4, '二市場入口除外と利益進捗による減枚'),
    ]
    return [dict(id=identifier, gate=gate, management=management, explanation=name,
                 confirmation_seconds=15., quote_gap_seconds=15.,
                 own_entry_reverse_r=.25, own_position_reverse_r=.1,
                 short_reverse_r=.1, loss_full_r=.5,
                 protected_progress_r=.75, protected_giveback_r=.25)
            for identifier, gate, management, name in definitions]


@njit(cache=True)
def _width(atr, tick):
    """
    機能: 現在公表済みのATRと八呼値の大きい幅を返す。
    引数: atr(float)、tick(float)は公開ATRと呼値。ATR未知は八呼値だけを使う。
    返り値: floatは価格幅。元親の非公開準備時幅の推測はしない。
    """
    return max(atr, 8. * tick) if np.isfinite(atr) and atr > 0. else 8. * tick


@njit(cache=True)
def _gate(a, now, side, width, kind, threshold, freshness):
    """
    機能: 初回通知時に観測済みの逆流だけで親全体の拒否理由を返す。
    引数: a(ndarray)、now/width/threshold/freshness(float)、side/kind(int)は当時の特徴と条件。
    返り値: intは拒否理由。0は採用。未知値を逆流とみなさない。
    """
    own = np.isfinite(a[13]) and np.isfinite(a[9]) and a[9] > 0.
    if kind == 1 and own and side * a[13] * a[9] / width < -threshold:
        return 14301
    peer = np.isfinite(a[21]) and np.isfinite(a[22]) and 0. <= now - a[22] <= freshness
    if kind == 2 and own and peer and side * a[13] < 0. and side * a[21] < 0.:
        return 14302
    return 0


@njit(cache=True)
def _adverse(a, ma20, now, side, width, kind, position_r, short_r, freshness):
    """
    機能: 元保険を変更せず、追加の失敗認定に必要な現在の証拠を返す。
    引数: a(ndarray)、ma20/now/width/position_r/short_r/freshness(float)、side/kind(int)。
    返り値: boolは当該行で条件が揃ったか。持続判定は呼出元で行う。
    """
    own = np.isfinite(a[10]) and np.isfinite(a[13]) and np.isfinite(a[9]) and a[9] > 0.
    if not own or side * a[13] >= 0.:
        return False
    if kind == 5:
        return np.isfinite(a[12]) and side * a[12] * a[9] / width <= -short_r
    if not np.isfinite(ma20) or side * (a[10] - ma20) / width > -position_r:
        return False
    if kind != 3 and (not np.isfinite(a[24]) or side * a[24] >= 0.):
        return False
    if kind == 2:
        return (np.isfinite(a[21]) and np.isfinite(a[26]) and np.isfinite(a[22])
                and 0. <= now - a[22] <= freshness
                and side * a[21] < 0. and side * a[26] < 0.)
    return True


@njit(cache=True)
def _parent(times, bid, ask, valid, atr, a, ma20, tick, rows, original_indices,
            ticket, ticket_count, settings, fee10):
    """
    機能: 一親の保存通知を時系列処理し、予約を尊重して追加返済を次正常原行へ送る。
    引数: times/bid/ask/valid/atr/a/ma20/rows/original_indices/ticket/settings(ndarray)、
          tick(float)、ticket_count/fee10(int)は当時資料、元注文、UID対応、設定、十倍手数料。
    返り値: tuple[ndarray,ndarray]は十一列内部注文と十二列選択記録。末列は同原行の順序。
    """
    n = len(times)
    count = len(rows)
    result = np.empty((count + 2 * ticket_count + 4, 11))
    trace = np.empty((count * 3 + 20, 12))
    nr = nt = 0
    parent = rows[0, 2]
    side = int(rows[0, 3])
    gate, mode = int(settings[0]), int(settings[1])
    hold, gap = settings[2], settings[3]
    # ----------------------------------------
    # 元の仮想残高と実残高を分け、途中半減後の元返済数量を因果的に縮小する。
    virtual = np.zeros(ticket_count, np.int64)
    actual = np.zeros(ticket_count, np.int64)
    reserved = np.zeros(ticket_count, np.int64)
    effective = np.zeros(count, np.int64)
    issued = np.zeros(count, np.bool_)
    filled = np.zeros(count, np.bool_)
    synth_qty = np.zeros(ticket_count, np.int64)
    synth_decision = np.full(ticket_count, -1, np.int64)
    synth_reason = np.zeros(ticket_count, np.int64)
    uid_values = np.zeros(ticket_count)
    for k in range(count):
        uid_values[ticket[k]] = rows[k, 8]
    decision_order = np.argsort(rows[:, 1], kind='mergesort')
    fill_order = np.argsort(rows[:, 0], kind='mergesort')
    di = fi = pending = 0
    admitted = False
    decided = False
    blocked = False
    initial_width = np.nan
    initial_price = np.nan
    best = 0.
    since = -np.inf
    intent = 0
    intent_reason = 0
    half_done = False
    full_done = False
    start = int(rows[decision_order[0], 1])
    for i in range(start, n):
        now = times[i]
        width = _width(atr[i], tick)
        # ----------------------------------------
        # 発注済みの元注文を最優先で執行する。将来の追加も発注済みなら消さない。
        while fi < count and int(rows[fill_order[fi], 0]) <= i:
            k = fill_order[fi]
            j = ticket[k]
            if issued[k]:
                q = effective[k]
                assert valid[i]
                assert int(rows[k, 0]) == i
                assert q > 0
                if rows[k, 7] > 0.:
                    actual[j] += q
                    if not np.isfinite(initial_price):
                        initial_price = rows[k, 5]
                else:
                    reserved[j] -= q
                    actual[j] -= q
                    assert actual[j] >= 0 and reserved[j] >= 0
                result[nr, :10] = rows[k]
                result[nr, 4] = q
                result[nr, 9] = q * fee10 // 10
                result[nr, 10] = original_indices[k]
                nr += 1
                filled[k] = True
                pending -= 1
            fi += 1
        # ----------------------------------------
        # 独自返済も発注した後の自己次正常原行だけで成立する。
        if valid[i]:
            for j in range(ticket_count):
                q = synth_qty[j]
                if q > 0 and i > synth_decision[j]:
                    px = bid[i] if side > 0 else ask[i]
                    result[nr, 0] = i
                    result[nr, 1] = synth_decision[j]
                    result[nr, 2] = parent
                    result[nr, 3] = -side
                    result[nr, 4] = q
                    result[nr, 5] = px
                    result[nr, 6] = synth_reason[j]
                    result[nr, 7] = 0
                    result[nr, 8] = uid_values[j]
                    result[nr, 9] = q * fee10 // 10
                    result[nr, 10] = 1.e12 + nr
                    nr += 1
                    actual[j] -= q
                    assert actual[j] >= 0
                    synth_qty[j] = 0
        gain = 0.
        if valid[i] and np.isfinite(initial_price):
            liquidation = bid[i] if side > 0 else ask[i]
            gain = side * (liquidation - initial_price) / initial_width
            if np.sum(actual) > 0:
                best = max(best, gain)
        # ----------------------------------------
        # この行で初めて届いた元通知を処理する。元返済は独自判断より優先する。
        while di < count and int(rows[decision_order[di], 1]) <= i:
            k = decision_order[di]
            j = ticket[k]
            q = int(rows[k, 4])
            assert int(rows[k, 1]) == i
            assert int(rows[k, 0]) > i
            use = 0
            if rows[k, 7] > 0.:
                virtual[j] += q
                if not decided:
                    assert int(rows[k, 3]) == side
                    initial_width = width
                    reason = _gate(a[i], now, side, width, gate, settings[4], gap)
                    admitted = reason == 0
                    decided = True
                    trace[nt] = np.array([i, parent, 1, side, int(admitted), reason,
                                          q if admitted else 0, 0., 0., initial_width, pending, now])
                    nt += 1
                if admitted and not blocked:
                    use = q
                elif admitted:
                    trace[nt] = np.array([i, parent, 4, side, 0, 14308, q,
                                          gain, best, initial_width, pending, now])
                    nt += 1
            else:
                old_virtual = virtual[j]
                assert old_virtual >= q
                available = actual[j] - reserved[j] - synth_qty[j]
                assert available >= 0
                if admitted and old_virtual > 0:
                    left = int(np.floor(available * (old_virtual - q) / old_virtual + .5))
                    use = available - left
                    reserved[j] += use
                virtual[j] -= q
            effective[k] = use
            if use > 0:
                issued[k] = True
                pending += 1
            di += 1
        # ----------------------------------------
        # 逆流は欠測・異常気配・十五秒超の間隔で持続を切る。
        quantity = int(np.sum(actual))
        if mode > 0 and admitted and quantity > 0 and not full_done:
            if i > start and times[i] - times[i - 1] > gap:
                since = -np.inf
            bad = valid[i] and _adverse(a[i], ma20[i], now, side, width,
                                         mode, settings[5], settings[6], gap)
            if bad:
                if not np.isfinite(since):
                    since = now
            else:
                since = -np.inf
            if intent == 0 and np.isfinite(since) and now - since >= hold:
                action = 2
                if mode == 4:
                    if gain <= -settings[7] or (half_done and gain <= 0.):
                        action = 2
                    elif not half_done and best >= settings[8] and best - gain >= settings[9] and quantity >= 2:
                        action = 1
                    else:
                        action = 0
                if action > 0:
                    intent = action
                    blocked = True
                    intent_reason = 14307 if mode == 5 else 14302 + mode
                    trace[nt] = np.array([i, parent, 2, side, action, intent_reason,
                                          quantity, gain, best, initial_width, pending, now])
                    nt += 1
            # ----------------------------------------
            # 元の予約が全て成立してから残玉を閉じる。新規予約の都合のよい取消はしない。
            if intent > 0 and pending == 0 and np.sum(synth_qty) == 0:
                to_close = quantity if intent == 2 else quantity // 2
                planned = to_close
                for j in range(ticket_count - 1, -1, -1):
                    q = min(actual[j], to_close)
                    if q:
                        synth_qty[j] = q
                        synth_decision[j] = i
                        synth_reason[j] = intent_reason
                        to_close -= q
                if planned:
                    trace[nt] = np.array([i, parent, 3, side, intent, intent_reason,
                                          planned, gain, best, initial_width, pending, now])
                    nt += 1
                if intent == 2:
                    full_done = True
                else:
                    half_done = True
                intent = 0
        elif quantity == 0:
            since = -np.inf
        assert np.min(actual) >= 0
        if di == count and pending == 0 and np.sum(synth_qty) == 0 and np.sum(actual) == 0:
            break
    # 全保存通知・約定を収める入力では未返済を容認しない。途中までの因果検査は別扱い。
    if np.max(rows[:, 0]) < n:
        assert np.sum(actual) == 0 and pending == 0 and np.sum(synth_qty) == 0
    return result[:nr], trace[:nt]


def replay(data, baseline, history, config):
    """
    機能: 保存基本枠全親へ当時情報だけの入口拒否・途中返済を適用する。
    引数: data(dict)はready/quotes/features30、baseline(ndarray[N,10])は保存通知、
          history(ndarray[T,15])は公開済みMA等、config(dict)は事前固定条件。
    返り値: tuple[ndarray[M,10],ndarray[K,12]]は約定とTRACE_COLUMNSの判断記録。
    """
    baseline = np.asarray(baseline, dtype=np.float64).reshape(-1, 10)
    if not len(baseline):
        return baseline.copy(), np.empty((0, 12))
    ready = data['ready']
    times = np.asarray(ready['time_s'], dtype=np.float64)
    assert np.all(np.diff(times) >= 0.)
    assert np.all(baseline[:, 0] > baseline[:, 1])
    assert np.all(baseline[:, 4] > 0.)
    if config['gate'] == config['management'] == 0:
        return baseline[baseline[:, 0] < len(times)].copy(), np.empty((0, 12))
    quotes = data['quotes']
    bid, ask = np.asarray(quotes['bid']), np.asarray(quotes['ask'])
    valid = (np.asarray(quotes['quote_valid'], dtype=np.bool_) & np.isfinite(bid)
             & np.isfinite(ask) & (bid > 0.) & (ask > bid))
    a = np.asarray(data['features'], dtype=np.float64)
    assert a.shape[0] == len(times) and a.shape[1] >= 28
    assert history.shape[0] == len(times) and history.shape[1] == 15
    settings = np.array([config['gate'], config['management'], config['confirmation_seconds'],
                         config['quote_gap_seconds'], config['own_entry_reverse_r'],
                         config['own_position_reverse_r'], config['short_reverse_r'],
                         config['loss_full_r'], config['protected_progress_r'],
                         config['protected_giveback_r']], dtype=float)
    fee10 = 385 if ready['symbol'] == 'NK225' else 418
    orders, traces = [], []
    for parent in np.unique(baseline[:, 2]):
        indices = np.flatnonzero(baseline[:, 2] == parent)
        rows = baseline[indices]
        if np.min(rows[:, 1]) >= len(times):
            continue
        assert rows[np.argmin(rows[:, 1]), 7] == 1.
        side = rows[np.argmin(rows[:, 1]), 3]
        assert np.all(rows[rows[:, 7] == 1, 3] == side)
        assert np.all(rows[rows[:, 7] == 0, 3] == -side)
        # UIDの初回登場順を保持し、半減は後から加わったUIDを先に閉じる。
        uids = list(dict.fromkeys(rows[:, 8]))
        mapping = {uid: j for j, uid in enumerate(uids)}
        tickets = np.array([mapping[uid] for uid in rows[:, 8]], dtype=np.int64)
        o, t = _parent(times, bid, ask, valid, np.asarray(ready['atr']), a,
                       np.asarray(history[:, 1]), float(ready['tick']), rows,
                       indices.astype(np.int64), tickets, len(uids), settings, fee10)
        orders.append(o)
        traces.append(t)
    joined = np.concatenate(orders) if orders else np.empty((0, 11))
    result = joined[np.lexsort((joined[:, 10], joined[:, 0])), :10] if len(joined) else joined[:, :10]
    trace = np.concatenate(traces) if traces else np.empty((0, 12))
    if len(trace):
        trace = trace[np.argsort(trace[:, 0], kind='stable')]
    return result, trace
