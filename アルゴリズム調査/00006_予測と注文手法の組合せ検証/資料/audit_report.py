"""報告書の候補別セッション表と元の全脚集計を独立に照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
REPORT = OUT.parents[1]/'アルゴリズム調査/00006_予測と注文手法の組合せ検証/検証結果.md'


def main() -> None:
    """機能: 既知部分と今回全体参考を区別し、表の利益・損失・収支・DD・脚数を照合する。

    引数: なし。返り値: None。報告書数値の独立監査.json を保存する。
    """
    text = REPORT.read_text(encoding='utf-8')
    full = pd.read_csv(OUT/'全条件_セッション集計.csv').set_index(['方式', 'セッション', '銘柄'])
    live = pd.read_csv(OUT/'現在照合_全体参考集計.csv').set_index(['方式', 'セッション', '銘柄'])
    columns = ['利益円', '損失円', '収支円', '費用倍収支円', '評価損益円', '全行最大下落円', '取引数']
    method, count, methods = None, 0, set()
    for line in text.splitlines():
        if match := re.match(r'#### (.+?)：', line):
            method = match.group(1)
        if not method or not re.match(r'\| 2026-09-\d{2}_(Day|Night)', line):
            continue
        values = [v.strip() for v in line.strip('|').split('|')]
        if len(values) != 9:
            continue
        session = values[0].split('（')[0]
        frame = live if '全体参考' in values[0] else full
        row = frame.loc[(method, session, values[1])]
        actual = np.array(list(map(float, values[2:])))
        expected = row[columns].to_numpy(dtype=float)
        expected[:-1] /= 10000
        np.testing.assert_allclose(actual, expected, atol=.0500001, rtol=0,
                                   err_msg=f'{method} {values[:2]}')
        count += 1
        methods.add(method)
    assert count == len(methods)*14 and len(methods) == 27
    assert '今回の一回照合） |' not in text
    assert '-0.0' not in text
    result = dict(一致=True, 候補条件数=len(methods), セッション表行数=count, 数値照合数=count*7,
                  報告書SHA256=hashlib.sha256(REPORT.read_bytes()).hexdigest(),
                  説明='５完全セッション、既知部分ナイト、今回末尾までの全体参考を別の元集計で確認。万円表示の丸め幅以内。')
    (OUT/'報告書数値の独立監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
