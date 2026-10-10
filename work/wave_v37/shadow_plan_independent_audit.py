"""既存固定A0の計画記録追加だけを、旧8結果と原本順で独立照合する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent / 'wave_v33'))
import dynamic_atr_engine_audit as fixtures
sys.path.insert(0, str(HERE.parent / 'wave_v34'))
import engine_scheduler as old
sys.path.insert(0, str(HERE))
import engine_shadow_plan as new
import partial_inputs as inputs_api

FIELDS = ('trades', 'cycles', 'curve', 'orders', 'stats', 'atr_curve', 'prepare_events', 'entry_preparations')
P = {name: i for i, name in enumerate(new.PLAN_COLUMNS)}


def digest(path: Path) -> str:
    """機能: 変更前後を検査する指紋を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deny(*args, **kwargs):
    """機能: 誤った通信を即時拒否する。

    引数: args/kwargs (任意)。返り値: なし。必ず例外を送出する。
    """
    raise AssertionError('この監査では通信を使用しない')


def clipped(ready: dict, count: int) -> dict:
    """機能: 場末等の既知定数を変えず原本の後続行だけ削除する。

    引数: ready (dict)、count (int)。返り値: 短縮入力 (dict)。
    """
    n = len(ready['last'])
    return {k: v[:count].copy() if isinstance(v, np.ndarray) and v.ndim and len(v) == n else v
            for k, v in ready.items()}


def equal(actual: dict, expected: dict) -> None:
    """機能: 計画以外の旧8配列を全要素厳密に検査する。

    引数: actual/expected (dict)。返り値: なし (None)。
    """
    for field in FIELDS:
        np.testing.assert_array_equal(actual[field], expected[field], err_msg=field)


def inspect_plans(ready: dict, result: dict) -> dict:
    """機能: 原本行後の計画を在庫曲線・準備・発注元行へ独立に対応付ける。

    引数: ready/result (dict)。返り値: 件数と検査結果 (dict)。
    """
    plans = result['plans']
    assert plans.shape == (len(ready['last']), len(P))
    valid = np.isfinite(ready['last']) & (ready['last'] > 0)
    rows = np.flatnonzero(valid)
    np.testing.assert_array_equal(plans[rows, P['plan_source_row']], rows)
    np.testing.assert_array_equal(plans[rows, P['shadow_qty']], result['curve'][rows, 2:4].sum(axis=1))
    np.testing.assert_array_equal(plans[rows, P['shadow_realized']], result['curve'][rows, 1])
    for record in result['prepare_events']:
        identity, row, side, level, atr, expiry, qty = record
        planned = plans[int(row)]
        np.testing.assert_array_equal(planned[[P[name] for name in
            ('pending_prepare_id', 'pending_prepare_row', 'pending_direction', 'pending_level',
             'pending_atr', 'pending_expiry', 'pending_qty')]],
            [identity, row, side, level, atr, expiry, qty])
    for order in result['orders']:
        filled, source = int(order[0]), int(order[1])
        assert 0 <= source < filled
        if order[7] == 1:
            planned = plans[source]
            assert planned[P['pending_direction']] == order[3]
            assert planned[P['pending_qty']] == order[4]
        else:
            assert plans[source, P['direction']] != 0
    return dict(原本行数=len(plans), 新設数=len(result['prepare_events']), 注文数=len(result['orders']))


def check_causal(ready: dict, state: np.ndarray, config: dict, result: dict, cuts: list[int]) -> None:
    """機能: 同時刻の後続行も未来として切断・改変し、過去計画を比較する。

    引数: ready/config/result (dict)、state (ndarray)、cuts (list[int])。返り値: なし (None)。
    """
    for count in cuts:
        short = new.run(clipped(ready, count), state[:count], config, True)
        np.testing.assert_array_equal(short['plans'], result['plans'][:count])
        future = deepcopy(ready)
        future['last'][count:] = 50000. + np.arange(len(state) - count) * ready['tick']
        future['atr'][count:] = 900.
        alternate = state.copy(); alternate[count:] = np.where(state[count:] == 1, -1, 1)
        changed = new.run(future, alternate, config, True)
        np.testing.assert_array_equal(changed['plans'][:count], result['plans'][:count])


