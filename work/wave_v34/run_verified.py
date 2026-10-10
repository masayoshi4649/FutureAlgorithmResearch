"""新損益前の仕様・入力因果・注文器合成を束ね、確認後だけ全192を起動する。"""

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
import scheduler_design as design

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
    """機能: 主192範囲・監査完了・全入力の実数に基づく件数を検査する。

    引数: fixed/causal/engine/runner/inputs (dict)。返り値: 検査件数 (dict)。
    """
    assert fixed['conditions'] == design.catalog()
    assert fixed['全条件数'] == 192 and fixed['主条件数'] == 48 and fixed['診断数'] == 144
    assert fixed['全セッション'] == list(design.SESSIONS) and fixed['共通評価7セッション'] == list(design.SESSIONS[6:])
    assert fixed['指定波'] == design.waves()
    assert len(inputs) == 26 and {key[0] for key in inputs} == set(design.SESSIONS)
    assert set(inputs) == {(s, symbol) for s in design.SESSIONS for symbol in ('TOPIX', 'NK225')}
    assert causal['構造監査合格'] is True and causal['全監査完了'] is True
    for name in ('新損益読取', '売買再生', '現在保存物使用'):
        assert causal[name] is False
    assert causal['API取得数'] == 0 and causal['対象入口ID'] == list(design.SIGNAL_IDS)
    assert causal['全セッション'] == fixed['全セッション'] and causal['共通評価7セッション'] == fixed['共通評価7セッション']
    assert causal['初期6セッション'] == list(design.SESSIONS[:6])
    assert causal['合成']['合成合格'] is True and all(v is True for v in causal['合成'].values())
    atr = causal['ATR']
    assert atr['全区間数'] == 26 and atr['原本行数'] == sum(len(v['last']) for v in inputs.values())
    assert atr['prefix比較数'] == atr['未来ATR改変比較数'] == 104
    rows = unique(atr['rows'], ('session', 'symbol'))
    assert set(rows) == set(inputs)
    for key, row in rows.items():
        assert row['原本行数'] == len(inputs[key]['last'])
        for name in ('入口ATR不変', '独立過去参照一致', 'prefix2点一致', '未来ATR2点一致'):
            assert row[name] is True
    entry = causal['入口']
    assert entry['全区間数'] == 312
    assert entry['prefix比較数'] == entry['未来方向改変比較数'] == 1248
    rows = unique(entry['rows'], ('id', 'session', 'symbol'))
    assert set(rows) == {(signal, *key) for signal in design.SIGNAL_IDS for key in inputs}
    assert set(entry['入口SHA256']) == set(design.SIGNAL_IDS)
    for row in rows.values():
        assert all(row[name] is True for name in ('v27_v30_v31同一', '独立過去参照一致', 'prefix2点一致', '未来方向2点一致'))
    assert engine['全合格'] is True and engine['合成全合格'] is True
    assert engine['合成件数'] == len(engine['合成検査']) == 9
    assert len({r['検査'] for r in engine['合成検査']}) == 9 and all(r['一致'] is True for r in engine['合成検査'])
    assert set(engine['既知互換']) == {'通常A0旧6一致', '通常At旧6一致', 'A0制御旧6一致', '新設準備対応検査'}
    assert all(value == 26 for value in engine['既知互換'].values())
    for name in ('新しいAt制御の実相場再生', '成績による選別', '現在保存物使用'):
        assert engine[name] is False
    assert engine['API取得数'] == 0 and engine['元ファイル不変'] is True
    assert engine['PREPARE_COLUMNS'] == ['prepare_id', 'row', 'side', 'level', 'initial_atr', 'expiry_time', 'qty']
    assert engine['ENTRY_PREPARATION_COLUMNS'] == ['campaign', 'fill_row', 'prepare_id', 'prepare_row']
    for name in ('監査完了', '部分返済と前組の実現益を区別', '含み利益なし損失組を隠さない', '取引数平均中央値', '空集合', '準備行のみ許可', '見送り4理由排他'):
        assert runner[name] is True
    assert runner['破損拒否数'] == 3
    return {'全条件数': 192, '主条件数': 48, '診断数': 144, '全入力数': 4992, '全指定波数': 1536,
            '入力原本行数': atr['原本行数'], '入口因果区間数': 312, '合成注文経路数': 9}


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
    planned = load(HERE / 'scheduler_design_fixed.json')
    assert planned['conditions'] == fixed['conditions'] and planned['規則'] == design.rules()
    assert planned['signals'] == design.signals() and planned['manager'] == design.manager() and planned['variants'] == design.variants()
    for group in (fixed['SHA256'], planned['参照SHA256']):
        for name, expected in group.items():
            check(ROOT / name, expected)
    with (HERE.parent / 'wave_v23/inputs.pkl').open('rb') as stream:
        inputs = pickle.load(stream)
    causal = load(HERE / 'input_causality_before_pnl.json')
    engine = load(HERE / 'scheduler_engine_audit.json')
    engine_fixed = load(HERE / 'engine_scheduler_fixed.json')
    for name, expected in engine_fixed['参照SHA256'].items():
        check(HERE / name, expected)
    runner_audit = load(HERE / 'runner_synthetic_audit.json')
    counts = verify_payload(fixed, causal, engine, runner_audit, inputs)
    expected_raw = {f'{folder}/{key[1]}/{key[0]}.{extension}' for key in inputs
                    for folder, extension in (('book', 'jsonl'), ('candle_1min', 'csv'), ('candle_5min', 'csv'))}
    assert set(causal['原本78SHA256']) == expected_raw and len(expected_raw) == 78
    for group in ('参照SHA256', '原本78SHA256'):
        for name, expected in causal[group].items():
            check(ROOT / name, expected)
    check(HERE / 'engine_scheduler.py', engine['engine_SHA256'])
    check(HERE / 'scheduler_engine_audit.py', engine['検査実装SHA256'])
    for name, expected in engine['元SHA256'].items():
        check(Path(name), expected)
    check(HERE / 'scheduler_runner.py', runner_audit['実装SHA256'])
    check(HERE / 'runner_synthetic_audit.py', runner_audit['検査SHA256'])
    assessment = load(HERE / 'scheduler_assessment_fixed.json')
    check(HERE / 'scheduler_assessment.py', assessment['実装SHA256'])
    check(HERE / 'scheduler_design_fixed.json', assessment['設計固定SHA256'])
    check(HERE / 'scheduler_assessment_test.json', assessment['人工検査SHA256'])
    tests = load(HERE / 'scheduler_assessment_test.json')
    assert tests['全検査合格'] is True and tests['人工検査件数'] == len(tests['検査']) == 21
    assert all(r['一致'] is True for r in tests['検査'])
    assert tests['新PnL参照'] is False and tests['現在保存物使用'] is False and tests['API取得数'] == 0
    check(HERE / 'scheduler_design.py', tests['設計実装SHA256'])
    check(HERE / 'scheduler_assessment.py', tests['判定実装SHA256'])
    import scheduler_input_audit
    input_audit = scheduler_input_audit.source
    entries = input_audit.load_entries(inputs)
    for signal, columns in entries.items():
        assert input_audit.array_hash(columns) == causal['入口']['入口SHA256'][signal]
    for delay in (0, 300):
        columns = {key: input_audit.make_tracking_atr(ready, delay)[0] for key, ready in inputs.items()}
        assert input_audit.array_hash(columns) == causal['ATR']['追跡ATR配列SHA256'][str(delay)]
    import scheduler_runner
    assert scheduler_runner.engine.PREPARE_COLUMNS == engine['PREPARE_COLUMNS']
    assert scheduler_runner.engine.ENTRY_PREPARATION_COLUMNS == engine['ENTRY_PREPARATION_COLUMNS']
    for key, ready in inputs.items():
        assert scheduler_runner.managers.make_config(fixed['manager'], key[1], ready) == scheduler_runner.managers.make_config(design.manager(), key[1], ready)
    for name in ('scheduler_engine_audit.py', 'engine_scheduler_contract.md', 'build_engine_scheduler.py',
                 'scheduler_assessment_test.py', 'scheduler_design.md', 'run_verified.py'):
        check(HERE / name)
    return {**counts, '実行可能': True, '探索固定SHA256': check(HERE / '探索条件の固定.json'),
            'SHA256': hashes, '採否条件変更': False, '新PnL参照': False, '現在保存物使用': False, 'API取得数': 0}


