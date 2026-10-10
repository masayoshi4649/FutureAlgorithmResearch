"""起動前監査の不合格・旧指紋を意図的に混ぜ、拒否されることを確認する。"""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch
import partial_startup_guard as guard


def main() -> None:
    """機能: 実在する結果前監査と人工破損を検査する。

    引数: なし。返り値: なし (None)。探索固定・売買再生は実行しない。
    """
    runner = guard.runner
    guard.prerequisities()
    read = runner.read
    corruptions = (
        ('partial_engine_audit', '全合格', False),
        ('partial_engine_audit', '旧A0完全一致入力数', 25),
        ('partial_engine_audit', '新方針の実相場損益再生', True),
        ('partial_engine_audit', 'engine_SHA256', '0'*64),
        ('shadow_plan_independent_audit', '計画prefix数', 51),
        ('shadow_plan_independent_audit', '新しい実枠制御の損益計算', True),
        ('partial_runner_synthetic', '全合格', False),
        ('partial_runner_synthetic', '人工再生数', 1235),
        ('partial_accounting_oracles', '破損拒否数', 0),
        ('partial_accounting_oracles', '新実データ損益', True),
        ('partial_assessment_test', '全検査合格', False),
        ('partial_assessment_test', '新損益読取', True))
    checks = []
    for name, field, value in corruptions:
        def changed(path):
            """機能: 対象監査の一項目だけをメモリで破損させる。

            引数: path (Path)。返り値: 監査内容 (dict)。実ファイルは変更しない。
            """
            result = deepcopy(read(path))
            if path.name == name+'.json': result[field] = value
            return result
        rejected = False
        with patch.object(runner, 'read', changed):
            try: guard.prerequisities()
            except AssertionError: rejected = True
        assert rejected, (name, field)
        checks.append(dict(対象=name, 項目=field, 拒否=True))
    runner.save(runner.HERE/'partial_startup_guard_test.json', dict(全合格=True, 破損拒否数=len(checks),
        新実データ損益=False, 検査=checks, ガードSHA256=runner.digest(runner.HERE/'partial_startup_guard.py')))
    print(f'起動ガードの人工破損{len(checks)}件を拒否。新売買なし。', flush=True)


if __name__ == '__main__':
    main()
