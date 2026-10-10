"""出力した取引明細と全条件集計の数値対応を独立に照合する。"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from model import MULTIPLIERS, OUT, SESSIONS, save


def check(prefix: str = '') -> dict:
    """機能: 保存JSONの取引からCSVの利益・損失・収支を再計算する。

    引数: prefix (str) は二銘柄出力などの接頭辞。返り値: 照合数と差分 (dict)。
    """
    trades = json.loads((OUT / f'{prefix}全取引.json').read_text(encoding='utf-8'))
    cells = pd.read_csv(OUT / f'{prefix}全条件セッション集計.csv')
    by_key = {}
    for t in trades:
        key = (t['方式'], t['セッション'], t['銘柄'])
        by_key.setdefault(key, []).append(t)
    errors = []
    for _, cell in cells.iterrows():
        key = (cell['方式'], cell['セッション'], cell['銘柄'])
        ts = by_key.get(key, [])
        closed = [t for t in ts if t['closed']]
        net = np.array([t['net_points'] * MULTIPLIERS[key[2]] for t in closed])
        expected = {'取引数': len(closed), '未返済数': len(ts)-len(closed), '勝ち数': (net > 0).sum(),
                    '利益円': net[net > 0].sum(), '損失円': -net[net < 0].sum(), '収支円': net.sum()}
        for field, value in expected.items():
            if not np.isclose(value, cell[field], atol=1e-6):
                errors.append(dict(条件=key, 項目=field, 計算値=float(value), 保存値=float(cell[field])))
        if key[1] != SESSIONS[-1] and len(ts) != len(closed):
            errors.append(dict(条件=key, 項目='完全セッション内の返済漏れ'))
    assert not errors, errors[:5]
    return dict(接頭辞=prefix, 方式数=int(cells.方式.nunique()), セル数=len(cells), 取引記録数=len(trades), 不一致=errors)


def main() -> None:
    """機能: 存在する全出力を照合して日本語JSONに保存する。

    引数: なし。返り値: なし (None)。
    """
    results = [check()]
    if (OUT / '二銘柄_全取引.json').exists():
        results.append(check('二銘柄_'))
    save(OUT / '損益再集計監査.json', dict(合格=True, 結果=results))
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
