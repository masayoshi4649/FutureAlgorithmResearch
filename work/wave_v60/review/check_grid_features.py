"""グリッド方向材料の公開時刻・週区分・未来非参照を独立検査する。"""

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'grid'))
import features


def main() -> None:
    """機能: 五分終値を辞書で独立集計し、50口座の公開材料と切断改変を検査する。

    引数: なし。返り値: なし(None)。将来の損益は参照しない。
    """
    ready=pickle.loads((HERE.parent/'inputs.pkl').read_bytes())
    quotes=pickle.loads((HERE.parent/'quotes.pkl').read_bytes())
    observations=prefixes=0
    for key,r in ready.items():
        q=quotes[key];got=features.direction_events(r,q);current={};last=None;ei=0
        for i in range(len(r['seq'])):
            bucket=int(r['time_s'][i]//300)
            if last is not None and bucket!=last:
                end=bucket-1
                present=[b in current for b in range(end-6,end+1)]
                valid=present[-1] and present[-2] and sum(present)>=6
                prices=[];prior=None
                for b in range(int(r['start']//300),end+1):
                    if b in current:prior=current[b]
                    if b>=end-6:prices.append(prior)
                if len(prices)<7 or any(v is None for v in prices):valid=False
                row=got[ei];assert row[0]==i and bool(row[3])==valid
                if len(prices)==7 and all(v is not None for v in prices):
                    np.testing.assert_array_equal(row[1:3],[prices[-1]-prices[0],prices[-1]-prices[-4]])
                ei+=1;observations+=1
            current[bucket]=q['mid'][i];last=bucket
        assert ei==len(got)
        for cut in (1,len(r['seq'])//3,len(r['seq'])*2//3):
            rc={k:(v[:cut].copy() if isinstance(v,np.ndarray) else v) for k,v in r.items()}
            qc={k:v[:cut].copy() for k,v in q.items()}
            expected=got[got[:,0]<cut]
            np.testing.assert_array_equal(features.direction_events(rc,qc),expected);prefixes+=1
            altered={k:v.copy() for k,v in q.items()}
            for col in ('mid','bid','ask'):altered[col][cut:]+=1000.
            actual=features.direction_events(r,altered)
            np.testing.assert_array_equal(actual[actual[:,0]<cut],expected);prefixes+=1
    weeks={features.week_start(key[0]) for key in ready}
    assert weeks=={'2026-09-21','2026-09-28','2026-10-05'}
    assert features.week_start('2026-09-25_Night')=='2026-09-21'
    evidence=dict(合格=True,口座=len(ready),公開材料=observations,未来切断改変=prefixes,週区分=sorted(weeks),
                  コードSHA256=hashlib.sha256((HERE.parent/'grid/features.py').read_bytes()).hexdigest())
    (HERE/'グリッド方向材料の独立監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
