"""選択要求と二つの入口を、売買損益を再生せず合成・未来除去で監査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import urllib.request

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / 'wave_v23'
sys.path.insert(0, str(HERE.parent / 'wave_v30'))
from context_structure_audit import read, save, digest, original_hashes, reject_network
sys.path.insert(0, str(HERE))
import selector_signals as target


def array_hash(outputs: dict) -> str:
    """機能: 全区間方向の型・キー順を固定して指紋を作る。

    引数: outputs (dict)。返り値: SHA256 (str)。
    """
    value = hashlib.sha256()
    for key in sorted(outputs):
        value.update(str(key).encode())
        value.update(outputs[key].tobytes())
    return value.hexdigest()


def equal(left: dict, right: dict) -> None:
    """機能: 区間別の同じ原本行要求又は方向を厳密照合する。

    引数: left/right (dict)。返り値: なし (None)。
    """
    assert set(left) == set(right)
    for key in left:
        np.testing.assert_array_equal(left[key], right[key])


def prefix(ready: dict, count: int) -> dict:
    """機能: 時刻・seq順を保ち入力末尾だけを物理的に削除する。

    引数: ready (dict)、count (int)。返り値: 切断入力 (dict)。
    """
    n = len(ready['seq'])
    return {k: v[:count].copy() if isinstance(v, np.ndarray) and len(v) == n else v for k, v in ready.items()}


def fixture(count: int = 9) -> tuple[dict, list[dict]]:
    """機能: 過去完了・共通R・同時刻行を検査する人工セッションを作る。

    引数: count (int)。返り値: 入力と人工影成績 (tuple[dict,list[dict]])。
    """
    inputs, rows = {}, []
    for number in range(count):
        session, start = f'合成{number:02d}', 10000. * number
        times = start + np.repeat(np.arange(0., 7321., 60.), 2)
        for symbol in target.SYMBOLS:
            ready = dict(session=session, symbol=symbol, start=start, limit=start + 7200., time_s=times,
                         seq=np.arange(len(times)), last=np.full(len(times), 100.), atr=np.full(len(times), 2.), tick=1., us_open=1e10)
            inputs[session, symbol] = ready
            risk = 2 * target.QUANTITY[symbol] * target.MULTIPLIER[symbol]
            for branch in target.BRANCHES:
                rows.append(dict(session=session, symbol=symbol, branch=branch, net_yen=risk * (branch == 'R'),
                                 completed_at=float(times[-1]), complete=True))
    return inputs, rows


def synthetic() -> dict:
    """機能: Aの確認解除・Bの厳密境界と当該区間除外・乱数時計・遅延を合成反証する。

    引数: なし。返り値: 合成検査の証跡 (dict)。新損益を計算しない。
    """
    inputs, shadow = fixture()
    requests, logs = target.build_past_requests(inputs, shadow)
    assert [r['request'] for r in logs] == [1] * 6 + [2] * 3
    assert logs[6]['training_sessions'] == [f'合成{i:02d}' for i in range(6)]
    assert all(r['session'] not in r['training_sessions'] for r in logs)
    assert logs[6]['reference_r']['合成00']['TOPIX']['risk_yen'] == 10000.
    assert logs[6]['reference_r']['合成00']['NK225']['risk_yen'] == 200.
    checked = []
    for branch in ('T', 'R'):
        changed = deepcopy(shadow)
        for row in changed:
            if row['session'] >= '合成06':
                row['net_yen'] = (1e12 if row['branch'] == branch else -1e12)
        result, detail = target.build_past_requests(inputs, changed)
        equal({k: v for k, v in requests.items() if k[0] <= '合成06'}, {k: v for k, v in result.items() if k[0] <= '合成06'})
        assert detail[:7] == logs[:7]
    checked.append('当該両市場と全未来の影損益を反転しても場初選択不変')
    equal(target.build_past_requests({k: v for k, v in inputs.items() if k[0] <= '合成06'},
          [r for r in shadow if r['session'] < '合成06'])[0], {k: v for k, v in requests.items() if k[0] <= '合成06'})
    checked.append('当該以降の影口座を物理削除しても同じ場初選択')
    for amount, expected in ((.25, 1), (.250001, 2)):
        changed = deepcopy(shadow)
        for row in changed:
            risk = 2 * target.QUANTITY[row['symbol']] * target.MULTIPLIER[row['symbol']]
            row['net_yen'] = risk * amount if row['branch'] == 'R' else 0.
        assert target.build_past_requests(inputs, changed)[1][6]['request'] == expected
    checked.append('gap=.25同点は維持、.250001だけ切替')
    missing = deepcopy(shadow)
    missing[0]['complete'] = False
    assert target.build_past_requests(inputs, missing)[1][6]['request'] == 1
    no_atr = deepcopy(inputs)
    no_atr['合成00', 'TOPIX']['atr'][:] = np.nan
    incomplete = target.build_past_requests(no_atr, shadow)[1][6]
    assert incomplete['request'] == 1 and '合成00' not in incomplete['training_sessions']
    late = deepcopy(inputs)
    ready = late['合成00', 'TOPIX']
    ready['atr'][ready['time_s'] == ready['start'] + 1200] = np.nan
    assert target.reference_r(late, '合成00')['TOPIX']['timestamp'] == 1260.
    checked.append('片側ATR欠損又は片枝未完了で区間全体を学習外、最初の有効ATRだけ採用')
    clip = deepcopy(shadow)
    for row in clip:
        row['net_yen'] = 1e9 if row['branch'] == 'R' and row['symbol'] == 'TOPIX' else (-1e9 if row['branch'] == 'R' else 0.)
    detail = target.build_past_requests(inputs, clip)[1][6]
    assert detail['symbol_means']['R'] == {'TOPIX': 3., 'NK225': -3.} and detail['scores']['R'] == -3. and detail['request'] == 1
    checked.append('学習だけ±3へ制限し両市場の低い平均を採る')
    try:
        target.build_past_requests(inputs, shadow + shadow[:1])
    except AssertionError:
        checked.append('影口座の重複を拒否')
    else:
        raise AssertionError('重複が拒否されない')
    # ----------------------------------------
    stamps = np.arange(1, 11, dtype=float) * 1800.
    models = {}
    for symbol in target.SYMBOLS:
        er = np.array([.1, .1, .1, .2, .3 if symbol == 'NK225' else .9, .35, .8, np.nan, .1, .1])
        feet = stamps - 180.
        feet[1] = feet[0]
        models['A合成', symbol] = dict(published=stamps, foot_time=feet, er=er)
    events = target._state_events('A合成', 0., 20000., 18000., models)
    assert [e['request'] for e in events] == [1, 1, 1, 1, 2, 2, 2, 1, 1, 1, 2]
    assert events[2]['streak'] == events[5]['streak'] == events[8]['streak'] == 0
    checked.append('Aは古い同じ足・中間不一致・欠測で連続確認だけ解除、閾値境界と2回同意が一致')
    counts = 0
    partial = {k: prefix(v, len(v['seq']) // 2) for k, v in inputs.items()}
    for mode in ('A', 'B'):
        for seed in range(64):
            full, _ = target.random_requests(inputs, mode, seed)
            # Bは過去完了時刻を残し、現在区間の末尾だけ短くする。
            short_inputs = {k: (partial[k] if k[0] == '合成08' else v) for k, v in inputs.items()}
            short, _ = target.random_requests(short_inputs, mode, seed)
            for key in short:
                np.testing.assert_array_equal(full[key][:len(short[key])], short[key])
            for session in sorted({k[0] for k in inputs}):
                np.testing.assert_array_equal(full[session, 'TOPIX'], full[session, 'NK225'])
            counts += 1
    checked.append('乱数A/B全64seedは両市場同期・末尾延長不変')
    ready = inputs['合成00', 'TOPIX']
    key = ('合成00', 'TOPIX')
    for initial, values in ((0, np.resize(np.array([1, -1, 0], np.int8), len(ready['seq']))),
                            (1, np.resize(np.array([1, 2, 1], np.int8), len(ready['seq'])))):
        for delay in (0., 1., 5., 15.):
            actual = target.delay_columns({key: ready}, {key: values}, delay, initial)[key]
            expected = []
            for i, stamp in enumerate(ready['time_s']):
                prior = [j for j in range(i + 1) if ready['time_s'][j] <= stamp - delay]
                expected.append(values[i] if delay == 0 else (values[prior[-1]] if prior else initial))
            np.testing.assert_array_equal(actual, expected)
    checked.append('1/5/15秒遅延は現在行以前、0秒同時刻identity、入口0/要求1で開始')
    return dict(全合成合格=True, 検査=checked, 乱数合成数=counts)


def synthetic_candles() -> dict:
    """機能: 原本を触らず合成確定足でERの最初の切替時刻と売買反射を検査する。

    引数: なし。返り値: 窓別の最初のR時刻 (dict)。
    """
    directory = HERE / 'audit_candles' / 'synthetic'
    inputs, _ = fixture(1)
    for symbol in target.SYMBOLS:
        path = directory / 'candle_1min' / symbol / '合成00.csv'
        path.parent.mkdir(parents=True, exist_ok=True)
        close = 100. + np.arange(124) % 2
        frame = pd.DataFrame(dict(time=pd.to_datetime(np.arange(124) * 60, unit='s', utc=True).astype(str),
                                  open=close, high=close + 1, low=close - 1, close=close, volume=1., closed=True))
        frame.to_csv(path, index=False)
    output = {}
    try:
        target.set_root(directory)
        for window, earliest in ((24, 3600.), (30, 5400.), (36, 5400.)):
            arrays, logs = target.build_state_requests(inputs, window)
            stamp = next(e['timestamp'] for e in logs if e['request'] == 2)
            assert stamp == earliest
            output[str(window)] = stamp / 60.
        for symbol in target.SYMBOLS:
            path = directory / 'candle_1min' / symbol / '合成00.csv'
            frame = pd.read_csv(path)
            frame['close'] = 300. - frame['close']
            frame.to_csv(path, index=False)
        target.clear_cache()
        reflected, mirror_logs = target.build_state_requests(inputs, 36)
        equal(arrays, reflected)
        assert logs == mirror_logs
    finally:
        target.set_root(ROOT)
    return dict(最早R要求までの分=output, 合成確定足の上下反射で選択不変=True)


def original_checks(inputs: dict, features: dict) -> tuple[dict, dict]:
    """機能: T/R元仕様を再生成し、旧T・P02数量非依存と全要求のprefixを確認する。

    引数: inputs/features (dict)。返り値: 入口列と監査記録 (tuple[dict,dict])。
    """
    target.initialize(inputs, features)
    entries = target.build_entries()
    with np.load(HERE.parent / 'wave_v27/directions/H019.npz') as old:
        for key, value in entries['T'].items():
            np.testing.assert_array_equal(value, old['|'.join(key)])
    states = {window: target.build_state_requests(inputs, window) for window in (24, 30, 36)}
    prefix_count = entries_count = 0
    for session in sorted({k[0] for k in inputs}):
        pair = {k: r for k, r in inputs.items() if k[0] == session}
        start = min(r['start'] for r in pair.values())
        finish = min(r['time_s'][-1] for r in pair.values())
        for fraction in (.37, .73):
            cutoff = start + (finish - start) * fraction
            cropped = {k: prefix(r, int(np.searchsorted(r['time_s'], cutoff, side='right'))) for k, r in pair.items()}
            target.clear_cache()
            for window in (24, 30, 36):
                short, logs = target.build_state_requests(cropped, window)
                for key in short:
                    np.testing.assert_array_equal(short[key], states[window][0][key][:len(short[key])])
                expected_logs = [r for r in states[window][1] if r['session'] == session and r['timestamp'] <= cutoff]
                assert logs == expected_logs
                prefix_count += len(short)
            # 全13区間でT/R再生成も物理切断と一致する。
            short_entries = target.build_entries(cropped, features)
            for branch in target.BRANCHES:
                for key in cropped:
                    np.testing.assert_array_equal(short_entries[branch][key], entries[branch][key][:len(cropped[key]['seq'])])
                    entries_count += 1
        print(session, 'T/RとA24/30/36の2切断が一致', flush=True)
    return entries, dict(T旧H019全26方向一致=True, 選択3窓prefix区間数=prefix_count, T_R方向prefix区間数=entries_count,
                         入口配列SHA256={branch: array_hash(columns) for branch, columns in entries.items()},
                         要求3窓SHA256={str(window): array_hash(item[0]) for window, item in states.items()})


def main() -> None:
    """機能: 実験損益の前に選択器の時計と情報境界を監査し証跡を保存する。

    引数: なし。返り値: なし (None)。API・現在データ・売買再生なし。
    """
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    urllib.request.OpenerDirector.open = reject_network
    originals = original_hashes()
    code_before = digest(HERE / 'selector_signals.py')
    tests, candle_tests = synthetic(), synthetic_candles()
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    features = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    entries, audited = original_checks(inputs, features)
    assert originals == original_hashes()
    assert code_before == digest(HERE / 'selector_signals.py')
    result = dict(構造監査合格=True, 合成=tests, 合成足=candle_tests, **audited,
                  入口来歴={'T': 'wave_v27 H019 再生成・旧NPZ全26一致',
                            'R': 'wave_v25 d016_price_control.build mode=P02 veto_mode=price。旧OFI撤回版は不使用。'},
                  参照SHA256={path.relative_to(ROOT).as_posix(): digest(path) for path in
                      [HERE / 'selector_signals.py', Path(__file__), HERE.parent / 'wave_v27/hierarchy_signals.py',
                       HERE.parent / 'wave_v27/hierarchy_design_fixed.json', HERE.parent / 'wave_v27/directions/H019.npz',
                       HERE.parent / 'wave_v25/d016_price_control.py', HERE.parent / 'wave_v25/d016_price_control_fixed.json',
                       HERE.parent / 'wave_v25/discovery_signals.py', OLD / 'signals.py', OLD / 'inputs.pkl', OLD / 'features_depth.pkl']},
                  原本78SHA256=originals, 新PnL参照=False, 売買再生実行=False, API取得数=0, 現在データ使用=False)
    save(HERE / 'selector_signal_audit.json', result)
    save(HERE / 'selector_causality_before_pnl.json', result)
    np.savez_compressed(HERE / 'audited_entries.npz', **{f'{branch}|{key[0]}|{key[1]}': value
        for branch, columns in entries.items() for key, value in columns.items()})
    print('T/Rと選択器の損益前監査合格。新損益未読。', flush=True)


if __name__ == '__main__':
    main()
