"""短期板の全約定台帳と各原本行の気配評価を独立照合する。"""

import argparse
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
BRANCH = HERE.parent / 'microstructure'
COMMON = HERE.parent.parent / 'wave_v60'


def equal(actual: float, expected: float, label: str) -> None:
    """機能: 金額や比率を浮動小数点の丸め誤差内で検算する。

    引数: actual/expected(float)、label(str)。返り値: なし(None)。
    """
    assert np.isclose(actual, expected, rtol=1e-10, atol=1e-6), (label, actual, expected)


def main() -> None:
    """機能: 指定ラウンドの全口座を注文現金・気配・組収支から再構成する。

    引数: --round(int)。返り値: なし(None)。新売買やAPIへアクセスしない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--round', type=int, default=1)
    parser.add_argument('--branch', default='microstructure')
    args = parser.parse_args()
    branch = HERE.parent / args.branch
    source = branch / f'round{args.round}'
    target = source / '集計結果.json'
    result = json.loads(target.read_text(encoding='utf-8'))
    frozen = json.loads((source / '実行前固定.json').read_text(encoding='utf-8'))
    for name, expected in frozen['SHA'].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected
    inputs = pickle.loads((COMMON / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((COMMON / 'quotes.pkl').read_bytes())
    signals = pickle.loads((branch / 'signals.pkl').read_bytes())
    totals = dict(口座=0, 注文=0, 決済組=0, 原本資産評価=0, 集計=0)
    for method in result['methods']:
        payload = Path(method['ledger']).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == method['ledger_SHA']
        ledgers = pickle.loads(payload)
        for account in method['accounts']:
            key = (account['session'], account['symbol'])
            ready, q, ledger = inputs[key], quotes[key], ledgers[key]
            orders, trades = ledger['orders'], ledger['trades']
            n = len(ready['seq'])
            value, qty, fee = (1000., 5, 209) if key[1] == 'TOPIX' else (10., 10, 110)
            cash = np.zeros(n)
            quantity = np.zeros(n)
            assert len(orders) == 2 * len(trades)
            if len(orders):
                d, i = orders[:, 0].astype(int), orders[:, 1].astype(int)
                assert np.all(i == d + 1) and i.min() >= 1 and i.max() < n
                np.testing.assert_array_equal(orders[:, 5], np.where(orders[:, 3] > 0, q['ask'][i], q['bid'][i]))
                np.testing.assert_array_equal(orders[:, 6], np.full(len(orders), fee))
                np.testing.assert_array_equal(orders[:, 4], np.full(len(orders), qty))
                assert np.all(orders[::2, 2] == 1) and np.all(orders[1::2, 2] == 2)
                assert np.all(ready['time_s'][i[::2]] < ready['limit'] - 300)
                assert np.all(ready['time_s'][i] < ready['limit'] + 300)
                np.testing.assert_array_equal(signals[key][method['config']['signal'], d[::2]] * method['config'].get('direction', 1), orders[::2, 3])
                np.add.at(cash, i, -orders[:, 3] * orders[:, 4] * orders[:, 5] * value - fee)
                np.add.at(quantity, i, orders[:, 3] * orders[:, 4])
                np.testing.assert_array_equal(trades[:, 0:2], orders[::2, 0:2])
                np.testing.assert_array_equal(trades[:, 2:4], orders[1::2, 0:2])
                np.testing.assert_array_equal(trades[:, 6], orders[::2, 5])
                np.testing.assert_array_equal(trades[:, 7], orders[1::2, 5])
            quantity = np.cumsum(quantity)
            assert quantity[-1] == 0 and np.max(np.abs(quantity), initial=0) <= qty
            curve = np.cumsum(cash) + quantity * np.where(quantity > 0, q['bid'], q['ask']) * value
            gross = trades[:, 4] * trades[:, 5] * (trades[:, 7] - trades[:, 6]) * value
            np.testing.assert_allclose(trades[:, 10], gross, rtol=0, atol=1e-6)
            np.testing.assert_allclose(trades[:, 11], gross - 2 * fee, rtol=0, atol=1e-6)
            net = trades[:, 11]
            values = dict(net=float(net.sum()), fees=float(orders[:, 6].sum()),
                gross_profit=float(gross[gross > 0].sum()), gross_loss=float(-gross[gross < 0].sum()),
                profit=float(net[net > 0].sum()), loss=float(-net[net < 0].sum()),
                wins=int(np.sum(net > 0)), losses=int(np.sum(net < 0)), flats=int(np.sum(net == 0)), cycles=len(net),
                drawdown=float(np.max(np.maximum.accumulate(np.r_[0., curve])[1:] - curve)),
                equity_min=float(np.min(curve, initial=0)), equity_max=float(np.max(curve, initial=0)),
                max_long_qty=int(np.max(quantity, initial=0)), max_short_qty=int(np.max(-quantity, initial=0)))
            equal(curve[-1], net.sum(), '全flat組と現金')
            for name, expected in values.items():
                equal(account[name], expected, name)
            totals['口座'] += 1
            totals['注文'] += len(orders)
            totals['決済組'] += len(trades)
            totals['原本資産評価'] += n
        for symbol in ('TOPIX', 'NK225'):
            aa = [a for a in method['accounts'] if a['symbol'] == symbol]
            summary = method['summary'][symbol]
            for name in ('gross_profit', 'gross_loss', 'fees', 'net', 'wins', 'losses', 'flats', 'cycles', 'profit', 'loss'):
                equal(summary[name], sum(a[name] for a in aa), name)
            if summary['cycles']:
                equal(summary['win_rate'], summary['wins'] / summary['cycles'], '組勝率')
            if summary['losses'] and summary['wins']:
                equal(summary['payoff'], (summary['profit'] / summary['wins']) / (summary['loss'] / summary['losses']), '組平均勝負')
            equal(summary['without_best'], summary['net'] - max(0, max(a['net'] for a in aa)), '黒字場除外')
            totals['集計'] += 1
    assert totals['口座'] == len(result['methods']) * 50
    proof = dict(合格=True, ラウンド=args.round, 件数=totals, 固定SHA一致=True,
        原本信号と次行気配一致=True, 全flat組費用後会計=True, 全行含みDD=True,
        結果SHA256=hashlib.sha256(target.read_bytes()).hexdigest())
    (HERE / f'{args.branch}_round{args.round}_全台帳の独立監査.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
