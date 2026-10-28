"""登録済み保存注文だけを読み、回転・待機による差額を原時刻へ分解する。"""

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo
import numpy as np
import account145
from source145 import HERE


def clock(timestamp):
    """
    機能: 原価格時計を日本時間の文字列にする。
    引数: timestamp(float)。返り値: str。
    """
    return datetime.fromtimestamp(float(timestamp), ZoneInfo('Asia/Tokyo')).isoformat()


def parent_detail(rows, data, method, scene):
    """
    機能: 保存済み親を約定と公開特徴、事後最高評価へ結び付ける。
    引数: rows(ndarray)、data(dict)、method/scene(str)。返り値: list[dict]。
    事後最高評価は診断専用で、売買へ戻さない。判断時の準備Rを事後推定しない。
    """
    times, quotes = data['ready']['time_s'], data['quotes']
    base = account145.financial_account(rows, times, quotes, method, scene, 'NK225')
    result=[]
    for parent in base['parents']:
        p=rows[rows[:,2]==parent['id']]
        first=p[p[:,7]>0][0];d=int(first[1]);i=int(first[0]);side=int(first[3])
        cash=0.;held=0;best=-float('inf');best_i=i
        for j,row in enumerate(p):
            idx=int(row[0]);cash-=row[3]*row[4]*row[5]*100
            held+=int(row[4]) if row[7] else -int(row[4])
            stop=int(p[j+1,0]) if j+1<len(p) else idx+1
            if stop<=idx:continue
            mark=quotes['bid'][idx:stop] if side>0 else quotes['ask'][idx:stop]
            values=cash+side*held*mark*100
            valid=np.isfinite(values)&quotes['quote_valid'][idx:stop]
            if valid.any():
                pos=int(np.argmax(np.where(valid,values,-np.inf)))
                if values[pos]>best:best=float(values[pos]);best_i=idx+pos
        a=data['features'][d]
        observations={name:float(a[k]) if np.isfinite(a[k]) else None for name,k in
            [('公開40分効率',2),('公開5分差',3),('公開40分差',4),('発注時公開R参考値',9),
             ('中値',10),('30秒差のR比',12),('120秒差のR比',13),('公開MA20',30)]}
        observations['公開ATR']=float(data['ready']['atr'][d]) if np.isfinite(data['ready']['atr'][d]) else None
        result.append(dict(parent=parent['id'],side=side,entry=clock(times[i]),entry_price=float(first[5]),
             net=parent['net'],peak_net=best,peak_time=clock(times[best_i]),giveback=best-parent['net'],
             decision=clock(times[d]),decision_features=observations,
             fills=[dict(at=clock(times[int(x[0])]),decision=clock(times[int(x[1])]),new=bool(x[7]),
                         side=int(x[3]),quantity=int(x[4]),price=float(x[5]),reason=int(x[6]),uid=int(x[8])) for x in p]))
    return result


def main():
    """
    機能: 全50場差分、具体例、理由別回数を保存する。
    引数: なし。返り値: None。金融再生を新しく行わない。
    """
    saved=json.loads((HERE/'結果145.json').read_text(encoding='utf-8'))
    records={(x['session'],x['method']):x for x in saved['rows']}
    scenes=sorted({x['session'] for x in saved['rows']})
    comparisons=[];cases={};reasons={};identical=True
    for scene in scenes:
        with np.load(HERE/'measurement'/f'NK225_{scene}.npz') as z:
            identical=identical and np.array_equal(z['V00'],z['V13'])
            for method in [f'V{i:02d}' for i in range(16)]:
                count=reasons.setdefault(method,Counter())
                for row in z['A_'+method]:count[str(int(row[6]))]+=1
    for source,target in [('V00','V11'),('V06','V07'),('V06','V08'),('V06','V09'),('V00','V04')]:
        differences=sorted([dict(session=s,change=records[s,target]['net']-records[s,source]['net'],
                                before=records[s,source]['net'],after=records[s,target]['net']) for s in scenes],key=lambda x:x['change'])
        positive=[x for x in differences if x['change']>0];negative=[x for x in differences if x['change']<0]
        selected=negative[:2]+positive[-2:]
        comparisons.append(dict(source=source,target=target,total_change=sum(x['change'] for x in differences),
              improved=len(positive),worsened=len(negative),equal=50-len(positive)-len(negative),
              selected=selected,differences=differences))
        for item in selected:
            scene=item['session'];key=source+'_'+target+'_'+scene
            with (HERE/'cache'/f'{scene}.pkl').open('rb') as f:_,data,_,_,_=pickle.load(f)
            with np.load(HERE/'measurement'/f'NK225_{scene}.npz') as z:
                cases[key]={source:parent_detail(z['A_'+source],data,source,scene),target:parent_detail(z['A_'+target],data,target,scene)}
    result=dict(comparisons=comparisons,cases=cases,reasons=reasons,V13全経路同値=identical,
                note='同じ保存済み約定の再集計。最高評価と終値分類は診断専用。新たな条件探索・金融再生なし。')
    (HERE/'追加回転と待機の具体的診断145.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    for comparison in comparisons:print(comparison['source'],comparison['target'],comparison['total_change'],comparison['improved'],comparison['worsened'])


if __name__=='__main__':main()
