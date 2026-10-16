"""追加C03の採否と、三源から整数配分までの未来切断を独立に確認する。"""

from pathlib import Path
import json
import pickle
import sys
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0, str(WORK / 'audit'))
import execution_checks as common


def save(name, value):
    """
    機能: 源監査の有限JSONをこの監査領域だけへ保存する。
    引数: name(str)、value(dict)。
    返り値: None。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def quality(frame, ready, observation, expected):
    """
    機能: 差分累積表を使わず窓の実行を直接読み、旧C03の全起点採否を復元する。
    引数: frame/observation(DataFrame)、ready/expected(dict)。
    返り値: dictの品質集計。
    """
    assert (frame.source_last_seq < frame.seq).all()
    assert (frame.source_time_s < frame.time_s).all()
    assert (frame.volume_time_s <= frame.time_s).all()
    times = frame.time_s.to_numpy()
    accepted = []
    counts = dict(起点候補=0, 過去価格不足=0, ATR不足=0, 現在品質不良=0, 採用起点=0)
    for origin in np.arange(ready['start'] + 1200., ready['limit'], 60.):
        counts['起点候補'] += 1
        query = np.array([origin - 300, origin - 60, origin])
        found = np.searchsorted(times, query, side='right') - 1
        if min(found) < 0 or np.any(query - times[found] > 60):
            counts['過去価格不足'] += 1
            continue
        a, b, end = map(int, found)
        if not np.isfinite(frame.iloc[end].atr) or frame.iloc[end].atr <= 0:
            counts['ATR不足'] += 1
            continue
        window = frame.iloc[:end + 1]
        window = window[(window.time_s > origin - 60) & (window.source_time_s >= origin - 60)]
        bad = len(window) < 2 or window.valid_events.sum() < 2 or window.source_age.max() > 60
        for column in ('continuity_resets', 'volume_resets', 'unavailable_volume_events',
                       'depth_incomplete_events', 'depth_disordered_events', 'depth_duplicate_events'):
            bad = bad or window[column].sum() > 0
        if bad:
            counts['現在品質不良'] += 1
            continue
        checkpoints = np.arange(origin - 300., origin + .1, 60.)
        indices = np.searchsorted(times, checkpoints, side='right') - 1
        if np.any(checkpoints - times[indices] > 60):
            counts['過去価格不足'] += 1
            continue
        accepted.append(origin)
        counts['採用起点'] += 1
        row = observation.loc[observation.time_s == origin]
        assert len(row) == 1
        row = row.iloc[0]
        assert row.observed_time == times[end] and row.seq == frame.iloc[end].seq
        assert row.observed_time <= origin and row.source_max_age <= 60
        assert row.valid_events == window.valid_events.sum() and row.blocks == len(window)
        assert abs(row.r1 - (frame.iloc[end].mid - frame.iloc[b].mid) / frame.iloc[end].atr) < 1e-10
        assert abs(row.r5 - (frame.iloc[end].mid - frame.iloc[a].mid) / frame.iloc[end].atr) < 1e-10
    np.testing.assert_array_equal(accepted, observation.time_s.to_numpy())
    assert counts == expected
    return counts


def fingerprints(prepare):
    """
    機能: 源・入力固定証拠と今回監査の指紋を取得する。
    引数: prepare(module)。
    返り値: dict[str,str]。研究実行器は含めない。
    """
    paths = [WORK / name for name in ('sources.py', 'source_prepare.py', 'm3_engine.py', 'c03_observe.py',
        'execution.py', 'accounting.py', 'catalog.py', 'prepared/sources.pkl', 'prepared/source_orders.pkl',
        'prepared/源素材の固定.json', 'prepared/準備完了.json')]
    paths += [Path(__file__), WORK / 'audit/execution_checks.py', WORK / 'audit/m3_checks.py',
              WORK / 'audit/M3観測建値と価格飛越しの人工検査.json']
    return {str(p.relative_to(common.ROOT)): prepare.sha(p) for p in paths}


def main():
    """
    機能: 追加十四口座の採否と代表四口座の特徴・注文・実配分を未来切断する。
    引数: なし。
    返り値: None。全配分の損益を探索せず主配分の因果性だけを検査する。
    """
    sources = common.module('wave88_source_audit_sources', WORK / 'sources.py')
    prepare = sources.prepare
    before = fingerprints(prepare)
    package, proof = prepare.load(verify=True)
    inputs, signals, input_hashes = prepare.prepare85.load_inputs(verify=True)
    assert input_hashes == proof['原入力SHA256']
    old_frames = pickle.loads((common.ROOT / 'work/wave_v52/measurement/features.pkl').read_bytes())
    extra = sorted(set(inputs) - set(old_frames))
    assert len(extra) == 14
    frames = dict(old_frames)
    quality_proofs = []
    for key in extra:
        path = WORK / 'prepared/追加C03' / f'{key[0]}_{key[1]}.pkl'
        blob = pickle.loads(path.read_bytes())
        frames[key] = blob['frame']
        tally = quality(blob['frame'], inputs[key], blob['observation'], blob['quality'])
        rebuilt, _ = prepare.observe.build_account(blob['frame'], inputs[key])
        pd.testing.assert_frame_equal(rebuilt, blob['observation'])
        pd.testing.assert_frame_equal(rebuilt, package['c03_observations'][key])
        quality_proofs.append(dict(セッション=key[0], 商品=key[1], **tally))
    print('追加C03全14口座の品質採否・原本公開元・観測値が一致', flush=True)
    features = sources.initialize(inputs, signals)
    helper = common.module('監査88切断道具', common.ROOT / 'work/wave_v86/audit/support.py')
    execution = common.module('監査88源から実行', WORK / 'execution.py')
    selected = [(session, symbol) for session in ('2026-10-07_Day', '2026-10-08_Night') for symbol in ('TOPIX', 'NK225')]
    allocation = dict(GU=6, M3=2, C03=2)
    records, raw_checks = [], []
    for key in selected:
        ready = inputs[key]
        full = {name: sources.play(name, key, ready, features)['orders'] for name in common.SOURCES}
        combined = execution.execute(ready, full, allocation)
        n = len(ready['last'])
        cuts = {int(n * .31), int(n * .71)}
        for orders in full.values():
            for group in (orders[orders[:, 7] == 1], orders[orders[:, 7] == 0]):
                if len(group):
                    for order in (group[0], group[-1]):
                        row = int(order[0])
                        cuts.update((row, row + 1, row + 2))
        cuts = sorted(c for c in cuts if 3 < c < n)
        arrays = 0
        for count in cuts:
            short = helper.clip(ready, count, n)
            peer_key = key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
            peer = inputs[peer_key]
            until = int(np.searchsorted(peer['time_s'], short['time_s'][-1], side='right'))
            clipped_peer = helper.clip(peer, until, len(peer['last']))
            directions, _ = prepare.m3_directions({key: short, peer_key: clipped_peer})
            np.testing.assert_array_equal(directions[key], package['m3'][key][:count])
            short_frame = frames[key][frames[key].seq <= short['seq'][-1]].copy()
            observations, _ = prepare.observe.build_account(short_frame, short)
            observations = observations.loc[observations.time_s <= short['time_s'][-1]].reset_index(drop=True)
            expected_observations = package['c03_observations'][key]
            expected_observations = expected_observations.loc[expected_observations.time_s <= short['time_s'][-1]].reset_index(drop=True)
            pd.testing.assert_frame_equal(observations, expected_observations)
            decisions, _ = prepare.backtest.build_signals(short, observations, 'C03', sources.C03_FIXED['尺度'])
            np.testing.assert_array_equal(decisions, package['c03'][key][package['c03'][key][:, 0] < count])
            feature = dict(GU=helper.clip(features[key]['GU'], count, n), M3=directions[key], C03=decisions)
            shorter = {name: sources.play(name, key, short, feature, finish=False)['orders'] for name in common.SOURCES}
            for name in common.SOURCES:
                np.testing.assert_array_equal(shorter[name], full[name][full[name][:, 0] < count])
            actual = execution.execute(short, shorter, allocation, finish=False)
            for name in ('orders', 'target_trace'):
                np.testing.assert_array_equal(actual[name], combined[name][combined[name][:, 0] < count])
            arrays += 8
        # ----------------------------------------
        # 追加場の原本を途中で読取り終了し、最後の未公開箱が混入しないことも確認する。
        count = int(n * .31)
        raw_cut = int(ready['seq'][count - 1]) + 1
        raw_path = common.ROOT / 'book' / key[1] / (key[0] + '.jsonl')
        raw_frame, raw_audit = prepare.extract.extract(raw_path, ready, max_rows=raw_cut)
        expected_frame = frames[key][frames[key].seq < raw_cut].reset_index(drop=True)
        pd.testing.assert_frame_equal(raw_frame.reset_index(drop=True), expected_frame)
        raw_checks.append(dict(セッション=key[0], 商品=key[1], 原本切断行=raw_cut,
            公開特徴行数=len(raw_frame), 原本部分SHA256=raw_audit['原本SHA256']))
        records.append(dict(セッション=key[0], 商品=key[1], 切断地点=len(cuts), 配列照合数=arrays,
            源注文数={name:len(orders) for name,orders in full.items()}))
        print(key, len(cuts), '特徴・三源注文・配分・原本途中読取一致', flush=True)
    assert before == fingerprints(prepare)
    save('三源の追加品質と原本から配分までの未来切断.json', dict(全合格=True, 追加品質口座数=len(extra),
        代表口座数=len(records), 切断地点数=sum(r['切断地点'] for r in records),
        配列照合数=sum(r['配列照合数'] for r in records), 原本途中抽出口座数=len(raw_checks),
        追加品質=quality_proofs, 原本切断=raw_checks, 検査=records, コード素材SHA256=before,
        将来ラベル='旧C03の未来ラベルを作らず、過去の公開箱と固定尺度だけから観測・判断を再生成した。',
        検査範囲='源の旧一致は別証拠、ここでは追加素材と代表実データの因果性を独立確認。新配分の全場収支は未計算。'))
    print('三源の追加品質と未来切断が全合格', flush=True)


if __name__ == '__main__':
    main()
