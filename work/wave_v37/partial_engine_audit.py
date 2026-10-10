"""数量枠の合成反例と旧A0同値のみを検査し、新機構の実相場損益は計算しない。"""

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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'wave_v33'))
import dynamic_atr_engine_audit as helpers
sys.path.insert(0, str(HERE.parent/'wave_v34'))
import engine_scheduler as old
sys.path.insert(0, str(HERE))
import engine_partial_restore as engine
import partial_design as design

POLICIES = {p['id']: p for p in design.policies()}
PRIMARY = POLICIES[design.PRIMARY_POLICY]
OLD_FIELDS = engine.FIELDS+('prepare_events', 'entry_preparations')


def reject(*args: object, **kwargs: object) -> None:
    """機能: 外部通信を常に拒否する。

    引数: 任意値 (object)。返り値: なし (None)、必ず例外。
    """
    raise AssertionError('設計・合成監査からの通信は禁止です')


def fixture(prices: list[float], bad_rows: tuple = (), good_rows: tuple = ()) -> tuple:
    """機能: 旧合成価格に当行公開の方向と根拠行を追加する。

    引数: prices(list)、bad_rows/good_rows(tuple[int])。返り値: ready/state/configと根拠列(tuple)。
    """
    ready, state, config, _ = helpers.fixture(prices)
    bad = np.zeros(len(state), dtype=np.int8); good = bad.copy()
    bad[list(bad_rows)] = -1; good[list(good_rows)] = 1
    source = np.arange(len(state), dtype=np.int64)
    return ready, state, config, bad, source, good, source.copy()


def play(args: tuple, policy: dict = PRIMARY, **kwargs: object) -> dict:
    """機能: 合成入力を指定方針へ接続する。

    引数: args(tuple)、policy(dict)、kwargs(任意引数)。返り値: 売買結果(dict)。
    """
    return engine.run(*args, policy, **kwargs)


def identities(ready: dict, state: np.ndarray, config: dict, result: dict) -> None:
    """機能: 全会計、元組開始、枠整合、前行計画、退出期限を独立に検算する。

    引数: ready/config/result(dict)、state(ndarray)。返り値: なし(None)。
    """
    helpers.account(ready, result, config)
    shadow = result['shadow']; q0 = int(config['initial_qty'])
    slots = result['slot_curve']; curve = result['curve']; ctrl = result['control_curve']
    np.testing.assert_array_equal(((slots & 2) != 0).sum(axis=1), curve[:, 2]+curve[:, 3])
    assert not np.any(((slots & 4) != 0) & (((slots & 1) == 0) | ((slots & 2) != 0)))
    for a in result['adjustment_events']:
        if a[2] == 1:
            assert 0 <= a[5] <= a[0] and a[5] > ctrl[int(a[0]), 16]
        if a[2] == 2:
            assert 0 <= a[4] < a[0] and ready['time_s'][int(a[4])] <= ready['time_s'][int(a[0])]
    actual_open = result['orders'][result['orders'][:, 6] == 20]
    original_open = shadow['orders'][shadow['orders'][:, 6] == 20]
    np.testing.assert_array_equal(actual_open[:, [0, 1, 2, 3, 5, 6, 7]], original_open[:, [0, 1, 2, 3, 5, 6, 7]])
    end = {int(c[0]): int(c[2]) for c in shadow['cycles']}
    for row in result['cycles']:
        if int(row[0]) in end:
            assert row[2] <= end[int(row[0])]
    for row in result['slot_events']:
        assert 0 <= row[1] < row[0] and row[10] < row[0]
        assert 1 <= row[3] <= q0
    source = shadow['plans'][:-1, engine.PLAN_COLUMNS.index('plan_source_row')]
    assert np.all(~np.isfinite(source) | (source <= np.arange(len(source))))


def prefix(result: dict, other: dict, cut: int) -> None:
    """機能: 切断より前の約定・判断・枠状態を全値照合する。

    引数: result/other(dict)、cut(int)。返り値: なし(None)。
    """
    for field in ('curve', 'atr_curve', 'control_curve', 'slot_curve'):
        np.testing.assert_array_equal(result[field][:cut], other[field][:cut], err_msg=field)
    for field, col in (('trades', 7), ('orders', 0), ('cycles', 2), ('slot_events', 0),
                       ('adjustment_events', 0), ('budget_events', 0), ('prepare_events', 1), ('entry_preparations', 1)):
        np.testing.assert_array_equal(result[field][result[field][:, col] < cut], other[field][other[field][:, col] < cut], err_msg=field)


