"""保存済みの追加セッションへ、既存レポートの四方式を条件不変で適用する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V47 = ROOT / 'work/wave_v47'
sys.path.insert(0, str(V47))
import integrated_followup as followup
import new_report as charts
import check_component_signals as checks

replay, integration = followup.replay, followup.integration
IDS = ('F50_NONE__E11', 'F50_NONE__E10', 'C01__E10', 'A0__E10')
SYMBOLS = ('TOPIX', 'NK225')


def sha(path: Path) -> str:
    """機能: 読取対象の内容指紋を得る。

    引数: path(Path)。返り値: SHA256(str)。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8388608):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> object:
    """機能: 通常又は圧縮された検証資料を読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    content = path.read_bytes()
    return json.loads(gzip.decompress(content) if path.suffix == '.gz' else content)


def save(path: Path, value: object) -> None:
    """機能: 追加作業の領域だけへ有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)
    temporary.replace(path)


def deny(*args: object, **kwargs: object) -> None:
    """機能: 再生中のネットワーク接続を拒否する。

    引数: 任意の引数(object)。返り値: なし(None)、常に例外。
    """
    raise RuntimeError('保存原本だけを使用し、APIの追加取得は行いません')


def module(name: str, path: Path) -> object:
    """機能: 旧実装を改変せず別名で読み込む。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def fingerprints(paths: list[Path]) -> dict:
    """機能: 独立した読取資料を並列に指紋化する。

    引数: paths(list[Path])。返り値: 相対パスと指紋(dict)。
    """
    unique = sorted(set(paths))
    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(zip((p.relative_to(ROOT).as_posix() for p in unique), pool.map(sha, unique)))


def verify(mapping: dict) -> None:
    """機能: 原本及び固定実装が変化していないことを確認する。

    引数: mapping(dict[str,str])。返り値: なし(None)。
    """
    actual = fingerprints([ROOT / name for name in mapping])
    assert actual == mapping, [name for name in mapping if actual[name] != mapping[name]]


def freeze(session: str) -> dict:
    """機能: 損益を読む前に追加対象・既存条件・原本・実装を固定する。

    引数: session(str)。返り値: 固定証跡(dict)。
    """
    selected = {s['id']: s for s in followup.catalog('new')}
    specs = [deepcopy(selected[name]) for name in IDS]
    old = read(V47 / '追加ナイト照合の固定.json')['原本SHA256']
    verify(old)
    target = HERE / '固定.json'
    if target.exists():
        prior_names = read(target)['既存追加フォルダ']
    else:
        prior_names = [name for name in read(HERE.parent / '追加結果一覧.json') if name != HERE.name]
    assert prior_names == ['update_20260930'], prior_names
    prior_paths = []
    for name in prior_names:
        folder = HERE.parent / name
        prior_fixed = read(folder / '固定.json')
        assert prior_fixed['対象'] != session and prior_fixed['条件'] == specs
        verify(prior_fixed['原本SHA256'])
        for relative, digest in prior_fixed['原本SHA256'].items():
            assert relative not in old or old[relative] == digest
            old[relative] = digest
        completion = read(folder / 'complete.json')
        assert completion['全合格'] and not completion['条件変更']
        verify(completion['出力SHA256'])
        prior_paths += [folder / '固定.json', folder / 'complete.json', folder / 'new_inputs.pkl']
        prior_paths += [ROOT / relative for relative in completion['出力SHA256']]
    new_paths = [ROOT / folder / symbol / (session + suffix)
                 for folder, suffix in (('book', '.jsonl'), ('candle_1min', '.csv'), ('candle_5min', '.csv'))
                 for symbol in SYMBOLS]
    assert all(p.exists() for p in new_paths)
    assert not any(p.relative_to(ROOT).as_posix() in old for p in new_paths)
    dependencies = read(V47 / '統合追試の固定.json')['参照SHA256']
    verify(dependencies)
    sources = [Path(__file__)]
    for value in tuple(sys.modules.values()):
        name = getattr(value, '__file__', None)
        if name:
            p = Path(name).resolve()
            if p.suffix == '.py' and p.is_relative_to(ROOT / 'work'):
                sources.append(p)
    fixed = dict(対象=session, 条件=specs, 条件変更=False, 旧原本不変=True,
                 原本SHA256=old | fingerprints(new_paths), 既存固定参照SHA256=dependencies,
                 既存追加フォルダ=prior_names, 既存追加参照SHA256=fingerprints(prior_paths),
                 実装SHA256=fingerprints(sources), API追加取得数=0,
                 枚数={'TOPIX': dict(初回=5, 片方向上限=10, 円倍率=1000),
                     'NK225': dict(初回=10, 片方向上限=20, 円倍率=10)})
    if target.exists():
        assert read(target) == fixed
    else:
        save(target, fixed)
    return fixed


def extract(session: str) -> tuple[dict, dict]:
    """機能: 生板・足から旧抽出器と同じ順序で追加二入力を生成する。

    引数: session(str)。返り値: 入力と板特徴(tuple[dict,dict])。
    """
    frame_map, audits = {}, []
    for symbol in SYMBOLS:
        reference = module('v48_data_' + symbol, ROOT / 'work/wave_v16/reference.py')
        extractor = module('v48_raw_' + symbol, ROOT / 'work/wave_v8/raw_features.py')
        depth = module('v48_depth_' + symbol, ROOT / 'work/wave_v23/depth_features.py')
        path = ROOT / 'book' / symbol / (session + '.jsonl')
        quotes = []
        frame, extraction = extractor.extract_features(path, symbol, session, quotes=quotes)
        extractor.write_features(frame, extraction, HERE / 'features', quotes=quotes)
        raw_audit, raw = reference.previous.data.scan_book(path, collect_prices=True)
        tape_path = HERE / 'features' / f'約定系列_{symbol}_{session}.npz'
        with np.load(tape_path, allow_pickle=False) as stored:
            tape = dict(stored)
        indices = tape['seq'].astype(int)
        tape['last'], tape['volume'] = raw['last'][indices], raw['volume'][indices]
        tape['current_price'] = tape['last'].copy()
        np.savez_compressed(tape_path, **tape)
        features, depth_audit = depth.extract(path, symbol, session, frame)
        frame_map[session, symbol] = features
        audits.append(dict(symbol=symbol, 原本=raw_audit, 抽出=extraction, 追加板特徴=depth_audit,
                           足一致=reference.previous.data.candle_consistency(session, symbol, raw),
                           実売買系列SHA256=sha(tape_path)))
        print(symbol + ' 原本から入力素材を抽出', flush=True)
    reference = module('v48_prepared', ROOT / 'work/wave_v16/reference.py')
    reference.previous.OUT = HERE
    inputs = reference.previous.build_inputs([session], roots={session: (ROOT, HERE / 'features')})
    coverage = []
    for key, ready in inputs.items():
        assert ready['time_s'][-1] > ready['limit']
        assert np.all(np.diff(ready['seq']) > 0) and np.all(np.diff(ready['time_s']) >= 0)
        with np.load(HERE / 'features' / f'約定系列_{key[1]}_{session}.npz') as tape:
            np.testing.assert_array_equal(tape['last'], ready['last'])
            np.testing.assert_array_equal(tape['seq'], ready['seq'])
        coverage.append(dict(session=key[0], symbol=key[1], 原本行数=len(ready['seq']),
                             最終時刻=float(ready['time_s'][-1]), 場内返済期限=float(ready['limit'])))
    for name, value in (('new_inputs.pkl', inputs), ('new_features_depth.pkl', frame_map)):
        (HERE / name).write_bytes(pickle.dumps(value, pickle.HIGHEST_PROTOCOL))
    save(HERE / '入力監査.json', dict(全合格=True, 対象=session, 入力被覆=coverage, 原本監査=audits,
        出力SHA256=fingerprints([HERE / 'new_inputs.pkl', HERE / 'new_features_depth.pkl']), API追加取得数=0))
    return inputs, frame_map


def candle_copy(keys: list, label: str, cutoff: float | None, pivots: dict | None) -> Path:
    """機能: 因果検査用の確定足コピーだけを変形する。

    引数: keys(list)、label(str)、cutoff(float|None)、pivots(dict|None)。返り値: 参照根(Path)。
    """
    output = HERE / 'audit_candles' / label
    for key in keys:
        frame = pd.read_csv(ROOT / 'candle_1min' / key[1] / (key[0] + '.csv'))
        if cutoff is not None:
            release = pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy(float) / 1e9 + 120
            mask = release >= cutoff
            for col in ('open', 'high', 'low', 'close', 'volume'):
                frame[col] = frame[col].astype(float)
                frame.loc[mask, col] = frame.loc[mask, col] * 1.7 + 7000
            frame.loc[mask, 'closed'] = True
            if 'volume_complete' in frame:
                frame.loc[mask, 'volume_complete'] = True
        if pivots is not None:
            pivot, high, low = pivots[key], frame.high.copy(), frame.low.copy()
            for col in ('open', 'close'):
                frame[col] = 2 * pivot - frame[col]
            frame['high'], frame['low'] = 2 * pivot - low, 2 * pivot - high
        target = output / 'candle_1min' / key[1] / (key[0] + '.csv')
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(target, index=False, encoding='utf-8')
    return output


def signals(inputs: dict, features: dict, root: Path) -> dict:
    """機能: 入口及び途中判断を原素材から生成する。

    引数: inputs/features(dict)、root(Path)。返り値: 信号辞書(dict)。
    """
    replay.entry.set_root(root)
    replay.mid.clear_cache()
    result = {'entry': replay.entry.build(replay.entry.specification(), inputs, features)}
    for code in ('B00', 'B01'):
        condition = next(s for s in replay.mid.catalog() if s['id'] == code)
        result[code] = replay.mid.build(condition, inputs, features)
    return result


def signal_audit(inputs: dict, features: dict) -> dict:
    """機能: 素材の切断・未来改変・反射・同秒順で信号を再生成する。

    引数: inputs/features(dict)。返り値: 元信号(dict)。
    """
    base = signals(inputs, features, ROOT)
    start = max(r['start'] for r in inputs.values())
    end = min(r['time_s'][-1] for r in inputs.values())
    cut, future_cut = start + (end - start) * .37, start + (end - start) * .73
    counts = {k: int(np.searchsorted(r['time_s'], cut, side='left')) for k, r in inputs.items()}
    clipped, cf = checks.slice_inputs(inputs, features, counts)
    partial = signals(clipped, cf, ROOT)
    changed, ff, _ = checks.transformed(inputs, features, future_cut)
    future = signals(changed, ff, candle_copy(list(inputs), 'future', future_cut, None))
    reflected, rf, pivots = checks.transformed(inputs, features, None)
    mirror = signals(reflected, rf, candle_copy(list(inputs), 'reflection', None, pivots))
    records = []
    for key, ready in inputs.items():
        n = len(ready['last'])
        fc = int(np.searchsorted(ready['time_s'], future_cut, side='left'))
        repeated = np.flatnonzero(np.diff(ready['time_s']) == 0) + 1
        tied = int(repeated[np.argmin(abs(repeated - int(n * .73)))])
        keep = {k: len(r['last']) for k, r in inputs.items()}
        keep[key] = tied
        clipped, cf = checks.slice_inputs(inputs, features, keep)
        same = signals(clipped, cf, ROOT)
        for alternate, count, reflected_flag in ((partial, counts[key], False), (future, fc, False),
                                                 (mirror, n, True), (same, tied, False)):
            np.testing.assert_array_equal(base['entry'][key][:count] * (-1 if reflected_flag else 1),
                                          alternate['entry'][key][:count])
            for code in ('B00', 'B01'):
                for name in ('direction', 'source_row', 'source_event_index'):
                    a = base[code][key][name][:count]
                    if reflected_flag and name == 'direction':
                        a = -a
                    np.testing.assert_array_equal(a, alternate[code][key][name][:count])
                np.testing.assert_array_equal(replay.valid_column(base[code][key])[:count],
                                              replay.valid_column(alternate[code][key])[:count])
        records.append(dict(session=key[0], symbol=key[1], 信号数=3, 切断一致=True,
                            未来変更一致=True, 上下反射一致=True, 同秒順一致=True))
    replay.entry.set_root(ROOT)
    save(HERE / '信号監査.json', dict(全合格=True, 検査=records, API追加取得数=0))
    return base


def reproduce(fixed: dict, inputs: dict, features: dict) -> None:
    """機能: 旧ナイトを完全再現してから追加場を四方式で再生する。

    引数: fixed/inputs/features(dict)。返り値: なし(None)。
    """
    integration.reference.initialize()
    new_signals = signal_audit(inputs, features)
    prior_inputs = pickle.loads((V47 / 'new_inputs.pkl').read_bytes())
    prior_features = pickle.loads((V47 / 'new_features_depth.pkl').read_bytes())
    old_signals = signals(prior_inputs, prior_features, ROOT)
    followup.INPUTS = prior_inputs | inputs
    replay.MID = {code: old_signals[code] | new_signals[code] for code in new_signals}
    for spec in fixed['条件']:
        identifier = spec['id']
        stored = read(V47 / 'integration_followup/new/ledgers' / (identifier + '.json.gz'))
        stored = {(r['session'], r['symbol']): r for r in stored}
        calibration = []
        for key in sorted(prior_inputs):
            columns, valid = replay.new_columns(spec, key)
            _, ledger, _, _ = followup.inspect_case(spec, key, columns, valid, False)
            for field in ('result_fingerprints', 'shadow_fingerprints', 'scheduler_fingerprints'):
                assert ledger[field] == stored[key][field], (identifier, key, field)
            calibration.append(dict(session=key[0], symbol=key[1], 全実口座指紋一致=True, 両仮想運転指紋一致=True))
        rows, ledgers, proofs = [], [], []
        for key in sorted(inputs):
            columns, valid = replay.new_columns(spec, key)
            row, ledger, proof, curve = followup.inspect_case(spec, key, columns, valid, True)
            symbol = key[1]
            config = ledger['config']
            expected = fixed['枚数'][symbol]
            assert config['initial_qty'] == expected['初回']
            assert config['audit_cap'] == expected['片方向上限']
            assert config['point_value'] == expected['円倍率']
            rows.append(row)
            ledgers.append(ledger)
            proofs.append(proof)
            target = HERE / 'curves' / (identifier + '_' + symbol + '.npz')
            target.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(target, equity=curve)
        for folder, value in (('sessions', rows), ('ledgers', ledgers), ('audits', proofs)):
            save(HERE / folder / (identifier + '.json.gz'), value)
        save(HERE / 'completed' / (identifier + '.json'), dict(id=identifier, 全合格=True,
            旧再現照合=calibration, 新監査数=2, 新因果監査数=2, 条件変更=False))
        print(identifier + ' 旧2口座再現・新2口座再生検算完了', flush=True)


def assessment(inputs: dict, fixed: dict) -> None:
    """機能: 旧十五場と追加場を実注文から再構築して期間統計を得る。

    引数: inputs(dict)、fixed(dict)。返り値: なし(None)。
    """
    old_inputs = pickle.loads((V47 / 'inputs.pkl').read_bytes())
    prior_inputs = dict(old_inputs)
    prior_folders = [HERE.parent / name for name in fixed['既存追加フォルダ']]
    for folder in prior_folders:
        addition = pickle.loads((folder / 'new_inputs.pkl').read_bytes())
        assert not (set(prior_inputs) & set(addition))
        prior_inputs.update(addition)
    assert not (set(prior_inputs) & set(inputs))
    combined = prior_inputs | inputs
    previous = read(V47 / 'integrated_assessment.json')['全14期間']
    previous15 = read(prior_folders[-1] / 'assessment.json')
    output = {}
    for identifier in IDS:
        rows, ledgers = [], []
        for folder in (V47 / 'exit_integration', V47 / 'integration_followup/new', *prior_folders, HERE):
            rows += read(folder / 'sessions' / (identifier + '.json.gz'))
            ledgers += read(folder / 'ledgers' / (identifier + '.json.gz'))
        assert len(rows) == len(ledgers) == len(combined) == 32
        series = {}
        by_key = {(r['session'], r['symbol']): r for r in rows}
        assert len(by_key) == len(rows)
        for ledger in ledgers:
            key = ledger['session'], ledger['symbol']
            curve, totals = charts.chart.reconstruct(combined[key], ledger)
            for field, value in totals.items():
                assert abs(by_key[key][field] - value) < 1e-6, (identifier, key, field)
            series[key] = curve[:, 0]
        names = sorted({r['session'] for r in rows})
        old_names = sorted({k[0] for k in old_inputs})
        old_rows = [r for r in rows if r['session'] in old_names]
        prior_names = sorted({k[0] for k in prior_inputs})
        prior_rows = [r for r in rows if r['session'] in prior_names]
        output[identifier] = {}
        for symbol in SYMBOLS:
            multiplier = replay.previous.old.base.research.MULT[symbol]
            old_period = replay.previous.audit.statistics.period(old_rows, series, old_names, symbol, multiplier)
            replay.previous.audit.statistics.equal(old_period, previous[identifier][symbol], '旧十四場統計不変')
            prior_period = replay.previous.audit.statistics.period(prior_rows, series, prior_names, symbol, multiplier)
            replay.previous.audit.statistics.equal(prior_period, previous15[identifier][symbol], '旧十五場統計不変')
            output[identifier][symbol] = replay.previous.audit.statistics.period(rows, series, names, symbol, multiplier)
    save(HERE / 'assessment.json', output)


def main() -> None:
    """機能: 新セッション入力生成、固定再生、期間集計と不変検査を順次行う。

    引数: session(str)、stage(str)はコマンドライン指定。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', default='2026-09-30_Night')
    parser.add_argument('--stage', choices=('all', 'prepare', 'replay'), default='all')
    args = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    fixed = freeze(args.session)
    if args.stage in ('all', 'prepare'):
        inputs, features = extract(args.session)
    else:
        proof = read(HERE / '入力監査.json')
        assert proof['全合格'] and proof['対象'] == args.session
        verify(proof['出力SHA256'])
        inputs = pickle.loads((HERE / 'new_inputs.pkl').read_bytes())
        features = pickle.loads((HERE / 'new_features_depth.pkl').read_bytes())
    if args.stage in ('all', 'replay'):
        reproduce(fixed, inputs, features)
        assessment(inputs, fixed)
    for field in ('原本SHA256', '既存固定参照SHA256', '既存追加参照SHA256', '実装SHA256'):
        verify(fixed[field])
    if args.stage in ('all', 'replay'):
        files = [HERE / 'assessment.json', HERE / '入力監査.json', HERE / '信号監査.json']
        files += [HERE / folder / (identifier + suffix) for identifier in IDS
                  for folder, suffix in (('sessions', '.json.gz'), ('ledgers', '.json.gz'),
                                         ('audits', '.json.gz'), ('completed', '.json'))]
        save(HERE / 'complete.json', dict(全合格=True, 対象=args.session, 条件数=4, 新口座数=8,
            旧再現口座数=8, 全期間場数=16, 旧十五場全統計一致=True, 条件変更=False, API追加取得数=0,
            固定SHA256=sha(HERE / '固定.json'), 出力SHA256=fingerprints(files), 原本実装不変=True))
        print('追加四方式・八口座及び全十六場集計の全検算完了', flush=True)


if __name__ == '__main__':
    main()
