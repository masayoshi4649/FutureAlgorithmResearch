"""独立検査した場末会計の限定補正を、旧版を残して適用する。"""

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import adaptive_cash_revision_checks as checks
import adaptive_cash_revision_guard as guard


def main() -> None:
    """機能: 場末2領域以外の本文同一を再確認して候補を適用する。

    引数: なし。返り値: なし (None)。売買や数値計算へ変更を加えない。
    """
    runner=guard.runner;plan=guard.legacy()
    proof=runner.read(runner.HERE/'adaptive_cash_revision_checks.json')
    assert proof['全合格'] and proof['旧固定前後SHA不変']
    assert proof['検査実装SHA256']==runner.digest(Path(checks.__file__))
    before=runner.HERE/'adaptive_cash_reconstruction.py'
    old=(runner.HERE/'cash_revision_v1'/before.name).read_bytes()
    assert before.read_bytes()==old
    candidate=runner.HERE/'adaptive_cash_reconstruction_v2_candidate.py'
    text=candidate.read_text(encoding='utf-8')
    reversed_text=text.replace(checks.NEW_ORDER,checks.OLD_ORDER).replace(checks.NEW_END,checks.OLD_END)
    assert reversed_text==(runner.HERE/'cash_revision_v1'/before.name).read_text(encoding='utf-8')
    assert text.count(checks.NEW_ORDER)==text.count(checks.NEW_END)==1
    before.write_bytes(candidate.read_bytes())
    assert runner.digest(before)==runner.digest(candidate)
    payload=dict(適用完了=True,適用日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        主再生の中断後改訂=True,境界2領域以外本文同一=True,
        売買変更=False,入力変更=False,損益算術変更=False,採否変更=False,対象変更=False,
        旧会計SHA256=runner.digest(runner.HERE/'cash_revision_v1'/before.name),
        新会計SHA256=runner.digest(before),検査SHA256=runner.digest(runner.HERE/'adaptive_cash_revision_checks.json'),
        改訂計画SHA256=runner.digest(runner.HERE/'adaptive_cash_revision_plan.json'),
        独立境界確認SHA256=runner.digest(runner.HERE/'adaptive_close_boundary_review.json'),
        全974再生前=True,全人工再検査は次段階=True,API取得数=0)
    runner.save(runner.HERE/'adaptive_cash_revision_applied.json',payload)
    print('場末2検査だけを補正。旧版・障害・人工反例を保存。')


if __name__=='__main__':main()
