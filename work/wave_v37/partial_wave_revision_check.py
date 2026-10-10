"""波監査の限定改訂について、数値計算不変と追加2列の参照元を照合する。"""

from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

import partial_wave_audit as old
import partial_wave_audit_v2 as new

HERE = Path(__file__).resolve().parent


def functions(path: Path) -> dict:
    """機能: モジュールから関数の構文木を取り出す。

    引数: path (Path)。返り値: 関数名と構文木 (dict)。
    """
    return {node.name: node for node in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(node, ast.FunctionDef)}


def main() -> None:
    """機能: 数値5関数の構文同一と注文2キー以外の同一を独立に検査する。

    引数: なし。返り値: なし (None)。人工入力のみ使う。
    """
    a, b = functions(HERE/'partial_wave_audit.py'), functions(HERE/'partial_wave_audit_v2.py')
    unchanged = ('compare', 'reconstruct', 'integrate', 'boundary', 'measure')
    for name in unchanged:
        assert ast.dump(a[name], include_attributes=False) == ast.dump(b[name], include_attributes=False), name
    current = deepcopy(b['order_records']); removed = []
    for node in ast.walk(current):
        if isinstance(node, ast.Call):
            removed.extend(k.arg for k in node.keywords if k.arg in ('発注元管理方向', '約定時管理方向'))
            node.keywords = [k for k in node.keywords if k.arg not in ('発注元管理方向', '約定時管理方向')]
    assert sorted(removed) == ['発注元管理方向', '約定時管理方向']
    assert ast.dump(a['order_records'], include_attributes=False) == ast.dump(current, include_attributes=False)
    ready = dict(session='人工', symbol='TOPIX', time_s=np.array([0., 0., 1., 1., 2.]), seq=np.array([3, 5, 7, 9, 20]))
    state = np.array([-1, 0, 1, -1, 1], dtype=np.int8)
    orders = np.array([[1, 0, 0, 1, 1, 100, 20, 1], [2, 1, 0, -1, 1, 101, 30, 0],
                       [3, 2, 0, 1, 1, 102, 31, 1], [4, 3, 0, -1, 1, 103, 2, 0]], dtype=float)
    original, revised = old.order_records(ready, state, orders), new.order_records(ready, state, orders)
    for row, before, after in zip(orders, original, revised, strict=True):
        assert after['発注元管理方向'] == int(state[int(row[1])])
        assert after['約定時管理方向'] == int(state[int(row[0])])
        stripped = {k:v for k,v in after.items() if k not in ('発注元管理方向', '約定時管理方向')}
        old.compare(stripped, before)
    result = dict(全合格=True, 数値関数AST同一=list(unchanged), 注文一覧は追加2キー以外AST同一=True,
        人工注文数=len(orders), 発注元と約定時の入口方向を別行から照合=True,
        売買再生=False, 新実データ損益=False,
        SHA256={p.name:old.digest(p) for p in (Path(__file__), HERE/'partial_wave_audit.py', HERE/'partial_wave_audit_v2.py')})
    (HERE/'partial_wave_revision_checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('数値5関数不変・注文一覧は独立2列追加だけ・人工4参照行一致。')


if __name__ == '__main__':
    main()
