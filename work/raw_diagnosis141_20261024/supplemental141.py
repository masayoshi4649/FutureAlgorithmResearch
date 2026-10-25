"""補完の時間軸矛盾を、保存主担当の判断行と独立した新規・返済状態で比較する。"""

import numpy as np
from numba import njit


EXTRA_PARENT = 4_000_000
NOTE_COLUMNS = ('原行', '種類', '親ID', '方向', '枚数', '値1', '値2', '値3')
NOTE_KINDS = {1: '保存主担当を採用', 2: '補完保有又は予約で主担当を見送り',
              3: '補完の新規判断', 4: '補完の返済判断', 5: '補完の全返済完了',
              6: '補完入口の待機状態変更'}


def configurations():
    """
    機能: 始値票の補正、20分方向への切替、途中の逆行返済の3条件を固定する。
    引数: なし。
    返り値: list[dict]はN1/N2/N3。日経夜間だけの比較を想定する。
    """
    names = ('始値方向を残し5分支持を待つ', '20分合議を優先し5分逆行を待つ',
             '20分合議と二市場の逆行継続返済')
    return [dict(id=f'N{i+1:02d}', name=name, mode=i+1, quantity=5, cap=10,
                 activation_after_us_seconds=1800., entry_cutoff_seconds=600.,
                 trail_start_r=.75, trail_width_r=.5, stop_r=1., minimum_ticks=8.,
                 band_fraction=.5, spread_r=.5, adverse_seconds=15., gap_seconds=15.,
                 multiplier=100., fee_tenths=385) for i, name in enumerate(names)]


@njit(cache=True)
def original_direction(h, mid):
    """
    機能: U06の始値優先方向式をそのまま再現する。
    引数: h(ndarray[15])、mid(float)は公開履歴と中値。
    返り値: intは買い1・売り-1・不成立0。
    """
    score = np.sign(mid-h[8])+np.sign(h[13])
    if score == 0.:
        score = np.sign(h[7])+np.sign(h[11])
    if score == 0.:
        score = h[7]
    if score == 0.:
        score = mid-h[8]
    return 1 if score > 0. else (-1 if score < 0. else 0)


@njit(cache=True)
def entry_direction(h, mid, mode):
    """
    機能: 当時既知の方向と5分支持を照合し、矛盾がある間は方向0にする。
    引数: h(ndarray[15])、mid(float)、mode(int)は公開履歴・中値・比較方式。
    返り値: tuple[int,int]は許可方向と待機理由。1は方向不一致、2は5分支持不足。
    """
    if mode == 1:
        side = original_direction(h, mid)
        if side == 0:
            return 0, 1
        if side*h[6] <= 0. or side*h[10] <= 0.:
            return 0, 2
        return side, 0
    own, peer = np.sign(h[7]), np.sign(h[11])
    if own == 0. or own != peer:
        return 0, 1
    side = int(own)
    if side*h[6] < 0. or side*h[10] < 0. or (h[6] == 0. and h[10] == 0.):
        return 0, 2
    return side, 0


@njit(cache=True)
def _note(notes, count, row, kind, parent, side, quantity, a, b, c):
    """
    機能: 当時の採否・待機・返済判断を診断列へ保存する。
    引数: notes(ndarray)、count/row/kind/parent/side/quantity(int)、a/b/c(float)は診断値。
    返り値: intは保存後の件数。
    """
    assert count < len(notes)
    notes[count] = np.array([row, kind, parent, side, quantity, a, b, c])
    return count+1


