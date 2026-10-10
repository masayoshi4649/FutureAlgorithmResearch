"""入口と保有管理の分離を、旧互換・合成反例・構文差分で検査する。"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import urllib.request

import numpy as np

import engine_context

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v23'
sys.path.insert(0, str(OLD))
import engine as previous
import managers


def no_network(*args: object, **kwargs: object) -> None:
    """機能: 監査中の外部通信を強制拒否する。

    引数: args/kwargs (object) は任意の通信引数。返り値: なし (None)。常に例外を送出する。
    """
    raise AssertionError('この検査では通信を許可しません')


def sha(path: Path) -> str:
    """機能: ファイルの内容を変更せず同一性を記録する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same(left: dict, right: dict) -> None:
    """機能: 旧版・新版の全返済・組・注文・時価・集計を厳密一致で比較する。

    引数: left/right (dict)。返り値: なし (None)。
    """
    assert set(left) == set(right)
    for name in left:
        np.testing.assert_array_equal(left[name], right[name], err_msg=name)


def account(result: dict, ready: dict, cap: int, final: bool = True) -> None:
    """機能: 注文現金・在庫を独立復元し、因果執行・場末・上限を確認する。

    引数: result/ready (dict)、cap (int)、final (bool)。返り値: なし (None)。
    """
    orders, trades = result['orders'], result['trades']
    changes = np.zeros((len(ready['last']), 3))
    for row, source, _, side, qty, price, _, opening in orders:
        assert 0 <= source < row < len(changes) and qty == int(qty) and qty > 0
        changes[int(row), 0] -= side * qty * price
        held_side = side if opening else -side
        changes[int(row), 1 if held_side > 0 else 2] += qty if opening else -qty
    series = np.cumsum(changes, axis=0)
    cash, longs, shorts = series.T
    equity = cash + (longs - shorts) * ready['last']
    np.testing.assert_allclose(equity, result['curve'][:, 0], atol=1e-7, rtol=0)
    np.testing.assert_array_equal(longs, result['curve'][:, 2])
    np.testing.assert_array_equal(shorts, result['curve'][:, 3])
    assert np.all((longs >= 0) & (longs <= cap) & (shorts >= 0) & (shorts <= cap))
    np.testing.assert_allclose(trades[:, 10], trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]), atol=1e-7)
    np.testing.assert_allclose(sum(trades[:, 10]), result['stats'][0], atol=1e-7)
    if final:
        assert longs[-1] == shorts[-1] == 0
        closing = np.flatnonzero(ready['time_s'] >= ready['limit'])[0] + 1
        assert not (longs[closing:] + shorts[closing:]).any()


class Normalize(ast.NodeTransformer):
    """機能: コメント相当の文書を除き、管理方向名だけを旧入口方向名へ戻す構文比較器。"""

    def visit_Name(self, node: ast.Name) -> ast.Name:
        """機能: context 参照だけを state へ戻す。

        引数: node (ast.Name)。返り値: 置換後ノード (ast.Name)。
        """
        if node.id == 'context':
            node.id = 'state'
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        """機能: 文書文字列と追加した管理引数だけを除いて本文比較を可能にする。

        引数: node (ast.FunctionDef)。返り値: 正規化ノード (ast.FunctionDef)。
        """
        node.body = [item for item in node.body if not (isinstance(item, ast.Expr)
                     and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str))]
        if node.name == 'simulate':
            node.args.args = [arg for arg in node.args.args if arg.arg != 'context']
        return self.generic_visit(node)


