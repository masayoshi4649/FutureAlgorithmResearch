"""再利用済み証跡と新しい窓・公開イベント乱数だけを検査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import pickle
import socket

import numpy as np
import pandas as pd

import prepare_partial_inputs as prepare
import partial_inputs as adapter

HERE, ROOT, source = prepare.HERE, prepare.ROOT, prepare.source


def clipped(ready: dict, n: int) -> dict:
    """機能: 原本配列を先頭から切断する。

    引数: ready (dict)、n (int)。返り値: 切断した辞書 (dict)。
    """
    return {name: value[:n].copy() if isinstance(value, np.ndarray) and value.ndim
        and len(value) == len(ready['seq']) else value for name, value in ready.items()}


def cuts(ready: dict) -> list[int]:
    """機能: 37%と、73%近傍の同時刻群途中を監査境界にする。

    引数: ready (dict)。返り値: 排他的行上限2つ (list[int])。
    """
    n = len(ready['seq'])
    duplicate = np.flatnonzero(np.diff(ready['time_s']) == 0)
    assert len(duplicate), '同時刻群を持つ固定入力を使用する'
    second = int(duplicate[np.argmin(abs(duplicate - int(n*.73)))]) + 1
    assert ready['time_s'][second-1] == ready['time_s'][second]
    return [max(2, int(n*.37)), second]


def valid_column(result: dict) -> np.ndarray:
    """機能: 公開鮮度と自市場窓品質からtimer用有効性を独立に展開する。

    引数: result (dict)。返り値: 有効性 (ndarray[bool])。
    """
    indices = result['source_event_index']
    output = np.zeros(len(indices), bool)
    present = indices >= 0
    output[present] = result['events']['valid'].to_numpy(bool)[indices[present]]
    return output


def same_prefix(expected: dict, actual: dict, n: int) -> None:
    """機能: 方向・公開元行・イベント・timer品質と過去証拠全列を厳密比較する。

    引数: expected/actual (dict)、n (int)。返り値: なし (None)。
    """
    for name in ('direction', 'source_row', 'source_event_index'):
        np.testing.assert_array_equal(expected[name][:n], actual[name][:n], err_msg=name)
    np.testing.assert_array_equal(valid_column(expected)[:n], valid_column(actual)[:n])
    a = expected['events'].loc[expected['events'].release_row < n].reset_index(drop=True)
    b = actual['events'].loc[actual['events'].release_row < n].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_exact=True)


def evidence(ready: dict, result: dict, peer: dict) -> None:
    """機能: ready配列行とrawseqの違い、公開前素材、peer60秒待ちを検算する。

    引数: ready/result/peer (dict)。返り値: なし (None)。
    """
    events = result['events']
    row = events.release_row.to_numpy(np.int64)
    np.testing.assert_array_equal(ready['seq'][row], events.release_seq.to_numpy())
    np.testing.assert_array_equal(ready['time_s'][row], events.release_time_s.to_numpy())
    assert (events.source_last_seq < events.release_seq).all() and (events.source_time_s < events.release_time_s).all()
    source_row, index = result['source_row'], result['source_event_index']
    present = index >= 0
    assert np.array_equal(source_row[present], row[index[present]])
    assert (source_row <= np.arange(len(source_row))).all()
    assert (ready['time_s'][present] - ready['time_s'][source_row[present]] <= 60.).all()
    assert valid_column(result)[result['direction'] != 0].all()
    for ref in ('long_ref', 'short_ref', 'stage_ref'):
        exists = events[ref+'_event'] >= 0
        assert (events.loc[exists, ref+'_row'] < events.loc[exists, 'release_row']).all()
    exists = events.peer_event >= 0
    rows = events.loc[exists, 'peer_release_row'].to_numpy(np.int64)
    np.testing.assert_array_equal(peer['seq'][rows], events.loc[exists, 'peer_release_seq'].to_numpy())
    np.testing.assert_array_equal(peer['time_s'][rows]+60., events.loc[exists, 'peer_available_time_s'].to_numpy())
    assert (events.loc[exists, 'peer_available_time_s'] <= events.loc[exists, 'release_time_s']).all()
    assert (events.loc[exists, 'release_time_s']-events.loc[exists, 'peer_available_time_s'] <= 60.).all()


def future_pair(inputs: dict, features: dict, key: tuple, n: int) -> tuple:
    """機能: 自市場の切断後と、+60秒待ちで未公開の相手情報だけを反証用に変更する。

    引数: inputs/features (dict)、key (tuple)、n (int)。返り値: 改変した2組 (tuple)。
    """
    peer = key[0], 'TOPIX' if key[1] == 'NK225' else 'NK225'
    stamp = inputs[key]['time_s'][n-1]
    rr, ff = {}, {}
    for member in (key, peer):
        ready = inputs[member]
        raw_mask = np.arange(len(ready['seq'])) >= n if member == key else ready['time_s']+60. > stamp
        rr[member] = dict(ready, last=ready['last'].copy(), atr=ready['atr'].copy())
        rr[member]['last'][raw_mask] += 10000*ready['tick']; rr[member]['atr'][raw_mask] = 50000.
        frame = features[member].copy(deep=True)
        mask = frame.seq > inputs[key]['seq'][n-1] if member == key else frame.time_s+60. > stamp
        frame.loc[mask, 'source_mid_last'] += 10000*ready['tick']
        for field in ('ofi_signed', 'dflow_near'): frame.loc[mask, field] *= -1
        for a, b in (('trade_pos', 'trade_neg'), ('refill_bid', 'refill_ask')):
            saved = frame.loc[mask, a].to_numpy(copy=True)
            frame.loc[mask, a] = frame.loc[mask, b].to_numpy(); frame.loc[mask, b] = saved
        ff[member] = frame
    return rr, ff


def reflected(inputs: dict, features: dict) -> tuple:
    """機能: 両市場の価格と数量方向を同時に上下反射する。

    引数: inputs/features (dict)。返り値: 反射後の2組 (tuple)。
    """
    rr, ff = {}, {}
    for key, ready in inputs.items():
        center = 2*np.ceil(np.max(ready['last'])/ready['tick'])*ready['tick']
        rr[key] = dict(ready, last=center-ready['last'])
        frame = features[key].copy(deep=True)
        frame['source_mid_last'] = center-frame.source_mid_last
        for field in ('ofi_signed', 'dflow_near'): frame[field] *= -1
        for a, b in (('trade_pos', 'trade_neg'), ('refill_bid', 'refill_ask')):
            old = frame[a].copy(); frame[a] = frame[b]; frame[b] = old
        ff[key] = frame
    return rr, ff


def synthetic() -> dict:
    """機能: rowとrawseqの混同、同時刻再抽選、invalidをtimerに使う反例を検査する。

    引数: なし。返り値: 合成記録 (dict)。
    """
    key = ('人工_Day', 'TOPIX')
    ready = dict(session=key[0], symbol=key[1], seq=np.array([101, 104, 107, 110, 113, 116, 119, 122]),
        time_s=np.array([0., 1., 1., 2., 3., 3., 3., 4.]), last=np.ones(8))
    direction = np.array([0, 1, 1, 0, -1, -1, 0, 0], np.int8)
    row = np.array([-1, 1, 1, 3, 4, 4, 6, 6], np.int64)
    event = np.array([-1, 0, 0, 1, 2, 2, 3, 3], np.int32)
    adapter.initialize({key: ready})
    path = adapter.condition_artifact('B06')
    adapter._CONDITIONS[path] = {'direction::'+'|'.join(key): direction, 'source_row::'+'|'.join(key): row,
        'event_index::'+'|'.join(key): event}
    adapter._VALID[adapter.condition_artifact('B06', evidence=True), key] = np.array([True, False, True, True])
    np.testing.assert_array_equal(adapter.publication_valid('B06', key), [False, True, True, False, True, True, True, True])
    for seed in range(64):
        actual = adapter.randomize_recovery(direction, row, ready, key, seed)
        expected = direction.copy()
        for i in np.flatnonzero(direction):
            payload = f'v37|{seed}|{key[0]}|{key[1]}|{int(ready["seq"][row[i]])}'.encode()
            factor = 1 if int.from_bytes(hashlib.sha256(payload).digest()[:8], 'little') % 2 == 0 else -1
            expected[i] *= factor
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(actual[:6], adapter.randomize_recovery(direction[:6], row[:6], clipped(ready, 6), key, seed))
        np.testing.assert_array_equal(-actual, adapter.randomize_recovery(-direction, row, ready, key, seed))
    rejected = 0
    for seed in (-1, 64, True, 1.5):
        try: adapter.randomize_recovery(direction, row, ready, key, seed)
        except AssertionError: rejected += 1
    assert rejected == 4
    adapter._INPUTS.clear(); adapter._CONDITIONS.clear(); adapter._VALID.clear()
    return dict(全合格=True, rawseqとready行分離=True, valid中立とinvalid分離=True,
        同時刻公開元保持=True, 全64seed別式一致=True, 接頭部反射一致=True, 不正seed拒否数=4)


def main() -> None:
    """機能: 新窓52入力と乱数回復1664入力を検査し、最終入力指紋を作る。

    引数: なし。返り値: なし (None)。旧270等の大規模監査・新損益は再実行しない。
    """
    socket.socket.connect = prepare.reject_network; socket.create_connection = prepare.reject_network
    tests = synthetic()
    manifest = prepare.read(HERE/'partial_input_artifacts.json')
    before = dict(manifest['SHA256'])
    before.update({path.relative_to(ROOT).as_posix(): prepare.digest(path) for path in
        (HERE/'partial_input_artifacts.json', HERE/'partial_input_audit.py')})
    assert before == {path: prepare.digest(ROOT/path) for path in before}
    inputs = pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    features = pickle.loads((HERE.parent/'wave_v23/features_depth.pkl').read_bytes())
    full = {}
    for spec in prepare.specs():
        source.clear_cache(); full[spec['id']] = source.build(spec, inputs, features)
    adapter.initialize(inputs)
    reuse_rows, records = [], []
    for h in adapter.SIGNALS:
        for scale in ((.8, 1., 1.2) if h == 'H019' else (1.,)):
            for key in inputs:
                value = adapter.entry(h, scale, key)
                reuse_rows.append(dict(kind='entry', id=h, scale=scale, session=key[0], symbol=key[1], n=len(value)))
    for c in adapter.CONDITIONS:
        for key in inputs:
            direction, row, event = adapter.condition(c, key)
            quality = adapter.publication_valid(c, key)
            assert quality[direction != 0].all()
            reuse_rows.append(dict(kind='condition', id=c, scale=1., session=key[0], symbol=key[1], n=len(direction)))
    for spec, scale in zip(prepare.specs(), (.8, 1.2)):
        for key, ready in inputs.items():
            peer = key[0], 'TOPIX' if key[1] == 'NK225' else 'NK225'
            expected = full[spec['id']][key]
            evidence(ready, expected, inputs[peer])
            loaded = adapter.condition('B06', key, scale)
            for name, values in zip(('direction', 'source_row', 'source_event_index'), loaded):
                np.testing.assert_array_equal(expected[name], values)
            np.testing.assert_array_equal(valid_column(expected), adapter.publication_valid('B06', key, scale))
            for n in cuts(ready):
                stamp = ready['time_s'][n-1]
                small = {key: clipped(ready, n), peer: clipped(inputs[peer], int(np.searchsorted(inputs[peer]['time_s'], stamp, side='right')))}
                source.clear_cache(); value = source.build(spec, small, features)[key]
                same_prefix(expected, value, n)
                rr, ff = future_pair(inputs, features, key, n)
                source.clear_cache(); value = source.build(spec, rr, ff)[key]
                same_prefix(expected, value, n)
            records.append(dict(id=spec['id'], session=key[0], symbol=key[1], prefix=2, future=2,
                同時刻群途中=True, 公開根拠照合=True, n=len(ready['seq'])))
        print(f'新窓 {spec["id"]} 全26の因果検査一致', flush=True)
    rr, ff = reflected(inputs, features)
    for spec in prepare.specs():
        source.clear_cache(); reflected_values = source.build(spec, rr, ff)
        for key in inputs:
            base, mirror = full[spec['id']][key], reflected_values[key]
            np.testing.assert_array_equal(base['direction'], -mirror['direction'])
            for name in ('source_row', 'source_event_index'): np.testing.assert_array_equal(base[name], mirror[name])
            np.testing.assert_array_equal(valid_column(base), valid_column(mirror))
    # ----------------------------------------
    # 乱数の新規要素だけを全seed検査する。元B06は既存証跡を継承する。
    random_rows = []
    for key, ready in inputs.items():
        direction, row, event = adapter.condition('B06', key)
        for seed in range(64):
            values, source_rows, indices = adapter.recovery('B06', key, random_seed=seed)
            assert np.array_equal(values == 0, direction == 0)
            assert np.array_equal(source_rows, row) and np.array_equal(indices, event)
            for n in cuts(ready):
                np.testing.assert_array_equal(values[:n], adapter.randomize_recovery(direction[:n], row[:n], clipped(ready, n), key, seed))
            np.testing.assert_array_equal(-values, adapter.randomize_recovery(-direction, row, ready, key, seed))
            random_rows.append(dict(seed=seed, session=key[0], symbol=key[1], prefix=2, reflection=1,
                非0保持=True, 公開元保持=True, SHA256=hashlib.sha256(values.tobytes()).hexdigest()))
    assert len(reuse_rows) == 22*26 and len(records) == 52 and len(random_rows) == 64*26
    source.clear_cache()
    assert before == {path: prepare.digest(ROOT/path) for path in before}
    original = manifest['再利用']['原本78SHA256']
    assert original == {path: prepare.digest(ROOT/path) for path in original}
    result = dict(全入力監査合格=True, 旧証跡SHA継承=True, 旧大規模再検査=False,
        再利用列入力数=len(reuse_rows), 再利用列=reuse_rows, 新窓固有数=2, 新窓入力数=52,
        新窓prefix数=104, 新窓future数=104, 新窓reflection数=52, 新窓検査=records,
        乱数seed数=64, 乱数入力数=1664, 乱数prefix数=3328, 乱数reflection数=1664,
        乱数検査=random_rows, 合成検査=tests, 原本78SHA256=original, 参照SHA256=before,
        新損益読取=False, 売買再生=False, 現在保存物使用=False, API取得数=0)
    prepare.save(HERE/'partial_input_causality.json', result)
    final = dict(before, **original)
    final['work/wave_v37/partial_input_causality.json'] = prepare.digest(HERE/'partial_input_causality.json')
    prepare.save(HERE/'partial_input_fixed.json', dict(全入力監査合格=True, 再利用入口数=14,
        再利用条件数=8, 新窓方向数=2, 乱数seed数=64, 新損益読取=False, SHA256=final))
    (HERE/'partial_input_contract.md').write_text('# 部分調整の入力\n\n旧14入口と8観測方向はv35の保存物・監査SHAを再利用する。新規はB06窓96/144秒だけで、悪化と回復へ別指定できる。短窓・段階窓も同率になり、peer遅延と鮮度は60秒のまま。\n\nsource_rowはreadyの配列行でありrawseqではない。根拠のrawseqはready.seq[source_row]。timerはpublication_validを併用し、有効中立は許すがinvalid・staleは許さない。peer同意はtimerに要求しない。\n\n乱数回復は元B06の非0機会を保ち、公開元rawseqごとの固定符号を元方向へ掛ける。素材の意味・発火時刻の情報は残る。配列末尾や将来イベント数を使わず、同時刻でも公開順を守る。\n\n全新窓の切断・未公開peer改変・反射、全64seedの接頭部と反射を検査。新損益、売買再生、API、保存ライブは使用していない。\n', encoding='utf-8')
    print({'全入力監査合格': True, '新窓入力数': 52, '乱数入力数': 1664}, flush=True)


if __name__ == '__main__':
    main()
