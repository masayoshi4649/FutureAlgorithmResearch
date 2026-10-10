"""別HTMLの埋込データを独立順位・公開用集計と照合する。"""
import json
from pathlib import Path
import re
import math
P=Path('work/wave_v17/rankings');checks=0

def compare(a:object,b:object,label:str)->None:
    """機能: 入れ子の値が同一かを確認する。

    引数: a/b (object)、label (str)。返り値: なし (None)。
    """
    global checks
    if isinstance(a,dict):
        assert set(a)==set(b),label
        for k in a:compare(a[k],b[k],f'{label}/{k}')
    elif isinstance(a,list):
        assert len(a)==len(b),label
        for i,(x,y) in enumerate(zip(a,b)):compare(x,y,f'{label}/{i}')
    elif isinstance(a,(int,float)) and not isinstance(a,bool):
        assert math.isclose(a,b,abs_tol=1e-5,rel_tol=1e-10),(label,a,b)
        checks+=1
    else:
        assert a==b,(label,a,b)
        checks+=1

html_path=Path('アルゴリズム調査/00012_状態切替と柔軟な建玉管理/週収支ランキングと両銘柄共通手法.html')
html=html_path.read_text(encoding='utf-8')
x=json.loads(re.search(r'<script[^>]*id="data"[^>]*>(.*?)</script>',html,re.S).group(1))
data=json.loads((P/'ranking_data.json').read_text(encoding='utf-8'))
expected=json.loads((P/'audit_expected_rankings.json').read_text(encoding='utf-8'))
for sy in ['NK225','TOPIX']:compare([r['id'] for r in x['single'][sy]],expected['銘柄別全順位'][sy][:5],f'{sy}/上位５')
compare([r['id'] for r in x['common']],[r['id'] for r in expected['共通資格全順位'][:5]],'共通上位５')
rows=x['single']['NK225']+x['single']['TOPIX']+x['common']+x['comparisons']
for r in rows:
    mid=r['id'];src=data['methods'][mid]
    compare(r['name'],src['name'],mid+'/手法名');compare(r['description'],src['description'],mid+'/説明')
    assert set(r['rows'])=={'NK225','TOPIX'}
    for sy in ['NK225','TOPIX']:
        s=src['stocks'][sy]
        compare(r['rows'][sy],s['week'],f'{mid}/{sy}/週集計')
        compare(r['diagnostics'][sy],dict(without_best=s['best_session_removed_net'],atr_pf=s['atr']['atr_pf']),f'{mid}/{sy}/診断')
for r in x['common']:
    src=next(s for s in data['common'] if s['id']==r['id'])
    compare(r['score'],src['score'],r['id']+'/共通得点');compare(r['stable'],src['stable'],r['id']+'/頑健判定')
assert [r['stable'] for r in x['common']]==[True,True,True,True,False]
result=dict(結果='全一致',HTML=str(html_path),独立順位照合枠=15,表示手法カード数=len(rows),表示週セル数=len(rows)*2,一致照合項目数=checks,共通５位は参考=True)
(P/'audit_html_data.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(result)
