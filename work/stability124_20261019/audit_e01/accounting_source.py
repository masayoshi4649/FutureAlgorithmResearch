"""旧119hの独立保存会計四関数だけを、構文不変で所有する。"""

from decimal import Decimal, ROUND_FLOOR

import hashlib
import numpy as np


MULTIPLIERS = {"TOPIX": 1000., "NK225": 10.}
FEES = {"TOPIX": "41.8", "NK225": "11"}
CAPS = {"TOPIX": 10, "NK225": 20}


class ArithmeticChecks:
    """独立会計の有限比較と検査件数だけを保持する。"""

    def __init__(self) -> None:
        """
        機能: 独立検査件数をゼロで初期化する。
        引数: なし。
        返り値: None。
        """
        self.CHECKS = 0

    def check(self, condition: bool, note: str) -> None:
        """
        機能: 独立期待値の一致を検査する。
        引数: condition (bool) 条件、note (str) 検査内容。
        返り値: None。
        """
        assert bool(condition), note
        self.CHECKS += 1

    def near(self, actual: object, expected: object, note: str) -> None:
        """
        機能: 未知と有限値を分け、旧検査と同じ許容差で比較する。
        引数: actual/expected (object) 比較対象、note (str) 検査内容。
        返り値: None。
        """
        if actual is None or expected is None:
            self.check(actual is None and expected is None, note)
        else:
            self.check(np.allclose(actual, expected, atol=1e-5, rtol=1e-10, equal_nan=True), note)

    def sha(self, payload: bytes) -> str:
        """
        機能: 所有資料の同一性を求める。
        引数: payload (bytes) 内容。
        返り値: str SHA256。
        """
        return hashlib.sha256(payload).hexdigest()


