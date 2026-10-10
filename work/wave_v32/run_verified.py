"""固定148条件と損益前の両段因果・注文器監査を結合してから主再生を起動する。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import subprocess
import sys
from zoneinfo import ZoneInfo

import numpy as np
import selector_design as design

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FUTURE_COUNTS = {'T_R未来足板価格ATR改変': 52, 'A未来足出来高価格改変': 78,
                 'A追加60秒の未公開足変更': 78, 'T_R上下反射': 52,
                 'A上下反射で同じ要求': 78, 'P02価格撤回版の数量OFI除去一致': 26,
                 'B全近傍と13場初の未来影削除改変': 65}


def read(path: Path) -> dict:
    """機能: UTF-8のJSON資料を読む。

    引数: path (Path)。返り値: 資料 (dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """機能: 指紋と起動証跡を有限JSONで保存する。

    引数: path (Path)、value (dict)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def verify_payload(fixed: dict, protocol: dict, causal: dict, engine: dict, keys: set) -> dict:
    """機能: 全148の集合と、未完成ではない因果・注文器監査を検算する。

    引数: fixed/protocol/causal/engine (dict)、keys (set[tuple[str,str]])。
    返り値: 検査済み件数 (dict)。新損益を読まない。
    """
    assert fixed['conditions'] == protocol['条件'] == design.catalog()
    assert (fixed['全条件数'], fixed['主比較数'], fixed['反証数']) == (148, 6, 142)
    assert fixed['全セッション'] == protocol['セッション順']
    assert fixed['初期6セッション'] == protocol['初期化6'] and fixed['共通評価7セッション'] == protocol['主評価7']
    assert len(fixed['全セッション']) == 13 and len(fixed['共通評価7セッション']) == 7
    assert set(map(tuple, protocol['全入力キー'])) == keys and len(keys) == 26
    assert keys == {(s, symbol) for s in fixed['全セッション'] for symbol in ('TOPIX', 'NK225')}
    assert causal['構造監査合格'] is True and causal['全監査完了'] is True
    assert causal['新PnL参照'] is False and causal['売買再生実行'] is False
    assert causal['API取得数'] == 0 and causal['現在データ使用'] is False
    assert causal['T旧H019全26方向一致'] is True
    assert causal['選択3窓prefix区間数'] == 156 and causal['T_R方向prefix区間数'] == 104
    assert causal['合成']['全合成合格'] is True and causal['合成']['乱数合成数'] == 128
    assert len(causal['合成']['検査']) == len(set(causal['合成']['検査'])) == 9
    assert causal['合成足']['最早R要求までの分'] == {'24': 60., '30': 90., '36': 90.}
    assert causal['合成足']['合成確定足の上下反射で選択不変'] is True
    assert set(causal['入口配列SHA256']) == {'T', 'R'} and set(causal['要求3窓SHA256']) == {'24', '30', '36'}
    added = causal['追加監査']
    assert added['追加監査合格'] is True and added['新PnL参照'] is False and added['売買再生実行'] is False
    assert added['API取得数'] == 0 and added['現在データ使用'] is False
    assert {key: added['検査件数'][key] for key in FUTURE_COUNTS} == FUTURE_COUNTS
    assert len(causal['原本78SHA256']) == 78
    assert engine['全合格'] is True and engine['合成全合格'] is True and engine['旧固定T完全一致区間数'] == 26
    assert engine['新規選択損益の実行'] is False and engine['API取得数'] == 0 and engine['現在保存物使用'] is False
    assert engine['旧原本不変'] is True
    checks = engine['合成検査']
    assert len(checks) == len({r['検査'] for r in checks}) == engine['合成境界件数'] == 20 and all(r['一致'] is True for r in checks)
    assert len(engine['SELECTION_COLUMNS']) == len(set(engine['SELECTION_COLUMNS'])) == 20
    assert len(engine['EVENT_COLUMNS']) == len(set(engine['EVENT_COLUMNS'])) == 15
    assert len(engine['EVENT_NAMES']) == 12 and len(engine['PHASE_NAMES']) == 3
    return {'全条件数': 148, '主比較数': 6, '反証数': 142, '全入力数': 3848, '主評価入力数': 2072,
            '入口prefix検査数': 104, 'A全窓prefix検査数': 156,
            'B全近傍未来影検査数': 65, '注文器合成数': 20, '旧固定T一致数': 26}


def verify_sources() -> dict:
    """機能: 全固定元・原本・監査実体を現在の実装指紋へ結合する。

    引数: なし。返り値: 起動可否と読取り資料の指紋 (dict)。新しい損益は読まない。
    """
    hashes = {}

    def check(path: Path, expected: str | None = None) -> str:
        """機能: 同一資料を重複読取りせず指紋を検査する。

        引数: path (Path)、expected (str|None)。返り値: 確認した指紋 (str)。
        """
        name = path.resolve().as_posix()
        if name not in hashes:
            hashes[name] = design.digest(path)
        assert expected is None or hashes[name] == expected, '固定指紋不一致: ' + name
        return hashes[name]

    fixed_path = HERE / '探索条件の固定.json'
    fixed, protocol = read(fixed_path), read(HERE / 'selection_fixed.json')
    for name, expected in fixed['SHA256'].items():
        check(ROOT / name, expected)
    for name, expected in protocol['SHA256'].items():
        check(HERE.parent / name, expected)
    inputs_path = HERE.parent / 'wave_v23/inputs.pkl'
    with inputs_path.open('rb') as source:
        inputs = pickle.load(source)
    causal = read(HERE / 'selector_causality_before_pnl.json')
    engine = read(HERE / 'engine_selector_audit.json')
    counts = verify_payload(fixed, protocol, causal, engine, set(inputs))
    first = read(HERE / 'selector_signal_audit.json')
    assert {k: v for k, v in causal.items() if k not in ('全監査完了', '追加監査', '参照SHA256')} == {k: v for k, v in first.items() if k != '参照SHA256'}
    assert causal['追加監査'] == read(HERE / 'selector_future_audit.json')
    assert set(first['参照SHA256']) <= set(causal['参照SHA256'])
    for name, expected in first['参照SHA256'].items():
        assert causal['参照SHA256'][name] == expected
    required = {'work/wave_v32/' + name for name in ('selector_signals.py', 'selector_signal_audit.py',
                 'selector_future_audit.py', 'selector_signal_audit.json', 'selector_future_audit.json', 'audited_entries.npz')}
    assert required <= set(causal['参照SHA256'])
    for name, expected in causal['参照SHA256'].items():
        check(ROOT / name, expected)
    assert causal['追加監査']['コードSHA256'] == check(HERE / 'selector_future_audit.py')
    raw_paths = {f'{folder}/{symbol}/{session}{extension}' for session, symbol in inputs
                 for folder, extension in (('book', '.jsonl'), ('candle_1min', '.csv'), ('candle_5min', '.csv'))}
    assert set(causal['原本78SHA256']) == raw_paths
    for name, expected in causal['原本78SHA256'].items():
        check(ROOT / name, expected)
    assert engine['engine_SHA256'] == check(HERE / 'engine_selector.py')
    old_paths = {(HERE.parent / name).resolve().as_posix() for name in ('wave_v28/engine_context.py', 'wave_v23/inputs.pkl', 'wave_v27/directions/H019.npz')}
    assert {Path(name).resolve().as_posix() for name in engine['旧原本SHA256']} == old_paths
    for name, expected in engine['旧原本SHA256'].items():
        check(Path(name), expected)
    with np.load(HERE / 'audited_entries.npz') as archive:
        assert set(archive.files) == {f'{b}|{k[0]}|{k[1]}' for b in ('T', 'R') for k in inputs}
        for branch in ('T', 'R'):
            fingerprint = hashlib.sha256()
            for key in sorted(inputs):
                values = archive[f'{branch}|{key[0]}|{key[1]}']
                assert values.dtype == np.int8 and len(values) == len(inputs[key]['seq']) and np.isin(values, [-1, 0, 1]).all()
                fingerprint.update(str(key).encode())
                fingerprint.update(values.tobytes())
            assert fingerprint.hexdigest() == causal['入口配列SHA256'][branch]
    assessment = read(HERE / 'selection_assessment_fixed.json')
    assert assessment['新閾値追加'] is False and assessment['候補対象'] == ['S002', 'S003']
    check(HERE / 'selection_assessment.py', assessment['実装SHA256'])
    check(HERE / 'selection_fixed.json', assessment['事前規則SHA256'])
    tests = read(HERE / 'selector_design_test.json')
    assert tests['合成全合格'] is True and tests['新損益参照'] is False and tests['売買再生実行'] is False
    check(HERE / 'selector_design.py', tests['設計実装SHA256'])
    check(HERE / 'selection_assessment.py', tests['独立判定実装SHA256'])
    run_tests = read(HERE / 'runner_synthetic_audit.json')
    assert run_tests['合成のみ'] is True and run_tests['全件合格'] is True
    assert run_tests['実相場損益参照'] is False and run_tests['API取得数'] == 0
    cases = run_tests['検査']
    assert len(cases) == 3 and {r['対象'] for r in cases} == {'無取引', '整数半分の利確', '同方向切替と再準備'}
    assert all(r['注文から枝損益一致'] is True and r['未定義価格の有限JSON往復'] is True for r in cases)
    for name, expected in run_tests['参照SHA256'].items():
        check(Path(name), expected)
    for name in ('探索条件の固定.json', 'selection_fixed.json', 'selector_causality_before_pnl.json',
                 'engine_selector_audit.py', 'engine_selector_audit.json', 'selection_assessment_fixed.json',
                 'selector_design_test.py', 'selector_design_test.json', 'selection_judgment.py',
                 'runner_synthetic_audit.py', 'runner_synthetic_audit.json'):
        check(HERE / name)
    return {**counts, '実行可能': True, '参照資料SHA256': hashes,
            '探索固定SHA256': check(fixed_path), '選択規則SHA256': check(HERE / 'selection_fixed.json'),
            '新損益参照': False, '現在データ使用': False, 'API取得数': 0}


def freeze() -> dict:
    """機能: 採否条件を変えない起動ガードの実装と拒否試験を固定する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    value = {'実装SHA256': design.digest(Path(__file__)), '合成検査SHA256': design.digest(HERE / 'run_verified_test.json'),
             '規則': '全148集合・両段信号因果・注文器20合成/旧26一致・runner3合成・元78・監査元SHAを確認してだけ固定runnerを起動。',
             '採否閾値変更': False, '損益選別': False}
    path = HERE / 'run_verified_fixed.json'
    if path.exists():
        assert read(path) == value
    else:
        save(path, value)
    return value


def main() -> None:
    """機能: 起動前監査を保存し、成功後だけ全148の固定再生を実行する。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    assert 1 <= args.workers <= 64
    fixed = freeze()
    evidence = verify_sources()
    evidence.update({'確認時刻': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
                     'ガード実装SHA256': fixed['実装SHA256'], 'ガード固定SHA256': design.digest(HERE / 'run_verified_fixed.json')})
    save(HERE / '起動前監査.json', evidence)
    if args.prepare:
        print('全148の範囲・両段因果・注文器・原本SHAが一致。売買再生なし。', flush=True)
        return
    path = HERE / '主再生の起動証跡.json'
    history = read(path)['実行'] if path.exists() else []
    record = dict(evidence, 完了=False)
    history.append(record)
    save(path, {'実行': history})
    subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'selection_runner.py'), '--workers', str(args.workers)], check=True)
    for name, expected in evidence['参照資料SHA256'].items():
        assert design.digest(Path(name)) == expected, '再生中の資料変更: ' + name
    record.update(完了=True, 完了時刻=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
                  主再生の完了SHA256=design.digest(HERE / '主再生の完了.json'))
    save(path, {'実行': history})
    print('全148の再生を完了。全固定指紋は起動前後一致。', flush=True)


if __name__ == '__main__':
    main()
