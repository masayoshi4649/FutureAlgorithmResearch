"""注文再生器の有限在庫・費用・未来遮断を合成系列と保存系列で検査する。"""

from __future__ import annotations

from pathlib import Path
import pickle
import numpy as np
import pandas as pd
import orders

OUT = Path(__file__).resolve().parent


def fixture(n: int = 300, seconds: float = 1., quantities: float = 10.) -> dict:
    """機能: 最良気配が一定の合成入力を作る。

    引数: n (int)、seconds/quantities (float)。返り値: 再生入力 (dict)。
    """
    start = orders._previous.bounds('2026-09-21_Day')[0]
    tape = dict(seq=np.arange(n, dtype=np.int64), time_s=start+np.arange(n)*seconds,
                bid=np.full(n, 1000.), ask=np.full(n, 1010.), bid_qty=np.full(n, quantities),
                ask_qty=np.full(n, quantities), atr=np.full(n, 40.))
    return orders.prepare(tape, pd.DataFrame(columns=['family']), '2026-09-21_Day', 'NK225')


def cut(prepared: dict, count: int) -> dict:
    """機能: 指定行数で将来の気配とイベントを除去する。

    引数: prepared (dict)、count (int)。返り値: 過去部分入力 (dict)。
    """
    result = dict(prepared)
    size = len(prepared['seq'])
    for key, value in prepared.items():
        if isinstance(value, np.ndarray) and len(value) == size:
            result[key] = value[:count].copy()
    result['families'] = {}
    for name, family in prepared['families'].items():
        mask = family['indices'] < count
        result['families'][name] = {key: value[mask] if isinstance(value, np.ndarray) else
                                    [x for x, keep in zip(value, mask) if keep] if key == 'rows' else value
                                    for key, value in family.items()}
    return result


def main() -> None:
    """機能: 会計と因果性の必要条件を実行して監査資料へ保存する。

    引数: なし。返り値: なし (None)。
    """
    checks = []
    fixed = dict(orders.DEFAULTS, id='合成', family='O02', max_positions=2, warmup_min=0.,
                 initial_stop_atr=100., trail_start_atr=np.inf, max_hold_min=.1)
    p = fixture()
    raw = orders.simulate_array(p, fixed)
    assert len(raw['trades']) == 2 and np.all(raw['trades'][:, 13] == 1)
    assert np.all(raw['trades'][:, 14] == -30.) and np.all(raw['trades'][:, 15] == -50.)
    assert raw['diagnostics']['全行最大DD点'] == 60.
    checks.append(dict(項目='両建ての２脚費用', 判定='合格', 確定点=-60., 費用倍点=-100.))
    partial = orders.simulate_array(fixture(5), dict(fixed, max_hold_min=100.))
    assert len(partial['trades']) == 2 and np.all(partial['trades'][:, 13] == 0)
    assert partial['equity'][-1, 2] == -60000.
    checks.append(dict(項目='途中断面では未返済の両脚評価を残す', 判定='合格'))
    split = dict(fixed, family='O08', max_positions=3)
    constrained = orders.simulate_array(fixture(30, quantities=1.), split)
    entries = constrained['trades'][:, 4].astype(int)
    assert len(entries) == 3 and len(np.unique(entries)) == 3
    checks.append(dict(項目='同じ行の最良数量１枚を３脚で重複利用しない', 判定='合格', 新規行=entries.tolist()))
    # ----------------------------------------
    # 実データで全条件の枚数・時系列・会計を確認し、全系統の未来遮断も比較する。
    inputs = pickle.loads((OUT/'再生入力.pkl').read_bytes())
    condition_count, trade_count, prefix_count = 0, 0, 0
    for (session, symbol), prepared in inputs.items():
        for cfg in orders.catalog():
            raw = orders.simulate_array(prepared, cfg)
            tr = raw['trades']
            assert raw['diagnostics']['最大総建玉枚数'] <= cfg['max_positions']
            assert np.all(tr[:, 2] < tr[:, 3]) and np.all(tr[:, 3] < tr[:, 4])
            assert np.allclose(tr[:, 14], tr[:, 1]*(tr[:, 8]-tr[:, 7])-2*prepared['tick'])
            assert np.allclose(tr[:, 15], tr[:, 14]-2*prepared['tick'])
            assert np.isclose(raw['equity'][-1, 2], tr[:, 14].sum()*orders.MULTIPLIERS[symbol])
            assert np.isclose(raw['equity'][-1, 4], np.sum(tr[:, 14]/tr[:, 6]))
            if prepared['time_s'][-1] > prepared['limit']+60:
                assert np.all(tr[:, 13] == 1)
            condition_count += 1
            trade_count += len(tr)
            if cfg['id'].endswith('G1_X1'):
                for fraction in (.37, .73):
                    count = int(len(prepared['seq'])*fraction)
                    sub = orders.simulate_array(cut(prepared, count), cfg)['trades']
                    sub = sub[sub[:, 13] == 1]
                    expected = tr[(tr[:, 13] == 1) & (tr[:, 5] < count)]
                    assert sub.shape == expected.shape
                    assert np.allclose(sub, expected, equal_nan=True)
                    prefix_count += 1
    checks.extend([dict(項目='実データ全条件の枚数・因果順序・全脚会計・終了返済', 判定='合格', 条件セル=condition_count, 売買数=trade_count),
                   dict(項目='将来行を削除しても過去に確定した全売買列が不変', 判定='合格', 比較数=prefix_count)])
    orders._previous.save(OUT/'注文再生の自己検査.json', dict(判定='合格', 検査=checks))
    print(f'合格: {condition_count}条件セル、{trade_count}脚、{prefix_count}前方切断比較')


if __name__ == '__main__':
    main()
