"""既定監査が拒否した減量状態の原本行と予約境界を限定抽出する。"""

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import adaptive_accounting_audit as audit


def main() -> None:
    """機能: 固定済みの一口座で減量状態の不一致行だけを記録する。

    引数: なし。返り値: なし (None)。売買・監査本体や採否は変更しない。
    """
    audit.initialize();runner=audit.runner
    identifier='H019__B00_T120_F25_N3__R1__L015';key=('2026-09-24_Night','NK225')
    spec=next(s for s in runner.FIXED['conditions'] if s['id']==identifier)
    ready=runner.INPUTS[key];cols=runner.columns(spec,key)
    state,bad,bs,good,gs,valid,branch,source,bv,choice=cols
    config=runner.base.managers.make_config(runner.FIXED['manager'],key[1],ready)
    before={str((runner.HERE/name).relative_to(runner.ROOT).as_posix()):runner.digest(runner.HERE/name)
        for name in ('adaptive_accounting_audit.py','adaptive_slot_audit.py','adaptive_shadow_oracle.py',
            'engine_partial_restore.py','engine_shadow_plan.py','adaptive_accounting_fixed.json','探索条件の固定.json')}
    shadow=runner.shadow(spec,key,state,config)
    result=runner.engine.run(ready,state,config,bad,bs,good,gs,spec['policy'],
        observed_fill=spec['observed_fill'],detail=True,shadow=shadow,good_valid=valid,
        budget_enabled=spec['budget_enabled'],min_delay_seconds=spec['min_delay_seconds'],
        branch_direction=branch,branch_source=source,branch_valid=bv,branch_mode=spec['branch_mode'],
        branch_choice=choice,branch_seed=spec['branch_seed'])
    try:
        audit.inspect(spec,ready,result,config,cols)
    except AssertionError as error:
        assert str(error)=='全行の減量状態'
        tb=error.__traceback__;locals_=None
        while tb:
            if tb.tb_frame.f_code.co_filename.endswith('adaptive_slot_audit.py') and tb.tb_frame.f_code.co_name=='audit':
                locals_=tb.tb_frame.f_locals
            tb=tb.tb_next
        assert locals_ is not None
        phase=locals_['phase'];control=result['control_curve']
        badrows=np.flatnonzero(control[:,2]!=phase)
        assert len(badrows)
        lo=max(0,int(badrows[0])-2);hi=min(len(phase),int(badrows[-1])+3)
        times=ready['time_s']
        rows=[]
        for i in range(lo,hi):
            rows.append(dict(row=i,時刻=datetime.fromtimestamp(times[i],ZoneInfo('Asia/Tokyo')).isoformat(),
                価格=float(ready['last'][i]),組=int(control[i,1]),実状態=int(control[i,2]),
                監査期待状態=int(phase[i]),実予約=int(control[i,8]),実予算予約=bool(control[i,13]),
                復元資格枚数=int(control[i,6]),実保有枚数=int(control[i,5]),
                監査予算予約=bool(locals_['expected_budget'][i]),
                調整予約期待=locals_['expected_pending'][i].tolist()))
        around=lambda values:values[(values[:,0]>=lo)&(values[:,0]<hi)].tolist()
        payload=dict(不一致再現=True,id=identifier,session=key[0],symbol=key[1],
            不一致行数=len(badrows),不一致行=badrows.tolist(),周辺行=rows,
            周辺調整=around(result['adjustment_events']),周辺予算=around(result['budget_events']),
            周辺注文=around(result['orders']),元影周辺注文=around(shadow['orders']),
            直前までの独立会計公開枠予約検査通過=True,全結果指紋=runner.fingerprints(result),
            凍結SHA256=before,コード変更=False,採否変更=False,API取得数=0,現在保存物使用=False)
    else:
        raise AssertionError('対象の減量状態不一致を再現できませんでした')
    assert before=={name:runner.digest(runner.ROOT/name) for name in before}
    runner.save(runner.HERE/'adaptive_phase_revision_probe.json',payload)
    print('不一致行数',payload['不一致行数'],'最初',payload['周辺行'][2],flush=True)


if __name__=='__main__':
    main()
