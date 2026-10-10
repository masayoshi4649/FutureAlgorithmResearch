"""反転約定を別実装の逐次参照器・手計算・打切り再生で監査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import mirror

OUT = Path(__file__).resolve().parent


def reference(ready: dict, raw: np.ndarray, cap: int, lag: int) -> np.ndarray:
    """機能: 各行を走査する独立参照器で数量と遅延を含む反転を再生する。

    引数: ready (dict)、raw (ndarray)、cap/lag (int)。返り値: ６列の反転記録 (ndarray)。
    """
    n = len(raw)
    answer = np.zeros((n, 6))
    answer[:, :2] = -1
    state = ['未発生']*n
    opening_due = np.full(n, np.inf)
    closing_due = np.full(n, np.inf)
    final = min(len(ready['seq'])-1, np.searchsorted(ready['time_s'], ready['limit']+300)-1)
    for i in range(final+1):
        capacity = [int(ready['bid_qty'][i]), int(ready['ask_qty'][i])]
        for j, trade in enumerate(raw):
            if trade[13] == 1 and int(trade[5]) == i:
                if state[j] == '新規待ち':
                    state[j] = '取消'
                elif state[j] == '保有':
                    state[j] = '返済待ち'
                    closing_due[j] = i+lag
            if int(trade[4]) == i:
                state[j] = '新規待ち'
                opening_due[j] = i+lag
        for j, trade in enumerate(raw):
            if state[j] == '返済待ち' and closing_due[j] <= i:
                side_index = 1 if trade[1] > 0 else 0
                if capacity[side_index]:
                    capacity[side_index] -= 1
                    answer[j, 1:3] = [i, 1]
                    answer[j, 4] = ready['ask' if side_index else 'bid'][i]
                    state[j] = '完了'
        for j, trade in enumerate(raw):
            if state[j] == '新規待ち' and opening_due[j] <= i:
                side_index = 0 if trade[1] > 0 else 1
                gross = sum(value in ('保有', '返済待ち') for value in state)
                if capacity[side_index] and gross < cap:
                    capacity[side_index] -= 1
                    answer[j, 0] = i
                    answer[j, 3] = ready['ask' if side_index else 'bid'][i]
                    state[j] = '保有'
    for j, trade in enumerate(raw):
        if answer[j, 0] < 0:
            continue
        if state[j] in ('保有', '返済待ち'):
            answer[j, 1] = final
            answer[j, 4] = ready['ask' if trade[1] > 0 else 'bid'][final]
        answer[j, 5] = -trade[1]*(answer[j, 4]-answer[j, 3])-2*ready['tick']
    return answer


def fixture(sides: list[int], entries: list[int], exits: list[int],
            bid_qty: list[int], ask_qty: list[int]) -> tuple[dict, np.ndarray]:
    """機能: 手計算しやすい気配と仮想元取引を作成する。

    引数: 方向・入口・出口・両気配数量 (list[int])。返り値: 気配と元取引 (tuple)。
    """
    n = len(bid_qty)
    ready = dict(seq=np.arange(n), time_s=np.arange(n), bid=100+np.arange(n)*10.,
                 ask=110+np.arange(n)*10., bid_qty=np.array(bid_qty), ask_qty=np.array(ask_qty),
                 tick=10., limit=1000.)
    raw = np.zeros((len(sides), 21))
    for j, (s, e, x) in enumerate(zip(sides, entries, exits)):
        raw[j, 1], raw[j, 4], raw[j, 5], raw[j, 13] = s, e, x, 1
    return ready, raw


def manual_and_reference() -> dict:
    """機能: 手計算３例と乱数固定の合成板を独立逐次器と照合する。

    引数: なし。返り値: 検査件数 (dict)。
    """
    p, raw = fixture([1], [0], [2], [1]*5, [1]*5)
    result, _ = mirror.replay_capacity(p, raw, 1, 1)
    np.testing.assert_array_equal(result, [[1, 3, 1, 110, 140, -50]])
    p, raw = fixture([1], [0], [2], [0, 0, 0, 1, 1], [1]*5)
    result, audit = mirror.replay_capacity(p, raw, 1, 1)
    assert result[0, 0] == -1 and audit['新規取消数'] == 1
    p, raw = fixture([1, 1], [0, 2], [2, 4], [1]*6, [1, 1, 0, 0, 1, 1])
    result, audit = mirror.replay_capacity(p, raw, 1, 1)
    np.testing.assert_array_equal(result[:, :3], [[1, 4, 1], [-1, -1, 0]])
    assert audit['最大実保有枚数'] == 1
    rng = np.random.default_rng(70924)
    checked = 0
    for _ in range(50):
        size = 9
        sides = rng.choice([-1, 1], size=5).tolist()
        entries = rng.integers(0, 5, size=5)
        exits = np.array([rng.integers(e+1, size) for e in entries])
        p, raw = fixture(sides, list(entries), list(exits),
                         rng.integers(0, 3, size=size).tolist(), rng.integers(0, 3, size=size).tolist())
        for cap in (1, 2, 3):
            for lag in (0, 1):
                expected = reference(p, raw, cap, lag)
                result, _ = mirror.replay_capacity(p, raw, cap, lag)
                np.testing.assert_array_equal(result, expected)
                checked += 1
    return dict(手計算数=3, 独立逐次参照器の比較数=checked)


def prefix_checks() -> int:
    """機能: 実データの仮想イベントと板を途中で打ち切り、反転約定の不変性を確認する。

    引数: なし。返り値: 実データ打切り検査数 (int)。
    """
    configs, schema, prepared, blocks = mirror.load_archive()
    wanted = ['H_P01_E1_X2_Z1', 'O02_G0_X0', 'O04_G1_X1', 'O08_G0_X0']
    count = 0
    for config in configs:
        if config['id'] not in wanted:
            continue
        ci = schema['条件'].index(config['id'])
        for cell in (4, 7):
            ready = prepared[tuple(schema['セル'][cell])]
            raw = blocks[(ci, cell)]
            cap = config.get('max_positions', 1)
            full, _ = mirror.replay_capacity(ready, raw, cap, 1)
            for fraction in (.371, .713):
                end = int((len(ready['seq'])-1)*fraction)
                keep = np.flatnonzero(raw[:, 4] <= end)
                cutraw = raw[keep].copy()
                future = cutraw[:, 5] > end
                cutraw[future, 5], cutraw[future, 13] = end, 0
                cutready = {key: (value[:end+1] if isinstance(value, np.ndarray) and len(value) == len(ready['seq']) else value)
                            for key, value in ready.items()}
                actual, _ = mirror.replay_capacity(cutready, cutraw, cap, 1)
                for k, j in enumerate(keep):
                    if full[j, 0] < 0 or full[j, 0] > end:
                        assert actual[k, 0] < 0
                        continue
                    assert actual[k, 0] == full[j, 0] and actual[k, 3] == full[j, 3]
                    if full[j, 2] == 1 and full[j, 1] <= end:
                        np.testing.assert_array_equal(actual[k], full[j])
                    else:
                        assert actual[k, 2] == 0 and actual[k, 1] == end
                        quote = ready['ask' if raw[j, 1] > 0 else 'bid'][end]
                        expected = -raw[j, 1]*(quote-actual[k, 3])-2*ready['tick']
                        assert actual[k, 4] == quote and actual[k, 5] == expected
                count += 1
    return count


def aggregate_checks() -> int:
    """機能: 別コードで作った全セルの反転会計と本集計を照合する。

    引数: なし。返り値: 検査した数値の個数 (int)。
    """
    keys = ['方式', 'セッション', '銘柄']
    independent = pd.read_csv(OUT/'監査_独立反転集計.csv').set_index(keys)
    actual = pd.read_csv(OUT/'反転_全条件セッション集計.csv').set_index(keys)
    compare = {'元確定円': '元収支円', '反転確定円': '理論反転収支円',
               '元清算評価円': '元総評価円', '反転清算評価円': '理論反転総評価円',
               '片方費用円': '元実効費用評価込み円', '元値動き円': '元mid値動き益評価込み円',
               '返済数': '元取引数', '未返済数': '元未返済数'}
    for own, produced in compare.items():
        expected = independent[own].reindex(actual.index, fill_value=0)
        np.testing.assert_allclose(actual[produced], expected, atol=1e-7)
    full = actual.reset_index().query('セッション != "2026-09-23_Night"')
    assert full['次行反転未返済数'].sum() == 0
    assert (actual['次行反転最大実保有枚数'] <= actual['設定最大枚数']).all()
    return len(actual)*len(compare)


def main() -> None:
    """機能: 独立約定参照、実板打切り、全数集計の検査結果を保存する。

    引数: なし。返り値: なし (None)。
    """
    report = manual_and_reference()
    report['実データ打切り数'] = prefix_checks()
    report['独立会計の全数照合値数'] = aggregate_checks()
    report['反転実装SHA256'] = hashlib.sha256((OUT/'mirror.py').read_bytes()).hexdigest()
    report['監査実装SHA256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['合格'] = True
    (OUT/'反転約定の独立監査.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
