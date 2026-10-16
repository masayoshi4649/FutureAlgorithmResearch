"""人工経路会計と既知1場だけで、新しい実行接続器を確認する。"""

from pathlib import Path
import importlib.util
import json
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
spec = importlib.util.spec_from_file_location('wave85_research_check', WORK / 'research.py')
research = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = research
spec.loader.exec_module(research)


def artificial(previous):
    """
    機能: 部分返済料金と無取引会計を、既知の数値で検査する。
    引数: previous (module) は旧67会計。
    返り値: dict の合否。実相場の新損益は計算しない。
    """
    ready = dict(session='人工', symbol='TOPIX', seq=np.arange(5), time_s=np.arange(5, dtype=float),
                 last=np.array([100., 100., 103., 101.5, 101.5]))
    orders = np.array([[1, 0, 0, 1, 5, 100., 20, 1], [2, 1, 0, -1, 2, 103., 7, 0],
                       [4, 3, 0, -1, 3, 101.5, 9, 0]], float)
    trades = np.array([[0, 0, 1, 2, 100., 103., 1, 2, 0, 7, 6.],
                       [0, 0, 1, 3, 100., 101.5, 1, 4, 0, 9, 4.5]])
    curve = np.zeros((5, 8)); curve[:, 0] = [0., 0., 15., 10.5, 10.5]
    result = dict(orders=orders, trades=trades, cycles=np.array([[0, 1, 4, 10.5, 25., 5., 5, 5, 1, 9]]),
                  curve=curve, stats=np.array([10.5, 0., 5, 0, 5, 5, 0, 0, 15., 0., 0.]))
    settings = dict(audit_cap=10)
    row, ledger, equity = research.account(previous, ready, result, settings)
    np.testing.assert_array_equal(ledger['fees'], [209., 83., 125.])
    np.testing.assert_array_equal(equity, [0., -209., 14708., 10208., 10083.])
    assert row['net'] == 10083 and row['fees'] == 417 and row['cycle_net'] == row['net']
    assert row['max_long'] == 5 and row['new_lots'] == row['exit_lots'] == 5
    original = dict(orders=orders.tolist(), trades=ledger['net_trades'], cycles=result['cycles'].tolist())
    research.compare_original(('人工', 'TOPIX'), result, ledger, original, 1000.)
    zero = dict(orders=np.empty((0, 8)), trades=np.empty((0, 11)), cycles=np.empty((0, 10)),
                curve=np.zeros((5, 8)), stats=np.zeros(11))
    blank, _, _ = research.account(previous, ready, zero, settings)
    assert blank['cycle_profit_share'] is None and blank['cycle_win_rate'] is None
    total = research.aggregate(previous, [blank], 'TOPIX', ['人工'])
    assert total['no_trade_sessions'] == 1 and total['positive_sessions'] == 0
    # ----------------------------------------
    # 前場終了100円、次場開始後の最安−50円なら、前場高値200円から150円の下落。
    a = dict(row, session='A', net=100., equity_min=0., equity_max=200., max_drawdown=100.)
    b = dict(row, session='B', net=50., equity_min=-50., equity_max=50., max_drawdown=50.)
    both = research.aggregate(previous, [a, b], 'TOPIX', ['A', 'B'])
    assert both['max_drawdown'] == 150. and both['best_session_removed'] == 50.
    return dict(全合格=True, 部分料金切捨按分=True, 全観測在庫時価=True, 無取引勝扱いなし=True,
                期間連結DD=True, 原形式11列復元=True)


def original_session(strategy, catalog):
    """
    機能: 前半既知1場でE01とGの指定値・観測値接続を旧台帳へ照合する。
    引数: strategy (module)、catalog (module)。
    返り値: list[dict] の照合結果。改修や追加場の損益は計算しない。
    """
    prepare = research.module('wave85_prepare', WORK / 'prepare.py')
    all_inputs, all_signals, _ = prepare.load_inputs()
    session = '2026-09-21_Day'
    inputs = {k: r for k, r in all_inputs.items() if k[0] == session}
    signals = {code: {k: r for k, r in values.items() if k in inputs} for code, values in all_signals.items()}
    del all_inputs, all_signals
    features = strategy.initialize(inputs, signals)
    results = []
    for model in research.MODELS:
        for identifier, old_id in (('E01', 'E01'), ('E01_G', 'R01')):
            config = next(c for c in catalog.catalog() if c['id'] == identifier)
            old = {(r['session'], r['symbol']): r for r in research.read(
                research.ROOT / 'work/wave_v67' / model / (old_id + '.json.gz'))['ledgers']}
            for key, ready in sorted(inputs.items()):
                result, settings = strategy.play(config, ready, features[key], observed=model == 'observed')
                row, ledger, _ = research.account(strategy.previous, ready, result, settings)
                research.compare_original(key, result, ledger, old[key], strategy.previous.VALUES[key[1]])
                results.append(dict(model=model, id=identifier, session=key[0], symbol=key[1],
                                    注文全列一致=True, 決済11列一致=True, 組全列一致=True, 料金後明細一致=True,
                                    全観測時価一致=True, 注文数=len(result['orders'])))
                del result
            print(model, identifier, '既知初日2口座の旧台帳一致', flush=True)
    return results


if __name__ == '__main__':
    strategy, catalog = research.engines()
    synthetic = artificial(strategy.previous)
    print('人工会計検査合格', flush=True)
    rows = original_session(strategy, catalog)
    output = dict(全合格=True, 人工会計=synthetic, 既知原版照合=rows, 改修損益計算=False, 追加場損益計算=False,
                  runner_SHA256=research.sha(WORK / 'research.py'), API取得=0)
    (HERE / 'runnerの人工会計と原版接続.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
