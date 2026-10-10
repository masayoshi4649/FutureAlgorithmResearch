"""既存集計だけを読む、共通ランキング資格の独立検討。"""
import json
from pathlib import Path
from collections import defaultdict
P=Path('work/wave_v17'); OUT=P/'rankings'
w=json.loads((P/'週合計.json').read_text(encoding='utf-8'))
s=json.loads((P/'セッション集計.json').read_text(encoding='utf-8'))
by=defaultdict(dict); cells=defaultdict(list)
for r in w:by[r['method_id']][r['symbol']]=r
for r in s:cells[r['method_id'],r['symbol']].append(r)
results=[]
for mid, pair in by.items():
    rs=list(pair.values())
    reduced={sy:r['net_yen']-max(c['net_yen'] for c in cells[mid,sy]) for sy,r in pair.items()}
    basic=all(r['net_yen']>0 and r['money_ratio'] is not None and r['money_ratio']>1 and r['unit_payoff'] is not None and r['unit_payoff']>1 for r in rs)
    majority=all(r['positive_sessions']>=6 for r in rs)
    leavebest=all(x>0 for x in reduced.values())
    ratios=[r[x] for r in rs for x in ['money_ratio','unit_payoff']]
    score=min(ratios) if all(x is not None for x in ratios) else None
    results.append(dict(id=mid,basic=basic,majority=majority,leave_best=leavebest,strict=basic and majority and leavebest,score=score,without_best=reduced,rows=pair))
summary={
 '基本資格数':sum(r['basic'] for r in results),
 '基本と黒字６区間資格数':sum(r['basic'] and r['majority'] for r in results),
 '基本と最大利益区間除外資格数':sum(r['basic'] and r['leave_best'] for r in results),
 '全資格数':sum(r['strict'] for r in results),
 '全条件':results,
 '基本資格順位':[r['id'] for r in sorted((r for r in results if r['basic']),key=lambda r:(-r['score'],r['id']))],
 '全資格順位':[r['id'] for r in sorted((r for r in results if r['strict']),key=lambda r:(-r['score'],r['id']))],
 '銘柄別週収支上位':{sy:[r['method_id'] for r in sorted((r for r in w if r['symbol']==sy),key=lambda r:(-r['net_yen'],r['method_id']))[:5]] for sy in ['NK225','TOPIX']}}
(OUT/'audit_design.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print({k:v for k,v in summary.items() if k!='全条件'})
for title,subset in [('全資格',summary['全資格順位'][:10]),('基本',summary['基本資格順位'][:10])]:
 print(title)
 for mid in subset:
  r=next(x for x in results if x['id']==mid)
  print(mid,round(r['score'],4),r['strict'],[(sy,x['net_yen']/10000,round(x['money_ratio'],3),round(x['unit_payoff'],3),x['positive_sessions'],r['without_best'][sy]/10000) for sy,x in r['rows'].items()])
