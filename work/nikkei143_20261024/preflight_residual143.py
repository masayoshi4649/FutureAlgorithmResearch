"""第三巡の登録前に、人工試験と保存済み源の親占有を独立照合する。"""

import io
import unittest
import numpy as np
import audit143 as audit
import run143_round3 as runner


def main():
    """
    機能: 人工試験を再実行し、残玉変更前の四源で親の実保有が重ならないことを調べる。
    引数: なし。
    返り値: None。新しい金融再生をせず、検査結果を別JSONに保存する。
    """
    output = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        ['test_profit_residual143', 'test_audit_round3_143'])
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    first = {row['session']:row for row in audit.read(audit.HERE/'第一巡結果143.json')['cache']}
    second = {row['session']:row for row in audit.read(audit.HERE/'第二巡結果143.json')['cache']}
    checks, overlaps = [], []
    for scene in first:
        sources, _, _ = runner.sources(scene, first, second)
        for source, orders in sources.items():
            spans = []
            for parent in np.unique(orders[:, 2]):
                rows = orders[orders[:, 2] == parent]
                spans.append(dict(parent=int(parent), first_decision=int(rows[:, 1].min()),
                    final_fill=int(rows[:, 0].max())))
            spans.sort(key=lambda row:row['first_decision'])
            conflicts = []
            for index, span in enumerate(spans):
                for old in spans[:index]:
                    if old['final_fill'] > span['first_decision']:
                        conflicts.append(dict(old=old, new=span))
            checks.append(dict(session=scene, source=source, parents=len(spans), overlaps=len(conflicts)))
            overlaps.extend(dict(session=scene, source=source, **item) for item in conflicts)
    payload = dict(status='全件合格' if result.wasSuccessful() and not overlaps else '要確認',
        人工試験数=result.testsRun, 成功=result.wasSuccessful(), 保存源口座数=len(checks),
        元親重複数=len(overlaps), 保存源検査=checks, 元親重複=overlaps,
        新金融再生=0, 人工試験出力=output.getvalue(),
        実装SHA={name:audit.digest(audit.HERE/name) for name in (
            'profit_residual143.py', 'run143_round3.py', 'test_profit_residual143.py',
            'audit143_round3.py', 'test_audit_round3_143.py', 'preflight_residual143.py')},
        定義='元親の最終実約定原行より、次親の初回判断原行が厳密に早い場合だけ重複。先行返済約定と次親判断が同じ原行なら重複としない。')
    audit.save(audit.HERE/'第三巡人工検査と源占有の独立照合143.json', payload)
    print({key:payload[key] for key in ('status', '人工試験数', '保存源口座数', '元親重複数')})
    assert result.wasSuccessful() and not overlaps


if __name__ == '__main__':
    main()
