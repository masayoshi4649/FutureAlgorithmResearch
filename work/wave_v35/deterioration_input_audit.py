"""入口時計3種と悪化12根拠を事前生成し、公開順・未来不変・符号対称を検査する。"""

from __future__ import annotations

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
V33 = HERE.parent / 'wave_v33'
sys.dont_write_bytecode = True
sys.path.insert(0, str(V33))
import input_audit as inherited
sys.path.insert(0, str(HERE))
import deterioration_signals as signals
import conditional_inputs as loader


def save(path: Path, value: dict) -> None:
    """機能: 今回作業領域へUTF-8の監査JSONを保存する。

    引数: path (Path)、value (dict)。返り値: なし (None)。
    """
    assert path.resolve().is_relative_to(HERE.resolve())
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def clipped(ready: dict, count: int) -> dict:
    """機能: 原本配列を指定行で切り、将来の行を渡さない入力を作る。

    引数: ready (dict)、count (int)。返り値: 切断入力 (dict)。
    """
    n = len(ready['last'])
    return {k: v[:count] if isinstance(v, np.ndarray) and len(v) == n else v for k, v in ready.items()}


def entry_specs() -> list[tuple[str, float, dict]]:
    """機能: 旧12入口から既存の時計近傍定義だけで0.8/1/1.2を作る。

    引数: なし。返り値: 元ID・倍率・旧builder互換仕様 (list[tuple])。
    """
    original = {s['id']: s for s in inherited.SIGNALS.catalog()}
    output = []
    for identifier in inherited.IDS:
        base = original[identifier]
        neighbors = [s for s in inherited.SIGNALS.neighbor_specs(base) if s['diagnostic_category'] == 'clock']
        assert len(neighbors) == 2 and all(s['applied'] for s in neighbors)
        for factor in (.8, 1., 1.2):
            selected = base if factor == 1. else next(s for s in neighbors if s['params']['clock_multiplier'] == base['params']['clock_multiplier'] * factor)
            output.append((identifier, factor, selected))
    return output


def reflected(inputs: dict, features: dict) -> tuple[dict, dict]:
    """機能: 価格を上下反転し買売数量を交換した公開入力を作る。

    引数: inputs/features (dict)。返り値: 反射した原本と板特徴 (tuple[dict,dict])。
    """
    ready_out, frame_out = {}, {}
    for key, ready in inputs.items():
        offset = 2 * np.ceil(np.max(ready['last']) / ready['tick']) * ready['tick']
        ready_out[key] = dict(ready, last=offset - ready['last'])
        frame = features[key].copy()
        frame['source_mid_last'] = offset - frame.source_mid_last
        for a, b in (('trade_pos', 'trade_neg'), ('refill_bid', 'refill_ask')):
            left, right = frame[a].copy(), frame[b].copy()
            frame[a], frame[b] = right, left
        for column in ('ofi_signed', 'dflow_near'):
            frame[column] = -frame[column]
        frame_out[key] = frame
    return ready_out, frame_out


def assert_prefix(expected: dict, changed: dict, count: int) -> None:
    """機能: 原本方向・解放行・証拠イベントが未来削除や変更で変わらないか検査する。

    引数: expected/changed (dict)、count (int)。返り値: なし (None)。
    """
    for name in ('direction', 'source_row', 'source_event_index'):
        np.testing.assert_array_equal(expected[name][:count], changed[name][:count], err_msg=name)
    a = expected['events'].loc[expected['events'].release_row < count].reset_index(drop=True)
    b = changed['events'].loc[changed['events'].release_row < count].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_exact=True)


