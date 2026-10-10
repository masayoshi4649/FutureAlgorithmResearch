"""公開用ランキング全順位・表示値を独立計算結果と原集計へ照合する。"""
import hashlib
import json
from pathlib import Path
import math
P=Path('work/wave_v17');O=P/'rankings';checks=0

def read(path:Path)->object:
    """機能: 日本語JSONを読み込む。

    引数: path (Path)。返り値: JSON内容 (object)。
    """
    return json.loads(path.read_text(encoding='utf-8'))

def compare(a:object,b:object,path:str)->None:
    """機能: 辞書・配列・値を再帰的に照合する。

    引数: a/b (object)、path (str)。返り値: なし (None)。
    """
    global checks
    if isinstance(a,dict):
        assert isinstance(b,dict) and set(a)==set(b),(path,'辞書キーの差')
        for k in a:compare(a[k],b[k],f'{path}/{k}')
    elif isinstance(a,list):
        assert isinstance(b,list) and len(a)==len(b),(path,'要素数の差')
        for i,(x,y) in enumerate(zip(a,b)):compare(x,y,f'{path}/{i}')
    elif isinstance(a,(float,int)) and not isinstance(a,bool):
        assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-5),(path,a,b)
        checks+=1
    else:
        assert a==b,(path,a,b)
        checks+=1

actual=read(O/'ranking_data.json');expected=read(O/'audit_expected_rankings.json')
weekly={(x['method_id'],x['symbol']):x for x in read(P/'週合計.json')}
sessions={(x['method_id'],x['session'],x['symbol']):x for x in read(P/'セッション集計.json')}
configs={x['id']:x for x in read(P/'全条件一覧.json')}
atr={(x['method_id'],x['symbol']):x for x in read(O/'audit_atr_normalized.json')['週']}
for sy in ['NK225','TOPIX']:
    compare([x['id'] for x in actual['individual_all'][sy]],expected['銘柄別全順位'][sy],f'{sy}全180順位')
    compare(actual['individual'][sy],actual['individual_all'][sy][:5],f'{sy}表示上位５')
    compare([x['rank'] for x in actual['individual_all'][sy]],list(range(1,181)),f'{sy}順位番号')
for x,y in zip(actual['common_all'],expected['共通資格全順位']):
    compare(x,dict(id=y['id'],score=y['score'],min_positive=y['min_positive'],min_recovery=y['min_recovery'],stable=y['頑健条件適合'],rank=y['順位']),'共通全順位')
compare(len(actual['common_all']),len(expected['共通資格全順位']),'共通資格件数')
compare(actual['common'],actual['common_all'][:5],'共通表示上位５')
compare(actual['metadata']['basic_qualified'],12,'基本資格数')
compare(actual['metadata']['stable_qualified'],4,'頑健資格数')
compare(actual['metadata']['conditions'],180,'条件数')
method_count=len(actual['methods']);week_count=0;session_count=0
for mid,method in actual['methods'].items():
    compare(method['id'],mid,'methodid');compare(method['config'],configs[mid],mid+'/全設定')
    assert set(method['stocks'])=={'NK225','TOPIX'}
    for sy,block in method['stocks'].items():
        week_count+=1;compare(block['week'],weekly[mid,sy],f'{mid}/{sy}/週')
        nets=[]
        for s in block['sessions']:
            session_count+=1;compare(s,sessions[mid,s['session'],sy],f'{mid}/{sy}/{s["session"]}')
            nets.append(s['net_yen'])
        assert len(nets)==10
        compare(block['best_session_removed_net'],sum(nets)-max(nets),f'{mid}/{sy}/最高利益区間除外')
        compare(block['best_two_removed_net'],sum(nets)-sum(sorted(nets,reverse=True)[:2]),f'{mid}/{sy}/最高利益２区間除外')
        compare(block['atr'],atr[mid,sy],f'{mid}/{sy}/ATR診断')
for name,h in actual['metadata']['source_hashes'].items():compare(hashlib.sha256((P/name).read_bytes()).hexdigest(),h,'入力ハッシュ')
result=dict(結果='全一致',照合項目数=checks,銘柄別全順位件数=360,共通基本資格順位件数=12,表示銘柄別上位枠=10,表示共通上位枠=5,掲載手法数=method_count,掲載週セル数=week_count,掲載セッションセル数=session_count,基本資格数=12,頑健資格数=4,第５位の参考扱い=actual['common'][4]['stable'] is False)
(O/'audit_ranking_data.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(result)
