"""複数建玉の原価、全行評価、数量共有と打切り不変性を独立に確認する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

import audit_single
import orders

OUT = Path(__file__).resolve().parent


def config(family: str, **changes: object) -> dict:
    """機能: 余計な返済を無効化した監査用の注文条件を作る。

    引数: family (str)、changes (dict)。返り値: dict。注文設定。
    """
    value = dict(id='独立監査', family=family, max_positions=3, warmup_min=0.,
                 repeat_min=60., cooldown_min=0., initial_stop_atr=100.,
                 trail_start_atr=np.inf, take_profit_atr=np.inf, max_hold_min=10000.,
                 basket_stop_atr=100., session_stop_atr=100., entry_deadline_min=0.)
    value.update(changes)
    return value


def independent_equity(ready: dict, trades: np.ndarray) -> np.ndarray:
    """機能: 売買一覧から各気配の清算評価と確定利益を二重計上せず再計算する。

    引数: ready (dict)、trades (ndarray)。返り値: ndarray。６列の全行評価。
    """
    values = np.zeros((len(ready['seq']), 7))
    for row in trades:
        side, first, last = int(row[1]), int(row[4]), int(row[5])
        quote = ready['bid'] if side > 0 else ready['ask']
        mark = side*(quote-row[7])-2*ready['tick']
        live = np.arange(len(quote)) >= first
        pnl = np.where(live, mark, 0.)
        if row[13]:
            pnl[last:] = row[14]
            values[last:, 6] += row[14]*1000
        stressed = pnl-np.where(live, 2*ready['tick'], 0.)
        values[:, 0] += pnl*1000
        values[:, 1] += stressed*1000
        values[:, 2] += pnl/row[6]
        values[:, 3] += stressed/row[6]
        held = live & ((np.arange(len(quote)) < last) if row[13] else True)
        values[:, 4] += held
        values[:, 5] += held*side
    return values


def check(name: str, ready: dict, setting: dict, reports: list[dict],
          expected: dict | None = None, delay: str = '次行') -> dict:
    """機能: 全行会計・順序・数量・最大順行と短い全 prefix を独立に照合する。

    引数: name (str)、ready/setting/expected (dict)、reports (list)、delay (str)。
    返り値: dict。実行結果。
    """
    result = orders.simulate_array(ready, setting, delay)
    trades, curve = result['trades'], result['equity']
    equity = independent_equity(ready, trades)
    positions = np.searchsorted(ready['seq'], curve[:, 1])
    np.testing.assert_allclose(curve[:, [2, 3, 4, 5, 6, 7, 10]], equity[positions])
    for j, key in [(0, '全行最大DD点'), (1, '全行費用倍最大DD点'),
                   (2, '全行最大下落ATR'), (3, '費用倍全行最大下落ATR')]:
        running_peak = np.maximum.accumulate(np.r_[0., equity[:, j]])[1:]
        wanted = np.max(running_peak-equity[:, j])/(1000 if j < 2 else 1)
        np.testing.assert_allclose(result['diagnostics'][key], wanted)
    assert equity[:, 4].max() <= setting['max_positions']
    use_bid, use_ask = np.zeros(len(ready['seq'])), np.zeros(len(ready['seq']))
    for row in trades:
        condition, trigger, entry, last = (int(row[x]) for x in [2, 3, 4, 5])
        assert condition < trigger < entry
        quote = ready['bid'][entry:last+1] if row[1] > 0 else ready['ask'][entry:last+1]
        np.testing.assert_allclose(row[11], max(0., np.max(row[1]*(quote-row[7]))))
        assert row[7] == (ready['ask'][entry] if row[1] > 0 else ready['bid'][entry])
        assert row[8] == (ready['bid'][last] if row[1] > 0 else ready['ask'][last])
        assert row[14] == row[1]*(row[8]-row[7])-2*ready['tick']
        (use_ask if row[1] > 0 else use_bid)[entry] += 1
        if row[13]:
            assert row[17] < last
            (use_bid if row[1] > 0 else use_ask)[last] += 1
    assert (use_bid <= ready['bid_qty']).all() and (use_ask <= ready['ask_qty']).all()
    if expected:
        actual = dict(建玉数=len(trades), 確定数=int(trades[:, 13].sum()),
                      確定円=float(trades[trades[:, 13] == 1, 14].sum()*1000),
                      未返済円=float(trades[trades[:, 13] == 0, 14].sum()*1000),
                      最終清算円=float(equity[-1, 0]), 最大総枚数=int(equity[:, 4].max()))
        for key, value in expected.items():
            assert actual[key] == value, (name, key, actual[key], value)
    for count in range(1, len(ready['seq'])+1):
        prefix = dict(ready)
        for key in ('seq', 'time_s', 'bid', 'ask', 'bid_qty', 'ask_qty', 'atr'):
            prefix[key] = ready[key][:count]
        observed = orders.simulate_array(prefix, setting, delay)['trades']
        observed = observed[observed[:, 13] == 1]
        wanted = trades[(trades[:, 13] == 1) & (trades[:, 5] < count)]
        np.testing.assert_allclose(observed, wanted, equal_nan=True)
    reports.append(dict(検査=name, 建玉数=len(trades), prefix数=len(ready['seq']), 手計算=expected,
                         全行最大DD円=float(result['diagnostics']['全行最大DD点']*1000)))
    return result


def main() -> None:
    """機能: 両建て、グリッド、追加建玉を含む独立監査を保存する。

    引数: なし。返り値: None。監査結果 JSON を作成する。
    """
    reports = []
    ready = audit_single.fixture([1000]*6)
    check('両建ては純枚数ゼロでも全脚にスプレッドと費用', ready, config('O02', max_positions=2), reports,
          dict(建玉数=2, 確定数=0, 未返済円=-60000., 最終清算円=-60000., 最大総枚数=2))
    ready = audit_single.fixture([1000, 1000, 1000, 1070, 1080, 1090])
    check('利益脚だけ返すと確定黒字でも全体は赤字', ready,
          config('O09', max_positions=2, take_profit_atr=.5), reports,
          dict(建玉数=2, 確定数=1, 確定円=50000., 未返済円=-120000., 最終清算円=-70000.))
    ready = audit_single.fixture([1000, 1000, 1000, 970, 960, 980, 1020])
    check('バスケット損失では全脚を次行返済', ready,
          config('O02', max_positions=2, basket_stop_atr=.5), reports,
          dict(建玉数=2, 確定数=2, 確定円=-60000., 未返済円=0.))
    ready = audit_single.fixture([1000, 1000, 1000, 1000, 1000, 1000])
    ready['bid_qty'][:] = 1
    ready['ask_qty'][:] = 1
    check('三脚成行も気配数量１なら３行へ分割', ready, config('O08'), reports,
          dict(建玉数=3, 確定数=0, 未返済円=-90000., 最大総枚数=3))
    ready = audit_single.fixture([1000, 900, 900, 910, 930, 1000, 1050, 1100])
    check('有限グリッドの指値条件通過と翌行約定', ready,
          config('O04', gap_atr=.5, take_profit_atr=.5), reports)
    ready = audit_single.fixture([1000, 930, 1000, 930, 920, 1010, 1010])
    result = check('指値条件後の反転は次行の不利価格で約定する', ready,
                   config('O04', gap_atr=.5), reports)
    first = result['trades'][np.argmin(result['trades'][:, 4])]
    assert first[4] == 2 and first[7] == 1010 and first[23] == 950
    for family in orders.FAMILIES:
        for delay in ['次行', '２行後', '次時刻']:
            bids = [1000, 1000, 1000, 1060, 1100, 1150, 1220, 1180, 1110,
                    1010, 920, 850, 890, 980, 1030, 1100, 1010, 1000]
            ready = audit_single.fixture(bids, seconds=[0, 0, 1, 2, 2, 3, 60, 61, 62,
                                                       120, 121, 122, 180, 181, 240, 300, 301, 302])
            check(f'{family}の全脚会計・数量・prefix・{delay}', ready,
                  config(family, gap_atr=.5, initial_stop_atr=.75, trail_start_atr=.5,
                         trail_atr=1., take_profit_atr=.75, basket_stop_atr=3.,
                         reset_width_atr=1., reset_min=2.), reports, delay=delay)
    for family in ['O07', 'O08']:
        ready = audit_single.fixture([1000, 1000, 1000, 1060, 1100, 1160, 1180, 1210, 1300, 1200])
        check(f'{family}の予測信号接続', ready, config(family, signal_family='監査', gap_atr=.5), reports)
    record = dict(一致=True, 件数=len(reports), prefix照合数=sum(r['prefix数'] for r in reports),
                  注文器SHA256=hashlib.sha256((OUT/'orders.py').read_bytes()).hexdigest(), 検査=reports)
    (OUT/'複数建玉の独立手計算監査.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k != '検査'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