def syntax_check() -> dict:
    """機能: シミュレーションの変更が管理方向４参照と追加引数だけであることを検査する。

    引数: なし。返り値: 構文比較記録 (dict)。
    """
    old_tree = ast.parse((OLD / 'engine.py').read_text(encoding='utf-8'))
    new_tree = ast.parse((HERE / 'engine_context.py').read_text(encoding='utf-8'))
    old_functions = {node.name: node for node in old_tree.body if isinstance(node, ast.FunctionDef)}
    new_functions = {node.name: node for node in new_tree.body if isinstance(node, ast.FunctionDef)}
    for name in ('rounded', 'close_positions', 'inventory', 'simulate'):
        old = Normalize().visit(copy.deepcopy(old_functions[name]))
        new = Normalize().visit(copy.deepcopy(new_functions[name]))
        assert ast.dump(old, include_attributes=False) == ast.dump(new, include_attributes=False), name
    references = [node for node in ast.walk(new_functions['simulate']) if isinstance(node, ast.Subscript)
                  and isinstance(node.value, ast.Name) and node.value.id == 'context']
    assert len(references) == 4
    assert engine_context.PARAMS == previous.PARAMS and engine_context.REASONS == previous.REASONS
    return {'管理方向参照の変更箇所': 4, '価格注文会計場末の構文同一': True, 'PARAMSと理由コード同一': True}


def fixture(prices: list | None = None, count: int = 30, step: float = 60.) -> tuple[dict, dict]:
    """機能: 外部データを使わず、入口・管理方向の効果を切り分ける合成相場を作る。

    引数: prices (list|None)、count (int)、step (float)。返り値: 入力と固定管理設定 (tuple[dict,dict])。
    """
    values = np.asarray(prices if prices is not None else [100.] * count, dtype=float)
    ready = {'time_s': np.arange(len(values), dtype=float) * step, 'last': values,
             'atr': np.ones(len(values)), 'tick': .1, 'start': 0., 'limit': (len(values) - 2) * step,
             'us_open': np.inf}
    spec = next(s for s in managers.manager_catalog() if s['id'] == 'G18')
    cfg = managers.make_config(spec, 'TOPIX', ready)
    cfg.update(warmup_min=0., entry_cutoff_min=0., cooldown_min=0., stop_atr=20., main_trail=np.inf)
    return ready, cfg


