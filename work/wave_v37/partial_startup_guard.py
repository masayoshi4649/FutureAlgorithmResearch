"""結果前監査と実行対象の指紋を結び、未完了のまま再生しない。"""

from __future__ import annotations

import argparse
from pathlib import Path
import partial_runner as runner


def checked_files() -> set[Path]:
    """機能: 入力・計画・注文・集計・独立反証の結果前記録を列挙する。

    引数: なし。返り値: 必須ファイル集合 (set[Path])。
    """
    names = ('partial_engine_audit.py', 'partial_engine_audit.json',
        'shadow_plan_independent_audit.py', 'shadow_plan_independent_audit.json',
        'partial_runner_synthetic.py', 'partial_runner_synthetic.json',
        'partial_accounting_oracles.py', 'partial_accounting_oracles.json',
        'partial_assessment.py', 'partial_assessment_fixed.json',
        'partial_assessment_test.py', 'partial_assessment_test.json',
        'partial_causality_audit.py', 'partial_causality_fixed.json',
        'partial_wave_audit.py', 'partial_wave_fixed.json',
        'partial_accounting_audit.py', 'partial_accounting_fixed.json',
        'partial_startup_guard.py', 'partial_startup_guard_test.py', 'partial_startup_guard_test.json')
    return {runner.HERE/name for name in names}


def prerequisities() -> dict:
    """機能: 数値契約と合格状態を確認する。

    引数: なし。返り値: 監査記録 (dict)。単なるファイル存在を合格としない。
    """
    records = {name: runner.read(runner.HERE/(name+'.json')) for name in (
        'partial_engine_audit', 'shadow_plan_independent_audit', 'partial_runner_synthetic',
        'partial_accounting_oracles', 'partial_assessment_test')}
    engine = records['partial_engine_audit']
    assert engine['全合格'] and engine['旧8配列一致'] and engine['旧A0完全一致入力数'] == 26
    assert not engine['新方針の実相場損益再生'] and engine['API取得数'] == 0
    assert engine['engine_SHA256'] == runner.digest(runner.HERE/'engine_partial_restore.py')
    assert engine['shadow_engine_SHA256'] == runner.digest(runner.HERE/'engine_shadow_plan.py')
    plan = records['shadow_plan_independent_audit']
    assert plan['全合格'] and plan['旧8同値入力数'] == 26 and plan['計画prefix数'] == plan['計画future数'] == 52
    assert not plan['新しい実枠制御の損益計算']
    for relative, sha in plan['参照SHA256'].items():
        candidate = Path(relative)
        if not candidate.is_absolute(): candidate = runner.ROOT/candidate
        assert runner.digest(candidate) == sha, relative
    synthetic = records['partial_runner_synthetic']
    assert synthetic['全合格'] and synthetic['人工再生数'] == 1236 and not synthetic['新実データ損益']
    for name, sha in synthetic['SHA256'].items(): assert runner.digest(runner.HERE/name) == sha, name
    oracle = records['partial_accounting_oracles']
    assert oracle['全人工会計合格'] and oracle['破損拒否数'] >= 4 and not oracle['新実データ損益']
    assert oracle['実装SHA256'] == runner.digest(runner.HERE/'partial_accounting_oracles.py')
    test = records['partial_assessment_test']
    assert test['全検査合格'] and test['検査数'] >= 55 and not test['新損益読取']
    for name in ('partial_assessment_fixed',):
        fixed = runner.read(runner.HERE/(name+'.json'))
        assert not fixed['新損益読取'] and fixed['API取得数'] == 0
        for relative, sha in fixed['参照SHA256'].items():
            assert runner.digest(runner.ROOT/relative) == sha, relative
    # ----------------------------------------
    # 実データで実行する独立反証も、対象集合・人工検査・参照実体まで固定する。
    causal = runner.read(runner.HERE/'partial_causality_fixed.json')
    wave = runner.read(runner.HERE/'partial_wave_fixed.json')
    cash = runner.read(runner.HERE/'partial_accounting_fixed.json')
    assert causal['合成検査合格'] and causal['規則']['全検査入力数'] == 1730
    assert causal['規則']['新実相場損益未読']
    all_ids = {r['id'] for r in runner.design.catalog()+runner.design.supplementary()}
    assert set(causal['規則']['全条件ID']) == all_ids
    assert wave['全合格'] and wave['合成検査合格'] and not wave['新実相場損益']
    assert wave['規則']['全波数'] == 3416 and wave['規則']['全境界数'] == 6832
    assert set(wave['規則']['主条件ID']) == {r['id'] for r in runner.design.catalog()}
    assert set(wave['規則']['補助条件ID']) == {r['id'] for r in runner.design.supplementary()}
    assert cash['全条件数'] == 427 and cash['全入力数'] == 11102 and not cash['新実データ損益']
    assert cash['主対象'] == runner.design.catalog() and cash['補助対象'] == runner.design.supplementary()
    assert cash['人工検査']['全合格'] and cash['人工検査']['人工入力検査数'] == 1236
    assert cash['人工検査']['破損欠落拒否数'] == 49
    assert len(cash['原本78SHA256']) == 78
    for relative, sha in cash['原本78SHA256'].items():
        assert runner.digest(runner.ROOT/relative) == sha, relative
    for fixed, field in ((causal,'SHA256'), (wave,'SHA256'), (cash,'参照SHA256')):
        for relative, sha in fixed[field].items():
            assert runner.digest(runner.ROOT/relative) == sha, relative
    for name, counter, expected, failures in (
            ('partial_causality_selftest', '人工条件数', 427, 4),
            ('partial_wave_selftest', '合成検査数', 6, 5)):
        record = runner.read(runner.HERE/(name+'.json'))
        assert record['全合格'] and record[counter] == expected and record['負例拒否数'] == failures
        assert not record['新実相場損益']
    return records


def main() -> None:
    """機能: 全仕様と監査を固定し、実行可能な場合だけ起動記録を保存する。

    引数: --check (bool) は既存の固定内容を検査する。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    runner.design.freeze()
    files = checked_files()
    assert all(path.is_file() for path in files)
    records = prerequisities()
    guard_test = runner.read(runner.HERE/'partial_startup_guard_test.json')
    assert guard_test['全合格'] and guard_test['破損拒否数'] == 12
    assert guard_test['ガードSHA256'] == runner.digest(Path(__file__))
    fixed = runner.prepare()
    value = dict(実行可能=True, 全条件数=363, 補助条件数=64, 全入力数=363*26, 補助入力数=64*26,
        主仮説=runner.design.PRIMARY_ID, 探索固定SHA256=runner.digest(runner.HERE/'探索条件の固定.json'),
        API取得数=0, 新実データ損益=False,
        SHA256={p.relative_to(runner.ROOT).as_posix(): runner.digest(p) for p in sorted(files)})
    path = runner.HERE/'起動前監査.json'
    if args.check or path.exists():
        assert runner.read(path) == value, '起動記録の固定後変更'
    else:
        runner.save(path, value)
    assert len(fixed['conditions']) == value['全条件数']
    print('主363・補助64の結果前契約が一致。新実データ損益は未計算。', flush=True)


if __name__ == '__main__':
    main()