def synthetic() -> list[dict]:
    """機能: 追跡更新と新設の区別、同時刻順、欠測、詳細省略を人工入力で検査する。

    引数: なし。返り値: 合成検査の一覧 (list[dict])。
    """
    cases = []
    for prices, tied in (([100., 99., 98., 99., 110., 105., 98.], False),
                         ([100., 101., 120., 113., 107.], True),
                         ([100., np.nan, 101., 120., 110.], False)):
        ready, state, config, _ = fixtures.fixture(prices)
        if tied:
            ready['time_s'][:len(prices)] = 0.
        actual = new.run(ready, state, config, True)
        equal(actual, old.run(ready, state, config, True))
        inspect_plans(ready, actual)
        check_causal(ready, state, config, actual, [2, len(prices) - 1])
        compact = new.run(ready, state, config, False)
        np.testing.assert_array_equal(compact['plans'], actual['plans'])
        # 欠測行は前の有効価格行の注文計画を保持する。ATRの診断最新値とは区別する。
        for row in np.flatnonzero(~np.isfinite(ready['last'])):
            np.testing.assert_array_equal(actual['plans'][row], actual['plans'][row - 1])
        cases.append(dict(人工価格数=len(prices), 同時刻=tied, 旧8同値=True, prefix数=2, future数=2,
                          詳細省略計画同値=True))
    return cases


def main() -> None:
    """機能: 既知H019固定A0だけの全26互換と計画因果性を記録する。

    引数: なし。返り値: なし (None)。新しい実枠制御の損益を計算しない。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    references = [Path(__file__), HERE / 'engine_shadow_plan.py', HERE / 'build_shadow_plan.py',
                  HERE / 'shadow_plan_build.json', HERE / 'partial_input_fixed.json',
                  HERE.parent / 'wave_v34/engine_scheduler.py',
                  HERE.parent / 'wave_v23/inputs.pkl',
                  HERE.parent / 'wave_v30/探索条件の固定.json',
                  HERE.parent / 'wave_v35/entries/H019__C100.npz']
    before = {str(path.relative_to(ROOT)).replace('\\', '/'): digest(path) for path in references}
    checks = synthetic()
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    inputs_api.initialize(inputs)
    rows = []
    for key, ready in inputs.items():
        state = inputs_api.entry('H019', 1., key)
        config = fixtures.config(key[1], ready)
        actual = new.run(ready, state, config, True)
        equal(actual, old.run(ready, state, config, True))
        counts = inspect_plans(ready, actual)
        n = len(state)
        duplicate = np.flatnonzero(np.diff(ready['time_s']) == 0) + 1
        assert len(duplicate)
        tied = int(duplicate[np.argmin(abs(duplicate - int(n * .73)))])
        check_causal(ready, state, config, actual, [int(n * .37), tied])
        rows.append(dict(session=key[0], symbol=key[1], 旧8同値=True, prefix数=2, future数=2,
                         同時刻群途中=True, **counts))
    assert len(rows) == 26
    assert before == {str(path.relative_to(ROOT)).replace('\\', '/'): digest(path) for path in references}
    payload = dict(全合格=True, 旧8同値入力数=26, 計画prefix数=52, 計画future数=52,
                   合成検査=checks, 検査=rows, 参照SHA256=before,
                   既知固定A0互換だけ=True, 新しい実枠制御の損益計算=False,
                   現在保存物使用=False, API取得数=0,
                   限定='欠測価格行のplansは最後の有効価格行の計画であり、同欠測行で更新されたATR診断値とは異なる。')
    (HERE / 'shadow_plan_independent_audit.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    (HERE / 'shadow_plan_independent_audit.md').write_text(
        '# 影計画の独立監査\n\n'
        '旧H019固定A0の26入力で旧8結果が完全一致。計画の切断52件・未来価格/ATR/方向改変52件が一致した。'
        '各入力の一方の境界は同じ最終約定時刻を持つ原本群の途中である。新しい実枠制御の損益は未計算。\n\n'
        'plans[i]は行iの処理後に決まり、原本の後続行からのみ有効。新設と追跡更新を分け、全新設と全注文の参照行を照合した。'
        '価格欠測行は前の有効価格行の注文計画をコピーするため、同じ欠測行で更新されたATR診断値を表すものではない。\n',
        encoding='utf-8')
    print('旧8結果26一致、計画prefix52/future52、合成3一致。新実枠損益なし。', flush=True)


if __name__ == '__main__':
    main()
