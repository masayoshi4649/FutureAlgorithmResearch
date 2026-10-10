"""固定した価格帯信号を旧D273注文器へ接続し、全損失・全数量を保存する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / 'wave_v33'))
import atr_runner as base
sys.path.insert(0, str(HERE.parent / 'wave_v35'))
import accounting_reconstruction_vectorized as accounting
sys.path.insert(0, str(HERE))
import band_design as design

INPUTS, FIXED, DIRECTIONS = {}, {}, {}
FIELDS = ('trades', 'cycles', 'curve', 'orders', 'stats', 'atr_curve')
STORED = ('trades', 'cycles', 'orders', 'stats')
SYMBOLS = ('TOPIX', 'NK225')


def digest(path: Path) -> str:
    """機能: ファイル内容をSHA256で固定する。

    引数: path (Path)。返り値: 指紋 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> object:
    """機能: 通常又は圧縮JSONの保存内容を読む。

    引数: path (Path)。返り値: JSON内容 (object)。
    """
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def save(path: Path, value: object) -> None:
    """機能: 非有限数を拒否し、内容が同じなら同じ圧縮結果で保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(gzip.compress(payload, mtime=0) if path.suffix == '.gz' else payload)
    temporary.replace(path)


def reject_network(*args: object, **kwargs: object) -> None:
    """機能: 保存データの再生中に外部通信を禁止する。

    引数: args/kwargs (object)。返り値: なし (None)。常に例外を送出する。
    """
    raise RuntimeError('保存データの再生から外部取得は行いません')


def initialize() -> None:
    """機能: 各子処理へ固定原本と条件を読み、方向キャッシュを初期化する。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, FIXED
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    INPUTS = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    FIXED = read(HERE / '探索条件の固定.json')
    DIRECTIONS.clear()
    assert len(INPUTS) == 26 and len(FIXED['conditions']) == 364


def direction(spec: dict, key: tuple) -> np.ndarray:
    """機能: 結果前に生成・監査した原本行対応の方向を返す。

    引数: spec (dict)、key (tuple[str,str])。返り値: 方向列 (ndarray[int8])。
    """
    label = spec['signal_id'] + f"__C{round(spec['clock_scale'] * 100):03d}"
    if label not in DIRECTIONS:
        with np.load(HERE / 'directions' / (label + '.npz'), allow_pickle=False) as archive:
            DIRECTIONS[label] = {name: archive[name] for name in archive.files}
    values = DIRECTIONS[label]['|'.join(key)]
    assert values.dtype == np.int8 and len(values) == len(INPUTS[key]['last'])
    assert np.isin(values, (-1, 0, 1)).all()
    if 'random_seed' in spec:
        ready = INPUTS[key]
        blocks, inverse = np.unique(np.floor((ready['time_s'] - ready['start']) / 1800.).astype(np.int64), return_inverse=True)
        signs = []
        for block in blocks:
            payload = f"v36|{spec['random_seed']}|{key[0]}|{int(block)}".encode('utf-8')
            bit = int.from_bytes(hashlib.sha256(payload).digest()[:8], 'little') & 1
            signs.append(1 if bit == 0 else -1)
        output = values * np.asarray(signs, dtype=np.int8)[inverse]
        assert np.array_equal(values == 0, output == 0)
        return output
    if spec.get('reverse_direction', False):
        return -values
    return values


def fingerprints(result: dict) -> dict:
    """機能: 全6配列の形状と内容を保存台帳へ結ぶ。

    引数: result (dict)。返り値: 指紋一覧 (dict)。
    """
    return {name: dict(shape=list(result[name].shape), SHA256=hashlib.sha256(result[name].tobytes()).hexdigest())
        for name in FIELDS}


def period(rows: list[dict], sessions: list[str]) -> dict:
    """機能: 銘柄別の期間成績を集計する。銘柄間の円額は足さない。

    引数: rows (list[dict])、sessions (list[str])。返り値: 銘柄別集計 (dict)。
    """
    output = {}
    for symbol in SYMBOLS:
        part = [r for r in rows if r['symbol'] == symbol and r['session'] in sessions]
        value = base.research.aggregate(part)
        for name in ('long_unit_minutes', 'short_unit_minutes', 'opening_orders'):
            value[name] = sum(r[name] for r in part)
        value['retracement'] = base.retracement_totals([r for item in part for r in item['retracements']])
        output[symbol] = value
    return output


