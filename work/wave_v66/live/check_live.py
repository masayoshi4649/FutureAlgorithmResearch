"""一回取得した現在原本の約定順と未返済会計を独立に検算する。"""

from datetime import datetime
import json
from pathlib import Path
import pickle

import numpy as np

import prepare_live


HERE = Path(__file__).resolve().parent


def reconstruct(ready: dict, quote: dict, orders: list[dict], count: int) -> dict:
    """機能: 約定原簿から指定境界の実現・費用・残玉評価を独立に復元する。

    引数: ready/quote(dict)、orders(list[dict])、count(int)。
    返り値: 境界資産(dict)。未約定予約を約定に数えず、未返済費用を課さない。
    """
    topix = ready['symbol'] == 'TOPIX'
    qty, value = (10, 1000.) if topix else (20, 10.)
    fee = int(41.8 * qty + 1.e-8) if topix else 11 * qty
    side, anchor, gross, costs, entry_fee = 0, 0., 0., 0, 0
    for order in orders:
        assert order['fill_i'] == order['decision_i'] + 1
        assert order['qty'] == qty and order['fee'] == fee
        fill, direction = order['fill_i'], order['side']
        expected = float(quote['ask'][fill] if direction > 0 else quote['bid'][fill])
        assert order['price'] == expected
        if fill >= count:
            continue
        costs += fee
        if order['action'] == '新規':
            assert side == 0 and ready['time_s'][fill] < ready['limit'] - 300.
            side, anchor, entry_fee = direction, expected, fee
        else:
            assert order['action'] == '返済' and side == -direction
            profit = side * qty * (expected - anchor) * value
            assert profit == order['gross']
            gross += profit
            side, entry_fee = 0, 0
    liquidation = float(quote['bid'][count - 1] if side > 0 else quote['ask'][count - 1]) if side else None
    unrealized = side * qty * (liquidation - anchor) * value if side else 0.
    return dict(gross_realized=gross, fees=costs, unrealized=unrealized, net=gross - costs + unrealized,
                long_qty=qty if side > 0 else 0, short_qty=qty if side < 0 else 0, open_entry_fees=entry_fee)


def trace_exit(ready: dict, quote: dict, entry_i: int, side: int, config: dict) -> dict:
    """機能: 一つの新規約定から最初の返済条件成立を別ループで照合する。

    引数: ready/quote/config(dict)、entry_i/side(int)。
    返り値: 最初の成立行・理由と保護開始行(dict)。原本末尾を返済条件にしない。
    """
    entry_price = float(quote['ask'][entry_i] if side > 0 else quote['bid'][entry_i])
    peak, armed, armed_i = -np.inf, False, -1
    stopline = -entry_price * config['stop']
    for i in range(entry_i, len(ready['seq'])):
        liquidation = float(quote['bid'][i] if side > 0 else quote['ask'][i])
        profit = side * (liquidation - entry_price)
        peak = max(peak, profit)
        if not armed and peak >= entry_price * config['arm'] - 1.e-9:
            armed, armed_i = True, i
        if armed:
            stopline = max(stopline, entry_price * config['floor'], peak - entry_price * config['trail'])
        if ready['time_s'][i] >= ready['limit'] - 60.:
            return dict(i=i, reason=4, armed_i=armed_i)
        if profit <= stopline + 1.e-9:
            return dict(i=i, reason=2 if armed else 1, armed_i=armed_i)
    return dict(i=None, reason=None, armed_i=armed_i)


def main() -> None:
    """機能: 24口座の次行約定・前半境界・全残玉と一回取得を独立に検査する。

    引数: なし。返り値: なし(None)。現在APIの追加取得と条件再調整はしない。
    """
    prepare_live.verify_seal()
    manifest = json.loads((HERE / '取得記録.json').read_text(encoding='utf-8'))
    assert manifest['全応答成功'] and len(manifest['requests']) == 3 and manifest['実注文'] == 0
    assert manifest['再試行'] is False and len({item['url'] for item in manifest['requests']}) == 3
    for request in manifest['requests'][1:]:
        trailers = {name.lower(): value for name, value in request['trailers'].items()}
        assert trailers['x-history-complete'] == ['true']
    sealed = json.loads((HERE / '取得前最終固定.json').read_text(encoding='utf-8'))
    assert datetime.fromisoformat(sealed['時刻']) < datetime.fromisoformat(manifest['共通to'].replace('Z', '+00:00'))
    inputs = pickle.loads((HERE / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((HERE / 'quotes.pkl').read_bytes())
    result = json.loads((HERE / '現在急傾斜の途中損益.json').read_text(encoding='utf-8'))
    assert result['条件数'] == 12 and len(result['methods']) == 12
    candidates = prepare_live.candidates()
    checks = []
    for method in result['methods']:
        assert method['config'] in candidates
        for account in method['accounts']:
            key = account['session'], account['symbol']
            ready, quote, orders = inputs[key], quotes[key], account['orders']
            count, n = account['既知境界']['valid_rows'], len(ready['seq'])
            for boundary_name, boundary_count in (('既知境界', count), ('現在末尾', n)):
                expected = reconstruct(ready, quote, orders, boundary_count)
                for name, value in expected.items():
                    np.testing.assert_allclose(account[boundary_name][name], value, atol=1.e-7)
            for name in ('gross_realized', 'fees', 'unrealized', 'net'):
                np.testing.assert_allclose(account['追加区間'][name],
                    account['現在末尾'][name] - account['既知境界'][name], atol=1.e-7)
            for row in account['rows']:
                observed = trace_exit(ready, quote, row['entry_i'], row['side'], method['config']['exit_config'])
                assert observed['i'] == row['exit_decision_i'] and row['exit_i'] == observed['i'] + 1
                assert observed['reason'] == row['reason'] and observed['armed_i'] == row['armed_i']
                assert row['net'] == row['gross'] - row['fees'] and row['fees'] == row['entry_fee'] + row['exit_fee']
            for position in account['現在末尾']['open_positions']:
                observed = trace_exit(ready, quote, position['entry_i'], position['side'], method['config']['exit_config'])
                pending = account['現在末尾']['pending_exit']
                if observed['i'] is None:
                    assert pending is None
                else:
                    assert observed['i'] == n - 1 and pending['i'] == n - 1 and pending['reason'] == observed['reason']
                assert position['future_exit_fee_incurred'] is False
            checks.append(dict(手法=method['config']['id'], セッション=key[0], 銘柄=key[1],
                               約定数=len(orders), 決済数=len(account['rows']), 前半境界行=count,
                               末尾未返済枚数=account['long_qty'] + account['short_qty'],
                               次行約定=True, 最初の返済条件=True, 全残玉評価=True, 手数料=True, 合格=True))
    prepare_live.save('現在会計の独立検査.json', dict(全合格=True, 件数=len(checks), 検査=checks,
        HTTP要求数=3, 現在API追加取得=0, 実注文=0, 取得前固定を確認=True, 原本末尾の架空清算=False))
    print('一回取得と12条件×2銘柄の次行約定・境界・未返済会計が合格しました。')


if __name__ == '__main__':
    main()
