"""注文時刻・方向・枚数を固定し、最終価格約定を同じ行の気配へ置換する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

from extract import HERE, save_json
from quotes import load_inputs_only


def account_sensitivity(account: dict, quotes: dict, ready: dict) -> tuple[dict, list]:
    """機能: 同じ注文行の買いを売気配、売りを買気配へ置き換え独立会計する。

    引数: account(dict:固定台帳)、quotes(dict:同原本行の気配)、ready(dict:最終価格)。
    返り値: 場別感度と組別記録(tuple[dict,list])。条件・注文時刻は再判定しない。
    """
    orders = np.asarray(account['orders'], dtype=float).reshape(-1, 10)
    multiplier = 1000. if account['symbol'] == 'TOPIX' else 10.
    assert np.array_equal(quotes['seq'], ready['seq'])
    original_cash = quote_cash = mid_cash = entry_delta = exit_delta = spread_cost = 0.
    held = 0.
    entry = None
    trades = []
    outside_entry = outside_exit = 0
    for order in orders:
        fill_seq = int(order[3])
        index = int(np.searchsorted(quotes['seq'], fill_seq))
        assert index < len(quotes['seq']) and quotes['seq'][index] == fill_seq
        assert quotes['time_s'][index] == order[1]
        original, side, qty = float(order[7]), int(order[5]), float(order[6])
        assert side in (-1, 1) and qty > 0
        assert ready['last'][index] == original
        bid, ask, mid = (float(quotes[name][index]) for name in ('bid', 'ask', 'mid'))
        actual = ask if side > 0 else bid
        change = -side * qty * (actual - original) * multiplier
        original_cash -= side * qty * original * multiplier
        quote_cash -= side * qty * actual * multiplier
        mid_cash -= side * qty * mid * multiplier
        spread_cost += qty * (ask - bid) / 2. * multiplier
        outside = int(original < bid or original > ask)
        if order[4] == 1:
            assert held == 0 and entry is None
            held = side * qty
            entry_delta += change
            outside_entry += outside
            entry = dict(time=float(order[1]), seq=fill_seq, side=side, qty=qty,
                         original=original, quote=actual, mid=mid, delta=change,
                         outside=outside)
        else:
            assert order[4] == 2 and entry is not None and held + side * qty == 0
            exit_delta += change
            outside_exit += outside
            ideal_pnl = entry['side'] * qty * (original - entry['original']) * multiplier
            quote_pnl = entry['side'] * qty * (actual - entry['quote']) * multiplier
            mid_pnl = entry['side'] * qty * (mid - entry['mid']) * multiplier
            assert abs(ideal_pnl - order[8]) < 1e-6
            assert abs(quote_pnl - ideal_pnl - entry['delta'] - change) < 1e-6
            trades.append(dict(entry_time=entry['time'], exit_time=float(order[1]),
                               entry_seq=entry['seq'], exit_seq=fill_seq, side=entry['side'], qty=qty,
                               original_entry=entry['original'], quote_entry=entry['quote'],
                               original_exit=original, quote_exit=actual,
                               original_net=ideal_pnl, quote_net=quote_pnl, mid_net=mid_pnl,
                               entry_delta=entry['delta'], exit_delta=change,
                               total_delta=quote_pnl - ideal_pnl,
                               entry_outside_quotes=entry['outside'], exit_outside_quotes=outside))
            held, entry = 0., None
    assert held == 0 and entry is None
    assert len(trades) == len(account['trades'])
    assert abs(original_cash - account['net']) < 1e-6
    assert abs(quote_cash - original_cash - entry_delta - exit_delta) < 1e-6
    assert abs(quote_cash - (mid_cash - spread_cost)) < 1e-6
    assert abs(quote_cash - sum(t['quote_net'] for t in trades)) < 1e-6
    result = dict(session=account['session'], symbol=account['symbol'],
                  original_net=original_cash, quote_net=quote_cash, mid_net=mid_cash,
                  entry_delta=entry_delta, exit_delta=exit_delta,
                  total_delta=quote_cash - original_cash,
                  entry_only_net=original_cash + entry_delta,
                  exit_only_net=original_cash + exit_delta,
                  midpoint_delta=mid_cash - original_cash, spread_cost=spread_cost,
                  cycles=len(trades), orders=len(orders),
                  entry_outside_quotes=outside_entry, exit_outside_quotes=outside_exit)
    for prefix in ('original', 'quote'):
        pnl = np.array([row[f'{prefix}_net'] for row in trades])
        qtys = np.array([row['qty'] for row in trades])
        result[f'{prefix}_profit'] = float(pnl[pnl > 0].sum())
        result[f'{prefix}_loss'] = float(-pnl[pnl < 0].sum())
        result[f'{prefix}_win_qty'] = int(qtys[pnl > 0].sum())
        result[f'{prefix}_loss_qty'] = int(qtys[pnl < 0].sum())
        result[f'{prefix}_flat_qty'] = int(qtys[pnl == 0].sum())
    return result, trades


def aggregate(accounts: list[dict]) -> dict:
    """機能: 同銘柄・同期間の固定注文感度を集計する。

    引数: accounts(list[dict])。返り値: 期間別感度(dict)。
    """
    columns = ('original_net', 'quote_net', 'mid_net', 'entry_delta', 'exit_delta',
               'total_delta', 'entry_only_net', 'exit_only_net', 'midpoint_delta', 'spread_cost',
               'cycles', 'orders', 'entry_outside_quotes', 'exit_outside_quotes')
    columns += tuple(f'{prefix}_{field}' for prefix in ('original', 'quote')
                     for field in ('profit', 'loss', 'win_qty', 'loss_qty', 'flat_qty'))
    result = {column: sum(row[column] for row in accounts) for column in columns}
    result['sessions'] = len(accounts)
    for prefix in ('original', 'quote'):
        result[f'{prefix}_positive_sessions'] = sum(row[f'{prefix}_net'] > 0 for row in accounts)
        result[f'{prefix}_pf'] = (result[f'{prefix}_profit'] / result[f'{prefix}_loss']
                                  if result[f'{prefix}_loss'] else None)
    assert abs(result['total_delta'] - result['entry_delta'] - result['exit_delta']) < 1e-6
    assert abs(result['quote_net'] - result['mid_net'] + result['spread_cost']) < 1e-6
    return result


def main() -> None:
    """機能: 14方式46口座へ同じ気配置換を施し、期間別・場別の差を保存する。

    引数: なし。返り値: なし(None)。最適化・方式選択・条件再判定は行わない。
    """
    base = HERE.parent
    ledger_path = base / 'ledgers.pkl'
    ledgers = pickle.loads(ledger_path.read_bytes())
    quotes = pickle.loads((HERE / 'quotes.pkl').read_bytes())
    ready = load_inputs_only()
    sessions = sorted({key[0] for key in ready})
    periods = {'先頭10場': sessions[:10], '次9場': sessions[10:19],
               '既知最後4場': sessions[19:], '全23場': sessions}
    assert len(ledgers) == 14 and len(sessions) == 23
    methods, detailed = {}, {}
    order_count = trade_count = 0
    for method, accounts in ledgers.items():
        assert set(accounts) == set(quotes) == set(ready)
        rows, method_trades = [], {}
        for key, account in accounts.items():
            row, trades = account_sensitivity(account, quotes[key], ready[key])
            rows.append(row)
            method_trades[key] = trades
            order_count += row['orders']
            trade_count += row['cycles']
        groups = {period: {symbol: aggregate([row for row in rows if row['symbol'] == symbol and row['session'] in selected])
                           for symbol in ('TOPIX', 'NK225')} for period, selected in periods.items()}
        methods[method] = dict(期間別=groups, セッション別=rows)
        detailed[method] = method_trades
        print(method, {symbol: [groups['全23場'][symbol]['original_net'], groups['全23場'][symbol]['quote_net']]
                       for symbol in ('TOPIX', 'NK225')}, flush=True)
    result = dict(方式='固定注文スケジュールの同原本行気配置換感度',
                   注意='判断時刻・約定行・売買方向・枚数・返済順を固定し、買いだけask、売りだけbidへ置換。建値変更後に損切り・追跡・入口・途中判断を再計算していないため、完全な再バックテストではない。',
                   基準価格='旧台帳は同じ原本行の最終約定値。気配もラージで、TOPIXミニとNK225マイクロの倍率へ換算。',
                   中値分解='quote_net = mid_net - spread_cost。midpoint_deltaは最終約定値から同じ行の中値へ変更した差。spread_costは全注文の片道半スプレッド合計。手数料ではない。',
                   差額符号='entry_delta/exit_delta/total_deltaは気配置換後から元の損益を引く。負数は悪化。',
                   時刻制限='同じ原本行の対応は厳密だが、板受信時計・実注文遅延・約定保証は再現しない。',
                   合格=True, 方式数=len(methods), 口座数=sum(len(x) for x in ledgers.values()),
                   注文数=order_count, 組数=trade_count,
                   元台帳SHA256=hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
                   気配SHA256=hashlib.sha256((HERE / 'quotes.pkl').read_bytes()).hexdigest(),
                   コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 手法=methods)
    save_json(HERE / '約定価格感度.json', result)
    (HERE / '約定価格感度_組別.pkl').write_bytes(pickle.dumps(detailed, pickle.HIGHEST_PROTOCOL))


if __name__ == '__main__':
    main()
