"""凍結した正遅延条件の場末検査だけを限定再現し、収益の選別をしない。"""

from datetime import datetime
from pathlib import Path
import traceback
from zoneinfo import ZoneInfo

import numpy as np
import adaptive_runner as runner


def jst(value: float) -> str:
    """機能: 原本の時刻を日本時間の確認表記へ変換する。

    引数: value (float)。返り値: 日時文字列 (str)。
    """
    return datetime.fromtimestamp(float(value), ZoneInfo('Asia/Tokyo')).isoformat()


def main() -> None:
    """機能: 未完成の最初の正遅延条件を順序どおり再生し、最初の境界拒否を記録する。

    引数: なし。返り値: なし (None)。凍結コードと既存成果を書き換えない。
    """
    runner.initialize()
    fixed = runner.FIXED
    core_names = ('adaptive_runner.py','adaptive_cash_reconstruction.py','engine_partial_restore.py',
        'engine_shadow_plan.py','adaptive_design.py','adaptive_assessment.py','探索条件の固定.json','起動前監査.json')
    before = {str((runner.HERE / name).relative_to(runner.ROOT).as_posix()): runner.digest(runner.HERE / name) for name in core_names}
    for relative, sha in fixed['SHA256'].items():
        assert runner.digest(runner.ROOT / relative) == sha, relative
    specs = [s for s in fixed['conditions'] if s['min_delay_seconds'] > 0
        and not (runner.HERE/'summaries'/(s['id']+'.json')).exists()]
    assert specs
    spec = specs[0]
    checks = []
    for key, ready in sorted(runner.INPUTS.items()):
        state,bad,bs,good,gs,valid,branch,source,bv,choice = runner.columns(spec, key)
        config = runner.base.managers.make_config(fixed['manager'], key[1], ready)
        original = runner.shadow(spec, key, state, config)
        result = runner.engine.run(ready,state,config,bad,bs,good,gs,spec['policy'],
            observed_fill=spec['observed_fill'],detail=True,shadow=original,good_valid=valid,
            budget_enabled=spec['budget_enabled'],min_delay_seconds=spec['min_delay_seconds'],
            branch_direction=branch,branch_source=source,branch_valid=bv,
            branch_mode=spec['branch_mode'],branch_choice=choice,branch_seed=spec['branch_seed'])
        try:
            runner.accounting.reconstruct(ready,result,key[1])
        except AssertionError as error:
            assert str(error) == '場末判断の次観測以降に持越し', str(error)
            n = len(ready['last']); times = ready['time_s']
            delta = np.zeros(n)
            for order in result['orders']:
                delta[int(order[0])] += order[4] if order[7] else -order[4]
            gross = np.cumsum(delta)
            at_limit = np.flatnonzero(times >= ready['limit'])
            first = int(at_limit[0]); old_after = first + 1
            close_time = ready.get('session_close', ready['limit'] + 600.)
            maturity = times[first] + spec['min_delay_seconds']
            eligible = np.flatnonzero((np.arange(n) > first) & (times >= maturity - 1e-9))
            expected_after = int(eligible[0]) if len(eligible) else None
            violations = np.flatnonzero(gross[old_after:] > 0) + old_after
            last = int(np.flatnonzero(gross > 0)[-1])
            end_orders = [r.tolist() for r in result['orders'] if r[0] >= first - 2]
            samples = [dict(row=i, 時刻=jst(times[i]), 保有枚数=int(gross[i]))
                for i in range(max(0, first - 1), min(n, last + 3))]
            result_record = dict(障害再現=True, 対象=spec, session=key[0], symbol=key[1],
                例外=str(error), traceback=traceback.format_exc(), 検査順=checks,
                原本行数=n, 場末判断予定=jst(ready['limit']), 真の終場=jst(close_time),
                最初の場末判断行=first, 最初の場末判断時刻=jst(times[first]),
                旧会計が返済済みを要求する行=old_after, 旧会計要求時刻=jst(times[old_after]),
                固定伝達秒=spec['min_delay_seconds'], 成熟時刻=jst(maturity),
                成熟後の最初の次観測行=expected_after,
                成熟後の最初の次観測時刻=jst(times[expected_after]) if expected_after is not None else None,
                最終保有行=last, 最終保有時刻=jst(times[last]), 最終残玉=int(gross[-1]),
                旧検査だけに反する行数=len(violations), 境界付近=samples,
                終盤注文=end_orders, 終盤注文列=runner.engine.shadow_engine.ORDER_COLUMNS if hasattr(runner.engine.shadow_engine,'ORDER_COLUMNS') else ['row','source','campaign','side','qty','price','reason','opening'],
                全約定が終場より前=all(times[int(row[0])] < close_time for row in result['orders']),
                終場以降保有なし=not bool(np.any(gross[times >= close_time])),
                成熟後残玉なし=expected_after is not None and not bool(np.any(gross[expected_after:])),
                凍結資料SHA256=before, 結果配列指紋=runner.fingerprints(result),
                損益による対象選択=False, 損益集計の表示=False, 既存成果変更=False,
                API取得数=0, 現在保存物使用=False)
            assert before == {relative: runner.digest(runner.ROOT / relative) for relative in before}
            runner.save(runner.HERE/'adaptive_cash_revision_failure_v1.json',result_record)
            print(spec['id'], key, str(error), result_record['全約定が終場より前'], flush=True)
            return
        checks.append(dict(session=key[0],symbol=key[1],旧会計検査通過=True))
    raise AssertionError('最初の未完成正遅延条件では障害を再現できませんでした')


if __name__ == '__main__':
    main()
