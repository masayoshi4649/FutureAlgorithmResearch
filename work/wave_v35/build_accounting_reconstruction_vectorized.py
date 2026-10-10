"""既存の独立会計を複写し、有限配列の極値走査だけを NumPy 化する。"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'wave_v29' / 'selected_accounting_audit.py'
TARGET = HERE / 'accounting_reconstruction_vectorized.py'


def generate() -> dict:
    """機能: 旧独立会計の式・検査を保ち、列の極値走査だけを置換する。

    引数: なし。返り値: 元・生成先の指紋と限定置換記録 (dict)。
    旧ファイルは読み取り専用。売買エンジンの集計や計算式を利用しない。
    """
    raw = SOURCE.read_text(encoding='utf-8-sig')
    tree = ast.parse(raw)
    wanted = ('close', 'integer', 'reconstruct')
    parts = {node.name: ast.get_source_segment(raw, node) for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in wanted}
    assert set(parts) == set(wanted)
    replacements = (
        ('max(longs + shorts)', 'np.max(longs + shorts)', 1),
        ('max(abs(net))', 'np.max(abs(net))', 1),
        ('max((longs + shorts)[first:last + 1])', 'np.max((longs + shorts)[first:last + 1])', 1),
        ('max(abs(net[first:last + 1]))', 'np.max(abs(net[first:last + 1]))', 1),
        ('max(longs)', 'np.max(longs)', 2),
        ('max(shorts)', 'np.max(shorts)', 2),
        ('min(equity)', 'np.min(equity)', 2),
        ('max(equity)', 'np.max(equity)', 2),
    )
    transformed = parts['reconstruct']
    for before, after, count in replacements:
        assert transformed.count(before) == count, (before, transformed.count(before), count)
        transformed = transformed.replace(before, after)
    # ----------------------------------------
    # 逆置換後の本文と全 assert の AST が旧版そのものへ戻ることを確認する。
    restored = transformed
    for before, after, count in reversed(replacements):
        assert restored.count(after) == count
        restored = restored.replace(after, before)
    assert restored == parts['reconstruct']
    original_asserts = [ast.dump(n) for n in ast.walk(ast.parse(parts['reconstruct'])) if isinstance(n, ast.Assert)]
    changed_asserts = [ast.dump(n) for n in ast.walk(ast.parse(transformed)) if isinstance(n, ast.Assert)]
    assert original_asserts == changed_asserts
    header = '''"""注文から再構成する独立会計。旧式の有限配列の極値走査だけを高速化。

生成元は v29 selected_accounting_audit.py の close / integer / reconstruct。
注文・元建玉・現金・数量・損益・曲線・上限・場末の検査は旧式を保持する。
最初に価格の全有限・正値を検査し、注文値の有限性も全件検査する。
その後の非空で有限な配列に対する極値だけを NumPy reduction へ置換する。
旧モジュールや売買エンジンを呼び出さない。生成器の逆置換で本文同値を検査済み。
"""

from __future__ import annotations

import numpy as np

MULT = {'TOPIX': 1000., 'NK225': 10.}
CAP = {'TOPIX': 10, 'NK225': 20}


'''
    code = header + '\n\n\n'.join((parts['close'], parts['integer'], transformed)) + '\n'
    compile(code, str(TARGET), 'exec')
    TARGET.write_text(code, encoding='utf-8')
    result = {'旧独立会計SHA256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              '生成器SHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              '新独立会計SHA256': hashlib.sha256(TARGET.read_bytes()).hexdigest(),
              '限定置換': [{'旧': a, '新': b, '箇所数': c} for a, b, c in replacements],
              '逆置換本文完全一致': True, '全assert同一': True, 'assert数': len(original_asserts),
              '旧コード変更': False, '売買エンジンへの依存': False}
    (HERE / 'reconstruction_vectorized_build.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(generate(), ensure_ascii=False))
