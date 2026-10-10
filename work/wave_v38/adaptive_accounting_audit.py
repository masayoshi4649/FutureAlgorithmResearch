"""全974条件を別会計・枠・分岐・成熟注文・期間統計へ結び、好成績の選別をしない。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

import adaptive_runner as runner
import adaptive_cash_reconstruction as cash
import adaptive_independent_statistics as statistics
import adaptive_slot_audit as slots


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def close(a: object, b: object, label: str) -> None:
    """機能: 独立会計の頻繁な数値比較を同じ絶対誤差で行う。

    引数: a/b (object)、label (str)。返り値: なし (None)。
    """
    left, right = np.asarray(a), np.asarray(b)
    assert left.shape == right.shape and np.isfinite(left).all() and np.isfinite(right).all(), label
    assert np.all(np.abs(left-right) <= 1e-6), label


def initialize() -> None:
    """機能: 凍結資料を検査して既知入力だけを各プロセスへ設定する。

    引数: なし。返り値: なし (None)。
    """
    fixed = runner.read(HERE/'adaptive_accounting_fixed.json')
    for relative, sha in fixed['参照SHA256'].items(): assert runner.digest(ROOT/relative) == sha, relative
    runner.initialize()
    cash.close = close


def inspect(spec: dict, ready: dict, result: dict, config: dict, columns: tuple) -> tuple:
    """機能: 一入力の注文会計・全行枠・公開予約・表示統計を別式で再構成する。

    引数: spec/ready/result/config (dict)、columns (tuple[ndarray])。
    返り値: 独立指標・独立曲線・枠証跡・基本会計 (tuple)。
    """
    assert len(columns) == 10
    state,bad,bad_source,good,good_source,valid,branch,branch_source,branch_valid,choice = columns
    basic, curves = cash.reconstruct(ready, result, ready['symbol'])
    proof = slots.audit(ready, result, config, spec['policy'], bad, bad_source, good, good_source, valid, curves,
        state=state, budget_enabled=spec['budget_enabled'], min_delay_seconds=spec['min_delay_seconds'],
        observed_fill=spec['observed_fill'], branch_direction=branch, branch_source=branch_source,
        branch_valid=branch_valid, branch_mode=spec['branch_mode'], branch_choice=choice, branch_seed=spec['branch_seed'])
    row = statistics.session(spec['id'], ready, result, config, basic, curves, columns, spec)
    return row, curves, proof, basic


def evaluate(spec: dict, destination: str = '') -> dict:
    """機能: 全26入力を再生成し、全保存台帳・必須統計・期間時価へ接続する。

    引数: spec (dict)、destination (str)。返り値: 一条件の独立証跡 (dict)。
    """
    identifier = spec['id']; started = time.perf_counter()
    base = HERE/destination
    paths = {folder:base/folder/(identifier+suffix) for folder,suffix in (
        ('sessions','.json.gz'),('ledgers','.json.gz'),('waves','.json.gz'),('accounting','.json.gz'),('summaries','.json'))}
    before = {p.relative_to(ROOT).as_posix():runner.digest(p) for p in paths.values()}
    summary = runner.read(paths['summaries'])
    assert summary['id'] == identifier and summary['spec'] == spec
    assert summary['探索固定SHA256'] == runner.digest(HERE/'探索条件の固定.json')
    saved = {}
    for folder in ('sessions','ledgers','accounting'):
        values=runner.read(paths[folder]); assert len(values)==26
        mapped={(v['session'],v['symbol']):v for v in values}
        assert len(mapped)==26 and set(mapped)==set(runner.INPUTS)
        saved[folder]=mapped
    rows, evidence, series = [], [], {}
    ledger_hash=hashlib.sha256()
    for key, ready in sorted(runner.INPUTS.items()):
        columns=runner.columns(spec,key)
        state,bad,bad_source,good,good_source,valid,branch,branch_source,branch_valid,choice=columns
        config=runner.base.managers.make_config(runner.FIXED['manager'],key[1],ready)
        original=runner.shadow(spec,key,state,config)
        result=runner.engine.run(ready,state,config,bad,bad_source,good,good_source,spec['policy'],
            observed_fill=spec['observed_fill'],detail=True,shadow=original,good_valid=valid,
            budget_enabled=spec['budget_enabled'],min_delay_seconds=spec['min_delay_seconds'],
            branch_direction=branch,branch_source=branch_source,branch_valid=branch_valid,
            branch_mode=spec['branch_mode'],branch_choice=choice,branch_seed=spec['branch_seed'])
        row,curves,proof,basic=inspect(spec,ready,result,config,columns)
        statistics.equal(saved['sessions'][key],row,'全session必須統計')
        stored=saved['ledgers'][key]
        assert stored['config']==config
        assert stored['result_fingerprints']==runner.fingerprints(result)
        assert stored['shadow_fingerprints']==runner.fingerprints(original,runner.engine.FIELDS+('plans','execution_plans','prepare_events','entry_preparations'))
        for name in runner.STORED:
            values=np.asarray(stored[name],dtype=float).reshape(result[name].shape)
            assert np.array_equal(values,result[name],equal_nan=True),(identifier,key,name)
        shadow_equal=spec['policy']['kind']=='baseline' and (not spec['budget_enabled'] or spec['min_delay_seconds']==0.)
        expected=dict(session=key[0],symbol=key[1],**{k:v for k,v in basic.items() if k not in ('session','symbol')},
            全行会計一致=True,元A0一致=shadow_equal,影の全配列同値を要求=shadow_equal,
            独立時価SHA256=hashlib.sha256(curves['equity'].tobytes()).hexdigest())
        statistics.equal(saved['accounting'][key],expected,'主の独立会計表示')
        if shadow_equal:
            for name in runner.engine.FIELDS:
                assert np.array_equal(result[name],original[name],equal_nan=True)
        ledger_hash.update(str(key).encode('utf-8')); ledger_hash.update(result['trades'].tobytes())
        rows.append(row); series[key]=curves['equity']
        assert proof['原本行数'] == len(ready['last'])
        evidence.append(dict(session=key[0],symbol=key[1],**proof,
            全保存数値一致=True,全台帳配列一致=True,分岐集計独立一致=True,全組R超過独立一致=True,
            影の全配列同値を要求=shadow_equal))
    assert ledger_hash.hexdigest()==summary['ledger_hash']
    periods={}
    for period,names in (('all_symbols',runner.FIXED['全セッション']),('symbols',runner.FIXED['後半7セッション'])):
        periods[period]={s:statistics.period(rows,series,names,s,runner.base.research.MULT[s]) for s in runner.SYMBOLS}
        statistics.equal(summary[period],periods[period],period+'全必須統計')
    assert before=={p.relative_to(ROOT).as_posix():runner.digest(p) for p in paths.values()}
    fixed_sha=runner.digest(HERE/'adaptive_accounting_fixed.json')
    result=dict(id=identifier,spec=spec,sessions=rows,検査=evidence,**periods,
        全監査合格=True,全入力数=26,全原本行会計数=sum(len(r['last']) for r in runner.INPUTS.values()),
        保存資料SHA256=before,監査固定SHA256=fixed_sha,探索固定SHA256=runner.digest(HERE/'探索条件の固定.json'),
        経過秒=time.perf_counter()-started)
    runner.save(base/'adaptive_accounting_details'/(identifier+'.json.gz'),result)
    return dict(id=identifier,全監査合格=True,全入力数=26,全原本行会計数=result['全原本行会計数'],
        実体SHA256=runner.digest(base/'adaptive_accounting_details'/(identifier+'.json.gz')),監査固定SHA256=fixed_sha)


def selftest() -> dict:
    """機能: 全974条件の人工価格で会計・枠・分岐・全統計を固定前に照合する。

    引数: なし。返り値: 合成証跡 (dict)。新しい実データは読まない。
    """
    import adaptive_statistics_selftest as fixtures
    cash.close = close
    immutable = (Path(__file__), Path(slots.__file__), Path(slots.shadow_oracle.__file__),
        Path(statistics.__file__), Path(fixtures.__file__), Path(runner.__file__),
        HERE/'engine_partial_restore.py', HERE/'engine_shadow_plan.py', HERE/'adaptive_design.py')
    before = {p.relative_to(ROOT).as_posix(): runner.digest(p) for p in immutable}
    count = 0; rejection = 0; retained = None
    specs = runner.design.catalog() + runner.design.supplementary()
    coverage = set()
    for spec in specs:
        rows, series = [], {}
        for symbol in runner.SYMBOLS:
            for inactive in (False, True):
                ready, columns, config = fixtures.artificial(spec, symbol, inactive)
                result = fixtures.play(spec, ready, columns, config)
                row, curves, proof, basic = inspect(spec, ready, result, config, columns)
                saved = runner.session_row(spec['id'], ready, result, config, columns[1], basic, curves)
                statistics.equal(saved, row, '人工session全項目')
                if not inactive:
                    rows.append(row); series[(ready['session'], symbol)] = curves['equity']
                if spec['id'] == runner.design.PRIMARY_ID and symbol == 'TOPIX' and not inactive:
                    retained = spec, ready, columns, config, result, row
                coverage.add((spec['budget_enabled'], spec['min_delay_seconds'], spec['branch_mode'], inactive))
                count += 1
        expected = runner.period(rows, ['2026-09-21_Day'])
        for symbol in runner.SYMBOLS:
            statistics.equal(expected[symbol], statistics.period(rows, series, ['2026-09-21_Day'], symbol,
                runner.base.research.MULT[symbol]), '人工period全項目')
    assert retained is not None and count == 974 * 4
    spec, ready, columns, config, result, row = retained
    changes = [('slot_curve', (2, 0), 0.), ('control_curve', (2, 5), 99.),
        ('slot_events', (0, 3), 99.), ('orders', (0, 4), 99.)]
    for field, index, value in changes:
        changed = deepcopy(result); changed[field][index] = value
        try:
            inspect(spec, ready, changed, config, columns)
        except (AssertionError, IndexError, KeyError, ValueError):
            rejection += 1
        else:
            raise AssertionError('破損受理:' + field)
    for field in row:
        changed = deepcopy(row); del changed[field]
        try:
            statistics.equal(changed, row, '必須統計欠落')
        except AssertionError:
            rejection += 1
        else:
            raise AssertionError('欠落受理:' + field)
    separate = runner.read(HERE/'adaptive_statistics_selftest.json')
    assert separate['全合格'] and separate['人工入力検査数'] == count
    for relative, sha in separate['参照SHA256'].items():
        assert runner.digest(ROOT/relative) == sha, relative
    assert before == {relative: runner.digest(ROOT/relative) for relative in before}
    return dict(全合格=True, 全条件数=974, 人工入力検査数=count, 破損欠落拒否数=rejection,
        独立統計破損拒否数=separate['破損欠落拒否数'],
        全974条件両銘柄活動無取引=True, 条件被覆=[list(v) for v in sorted(coverage)],
        参照SHA256=before, 新実データ損益=False, API取得数=0, 現在保存物使用=False)


def prepare() -> dict:
    """機能: 全974の対象・検算・人工証跡を新損益前に固定する。

    引数: なし。返り値: 固定資料 (dict)。主探索の存在前にも実行可能。
    """
    path = HERE/'adaptive_accounting_fixed.json'
    if path.exists():
        fixed = runner.read(path)
        assert fixed['主対象'] == runner.design.catalog() and fixed['補助対象'] == runner.design.supplementary()
        for relative, sha in fixed['参照SHA256'].items():
            assert runner.digest(ROOT/relative) == sha, relative
        return fixed
    test = selftest(); runner.save(HERE/'adaptive_accounting_selftest.json', test)
    names = ('adaptive_accounting_audit.py','adaptive_slot_audit.py','adaptive_shadow_oracle.py',
        'adaptive_slot_selftest.py','adaptive_slot_selftest.json',
        'adaptive_independent_statistics.py','adaptive_cash_reconstruction.py','adaptive_accounting_selftest.json',
        'adaptive_statistics_selftest.py','adaptive_statistics_selftest.json','adaptive_runner_synthetic.py',
        'adaptive_runner.py','engine_partial_restore.py','engine_shadow_plan.py','adaptive_design.py',
        'adaptive_design_fixed.json','branch_inputs.py','branch_inputs_runtime.py',
        'branch_input_fixed.json','branch_input_runtime_fixed.json')
    paths = {HERE/name for name in names}
    slot_test = runner.read(HERE/'adaptive_slot_selftest.json')
    assert slot_test['全合格'] and slot_test['主人工数'] == 824 and slot_test['補助人工数'] == 768
    assert slot_test['破損拒否数'] >= 13 and not slot_test['新実相場損益']
    for relative, sha in slot_test['SHA256'].items():
        source = Path(relative)
        assert source.is_relative_to(ROOT) and runner.digest(source) == sha, relative
        paths.add(source)
    paths.update(HERE.parent/'wave_v37'/name for name in ('partial_accounting_oracles.py','partial_accounting_oracles.json'))
    originals = runner.read(HERE/'branch_input_causality.json')['原本78SHA256']
    for relative, sha in originals.items():
        assert runner.digest(ROOT/relative) == sha, relative
    fixed = dict(主対象=runner.design.catalog(), 補助対象=runner.design.supplementary(),
        主条件数=206, 補助条件数=768, 全条件数=974, 全入力数=974*26,
        規則='全条件全26。独立注文会計・元枠・新根拠・成熟注文・分岐・R有無・同約定カバー時価・全session/period必須項目・実15影10配列指紋を照合。成績で除外しない。',
        A0同値範囲='影全配列同値はA0でR無効又は遅延0のみ要求。正遅延R有効のA0も全会計と元影初回共有は常時要求。',
        因果性の分担='別adaptive_causality_auditで主846＋補助3072入力のprefix/future/reflection。全会計25324入力と区別する。',
        人工検査=test, 原本78SHA256=originals,
        参照SHA256={p.relative_to(ROOT).as_posix(): runner.digest(p) for p in sorted(paths)},
        新実データ損益=False, API取得数=0, 現在保存物使用=False)
    runner.save(path, fixed)
    return fixed


def main() -> None:
    """機能: 結果前固定、又は完成済みの主・補助の全件独立会計を実行する。

    引数: --prepare/--supplementary (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--supplementary', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    fixed = prepare()
    if args.prepare:
        print('全974の独立会計を結果前固定。人工入力', fixed['人工検査']['人工入力検査数'], flush=True)
        return
    initialize(); destination = 'supplementary' if args.supplementary else ''
    specs = fixed['補助対象'] if args.supplementary else fixed['主対象']
    complete = runner.read(HERE/destination/'主再生の完了.json')
    assert complete['全条件数'] == len(specs) and complete['全入力数'] == len(specs)*26
    assert complete['探索固定SHA256'] == runner.digest(HERE/'探索条件の固定.json')
    before = {relative: runner.digest(ROOT/relative) for relative in fixed['参照SHA256']}
    records = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as executor:
        futures = {executor.submit(evaluate, spec, destination): spec['id'] for spec in specs}
        for future in as_completed(futures):
            records.append(future.result())
            if len(records) % 12 == 0 or len(records) == len(specs):
                print('独立会計', len(records), '/', len(specs), flush=True)
    assert len(records) == len(specs) and {r['id'] for r in records} == {s['id'] for s in specs}
    assert before == {relative: runner.digest(ROOT/relative) for relative in before}
    for relative, sha in fixed['原本78SHA256'].items():
        assert runner.digest(ROOT/relative) == sha
    result = dict(全監査合格=True, 対象条件数=len(specs), 全入力数=len(specs)*26,
        全原本行会計数=sum(r['全原本行会計数'] for r in records), 条件=sorted(records, key=lambda r: r['id']),
        全枠会計一致=True, 全予約と新根拠一致=True, 同約定両建て全行一致=True, 全予算予約一致=True,
        全保存統計一致=True, 全台帳配列一致=True, 元終了以前=True,
        全分岐独立一致=True, 全成熟注文独立一致=True, 全組R超過独立一致=True,
        監査固定SHA256=runner.digest(HERE/'adaptive_accounting_fixed.json'),
        探索固定SHA256=runner.digest(HERE/'探索条件の固定.json'), 参照SHA256=before,
        原本78SHA256=fixed['原本78SHA256'], API取得数=0, 現在保存物使用=False)
    runner.save(HERE/destination/'adaptive_accounting_audit.json', result)
    print('独立会計の全件完了', len(specs), flush=True)


if __name__ == '__main__':
    main()