@njit(cache=True)
def _simulate(times, bid, ask, good, atr, history, market, core, parent_index,
              decision_order, fill_order, parent_count, activation, end, tick, p):
    """
    機能: 保存主担当を判断時点で採否し、新補完を次の自己正常原行へ発注する。
    引数: 原行・保存注文・索引(ndarray)、parent_count(int)、activation/end/tick(float)、p(ndarray)。
    返り値: tuple[ndarray,ndarray]は10列注文と診断。新補完の損益・出口を旧玉から移さない。
    """
    (mode, quantity, cap, cutoff, trail_start, trail_width, stop, minimum_ticks,
     band_fraction, spread_r, adverse_seconds, gap_seconds, multiplier, fee_tenths) = p
    mode, quantity, cap, fee_tenths = int(mode), int(quantity), int(cap), int(fee_tenths)
    orders = np.zeros((len(core)+2, 10))
    notes = np.zeros((max(2048, len(times)//8), 8))
    accepted = np.zeros(parent_count, np.int64)
    active_core = -1
    core_held = 0
    core_entered = False
    attempted = False
    held = 0
    pending = 0
    source = -1
    side = 0
    risk = entry = 0.
    floor = -np.inf
    mfe = 0.
    reason = 0
    adverse_since = -np.inf
    previous_wait = -1
    dp = fp = oc = nc = 0
    for i in range(len(times)):
        now = times[i]
        valid = good[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0. < bid[i] < ask[i]
        gap = i > 0 and now-times[i-1] > gap_seconds
        if gap:
            adverse_since = -np.inf
        # ----------------------------------------
        # 保存主担当は新規判断を承認した親だけを約定時点に取り込む。
        while fp < len(fill_order) and int(core[fill_order[fp], 0]) == i:
            k = fill_order[fp]
            fp += 1
            pi = parent_index[k]
            if accepted[pi] != 1:
                continue
            row = core[k]
            assert held == 0 and pending == 0 and active_core == pi
            assert valid and abs(row[5]-(ask[i] if row[3] > 0 else bid[i])) < 1.e-7
            orders[oc] = row
            oc += 1
            if row[7] == 1:
                assert core_held == 0
                core_held = int(row[4])
                core_entered = True
            else:
                core_held -= int(row[4])
                assert core_held >= 0
                if core_held == 0:
                    active_core = -1
        # 既発注を時刻境界で取り消した扱いにしない。新約定後に場末返済へ移る。
        if pending and valid and i > source:
            fee = quantity*fee_tenths//10
            if pending == 1:
                assert active_core < 0 and core_held == 0
                held = quantity
                entry = ask[i] if side > 0 else bid[i]
                floor = -stop*risk
                mfe = 0.
                orders[oc] = np.array([i, source, EXTRA_PARENT, side, quantity, entry, 1410+mode, 1, 999, fee])
            else:
                price = bid[i] if side > 0 else ask[i]
                assert held == quantity
                orders[oc] = np.array([i, source, EXTRA_PARENT, -side, quantity, price, reason, 0, 999, fee])
                held = 0
                nc = _note(notes, nc, i, 5, EXTRA_PARENT, side, quantity, entry, price, reason)
            oc += 1
            pending = 0
        # ----------------------------------------
        # 未来の主担当開始時刻から補完を早めに降りない。判断が到着した親だけを採否する。
        while dp < len(decision_order) and int(core[decision_order[dp], 1]) == i:
            k = decision_order[dp]
            dp += 1
            pi = parent_index[k]
            assert accepted[pi] == 0
            allowed = held == 0 and pending == 0 and active_core < 0
            accepted[pi] = 1 if allowed else -1
            if allowed:
                active_core = pi
            nc = _note(notes, nc, i, 1 if allowed else 2, int(core[k, 2]), int(core[k, 3]),
                       int(core[k, 4]), held, pending, now)
        # ----------------------------------------
        # 停止と利益追尾は新建値と新判断Rで開始。N3だけ二市場逆行の継続を追加する。
        if held and not pending:
            close_reason = 93 if now >= end else 0
            if valid and not close_reason:
                mark = bid[i] if side > 0 else ask[i]
                gain = side*(mark-entry)
                mfe = max(mfe, gain)
                if mfe >= trail_start*risk:
                    floor = max(floor, mfe-trail_width*risk)
                if gain <= floor:
                    close_reason = 32 if floor < 0. else 70
                inverse = mode == 3 and market[i, 11] == 1.
                for col in (4, 5, 6, 7):
                    inverse = inverse and np.isfinite(market[i, col]) and side*market[i, col] < 0.
                if inverse:
                    if not np.isfinite(adverse_since):
                        adverse_since = now
                    if now-adverse_since >= adverse_seconds and not close_reason:
                        close_reason = 1413
                else:
                    adverse_since = -np.inf
            elif not valid:
                adverse_since = -np.inf
            if close_reason:
                pending, source, reason = 2, i, close_reason
                nc = _note(notes, nc, i, 4, EXTRA_PARENT, side, held, risk, floor, close_reason)
        known = valid and np.isfinite(history[i]).all() and np.isfinite(atr[i]) and atr[i] > 0.
        if not attempted and not core_entered and not held and not pending and active_core < 0 and known and activation <= now < end-cutoff:
            mid = (bid[i]+ask[i])*.5
            chosen, wait = entry_direction(history[i], mid, mode)
            r = max(atr[i], band_fraction*(history[i, 3]-history[i, 4]), minimum_ticks*tick)
            if chosen and ask[i]-bid[i] > spread_r*r:
                chosen, wait = 0, 3
            if wait != previous_wait:
                nc = _note(notes, nc, i, 6, EXTRA_PARENT, chosen, quantity, wait, history[i, 6], history[i, 10])
                previous_wait = wait
            if chosen:
                pending, source, side, risk, attempted = 1, i, chosen, r, True
                adverse_since = -np.inf
                nc = _note(notes, nc, i, 3, EXTRA_PARENT, side, quantity, risk, mid, now)
        assert 0 <= core_held <= cap and 0 <= held <= cap
        assert core_held+held <= cap
    assert held == 0 and pending == 0 and core_held == 0 and active_core < 0, '終端の返済又は保存主担当の約定が不足'
    return orders[:oc], notes[:nc]


def replay(ready, quotes, history, market, baseline_core, config):
    """
    機能: 保存B5主担当だけを固定し、新補完の入口から出口までを別状態で計算する。
    引数: ready/quotes/config(dict)、history(ndarray[n,15])、market(ndarray[n,12])、baseline_core(ndarray[m,10])。
    返り値: tuple[ndarray,list[dict]]は共通会計可能な注文とJSON保存可能な診断。補完UID999を含む入力は拒否する。
    """
    c = config
    assert ready['session'].endswith('_Night') and ready['symbol'] == 'NK225'
    assert c['mode'] in (1, 2, 3) and 1 <= c['quantity'] <= c['cap'] <= 10
    core = np.asarray(baseline_core, dtype=float)
    assert core.ndim == 2 and core.shape[1] == 10
    assert np.all(core[:, 8] != 999) and np.all(core[:, 2] != EXTRA_PARENT)
    assert len(history) == len(market) == len(ready['time_s'])
    ids, mapping = np.unique(core[:, 2], return_inverse=True)
    opening = np.flatnonzero(core[:, 7] == 1)
    assert len(opening) == len(ids)
    for parent in ids:
        rows = core[core[:, 2] == parent]
        assert np.count_nonzero(rows[:, 7] == 1) == 1
        assert rows[0, 7] == 1 and np.all(rows[:, 1] < rows[:, 0])
        assert rows[0, 4] == rows[rows[:, 7] == 0, 4].sum()
        assert np.all(rows[:, 4] <= c['cap'])
    decision_order = opening[np.argsort(core[opening, 1], kind='stable')]
    fill_order = np.argsort(core[:, 0], kind='stable')
    keys = ('mode', 'quantity', 'cap', 'entry_cutoff_seconds', 'trail_start_r', 'trail_width_r',
            'stop_r', 'minimum_ticks', 'band_fraction', 'spread_r', 'adverse_seconds', 'gap_seconds',
            'multiplier', 'fee_tenths')
    p = np.array([c[k] for k in keys], dtype=float)
    orders, notes = _simulate(np.asarray(ready['time_s']), np.asarray(quotes['bid']), np.asarray(quotes['ask']),
        np.asarray(quotes['quote_valid']), np.asarray(ready['atr']), np.asarray(history), np.asarray(market),
        core, mapping, decision_order, fill_order, len(ids), ready['us_open']+c['activation_after_us_seconds'],
        ready['limit'], ready['tick'], p)
    assert np.isfinite(notes).all()
    records = [{name: int(value) if j < 5 else float(value) for j, (name, value) in enumerate(zip(NOTE_COLUMNS, row))}
               for row in notes]
    return orders, records
