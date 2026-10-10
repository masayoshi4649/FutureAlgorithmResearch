"""選択器の所有者・取消・休止を合成相場と旧固定Tの一致だけで検査する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import urllib.request

import numpy as np

import engine_selector as engine

HERE = Path(__file__).resolve().parent
V28, OLD = HERE.parent / 'wave_v28', HERE.parent / 'wave_v23'
sys.path.insert(0, str(V28))
import engine_context as previous
sys.path.insert(0, str(OLD))
import managers

S = {name: index for index, name in enumerate(engine.SELECTION_COLUMNS)}
E = {name: index for index, name in enumerate(engine.EVENT_COLUMNS)}


def deny(*args: object, **kwargs: object) -> None:
    """機能: 外部通信を拒否する。

    引数: args/kwargs (object)。返り値: なし (None)。常に例外。
    """
    raise AssertionError('選択注文器の監査では外部通信を禁止します')


def config(symbol: str, ready: dict) -> dict:
    """機能: 既に凍結されたD273と同値のL000設定を読む。

    引数: symbol (str)、ready (dict)。返り値: 共通設定 (dict)。
    """
    fixed = json.loads((HERE.parent / 'wave_v30' / '探索条件の固定.json').read_text(encoding='utf-8'))
    spec = next(row for row in fixed['managers'] if row['id'] == 'L000')
    return managers.make_config(spec, symbol, ready)


def fixture(prices: list[float], request: list[int] | None = None, states: list[list[int]] | None = None,
            times: list[float] | None = None, atr: list[float] | None = None) -> tuple[dict, np.ndarray, np.ndarray, dict]:
    """機能: 初期準備済みの合成相場に場末判断と次行返済を付ける。

    引数: prices/times/atr (list[float]|None)、request (list[int]|None)、states (list[list[int]]|None)。
    返り値: ready・二方向・要求ID・D273 (tuple)。実データを使わない。
    """
    count = len(prices)
    times = list(map(float, times if times is not None else range(count)))
    entry = states if states is not None else [[1, 1] for _ in prices]
    requested = request if request is not None else [1] * count
    atr = atr if atr is not None else [4.] * count
    ready = {'time_s': np.array(times + [10000., 10001.]), 'last': np.array(prices + [prices[-1]] * 2, dtype=float),
             'atr': np.array(list(atr) + [atr[-1]] * 2, dtype=float), 'tick': 1., 'start': -1200.,
             'limit': 10000., 'us_open': np.inf, 'seq': np.arange(count + 2)}
    states_array = np.asarray(entry + [entry[-1]] * 2, dtype=np.int8)
    request_array = np.asarray(requested + [requested[-1]] * 2, dtype=np.int8)
    return ready, states_array, request_array, config('TOPIX', ready)


def events(result: dict, code: int) -> np.ndarray:
    """機能: 指定した種類の所有者イベントを抽出する。

    引数: result (dict)、code (int)。返り値: 該当行列 (ndarray)。
    """
    rows = result['selection_events']
    return rows[rows[:, E['event']] == code]


def same_old(actual: dict, expected: dict) -> None:
    """機能: 旧5結果の全要素を厳密比較する。

    引数: actual/expected (dict)。返り値: なし (None)。
    """
    for field in ('trades', 'cycles', 'curve', 'orders', 'stats'):
        np.testing.assert_array_equal(actual[field], expected[field], err_msg=field)


def accounting(ready: dict, result: dict, cfg: dict, final: bool = True) -> None:
    """機能: 約定台帳から両保有・現金・時価と所有者を独立に確認する。

    引数: ready/result/cfg (dict)、final (bool)。返り値: なし (None)。
    """
    orders, trades, curve, selected = (result[field] for field in ('orders', 'trades', 'curve', 'selection_curve'))
    changes = np.zeros((len(ready['last']), 3))
    for row, source, _, side, qty, price, _, opening in orders:
        row, source = int(row), int(source)
        assert 0 <= source < row
        changes[row, 0] -= side * qty * price
        held_side = side if opening else -side
        changes[row, 1 if held_side == 1 else 2] += qty if opening else -qty
        if opening:
            assert selected[row, S['position_owner_id']] in (1, 2)
            assert selected[row, S['position_entry_source_id']] in (1, 2)
    cash, long, short = np.cumsum(changes, axis=0).T
    equity = cash + (long - short) * ready['last']
    np.testing.assert_allclose(curve[:, [0, 2, 3, 5, 6]], np.column_stack((equity, long, short, cash, long - short)), atol=1e-7, rtol=0)
    assert np.all((long >= 0) & (short >= 0) & (long <= cfg['audit_cap']) & (short <= cfg['audit_cap']))
    np.testing.assert_allclose(trades[:, 10], trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]), atol=1e-7, rtol=0)
    held = long + short > 0
    assert np.all(np.isin(selected[held, S['position_owner_id']], (1, 2)))
    assert np.all(selected[~held, S['position_owner_id']] == 0)
    if final:
        assert long[-1] == short[-1] == 0
        np.testing.assert_allclose(sum(trades[:, 10]), cash[-1], atol=1e-7, rtol=0)
    for order in events(result, 7):
        row = int(order[E['row']])
        assert order[E['entry_source_id']] == selected[row, S['position_entry_source_id']]
        assert order[E['position_owner_id']] == selected[row, S['position_owner_id']]
    for canceled in events(result, 2):
        row = int(canceled[E['row']])
        acknowledged = events(result, 3)
        hit = acknowledged[acknowledged[:, E['source_row']] == row]
        assert len(hit) == 1 and hit[0, E['row']] == row + 1


def synthetic() -> list[dict]:
    """機能: 意地悪な同方向切替・既存約定優先・部分返済・休止の反例を作る。

    引数: なし。返り値: 検査名と結果 (list[dict])。新規の相場成績は評価しない。
    """
    checks = []
    r, states, request, cfg = fixture([100., 101., 108., 110., 104., 95.])
    for branch in (1, 2):
        fixed = np.full(len(request), branch, dtype=np.int8)
        answer = engine.run(r, states, fixed, cfg, True)
        old = previous.run(r, states[:, branch - 1], cfg, True)
        same_old(answer, old)
        accounting(r, answer, cfg)
        assert np.all(answer['selection_curve'][:, S['applied_id']] == branch)
    checks.append({'検査': '固定T/Rは部分利確を含む旧5結果と厳密一致', '一致': True})

    # ----------------------------------------
    r, states, request, cfg = fixture([100., 100., 103., 106.], [1, 2, 2, 2], atr=[4., 8., 12., 12.])
    answer = engine.run(r, states, request, cfg, True)
    accounting(r, answer, cfg)
    opening = answer['orders'][answer['orders'][:, 7] == 1]
    assert opening[0, 0] == 3 and opening[0, 1] == 2 and opening[0, 5] == 106
    assert events(answer, 2)[0, E['row']] == 1 and events(answer, 3)[0, E['row']] == 2
    assert events(answer, 12)[0, E['row']] == 2
    assert answer['selection_curve'][2, S['pending_atr']] == 12
    assert answer['selection_curve'][2, S['pending_expiry']] == 302
    assert answer['selection_curve'][3, S['position_owner_id']] == 2
    checks.append({'検査': '同方向ID変更でも取消→次行確認→新ATRと価格で再準備→さらに次行約定', '一致': True})
    for override in (1, 2):
        modified = states.copy()
        modified[:, 1 - (override - 1)] *= -1
        result = engine.run(r, modified, request, cfg, True, source_override=override)
        accounting(r, result, cfg)
        assert events(result, 7)[0, E['position_owner_id']] == 2
        assert events(result, 7)[0, E['entry_source_id']] == override
    checks.append({'検査': '取消対照は要求所有IDと実T/R入口源を混同しない', '一致': True})

    # ----------------------------------------
    r, states, request, cfg = fixture([100., 102., 103.], [1, 2, 2], [[1, -1]] * 3)
    answer = engine.run(r, states, request, cfg, True)
    accounting(r, answer, cfg)
    assert answer['orders'][0, 0] == 1 and answer['orders'][0, 5] == 101
    assert answer['selection_curve'][1, S['request_id']] == 2
    assert answer['selection_curve'][1, S['position_owner_id']] == 1
    assert len(events(answer, 2)) == 0 and len(events(answer, 11)) >= 1
    checks.append({'検査': '要求変更と価格到達が同じ行なら旧注文が先に約定し旧所有者で保持', '一致': True})
    r, states, request, cfg = fixture([100., 100., 103., 104.], [1, 2, 1, 1])
    answer = engine.run(r, states, request, cfg, True)
    accounting(r, answer, cfg)
    assert answer['orders'][0, 0] == 3 and answer['orders'][0, 5] == 104
    assert answer['selection_curve'][3, S['position_owner_id']] == 1
    assert events(answer, 3)[0, E['row']] == 2
    checks.append({'検査': '取消確認行で要求が元に戻っても旧注文は復活せず最新要求で再準備', '一致': True})
    r, states, request, cfg = fixture([100., 100., 101.], [1, 2, 2], [[0, 1]] * 3)
    answer = engine.run(r, states, request, cfg, True)
    assert len(events(answer, 2)) == 0 and answer['orders'][0, 0] == 2
    accounting(r, answer, cfg)
    checks.append({'検査': '未約定なしのID変更では余計な取消待ちを作らず現在準備・次行約定', '一致': True})
    r, states, request, cfg = fixture([100., 100., 101.], [1, 2, 2], times=[0., 300., 301.])
    answer = engine.run(r, states, request, cfg, True)
    assert len(events(answer, 2)) == 0 and answer['orders'][0, 0] == 2
    assert len(events(answer, 10)) == 1
    accounting(r, answer, cfg)
    checks.append({'検査': '期限切れ注文は有効pendingと扱わずID変更に余分な取消待ちを追加しない', '一致': True})

    # ----------------------------------------
    r, states, request, cfg = fixture([100., 101., 96., 96., 97., 98., 99.], [1, 1, 2, 2, 2, 2, 2],
                                      times=[0., 1., 2., 100., 301., 302., 303.])
    answer = engine.run(r, states, request, cfg, True)
    accounting(r, answer, cfg)
    opening = answer['orders'][answer['orders'][:, 7] == 1]
    assert opening[1, 0] == 6 and opening[1, 1] == 5
    assert answer['selection_curve'][2, S['cooldown_until']] == 302
    assert not answer['selection_curve'][3:5, S['pending_direction']].any()
    checks.append({'検査': '損切り後にIDを変更しても完全返済から5分待ち、解禁後の新準備と次行約定', '一致': True})
    r, states, request, cfg = fixture([100., 101., 110., 104.], [1, 1, 2, 2], [[1, -1]] * 4)
    answer = engine.run(r, states, request, cfg, True)
    accounting(r, answer, cfg)
    assert answer['curve'][2, 2] == 3 and answer['selection_curve'][2, S['position_owner_id']] == 1
    assert events(answer, 8)[0, E['quantity']] == 2 and events(answer, 8)[0, E['position_owner_id']] == 1
    assert answer['selection_curve'][2, S['position_atr']] == 4
    same_old(answer, previous.run(r, states[:, 0], cfg, True))
    checks.append({'検査': '部分利確後の残玉・初期ATR・出口を要求変更でも維持する', '一致': True})
    r, states, request, cfg = fixture([100., 100., 103., 104.], [1, 2, 2, 2], times=[0., 0., 0., 0.])
    answer = engine.run(r, states, request, cfg, True)
    accounting(r, answer, cfg)
    assert answer['orders'][0, 0] == 3 and answer['orders'][0, 1] == 2
    checks.append({'検査': '同時刻の行でも取消確認と再発注を原本行順に分離する', '一致': True})

    # ----------------------------------------
    r, states, request, cfg = fixture([100., 100., np.nan, 103., 104.], [1, 2, 2, 2, 2])
    answer = engine.run(r, states, request, cfg, True)
    assert events(answer, 3)[0, E['row']] == 2
    assert answer['selection_curve'][2, S['applied_id']] == 2
    assert answer['selection_curve'][2, S['entry_source_id']] == 2
    assert answer['selection_curve'][2, S['pending_owner_id']] == 0
    assert np.isnan(answer['selection_curve'][2, S['pending_level']])
    assert answer['orders'][0, 0] == 4 and answer['orders'][0, 1] == 3
    fixed = np.ones(len(request), dtype=np.int8)
    same_old(engine.run(r, states, fixed, cfg, True), previous.run(r, states[:, 0], cfg, True))
    checks.append({'検査': '価格欠測行でも前行取消を確認して旧注文を消し、新しい価格判断は次の有効行へ待つ', '一致': True})
    r, states, request, cfg = fixture([100., 100., 103., 104.], [1, 2, 2, 2], times=[9697., 9698., 9700., 9701.])
    answer = engine.run(r, states, request, cfg, True)
    accounting(r, answer, cfg)
    assert len(answer['orders']) == 0 and len(events(answer, 3)) == 1
    assert len(events(answer, 12)) == 0
    checks.append({'検査': '新規締切到達行で取消確認しても再準備せず、締切後の価格到達で約定しない', '一致': True})
    r, states, request, cfg = fixture([100., 101., 110., 97., 97., 96.], [1, 1, 2, 2, 2, 2],
                                      [[1, -1]] * 6, times=[0., 1., 2., 3., 303., 304.])
    answer = engine.run(r, states, request, cfg, True)
    accounting(r, answer, cfg)
    opening = answer['orders'][answer['orders'][:, 7] == 1]
    assert answer['selection_curve'][2, S['position_owner_id']] == 1
    assert answer['selection_curve'][3, S['position_owner_id']] == 0
    assert answer['selection_curve'][3, S['applied_id']] == 2
    assert opening[1, 0] == 5 and opening[1, 1] == 4 and opening[1, 3] == -1
    assert answer['selection_curve'][5, S['position_owner_id']] == 2
    checks.append({'検査': '保有中に保留した反対要求は完全返済後に適用し、元の5分休止後だけ別枝で売り直す', '一致': True})
    other, other_states, other_request, other_cfg = fixture([100., 100., 100., 100., 100., 99.], [1, 1, 2, 2, 2, 2],
                                                           [[1, -1]] * 6, times=[0., 1., 2., 3., 303., 304.])
    second = engine.run(other, other_states, other_request, other_cfg, True)
    assert answer['selection_curve'][2, S['position_owner_id']] == 1
    assert second['selection_curve'][2, S['cancel_wait']] == 1
    assert second['selection_curve'][3, S['applied_id']] == 2
    checks.append({'検査': '両市場の要求が共通でも保有市場とフラット市場の取消・適用は独立する', '一致': True})

    # ----------------------------------------
    r, states, request, cfg = fixture([100., 102., 114., 100.])
    observed = engine.run(r, states, request, cfg, True, observed_fill=True)
    specified = engine.run(r, states, request, cfg, True)
    accounting(r, observed, cfg)
    for row in observed['orders']:
        assert row[5] == r['last'][int(row[0])]
    assert specified['orders'][0, 5] == 101 and observed['orders'][0, 5] == 102
    assert specified['trades'][0, 5] == 109 and observed['trades'][0, 5] == 114
    checks.append({'検査': '観測モデルは新規と部分利確を含む全約定で現観測価格を使う', '一致': True})
    reflected = dict(r, last=300. - r['last'])
    for observed_fill in (False, True):
        a = engine.run(r, states, request, cfg, True, observed_fill=observed_fill)
        b = engine.run(reflected, -states, request, cfg, True, observed_fill=observed_fill)
        np.testing.assert_array_equal(a['trades'][:, [0, 1, 3, 6, 7, 8, 9, 10]], b['trades'][:, [0, 1, 3, 6, 7, 8, 9, 10]])
        np.testing.assert_allclose(a['orders'][:, 5] + b['orders'][:, 5], 300., atol=1e-9)
        np.testing.assert_array_equal(a['selection_curve'][:, [S[x] for x in ('request_id', 'applied_id', 'pending_owner_id', 'position_owner_id')]],
                                      b['selection_curve'][:, [S[x] for x in ('request_id', 'applied_id', 'pending_owner_id', 'position_owner_id')]])
    checks.append({'検査': '指定/観測とも価格反射と売買反転で損益・時刻・数量・所有者が対称', '一致': True})
    r, states, request, cfg = fixture([100., 100., 103., 104., 110.], [1, 2, 2, 1, 1])
    full = engine.run(r, states, request, cfg, True)
    cut = 3
    prefix_ready = {key: value[:cut].copy() if isinstance(value, np.ndarray) else value for key, value in r.items()}
    prefix = engine.run(prefix_ready, states[:cut], request[:cut], cfg, True)
    np.testing.assert_array_equal(prefix['selection_curve'], full['selection_curve'][:cut])
    np.testing.assert_array_equal(prefix['selection_events'], full['selection_events'][full['selection_events'][:, E['row']] < cut])
    mutated = deepcopy(r)
    mutated['last'][cut:] = 5000
    mutated['atr'][cut:] = 50
    changed = request.copy();changed[cut:] = 2
    states_changed = states.copy();states_changed[cut:] *= -1
    future = engine.run(mutated, states_changed, changed, cfg, True)
    np.testing.assert_array_equal(future['selection_curve'][:cut], full['selection_curve'][:cut])
    np.testing.assert_array_equal(future['orders'][future['orders'][:, 0] < cut], full['orders'][full['orders'][:, 0] < cut])
    checks.append({'検査': '未来価格/ATR/両方向/要求を削除又は改変しても過去所有曲線・注文・イベント不変', '一致': True})
    compact = engine.run(r, states, request, cfg, False)
    for field in ('selection_curve', 'selection_events', 'orders', 'trades', 'cycles', 'stats'):
        np.testing.assert_array_equal(compact[field], full[field])
    checks.append({'検査': 'detail=Falseでも全行所有曲線とイベント・台帳・集計を保持する', '一致': True})
    for bad in (dict(cfg, lock_fraction=.5), dict(cfg, initial_qty=1), dict(cfg, signal_exit=1)):
        try:
            engine.run(r, states, request, bad)
        except ValueError:
            pass
        else:
            raise AssertionError('共通D273以外を許可した')
    checks.append({'検査': '保護・枚数・方向返済を追加した別管理を明示拒否', '一致': True})
    invalid = [(states.astype(np.int64), request, 0), (states[:, 0], request, 0),
               (states, request.astype(np.int64), 0), (states, np.zeros_like(request), 0),
               (np.full_like(states, 2), request, 0), (states, request, 3)]
    for directions, requests, override in invalid:
        try:
            engine.run(r, directions, requests, cfg, source_override=override)
        except ValueError:
            pass
        else:
            raise AssertionError('不正な方向・要求・上書き入力を許可した')
    checks.append({'検査': '方向と要求IDの形・型・値域および入口上書きの値域を拒否検算', '一致': True})
    return checks


def old_fixed_t() -> int:
    """機能: 既知26区間のH019固定Tで旧5台帳の厳密同値だけを確認する。

    引数: なし。返り値: 一致した区間数 (int)。選抜・順位・新しい損益表は作らない。
    """
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    count = 0
    with np.load(HERE.parent / 'wave_v27' / 'directions' / 'H019.npz') as archive:
        for key, ready in inputs.items():
            state = archive['|'.join(key)]
            pair = np.column_stack((state, -state)).astype(np.int8)
            request = np.ones(len(state), dtype=np.int8)
            cfg = config(key[1], ready)
            answer = engine.run(ready, pair, request, cfg, True)
            same_old(answer, previous.run(ready, state, cfg, True))
            accounting(ready, answer, cfg)
            count += 1
    return count


def main() -> None:
    """機能: 合成検査と任意の旧固定T互換検査を実行し、SHAと成功件数だけを保存する。

    引数: --synthetic-only (bool)。返り値: なし (None)。実選択A/Bの損益は計算しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--synthetic-only', action='store_true')
    args = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    urllib.request.OpenerDirector.open = deny
    paths = [V28 / 'engine_context.py', OLD / 'inputs.pkl', HERE.parent / 'wave_v27' / 'directions' / 'H019.npz']
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    checks = synthetic()
    count = 0 if args.synthetic_only else old_fixed_t()
    assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    record = {'全合格': count == 26 and all(row['一致'] for row in checks),
              '合成全合格': True, '合成境界件数': len(checks), '合成検査': checks, '旧固定T完全一致区間数': count,
              '新規選択損益の実行': False, 'API取得数': 0, '現在保存物使用': False, '旧原本不変': True,
              '旧原本SHA256': before, 'engine_SHA256': hashlib.sha256((HERE / 'engine_selector.py').read_bytes()).hexdigest(),
              'SELECTION_COLUMNS': engine.SELECTION_COLUMNS, 'EVENT_COLUMNS': engine.EVENT_COLUMNS,
              'EVENT_NAMES': engine.EVENT_NAMES, 'PHASE_NAMES': engine.PHASE_NAMES}
    (HERE / 'engine_selector_audit.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print('合成', len(checks), '件、旧固定T', count, '区間一致。選択成績計算なし。', flush=True)


if __name__ == '__main__':
    main()
