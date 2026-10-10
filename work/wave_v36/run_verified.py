"""価格帯入力・固定判定・注文器接続の証跡を結び、検査前の売買再生を拒否する。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import pickle
import subprocess
import sys
from zoneinfo import ZoneInfo

import numpy as np

import band_runner as runner
import band_assessment as assessment
import volume_quote_events as volume


HERE, ROOT = runner.HERE, runner.ROOT


def unique(rows: list[dict], fields: tuple) -> dict:
    """機能: 明細の重複を拒否した索引を作る。

    引数: rows (list[dict])、fields (tuple[str,...])。返り値: 索引 (dict)。
    """
    result = {tuple(row[name] for name in fields): row for row in rows}
    assert len(result) == len(rows), '明細重複'
    return result


def verify_catalog(fixed: dict) -> None:
    """機能: 主仮説と全条件・補助全seed/反転の正確な集合を確認する。

    引数: fixed (dict)。返り値: なし (None)。上位だけへの削減を許さない。
    """
    assert fixed['conditions'] == runner.design.conditions()
    assert fixed['supplementary_conditions'] == runner.design.supplementary_conditions()
    assert fixed['主仮説'] == assessment.PRIMARY == 'Q034__V000'
    assert fixed['全条件数'] == 364 and fixed['主条件数'] == 91 and fixed['診断条件数'] == 273
    assert fixed['補助条件数'] == 65
    assert len(unique(fixed['conditions'], ('id',))) == 364
    extras = unique(fixed['supplementary_conditions'], ('id',))
    assert set(extras) == {(f'Q034__R{seed:03d}',) for seed in range(64)} | {('Q034__REV',)}
    assert {r['random_seed'] for r in extras.values() if 'random_seed' in r} == set(range(64))
    for key, row in extras.items():
        assert row['signal_id'] == 'Q034' and row['variant_id'] == 'V000'
        assert row['clock_scale'] == 1. and row['observed_fill'] is False
        assert row['supplementary'] is True and row['primary'] is False
        assert row.get('reverse_direction', False) == (key == ('Q034__REV',))


def verify_event_frame(events, feature) -> None:
    """機能: 個別価格イベントの側・数量比・原本隣接性・公開境界を別式で照合する。

    引数: events/feature (DataFrame)。返り値: なし (None)。原本再抽出は行わない。
    """
    assert set(volume.COLUMNS) == set(events)
    assert events.current_seq.is_unique and events.current_seq.is_monotonic_increasing
    assert (events.current_seq == events.prev_seq + 1).all()
    assert (events.volume_delta == events.current_volume - events.prev_volume).all()
    assert (events.volume_delta > 0).all()
    side = np.where(events.current_price == events.ask, 1, np.where(events.current_price == events.bid, -1, 0))
    qty = np.where(side == 1, events.ask_qty, np.where(side == -1, events.bid_qty, 0.))
    ratio = np.divide(events.volume_delta, qty, out=np.full(len(events), np.nan), where=qty > 0)
    assert np.array_equal(events.side.to_numpy(), side)
    assert np.array_equal(events.side_qty.to_numpy(), qty)
    assert np.array_equal(events.volume_to_side_qty.to_numpy(), ratio, equal_nan=True)
    stable = np.ones(len(events), bool)
    for current, prior in (('current_price', 'prev_price'), ('bid', 'prev_bid'), ('ask', 'prev_ask'),
                           ('bid_qty', 'prev_bid_qty'), ('ask_qty', 'prev_ask_qty')):
        stable &= events[current].to_numpy() == events[prior].to_numpy()
    assert np.array_equal(events.stable.to_numpy(), stable)
    positions = events.feature_row.to_numpy(np.int64)
    assert np.all((positions >= 0) & (positions < len(feature)))
    for event_field, source_field in (('source_first_seq', 'source_first_seq'), ('source_last_seq', 'source_last_seq'),
                                     ('release_seq', 'seq'), ('release_time_s', 'time_s')):
        assert np.array_equal(events[event_field].to_numpy(), feature[source_field].to_numpy()[positions])
    assert np.all(events.current_time_s.to_numpy() == feature.source_time_s.to_numpy()[positions])
    assert (events.source_first_seq <= events.current_seq).all()
    assert (events.current_seq <= events.source_last_seq).all() and (events.source_last_seq < events.release_seq).all()
    assert (events.prev_volume_time_s <= events.release_time_s).all()
    assert (events.current_volume_time_s <= events.release_time_s).all()


def verify_direction(values: np.ndarray, source: np.ndarray, episode: np.ndarray,
                     records: list[dict], ready: dict, params: dict) -> None:
    """機能: 保存方向と根拠列を、保存された全採用区間から独立に展開して照合する。

    引数: values/source/episode (ndarray)、records (list[dict])、ready/params (dict)。
    返り値: なし (None)。価格から信号を再生成せず、入力成果の接続を検査する。
    """
    n = len(ready['seq'])
    assert values.dtype == np.int8 and source.dtype == episode.dtype == np.int64
    assert values.shape == source.shape == episode.shape == (n,)
    assert np.isin(values, (-1, 0, 1)).all()
    assert np.all(source[values == 0] == -1) and np.all(episode[values == 0] == -1)
    assert np.all((source[values != 0] >= 0) & (source[values != 0] <= ready['seq'][values != 0]))
    assert [r['episode_id'] for r in records] == list(range(len(records)))
    accepted = []
    for row in records:
        assert row['stable_volume_score'] <= row['all_volume_score'] + 1e-8
        assert row['stable_volume_score'] >= 0 and row['all_volume_score'] >= 0
        assert row['setup_source_last_seq'] < row['setup_seq']
        assert row['setup_source_time_s'] < row['setup_time_s']
        confirmed = row['resolution'] == 'confirmed'
        proxy = params['proxy']
        proxy_pass = proxy == 'price' or row[proxy + '_score'] >= params['volume_threshold']
        branch_pass = confirmed and (params['branch'] == 'automatic' or row['response_branch'] == params['branch'])
        peer = params['peer_mode']
        peer_pass = peer == 'none' or (row['peer_available'] and
            (row['peer_direction'] != -row['response_direction'] if peer == 'veto'
             else row['peer_direction'] == row['response_direction']))
        assert row['proxy_pass'] == bool(proxy_pass) and row['branch_pass'] == bool(branch_pass)
        assert row['peer_pass'] == bool(peer_pass)
        assert row['accepted'] == bool(confirmed and proxy_pass and branch_pass and peer_pass)
        if confirmed:
            assert row['confirmation_seq'] > row['setup_seq']
            assert row['resolution_source_last_seq'] < row['confirmation_seq']
            assert row['setup_time_s'] < row['confirmation_time_s'] < row['expiry_time_s']
        if row['accepted']:
            assert row['response_direction'] in (-1, 1)
            assert row['signal_expiry_time_s'] == row['confirmation_time_s'] + params['signal_lifetime_seconds']
            if peer != 'none':
                assert row['peer_available'] and row['peer_available_time_s'] <= row['confirmation_time_s']
            accepted.append(row)
    expected = np.zeros(n, np.int8)
    expected_source = np.full(n, -1, np.int64)
    expected_episode = np.full(n, -1, np.int64)
    for i, row in enumerate(accepted):
        left = int(np.searchsorted(ready['seq'], row['confirmation_seq'], side='left'))
        right = int(np.searchsorted(ready['time_s'], row['signal_expiry_time_s'], side='left'))
        if i + 1 < len(accepted):
            right = min(right, int(np.searchsorted(ready['seq'], accepted[i + 1]['confirmation_seq'], side='left')))
        if right > left:
            expected[left:right] = row['response_direction']
            expected_source[left:right] = row['confirmation_seq']
            expected_episode[left:right] = row['episode_id']
    assert np.array_equal(values, expected)
    assert np.array_equal(source, expected_source) and np.array_equal(episode, expected_episode)


def verify_material(inputs: dict, load, check) -> dict:
    """機能: 全方向・根拠・共通価格区間と旧比較の保存実体を確認する。

    引数: inputs (dict)、load/check (callable)。返り値: 実体件数 (dict)。
    """
    features = pickle.loads((HERE.parent / 'wave_v23/features_depth.pkl').read_bytes())
    events = pickle.loads((HERE / 'events.pkl').read_bytes())
    assert set(inputs) == set(features) == set(events) and len(inputs) == 26
    for key in inputs:
        verify_event_frame(events[key], features[key])
    artifact = load(HERE / 'input_artifacts.json')
    assert artifact['方向ファイル数'] == 273 and artifact['新信号方向ファイル数'] == 270
    assert artifact['旧比較方向ファイル数'] == 3 and artifact['新規根拠ファイル数'] == artifact['新規区間明細数'] == 270
    assert artifact['全26入力'] is True and artifact['新損益再生'] is False
    for name, sha in artifact['SHA256'].items():
        check(ROOT / name, sha)
    new_ids = {s['id'] + f'__C{int(scale * 100):03d}' for s in runner.design.catalog() for scale in (.8, 1., 1.2)}
    old_ids = {'H019__C080', 'H019__C100', 'H019__C120'}
    for folder, suffix, expected in (('directions', '.npz', new_ids | old_ids),
                                     ('provenance', '.npz', new_ids), ('episodes', '.json.gz', new_ids)):
        assert {p.name for p in (HERE / folder).glob('*' + suffix)} == {name + suffix for name in expected}
    expected_keys = {'|'.join(key) for key in inputs}
    mothers, count = {}, 0
    direction_sha = hashlib.sha256()
    for scale in (.8, 1., 1.2):
        for spec in runner.design.catalog():
            name = spec['id'] + f'__C{int(scale * 100):03d}'
            rows = load(HERE / 'episodes' / (name + '.json.gz'))
            records = unique(rows, ('session', 'symbol'))
            assert set(records) == set(inputs)
            with np.load(HERE / 'directions' / (name + '.npz'), allow_pickle=False) as directions, \
                 np.load(HERE / 'provenance' / (name + '.npz'), allow_pickle=False) as provenance:
                assert set(directions.files) == expected_keys
                assert set(provenance.files) == {prefix + label for prefix in ('source_row::', 'source_episode::') for label in expected_keys}
                for key, ready in inputs.items():
                    label = '|'.join(key)
                    row = records[key]
                    verify_direction(directions[label], provenance['source_row::' + label],
                        provenance['source_episode::' + label], row['episodes'], ready, spec['params'])
                    direction_sha.update(directions[label].tobytes())
                    # 共通準備に採否・他市場の都合が混ざっていないことを全対応で確認する。
                    basic = [{k: v for k, v in ep.items() if not k.startswith('peer_') and k not in
                        ('accepted', 'proxy_pass', 'branch_pass', 'rejection_reasons', 'signal_expiry_time_s')} for ep in row['episodes']]
                    common = key, spec['params']['window_seconds'], scale
                    if common in mothers:
                        assert mothers[common] == basic, '共通価格準備を情報条件で変更した'
                    else:
                        mothers[common] = basic
                    count += 1
        old = f'H019__C{int(scale * 100):03d}.npz'
        check(HERE / 'directions' / old, check(HERE.parent / 'wave_v35/entries' / old))
        with np.load(HERE / 'directions' / old, allow_pickle=False) as archive:
            assert set(archive.files) == expected_keys
            for key, ready in inputs.items():
                array = archive['|'.join(key)]
                assert array.dtype == np.int8 and array.shape == (len(ready['seq']),)
                assert np.isin(array, (-1, 0, 1)).all()
    assert count == 7020 and len(mothers) == 156
    return dict(方向ファイル数=273, 根拠ファイル数=270, 共通区間ファイル数=270,
        新方向入力数=count, 共通価格準備群数=len(mothers), 個別出来高入力数=26, 旧H019方向3同一=True,
        全条件方向SHA256=direction_sha.hexdigest())


def verify_signal_audits(inputs: dict, load, check) -> dict:
    """機能: 全入力の母集団監査と全条件の代表期間因果監査を、別の検査範囲として結ぶ。

    引数: inputs (dict)、load/check (callable)。返り値: 件数・最終方向指紋 (dict)。
    全26で行った検査と代表期間だけの検査を混同しない。
    """
    implementation = load(HERE / 'band_signal_audit.json')
    independent = load(HERE / 'band_signal_independent_audit.json')
    for audit in (implementation, independent):
        assert audit['全監査合格'] is True and audit['入力ソース前後不変'] is True
        assert audit['新損益読取'] is False and audit['売買再生'] is False
        assert audit['現在保存物使用'] is False and audit['API取得数'] == 0
        assert audit['人工検査']['全合格'] is True
        for name, sha in audit['参照SHA256'].items():
            check(ROOT / name, sha)
    assert implementation['全入力数'] == 26 and implementation['全条件時計入力数'] == 7020
    assert implementation['共通価格母集団数'] == 156
    assert implementation['接頭部列比較数'] == implementation['未来改変列比較数'] == 2808
    assert implementation['売買反射列比較数'] == 1404
    activities = unique(implementation['条件別活動量'], ('id', 'clock_scale'))
    expected = {(spec['id'], scale) for spec in runner.design.catalog() for scale in (.8, 1., 1.2)}
    assert set(activities) == expected
    periods = ['2026-09-22_Night', '2026-09-29_Day']
    assert independent['代表期間'] == periods and independent['入力区間数'] == 4
    assert independent['条件時計数'] == 270 and independent['条件入力組数'] == 1080
    assert independent['prefix入力比較数'] == 2160 and independent['prefix配列比較数'] == 6480
    for kind in ('未来改変', '上下反射'):
        assert independent[kind + '入力比較数'] == 1080 and independent[kind + '配列比較数'] == 3240
    columns = ['direction', 'source_episode', 'source_row']
    assert independent['比較列'] == columns
    records = unique(independent['検査行'], ('id', 'clock_scale', 'session', 'symbol'))
    assert set(records) == {(name, scale, session, symbol) for name, scale in expected
                            for session in periods for symbol in ('TOPIX', 'NK225')}
    for row in records.values():
        assert row['全一致'] is True and row['prefix検査数'] == 2
        assert row['未来改変検査数'] == row['上下反射検査数'] == 1 and row['比較列'] == columns
    clocks = unique(independent['共通時計切断'], ('session', 'fraction'))
    assert set(clocks) == {(session, fraction) for session in periods for fraction in (.37, .73)}
    for (session, fraction), row in clocks.items():
        assert row['同時刻群途中'] == (fraction == .73)
        assert set(row['cuts']) == {'TOPIX', 'NK225'}
        for symbol, count in row['cuts'].items():
            ready = inputs[session, symbol]
            assert 0 < count < len(ready['seq'])
            assert ready['time_s'][count-1] <= row['clock']
            if fraction == .73 and symbol == 'NK225':
                assert ready['time_s'][count-1] == ready['time_s'][count] == row['clock']
            else:
                assert count == int(np.searchsorted(ready['time_s'], row['clock'], side='right'))
    assert independent['人工検査']['検査']['窓外0.3の丸めでK2の部分集合を逆転させない'] is True
    synthetic = load(HERE / 'band_signal_selftest.json')
    assert synthetic['人工検査'] == implementation['人工検査']
    assert synthetic['入力ソース前後不変'] is True
    for name, sha in synthetic['参照SHA256'].items():
        check(ROOT / name, sha)
    subset = load(HERE / 'band_subset_audit.json')
    assert subset['全監査合格'] is True and subset['入力ソース前後不変'] is True
    assert subset['売買再生'] is False and subset['新損益読取'] is False
    assert subset['API取得数'] == 0 and subset['現在保存物使用'] is False
    assert subset['全入力数'] == 26 and subset['対応集合数'] == 2808
    for name, sha in subset['参照SHA256'].items():
        check(ROOT / name, sha)
    subset_rows = unique(subset['検査行'], ('clock_scale', 'window_seconds', 'branch', 'peer_mode', 'session', 'symbol', 'threshold'))
    assert set(subset_rows) == {(scale, window, branch, peer, session, symbol, threshold)
        for scale in (.8, 1., 1.2) for window in (120., 600.)
        for branch in ('reversal', 'breakout', 'automatic') for peer in ('none', 'veto', 'confirm')
        for session, symbol in inputs for threshold in (2., 5.)}
    for row in subset_rows.values():
        assert row['採用episode部分集合一致'] is True
        assert 0 <= row['気配維持採用数'] <= row['全量採用数'] <= row['純価格採用数']
    return dict(全26母集団入力数=7020, 共通準備群数=156,
        全270代表期間入力数=1080, 独立接頭部入力数=2160, 独立未来入力数=1080, 独立反射入力数=1080,
        実装者接頭部配列数=2808, 実装者未来配列数=2808, 実装者反射配列数=1404,
        採用episode部分集合対応数=2808, 全条件方向SHA256=implementation['全条件方向SHA256'])


def verify_sources() -> dict:
    """機能: 最終入力監査・人工判定・注文器接続を結合して起動可否を返す。

    引数: なし。返り値: 起動証跡 (dict)。全証跡のSHAを読取前後で確認する。
    """
    hashes = {}
    def check(path: Path, expected: str | None = None) -> str:
        """機能: 参照資料のSHAを一度だけ計算し、複数証跡間の不一致を拒否する。

        引数: path (Path)、expected (str|None)。返り値: 実体SHA (str)。
        """
        path = path.resolve()
        relative = path.relative_to(ROOT).as_posix()
        assert '/live/' not in relative.lower() and '/current/' not in relative.lower()
        if relative not in hashes:
            hashes[relative] = runner.digest(path)
        if expected is not None:
            assert hashes[relative] == expected, '指紋不一致: ' + relative
        return hashes[relative]
    def load(path: Path) -> dict:
        """機能: 読み込むJSONも内容とともに証跡へ加える。

        引数: path (Path)。返り値: JSON値 (dict)。
        """
        check(path)
        return runner.read(path)
    def references(record: dict, field: str = '参照SHA256') -> None:
        """機能: 記録が参照する全資料の実体を検査する。

        引数: record (dict)、field (str)。返り値: なし (None)。
        """
        assert record[field]
        for relative, sha in record[field].items():
            check(ROOT / relative, sha)

    fixed = load(HERE / '探索条件の固定.json')
    verify_catalog(fixed)
    references(fixed, 'SHA256')
    material = load(HERE / '入力固定.json')
    assert material['全入力監査合格'] is True and material['方向ファイル数'] == 273
    references(material, 'SHA256')
    mandatory = ('input_artifacts.json', 'band_signal_audit.json', 'band_signal_independent_audit.json',
        'band_signal_selftest.json', 'band_subset_audit.json', 'volume_quote_audit.json', 'volume_quote_fixed.json', 'volume_quote_selftest.json')
    for name in mandatory:
        relative = (HERE / name).relative_to(ROOT).as_posix()
        assert relative in material['SHA256'] and relative in fixed['SHA256'], '固定対象不足: ' + relative
    input_path = HERE.parent / 'wave_v23/inputs.pkl'
    check(input_path)
    inputs = pickle.loads(input_path.read_bytes())
    names = sorted({key[0] for key in inputs})
    assert len(inputs) == 26 and len(names) == 13
    assert fixed['全セッション'] == names and fixed['後半7セッション'] == names[6:]
    assert fixed['指定波'] == list(runner.base.wave_metrics.EPISODES)
    old = load(HERE.parent / 'wave_v35/探索条件の固定.json')
    assert fixed['manager'] == old['manager']
    original = load(HERE.parent / 'wave_v35/input_causality_before_pnl.json')['原本78SHA256']
    assert len(original) == 78
    for relative, sha in original.items():
        assert fixed['SHA256'][relative] == sha
        check(ROOT / relative, sha)

    # ----------------------------------------
    # 出来高代理の抽出と二系統の信号因果監査を接続する。
    volume_fixed = load(HERE / 'volume_quote_fixed.json')
    volume_audit = load(HERE / 'volume_quote_audit.json')
    volume_test = load(HERE / 'volume_quote_selftest.json')
    assert volume_audit['全監査合格'] is True and volume_audit['原本前後不変'] is True
    assert volume_audit['全入力数'] == volume_fixed['全入力数'] == 26
    assert volume_audit['接頭部検査数'] == volume_audit['未来改変検査数'] == 52
    assert volume_test == volume_audit['人工検査'] and volume_test['全合格'] is True
    assert volume_test['検査数'] == len(volume_test['検査']) == 15 and all(volume_test['検査'].values())
    assert volume_audit['固定SHA256'] == check(HERE / 'volume_quote_fixed.json')
    check(HERE / 'events.pkl', volume_audit['出力SHA256'])
    assert volume_audit['原本26SHA256'] == volume_fixed['原本26SHA256']
    assert len(volume_fixed['原本26SHA256']) == 26
    for relative, sha in volume_fixed['原本26SHA256'].items():
        assert original[relative] == sha
        check(ROOT / relative, sha)
    for record in (volume_fixed, volume_audit):
        references(record)
        assert record['新損益読取'] is False and record['売買再生'] is False
        assert record['API取得数'] == 0 and record['現在保存物使用'] is False
    events = pickle.loads((HERE / 'events.pkl').read_bytes())
    records = unique(volume_audit['各入力'], ('session', 'symbol'))
    assert set(records) == set(events) == set(inputs)
    assert sum(len(events[key]) for key in inputs) == volume_audit['全イベント数']
    for key, row in records.items():
        assert row['保存イベント数'] == len(events[key])
        assert len(row['境界検査']) == 2
        assert all(item['接頭部一致'] is True and item['未来改変一致'] is True for item in row['境界検査'])
    signal_proof = verify_signal_audits(inputs, load, check)
    content = verify_material(inputs, load, check)
    assert signal_proof['全条件方向SHA256'] == content['全条件方向SHA256']
    revision = load(HERE / '代理スコアの数値境界改訂.json')
    for flag in ('仕様閾値変更', '新損益読取', '売買再生'):
        assert revision[flag] is False
    assert revision['API取得数'] == 0
    for label, path in (('旧信号', 'band_signals_cumsum_before_audit.py.txt'),
        ('新信号', 'band_signals.py'), ('旧監査', 'band_signal_audit_before_fsum.py.txt'),
        ('新監査', 'band_signal_audit.py')):
        check(HERE / path, revision[label + 'SHA256'])

    # ----------------------------------------
    # 採否42人工と注文接続72人工は実損益を読まない段階で固定する。
    criteria = load(HERE / 'band_assessment_fixed.json')
    criteria_test = load(HERE / 'band_assessment_test.json')
    references(criteria)
    assert criteria['主仮説'] == fixed['主仮説'] and criteria['主仮説の事後差替'] is False
    assert criteria['全条件数'] == 364 and criteria['別補助条件数'] == 65
    assert criteria['人工検査'] == criteria_test
    assert criteria_test['全検査合格'] is True and criteria_test['検査数'] == len(criteria_test['検査']) == 42
    assert all(row['一致'] is True for row in criteria_test['検査'])
    for flag in ('新損益読取', '売買再生', '現在保存物使用'):
        assert criteria[flag] is False and criteria_test[flag] is False
    change = load(HERE / '乱数対照の説明明確化.json')
    assert change['説明明確化のみ'] is True and change['採否条件変更'] is False and change['乱数実装変更'] is False
    assert change['新損益読取'] is False and change['売買再生'] is False
    for label, path in (('旧規則', '採否と反証の事前規則_乱数保持情報明記前.md'),
        ('新規則', '採否と反証の事前規則.md'), ('旧判定固定', 'band_assessment_fixed_乱数保持情報明記前.json'),
        ('新判定固定', 'band_assessment_fixed.json')):
        check(HERE / path, change[label + 'SHA256'])
    previous = load(HERE / 'band_assessment_fixed_乱数保持情報明記前.json')
    altered = [key for key in previous['参照SHA256'] if previous['参照SHA256'][key] != criteria['参照SHA256'][key]]
    assert altered == change['変更参照'] == ['work/wave_v36/band_assessment.py', 'work/wave_v36/採否と反証の事前規則.md']
    check(HERE / 'band_assessment_乱数保持情報明記前.py', change['旧判定実装SHA256'])
    check(HERE / 'band_assessment.py', change['新判定実装SHA256'])
    old_text = (HERE / 'band_assessment_乱数保持情報明記前.py').read_text(encoding='utf-8')
    expected_text = old_text.replace('活動時刻だけを保つ方向対照。実際の新規数・保有時間・約定は揃わず、正式p値ではない。',
        '元方向へ30分ブロック共通の符号を掛ける構造保存対照。活動時刻・ブロック内の方向変化・両市場の相対方向関係を保つ。実際の新規数・保有時間・約定は揃わず、正式p値ではない。')
    assert expected_text == (HERE / 'band_assessment.py').read_text(encoding='utf-8')
    assert {k: v for k, v in previous.items() if k != '参照SHA256'} == {k: v for k, v in criteria.items() if k != '参照SHA256'}
    synthetic = load(HERE / 'band_runner_synthetic.json')
    for flag in ('人工経路72合格', '全行独立会計', '全玉場内返済', 'JSON非有限拒否'):
        assert synthetic[flag] is True
    assert synthetic['prefix'] == synthetic['future'] == 144 and synthetic['reflection'] == 72
    assert synthetic['新規原本成績使用'] is False
    for field, path in (('実装SHA256', HERE / 'band_runner_synthetic.py'),
        ('runner_SHA256', HERE / 'band_runner.py'), ('接続検査SHA256', HERE / 'engine_connection_audit.py'),
        ('注文器SHA256', HERE.parent / 'wave_v33/engine_dynamic_atr.py'),
        ('独立会計SHA256', HERE.parent / 'wave_v35/accounting_reconstruction_vectorized.py')):
        check(path, synthetic[field])
    accounting = load(HERE / 'band_accounting_fixed.json')
    assert accounting['主条件数'] == 364 and accounting['補助条件数'] == 65 and accounting['全入力数'] == 26
    assert accounting['原本切断比率'] == .37 and accounting['成績選別'] is False
    for field in ('全条件会計', '全条件未来変更', '全条件買売反射'):
        assert accounting[field] is True
    references(accounting, 'SHA256')
    assert 'work/wave_v36/band_accounting_audit.py' in accounting['SHA256']
    statistics_test = load(HERE / 'band_statistics_selftest.json')
    assert statistics_test['全人工合格'] is True and statistics_test['新損益使用'] is False
    assert statistics_test['入力数'] == 12 and statistics_test['期間数'] == 2 and statistics_test['破損拒否数'] == 490
    references(statistics_test, 'SHA256')
    for name in ('band_independent_statistics.py', 'band_statistics_selftest.py', 'band_statistics_selftest.json'):
        assert (HERE / name).relative_to(ROOT).as_posix() in accounting['SHA256']

    # ----------------------------------------
    # 波の採否値も全429条件で照合する計画と、成績で選ばない104図を先に固定する。
    chart_wave = load(HERE / 'chart_wave_fixed.json')
    assert chart_wave['対象'] == ([dict(destination='', spec=s) for s in fixed['conditions']] +
        [dict(destination='supplementary', spec=s) for s in fixed['supplementary_conditions']])
    assert chart_wave['主条件数'] == 364 and chart_wave['補助条件数'] == 65 and chart_wave['全条件数'] == 429
    assert chart_wave['全指定波数'] == 3432 and chart_wave['比較境界数'] == 6864
    assert chart_wave['指定波'] == fixed['指定波'] and chart_wave['期間'] == names
    assert chart_wave['新損益読取'] is False and chart_wave['API取得数'] == 0 and chart_wave['現在保存物使用'] is False
    references(chart_wave)
    methods = ['Q034__V000', 'Q007__V000', 'Q016__V000', 'H019__V000']
    assert list(chart_wave['図示対象']) == methods and chart_wave['全図示数'] == 104
    waves = load(HERE / 'wave_order_fixed.json')
    assert waves['対象'] == [dict(id=item['spec']['id'], destination=item['destination']) for item in chart_wave['対象']]
    assert waves['主条件数'] == 364 and waves['補助条件数'] == 65 and waves['全条件数'] == 429
    assert waves['全指定波数'] == 3432 and waves['比較境界数'] == 6864
    references(waves, 'SHA256')
    assert 'work/wave_v36/wave_order_audit.py' in waves['SHA256']
    chart = load(HERE / 'chart_fixed.json')
    assert chart['手法'] == methods and chart['全図示数'] == 104
    references(chart, 'SHA256')
    assert all('work/wave_v36/' + name in chart['SHA256'] for name in ('chart_report.py', 'chart_data_audit.py', 'chart.js'))

    own = load(HERE / 'run_verified_fixed.json')
    references(own, 'SHA256')
    own_test = load(HERE / 'run_verified_test.json')
    assert own_test['全検査合格'] is True and own_test['検査数'] == len(own_test['検査'])
    assert own_test['検査数'] >= 22 and all(row['一致'] is True for row in own_test['検査'])
    assert own_test['ガード実装SHA256'] == check(Path(__file__))
    assert all(runner.digest(ROOT / name) == sha for name, sha in hashes.items()), '検査中に参照資料が変化'
    return dict(実行可能=True, 全条件数=364, 主条件数=91, 診断条件数=273, 補助条件数=65,
        全入力数=364 * 26, 補助全入力数=65 * 26, 探索固定SHA256=check(HERE / '探索条件の固定.json'),
        全入力実体=content, 信号監査範囲=signal_proof, 個別出来高イベント数=volume_audit['全イベント数'],
        採否人工検査数=42, 注文接続人工経路数=72, API取得数=0, 現在保存物使用=False,
        新損益読取=False, 売買再生=False, 監査日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        ガード固定SHA256=check(HERE / 'run_verified_fixed.json'), SHA256=dict(sorted(hashes.items())))


def freeze() -> dict:
    """機能: 起動ガードと人工拒否試験を、実損益の前に固定する。

    引数: なし。返り値: ガード固定仕様 (dict)。監査対象の採否条件は変更しない。
    """
    paths = [HERE / name for name in ('run_verified.py', 'run_verified_test.py', 'run_verified_test.json')]
    value = dict(主条件数=364, 補助条件数=65, 採否条件変更=False, 新損益読取=False,
        SHA256={path.relative_to(ROOT).as_posix(): runner.digest(path) for path in paths})
    path = HERE / 'run_verified_fixed.json'
    if path.exists() and runner.read(path) != value:
        assert not (HERE / '起動実行の証跡.json').exists(), '実行後の起動条件改訂を拒否'
        assert not list((HERE / 'summaries').glob('*.json')), '損益保存後の起動条件改訂を拒否'
        preserved = runner.read(HERE / '起動ガードの波監査接続前保存.json')
        for item in preserved['旧資料'].values():
            assert runner.digest(HERE / item['保存先']) == item['SHA256']
        assert runner.read(path) == runner.read(HERE / 'run_verified_fixed_波監査接続前.json')
        old_sha = runner.digest(path)
        runner.save(path, value)
        runner.save(HERE / '起動ガードの追加接続.json', dict(
            理由='同じ採否を支える全429波と固定104図の事前監査SHAを追加。売買・採否・対象条件は変更しない。',
            旧固定SHA256=old_sha, 新固定SHA256=runner.digest(path),
            新損益読取=False, 売買再生=False, 採否変更=False, 売買条件変更=False))
    elif path.exists():
        assert runner.read(path) == value
    else:
        runner.save(path, value)
    return value


def main() -> None:
    """機能: 起動前確認だけ、又は全固定主条件と補助条件の連続実行を行う。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--freeze-only', action='store_true')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    freeze()
    if args.freeze_only:
        print('起動ガードだけを固定。売買再生なし。', flush=True)
        return
    value = verify_sources()
    runner.save(HERE / '起動前監査.json', value)
    if args.prepare:
        print('全証跡を確認。新損益再生は行っていません。', flush=True)
        return
    proof = dict(開始日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        起動前監査SHA256=runner.digest(HERE / '起動前監査.json'),
        探索固定SHA256=value['探索固定SHA256'], SHA256=value['SHA256'],
        主終了コード=None, 補助終了コード=None, 全実行完了=False,
        API取得数=0, 現在保存物使用=False)
    path = HERE / '起動実行の証跡.json'
    assert not path.exists(), '既存起動証跡を上書きしない'
    runner.save(path, proof)
    for destination in ('', 'supplementary'):
        command = [sys.executable, '-X', 'utf8', str(HERE / 'band_runner.py'), '--workers', str(args.workers)]
        if destination:
            command.append('--supplementary')
        completed = subprocess.run(command, cwd=ROOT, check=False)
        label = '補助' if destination else '主'
        proof[label + '終了コード'] = completed.returncode
        proof[label + '後固定SHA一致'] = all(runner.digest(ROOT / name) == sha for name, sha in value['SHA256'].items())
        runner.save(path, proof)
        assert completed.returncode == 0 and proof[label + '後固定SHA一致'], label + '再生失敗又は固定後変更'
        result_path = HERE / destination / '主再生の完了.json'
        result = runner.read(result_path)
        count = 65 if destination else 364
        assert result['全条件数'] == count and result['全入力数'] == count * 26 and result['全指定波数'] == count * 8
        assert result['探索固定SHA256'] == value['探索固定SHA256']
        proof[label + '完了資料SHA256'] = runner.digest(result_path)
    proof['終了日時'] = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()
    proof['全実行完了'] = True
    runner.save(path, proof)
    print('主364と補助65の再生完了。前後固定SHA一致。独立監査は別途必要。', flush=True)


if __name__ == '__main__':
    main()