def hedge_equal(ready: dict, result: dict) -> None:
    """機能: 同約定の主玉＋反対玉と純数量操作の全行時価を別会計で比較する。

    引数: ready/result(dict)。返り値: なし(None)。
    退役時は主玉と反対玉を同価格で閉じ、実現益の見え方を利益源にしない。
    """
    n = len(ready['last']); moves = np.zeros((n, 3)); covered = {}; core = {}
    for ev in result['slot_events']:
        row, campaign, slot, event = map(int, ev[[0, 2, 3, 4]])
        d, p = ev[6:8]; key = campaign, slot
        if event == 1:
            core[key] = d; covered[key] = False
            moves[row, 0] -= d*p; moves[row, 1] += d
        elif event == 2:
            assert core.get(key) == d and not covered[key]
            covered[key] = True; moves[row, 0] += d*p; moves[row, 2] -= d
        elif event == 3:
            assert covered[key]
            covered[key] = False; moves[row, 0] -= d*p; moves[row, 2] += d
        elif event in (4, 5):
            if key in core:
                moves[row, 0] += d*p; moves[row, 1] -= d
                if covered[key]:
                    moves[row, 0] -= d*p; moves[row, 2] += d
                del core[key]; del covered[key]
    path = np.cumsum(moves, axis=0); qty = path[:, 1]+path[:, 2]
    np.testing.assert_array_equal(qty, result['curve'][:, 6])
    np.testing.assert_allclose(path[:, 0]+qty*ready['last'], result['curve'][:, 0], rtol=0, atol=1e-8)
    assert not core and not covered


