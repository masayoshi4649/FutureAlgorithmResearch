"""終了済みの失敗監査における未保存条件を、全26口座で独立に再点検する。"""

from concurrent.futures import ProcessPoolExecutor, as_completed
import traceback

import numpy as np
import adaptive_accounting_audit as audit


def inspect_condition(spec: dict) -> dict:
    """機能: 不合格候補一条件の全口座で、最初に破れた検査を保存する。

    引数: spec (dict)。返り値: 口座別の合否と例外 (dict)。既存監査明細は変更しない。
    """
    runner=audit.runner;rows=[]
    for key,ready in sorted(runner.INPUTS.items()):
        cols=runner.columns(spec,key)
        state,bad,bs,good,gs,valid,branch,source,bv,choice=cols
        config=runner.base.managers.make_config(runner.FIXED['manager'],key[1],ready)
        shadow=runner.shadow(spec,key,state,config)
        result=runner.engine.run(ready,state,config,bad,bs,good,gs,spec['policy'],
            observed_fill=spec['observed_fill'],detail=True,shadow=shadow,good_valid=valid,
            budget_enabled=spec['budget_enabled'],min_delay_seconds=spec['min_delay_seconds'],
            branch_direction=branch,branch_source=source,branch_valid=bv,branch_mode=spec['branch_mode'],
            branch_choice=choice,branch_seed=spec['branch_seed'])
        record=dict(session=key[0],symbol=key[1],原本行数=len(ready['last']))
        try:
            audit.inspect(spec,ready,result,config,cols)
        except Exception as error:
            record.update(全検査通過=False,例外種類=type(error).__name__,例外=str(error),traceback=traceback.format_exc())
            tb=error.__traceback__
            while tb:
                values=tb.tb_frame.f_locals
                if tb.tb_frame.f_code.co_name=='audit' and 'phase' in values and 'control' in values:
                    phase=values['phase'];control=values['control']
                    mismatch=np.flatnonzero(phase!=control[:,2])
                    record['状態不一致']=[dict(row=int(i),時刻秒=float(ready['time_s'][i]),
                        実状態=int(control[i,2]),期待状態=int(phase[i]),実予約=int(control[i,8]),
                        実予算予約=bool(control[i,13]),復元資格枚数=int(control[i,6])) for i in mismatch]
                tb=tb.tb_next
        else:
            record['全検査通過']=True
        rows.append(record)
    return dict(id=spec['id'],口座数=len(rows),不合格口座数=sum(not r['全検査通過'] for r in rows),結果=rows)


def main() -> None:
    """機能: 失敗監査の終了証跡にある全集合を再検査し、全不一致を列挙する。

    引数: なし。返り値: なし (None)。終了証跡のない実行中監査は対象にしない。
    """
    audit.initialize();runner=audit.runner
    end=runner.read(runner.HERE/'adaptive_accounting_failed_run.json')
    assert end['終了コード']==1 and end['監査プロセス終了'] is True
    fixed=runner.read(runner.HERE/'adaptive_accounting_fixed.json')
    before={relative:runner.digest(runner.ROOT/relative) for relative in fixed['参照SHA256']}
    expected={s['id']:s for s in fixed['主対象']}
    completed={p.name.removesuffix('.json.gz') for p in (runner.HERE/'adaptive_accounting_details').glob('*.json.gz')}
    missing=set(expected)-completed
    assert missing==set(end['未保存条件IDs']) and completed==set(end['保存済み条件IDs'])
    rows=[]
    with ProcessPoolExecutor(max_workers=2,initializer=audit.initialize) as executor:
        tasks={executor.submit(inspect_condition,expected[i]):i for i in sorted(missing)}
        for future in as_completed(tasks):
            item=future.result();rows.append(item)
            print(item['id'],item['不合格口座数'],'/26',flush=True)
    assert before=={relative:runner.digest(runner.ROOT/relative) for relative in before}
    result=dict(全未保存条件検査完了=True,全主条件数=len(expected),保存済み合格条件数=len(completed),
        未保存条件数=len(missing),追加検査口座数=26*len(missing),
        不合格口座数=sum(r['不合格口座数'] for r in rows),結果=sorted(rows,key=lambda r:r['id']),
        参照SHA256=before,API取得数=0,現在保存物使用=False,コード変更=False,採否変更=False,
        限界='失敗口座では最初の破綻までを列挙する。修正後の全項目合格は別途必要。')
    runner.save(runner.HERE/'adaptive_accounting_failure_inventory.json',result)


if __name__=='__main__':
    main()