def evaluate(spec: dict, destination: str = '') -> dict:
    """機能: 一条件の全26入力を再生し、別会計で全行の時価・全数量を照合する。

    引数: spec (dict)、destination (str) は空又はsupplementary。返り値: 期間成績 (dict)。
    """
    identifier, started = spec['id'], time.perf_counter()
    assert destination in ('', 'supplementary')
    rows, ledgers, waves, checks = [], [], [], []
    ledger_hash = hashlib.sha256()
    baseline = spec['signal_id'] == 'H019'
    prior = read(HERE.parent / 'wave_v35/ledgers' / f'H019__A0__{spec["variant_id"]}.json.gz') if baseline else []
    for key, ready in sorted(INPUTS.items()):
        state = direction(spec, key)
        config = base.managers.make_config(FIXED['manager'], key[1], ready)
        result = base.engine.run(ready, state, config, detail=True, width_mode=0,
            observed_fill=spec['observed_fill'])
        row = base.research.summarize(result, config, key[1], key[0], identifier)
        independent, curves = accounting.reconstruct(ready, result, key[1])
        for field in independent.keys() & row.keys():
            if isinstance(independent[field], (int, float)):
                assert abs(independent[field] - row[field]) <= 1e-6, (identifier, key, field)
        if baseline:
            expected = next(r for r in prior if (r['session'], r['symbol']) == key)
            for field in STORED:
                assert result[field].tolist() == expected[field], ('旧H019固定A0不一致', key, field)
            assert hashlib.sha256(result['curve'].tobytes()).hexdigest() == expected['result_fingerprints']['curve']['SHA256']
        row['two_largest_cycle_profits'] = sorted(
            [float(v) * config['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2]
        durations = np.diff(ready['time_s'], append=ready['time_s'][-1]) / 60.
        row['long_unit_minutes'] = float(np.sum(curves['long'] * durations))
        row['short_unit_minutes'] = float(np.sum(curves['short'] * durations))
        row['opening_orders'] = int(np.sum(result['orders'][:, 7] == 1))
        row['retracements'] = base.retracements(result, ready, config['point_value'])
        rows.append(row)
        ledger_hash.update(str(key).encode('utf-8'))
        ledger_hash.update(result['trades'].tobytes())
        ledgers.append(dict(session=key[0], symbol=key[1], config=config,
            **{field: result[field].tolist() for field in STORED}, result_fingerprints=fingerprints(result)))
        checks.append(dict(session=key[0], symbol=key[1], **{k: v for k, v in independent.items() if k not in ('symbol', 'session')},
            全行会計一致=True, 旧固定一致=baseline,
            独立時価SHA256=hashlib.sha256(curves['equity'].tobytes()).hexdigest()))
        for wave in FIXED['指定波']:
            if wave['session'] == key[0]:
                orders = base.wave_metrics.order_records(ready, state, result, base.engine.REASONS)
                waves.append(base.wave_metrics.episode_metrics(dict(id=identifier, manager=FIXED['manager']),
                    wave, ready, state, result, orders, config['point_value']))
    assert len(rows) == len(ledgers) == len(checks) == 26 and len(waves) == 8
    value = dict(id=identifier, spec=spec, all_symbols=period(rows, FIXED['全セッション']),
        symbols=period(rows, FIXED['後半7セッション']), ledger_hash=ledger_hash.hexdigest(),
        wave_passes=sum(r['正方向ネット20分目安達成'] for r in waves), 旧固定一致=baseline,
        全26全行独立会計一致=True, 経過秒=time.perf_counter() - started,
        探索固定SHA256=digest(HERE / '探索条件の固定.json'))
    for folder, payload, suffix in (('sessions', rows, '.json.gz'), ('ledgers', ledgers, '.json.gz'),
        ('waves', waves, '.json.gz'), ('accounting', checks, '.json.gz'), ('summaries', value, '.json')):
        save(HERE / destination / folder / (identifier + suffix), payload)
    return value


def runtime_files() -> set[Path]:
    """機能: 読込済みの研究コードと明示した直接依存を固定対象へ集める。

    引数: なし。返り値: ワークスペース内のファイル集合 (set[Path])。
    """
    paths = {Path(__file__).resolve(), HERE / 'band_design.py', HERE / 'band_signals.py',
        HERE / '価格帯の方向判定設計.md', HERE / 'band_assessment.py', HERE / 'band_assessment_fixed.json',
        HERE / 'band_runner_synthetic.json', HERE / 'band_runner_synthetic.py', HERE / '入力固定.json',
        HERE / 'engine_connection_audit.py', HERE / 'build_band_inputs.py',
        HERE.parent / 'wave_v23/inputs.pkl', HERE.parent / 'wave_v23/features_depth.pkl',
        HERE.parent / 'wave_v35/探索条件の固定.json'}
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.is_relative_to(ROOT / 'work') and path.suffix == '.py':
                paths.add(path)
    return paths


def prepare() -> dict:
    """機能: 全条件・監査済み入力・実装を新しい損益の前に固定する。

    引数: なし。返り値: 固定記録 (dict)。固定後の差は拒否する。
    """
    path = HERE / '探索条件の固定.json'
    conditions = design.conditions()
    if path.exists():
        value = read(path)
        assert value['conditions'] == conditions
        assert value['supplementary_conditions'] == design.supplementary_conditions()
        for relative, fingerprint in value['SHA256'].items():
            assert digest(ROOT / relative) == fingerprint, '固定後変更: ' + relative
        return value
    material = read(HERE / '入力固定.json')
    assert material['全入力監査合格'] and material['方向ファイル数'] == 273
    paths = runtime_files()
    for relative in material['SHA256']:
        paths.add(ROOT / relative)
    originals = read(HERE.parent / 'wave_v35/input_causality_before_pnl.json')['原本78SHA256']
    for relative, fingerprint in originals.items():
        assert digest(ROOT / relative) == fingerprint
        paths.add(ROOT / relative)
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    sessions = sorted({key[0] for key in inputs})
    manager = read(HERE.parent / 'wave_v35/探索条件の固定.json')['manager']
    assert len(inputs) == 26 and len(sessions) == 13
    value = dict(固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), conditions=conditions,
        supplementary_conditions=design.supplementary_conditions(), 補助条件数=65,
        manager=manager, 主仮説=design.PRIMARY_SIGNAL + '__V000', 主条件数=91, 診断条件数=273, 全条件数=364,
        全セッション=sessions, 後半7セッション=sessions[6:], 指定波=list(base.wave_metrics.EPISODES),
        新方式の選択='Q034固定。各価格準備の先着反応による機械分岐。成績で主仮説を変更しない。',
        データ='全13既知。後半も真の未見ではない。現在API・保存ライブ不使用。',
        SHA256={p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)})
    save(path, value)
    return value


def main() -> None:
    """機能: 結果前監査の固定を確認して主91＋診断273を再生する。

    引数: --prepare/--supplementary (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--supplementary', action='store_true')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    fixed = prepare()
    if args.prepare:
        print('全364条件を固定。新しい売買再生なし。', flush=True)
        return
    startup = read(HERE / '起動前監査.json')
    assert startup['実行可能'] and startup['探索固定SHA256'] == digest(HERE / '探索条件の固定.json')
    for relative, fingerprint in startup['SHA256'].items():
        assert digest(ROOT / relative) == fingerprint
    specs = fixed['supplementary_conditions'] if args.supplementary else fixed['conditions']
    destination = 'supplementary' if args.supplementary else ''
    if args.supplementary:
        assert read(HERE / '主再生の完了.json')['全条件数'] == 364
    started, results = time.perf_counter(), []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(evaluate, spec, destination): spec['id'] for spec in specs}
        for future in as_completed(futures):
            value = future.result()
            results.append(value)
            print(f"{len(results)}/{len(specs)} {value['id']} 全行会計一致", flush=True)
    assert {r['id'] for r in results} == {r['id'] for r in specs}
    assert len(results) == len(specs)
    prepare()
    save(HERE / destination / '全条件の期間集計.json.gz', sorted(results, key=lambda r: r['id']))
    save(HERE / destination / '主再生の完了.json', dict(全条件数=len(specs), 全入力数=len(specs) * 26, 全指定波数=len(specs) * 8,
        主仮説=fixed['主仮説'], 全行独立会計=True, 旧H019全4変形一致=not args.supplementary,
        経過秒=time.perf_counter() - started, API取得数=0, 現在保存物使用=False,
        探索固定SHA256=digest(HERE / '探索条件の固定.json')))


if __name__ == '__main__':
    main()
