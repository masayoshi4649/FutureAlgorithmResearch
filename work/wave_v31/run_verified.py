"""損益前の構造監査を全件確認し、固定済みの420対照再生だけを起動する。"""

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

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parent
COUNTS = {'独立変形照合': 15, '同一行ゼロ遅延': 3, 'prefix列数': 30,
          '未来方向改変列数': 30, '未来時刻改変列数': 30,
          '上下反射列数': 15, '時刻平行移動列数': 15}
VARIANTS = {'V000': (0., 'identity'), 'V030': (1800., 'lag'),
            'V060': (3600., 'lag'), 'W030': (1800., 'start_only'), 'W060': (3600., 'start_only')}


def digest(path: Path) -> str:
    """機能: ファイルを分割読取りして指紋を得る。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read(path: Path) -> dict:
    """機能: UTF-8の固定JSONを読む。

    引数: path (Path)。返り値: 資料 (dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """機能: 監査証跡をUTF-8で保存する。

    引数: path (Path)、value (dict)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def verify_payload(fixed: dict, old: dict, audit: dict, keys: set) -> dict:
    """機能: 起動可否を決める全件集合と構造監査の内容を検算する。

    引数: fixed/old/audit (dict)、keys (set[tuple[str,str]])。
    返り値: 確認件数 (dict)。利益や採否の基準は追加しない。
    """
    assert fixed['signals'] == old['signals'] and fixed['managers'] == old['managers']
    assert fixed['own_signals'] == old['own_signals']
    signals = [s['id'] for s in fixed['signals']]
    managers = [m['id'] for m in fixed['managers']]
    assert len(signals) == len(set(signals)) == 12
    assert len(managers) == len(set(managers)) == 7 and set(managers) == {f'L{i:03}' for i in range(7)}
    variants = fixed['variants']
    assert len(variants) == 5 and {v['id']: (v['delay_seconds'], v['mode']) for v in variants} == VARIANTS
    assert (fixed['全組合せ数'], fixed['元条件数'], fixed['新補助対照数']) == (420, 84, 336)
    assert len(keys) == 26 and {s for _, s in keys} == {'TOPIX', 'NK225'}
    assert audit['構造検査合格'] is True and audit['損益参照前'] is True
    assert audit['売買再生実行'] is False and audit['現在データ使用'] is False and audit['API取得数'] == 0
    assert (audit['全入口数'], audit['全入力数'], audit['全変形数'], audit['全方向列数']) == (12, 312, 5, 4680)
    expected = {(s, session, symbol) for s in signals for session, symbol in keys}
    rows = audit['各入力']
    assert len(rows) == 312 and {(r['signal'], r['session'], r['symbol']) for r in rows} == expected
    for row in rows:
        assert row['価格ATRと元入力不変'] is True
        assert {name: row[name] for name in COUNTS} == COUNTS
        assert set(row['各変形SHA256']) == set(VARIANTS)
        for value in row['各変形SHA256'].values():
            assert isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)
    assert audit['検査件数'] == {name: count * 312 for name, count in COUNTS.items()}
    assert len(audit['元3列SHA256']) == 36 and len(audit['原本78SHA256']) == 78
    return {'全条件数': 420, '全入力数': 10920, '構造監査対象入力数': 312, '構造監査全方向列数': 4680}


def verify_sources() -> dict:
    """機能: 固定原資料と監査対象を現在の指紋へ結び、起動可能か検算する。

    引数: なし。返り値: 指紋と全件検査を含む証跡 (dict)。新損益は読まない。
    """
    tracked = {}

    def check(path: Path, expected: str | None = None) -> str:
        """機能: 同一パスを一度だけ検算して監査証跡に加える。

        引数: path (Path)、expected (str|None)。返り値: 確認した指紋 (str)。
        """
        name = path.resolve().as_posix()
        value = tracked.setdefault(name, digest(path)) if name not in tracked else tracked[name]
        assert expected is None or value == expected, f'固定指紋不一致: {path}'
        return value

    fixed_path = HERE / '探索条件の固定.json'
    fixed = read(fixed_path)
    old_path = WORK / 'wave_v30/探索条件の固定.json'
    old = read(old_path)
    protocol_path = HERE / 'freshness_diagnostic_fixed.json'
    protocol = read(protocol_path)
    for material in (fixed, old, protocol):
        for name, expected in material['SHA256'].items():
            check(WORK / name, expected)
    audit_path = HERE / 'lag_causality_before_pnl.json'
    audit = read(audit_path)
    assert audit == read(HERE / 'lag_causality_audit.json')
    inputs_path = WORK / 'wave_v23/inputs.pkl'
    check(inputs_path, audit['入力SHA256'])
    with inputs_path.open('rb') as source:
        keys = set(pickle.load(source))
    counts = verify_payload(fixed, old, audit, keys)
    source_paths = {(WORK / 'wave_v30' / folder / (s['id'] + '.npz')).resolve().as_posix()
                    for s in fixed['signals'] for folder in ('directions', 'contexts', 'contexts_own')}
    assert {Path(p).resolve().as_posix() for p in audit['元3列SHA256']} == source_paths
    for name, expected in audit['元3列SHA256'].items():
        check(Path(name), expected)
    raw_paths = {f'{folder}/{symbol}/{session}{extension}' for session, symbol in keys
                 for folder, extension in (('book', '.jsonl'), ('candle_1min', '.csv'), ('candle_5min', '.csv'))}
    assert set(audit['原本78SHA256']) == raw_paths
    for name, expected in audit['原本78SHA256'].items():
        check(ROOT / name, expected)
    binding = audit['監査固定']
    assert binding == read(HERE / 'lag_causality_fixed.json')
    for path, field in ((HERE / 'lag_causality_audit.py', '監査コードSHA256'),
                        (HERE / 'lag_design.py', 'lag_design_SHA256'),
                        (HERE / 'lag_audit_plan.md', '設計計画SHA256'),
                        (WORK / 'wave_v30/context_structure_before_pnl.json', '旧構造監査SHA256')):
        check(path, binding[field])
    assert audit['lag_design_SHA256'] == binding['lag_design_SHA256']
    for path in (fixed_path, old_path, protocol_path, audit_path, HERE / 'lag_causality_audit.json', HERE / 'lag_causality_fixed.json'):
        check(path)
    return {**counts, '開始前検査合格': True, '参照資料SHA256': tracked,
            '探索固定SHA256': check(fixed_path), '構造監査SHA256': check(audit_path),
            '新損益読取': False, '現在データ使用': False, 'API取得数': 0}


def freeze() -> dict:
    """機能: 閾値や選択を変えない起動ガードの仕様と実装を固定する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    value = {'規則': '全420条件・312構造監査・元78原本・固定実装指紋を確認してから固定runnerを起動。損益や採否による絞込みなし。',
             '実装SHA256': digest(Path(__file__)), '合成検査SHA256': digest(HERE / 'run_verified_test.json'),
             '閾値順位候補数変更': False, '現在データ使用': False, 'API取得数': 0}
    path = HERE / 'run_verified_fixed.json'
    if path.exists():
        assert read(path) == value
    else:
        save(path, value)
    return value


def main() -> None:
    """機能: 起動前証跡の保存後にだけ凍結済みrunnerを子処理で呼ぶ。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=12)
    args = parser.parse_args()
    assert 1 <= args.workers <= 64
    fixed = freeze()
    evidence = verify_sources()
    evidence.update({'確認時刻': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
                     'ガード固定SHA256': digest(HERE / 'run_verified_fixed.json'),
                     'ガード実装SHA256': fixed['実装SHA256'], '起動実行': not args.prepare})
    if args.prepare:
        save(HERE / '起動前ガードの準備.json', evidence)
        print('全420条件・構造監査312入力・原本78指紋の起動前ガード合格。売買再生なし。', flush=True)
        return
    path = HERE / '主再生の起動証跡.json'
    history = read(path).get('実行', []) if path.exists() else []
    record = dict(evidence, 完了=False)
    history.append(record)
    save(path, {'実行': history})
    subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'lag_runner.py'), '--workers', str(args.workers)], check=True)
    for name, expected in evidence['参照資料SHA256'].items():
        assert digest(Path(name)) == expected, f'実行中の参照変更: {name}'
    record['完了'] = True
    record['完了時刻'] = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()
    record['主再生の完了SHA256'] = digest(HERE / '主再生の完了.json')
    save(path, {'実行': history})
    print('起動前後の固定指紋一致。全420条件の固定runner完了。', flush=True)


if __name__ == '__main__':
    main()
