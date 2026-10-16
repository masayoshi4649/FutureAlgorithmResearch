"""第一段を変更せず、指値の価格改善と休止後の基準更新を分けた15条件を作る。"""

import importlib.util
from pathlib import Path

PRIMARY = 'D_C_QA'
SYMBOLS = ('TOPIX', 'NK225')


def catalog() -> list[dict]:
    """
    機能: 数量と方向分類を保持し、価格改善と基準更新の二軸だけを列挙する。
    引数: なし。
    返り値: list[dict]。主はD_C_QA、価格改善のみQ/基準更新のみA/両方QA。
    """
    path = Path(__file__).resolve().parent.parent/'catalog.py'
    spec = importlib.util.spec_from_file_location('配分90の元条件読取', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = {c['id']: c for c in module.catalog()}
    cases = [(name, 'Q') for name in ('J10', 'J8', 'O10', 'O2', 'M82')]
    cases += [(name, variant) for name in ('D_C', 'G82_C') for variant in ('Q', 'A', 'QA')]
    cases += [(name, 'QA') for name in ('D_E', 'D_X', 'G82_E', 'G82_X')]
    result = []
    for name, variant in cases:
        result.append(dict(original[name], id=f'{name}_{variant}', base_id=name,
                           improve_limit='Q' in variant, activate_anchor='A' in variant))
    assert len(result) == len({c['id'] for c in result}) == 15
    return result
