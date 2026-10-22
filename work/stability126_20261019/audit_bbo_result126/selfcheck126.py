"""独立BBO会計監査器が、人工会計の破損を拒否することを確認する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

import audit126 as audit


HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'input_audit/bbo_artificial126'))
import check_bbo126 as toy


def execute() -> None:
    """
    機能: 正しい人工を独立監査し、金額・数量・時刻・気配の故意破損を拒否する。
    引数: なし。
    返り値: None。市場入力・金融再生は0。
    """
    configs={v['id']:v for v in toy.catalog()};checks=[]
    for qty in (5,10):
        for label,value in toy.mechanism_cases(qty).items():
            for config in configs.values():
                result=toy.interface.play(config,value[0],value[1],value[2],value[3],use_python=True)
                audit.audit_account(*value[:3],value[3],result,config)
                checks.append('人工正値_'+str(qty)+'_'+label+'_'+config['id'])
    value=toy.mechanism_cases(5)['P'];config=configs['P01']
    correct=toy.interface.play(config,value[0],value[1],value[2],value[3],use_python=True)
    mutations=[]
    broken=deepcopy(correct);broken['trades'][0,10]+=1.;mutations.append(('FIFO利益破損',value,broken))
    broken=deepcopy(correct);broken['curve'][3,0]+=1.;mutations.append(('途中時価破損',value,broken))
    broken=deepcopy(correct);broken['orders'][0,5]-=1.;mutations.append(('買bid誤使用',value,broken))
    broken=deepcopy(correct);broken['orders'][0,1]=broken['orders'][0,0];mutations.append(('当行新設同時約定',value,broken))
    broken=deepcopy(correct);broken['cycles'][0,5]+=1.;mutations.append(('初期ATR差替え',value,broken))
    broken=deepcopy(correct);broken['execution_states'][4,9]=0.;mutations.append(('stale気配元行破損',value,broken))
    broken=deepcopy(correct);broken['stats'][0]+=1.;mutations.append(('集計損益破損',value,broken))
    badquotes=deepcopy(value);badquotes[1]['quote_valid'][2]=False;mutations.append(('不適格行での新規',badquotes,correct))
    for label,value,broken in mutations:
        try:audit.audit_account(*value[:3],value[3],broken,config)
        except (AssertionError,IndexError):checks.append('故意破損拒否_'+label)
        else:raise AssertionError('破損を許可:'+label)
    target=HERE/'独立会計監査器の人工正値と故意破損の反証.json';assert not target.exists()
    proof=dict(passed=True,checks=checks,count=len(checks),auditor_sha256=hashlib.sha256((HERE/'audit126.py').read_bytes()).hexdigest(),
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),market_reads=0,financial_replays=0,API=0,
        scope='合成96政策会計は独立FIFO/全行BBO/場risk等まで照合、8故意破損を拒否。実市場での有効性標本ではない。')
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,count=len(checks)),ensure_ascii=False))


if __name__=='__main__':execute()
