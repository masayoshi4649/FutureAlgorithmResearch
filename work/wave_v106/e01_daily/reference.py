"""旧残返済料の2関数だけを接続し、旧bridgeや紙上engineを実行しない。"""

import ast
from decimal import Decimal, ROUND_FLOOR
from functools import lru_cache

import numpy as np

import common
import core


@lru_cache(maxsize=1)
def functions() -> dict:
    """
    機能: 不変旧sourceから料金定数とfee/remaining_feesだけをASTで読み取る。
    引数: なし。
    返り値: dictは元関数の名前空間。旧moduleのimport/mainを実行しない。
    """
    constants = ast.parse((common.REFERENCE/'specification.py').read_text(encoding='utf-8-sig'))
    values = {}
    for node in constants.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ('VALUE', 'FEE', 'QUANTITY', 'CAP'):
                values[node.targets[0].id] = ast.literal_eval(node.value)
    for name in ('VALUE', 'FEE', 'QUANTITY', 'CAP'):
        assert values[name] == getattr(core, name), name
    tree = ast.parse((common.REFERENCE/'liquidation_path.py').read_text(encoding='utf-8-sig'))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name in ('fee', 'remaining_fees')]
    assert {node.name for node in selected} == {'fee', 'remaining_fees'}
    namespace = dict(np=np, Decimal=Decimal, ROUND_FLOOR=ROUND_FLOOR, FEE=values['FEE'])
    exec(compile(ast.Module(body=selected, type_ignores=[]),
         str(common.REFERENCE/'liquidation_path.py'), 'exec'), namespace)
    return namespace


def check_reserved(old: dict, fresh: dict, symbol: str) -> None:
    """
    機能: 旧料金関数の全行残返済料を、新しい独立実注文会計へ照合する。
    引数: old/fresh(dict)は同じ実orders/UID、symbol(str)は商品。
    返り値: None。保存未来tradeやvirtual exitは条件計算に使わない。
    """
    wanted = functions()['remaining_fees'](old, len(fresh['equity_yen']), symbol)
    np.testing.assert_array_equal(wanted, fresh['reserved_exit_fees'])
    np.testing.assert_allclose(old['equity_yen']-wanted, fresh['liquidation_yen'], atol=1e-5, rtol=1e-12)

