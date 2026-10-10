"""固定した売買試験の判断・約定・会計を、成績選択と独立して監査する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK))
SPEC = importlib.util.spec_from_file_location('backtest_independent_review', TASK/'backtest.py')
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def independent_account(ready: dict, result: dict) -> dict:
    """機能: 返済組から直接時価曲線を再構成し、注文と30分会計を確認する。

    引数: ready(dict)、result(dict)。返り値: 件数等の機械監査結果(dict)。
    損益順位の選択には使用せず、すべての条件を同じ式で検査する。
    """
    value, cap = (1000., 10) if ready['symbol'] == 'TOPIX' else (10., 20)
    prices, times, sequences = ready['last'], ready['time_s'], ready['seq']
    realized_steps = np.zeros(len(prices))
    floating = np.zeros(len(prices))
    holding = np.zeros(len(prices), dtype=np.int64)
    trades = result['trades']
    assert len(result['orders']) == 2*len(trades)
    entry_map = {}
    for order in result['orders']:
        decision = int(np.searchsorted(sequences, int(order[2])))
        fill = int(np.searchsorted(sequences, int(order[3])))
        assert sequences[decision] == order[2] and sequences[fill] == order[3]
        assert fill == decision+1, '次有効原本行の約定ではない'
        assert times[decision] == order[0] and times[fill] == order[1]
        assert prices[fill] == order[7]
        if order[4] == 1:
            assert times[decision] < ready['limit']-300.
            entry_map[int(order[3])] = order
    for trade in trades:
        start = int(np.searchsorted(sequences, int(trade[11])))
        end = int(np.searchsorted(sequences, int(trade[12])))
        side, qty, entry, exit_price, pnl = trade[2], trade[3], trade[4], trade[5], trade[6]
        assert sequences[start] == trade[11] and sequences[end] == trade[12]
        assert times[start] == trade[0] and times[end] == trade[1]
        assert prices[start] == entry and prices[end] == exit_price
        assert end > start and times[end] < ready['limit']+300.
        assert pnl == side*qty*(exit_price-entry)*value
        assert entry_map[int(trade[11])][6] == qty
        assert not np.any(holding[start:end]), '想定外の重複建玉'
        holding[start:end] = int(side*qty)
        floating[start:end] = side*qty*(prices[start:end]-entry)*value
        realized_steps[end] += pnl
        maximum = max(0., float(np.max(side*(prices[start:end+1]-entry))))/trade[8]
        assert np.isclose(maximum, trade[14], rtol=0, atol=1e-10), '約定終端を含むMFE不一致'
    curve = np.cumsum(realized_steps)+floating
    assert holding[-1] == 0 and np.max(abs(holding), initial=0) <= cap
    net = sum(trade[6] for trade in trades)
    assert net == result['net'] == curve[-1]
    assert result['profit'] == sum(max(trade[6], 0.) for trade in trades)
    assert result['loss'] == -sum(min(trade[6], 0.) for trade in trades)
    assert result['win_qty'] == sum(int(t[3]) for t in trades if t[6] > 0)
    assert result['loss_qty'] == sum(int(t[3]) for t in trades if t[6] < 0)
    dd = float(np.max(np.maximum.accumulate(np.r_[0., curve])[1:]-curve, initial=0.))
    assert np.isclose(dd, result['drawdown'], rtol=0, atol=1e-6)
    previous = 0.
    cumulative_realized = np.cumsum(realized_steps)
    for interval in result['intervals']:
        right = datetime.fromisoformat(interval['終了未満']).timestamp()
        k = int(np.searchsorted(times, right, side='left'))-1
        equity = float(curve[k]) if k >= 0 else 0.
        realized = float(cumulative_realized[k]) if k >= 0 else 0.
        assert np.isclose(equity-previous, interval['時価収支円'], rtol=0, atol=1e-6)
        assert np.isclose(equity-realized, interval['終了含み円'], rtol=0, atol=1e-6)
        previous = equity
    assert sum(i['時価収支円'] for i in result['intervals']) == net
    return dict(セッション=ready['session'], 銘柄=ready['symbol'], 注文数=len(result['orders']),
                返済組数=len(trades), 区間数=len(result['intervals']))


def prefix_checks(ready: dict, observations: pd.DataFrame, method: dict,
                  calibration: dict, full_signals: np.ndarray, full_result: dict) -> list[dict]:
    """機能: 現在までの判断と約定が未来観測や未来価格に左右されないか確認する。

    引数: ready/ calibration/ full_result(dict)、observations(DataFrame)、method(dict)、full_signals(ndarray)。
    返り値: 二つの切断点の検査結果(list[dict])。
    """
    out = []
    for fraction in (.4, .7):
        end = int(len(ready['seq'])*fraction)
        cutoff = float(ready['time_s'][end-1])
        cut = {key: value[:end] if isinstance(value, np.ndarray) and len(value) == len(ready['seq']) else value
               for key, value in ready.items()}
        old = observations.loc[observations.time_s <= cutoff].copy()
        decisions, _ = MODULE.build_signals(cut, old, method['id'], calibration)
        wanted = full_signals[full_signals[:, 0] < end]
        np.testing.assert_array_equal(decisions, wanted)
        result = MODULE.execute(cut, decisions, method['spec'], finish=False)
        known_orders = [row for row in full_result['orders'] if row[3] <= ready['seq'][end-1]]
        assert result['orders'] == known_orders
        changed = observations.copy()
        future = changed.time_s > cutoff
        for col in ('execution', 'r1', 'supply', 'recovery', 'repricing', 'peer_repricing'):
            changed.loc[future, col] = -changed.loc[future, col]
        other_signals, _ = MODULE.build_signals(ready, changed, method['id'], calibration)
        np.testing.assert_array_equal(other_signals[other_signals[:, 0] < end], wanted)
        future_prices = dict(ready)
        future_prices['last'] = ready['last'].copy()
        future_prices['atr'] = ready['atr'].copy()
        future_prices['last'][end:] += 777.
        future_prices['atr'][end:] *= 4.
        future_result = MODULE.execute(future_prices, other_signals, method['spec'], finish=False)
        assert [row for row in future_result['orders'] if row[3] <= ready['seq'][end-1]] == known_orders
        out.append(dict(セッション=ready['session'], 銘柄=ready['symbol'], 手法=method['id'],
                        切断行数=end, 一致判断数=len(wanted), 一致注文数=len(known_orders)))
    return out


def main() -> None:
    """機能: 全固定条件の会計と主試験・出口対照の実データ因果性を監査する。

    引数: なし。返り値: なし(None)。原本や売買結果は変更しない。
    """
    ledgers = pickle.loads((TASK/'ledgers.pkl').read_bytes())
    signals = pickle.loads((TASK/'signals.pkl').read_bytes())
    fixed = json.loads((TASK/'売買仕様固定.json').read_text(encoding='utf8'))
    methods = {method['id']: method for method in fixed['手法']}
    observations = pd.read_pickle(TASK/'theory/観測.pkl')
    ready = MODULE.load_ready()
    accounting = []
    for mid, accounts in ledgers.items():
        for key, result in accounts.items():
            accounting.append(dict(手法=mid, **independent_account(ready[key], result)))
    checks = []
    for session in ('2026-09-21_Day', '2026-09-24_Day', '2026-10-06_Day'):
        for symbol in ('TOPIX', 'NK225'):
            key = session, symbol
            own = observations.loc[(observations.session == session) & (observations.symbol == symbol)]
            for mid in ('P01', 'P02', 'P03', 'P04', 'C03', 'E15', 'EN0'):
                checks.extend(prefix_checks(ready[key], own, methods[mid], fixed['尺度'], signals[mid][key], ledgers[mid][key]))
    report = dict(合格=True, 条件数=len(ledgers), 会計口座数=len(accounting),
                  注文数=sum(item['注文数'] for item in accounting),
                  返済組数=sum(item['返済組数'] for item in accounting),
                  区間数=sum(item['区間数'] for item in accounting),
                  次有効原本行約定一致=True, 場内無保有=True, 損益と枚数一致=True,
                  約定行を含む最大順行一致=True, 独立時価曲線と最大下落一致=True,
                  三十分区間の含み込み会計一致=True, 実データ未来切断と改変=checks,
                  コードSHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (TASK/'backtest.py', TASK/'replay.py', TASK/'export.py')},
                  注意='機械的再現と会計の検査。主案の採否・ランキングには利用しない。')
    (HERE/'売買試験の独立監査.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({key:value for key,value in report.items() if key != '実データ未来切断と改変'}, ensure_ascii=False))
    print('未来切断・改変の比較数:', len(checks))


if __name__ == '__main__':
    main()
