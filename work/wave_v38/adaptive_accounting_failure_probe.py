"""独立会計の未完了一条件を固定順序で再現し、例外の場所だけを記録する。"""

from pathlib import Path
import traceback

import adaptive_accounting_audit as audit


def main() -> None:
    """機能: 進捗中の欠落一条件を同じ監査で再現し、採否を変えず診断する。

    引数: なし。返り値: なし (None)。売買・監査コードと固定資料は変更しない。
    """
    audit.initialize()
    runner=audit.runner
    identifier='H019__B00_T120_F25_N3__R1__L015'
    spec=next(s for s in runner.FIXED['conditions'] if s['id']==identifier)
    paths=(runner.HERE/'adaptive_accounting_audit.py',runner.HERE/'adaptive_slot_audit.py',
        runner.HERE/'adaptive_shadow_oracle.py',runner.HERE/'adaptive_independent_statistics.py',
        runner.HERE/'adaptive_accounting_fixed.json',runner.HERE/'探索条件の固定.json')
    before={p.relative_to(runner.ROOT).as_posix():runner.digest(p) for p in paths}
    try:
        result=audit.evaluate(spec,'')
    except Exception as error:
        frames=[];tb=error.__traceback__
        while tb is not None:
            values=tb.tb_frame.f_locals
            item=dict(関数=tb.tb_frame.f_code.co_name,行=tb.tb_lineno,
                ファイル=tb.tb_frame.f_code.co_filename)
            if 'key' in values and isinstance(values['key'],tuple):
                item['key']=list(values['key'])
            if 'ready' in values and isinstance(values['ready'],dict):
                r=values['ready'];item['session']=r.get('session');item['symbol']=r.get('symbol')
                item['原本行数']=len(r.get('last',[]))
            for key in ('i','row','src','source','campaign','mode','count'):
                value=values.get(key)
                if isinstance(value,(str,int,float,bool)):
                    item[key]=value
            frames.append(item);tb=tb.tb_next
        payload=dict(例外再現=True,id=identifier,spec=spec,例外種類=type(error).__name__,例外=str(error),
            traceback=traceback.format_exc(),呼出箇所=frames,凍結SHA256=before,
            採否条件変更=False,コード変更=False,API取得数=0,現在保存物使用=False)
    else:
        payload=dict(例外再現=False,id=identifier,結果=result,凍結SHA256=before)
    assert before=={p.relative_to(runner.ROOT).as_posix():runner.digest(p) for p in paths}
    runner.save(runner.HERE/'adaptive_accounting_failure_probe.json',payload)
    print(payload.get('traceback','限定再現は合格'),flush=True)


if __name__=='__main__':
    main()
