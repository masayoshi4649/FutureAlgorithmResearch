"""機能: 純両建ての同一発注イベントを、元玉縮小・復帰の対照へ写像する。"""

from collections import deque
import math

import numpy as np


ORDER_COLUMNS = ('約定行', '判断行', '組', '売買方向', '枚数', '価格', '理由', '新規', '役割')
TRADE_COLUMNS = ('組', '新規行', '返済行', '建玉方向', '枚数', '建値', '返済値',
                 '新規料金', '返済料金', '料金前損益', '収支', '役割')


def _fee(quantity, fee_unit):
    """機能: 注文全体の片道料金を1円未満切捨てで算出する。

    引数: quantity(int)は注文数量、fee_unit(float)は1枚の片道料金。
    返り値: intの料金。数量0の注文は0。
    """
    return math.floor(quantity * fee_unit + 1e-8)


def _allocate(total_fee, before, quantity, total_quantity):
    """機能: 累積使用数量の整数比率差分で注文料金を決済明細へ配賦する。

    引数: total_fee/before/quantity/total_quantity(int)は合計料金・既配賦枚数・
    今回枚数・元注文全枚数。返り値: intの今回配賦料金。
    """
    return (total_fee * (before + quantity) // total_quantity
            - total_fee * before // total_quantity)


def _mark(times, bid, ask, orders, value, fee_unit):
    """機能: 注文差分を加算・累積し、全原本行の清算気配時価をベクトル計算する。

    引数: times/bid/ask(ndarray)は原本時刻・買売気配、orders(ndarray9列)は注文、
    value/fee_unit(float)はポイント倍率・片道料金。
    返り値: tuple(ndarray時価,dict統計)。全原本行をPythonのforで巡回しない。
    """
    n = len(times)
    if n == 0:
        return np.empty(0, dtype=np.float64), {
            '最大買い保有': 0, '最大売り保有': 0, '最大合計保有': 0,
            '最大絶対ネット保有': 0, '終端買い保有': 0, '終端売り保有': 0,
            '新規手数料': 0, '返済手数料': 0, '合計手数料': 0,
        }
    cash_delta = np.zeros(n, dtype=np.float64)
    long_delta = np.zeros(n, dtype=np.int64)
    short_delta = np.zeros(n, dtype=np.int64)
    entry_fee = exit_fee = 0
    if len(orders):
        rows = orders[:, 0].astype(np.int64)
        side = orders[:, 3].astype(np.int64)
        quantity = orders[:, 4].astype(np.int64)
        new = orders[:, 7].astype(np.int64)
        fees = np.floor(quantity * fee_unit + 1e-8).astype(np.int64)
        cash = -side * quantity * orders[:, 5] * value - fees
        np.add.at(cash_delta, rows, cash)
        long_change = np.where(new == 1, np.where(side == 1, quantity, 0),
                               np.where(side == -1, -quantity, 0))
        short_change = np.where(new == 1, np.where(side == -1, quantity, 0),
                                np.where(side == 1, -quantity, 0))
        np.add.at(long_delta, rows, long_change)
        np.add.at(short_delta, rows, short_change)
        entry_fee = int(fees[new == 1].sum())
        exit_fee = int(fees[new == 0].sum())
    cash = np.cumsum(cash_delta)
    long_quantity = np.cumsum(long_delta)
    short_quantity = np.cumsum(short_delta)
    if np.any(long_quantity < 0) or np.any(short_quantity < 0):
        raise ValueError('縮小対照の返済数量が保有数量を超えています。')
    valid = (np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask >= bid))
    source_rows = np.maximum.accumulate(np.where(valid, np.arange(n), -1))
    safe_rows = np.maximum(source_rows, 0)
    last_bid = np.where(source_rows >= 0, bid[safe_rows], 0.0)
    last_ask = np.where(source_rows >= 0, ask[safe_rows], 0.0)
    curve = cash + long_quantity * last_bid * value - short_quantity * last_ask * value
    metadata = {
        '最大買い保有': int(long_quantity.max()),
        '最大売り保有': int(short_quantity.max()),
        '最大合計保有': int((long_quantity + short_quantity).max()),
        '最大絶対ネット保有': int(np.abs(long_quantity - short_quantity).max()),
        '終端買い保有': int(long_quantity[-1]),
        '終端売り保有': int(short_quantity[-1]),
        '新規手数料': entry_fee,
        '返済手数料': exit_fee,
        '合計手数料': entry_fee + exit_fee,
    }
    return curve, metadata


