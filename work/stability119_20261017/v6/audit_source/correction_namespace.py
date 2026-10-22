"""SOURCE段階で、旧補正関数のAST抜出しに必要な定数環境を反証する。"""

import ast
import hashlib
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def main() -> None:
    """
    機能: npだけの注入では旧correct_arraysのCHANGEDが未定義になることを小人工で確認する。
    引数: なし。元市場・CSV・保存結果を読まない。
    返り値: None。反証証跡を新規保存する。
    """
    source = ROOT / 'work/wave_v103/input_v2/correction.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'correct_arrays')
    namespace = {'np': np}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(source), 'exec'), namespace)
    sample = {f'人工列{i}': np.empty(0) for i in range(44)}
    found = None
    try:
        namespace['correct_arrays'](sample)
    except NameError as exc:
        found = str(exc)
    assert found is not None and 'CHANGED' in found
    path = HERE / '旧補正ASTの定数環境不足の人工反証.json'
    assert not path.exists()
    path.write_text(json.dumps(dict(再現=True, 例外=found,
        source_SHA256=hashlib.sha256(source.read_bytes()).hexdigest(),
        注入環境=['np'], 必要追加定数='CHANGED', 元市場読取=0, CSV読取=0, 保存結果読取=0, 金融=0),
        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(found)


if __name__ == '__main__':
    main()
