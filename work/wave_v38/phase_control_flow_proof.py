"""取消後の状態値が売買へ到達しない構造と、復元取消の人工反例を検査する。"""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

import phase_state_counterfactual as comparison

HERE = Path(__file__).resolve().parent


def zero_phase(statement: ast.AST) -> bool:
    """機能: 状態0を代入する文かを判定する。

    引数: statement(AST)。返り値: 該当するか(bool)。
    """
    return (isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'phase' for t in statement.targets)
        and isinstance(statement.value, ast.Constant) and statement.value.value == 0)


def ast_proof(source: str) -> dict:
    """機能: 全状態参照の保護条件と、予算解除時の状態初期化を列挙する。

    引数: source(str)。返り値: 構文木による証拠(dict)。
    """
    tree = ast.parse(source)
    simulate = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'simulate')
    parents = {child: node for node in ast.walk(simulate) for child in ast.iter_child_nodes(node)}
    loads = []
    for node in ast.walk(simulate):
        if not isinstance(node, ast.Name) or node.id != 'phase' or not isinstance(node.ctx, ast.Load):
            continue
        ancestry = []
        current = node
        while current in parents:
            current = parents[current]
            ancestry.append(current)
        compare = next((p for p in ancestry if isinstance(p, ast.Compare)), None)
        if compare is not None:
            gates = [p for p in ancestry if isinstance(p, ast.If) and any(
                isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not)
                and isinstance(t.operand, ast.Name) and t.operand.id == 'budget' for t in ast.walk(p.test))]
            assert gates
            loads.append(dict(行=node.lineno, 用途='新調整の判断', 式=ast.unparse(compare),
                予算なしを要求する行=gates[0].lineno, 条件=ast.unparse(gates[0].test)))
        else:
            assignment = next(p for p in ancestry if isinstance(p, ast.Assign))
            assert ast.unparse(assignment.targets[0]) == 'control[i]'
            loads.append(dict(行=node.lineno, 用途='状態証跡の書出し', 式='control[i]'))
    assert len(loads) == 3 and sum(x['用途'] == '新調整の判断' for x in loads) == 2
    stores = []
    for node in ast.walk(simulate):
        if not isinstance(node, ast.Assign) or not any(isinstance(t, ast.Name) and t.id == 'budget' for t in node.targets):
            continue
        assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool)
        item = dict(行=node.lineno, 代入値=node.value.value)
        if not node.value.value:
            parent = parents[node]
            block = next(value for _, value in ast.iter_fields(parent) if isinstance(value, list) and node in value)
            reset = [n.lineno for n in block if zero_phase(n)]
            assert reset
            item['同じ処理経路の状態0代入行'] = reset
        stores.append(item)
    assert len(stores) == 4 and sum(not s['代入値'] for s in stores) == 3
    return dict(全phase読込=sorted(loads, key=lambda x: x['行']), 全budget代入=sorted(stores,key=lambda x:x['行']),
        構造条件すべて成立=True, 限定='この凍結simulate内部の到達性。外部が誤ったphaseを利用する安全性は保証しない。')


def main() -> None:
    """機能: 構造証拠・追加人工・未採用修正版を新規ファイルへ保存する。

    引数: なし。返り値: なし(None)。既存売買・監査を更新しない。
    """
    comparison.socket.create_connection = comparison.reject
    comparison.urllib.request.urlopen = comparison.reject
    source_path = Path(comparison.engine.__file__)
    source = source_path.read_text(encoding='utf-8')
    original_hash = comparison.digest(source_path)
    structure = ast_proof(source)
    variant, replacement = comparison.alternative()
    policy = deepcopy(comparison.fixtures.POLICIES['B06_RB06_F50_N3'])
    rows = []
    for delay in (1.,5.,15.):
        for terminal in ('元停止優先','予算成行','元部分優先'):
            for observed in (False,True):
                for reflected in (False,True):
                    prices = [100,101,102,99,103,104,101,100,100,98]
                    if terminal == '元停止優先': prices += [96,96]
                    elif terminal == '予算成行': prices += [98,98]
                    else: prices += [110,110]
                    args = list(comparison.fixtures.fixture(prices, (2,6), (4,8)))
                    args[0]['time_s'][:12] = [0,20,40,60,80,100,120,140,160,160+delay/2,160+2*delay,160+3*delay]
                    if reflected:
                        args[0]['last'] = 400-args[0]['last']
                        for k in (1,3,5): args[k] = -args[k]
                    item = comparison.compare(tuple(args), policy,
                        dict(min_delay_seconds=delay, observed_fill=observed), variant,
                        dict(例='復元予約の予算取消', 終了経路=terminal, 遅延秒=delay, 観測約定=observed, 反射=reflected))
                    assert any(e['種類'] == 1 for e in item['予算取消'])
                    assert item['状態表示差行数'] > 0
                    if terminal == '元部分優先': assert any(e['予算中の元部分利確'] for e in item['予算取消'])
                    expected_reason = 1 if terminal == '元停止優先' else 32
                    assert all(e['終了理由'] == expected_reason for e in item['予算取消'])
                    rows.append(item)
    candidate_source = source.replace(replacement['置換前'], replacement['置換後'])
    candidate_source = '# 未採用の状態記録修正候補。正式なv38再生・採否へは接続しない。\n' + candidate_source
    candidate_path = HERE/'engine_partial_restore_phase_candidate.py'
    if candidate_path.exists():
        assert candidate_path.read_text(encoding='utf-8') == candidate_source
    else:
        candidate_path.write_text(candidate_source, encoding='utf-8')
    assert comparison.digest(source_path) == original_hash
    result = dict(構造検査=structure, 追加人工入力数=len(rows), 追加人工再生数=2*len(rows),
        全人工経済注文証跡一致=True, 正式旧版の表示不適合は未修正=True,
        元コア変更=False, 監査改変=False, 新実相場再生=False, API取得数=0,
        先行人工=comparison.digest(HERE/'phase_state_counterfactual.json'),
        コアSHA256=original_hash, 実装SHA256=comparison.digest(Path(__file__)),
        未採用候補=dict(ファイル=candidate_path.name, SHA256=comparison.digest(candidate_path),
            差分='追加実R取消の直後、phaseを復元権の有無により2又は0へ再設定する一行。機能差分は人工メモリ対照と同じ。',
            全実相場同値は未実施=True), 検査=rows)
    (HERE/'phase_control_flow_proof.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('検査','構造検査')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
