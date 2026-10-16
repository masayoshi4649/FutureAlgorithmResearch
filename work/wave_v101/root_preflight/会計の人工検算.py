"""売買本体も原板も使わず、複数新規と一括返済の会計を検算する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(WORK))
import accounting


COHORT_COLUMNS = ['parent_id', 'cohort_id', 'source', 'side', 'quantity',
                  'decision_row', 'decision_seq', 'decision_time', 'entry_row',
                  'entry_seq', 'entry_time', 'entry_price', 'entry_fee', 'order_uid',
                  'exit_row', 'exit_seq', 'exit_time', 'exit_price', 'exit_fee_share',
                  'gross', 'net', 'risk_budget', 'initial_quantity', 'entry_kind',
                  'parent_final_quantity']


def artificial(side: int) -> dict:
    """
    機能: 手計算で親335円、建玉群+917円と−582円になる注文を作る。
    引数: side (int)。1は買い、−1は同じ損益になる価格反射の売り。
    返り値: dict。raw価格や売買本体を入力しない会計専用の人工記録。
    """
    entry = 4000.
    added = 4000. + side * 1.5
    exit_price = 4000. + side
    orders = np.zeros((3, 17), float)
    orders[0] = [1, 0, 1, 0, side, 1, entry, 1, 10, 41, 0, 1, 0, 1, 0, side, 1]
    orders[1] = [2, 1, 1, 0, side, 1, added, 1, 16, 41, 1, 2, 0, 1, 0, side, 2]
    orders[2] = [3, 2, 1, 0, -side, 2, exit_price, 0, 2, 83, 2, 3, 0, 1, 0, side, 3]
    trades = np.array([[1, 0, 1, 3, side, 2, (entry+added)/2,
                        exit_price, 82, 83, 500, 335, 10, 2, 1, 0]], float)
    cohorts = np.zeros((2, len(COHORT_COLUMNS)), float)
    positions = {name: i for i, name in enumerate(COHORT_COLUMNS)}
    for i, price in enumerate((entry, added)):
        values = dict(parent_id=1, cohort_id=i+1, source=0, side=side,
                      quantity=1, entry_row=i+1, entry_price=price, entry_fee=41,
                      exit_row=3, exit_price=exit_price, exit_fee_share=42-i,
                      gross=1000 if i == 0 else -500, net=917 if i == 0 else -582)
        for name, value in values.items():
            cohorts[i, positions[name]] = value
    curve = np.array([0., -582., 335., 335.])
    trace = np.zeros((4, 6), float)
    direction = 0 if side == 1 else 1
    trace[1:3, direction] = [1, 2]
    trace[1:3, direction+2] = [1, 2]
    stats = np.zeros(16, float)
    stats[direction] = stats[direction+2] = stats[8] = 2
    stats[15] = 335.
    return dict(orders=orders, trades=trades, growth_cohorts=cohorts,
                growth_cohort_columns=COHORT_COLUMNS,
                curve=curve, source_curve=np.column_stack((curve, np.zeros(len(curve)))),
                target_trace=trace,
                trace_columns=['held_long', 'held_short', 'occupied_long', 'occupied_short',
                               'pending_entry', 'pending_exit'],
                stats=stats,
                stat_columns=[str(i) for i in range(16)], events=np.empty((0, 12)))


# ----------------------------------------


def main() -> None:
    """
    機能: 買売反射・整数料金・相殺前利益率と改ざん検出を検算する。
    引数: なし。
    返り値: None。人工会計だけの証跡を保存し、収益性は評価しない。
    """
    for side in (1, -1):
        output = artificial(side)
        row = accounting.account(('2026-09-21_Day', 'TOPIX'), output)
        assert (row['profit'], row['loss'], row['net'], row['fees']) == (335., 0., 335., 165.)
        assert (row['cohorts']['profit'], row['cohorts']['loss']) == (917., 582.)
        assert row['profit_share'] == 1. and row['cohorts']['profit_share'] == 917 / 1499
        assert row['adding_order_count'] == 1 and row['order_count'] == 3
        period = accounting.aggregate([row], 'TOPIX', ['2026-09-21_Day'])
        assert period['cohorts'] == row['cohorts']
        assert period['without_best_day']['cohorts']['net'] == 0

    output = artificial(1)
    bad_cases = []
    for name in ('料金配分tie逆転', '建玉群損失隠し', '平均建値の呼値丸め', '非整数注文枚数'):
        changed = deepcopy(output)
        if name == '料金配分tie逆転':
            changed['growth_cohorts'][:, 18] = [41, 42]
        elif name == '建玉群損失隠し':
            changed['growth_cohorts'][1, 20] = 0
        elif name == '平均建値の呼値丸め':
            changed['trades'][0, 6] = 4001.
        else:
            changed['orders'][1, 5] = 1.5
        try:
            accounting.verify_campaigns(('2026-09-21_Day', 'TOPIX'), changed)
        except AssertionError:
            bad_cases.append(name)
        else:
            raise AssertionError('改ざんを検出できませんでした: ' + name)
    assert len(bad_cases) == 4
    paths = [Path(__file__), WORK / 'accounting.py']
    proof = dict(全合格=True, 買売会計反射=2, 不正会計検出=bad_cases,
                 親利益割合=1., 建玉群利益割合=917/1499,
                 検査範囲='会計専用の人工注文だけ。売買本体・原板・因果時系列や収益性の検査ではない。',
                 売買本体呼出=0, 正式101損益=0, API取得=0, 実注文=0,
                 SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in paths})
    (HERE / '複数実新規と全量返済の人工会計.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('会計人工の買売2例・改ざん4例を確認。売買本体・正式101損益0。', flush=True)


if __name__ == '__main__':
    main()