def synthetic() -> list[dict]:
    """機能: 旧肯定・枠競合・次行・損失予算・左右反射等の反例を検査する。

    引数: なし。返り値: 日本語の検査記録(list[dict])。
    """
    results = []
    args = fixture([100, 101, 102, 101, 100, 101, 103, 104, 109, 106, 95], (2,), (4,))
    for policy in (POLICIES['A0'], POLICIES['CORE25'], POLICIES['CORE50'], POLICIES['SMALL25'], POLICIES['SMALL50'], PRIMARY):
        for observed in (False, True):
            actual = play(args, policy, observed_fill=observed)
            identities(*args[:3], actual)
            if policy['id'] == 'A0':
                reference = old.run(*args[:3], detail=True, observed_fill=observed)
                for name in OLD_FIELDS: np.testing.assert_array_equal(actual[name], reference[name], err_msg=name)
            results.append(dict(検査='旧基準又は数量枠・全会計・元退出期限', 方針=policy['id'], 観測約定=observed, 合格=True))
    actual = play(args)
    assert actual['orders'][actual['orders'][:, 6] == 30][0, 0] == 3
    assert actual['orders'][actual['orders'][:, 6] == 31][0, 0] == 5
    hedge_equal(args[0], actual)
    # ----------------------------------------
    stale = list(deepcopy(args)); stale[6][4] = 2
    result = play(tuple(stale))
    assert not np.any(result['orders'][:, 6] == 31)
    results.append(dict(検査='減量前の肯定保持は復元しない／同約定カバー全行時価一致', 合格=True))
    collision = fixture([100, 101, 102, 102, 108, 109, 110, 106, 95], (2,), (4, 6))
    result = play(collision); identities(*collision[:3], result); hedge_equal(collision[0], result)
    assert not np.any(result['orders'][:, 6] == 31)
    assert np.any((result['adjustment_events'][:, 2] == 3) & (result['adjustment_events'][:, 0] == 5))
    np.testing.assert_array_equal(result['curve'][5, [2, 3]], [3, 0])
    results.append(dict(検査='復元予約と元部分利確の競合では空き枠を退役し全調整取消', 合格=True))
    timer_args = list(fixture([100, 101, 102, 102, 102, 102, 102, 102, 95], (2,), ()))
    timer_args[0]['time_s'][:9] = [0, 1, 2, 3, 122, 123, 124, 125, 126]
    timer_args[6][5] = 4
    policy = next(p for p in POLICIES.values() if p['id'] == 'B06_T120_F50_N1')
    result = play(tuple(timer_args), policy, good_valid=np.ones(len(timer_args[1]), dtype=np.bool_))
    restores = result['orders'][result['orders'][:, 6] == 31]
    assert len(restores) == 1 and restores[0, 0] == 7 and restores[0, 1] == 6
    results.append(dict(検査='時計119秒の公開保持を120秒の新情報とせず124秒公開→次行復元', 合格=True))
    repeated = fixture([100, 101, 103, 100, 103, 104, 100, 99, 101, 104, 100, 98, 95], (2, 6, 10), (4, 8))
    repeat_policy = POLICIES['B06_RB06_F50_N3']
    result = play(repeated, repeat_policy); identities(*repeated[:3], result); hedge_equal(repeated[0], result)
    assert np.any(result['budget_events'][:, 2] == 1) and np.any(result['orders'][:, 6] == 32)
    assert result['cycles'][0, 3] < -result['cycles'][0, 4]
    results.append(dict(検査='反復の実現損失を固定Rへ累積し次行予算返済、ギャップ超過を記帳', 合格=True))
    delayed_budget = list(deepcopy(repeated)); delayed_budget[0]['last'][11:13] = [109, 110]
    result = play(tuple(delayed_budget), repeat_policy); identities(*delayed_budget[:3], result)
    assert result['control_curve'][11, 13] == 1
    assert np.any((result['budget_events'][:, 0] == 11) & (result['budget_events'][:, 2] == 3))
    assert np.any((result['orders'][:, 0] == 12) & (result['orders'][:, 6] == 32))
    results.append(dict(検査='元部分利確と予算予約の競合では元利確優先、予算予約を消さず次行全返済', 合格=True))
    parallel_budget = list(deepcopy(repeated)); parallel_budget[0]['last'][11] = 95
    result = play(tuple(parallel_budget), repeat_policy); identities(*parallel_budget[:3], result)
    returned = result['orders'][(result['orders'][:, 0] == 11) & (result['orders'][:, 7] == 0)]
    assert len(returned) and np.all(returned[:, 5] == 97) and np.all(returned[:, 6] == 1)
    assert result['cycles'][0, 2] == result['shadow']['cycles'][0, 2]
    results.append(dict(検査='元既設ストップと実予算成行の同時成立は元指定価格を優先し影より遅延しない', 合格=True))
    # ----------------------------------------
    for observed in (False, True):
        tied = list(deepcopy(args)); tied[0]['time_s'][:9] = 0
        result = play(tuple(tied), observed_fill=observed); identities(*tied[:3], result)
        mirrored = list(deepcopy(tied)); mirrored[0]['last'] = 400-mirrored[0]['last']
        for index in (1, 3, 5): mirrored[index] = -mirrored[index]
        other = play(tuple(mirrored), observed_fill=observed)
        expected = result['orders'].copy(); expected[:, 3] *= -1; expected[:, 5] = 400-expected[:, 5]
        np.testing.assert_array_equal(other['orders'], expected)
        np.testing.assert_allclose(other['curve'][:, 0], result['curve'][:, 0], rtol=0, atol=1e-8)
        for cut in (4, 7):
            short = [({k: (v[:cut].copy() if isinstance(v, np.ndarray) and len(v) == len(tied[1]) else v) for k, v in tied[0].items()})]
            short.extend(v[:cut].copy() if isinstance(v, np.ndarray) else deepcopy(v) for v in tied[1:])
            prefix(result, play(tuple(short), observed_fill=observed), cut)
            future = list(deepcopy(tied)); future[0]['last'][cut:] += 20; future[0]['atr'][cut:] *= 2
            for index in (1, 3, 5): future[index][cut:] *= -1
            prefix(result, play(tuple(future), observed_fill=observed), cut)
        results.append(dict(検査='同時刻群・買売反射・未来切断変更', 観測約定=observed, 合格=True))
    corrupt = engine.make_shadow(*args[:3]); changed = deepcopy(args[0]); changed['last'][2] += 1
    try:
        engine.run(changed, *args[1:], PRIMARY, shadow=corrupt)
    except ValueError:
        pass
    else:
        raise AssertionError('別入力の影キャッシュを拒否しませんでした')
    results.append(dict(検査='影キャッシュの異なる全入力SHAを拒否', 合格=True))
    missing = fixture([100, 101, 102, float('nan'), 100, 103, 109, 95], (2,), ())
    result = play(missing)
    reduction = result['orders'][result['orders'][:, 6] == 30]
    assert len(reduction) == 1 and reduction[0, 0] == 4 and reduction[0, 1] == 2
    assert not np.any(result['orders'][:, 0] == 3)
    baseline = play(missing, POLICIES['A0']); reference = old.run(*missing[:3], detail=True)
    for name in OLD_FIELDS: np.testing.assert_array_equal(baseline[name], reference[name], err_msg=name)
    results.append(dict(検査='価格欠測中は注文を約定せず次の有効行、元8配列は欠測でも同値', 合格=True))
    terminal = fixture([100, 101, 102, 102], (2,), ())
    result = play(terminal)
    assert result['cycles'][0, 2] == len(terminal[1])-1
    assert result['cycles'][0, 9] == 9 and result['stats'][9] == 0
    assert result['control_curve'][-1, 6] == 0
    results.append(dict(検査='場末判断の次行で全残玉と復元権を終了', 合格=True))
    invalid = list(deepcopy(args)); invalid[4][2] = 3
    try:
        play(tuple(invalid))
    except ValueError:
        pass
    else:
        raise AssertionError('未来根拠行を拒否しませんでした')
    invalid = list(deepcopy(args)); invalid[5] = invalid[5].astype(np.int64)
    try:
        play(tuple(invalid))
    except ValueError:
        pass
    else:
        raise AssertionError('方向列の不正型を拒否しませんでした')
    delayed = deepcopy(result); delayed['cycles'][0, 2] += 1
    try:
        identities(*terminal[:3], delayed)
    except AssertionError:
        pass
    else:
        raise AssertionError('影終了後への事後追従を拒否しませんでした')
    results.append(dict(検査='未来根拠・不正型・影終了より遅い壊れ返済を拒否', 合格=True))
    # ----------------------------------------
    # 全方針の同じ人工経路を検査する。実相場の新しい方針はここでは再生しない。
    count = 0
    for symbol in ('TOPIX', 'NK225'):
        material = list(deepcopy(repeated)); material[2] = helpers.config(symbol, material[0])
        for policy in POLICIES.values():
            for observed in (False, True):
                actual = play(tuple(material), policy, observed_fill=observed,
                              good_valid=np.ones(len(material[1]), dtype=np.bool_))
                identities(*material[:3], actual)
                if policy['kind'] in ('baseline', 'dynamic'):
                    hedge_equal(material[0], actual)
                count += 1
    assert count == 309*2*2
    results.append(dict(検査='全309管理×2枚数体系×2約定モデルの人工枠・会計・元終了以前', 比較数=count, 合格=True))
    return results


