"""新損益前の仕様・入力因果・注文器合成を束ね、確認後だけ全840を起動する。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import pickle
import subprocess
import sys
from zoneinfo import ZoneInfo

import numpy as np
import conditional_design as design

HERE, ROOT = design.HERE, design.ROOT


def read(path: Path) -> dict:
    """機能: UTF-8の監査JSONを読む。

    引数: path (Path)。返り値: JSON内容 (dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """機能: 監査の証跡を日本語JSONで保存する。

    引数: path (Path)、value (dict)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def unique(rows: list[dict], fields: tuple[str, ...]) -> dict:
    """機能: 行集合を索引化し重複を拒否する。

    引数: rows (list[dict])、fields (tuple[str,...])。返り値: 行索引 (dict)。
    """
    result = {tuple(r[k] for k in fields): r for r in rows}
    assert len(result) == len(rows), '監査の重複'
    return result


def verify_payload(fixed: dict, causal: dict, engine: dict, runner: dict, inputs: dict) -> dict:
    """機能: 全840の対象集合と新損益前の因果・注文・集計監査を要求する。

    引数: fixed/causal/engine/runner/inputs (dict)。返り値: 件数 (dict)。
    """
    assert fixed['conditions'] == design.catalog()
    assert fixed['全条件数'] == 840 and fixed['主条件数'] == 168 and fixed['診断数'] == 672
    assert fixed['全セッション'] == list(design.SESSIONS)
    assert fixed['選択用6セッション'] == list(design.SESSIONS[:6])
    assert fixed['共通評価7セッション'] == list(design.SESSIONS[6:]) and fixed['指定波'] == design.waves()
    assert set(inputs) == {(s, symbol) for s in design.SESSIONS for symbol in ('TOPIX', 'NK225')}
    assert causal['構造監査合格'] is True and causal['全監査完了'] is True
    for name in ('新損益読取', '売買再生', '現在保存物使用'):
        assert causal[name] is False
    assert causal['API取得数'] == 0 and causal['対象入口ID'] == list(design.SIGNAL_IDS)
    assert causal['全セッション'] == fixed['全セッション']
    assert causal['訓練6セッション'] == fixed['選択用6セッション']
    assert causal['評価7セッション'] == fixed['共通評価7セッション']
    for name in ('全機序合成発火', '上下反射', '欠測は不発', '原本同時刻はseq順',
                 '乱数prefix安定', '乱数両市場同一', '乱数ゼロ位置維持'):
        assert causal['合成'][name] is True
    assert set(causal['合成']['人工発火数']) == {f'B{i:02d}' for i in range(12)}
    assert all(value > 0 for value in causal['合成']['人工発火数'].values())
    entries, conditions = causal['入口'], causal['悪化']
    assert entries['配列数'] == 36 and entries['全区間数'] == len(entries['rows']) == 936
    assert conditions['配列数'] == 12 and conditions['全区間数'] == len(conditions['rows']) == 312
    erows = unique(entries['rows'], ('id', 'clock_scale', 'session', 'symbol'))
    assert set(erows) == {(h, scale, *key) for h in design.SIGNAL_IDS for scale in (.8, 1., 1.2) for key in inputs}
    for (signal, scale, session, symbol), row in erows.items():
        assert row['原本行数'] == len(inputs[session, symbol]['last']) and row['基準旧列一致'] == (scale == 1.)
    brows = unique(conditions['rows'], ('id', 'session', 'symbol'))
    assert set(brows) == {(b['id'], *key) for b in design.condition_specs() for key in inputs}
    for (name, session, symbol), row in brows.items():
        assert row['原本行数'] == len(inputs[session, symbol]['last']) and row['公開順確認'] is True
        assert 0 <= row['非中立行数'] <= row['原本行数'] and row['証拠イベント数'] >= 0
    for name, count in (('入口prefix比較数', 1872), ('入口未来改変比較数', 1872),
                        ('悪化prefix比較数', 624), ('悪化未来改変比較数', 624), ('悪化反射比較数', 312)):
        assert causal[name] == count
    assert engine['全合格'] is True and engine['合成全合格'] is True
    assert engine['合成件数'] == len(engine['合成検査']) == 11
    assert len({r['検査'] for r in engine['合成検査']}) == 11 and all(r['一致'] is True for r in engine['合成検査'])
    assert engine['旧固定互換'] == {'固定A0通常の旧8完全一致': 26, '固定A0同期の全10完全一致': 26}
    assert engine['元ファイル不変'] is True and engine['API取得数'] == 0
    for name in ('新最小幅条件の実相場再生', '成績選抜', '現在保存物使用'):
        assert engine[name] is False
    assert len(engine['CONDITIONAL_COLUMNS']) == len(set(engine['CONDITIONAL_COLUMNS'])) == 18
    assert len(engine['TRAIL_EVENT_COLUMNS']) == len(set(engine['TRAIL_EVENT_COLUMNS'])) == 15
    for name in ('監査完了', '悪化と注文変化を分離', '同じ新規の退出差一致'):
        assert runner[name] is True
    assert runner['破損拒否数'] == 4 and runner['実相場再生'] is False
    return {'全条件数': 840, '主条件数': 168, '診断数': 672, '全入力数': 21840,
            '前6入力数': 10080, '後7入力数': 11760, '全指定波数': 6720,
            '入力原本行数': sum(len(v['last']) for v in inputs.values()),
            '入口因果区間数': 936, '悪化因果区間数': 312, '合成注文経路数': 11}


def verify_sources() -> dict:
    """機能: 各監査の完了内容を実装・入力指紋へ結合する。

    引数: なし。返り値: 起動前監査証跡 (dict)。売買再生はしない。
    """
    hashes = {}

    def check(path: Path, expected: str | None = None) -> str:
        """機能: 参照指紋を保存して改変を拒否する。

        引数: path (Path)、expected (str|None)。返り値: SHA256 (str)。
        """
        path = path.resolve()
        name = path.relative_to(ROOT).as_posix()
        actual = design.digest(path)
        assert expected is None or expected == actual, '指紋不一致: ' + name
        assert name not in hashes or hashes[name] == actual, '読取中の改変: ' + name
        hashes[name] = actual
        return actual

    def load(path: Path) -> dict:
        """機能: 指紋を記録しJSONを読む。

        引数: path (Path)。返り値: JSON内容 (dict)。
        """
        check(path)
        return read(path)

    fixed = load(HERE / '探索条件の固定.json')
    planned = load(HERE / 'conditional_design_fixed.json')
    assert planned['conditions'] == fixed['conditions'] and planned['規則'] == design.rules()
    assert planned['signals'] == design.signals() and planned['manager'] == design.manager() and planned['variants'] == design.variants()
    for group in (fixed['SHA256'], planned['参照SHA256']):
        for name, expected in group.items():
            check(ROOT / name, expected)
    with (HERE.parent / 'wave_v23/inputs.pkl').open('rb') as stream:
        inputs = pickle.load(stream)
    causal = load(HERE / 'input_causality_before_pnl.json')
    engine = load(HERE / 'conditional_engine_audit.json')
    engine_fixed = load(HERE / 'engine_conditional_fixed.json')
    for name, expected in engine_fixed['ファイルSHA256'].items():
        check(HERE / name, expected)
    runner_audit = load(HERE / 'runner_synthetic_audit.json')
    counts = verify_payload(fixed, causal, engine, runner_audit, inputs)
    expected_raw = {f'{folder}/{key[1]}/{key[0]}.{extension}' for key in inputs
                    for folder, extension in (('book', 'jsonl'), ('candle_1min', 'csv'), ('candle_5min', 'csv'))}
    assert set(causal['原本78SHA256']) == expected_raw and len(expected_raw) == 78
    for group in ('参照SHA256', '原本78SHA256'):
        for name, expected in causal[group].items():
            check(ROOT / name, expected)
    check(HERE / 'engine_conditional.py', engine['engine_SHA256'])
    check(HERE / 'conditional_engine_audit.py', engine['監査実装SHA256'])
    for name, expected in engine['元SHA256'].items():
        check(Path(name), expected)
    check(HERE / 'conditional_runner.py', runner_audit['実装SHA256'])
    check(HERE / 'runner_synthetic_audit.py', runner_audit['検査SHA256'])
    assessment = load(HERE / 'conditional_assessment_fixed.json')
    check(HERE / 'conditional_assessment.py', assessment['実装SHA256'])
    check(HERE / 'conditional_design_fixed.json', assessment['設計固定SHA256'])
    check(HERE / 'conditional_assessment_test.json', assessment['人工検査SHA256'])
    tests = load(HERE / 'conditional_assessment_test.json')
    assert tests['全検査合格'] is True and tests['人工検査件数'] == len(tests['検査']) == 15
    assert all(r['一致'] is True for r in tests['検査'])
    assert tests['新PnL参照'] is False and tests['現在保存物使用'] is False and tests['API取得数'] == 0
    check(HERE / 'conditional_design.py', tests['設計実装SHA256'])
    check(HERE / 'conditional_assessment.py', tests['判定実装SHA256'])
    artifacts = load(HERE / 'input_artifacts.json')
    assert artifacts == causal['artifacts'] and artifacts['新損益読取'] is False
    assert artifacts['入口配列数'] == 36 and artifacts['悪化配列数'] == artifacts['証拠表数'] == 12
    paths = {f'work/wave_v35/entries/{h}__C{round(scale * 100):03d}.npz'
             for h in design.SIGNAL_IDS for scale in (.8, 1., 1.2)}
    paths |= {f'work/wave_v35/{folder}/B{i:02d}.npz' for folder in ('deterioration', 'evidence') for i in range(12)}
    assert set(artifacts['SHA256']) == paths and len(paths) == 60
    for name, expected in artifacts['SHA256'].items():
        check(ROOT / name, expected)
    input_fixed = load(HERE / 'conditional_input_fixed.json')
    assert input_fixed['全構造監査合格'] is True and input_fixed['新損益読取'] is False
    assert input_fixed['入口配列数'] == 36 and input_fixed['悪化配列数'] == 12
    expected_input = {**causal['参照SHA256'], **causal['原本78SHA256'], **artifacts['SHA256'],
        'work/wave_v35/input_artifacts.json': design.digest(HERE / 'input_artifacts.json'),
        'work/wave_v35/input_causality_before_pnl.json': design.digest(HERE / 'input_causality_before_pnl.json')}
    assert input_fixed['SHA256'] == expected_input
    for name, expected in input_fixed['SHA256'].items():
        check(ROOT / name, expected)
    import conditional_runner
    assert conditional_runner.engine.CONDITIONAL_COLUMNS == engine['CONDITIONAL_COLUMNS']
    assert conditional_runner.engine.TRAIL_EVENT_COLUMNS == engine['TRAIL_EVENT_COLUMNS']
    for key, ready in inputs.items():
        assert conditional_runner.managers.make_config(fixed['manager'], key[1], ready) == conditional_runner.managers.make_config(design.manager(), key[1], ready)
    import supplementary_diagnostics
    supplemental = load(HERE / 'supplementary_design_fixed.json')
    check(HERE / 'supplementary_diagnostics.py', supplemental['実装SHA256'])
    check(HERE / 'conditional_design_fixed.json', supplemental['設計固定SHA256'])
    assert supplemental['新損益参照'] is False and supplemental['採用変更'] is False and supplemental['正式p値'] is False
    assert supplemental['選択工程全体の乱数化'] is False
    expected_branches = {mode['id']: supplementary_diagnostics.catalog(mode['id']) for mode in design.exit_modes()}
    assert supplemental['全分岐'] == expected_branches
    assert len(expected_branches) == 14 and expected_branches['A0'] == expected_branches['MIN'] == []
    for mode, branch in expected_branches.items():
        if mode in ('A0', 'MIN'):
            continue
        assert len(branch) == len({s['id'] for s in branch}) == 64
        assert {s['random_seed'] for s in branch} == {None, *range(1, 64)}
        assert sum(s['reverse_deterioration'] for s in branch) == 1
        assert all(s['signal_id'] == 'H019' and s['exit_mode_id'] == mode and s['adoption_scope'] is False
                   and s['role'] == 'supplemental' for s in branch)
    for name in ('conditional_engine_audit.py', 'conditional_engine_contract.md', 'build_engine_conditional.py',
                 'conditional_assessment_test.py', 'conditional_design.md', 'run_verified.py'):
        check(HERE / name)
    return {**counts, '実行可能': True, '探索固定SHA256': check(HERE / '探索条件の固定.json'),
            'SHA256': hashes, '採否条件変更': False, '新PnL参照': False, '現在保存物使用': False, 'API取得数': 0}


def freeze() -> dict:
    """機能: 起動前ガードと破損拒否検査の実装を固定する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    value = {'実装SHA256': design.digest(Path(__file__)), '拒否検査SHA256': design.digest(HERE / 'run_verified_test.json'),
             '拒否検査実装SHA256': design.digest(HERE / 'run_verified_test.py'),
             '採否条件変更': False, '全840を選別せず起動': True}
    path = HERE / 'run_verified_fixed.json'
    if path.exists():
        assert read(path) == value
    else:
        save(path, value)
    return value


def main() -> None:
    """機能: 全検査後だけ起動監査を保存し、指定時に固定840再生を開始する。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    assert 1 <= args.workers <= 64
    frozen = freeze()
    evidence = verify_sources()
    evidence.update({'確認日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
                     'ガード実装SHA256': frozen['実装SHA256'], 'ガード固定SHA256': design.digest(HERE / 'run_verified_fixed.json')})
    save(HERE / '起動前監査.json', evidence)
    if args.prepare:
        print('全840の因果・注文器・集計合成・固定指紋一致。新損益再生なし。', flush=True)
        return
    path = HERE / '主再生の起動証跡.json'
    records = read(path)['実行'] if path.exists() else []
    record = dict(evidence, 完了=False)
    records.append(record)
    save(path, {'実行': records})
    subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'conditional_runner.py'), '--workers', str(args.workers)], check=True)
    record.update(主再生済=True, 主再生の完了SHA256=design.digest(HERE / '主再生の完了.json'),
                  選択固定SHA256=design.digest(HERE / '選択固定.json'))
    save(path, {'実行': records})
    subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'supplementary_diagnostics.py'), '--workers', str(args.workers)], check=True)
    for name, expected in evidence['SHA256'].items():
        assert design.digest(ROOT / name) == expected, '再生前後の指紋変更: ' + name
    record.update(完了=True, 完了日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
                  主再生の完了SHA256=design.digest(HERE / '主再生の完了.json'),
                  補助診断SHA256=design.digest(HERE / '補助乱数診断.json'))
    save(path, {'実行': records})
    print('全840再生完了、起動前後の指紋一致。', flush=True)


if __name__ == '__main__':
    main()