def freeze() -> dict:
    """機能: 起動前ガードと破損拒否検査の実装を固定する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    value = {'実装SHA256': design.digest(Path(__file__)), '拒否検査SHA256': design.digest(HERE / 'run_verified_test.json'),
             '拒否検査実装SHA256': design.digest(HERE / 'run_verified_test.py'),
             '採否条件変更': False, '全192を選別せず起動': True}
    path = HERE / 'run_verified_fixed.json'
    if path.exists():
        assert read(path) == value
    else:
        save(path, value)
    return value


def main() -> None:
    """機能: 全検査後だけ起動監査を保存し、指定時に固定192再生を開始する。

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
        print('全192の因果・注文器・集計合成・固定指紋一致。新損益再生なし。', flush=True)
        return
    path = HERE / '主再生の起動証跡.json'
    records = read(path)['実行'] if path.exists() else []
    record = dict(evidence, 完了=False)
    records.append(record)
    save(path, {'実行': records})
    subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'scheduler_runner.py'), '--workers', str(args.workers)], check=True)
    for name, expected in evidence['SHA256'].items():
        assert design.digest(ROOT / name) == expected, '再生前後の指紋変更: ' + name
    record.update(完了=True, 完了日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
                  主再生の完了SHA256=design.digest(HERE / '主再生の完了.json'))
    save(path, {'実行': records})
    print('全192再生完了、起動前後の指紋一致。', flush=True)


if __name__ == '__main__':
    main()
