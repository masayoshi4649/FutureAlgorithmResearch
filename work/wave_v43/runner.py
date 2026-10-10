"""旧注文器と独立会計を保持し、時間窓合議の固定条件を再生する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from copy import deepcopy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent/'wave_v41'))
import replay_state_fix as reference
audit, old, engine = reference.audit, reference.runner, reference.corrected
sys.path.insert(0, str(HERE.parent/'wave_v38'))
import adaptive_causality_audit as causal


def module(name: str, path: Path) -> object:
    """機能: 同名の旧モジュールを置換せず今回の実装を読む。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    assert Path(value.__file__).resolve() == path.resolve()
    return value


design = module('window_comparison_design', HERE/'design.py')
INPUTS, FIXED, ENTRIES = {}, {}, {}
FIELDS, STORED = old.FIELDS, old.STORED
PROOF_FLAGS = reference.PROOF_FLAGS
REPRESENTATIVE = ('2026-09-24_Night', '2026-09-29_Day')


def digest(path: Path) -> str:
    """機能: 巨大入力も逐次読取で指紋化する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return reference.digest(path)


def read(path: Path) -> object:
    """機能: 通常又は圧縮JSONを読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return reference.read(path)


def save(path: Path, value: object) -> None:
    """機能: 今回の領域内へ有限JSONを原子的に保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)
    temporary.replace(path)


def verify(files: dict) -> None:
    """機能: 全参照資料を固定指紋と照合する。

    引数: files(dict[str,str])。返り値: なし(None)。不一致は停止する。
    """
    def check(item: tuple) -> None:
        """機能: 一つの相対パスとSHAを照合する。

        引数: item(tuple[str,str])。返り値: なし(None)。
        """
        name, expected = item
        path = (ROOT/name).resolve()
        assert path.is_relative_to(ROOT) and digest(path) == expected, name
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(check, files.items()))


def initialize() -> None:
    """機能: 旧凍結入力と今回の入口列を準備する。外部通信は旧初期化で拒否する。

    引数: なし。返り値: なし(None)。
    """
    global INPUTS, FIXED, ENTRIES
    audit.initialize()
    INPUTS = old.INPUTS
    FIXED = read(HERE/'探索条件の固定.json')
    ENTRIES = {}
    for name in design.SIGNALS:
        with np.load(HERE/'entries'/(name+'.npz'), allow_pickle=False) as archive:
            columns = {tuple(key.split('|')): archive[key] for key in archive.files}
        assert set(columns) == set(INPUTS)
        for key, values in columns.items():
            assert values.dtype == np.int8 and values.shape == INPUTS[key]['seq'].shape
            assert np.isin(values, (-1, 0, 1)).all()
            values.flags.writeable = False
        ENTRIES[name] = columns
    assert Path(engine.__file__).resolve() == HERE.parent/'wave_v41/engine_partial_restore_corrected.py'
    assert Path(audit.__file__).resolve() == HERE.parent/'wave_v38/adaptive_accounting_audit.py'


def columns_for(spec: dict, key: tuple) -> tuple:
    """機能: 入口だけを今回の合議へ変更し、出口の板列を旧仕様で読む。

    引数: spec(dict)、key(tuple[str,str])。返り値: 入口・板根拠・公開品質の10列(tuple)。
    """
    original = dict(spec, signal_id='H019', entry_scale=1.)
    return (ENTRIES[spec['window_id']][key], *old.columns(original, key)[1:])


def play(spec: dict, ready: dict, columns: tuple, config: dict) -> dict:
    """機能: 入口ごとに影注文を新規生成し、修正版の実口座へ接続する。

    引数: spec/ready/config(dict)、columns(tuple)。返り値: 全約定と全行状態(dict)。
    """
    shadow = engine.make_shadow(ready, columns[0], config, spec['observed_fill'], spec['min_delay_seconds'])
    result = reference.play(engine, spec, ready, columns, config, shadow)
    assert shadow['input_sha256'] == engine.input_digest(ready, columns[0], config,
                                                       spec['observed_fill'], spec['min_delay_seconds'])
    return result


def causal_check(spec: dict, ready: dict, columns: tuple, config: dict, actual: dict) -> dict:
    """機能: 入口監査とは別に、合成済み注文口座の先頭切断と未来改変を検査する。

    引数: spec/ready/config/actual(dict)、columns(tuple)。返り値: 証跡(dict)。
    入力列自体の未来非依存は独立したsignal_auditへ接続する。
    """
    n = len(ready['last'])
    cut = max(2, int(n*.37))
    short = play(spec, causal.clipped(ready, cut), tuple(v[:cut].copy() for v in columns), config)
    causal.prefix(actual, short, cut)
    del short
    repeated = np.flatnonzero(np.diff(ready['time_s']) == 0)+1
    change = int(repeated[np.argmin(abs(repeated-int(n*.73)))]) if len(repeated) else int(n*.73)
    future = causal.clipped(ready, n)
    future['last'][change:] += ready['tick']*37
    future['atr'][change:] *= 3
    altered = tuple(v.copy() for v in columns)
    for index in (0, 1, 3, 6):
        altered[index][change:] *= -1
    result = play(spec, future, altered, config)
    causal.prefix(actual, result, change)
    return dict(先頭切断一致=True, 未来変更一致=True, 切断行=cut, 未来変更行=change)


def legacy_id(spec: dict) -> str | None:
    """機能: 単一窓の旧条件との対応を返す。

    引数: spec(dict)。返り値: 旧ID又は該当なし(str|None)。
    """
    if spec['window_id'] not in ('S080', 'S100', 'S120'):
        return None
    variant = {'S080':'E080', 'S100':'V000', 'S120':'E120'}[spec['window_id']]
    return f"H019__{spec['prior_manager']}__R1__{variant}"


def evaluate(spec: dict) -> dict:
    """機能: 一条件の26入力を全行会計へ通し、期間集計と元単一窓同値を保存する。

    引数: spec(dict)。返り値: 条件完了記録(dict)。
    """
    identifier, started = spec['id'], time.perf_counter()
    rows, series, ledgers, proofs, waves, causality = [], {}, [], [], [], []
    prior_id = legacy_id(spec)
    prior = {(r['session'],r['symbol']):r for r in read(HERE.parent/'wave_v38/ledgers'/(prior_id+'.json.gz'))} if prior_id else {}
    signal_use = []
    for key, ready in sorted(INPUTS.items()):
        columns = columns_for(spec, key)
        config = old.base.managers.make_config(old.FIXED['manager'], key[1], ready)
        result = play(spec, ready, columns, config)
        row, curves, proof, basic = audit.inspect(spec, ready, result, config, columns)
        for flag in PROOF_FLAGS:
            assert proof[flag] is True, (identifier, key, flag)
        assert proof['原本行数'] == len(ready['last'])
        other_row = old.session_row(identifier, ready, result, config, columns[1], basic, curves)
        audit.statistics.equal(other_row, row, '別経路の全統計')
        fingerprints = old.fingerprints(result)
        if prior_id:
            assert fingerprints == prior[key]['result_fingerprints'], (identifier, key, '旧単一窓全15指紋')
        rows.append(row)
        series[key] = curves['equity']
        durations = np.diff(ready['time_s'], append=ready['time_s'][-1])/60
        signal_use.append(dict(session=key[0], symbol=key[1],
            long_minutes=float(durations[columns[0]>0].sum()),
            short_minutes=float(durations[columns[0]<0].sum()),
            neutral_minutes=float(durations[columns[0]==0].sum())))
        ledgers.append(dict(session=key[0], symbol=key[1], config=config,
            **{field:result[field].tolist() for field in STORED}, result_fingerprints=fingerprints,
            shadow_fingerprints=old.fingerprints(result['shadow'], reference.EXPECTED_SHADOW_FIELDS)))
        proofs.append(dict(session=key[0], symbol=key[1], **proof, 全統計一致=True,
            時価SHA256=hashlib.sha256(curves['equity'].tobytes()).hexdigest(), 旧単一窓一致=prior_id is not None))
        if key[0] in REPRESENTATIVE:
            causality.append(dict(session=key[0], symbol=key[1], **causal_check(spec, ready, columns, config, result)))
        for wave in old.FIXED['指定波']:
            if wave['session'] == key[0]:
                records = old.base.wave_metrics.order_records(ready, columns[0], result, engine.REASONS)
                waves.append(old.base.wave_metrics.episode_metrics(dict(id=identifier, manager=old.FIXED['manager']),
                    wave, ready, columns[0], result, records, config['point_value']))
    assert len(rows) == len(ledgers) == len(proofs) == 26 and len(waves) == 8 and len(causality) == 4
    periods = {}
    for period, names in (('all_symbols', old.FIXED['全セッション']), ('symbols', old.FIXED['後半7セッション'])):
        periods[period] = {s:audit.statistics.period(rows, series, names, s, old.base.research.MULT[s]) for s in old.SYMBOLS}
        audit.statistics.equal(old.period(rows, names), periods[period], '期間全統計')
    value = dict(id=identifier, spec=spec, **periods, wave_passes=sum(r['正方向ネット20分目安達成'] for r in waves),
        全26全行独立会計一致=True, 探索固定SHA256=digest(HERE/'探索条件の固定.json'),
        全原本行会計数=sum(len(r['last']) for r in INPUTS.values()), 旧単一窓一致入力数=26 if prior_id else 0)
    paths = []
    for folder, payload, suffix in (('sessions', rows, '.json.gz'), ('ledgers', ledgers, '.json.gz'),
        ('audits', proofs, '.json.gz'), ('waves', waves, '.json.gz'), ('causality', causality, '.json'),
        ('signal_use', signal_use, '.json'), ('summaries', value, '.json')):
        path = HERE/folder/(identifier+suffix)
        save(path, payload)
        paths.append(path)
    done = dict(id=identifier, 全合格=True, 全入力数=26, 因果入力数=4,
        全原本行会計数=value['全原本行会計数'], 旧単一窓一致入力数=value['旧単一窓一致入力数'],
        探索固定SHA256=digest(HERE/'探索条件の固定.json'),
        出力SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in paths}, 経過秒=time.perf_counter()-started)
    save(HERE/'completed'/(identifier+'.json'), done)
    return done


def main() -> None:
    """機能: 凍結後だけ全条件を再生し、全数の完了記録を保存する。

    引数: コマンドラインworkers(int)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    fixed = read(HERE/'探索条件の固定.json')
    assert fixed['conditions'] == design.catalog()
    verify(fixed['参照資料SHA256'])
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(evaluate, spec):spec['id'] for spec in design.catalog()}
        completed = []
        for future in as_completed(futures):
            completed.append(future.result())
            print(f"{len(completed)}/{len(futures)} {futures[future]} 完了", flush=True)
    assert {v['id'] for v in completed} == {s['id'] for s in design.catalog()}
    verify(fixed['参照資料SHA256'])
    save(HERE/'主再生の完了.json', dict(全合格=True, 全条件数=len(completed),
        全入力数=sum(r['全入力数'] for r in completed), 因果入力数=sum(r['因果入力数'] for r in completed),
        全原本行会計数=sum(r['全原本行会計数'] for r in completed),
        旧単一窓一致入力数=sum(r['旧単一窓一致入力数'] for r in completed),
        探索固定SHA256=digest(HERE/'探索条件の固定.json'), records=sorted(completed, key=lambda x:x['id']),
        現在API取得数=0, 保存ライブ使用=False, 全体目標達成=False))


if __name__ == '__main__':
    main()