def old_identity() -> int:
    """機能: H019全26入力の旧A0を8配列厳密照合する。新方針の実相場再生は禁止。

    引数: なし。返り値: 一致入力数(int)。
    """
    with (HERE.parent/'wave_v23/inputs.pkl').open('rb') as f:
        inputs = pickle.load(f)
    states = np.load(HERE.parent/'wave_v27/directions/H019.npz')
    count = 0
    for key, ready in inputs.items():
        name = '|'.join(key); state = states[name]; config = helpers.config(key[1], ready)
        empty = np.zeros(len(state), dtype=np.int8); sources = np.full(len(state), -1, dtype=np.int64)
        actual = engine.run(ready, state, config, empty, sources, empty, sources, POLICIES['A0'])
        reference = old.run(ready, state, config, detail=True)
        for name in OLD_FIELDS: np.testing.assert_array_equal(actual[name], reference[name], err_msg=str(key)+' '+name)
        identities(ready, state, config, actual)
        count += 1
        print('旧A0同値', count, '/26', flush=True)
    return count


def main() -> None:
    """機能: 通信を止め合成・旧同値を保存し、新損益の未実行を記録する。

    引数: --synthetic-only(bool)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--synthetic-only', action='store_true'); args = parser.parse_args()
    socket.socket.connect = reject; socket.create_connection = reject; urllib.request.OpenerDirector.open = reject
    paths = [HERE.parent/'wave_v34/engine_scheduler.py', HERE.parent/'wave_v33/engine_dynamic_atr.py',
             HERE.parent/'wave_v23/inputs.pkl', HERE.parent/'wave_v27/directions/H019.npz']
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    checks = synthetic(); count = 0 if args.synthetic_only else old_identity()
    assert hashes == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    record = dict(全合格=count == 26, 合成全合格=True, 合成件数=len(checks), 合成検査=checks,
                  旧A0完全一致入力数=count, 旧8配列一致=count == 26, 新方針の実相場損益再生=False,
                  原本不変=True, API取得数=0, 保存ライブ使用=False, 原本SHA256=hashes,
                  engine_SHA256=hashlib.sha256((HERE/'engine_partial_restore.py').read_bytes()).hexdigest(),
                  shadow_engine_SHA256=hashlib.sha256((HERE/'engine_shadow_plan.py').read_bytes()).hexdigest())
    filename = 'partial_engine_synthetic.json' if args.synthetic_only else 'partial_engine_audit.json'
    (HERE/filename).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print('合成合格', len(checks), '旧同値', count, flush=True)


if __name__ == '__main__':
    main()
