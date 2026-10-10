"""親実装を参照せず、確定したランキング仕様の全順位を計算する。"""
import json
from pathlib import Path
P=Path('work/wave_v17/rankings')
r=json.loads((P/'audit_design.json').read_text(encoding='utf-8'))
all_rows=r['全条件']
for row in all_rows:
    row['min_positive']=min(x['positive_sessions'] for x in row['rows'].values())
    row['min_recovery']=min(x['net_yen']/x['drawdown_yen'] for x in row['rows'].values())
rank=sorted((x for x in all_rows if x['basic']),key=lambda x:(-x['score'],-x['min_positive'],-x['min_recovery'],x['id']))
weekly=[dict(x,method_id=r['id']) for r in all_rows for x in r['rows'].values()]
out=dict(共通資格全順位=[dict(順位=i+1,id=x['id'],score=x['score'],min_positive=x['min_positive'],min_recovery=x['min_recovery'],頑健条件適合=x['strict']) for i,x in enumerate(rank)],銘柄別全順位={sy:[x['method_id'] for x in sorted((x for x in weekly if x['symbol']==sy),key=lambda x:(-x['net_yen'],x['method_id']))] for sy in ['NK225','TOPIX']})
(P/'audit_expected_rankings.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(out['共通資格全順位'])
