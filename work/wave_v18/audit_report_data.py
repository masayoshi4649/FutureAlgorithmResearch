"""親集計の縮小版表示データを独立した全行時価再構成結果と照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent
CHECKS = 0


def equal(actual: object, expected: object, label: str) -> None:
    """機能: 表示値と独立値の一致を検証する。

    引数: actual/expected (object)、label (str)。返り値: なし (None)。
    """
    global CHECKS
    if actual is None or expected is None or isinstance(expected, str):
        assert actual == expected, (label, actual, expected)
    else:
        assert np.isclose(actual, expected, rtol=1e-10, atol=1e-5), (label, actual, expected)
    CHECKS += 1


def metrics(actual: dict, expected: dict, label: str) -> None:
    """機能: 共有する会計・枚数・時価指標を全項目照合する。

    引数: actual/expected (dict)、label (str)。返り値: なし (None)。
    """
    for key in sorted(set(actual) & set(expected)):
        equal(actual[key], expected[key], f'{label}:{key}')


def main() -> None:
    """機能: 主案・補助案の全16週集計と160区間集計を独立値へ照合する。

    引数: なし。返り値: なし (None)。
    """
    path = OUT / 'scale_data.json'
    parent = json.loads(path.read_text(encoding='utf-8'))
    audit = json.loads((OUT / 'audit_scale.json').read_text(encoding='utf-8'))
    assert audit['合格']
    expected_ids = ['M3_逆_A03', 'M3_逆_A00', 'M2_逆_A00', 'M2_逆_A01']
    assert [m['id'] for m in parent['methods']] == expected_ids
    cells, weeks = 0, 0
    for mode, targets in audit['配分'].items():
        index_week = {(w['method_id'], w['symbol']): w for w in targets['weekly']}
        index_session = {(r['method_id'], r['symbol'], r['session']): r for r in targets['sessions']}
        for method in parent['methods']:
            for symbol, primary in method['variants'].items():
                variant = primary if mode == '各手法の最大枚数枠を利用' else primary['uniform']
                expected = index_week[(method['id'], symbol)]
                label = f'{mode}:{method["id"]}:{symbol}'
                metrics(variant['week'], expected, label)
                for field in ['initial_qty', 'add_qty', 'quantity_factor', 'money_factor']:
                    equal(variant['config'][field], expected[field], f'{label}:config:{field}')
                equal(variant['config']['position_cap'], expected['cap'], f'{label}:config:上限')
                for field in ['min', 'median', 'max']:
                    equal(variant['risk'][f'{field}_yen'], expected[f'risk_budget_{field}'], f'{label}:risk:{field}')
                assert len(variant['sessions']) == 10
                weeks += 1
                for row in variant['sessions']:
                    expected_row = index_session[(method['id'], symbol, row['session'])]
                    metrics(row, expected_row, f'{label}:{row["session"]}')
                    cells += 1
    assert cells == 160 and weeks == 16
    output = dict(合格=True, 数値文字列照合数=CHECKS, 週集計数=weeks, セッション集計数=cells,
                  原返済全行時価再構成監査='audit_scale.json', 対象='scale_data.json',
                  対象SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  確認='主配分と一律縮小の両方について、金額・累計枚数・最大同時枚数・最大下落・初期数量・追加数量・初期損失予算を独立結果と照合。')
    (OUT / 'audit_report_data.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