audit = ArithmeticChecks()


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 一つの注文又はUID残数量に対する料金を独立に切り捨てる。
    引数: quantity(int)、symbol(str) は実枚数と商品。
    返り値: int は円単位の料金。異なるUIDの返済予定料は合算切捨てしない。
    """
    return int((Decimal(int(quantity)) * Decimal(FEES[symbol])).to_integral_value(rounding=ROUND_FLOOR))


def compare(actual: object, expected: object, label: str) -> None:
    """
    機能: 日本語台帳のdict/list/数値を独立値と再帰照合する。
    引数: actual/expected(object)、label(str) は対象と説明。
    返り値: None。未保存値を零で補わない。
    """
    if isinstance(expected, dict):
        for key, value in expected.items():
            audit.check(key in actual, label + ':' + key)
            compare(actual[key], value, label + ':' + key)
    elif isinstance(expected, list):
        audit.check(len(actual) == len(expected), label + ':件数')
        for a, e in zip(actual, expected):
            compare(a, e, label)
    elif isinstance(expected, (str, bool)) or expected is None:
        audit.check(actual == expected, label)
    else:
        audit.near(actual, expected, label)


def reconstruct(account: dict, ledger: dict) -> dict:
    """
    機能: 保存された実注文だけからUID/FIFO、親、全行時価と料金を独立復元する。
    引数: account(dict) は新入力、ledger(dict) は同じ新台帳。
    返り値: dict は独立場集計。入口/出口規則の金融再実行は行わない。
    """
    symbol, record, quotes = account['symbol'], account['record'], account['quotes']
    orders, uids, targets = ledger['orders'], ledger['order_uids'], ledger['exit_target_uids']
    n, multiplier = len(record['price']), MULTIPLIERS[symbol]
    audit.check(n > 0 and orders.shape == (len(uids), 8) and targets.shape == uids.shape, '実注文8列とUID/返済先shape')
    audit.near(record['seq'], quotes['seq'], '入力と気配は同原seq')
    audit.near(record['time_s'], quotes['time_s'], '入力と気配は同価格時計')
    audit.check(np.all(np.diff(record['seq']) > 0) and np.all(np.diff(record['time_s']) >= 0), '原seq単調と価格時計非減少')
    valid = quotes['quote_valid'] & np.isfinite(quotes['bid']) & np.isfinite(quotes['ask']) & (quotes['bid'] > 0) & (quotes['ask'] > quotes['bid'])
    audit.check(np.isfinite(orders).all() and np.all(np.diff(orders[:, 0]) >= 0), '有限で原行順の実注文')
    cash_delta, paid_delta = np.zeros(n), np.zeros(n)
    long_delta, short_delta, long_basis_delta, short_basis_delta = (np.zeros(n) for _ in range(4))
    reserved = np.zeros(n)
    states, parents, legs = {}, {}, []
    order_fees = []
    cursor, previous, reserve = 0, 0, 0
    while cursor < len(orders):
        row = int(orders[cursor, 0])
        audit.check(previous <= row < n, '注文原行範囲')
        reserved[previous:row] = reserve
        while cursor < len(orders) and int(orders[cursor, 0]) == row:
            order = orders[cursor]
            source, cid, side, quantity, new = map(int, (order[1], order[2], order[3], order[4], order[7]))
            uid, target = int(uids[cursor]), int(targets[cursor])
            audit.near(order[[0, 1, 2, 3, 4, 6, 7]], np.rint(order[[0, 1, 2, 3, 4, 6, 7]]), '注文離散欄は整数')
            audit.check(0 <= source < row and side in (-1, 1) and new in (0, 1) and 0 < quantity <= CAPS[symbol], '前原行判断・売買・実数量上限')
            audit.check(valid[row], '実注文は当時正常気配')
            audit.near(order[5], quotes['ask' if side == 1 else 'bid'][row], '実価格は買ask/売bid')
            audit.check(record['time_s'][source] <= record['time_s'][row], '同clock原行順を守る')
            cost = fee(quantity, symbol)
            paid_delta[row] += cost
            cash_delta[row] -= cost
            order_fees.append(cost)
            if cid not in parents:
                audit.check(new == 1, '親は実新規から生成')
                parents[cid] = dict(親=cid, 新規行=row, 最終返済行=row, 方向=side, 枚数=0, 費用=0, 粗損益=0.)
            parents[cid]['費用'] += cost
            if new:
                audit.check(uid >= 0 and uid not in states and target == -1, '実新規UIDの一意性')
                states[uid] = dict(cid=cid, side=side, quantity=quantity, remaining=quantity, row=row, price=order[5], fee=cost)
                parents[cid]['枚数'] += quantity
                if side == 1:
                    long_delta[row] += quantity
                    long_basis_delta[row] += quantity * order[5]
                else:
                    short_delta[row] += quantity
                    short_basis_delta[row] += quantity * order[5]
            else:
                audit.check(uid == -1, '返済注文自身に新UIDを付けない')
                remaining = quantity
                for current, state in states.items():
                    if (target >= 0 and current != target) or state['cid'] != cid or state['side'] != -side or not state['remaining']:
                        continue
                    q = min(remaining, state['remaining'])
                    gross = state['side'] * (order[5] - state['price']) * q * multiplier
                    infee, outfee = state['fee'] * q / state['quantity'], cost * q / quantity
                    legs.append(dict(uid=current, 親=cid, 方向=state['side'], 枚数=q, 新規行=state['row'], 返済行=row,
                        新規価格=state['price'], 返済価格=order[5], 粗損益=gross, 新規料金配分=infee, 返済料金配分=outfee,
                        収支=gross - infee - outfee, 返済注文=cursor, 理由=int(order[6])))
                    state['remaining'] -= q
                    remaining -= q
                    cash_delta[row] += gross
                    parents[cid]['粗損益'] += gross
                    if state['side'] == 1:
                        long_delta[row] -= q
                        long_basis_delta[row] -= q * state['price']
                    else:
                        short_delta[row] -= q
                        short_basis_delta[row] -= q * state['price']
                    if remaining == 0:
                        break
                audit.check(remaining == 0, '返済超過なし・UID指定又はFIFO')
                parents[cid]['最終返済行'] = row
            cursor += 1
        reserve = sum(fee(state['remaining'], symbol) for state in states.values() if state['remaining'])
        previous = row
    reserved[previous:] = reserve
    long_qty, short_qty = np.cumsum(long_delta), np.cumsum(short_delta)
    audit.check(np.all((long_qty >= 0) & (long_qty <= CAPS[symbol])) and np.all((short_qty >= 0) & (short_qty <= CAPS[symbol])), '全原行の片方向保有上限')
    q = np.maximum.accumulate(np.where(valid, np.arange(n), -1))
    audit.check(not np.any((q < 0) & ((long_qty > 0) | (short_qty > 0))), '正常気配前の未知建玉時価を作らない')
    bid, ask = np.where(q >= 0, quotes['bid'][np.maximum(q, 0)], 0.), np.where(q >= 0, quotes['ask'][np.maximum(q, 0)], 0.)
    cash = np.cumsum(cash_delta)
    unrealized = ((long_qty * bid - np.cumsum(long_basis_delta)) + (np.cumsum(short_basis_delta) - short_qty * ask)) * multiplier
    equity, paid = cash + unrealized, np.cumsum(paid_delta)
    for field, values in dict(equity_yen=equity, liquidation_yen=equity-reserved, reserved_exit_fees=reserved,
                              long_qty=long_qty, short_qty=short_qty, cumulative_fees=paid).items():
        audit.near(ledger[field], values, '全原行の独立会計:' + field)
    audit.near(ledger['order_fees'], order_fees, '全注文の支払料金')
    audit.check(long_qty[-1] == short_qty[-1] == reserved[-1] == 0 and all(state['remaining'] == 0 for state in states.values()), '新14は実終端全玉返済')
    parent_rows = list(parents.values())
    for parent in parent_rows:
        parent['収支'] = parent['粗損益'] - parent['費用']
    compare(ledger['parent'], parent_rows, '親全会計')
    compare(ledger['actual_legs'], legs, 'UID別の全返済玉と費用按分')
    uid_rows = []
    for uid, state in states.items():
        own = [leg for leg in legs if leg['uid'] == uid]
        uid_rows.append(dict(uid=uid, 親=state['cid'], 方向=state['side'], 枚数=state['quantity'], 残枚数=state['remaining'],
            新規行=state['row'], 新規価格=state['price'], 収支=sum(leg['収支'] for leg in own), 実玉数=len(own)))
    compare(ledger['uid_accounts'], uid_rows, '全UID残数量と決済会計')
    nets = np.asarray([parent['収支'] for parent in parent_rows])
    gain, loss = float(sum(np.maximum(nets, 0.))), float(sum(np.maximum(-nets, 0.)))
    summary = dict(利益=gain, 損失=loss, 収支=float(sum(nets)), 親数=len(nets), 勝ち親=int(sum(nets > 0)),
        負け親=int(sum(nets < 0)), 零親=int(sum(nets == 0)), 費用=int(sum(order_fees)),
        新規枚数=sum(state['quantity'] for state in states.values()), 勝ち枚数=sum(leg['枚数'] for leg in legs if leg['収支'] > 0),
        負け枚数=sum(leg['枚数'] for leg in legs if leg['収支'] < 0), 零枚数=sum(leg['枚数'] for leg in legs if leg['収支'] == 0),
        最大買枚数=int(max(long_qty)), 最大売枚数=int(max(short_qty)),
        最大DD=float(max(np.maximum.accumulate(np.maximum(equity, 0.)) - equity)), 最悪時価=float(min(0., min(equity))),
        注文件数=len(orders), 全会計合格=True)
    compare(ledger['summary'], summary, '新口座場会計')
    audit.near(summary['収支'], cash[-1], '全実現現金と全親net')
    return summary


def metrics(rows: list[dict]) -> dict:
    """
    機能: 旧保存引用と新会計を分母どおりに独立集計する。
    引数: rows(list[dict]) は同商品同期間の場会計。
    返り値: dict は利益・損失・黒赤場・中央値等。無取引は勝ちにしない。
    """
    net = [r['net'] for r in rows]
    positive, negative = [v for v in net if v > 0], [v for v in net if v < 0]
    gain, loss = sum(r['profit'] for r in rows), sum(r['loss'] for r in rows)
    active = sum(r['campaigns'] > 0 for r in rows)
    return dict(net=sum(net), profit=gain, loss=loss, fees=sum(r['fees'] for r in rows), parents=sum(r['campaigns'] for r in rows),
        sessions=len(rows), positive=len(positive), negative=len(negative), active=active, no_trade=len(rows)-active,
        median=float(np.median(net)), mean_session_net=sum(net)/len(net), profit_share=gain/(gain+loss) if gain+loss else None,
        mean_positive_session_net=sum(positive)/len(positive) if positive else None, worst_session_loss=max([-v for v in negative], default=0),
        黒字率=len(positive)/len(rows), 未取引は勝ちでない=True, 旧十万円床を判定に使用しない=True)
