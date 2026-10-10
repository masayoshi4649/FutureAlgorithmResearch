"""階層信号96条件の原本行契約と時間因果性を、売買損益なしで確認する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

import hierarchy_signals as signal

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v23'


def clipped(ready: dict, fraction: float) -> dict:
    """機能: 同じ観測時刻の末尾で原本入力を切断する。

    引数: ready (dict)、fraction (float)。返り値: 切断した入力 (dict)。
    """
    cutoff = ready['start'] + fraction * (ready['time_s'][-1] - ready['start'])
    mask = ready['time_s'] <= cutoff
    return {name: value[mask] if isinstance(value, np.ndarray) and value.ndim > 0 and len(value) == len(mask) else value
            for name, value in ready.items()}


def synthetic() -> dict:
    """機能: 準備後の別イベント発火・主方向撤回・TTL失効を合成で確認する。

    引数: なし。返り値: 検算結果 (dict)。
    """
    seq = np.arange(6, dtype=np.int64)
    times = seq.astype(float) * 10
    allowed = np.ones(6, dtype=np.int8)
    events = np.array([0, 2, 4], dtype=np.int64)
    event_time = times[events]
    event_main = np.ones(3, dtype=np.int8)
    price, ofi = np.array([-.2, .1, .1]), np.array([0., .1, .1])
    direction, setup, fired = signal._entry_filter(seq, times, allowed, events, event_time, event_main, price, ofi, 3, 1.)
    np.testing.assert_array_equal(direction, [0, 0, 1, 1, 1, 1])
    assert setup[1] == 0 and fired[1] == 1 and events[1] > setup[1]
    withdrawn = allowed.copy()
    withdrawn[1] = 0
    direction, _, fired = signal._entry_filter(seq, times, withdrawn, events, event_time, event_main, price, ofi, 3, 1.)
    assert not direction.any() and not fired.any()
    tiny_seq = np.arange(5, dtype=np.int64)
    tiny_time = np.array([0., 60., 120., 121., 200.])
    arguments = (tiny_seq, tiny_time, np.ones(5, dtype=np.int8), np.array([0], dtype=np.int64),
                 np.array([0.]), np.array([1], dtype=np.int8), np.array([.1]), np.array([.1]), 1, 1.)
    direction, _, _ = signal._entry_filter(*arguments)
    np.testing.assert_array_equal(direction, [1, 1, 1, 0, 0])
    index = np.arange(240, dtype=float)
    prices = 10000. + .3 * index + 20 * np.sin(index / 12)
    future_prices = prices.copy()
    future_prices[150:] += 1000
    reference = {'close': prices, 'high': prices + .5, 'low': prices - .5,
                 'vwap': np.cumsum(prices) / (index + 1), 'atr': np.full(240, 5.)}
    modified = {'close': future_prices, 'high': future_prices + .5, 'low': future_prices - .5,
                'vwap': np.cumsum(future_prices) / (index + 1), 'atr': np.full(240, 5.)}
    futures = 0
    for spec in signal.catalog():
        if spec['params']['entry_kind'] != 'direction' or spec['params']['peer_confirm']:
            continue
        baseline = signal._main_from_bars(reference, spec['params'])
        changed = signal._main_from_bars(modified, spec['params'])
        np.testing.assert_array_equal(baseline[:150], changed[:150])
        futures += 1
    raw = np.arange(50, dtype=np.int64)
    raw_time = raw.astype(float) * 10
    main = np.ones(50, dtype=np.int8)
    short = np.sin(raw / 2)
    for mode in (1, 2, 3):
        baseline = signal._entry_filter(raw, raw_time, main, raw, raw_time, main, short, short, mode, 1.)[0]
        changed_short, changed_main = short.copy(), main.copy()
        changed_short[25:], changed_main[25:] = 1000., -1
        changed = signal._entry_filter(raw, raw_time, changed_main, raw, raw_time, changed_main, changed_short, changed_short, mode, 1.)[0]
        np.testing.assert_array_equal(baseline[:25], changed[:25])
        futures += 1
    return {'準備と発火が別イベント': True, '板更新間の主方向撤回で旧準備破棄': True,
            'TTL120秒境界': True, '主方向12通りと短期3方式の未来値変更一致': futures}


def main() -> None:
    """機能: 全96条件のprefix・方向整合・板不使用経路を検査する。

    引数: なし。返り値: なし (None)。売買エンジンや現在APIを呼ばない。
    """
    began = time.perf_counter()
    loaded = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    loaded_features = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    sessions = sorted({key[0] for key in loaded})
    selected = {sessions[0], sessions[-1]}
    inputs = {key: value for key, value in loaded.items() if key[0] in selected}
    features = {key: loaded_features[key] for key in inputs}
    prefixes = [{key: clipped(value, fraction) for key, value in inputs.items()} for fraction in (.3, .7)]
    prefix_count, base_count, condition_count = 0, 0, 0
    hashes = set()
    for spec in signal.catalog():
        full = signal.build(spec, inputs, features)
        main_only = signal.main_directions(spec, inputs)
        hasher = hashlib.sha256()
        for key, ready in inputs.items():
            assert full[key].dtype == np.int8 and len(full[key]) == len(ready['seq'])
            assert np.all((full[key] == 0) | (full[key] == main_only[key]))
            assert not full[key][ready['time_s'] < ready['start'] + 1200].any()
            hasher.update(str(key).encode())
            hasher.update(full[key].tobytes())
        hashes.add(hasher.hexdigest())
        if spec['params']['entry_kind'] == 'direction':
            no_features = signal.build(spec, inputs, {})
            for key in inputs:
                np.testing.assert_array_equal(no_features[key], main_only[key])
                base_count += 1
        for shortened in prefixes:
            actual = signal.build(spec, shortened, features)
            for key in inputs:
                np.testing.assert_array_equal(actual[key], full[key][:len(actual[key])])
                prefix_count += 1
        condition_count += 1
    result = {'売買損益計算': False, 'API取得': False, '全条件数': condition_count,
              '対象セッション': sorted(selected), '未来末尾削除の方向一致': prefix_count,
              '短期入口なしが板特徴なしで原方向一致': base_count,
              '入口方向が主方向に逆らわない': True, '開始20分前は中立': True,
              '選択2セッション内の方向一意数': len(hashes), '合成': synthetic(),
              '実行秒': time.perf_counter() - began,
              'コードSHA256': hashlib.sha256(Path(signal.__file__).read_bytes()).hexdigest(),
              '設計SHA256': hashlib.sha256(signal.DESIGN_PATH.read_bytes()).hexdigest()}
    (HERE / 'hierarchy_interface_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
