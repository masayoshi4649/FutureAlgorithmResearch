"""独立監査だけの速度改訂と、旧全完了実体の保存・同値を記録する。"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

import conditional_accounting_audit as audit

HERE, ROOT = audit.HERE, audit.ROOT
read, save, digest = audit.read, audit.save, audit.digest


def snapshot() -> dict:
    """機能: 旧ジョブ停止後の全完了監査を安全な同一作業内へ保存する。

    引数: なし。返り値: 改訂前記録 (dict)。呼出前に旧処理の停止と15同値の完了を確認する。
    """
    probe = read(HERE / 'performance_probe_equivalence.json')
    assert probe['全値同一'] and probe['条件数'] == 15 and probe['入力数'] == 390
    source = (HERE / 'accounting_details').resolve()
    destination = (HERE / 'accounting_v1/accounting_details').resolve()
    source.relative_to(HERE.resolve()); destination.relative_to(HERE.resolve())
    assert source.is_dir() and not destination.exists()
    paths = sorted(source.glob('*.json.gz'))
    assert len(paths) >= 15
    records = [read(p) for p in paths]
    assert all(r.get('監査版') is None and r['全入力数'] == 26 for r in records)
    assert not (HERE / 'accounting_audit.json').exists(), '旧版全完了との混同を防ぐ'
    hashes = {p.name: digest(p) for p in paths}
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    source.mkdir()
    assert hashes == {p.name: digest(p) for p in destination.glob('*.json.gz')}
    files = ('conditional_accounting_audit.py', 'conditional_audit_helpers.py', 'accounting_fixed.json', 'accounting_selftest.json')
    for name in files:
        shutil.copy2(HERE / name, destination.parent / name)
        assert digest(HERE / name) == digest(destination.parent / name)
    relocation = {(source / p.name).relative_to(ROOT).as_posix(): (destination / p.name).relative_to(ROOT).as_posix() for p in paths}
    value = dict(改訂日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        理由='同じ全件検査の速度改善。数値比較器の一巡化と有限配列の極値走査だけを変更する。',
        旧完了条件数=len(records), 旧完了条件IDs=[r['id'] for r in records],
        旧完了実体SHA256={(destination / name).relative_to(ROOT).as_posix(): sha for name, sha in hashes.items()},
        旧参照移設対応=relocation,
        旧監査実装SHA256={name: digest(HERE / name) for name in files[:2]},
        旧監査固定SHA256=digest(HERE / 'accounting_fixed.json'),
        新監査固定SHA256=digest(HERE / 'accounting_fixed_v2.json'),
        既15同値成果SHA256=digest(HERE / 'performance_probe_equivalence.json'),
        売買条件変更=False, 入力変更=False, 成績変更=False, 採否基準変更=False,
        監査対象変更=False, 検査閾値変更=False, 全840を新版で再実施=True, 旧版全監査完了ではない=True)
    save(HERE / 'accounting_revision_plan.json', value)
    return value


def finalize() -> dict:
    """機能: 旧全完了実体の同値と主840・補助64の全新版実施を最終記録へ結ぶ。

    引数: なし。返り値: 最終改訂記録 (dict)。検査未完了なら失敗する。
    """
    plan = read(HERE / 'accounting_revision_plan.json')
    main = read(HERE / 'accounting_audit.json')
    extra = read(HERE / 'supplementary/accounting_audit.json')
    assert main['全監査合格'] and main['対象条件数'] == 840 and main['全入力数'] == 21840
    assert extra['全監査合格'] and extra['対象条件数'] == 64 and extra['全入力数'] == 1664
    assert main['監査版'] == extra['監査版'] == 2
    fixed_sha = digest(HERE / 'accounting_fixed_v2.json')
    assert main['監査固定SHA256'] == extra['監査固定SHA256'] == fixed_sha == plan['新監査固定SHA256']
    for record in [*main['条件'], *extra['条件']]:
        assert record['監査版'] == 2 and record['監査固定SHA256'] == fixed_sha
    evidence = []
    for path, sha in plan['旧完了実体SHA256'].items():
        old_path = ROOT / path
        assert digest(old_path) == sha
        old = read(old_path); new_path = HERE / 'accounting_details' / old_path.name
        new = read(new_path)
        assert new['監査版'] == 2 and new['監査固定SHA256'] == fixed_sha and new['旧版実体同値'] is True
        assert {k: v for k, v in new.items() if k not in ('監査版', '監査固定SHA256', '旧版実体同値')} == old
        evidence.append(dict(id=old['id'], 旧実体=path, 旧SHA256=sha,
            新実体=new_path.relative_to(ROOT).as_posix(), 新SHA256=digest(new_path), 全値同一=True))
    assert len(evidence) == plan['旧完了条件数'] == main['旧版実体同値条件数']
    proof = dict(全既完了同値=True, 条件数=len(evidence), 入力数=len(evidence) * 26, 条件=evidence)
    save(HERE / 'accounting_v1_equivalence.json', proof)
    files = ('fast_comparison.py', 'conditional_accounting_audit_v2.py', 'accounting_reconstruction_vectorized.py',
        'comparison_equivalence.json', 'accounting_selftest_v2.json', 'performance_probe_equivalence.json',
        'reconstruction_vectorized_build.json', 'reconstruction_vectorized_audit.json',
        'build_accounting_reconstruction_vectorized.py', 'reconstruction_vectorized_audit.py',
        'accounting_fixed_v2.json', 'accounting_v1_equivalence.json', 'accounting_revision_plan.json',
        'accounting_audit.json', 'supplementary/accounting_audit.json', 'accounting_v1_stop.json',
        'accounting_v1/conditional_accounting_audit.py', 'accounting_v1/conditional_audit_helpers.py',
        'accounting_v1/accounting_fixed.json', 'accounting_v1/accounting_selftest.json')
    output = {**plan, '改訂完了': True, '全既完了同値成果SHA256': digest(HERE / 'accounting_v1_equivalence.json'),
        '主新版完了条件数': 840, '補助新版完了条件数': 64, '混在なし': True,
        '参照SHA256': {(HERE / name).relative_to(ROOT).as_posix(): digest(HERE / name) for name in files},
        '記録実装SHA256': digest(Path(__file__))}
    save(HERE / 'accounting_revision.json', output)
    return output


def main() -> None:
    """機能: 明示指定された旧版保存又は新版完了記録だけを実行する。

    引数: --snapshot又は--finalize (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(); group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--snapshot', action='store_true'); group.add_argument('--finalize', action='store_true')
    args = parser.parse_args(); value = snapshot() if args.snapshot else finalize()
    print({k: value[k] for k in ('旧完了条件数', '監査対象変更', '検査閾値変更')}, flush=True)


if __name__ == '__main__':
    main()
