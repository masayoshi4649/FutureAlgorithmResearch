"""在庫枝の全注文を原本気配と独立現金会計で照合する。"""

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
BRANCH = HERE.parent / 'inventory'
COMMON = HERE.parent.parent / 'wave_v60'


def equal(actual: object, expected: object, name: str) -> None:
    """機能: 未定義と金額を区別して照合する。

    引数: actual/expected(object)、name(str)。返り値: なし(None)。
    """
    if expected is None:
        assert actual is None, (name, actual)
    else:
        assert np.isclose(actual, expected, rtol=1e-10, atol=1e-6), (name, actual, expected)


def stats(groups: np.ndarray) -> dict:
    """機能: 全flat組だけから勝率・平均勝負比を計算する。

    引数: groups(ndarray)。返り値: 指標(dict)。
    """
    x = groups[:, 11]
    positive, negative = x[x > 0], -x[x < 0]
    avw = float(positive.mean()) if len(positive) else None
    avl = float(negative.mean()) if len(negative) else None
    return dict(groups=len(x), wins=len(positive), losses=len(negative), flats=int(np.sum(x == 0)),
        win_rate=len(positive)/len(x) if len(x) else None, profit=float(positive.sum()),
        loss=float(negative.sum()), net=float(x.sum()), pf=float(positive.sum()/negative.sum()) if len(negative) else None,
        average_win=avw, average_loss=avl, payoff=avw/avl if avw is not None and avl else None,
        max_win=float(positive.max(initial=0)), max_loss=float(negative.max(initial=0)),
        hold_median_minutes=float(np.median((groups[:, 6]-groups[:, 5])/60)) if len(x) else None)


def audit(account: dict, ledger: dict, ready: dict, quote: dict, config: dict) -> dict:
    """機能: 原本順・約定価格・全行資産・全組会計を別式で復元する。

    引数: account/ledger/ready/quote/config(dict)。返り値: 検査件数(dict)。
    """
    orders, groups = ledger['orders'], ledger['groups']
    times, mid, bid, ask = ready['time_s'], quote['mid'], quote['bid'], quote['ask']
    n = len(times)
    qty, value, fee_unit = (5, 1000., 418) if account['symbol'] == 'TOPIX' else (10, 10., 110)
    mode = config['mode']
    fee = qty*fee_unit//10
    width = max(2*ready['tick'], np.ceil(mid[0]*config['fraction']/ready['tick']-1e-12)*ready['tick'])
    equal(ledger['width'], width, '幅固定')
    assert len(orders) == 2*len(groups)
    cash, quantity = np.zeros(n), np.zeros(n)
    if len(orders):
        d, f = orders[:, 1].astype(int), orders[:, 2].astype(int)
        assert np.all(f > d) and np.all(np.diff(f) > 0)
        np.testing.assert_array_equal(orders[:, 0], np.arange(len(orders)))
        np.testing.assert_array_equal(orders[::2, 5], np.ones(len(groups)))
        np.testing.assert_array_equal(orders[1::2, 5], np.full(len(groups), 2))
        np.testing.assert_array_equal(orders[:, 3], times[d])
        np.testing.assert_array_equal(orders[:, 4], times[f])
        np.testing.assert_array_equal(orders[:, 7], np.full(len(orders), qty))
        np.testing.assert_array_equal(orders[:, 9], np.full(len(orders), fee))
        np.testing.assert_array_equal(orders[1::2, 6], -orders[::2, 6])
        assert np.all(times[f[::2]] < ready['limit']-300)
        assert np.all(times[f] < ready['limit']+300)
        passive = ((orders[:, 5] == 1) & (mode in (1, 2))) | ((orders[:, 5] == 2) & (mode == 2) & (orders[:, 11] == 5))
        np.testing.assert_array_equal(f[~passive], d[~passive]+1)
        ordinary_price = mid[f] if mode == 3 else np.where(orders[:, 6] > 0, ask[f], bid[f])
        np.testing.assert_array_equal(orders[~passive, 8], ordinary_price[~passive])
        for oi in np.flatnonzero(passive):
            if orders[oi, 5] == 1:
                price = bid[d[oi]] if orders[oi, 6] > 0 else ask[d[oi]]
                assert times[f[oi]]-times[d[oi]] < 60.
            else:
                opening = orders[oi-1]
                target = np.ceil(1.5*width/ready['tick']-1e-12)*ready['tick']
                price = opening[8]+opening[6]*target
                assert d[oi] == int(opening[2])
            equal(orders[oi, 8], price, '待機指値')
            hit = ask[f[oi]] <= price-ready['tick'] if orders[oi, 6] > 0 else bid[f[oi]] >= price+ready['tick']
            assert hit
            before = np.arange(d[oi]+1, f[oi])
            prior_hit = ask[before] <= price-ready['tick'] if orders[oi, 6] > 0 else bid[before] >= price+ready['tick']
            assert not np.any(prior_hit), '指値の最初の通過を飛ばしていない'
        np.add.at(cash, f, -orders[:, 6]*orders[:, 7]*orders[:, 8]*value-orders[:, 9])
        np.add.at(quantity, f, orders[:, 6]*orders[:, 7])
        np.testing.assert_array_equal(groups[:, 3], f[::2])
        np.testing.assert_array_equal(groups[:, 4], f[1::2])
        np.testing.assert_array_equal(groups[:, 5:7], np.column_stack((times[f[::2]], times[f[1::2]])))
        np.testing.assert_array_equal(groups[:, 1], orders[::2, 6])
        np.testing.assert_array_equal(groups[:, 2], orders[::2, 7])
        np.testing.assert_array_equal(groups[:, 7], orders[::2, 8])
        np.testing.assert_array_equal(groups[:, 8], orders[1::2, 8])
        for gi, g in enumerate(groups):
            liq = mid if mode == 3 else (bid if g[1] > 0 else ask)
            movement = g[1]*(liq[int(g[3]):int(g[4])+1]-g[7])
            equal(g[13], movement.max(initial=0), 'MFE')
            equal(g[14], movement.min(initial=0), 'MAE')
            if g[12] == 6:
                assert orders[2*gi+1, 3]-g[5] >= 900.
    q = np.cumsum(quantity)
    assert q[-1] == 0 and np.max(np.abs(q), initial=0) <= qty
    liquid = mid if mode == 3 else np.where(q >= 0, bid, ask)
    curve = np.cumsum(cash)+q*liquid*value
    gross = groups[:, 1]*groups[:, 2]*(groups[:, 8]-groups[:, 7])*value
    np.testing.assert_allclose(groups[:, 9], gross, rtol=0, atol=1e-6)
    np.testing.assert_array_equal(groups[:, 10], np.full(len(groups), 2*fee))
    np.testing.assert_allclose(groups[:, 11], gross-2*fee, rtol=0, atol=1e-6)
    equal(curve[-1], groups[:, 11].sum(), '現金と全組')
    for name, expected in stats(groups).items():
        equal(account[name], expected, name)
    other = dict(gross_profit=float(gross[gross > 0].sum()), gross_loss=float(-gross[gross < 0].sum()),
        gross_pnl=float(gross.sum()), fees=float(orders[:, 9].sum()), orders=len(orders),
        win_qty=float(groups[groups[:, 11] > 0, 2].sum()), loss_qty=float(groups[groups[:, 11] < 0, 2].sum()),
        flat_qty=float(groups[groups[:, 11] == 0, 2].sum()),
        drawdown=float(np.max(np.maximum.accumulate(np.r_[0., curve])[1:]-curve)),
        equity_min=float(curve.min(initial=0)), equity_max=float(curve.max(initial=0)),
        max_long_qty=float(q.max(initial=0)), max_short_qty=float((-q).max(initial=0)),
        same_orders_mid_net=float(np.sum(-orders[:, 6]*orders[:, 7]*mid[orders[:, 2].astype(int)]*value-orders[:, 9])))
    for name, expected in other.items():
        equal(account[name], expected, name)
    return dict(口座=1, 注文=len(orders), 決済組=len(groups), 原本資産評価=n)