def evidence_checks(ready: dict, result: dict, other_ready: dict | None, params: dict) -> None:
    """機能: 全非中立根拠の自解放・過去窓・peer追加待ちを原本行へ照合する。

    引数: ready/result/params (dict)、other_ready (dict|None)。返り値: なし (None)。
    """
    e = result['events']
    rows = e.release_row.to_numpy(np.int64)
    assert np.array_equal(ready['seq'][rows], e.release_seq.to_numpy())
    assert np.array_equal(ready['time_s'][rows], e.release_time_s.to_numpy())
    assert (e.source_last_seq < e.release_seq).all() and (e.source_time_s < e.release_time_s).all()
    assert np.isin(result['direction'], (-1, 0, 1)).all()
    assert np.all(result['source_row'] <= np.arange(len(result['direction'])))
    active = e.direction != 0
    assert e.loc[active, 'valid'].all()
    for ref in ('long_ref', 'short_ref', 'stage_ref'):
        present = e[ref + '_event'] >= 0
        assert (e.loc[present, ref + '_row'] < e.loc[present, 'release_row']).all()
        assert (e.loc[present, ref + '_time_s'] < e.loc[present, 'release_time_s']).all()
    peer = e.peer_event >= 0
    if peer.any():
        assert other_ready is not None
        pr = e.loc[peer, 'peer_release_row'].to_numpy(np.int64)
        np.testing.assert_array_equal(other_ready['seq'][pr], e.loc[peer, 'peer_release_seq'].to_numpy())
        np.testing.assert_array_equal(other_ready['time_s'][pr], e.loc[peer, 'peer_release_time_s'].to_numpy())
        assert (e.loc[peer, 'peer_available_time_s'] <= e.loc[peer, 'release_time_s']).all()
        assert (e.loc[peer, 'release_time_s'] - e.loc[peer, 'peer_available_time_s'] <= params['freshness_seconds']).all()
    source = result['source_row']
    nonzero = result['direction'] != 0
    assert np.all(source[nonzero] >= 0)
    assert np.all(ready['time_s'][nonzero] - ready['time_s'][source[nonzero]] <= params['freshness_seconds'])


def synthetic() -> dict:
    """機能: 人工板で全12機序、欠測、反射、乱数の時刻共通性とprefix安定性を確認する。

    引数: なし。返り値: 合成検査結果 (dict)。売買は再生しない。
    """
    n = 2702
    inputs, features = {}, {}
    for symbol in ('NK225', 'TOPIX'):
        times = 10000. + np.arange(n)
        mid = 1000. - np.maximum(np.arange(n) - 900, 0) * .1
        signed = np.where(np.arange(1, n) < 1600, 1., -1.)
        ready = dict(time_s=times, seq=np.arange(n, dtype=np.int64), last=mid,
                     atr=np.full(n, 10.), tick=1., start=10000., limit=times[-1], session='合成Day', symbol=symbol)
        frame = pd.DataFrame(dict(time_s=times[1:], seq=np.arange(1, n), source_time_s=times[:-1],
            source_first_seq=np.arange(n - 1), source_last_seq=np.arange(n - 1), source_mid_last=mid[:-1],
            valid_event_count=np.ones(n - 1), ofi_signed=signed, ofi_abs=np.ones(n - 1), dflow_near=signed * .3,
            trade_pos=np.where(signed > 0, 5., 1.), trade_neg=np.where(signed > 0, 1., 5.),
            refill_bid=np.ones(n - 1), refill_ask=np.full(n - 1, 5.)))
        inputs['合成Day', symbol], features['合成Day', symbol] = ready, frame
    mirrored_inputs, mirrored_features = reflected(inputs, features)
    active = {}
    for spec in signals.catalog():
        signals.clear_cache(); result = signals.build(spec, inputs, features)
        signals.clear_cache(); mirror = signals.build(spec, mirrored_inputs, mirrored_features)
        active[spec['id']] = sum(int(np.count_nonzero(r['direction'])) for r in result.values())
        assert active[spec['id']] > 0, ('合成で未発火の機序', spec['id'])
        for key in inputs:
            np.testing.assert_array_equal(result[key]['direction'], -mirror[key]['direction'])
            np.testing.assert_array_equal(result[key]['source_row'], mirror[key]['source_row'])
    ready = inputs['合成Day', 'TOPIX']
    source = np.resize(np.array([0, 1, -1], np.int8), n)
    for seed in (0, 1, 63):
        a = loader.randomize_direction(source, ready, seed)
        for count in (123, 1800, 2300):
            b = loader.randomize_direction(source[:count], clipped(ready, count), seed)
            np.testing.assert_array_equal(a[:count], b)
        other = loader.randomize_direction(source, inputs['合成Day', 'NK225'], seed)
        np.testing.assert_array_equal(a, other)
        assert np.array_equal(a == 0, source == 0)
    # 同じ時刻の後続原本行は、seqが公開行より前なら根拠を受け取れない。
    ready = dict(inputs['合成Day', 'TOPIX'])
    target = 1001
    ready['time_s'] = ready['time_s'].copy(); ready['time_s'][target - 1] = ready['time_s'][target]
    # 同時刻性の原本対応は既存入力遅延の合成監査も継承し、ここではseq探索を直接照合する。
    sequence = np.array([10, 20, 30])
    target_sequence = np.array([9, 10, 11, 19, 20, 29, 30])
    np.testing.assert_array_equal(np.searchsorted(sequence, target_sequence, side='right') - 1, [-1, 0, 0, 0, 1, 1, 2])
    missing = {k: f.loc[~f.time_s.between(11000., 11100.)].copy() for k, f in features.items()}
    signals.clear_cache(); lost = signals.build(signals.catalog()[0], inputs, missing)
    for key, value in lost.items():
        mask = (inputs[key]['time_s'] >= 11060) & (inputs[key]['time_s'] < 11100)
        assert not value['direction'][mask].any()
    return dict(全機序合成発火=True, 人工発火数=active, 上下反射=True, 欠測は不発=True,
                原本同時刻はseq順=True, 乱数prefix安定=True, 乱数両市場同一=True, 乱数ゼロ位置維持=True)