def synthetic() -> list[dict]:
    """機能: 入口中立・管理反転・中立時計・カバー返済の境界を個別に確認する。

    引数: なし。返り値: 合成検査名と結果 (list[dict])。現在セッションや新候補を使用しない。
    """
    records = []
    ready, cfg = fixture()
    entry = np.zeros(len(ready['last']), dtype=np.int8)
    entry[0] = 1
    context = np.ones_like(entry)
    neutral_cfg = dict(cfg, neutral_min=10.)
    baseline = previous.run(ready, entry, neutral_cfg, True)
    held = engine_context.run(ready, entry, neutral_cfg, True, context)
    assert int(baseline['trades'][0, 9]) == 10 and int(baseline['trades'][0, 7]) == 12
    assert int(held['trades'][0, 9]) == 9 and int(held['trades'][0, 7]) == 29
    account(held, ready, cfg['audit_cap'])
    records.append({'検査': '入口中立が続いても主方向保持中は10分中立返済を起こさない', '一致': True})

    opposite = context.copy()
    opposite[8:] = -1
    answer = engine_context.run(ready, entry, dict(cfg, signal_exit=1), True, opposite)
    trade = answer['trades'][0]
    assert int(trade[7]) == 9 and int(trade[9]) == 13
    assert int(answer['orders'][1, 1]) == 8
    account(answer, ready, cfg['audit_cap'])
    records.append({'検査': '管理方向反転の観測行では返済せず次行で方向撤回返済', '一致': True})

    answer = engine_context.run(ready, entry, dict(cfg, reverse_mode=1), True, opposite)
    reverse_orders = answer['orders'][answer['orders'][:, 0] == 9]
    assert len(reverse_orders) == 2
    np.testing.assert_array_equal(reverse_orders[:, [1, 3, 6, 7]], [[8, -1, 5, 0], [8, -1, 23, 1]])
    account(answer, ready, cfg['audit_cap'])
    records.append({'検査': '反転補充は既存の保有管理に含まれ入口中立でも次行で実行', '一致': True})

    neutral = context.copy()
    neutral[5:7], neutral[9:] = 0, 0
    answer = engine_context.run(ready, entry, neutral_cfg, True, neutral)
    assert int(answer['trades'][0, 7]) == 20 and int(answer['trades'][0, 9]) == 10
    records.append({'検査': '中立時計は管理方向の再確認でリセットし最後の中立から10分後の次行返済', '一致': True})

    no_entry = engine_context.run(ready, np.zeros_like(entry), cfg, True, context)
    assert not len(no_entry['orders'])
    opposite_entry = np.full_like(entry, -1)
    answer = engine_context.run(ready, opposite_entry, cfg, True, context)
    assert answer['orders'][0, 3] == -1
    records.append({'検査': 'フラット時の通常新規は管理方向だけで発火しない', '一致': True})

    cancel_ready, cancel_cfg = fixture([100., 100.2, 101., 101., 101., 101.])
    cancel_entry = np.array([1, 0, 0, 0, 0, 0], dtype=np.int8)
    cancel_cfg.update(entry_mode=0, entry_atr=1.)
    answer = engine_context.run(cancel_ready, cancel_entry, cancel_cfg, True, np.ones(6, dtype=np.int8))
    assert not len(answer['orders'])
    records.append({'検査': '未約定注文の取消は入口中立で成立し管理方向保持で延命しない', '一致': True})

    add_ready, add_cfg = fixture([100., 100., 101., 102., 103., 104., 105., 106.])
    add_cfg.update(initial_qty=2, add_mode=1, add_qty=1, add_step=1.)
    add_entry = np.zeros(8, dtype=np.int8)
    add_entry[0] = 1
    answer = engine_context.run(add_ready, add_entry, add_cfg, True, np.ones(8, dtype=np.int8))
    assert not (answer['orders'][:, 6] == 22).any()
    adds = engine_context.run(add_ready, np.ones(8, dtype=np.int8), add_cfg, True, np.ones(8, dtype=np.int8))
    assert (adds['orders'][:, 6] == 22).any()
    account(adds, add_ready, add_cfg['audit_cap'])
    records.append({'検査': '利益増玉には入口方向一致が必要で管理方向保持だけでは追加しない', '一致': True})

    cover_ready, cover_cfg = fixture([100., 100., 99.5, 99.3, 99.2, 99.2, 99.2, 99.2])
    cover_cfg.update(initial_qty=4, hedge_ratio=.5, hedge_trigger=.5, cover_trail=np.inf)
    cover_entry = np.zeros(8, dtype=np.int8)
    cover_entry[0] = 1
    cover_context = np.zeros(8, dtype=np.int8)
    cover_context[3:] = 1
    answer = engine_context.run(cover_ready, cover_entry, cover_cfg, True, cover_context)
    take = answer['orders'][answer['orders'][:, 6] == 6]
    assert len(take) and take[0, 0] == 4 and take[0, 1] == 3
    old = engine_context.run(cover_ready, cover_entry, cover_cfg, True)
    assert not (old['orders'][:, 6] == 6).any()
    account(answer, cover_ready, cover_cfg['audit_cap'])
    records.append({'検査': '利益中カバー返済の主方向再確認は管理方向を用いて次行執行', '一致': True})

    invalids = [context.tolist(), context.astype(float), context.astype(np.int64), context.reshape(-1, 1),
                context[:-1], np.full_like(context, 2)]
    for invalid in invalids:
        try:
            engine_context.run(ready, entry, cfg, True, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('不正な管理方向入力が受理された')
    records.append({'検査': '管理方向の型・次元・行数・値域６反例を拒否', '一致': True})
    return records


def compatibility() -> dict:
    """機能: 旧保存入力の昼夜・両銘柄で旧20管理の互換性だけを検査する。

    引数: なし。返り値: 比較件数と台帳ハッシュ (dict)。新しい性能順位や損益表は作らない。
    """
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    directions = pickle.loads((OLD / 'directions.pkl').read_bytes())['F32']
    sessions = sorted({key[0] for key in inputs})[:2]
    keys = [key for key in inputs if key[0] in sessions]
    assert len(keys) == 4 and any('Day' in key[0] for key in keys) and any('Night' in key[0] for key in keys)
    count, hasher = 0, hashlib.sha256()
    for key in keys:
        ready, state = inputs[key], directions[key]
        assert state.dtype == np.int8
        for spec in managers.manager_catalog():
            cfg = managers.make_config(spec, key[1], ready)
            old = previous.run(ready, state, cfg, True)
            implicit = engine_context.run(ready, state, cfg, True)
            explicit = engine_context.run(ready, state, cfg, True, state)
            same(old, implicit)
            same(old, explicit)
            account(explicit, ready, cfg['audit_cap'])
            hasher.update(str((key, spec['id'])).encode())
            hasher.update(explicit['trades'].tobytes())
            count += 1
    return {'入力': [list(key) for key in keys], '信号': '既存F32', '旧管理数': 20,
            '旧版対既定context比較': count, '旧版対明示context比較': count,
            '新候補の収益評価': False, '一致台帳SHA256': hasher.hexdigest()}


def main() -> None:
    """機能: 通信と現在データを使用せず、追加した入力契約だけを検証する。

    引数: なし。返り値: なし (None)。新しい監査JSON・MDへ保存する。
    """
    socket.socket.connect = no_network
    socket.create_connection = no_network
    urllib.request.OpenerDirector.open = no_network
    originals = {str(p): sha(p) for p in [OLD / 'engine.py', OLD / 'managers.py', OLD / 'inputs.pkl', OLD / 'directions.pkl']}
    result = {'API取得': 0, '現在スナップショット参照': False, '新手法の成績計算': False,
              '構文比較': syntax_check(), '合成': synthetic(), '旧版互換': compatibility()}
    assert originals == {path: sha(Path(path)) for path in originals}
    result['旧ファイル不変SHA256'] = originals
    result['新エンジンSHA256'] = sha(HERE / 'engine_context.py')
    (HERE / 'engine_context_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 入口と保有管理の分離：実装監査', '',
             '価格注文・次行執行・部分返済・会計・数量上限・場末処理は変更していません。',
             '構文比較でも、シミュレーション本体は管理方向４参照と追加引数を旧形へ戻すと完全に一致しました。', '',
             '変更する判断は、保有中の反対方向返済、反転、利益中カバー返済の主方向再確認、中立タイマーです。',
             'フラット時の通常新規、未約定の取消、増玉、連敗後の再開は入口方向を使います。',
             '反転に伴うカバー昇格と不足分の補充は保有管理の一部であり、管理方向の反転から次行に従来どおり実行します。', '',
             '旧保存の昼夜・両銘柄４入力×20管理について、context省略とcontext=stateの各80比較で注文・返済・組・曲線・集計が旧版と厳密一致しました。',
             '入口中立でも主方向保持、反対主方向の次行返済、10分中立タイマーのリセット、カバー返済、入口だけの新規・取消・増玉を合成で確認しました。',
             '現在スナップショットは参照せず、新手法の損益比較も実施していません。旧コード・入力のSHA256は不変です。', '',
             '観測価格版はこの新エンジンから別ファイルへ複写し、価格成立後の fill=level を fill=p if event!=6 else level、新規の anchor=p if pending_market else pending_level を anchor=p に各１箇所だけ変換します。',
             '変換元SHA256・置換件数・生成先SHA256を固定し、通常の import engine_context_observed を使います。動的な別名importはNumbaキャッシュの参照先不整合を起こし得るため避けます。',
             'この派生は指値の部分利確を指定価格のまま残し、逆指値等の到達後価格だけを変える補足検査です。主前提の費用０・指定価格約定とは区別します。']
    (HERE / 'engine_context_audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
