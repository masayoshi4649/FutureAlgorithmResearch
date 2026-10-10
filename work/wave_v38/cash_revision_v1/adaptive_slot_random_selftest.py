"""複数組・取消・伝達待ちを含む固定人工経路で独立監査を追加検査する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import urllib.request
import numpy as np
import random_path_audit as paths
import adaptive_slot_audit as audit
import adaptive_slot_selftest as synthetic

HERE=Path(__file__).resolve().parent


def main() -> dict:
    """機能: 固定乱数経路と上下反射を独立枠・成熟計画へ全数照合する。

    引数: なし。返り値: 全判定・実装SHAを含む監査記録(dict)。実相場を読まない。
    """
    socket.socket.connect=synthetic.fixtures.reject
    socket.create_connection=synthetic.fixtures.reject
    urllib.request.urlopen=synthetic.fixtures.reject
    policies={p['id']:p for p in paths.runner.design.policies()}
    names=('A0',paths.runner.design.PRIMARY_POLICY,paths.runner.design.REVERSE_POLICY,paths.runner.design.CLOCK_POLICY)
    records=[]
    for seed in range(64):
        for symbol in ('TOPIX','NK225'):
            original=paths.generated(seed,symbol)
            for offset,name in enumerate(names):
                policy=policies[name];delay=(0.,1.,5.,15.)[(seed+offset)%4]
                budget=bool((seed//4+offset)%2);observed=bool((seed//8+offset)%2)
                for reflected in (False,True):
                    ready,state,config,bad,bs,good,gs,valid,branch,source,bv,choice=deepcopy(original)
                    if reflected:
                        ready['last']=500.-ready['last'];state=-state;bad=-bad;good=-good;branch=-branch
                    options=dict(observed_fill=observed,good_valid=valid,budget_enabled=budget,
                        min_delay_seconds=delay,branch_direction=branch,branch_source=source,branch_valid=bv,
                        branch_choice=choice,branch_mode=policy['branch_mode'],branch_seed=None)
                    context=dict(seed=seed,symbol=symbol,policy=name,delay=delay,budget=budget,
                                 observed=observed,reflected=reflected)
                    try:
                        result=paths.runner.engine.run(ready,state,config,bad,bs,good,gs,policy,**options)
                        del options['good_valid']
                        proof=audit.audit(ready,result,config,policy,bad,bs,good,gs,valid,
                                          synthetic.curves(ready,result),state=state,**options)
                    except Exception as error:
                        (HERE/'adaptive_slot_random_failure.json').write_text(json.dumps(dict(**context,error=repr(error)),ensure_ascii=False,indent=2),encoding='utf-8')
                        raise
                    records.append(dict(**context,全独立検査一致=True,組数=len(result['cycles'])))
        if seed%8==7:print('完了',len(records),flush=True)
    sources=(Path(__file__),HERE/'adaptive_slot_audit.py',HERE/'adaptive_shadow_oracle.py',
             HERE/'engine_partial_restore.py',HERE/'engine_shadow_plan.py',HERE/'random_path_audit.py')
    summary=dict(全合格=True,人工再生数=len(records),新実相場損益=False,検査=records,
                 SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (HERE/'adaptive_slot_random_selftest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('PASS',len(records),flush=True)
    return summary


if __name__=='__main__':main()