def main() -> None:
    """機能: 新損益を読まず入口36列・根拠12列と証拠を生成し、全入力の因果性を監査する。

    引数: なし。返り値: なし (None)。原本・旧版は変更しない。
    """
    socket.socket.connect = inherited.reject_network
    socket.create_connection = inherited.reject_network
    urllib.request.OpenerDirector.open = inherited.reject_network
    signals.freeze()
    prior = inherited.read(V33 / 'input_causality_before_pnl.json')
    originals = prior['原本78SHA256']
    refs = dict(prior['参照SHA256'])
    for path in (Path(__file__), HERE / 'deterioration_signals.py', HERE / 'conditional_inputs.py',
                 HERE / 'deterioration_design_fixed.json', V33 / 'input_causality_before_pnl.json'):
        refs[path.relative_to(ROOT).as_posix()] = inherited.digest(path)
    assert refs == {name: inherited.digest(ROOT / name) for name in refs}
    assert len(originals) == 78 and originals == {name: inherited.digest(ROOT / name) for name in originals}
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    features = pickle.loads((HERE.parent / 'wave_v23/features_depth.pkl').read_bytes())
    base = inherited.load_entries(inputs)
    tests = synthetic()
    for folder in ('entries', 'deterioration', 'evidence'):
        (HERE / folder).mkdir(exist_ok=True)
    full_entries = {}
    entry_rows = []
    for identifier, scale, spec in entry_specs():
        inherited.SIGNALS.clear_cache()
        directions = inherited.SIGNALS.build(spec, inputs, features)
        label = f'{identifier}__C{round(scale * 100):03d}'
        full_entries[identifier, scale] = directions
        for key, values in directions.items():
            assert values.dtype == np.int8 and len(values) == len(inputs[key]['last'])
            if scale == 1.:
                np.testing.assert_array_equal(values, base[identifier][key])
            entry_rows.append(dict(id=identifier, clock_scale=scale, session=key[0], symbol=key[1], 原本行数=len(values), 基準旧列一致=scale == 1.))
        np.savez_compressed(HERE / 'entries' / (label + '.npz'), **{'|'.join(k): v for k, v in directions.items()})
    print('旧12入口×時計3種=36列を再生成。基準12は旧版と同一。', flush=True)
    full, records = {}, []
    signals.clear_cache()
    for spec in signals.catalog():
        result = signals.build(spec, inputs, features)
        full[spec['id']] = result
        arrays, evidence = {}, {}
        for key, ready in inputs.items():
            item, name = result[key], '|'.join(key)
            other = key[0], 'TOPIX' if key[1] == 'NK225' else 'NK225'
            evidence_checks(ready, item, inputs.get(other), spec['params'])
            arrays.update({'direction::' + name: item['direction'], 'source_row::' + name: item['source_row'],
                           'event_index::' + name: item['source_event_index']})
            for column in item['events']:
                evidence[name + '::' + column] = item['events'][column].to_numpy()
            records.append(dict(id=spec['id'], session=key[0], symbol=key[1], 原本行数=len(item['direction']),
                                証拠イベント数=len(item['events']), 非中立行数=int(np.count_nonzero(item['direction'])), 公開順確認=True))
        np.savez_compressed(HERE / 'deterioration' / (spec['id'] + '.npz'), **arrays)
        np.savez_compressed(HERE / 'evidence' / (spec['id'] + '.npz'), **evidence)
    print('悪化12列と全公開証拠を生成。損益は未計算。', flush=True)
    # ----------------------------------------
    # 各入力の原本行で切断し、相手は対象時刻まで残す。相手の追加60秒待ち後の未来も改変する。
    counters = dict(入口prefix比較数=0, 入口未来改変比較数=0, 悪化prefix比較数=0, 悪化未来改変比較数=0, 悪化反射比較数=0)
    for key, ready in inputs.items():
        peer_key = key[0], 'TOPIX' if key[1] == 'NK225' else 'NK225'
        for fraction in (.37, .73):
            count = max(2, int(len(ready['last']) * fraction))
            timestamp = ready['time_s'][count - 1]
            pair = {key: ready, peer_key: inputs[peer_key]}
            small = {key: clipped(ready, count), peer_key: clipped(inputs[peer_key], int(np.searchsorted(inputs[peer_key]['time_s'], timestamp, side='right')))}
            if not len(small[peer_key]['last']):
                small.pop(peer_key)
            changed, changed_features = {}, {}
            for member, data in pair.items():
                cutoff = timestamp if member == key else timestamp - 60.
                mask = data['time_s'] > cutoff
                altered = dict(data, last=data['last'].copy(), atr=data['atr'].copy())
                altered['last'][mask] += 10000 * data['tick']; altered['atr'][mask] = 50000.
                changed[member] = altered
                frame = features[member].copy()
                future = frame.seq > ready['seq'][count - 1] if member == key else frame.time_s + 60 > timestamp
                frame.loc[future, 'source_mid_last'] += 10000 * data['tick']
                for column in ('ofi_signed', 'dflow_near'):
                    frame.loc[future, column] *= -1
                for a, b in (('trade_pos', 'trade_neg'), ('refill_bid', 'refill_ask')):
                    left = frame.loc[future, a].copy()
                    frame.loc[future, a] = frame.loc[future, b].to_numpy(); frame.loc[future, b] = left.to_numpy()
                changed_features[member] = frame
            for identifier, scale, spec in entry_specs():
                inherited.SIGNALS.clear_cache()
                shortened = inherited.SIGNALS.build(spec, small, features)[key]
                np.testing.assert_array_equal(full_entries[identifier, scale][key][:count], shortened)
                inherited.SIGNALS.clear_cache()
                future = inherited.SIGNALS.build(spec, changed, changed_features)[key]
                np.testing.assert_array_equal(full_entries[identifier, scale][key][:count], future[:count])
                counters['入口prefix比較数'] += 1; counters['入口未来改変比較数'] += 1
            for spec in signals.catalog():
                signals.clear_cache(); shortened = signals.build(spec, small, features)[key]
                assert_prefix(full[spec['id']][key], shortened, count)
                signals.clear_cache(); future = signals.build(spec, changed, changed_features)[key]
                assert_prefix(full[spec['id']][key], future, count)
                counters['悪化prefix比較数'] += 1; counters['悪化未来改変比較数'] += 1
    mirror_inputs, mirror_features = reflected(inputs, features)
    signals.clear_cache()
    for spec in signals.catalog():
        mirrored = signals.build(spec, mirror_inputs, mirror_features)
        for key in inputs:
            np.testing.assert_array_equal(full[spec['id']][key]['direction'], -mirrored[key]['direction'])
            np.testing.assert_array_equal(full[spec['id']][key]['source_row'], mirrored[key]['source_row'])
            counters['悪化反射比較数'] += 1
    assert counters == dict(入口prefix比較数=1872, 入口未来改変比較数=1872, 悪化prefix比較数=624, 悪化未来改変比較数=624, 悪化反射比較数=312)
    # ----------------------------------------
    # 生成ファイルを実際のrunner用APIから再読し、訓練/評価の部分集合にも対応を確認する。
    for sessions in (sorted({k[0] for k in inputs})[:6], sorted({k[0] for k in inputs})[6:]):
        subset = {k: v for k, v in inputs.items() if k[0] in sessions}
        loader.initialize(subset)
        for identifier, scale, _ in entry_specs():
            for key in subset:
                np.testing.assert_array_equal(loader.entry(identifier, scale, key), full_entries[identifier, scale][key])
        for spec in signals.catalog():
            for key in subset:
                direction, source = loader.deterioration(spec['id'], key)
                np.testing.assert_array_equal(direction, full[spec['id']][key]['direction'])
                np.testing.assert_array_equal(source, full[spec['id']][key]['source_row'])
                random, random_source = loader.deterioration(spec['id'], key, 0)
                assert np.array_equal(random == 0, direction == 0)
                np.testing.assert_array_equal(source, random_source)
                for fraction in (.37, .73):
                    count = max(2, int(len(direction) * fraction))
                    np.testing.assert_array_equal(random[:count], loader.randomize_direction(direction[:count], clipped(subset[key], count), 0))
    artifacts = sorted([*HERE.glob('entries/*.npz'), *HERE.glob('deterioration/*.npz'), *HERE.glob('evidence/*.npz')])
    assert len(artifacts) == 60
    manifest = dict(入口配列数=36, 悪化配列数=12, 証拠表数=12, 新損益読取=False,
                    SHA256={p.relative_to(ROOT).as_posix(): inherited.digest(p) for p in artifacts})
    save(HERE / 'input_artifacts.json', manifest)
    assert refs == {name: inherited.digest(ROOT / name) for name in refs}
    assert originals == {name: inherited.digest(ROOT / name) for name in originals}
    sessions = sorted({k[0] for k in inputs})
    result = dict(構造監査合格=True, 全監査完了=True, 新損益読取=False, 売買再生=False, API取得数=0, 現在保存物使用=False,
        全セッション=sessions, 訓練6セッション=sessions[:6], 評価7セッション=sessions[6:], 対象入口ID=inherited.IDS,
        入口=dict(配列数=36, 全区間数=936, rows=entry_rows), 悪化=dict(配列数=12, 全区間数=312, rows=records),
        合成=tests, **counters, 参照SHA256=refs, 原本78SHA256=originals, artifacts=manifest,
        注意='既知13区間。悪化窓そのものの感度は今回未検査。原本時刻はCurrentPriceTime代理。活動数を根拠に条件変更しない。')
    save(HERE / 'input_causality_before_pnl.json', result)
    files = dict(refs, **originals, **manifest['SHA256'])
    for path in (HERE / 'input_artifacts.json', HERE / 'input_causality_before_pnl.json'):
        files[path.relative_to(ROOT).as_posix()] = inherited.digest(path)
    save(HERE / 'conditional_input_fixed.json', dict(SHA256=files, 入口配列数=36, 悪化配列数=12, 全構造監査合格=True, 新損益読取=False))
    (HERE / 'input_audit.md').write_text('# 条件付き追跡の入力監査\n\n入口36配列（同12入口×時計0.8/1/1.2）、悪化12配列、証拠12表を固定した。基準入口は旧版と一致。全26入力で2切断点の未来削除・自市場未来値変更・60秒待ちで未公開の相手情報変更が過去列に影響しないことを確認した。\n\n悪化12×26は上下反射に対称。原本同時刻はseq順で解放し、peerは解放+60秒。根拠不足を0にし、0を悪化と解釈しない。乱数対照は非0時間帯と公開元を保持するが、保有に逆らう回数や実短縮回数まで揃えるものではない。\n\n損益・売買再生・現在保存物・APIは使用していない。原本78と旧定義は前後SHA一致。\n', encoding='utf-8')
    print(dict(構造監査合格=True, 入口区間数=936, 悪化区間数=312, **counters), flush=True)


if __name__ == '__main__':
    main()