def pair(times, bid, ask, orders, cap, value, fee_unit):
    """機能: 両建て管理の発注列を同じ観測・価格の元玉縮小復帰へ写像する。

    引数: times/bid/ask(ndarray)は原本時刻・買売気配、orders(ndarray9列)は
    [約定行,判断行,組,売買方向,枚数,価格,理由,新規,役割]、cap(int)は片方向上限、
    value/fee_unit(float)はポイント倍率・片道料金。役割0元玉/1保険。
    返り値: tuple(ndarray9列注文,ndarray12列決済,ndarray時価,dict統計)。
    入口・保険の判断を新たに選ばず、同一fill_i/cidの終了群だけ残ネット玉へ圧縮する。
    終了群は既に確定した同時注文のまとめであり、将来価格を判断条件に用いない。
    FIFO元注文料金・返済注文料金をそれぞれ整数の累積比率差分で完全配賦する。
    """
    times = np.asarray(times, dtype=np.float64)
    bid = np.asarray(bid, dtype=np.float64)
    ask = np.asarray(ask, dtype=np.float64)
    source = np.asarray(orders, dtype=np.float64)
    if source.size == 0:
        source = np.empty((0, 9), dtype=np.float64)
    if source.ndim != 2 or source.shape[1] != 9:
        raise ValueError('入力注文は9列で指定してください。')
    if not (len(times) == len(bid) == len(ask)):
        raise ValueError('時刻と両気配の行数が一致しません。')
    if cap <= 0 or int(cap) != cap or value <= 0 or fee_unit < 0:
        raise ValueError('上限・倍率・片道料金が不正です。')
    if len(source) and np.any(np.diff(source[:, 0]) < 0):
        raise ValueError('入力注文は約定行の昇順で指定してください。')
    # ----------------------------------------
    # Pythonループは注文群とFIFO明細だけ。板原本n行は_markでベクトル計算する。
    mapped = []
    trades = []
    states = {}
    terminal_groups = []
    normal_cover_new = normal_cover_close = 0

    def emit(record, side, quantity, new, state):
        """機能: 写像注文を追記し、FIFOで新規玉または決済明細を生成する。

        引数: record(ndarray9列)、side/quantity/new(int)、state(dict)は組の状態。
        返り値: None。mapped/trades/stateへ反映する。quantity=0なら注文を作らない。
        """
        if quantity == 0:
            return
        row, decision, cid = int(record[0]), int(record[1]), int(record[2])
        if not (0 <= decision < row < len(times)):
            raise ValueError('判断行と約定行の因果順序が不正です。')
        if not (np.isfinite(bid[row]) and np.isfinite(ask[row])
                and bid[row] > 0 and ask[row] >= bid[row]):
            raise ValueError('約定行に有効な両気配がありません。')
        expected_price = ask[row] if side == 1 else bid[row]
        price = float(record[5])
        if not np.isclose(price, expected_price, rtol=0, atol=1e-8):
            raise ValueError('原注文価格が約定行の買ask・売bidと一致しません。')
        order_fee = _fee(quantity, fee_unit)
        mapped.append([row, decision, cid, side, quantity, price,
                       int(record[6]), new, 0])
        if new:
            if side != state['side']:
                raise ValueError('縮小対照の新規方向が元玉方向と異なります。')
            state['lots'].append({'row': row, 'quantity': quantity, 'remaining': quantity,
                                  'price': price, 'fee': order_fee, 'used': 0})
            return
        if side != -state['side']:
            raise ValueError('縮小対照の返済方向が元玉方向と一致しません。')
        if quantity > sum(lot['remaining'] for lot in state['lots']):
            raise ValueError('縮小対照の返済枚数が元玉残数を超えています。')
        remaining = quantity
        used_exit = 0
        while remaining:
            lot = state['lots'][0]
            chunk = min(remaining, lot['remaining'])
            allocated_entry = _allocate(lot['fee'], lot['used'], chunk, lot['quantity'])
            allocated_exit = _allocate(order_fee, used_exit, chunk, quantity)
            gross = state['side'] * (price - lot['price']) * chunk * value
            net = gross - allocated_entry - allocated_exit
            trades.append([cid, lot['row'], row, state['side'], chunk, lot['price'], price,
                           allocated_entry, allocated_exit, gross, net, 0])
            lot['remaining'] -= chunk
            lot['used'] += chunk
            remaining -= chunk
            used_exit += chunk
            if lot['remaining'] == 0:
                state['lots'].popleft()

    offset = 0
    while offset < len(source):
        end = offset + 1
        row, cid = int(source[offset, 0]), int(source[offset, 2])
        while end < len(source) and int(source[end, 0]) == row and int(source[end, 2]) == cid:
            end += 1
        group = source[offset:end]
        terminals = group[(group[:, 8] == 0) & (group[:, 7] == 0)]
        # ----------------------------------------
        # 同一観測の全返済は保険を買い戻してから元玉を売る往復を省き、残数だけ返す。
        if len(terminals):
            if len(terminals) != 1 or cid not in states:
                raise ValueError('元玉終了群が一意でないか、入口がありません。')
            record = terminals[0]
            state = states[cid]
            if (state['ended'] or int(record[4]) != cap
                    or int(record[6]) not in (1, 2, 3, 4, 5, 6)
                    or int(record[3]) != -state['side']):
                raise ValueError('純両建ての元玉全返済形式と一致しません。')
            cover_closes = group[group[:, 8] == 1]
            if np.any(cover_closes[:, 7] != 0):
                raise ValueError('元玉終了と同時に新規保険が登録されています。')
            if int(cover_closes[:, 4].sum()) != state['cover']:
                raise ValueError('終了時の保険返済数が保険残数と一致しません。')
            net_quantity = sum(lot['remaining'] for lot in state['lots'])
            if net_quantity != cap - state['cover']:
                raise ValueError('元玉残数が上限から保険残数を引いた値と異なります。')
            source_fees = sum(_fee(int(x[4]), fee_unit) for x in group)
            saved_fees = source_fees - _fee(net_quantity, fee_unit)
            saved_spread = state['cover'] * (ask[row] - bid[row]) * value
            terminal_groups.append({
                '組': cid, '約定行': row, '残保険枚数': state['cover'],
                '対照返済枚数': net_quantity, '手数料節約円': saved_fees,
                '気配差節約円': saved_spread,
                '理論終了収支差_縮小側引く両建て側': saved_fees + saved_spread,
            })
            emit(record, -state['side'], net_quantity, 0, state)
            state['ended'] = True
            state['cover'] = 0
        else:
            for record in group:
                side, quantity = int(record[3]), int(record[4])
                new, role = int(record[7]), int(record[8])
                if side not in (-1, 1) or quantity <= 0 or new not in (0, 1) or role not in (0, 1):
                    raise ValueError('注文の方向・数量・新規区分・役割が不正です。')
                if role == 0:
                    if new != 1 or quantity != cap or cid in states:
                        raise ValueError('純両建ての初回元玉は上限一括・組ごとに1回です。')
                    state = {'side': side, 'cover': 0, 'lots': deque(), 'ended': False}
                    states[cid] = state
                    emit(record, side, quantity, 1, state)
                else:
                    if cid not in states or states[cid]['ended']:
                        raise ValueError('開始前または終了後の保険注文があります。')
                    state = states[cid]
                    if new:
                        if side != -state['side'] or state['cover'] + quantity > cap:
                            raise ValueError('保険方向または片方向保有上限が不正です。')
                        emit(record, side, quantity, 0, state)
                        state['cover'] += quantity
                        normal_cover_new += quantity
                    else:
                        if side != state['side'] or quantity > state['cover']:
                            raise ValueError('保険返済方向または保険残数が不正です。')
                        emit(record, side, quantity, 1, state)
                        state['cover'] -= quantity
                        normal_cover_close += quantity
        offset = end
    # ----------------------------------------
    result_orders = np.asarray(mapped, dtype=np.float64).reshape((-1, 9))
    result_trades = np.asarray(trades, dtype=np.float64).reshape((-1, 12))
    curve, metadata = _mark(times, bid, ask, result_orders, value, fee_unit)
    if metadata['最大買い保有'] > cap or metadata['最大売り保有'] > cap:
        raise ValueError('縮小対照が片方向最大保有上限を超えました。')
    metadata.update({
        '方式': '純両建ての同判断・同約定時刻の縮小復帰対照',
        '元注文数': len(source), '対照注文数': len(result_orders),
        '決済明細数': len(result_trades),
        '通常保険新規を元玉返済へ変換した枚数': normal_cover_new,
        '通常保険返済を元玉新規へ変換した枚数': normal_cover_close,
        '完了組数': sum(state['ended'] for state in states.values()),
        '継続組数': sum(not state['ended'] for state in states.values()),
        '終端仮想保険枚数': sum(state['cover'] for state in states.values()),
        '終了群': terminal_groups,
        '終了群の理論節約合計円': sum(x['理論終了収支差_縮小側引く両建て側']
                                    for x in terminal_groups),
        '未配賦新規手数料': sum(lot['fee'] - _allocate(lot['fee'], 0, lot['used'], lot['quantity'])
                                for state in states.values() for lot in state['lots']),
    })
    if metadata['継続組数'] == 0 and len(curve):
        expected = float(result_trades[:, 10].sum()) if len(result_trades) else 0.0
        if not np.isclose(curve[-1], expected, rtol=0, atol=1e-6):
            raise ValueError('全返済後の時価と決済明細の合計が一致しません。')
        if metadata['未配賦新規手数料'] != 0:
            raise ValueError('全返済後に未配賦新規手数料が残っています。')
    return result_orders, result_trades, curve, metadata
