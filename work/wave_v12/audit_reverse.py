"""反転計算を元の数値取引と生気配から独立して照合する。"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
OLD = OUT.parent / 'wave_v11'


def manual_cases() -> list[dict]:
    """機能: 費用負け、方向の誤り、売り方向、幅変化を手計算値と照合する。

    引数: なし。返り値: 例ごとの計算結果 (list[dict])。
    """
    cases = [
        (1, 100., 110., 80., 90., 20., -50., -10.),
        (1, 100., 110., 40., 50., 20., -90., 30.),
        (-1, 100., 110., 140., 150., 20., -70., 10.),
        (1, 100., 120., 95., 105., 0., -25., -5.),
        (-1, 100., 100., 110., 110., 0., -10., 10.),
    ]
    results = []
    for s, b0, a0, b1, a1, fee, p, r in cases:
        original = s * ((b1 if s > 0 else a1) - (a0 if s > 0 else b0)) - fee
        reverse = -s * ((a1 if s > 0 else b1) - (b0 if s > 0 else a0)) - fee
        costs = ((a0-b0) + (a1-b1))/2 + fee
        assert original == p and reverse == r
        assert original + reverse == -2*costs
        results.append(dict(元方向=s, 元収支ポイント=original, 反転収支ポイント=reverse,
                            片方費用ポイント=costs))
    return results


def independent_ledger() -> tuple[pd.DataFrame, dict]:
    """機能: 元取引の全脚を原気配で独立再計算し反転の恒等式を確認する。

    引数: なし。返り値: 条件・セル別の独立集計と照合件数 (tuple[DataFrame, dict])。
    """
    schema = json.loads((OLD/'数値形式.json').read_text(encoding='utf-8'))
    conditions = schema['条件']
    cells = schema['セル']
    ready = pickle.loads((OLD/'再生入力.pkl').read_bytes())
    source = np.load(OLD/'全売買数値.npz')
    bins = defaultdict(lambda: dict(脚数=0, 返済数=0, 未返済数=0, 元値動き円=0.,
                                    元清算評価円=0., 反転清算評価円=0., 片方費用円=0.,
                                    元確定円=0., 反転確定円=0.))
    count, open_count, mismatch = 0, 0, 0.
    for block in source.files:
        for record in source[block]:
            ci, cell = int(record[0]), int(record[1])
            trade = record[2:]
            session, symbol = cells[cell]
            p = ready[(session, symbol)]
            factor = 1000. if symbol == 'NK225' else 10000.
            s, e, x = int(trade[1]), int(trade[4]), int(trade[5])
            b0, a0, b1, a1 = p['bid'][e], p['ask'][e], p['bid'][x], p['ask'][x]
            entry = a0 if s > 0 else b0
            end = b1 if s > 0 else a1
            extra = 2*p['tick']
            original = (s*(end-entry)-extra)*factor
            reverse = (-s*((a1 if s > 0 else b1)-(b0 if s > 0 else a0))-extra)*factor
            middle = s*((a1+b1-a0-b0)/2)*factor
            cost = (((a0-b0)+(a1-b1))/2+extra)*factor
            assert abs(entry-trade[7]) < 1e-7 and abs(end-trade[8]) < 1e-7
            assert abs(original-trade[14]*factor) < 1e-6
            assert abs(original-(middle-cost)) < 1e-6
            error = abs(reverse-(-original-2*cost))
            assert error < 1e-6
            mismatch = max(mismatch, error)
            value = bins[(conditions[ci], session, symbol)]
            value['脚数'] += 1
            value['元値動き円'] += middle
            value['元清算評価円'] += original
            value['反転清算評価円'] += reverse
            value['片方費用円'] += cost
            if trade[13] == 1:
                value['返済数'] += 1
                value['元確定円'] += original
                value['反転確定円'] += reverse
            else:
                value['未返済数'] += 1
                open_count += 1
            count += 1
    rows = [dict(方式=c, セッション=s, 銘柄=y, **v) for (c, s, y), v in bins.items()]
    return pd.DataFrame(rows), dict(全脚数=count, 未返済脚数=open_count, 恒等式最大誤差円=mismatch)


def main() -> None:
    """機能: 独立照合を実行し、再計算結果と監査証跡を保存する。

    引数: なし。返り値: なし (None)。
    """
    manual = manual_cases()
    table, checked = independent_ledger()
    table.to_csv(OUT/'監査_独立反転集計.csv', index=False, encoding='utf-8-sig')
    report = dict(手計算=manual, 全取引照合=checked,
                  原売買sha256=hashlib.sha256((OLD/'全売買数値.npz').read_bytes()).hexdigest(),
                  原入力sha256=hashlib.sha256((OLD/'再生入力.pkl').read_bytes()).hexdigest(),
                  監査コードsha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'反転の独立会計監査.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['全取引照合'], ensure_ascii=False))


if __name__ == '__main__':
    main()