def main() -> None:
    """機能: 全三ラウンドを照合し、コード固定と検査件数を保存する。

    引数: なし。返り値: なし(None)。売買条件変更も新再生もしない。
    """
    inputs = pickle.loads((COMMON/'inputs.pkl').read_bytes())
    quotes = pickle.loads((COMMON/'quotes.pkl').read_bytes())
    reports = []
    for label in ('R1', 'R2', 'R3'):
        path = BRANCH/f'{label}_集計結果.json'
        result = json.loads(path.read_text(encoding='utf-8'))
        frozen = json.loads((BRANCH/f'{label}_実行前固定.json').read_text(encoding='utf-8'))
        for name, expected in frozen['code'].items():
            source = BRANCH/'R1_code'/name if label == 'R1' else BRANCH/name
            assert hashlib.sha256(source.read_bytes()).hexdigest() == expected
        totals = dict(口座=0, 注文=0, 決済組=0, 原本資産評価=0, 集計=0)
        for method in result['methods']:
            ledger = pickle.loads((BRANCH/method['ledger']).read_bytes())
            for account in method['accounts']:
                key = (account['session'], account['symbol'])
                counts = audit(account, ledger[key], inputs[key], quotes[key], method)
                for k, v in counts.items():
                    totals[k] += v
            for symbol in ('TOPIX', 'NK225'):
                groups = np.concatenate([v['groups'] for k, v in ledger.items() if k[1] == symbol])
                accounts = [a for a in method['accounts'] if a['symbol'] == symbol]
                summary = method['summary'][symbol]
                for k, v in stats(groups).items():
                    equal(summary[k], v, k)
                for k in ('gross_profit', 'gross_loss', 'gross_pnl', 'fees', 'win_qty', 'loss_qty', 'flat_qty', 'orders', 'same_orders_mid_net'):
                    equal(summary[k], sum(a[k] for a in accounts), k)
                equal(summary['without_best_session'], sum(a['net'] for a in accounts)-max(0, max(a['net'] for a in accounts)), '大勝場除去')
                balance = peak = dd = 0.
                for a in accounts:
                    dd = max(dd, peak-balance-a['equity_min'], a['drawdown'])
                    peak = max(peak, balance+a['equity_max'])
                    balance += a['net']
                equal(summary['drawdown'], dd, '全期間DD')
                totals['集計'] += 1
        reports.append(dict(ラウンド=label, 合格=True, 件数=totals, 結果SHA256=hashlib.sha256(path.read_bytes()).hexdigest()))
        print(json.dumps(reports[-1], ensure_ascii=False), flush=True)
    output = dict(合格=True, ラウンド別=reports, 全flat組費用後会計=True, 指値待機と一呼値通過と最初の約定=True,
        指値以外は次行約定=True, 全原本資産DDとMFE_MAE=True, 現在市場API回数=0)
    (HERE/'在庫全三ラウンドの独立会計監査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
