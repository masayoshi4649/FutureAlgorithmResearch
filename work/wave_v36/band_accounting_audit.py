"""全候補の保存台帳を別処理で再生し、会計と注文接続の因果性を検算する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
from pathlib import Path
import time

import numpy as np

import band_runner as runner
import engine_connection_audit as connection
import band_independent_statistics as statistics

HERE, ROOT = runner.HERE, runner.ROOT


def period_check(expected: dict, rows: list[dict], series: dict, names: list[str]) -> None:
    """機能: 保存済み期間値を、別会計の全時価曲線と全返済から照合する。

    引数: expected/series (dict)、rows (list[dict])、names (list[str])。返り値: なし (None)。
    """
    assert set(expected) == set(runner.SYMBOLS)
    for symbol in runner.SYMBOLS:
        value = statistics.period(rows, series, names, symbol, runner.accounting.MULT[symbol])
        statistics.equal(expected[symbol], value, symbol)


def evaluate(spec: dict, destination: str) -> dict:
    """機能: 一条件全26を収益順に選別せず再生し、全保存値と因果性を検査する。

    引数: spec (dict)、destination (str)。返り値: 条件別監査証跡 (dict)。
    """
    identifier = spec['id']
    files = {name: HERE / destination / name / (identifier + ('.json' if name == 'summaries' else '.json.gz'))
        for name in ('sessions', 'ledgers', 'accounting', 'summaries', 'waves')}
    before = {p.relative_to(ROOT).as_posix(): runner.digest(p) for p in files.values()}
    data = {name: runner.read(path) for name, path in files.items()}
    assert data['summaries']['id'] == identifier and data['summaries']['spec'] == spec
    assert data['summaries']['探索固定SHA256'] == runner.digest(HERE / '探索条件の固定.json')
    maps = {}
    for name in ('sessions', 'ledgers', 'accounting'):
        records = data[name]
        maps[name] = {(r['session'], r['symbol']): r for r in records}
        assert len(records) == len(maps[name]) == 26 and set(maps[name]) == set(runner.INPUTS)
    rows, series, checks = [], {}, []
    ledger_hash = hashlib.sha256()
    for key, ready in sorted(runner.INPUTS.items()):
        state = runner.direction(spec, key)
        config = runner.base.managers.make_config(runner.FIXED['manager'], key[1], ready)
        result = runner.base.engine.run(ready, state, config, detail=True, width_mode=0, observed_fill=spec['observed_fill'])
        ledger = maps['ledgers'][key]
        assert ledger['config'] == config
        for field in runner.STORED:
            assert ledger[field] == result[field].tolist(), (identifier, key, field)
        assert runner.fingerprints(result) == ledger['result_fingerprints']
        independent, values = runner.accounting.reconstruct(ready, result, key[1])
        original = maps['sessions'][key]
        complete_row = statistics.session(identifier, ready, result, config, independent, values)
        statistics.equal(original, complete_row, identifier + '/' + str(key))
        stored_audit = maps['accounting'][key]
        statistics.equal(stored_audit, dict(**independent, 全行会計一致=True, 旧固定一致=spec['signal_id'] == 'H019',
            独立時価SHA256=hashlib.sha256(values['equity'].tobytes()).hexdigest()), '保存会計')
        proof = connection.verify(ready, state, config, result, spec['observed_fill'])
        rows.append(complete_row); series[key] = values['equity']
        checks.append(dict(session=key[0], symbol=key[1], **proof, 原本行会計数=len(ready['last'])))
        ledger_hash.update(str(key).encode('utf-8')); ledger_hash.update(result['trades'].tobytes())
    assert ledger_hash.hexdigest() == data['summaries']['ledger_hash']
    period_check(data['summaries']['all_symbols'], rows, series, runner.FIXED['全セッション'])
    period_check(data['summaries']['symbols'], rows, series, runner.FIXED['後半7セッション'])
    assert before == {p.relative_to(ROOT).as_posix(): runner.digest(p) for p in files.values()}
    value = dict(id=identifier, 全入力数=26, 全保存台帳一致=True, 全会計一致=True, 全期間時価一致=True,
        prefix=sum(r['prefix'] for r in checks), future=sum(r['future'] for r in checks),
        reflection=sum(r['reflection'] for r in checks), 原本行会計数=sum(r['原本行会計数'] for r in checks),
        入力別=checks, 保存物SHA256=before, 監査固定SHA256=runner.digest(HERE / 'band_accounting_fixed.json'))
    runner.save(HERE / destination / 'accounting_details' / (identifier + '.json.gz'), value)
    return value


def freeze() -> dict:
    """機能: 損益を読む前に監査の対象・コードを固定し、変更を拒否する。

    引数: なし。返り値: 固定監査条件 (dict)。
    """
    files = [Path(__file__), HERE / 'engine_connection_audit.py', HERE / 'band_runner.py',
        HERE / 'band_independent_statistics.py', HERE / 'band_statistics_selftest.py', HERE / 'band_statistics_selftest.json',
        HERE / 'band_design.py', HERE.parent / 'wave_v35/accounting_reconstruction_vectorized.py',
        HERE.parent / 'wave_v33/engine_dynamic_atr.py']
    value = dict(主条件数=364, 補助条件数=65, 全入力数=26, 原本切断比率=.37,
        全条件会計=True, 全条件未来変更=True, 全条件買売反射=True, 成績選別=False,
        SHA256={p.relative_to(ROOT).as_posix(): runner.digest(p) for p in files})
    path = HERE / 'band_accounting_fixed.json'
    if path.exists():
        assert runner.read(path) == value, '監査固定後の変更'
    else:
        runner.save(path, value)
    return value


def main() -> None:
    """機能: 全364又は補助65を一つの固定監査で検算する。

    引数: --prepare/--supplementary (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--supplementary', action='store_true')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    fixed = freeze()
    if args.prepare:
        print('全364＋補助65の独立会計・注文因果性を固定。損益読取なし。')
        return
    runner.prepare(); runner.initialize()
    specs = runner.FIXED['supplementary_conditions'] if args.supplementary else runner.FIXED['conditions']
    destination = 'supplementary' if args.supplementary else ''
    complete = runner.read(HERE / destination / '主再生の完了.json')
    assert complete['全条件数'] == len(specs)
    started, values = time.perf_counter(), []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=runner.initialize) as pool:
        futures = {pool.submit(evaluate, spec, destination): spec['id'] for spec in specs}
        for future in as_completed(futures):
            value = future.result(); values.append(value)
            print(f"独立監査 {len(values)}/{len(specs)} {value['id']}", flush=True)
    assert len(values) == len({r['id'] for r in values}) == len(specs)
    assert {r['id'] for r in values} == {r['id'] for r in specs}
    assert freeze() == fixed
    runner.prepare()
    result = dict(全監査合格=True, 対象条件数=len(specs), 全入力数=len(specs) * 26,
        prefix=sum(r['prefix'] for r in values), future=sum(r['future'] for r in values),
        reflection=sum(r['reflection'] for r in values), 原本行会計数=sum(r['原本行会計数'] for r in values),
        条件=sorted(values, key=lambda r: r['id']), 経過秒=time.perf_counter() - started,
        監査固定SHA256=runner.digest(HERE / 'band_accounting_fixed.json'),
        探索固定SHA256=runner.digest(HERE / '探索条件の固定.json'), API取得数=0, 現在保存物使用=False)
    runner.save(HERE / destination / 'accounting_audit.json', result)
    print({k: result[k] for k in ('全監査合格', '対象条件数', '全入力数', '経過秒')}, flush=True)


if __name__ == '__main__':
    main()
