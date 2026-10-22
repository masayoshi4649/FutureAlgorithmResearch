"""保存会計の再集計だけを行い、頻度・損失規模・時間帯・新旧期間を分ける。"""

import json
from pathlib import Path
import statistics
from common139 import HERE,PUBLIC,read


def statistics_for(rows):
    """
    機能: 総損益だけでは見えない赤字頻度と赤字の深さを集計する。
    引数: rows(list[dict])は同じ商品・手法のセッション会計。
    返り値: dictは頻度、金額、費用、買売寄与、上位三場除外後損益。
    """
    values=[r['net'] for r in rows];negative=[-x for x in values if x<0];positive=[x for x in values if x>0]
    return dict(sessions=len(rows),wins=len(positive),reds=len(negative),zero=sum(x==0 for x in values),
        no_trade=sum(r['entries']==0 for r in rows),profit=sum(r['profit'] for r in rows),loss=sum(r['loss'] for r in rows),
        net=sum(values),fees=sum(r['fees'] for r in rows),mean_win=statistics.mean(positive) if positive else 0,
        mean_loss=statistics.mean(negative) if negative else 0,median_loss=statistics.median(negative) if negative else 0,
        max_loss=max(negative,default=0),top3_removed=sum(values)-sum(sorted(positive,reverse=True)[:3]),
        buy=sum(p['net'] for r in rows for p in r['parents'] if p['side']>0),sell=sum(p['net'] for r in rows for p in r['parents'] if p['side']<0),
        entries=sum(r['entries'] for r in rows),quantity=sum(r['quantity'] for r in rows),max_per_side=max((r['max_per_side'] for r in rows),default=0),
        early_entries=sum(r.get('early_entries',0) for r in rows),recycle_entries=sum(r.get('recycle_entries',0) for r in rows))


def paired(base,changed):
    """
    機能: 同じ場同士の改善・悪化を数え、赤字を消した場と作った場を分ける。
    引数: base/changed(list[dict])は比較元と変更後の保存会計。
    返り値: dictは差分集計と全場の対照。
    """
    old={r['session']:r for r in base};rows=[]
    for r in changed:
        b=old[r['session']];rows.append(dict(session=r['session'],before=b['net'],after=r['net'],difference=r['net']-b['net']))
    return dict(better=sum(r['difference']>0 for r in rows),worse=sum(r['difference']<0 for r in rows),same=sum(r['difference']==0 for r in rows),
        red_removed=sum(r['before']<0 and r['after']>=0 for r in rows),red_created=sum(r['before']>=0 and r['after']<0 for r in rows),
        delta=sum(r['difference'] for r in rows),rows=rows)


def main():
    """
    機能: 完成済み全結果をまとめ、既知45場と追加2場を別集計する。
    引数: なし。
    返り値: None。入力・売買・既存会計を変更しない。
    """
    rows=[];sources=[]
    for folder in ('results','extra_results','early_results','recycle_results','protect_results','guard_results'):
        p=HERE/folder/'結果.json'
        if p.exists():data=read(p);rows.extend(data['rows']);sources.append(str(p))
    ids=sorted({r['method'] for r in rows});summaries={};comparisons={}
    for symbol in ('NK225','TOPIX'):
        grouped={key:[r for r in rows if r['symbol']==symbol and r['method']==key] for key in ids}
        summaries[symbol]={};comparisons[symbol]={}
        for key,group in grouped.items():
            assert len(group)==47,(symbol,key,len(group))
            summaries[symbol][key]={label:statistics_for([r for r in group if predicate(r)]) for label,predicate in
                [('全47場',lambda r:True),('既知45場',lambda r:r['session']<'2026-10-21_Night'),
                 ('追加2場',lambda r:r['session']>='2026-10-21_Night'),('デイ',lambda r:r['kind']=='Day'),('ナイト',lambda r:r['kind']=='Night')]}
            if key.startswith(('B5_E','C04_E','B5_G','C04_G')):base=key.split('_')[0]
            elif key.startswith(('PR','CR','PH','CH')):base=key[0]+'04'
            elif key not in ('B5','B2') and not key.startswith(('E','G')):base='B5'
            else:continue
            comparisons[symbol][key]={'base':base,**paired(grouped[base],group)}
    PUBLIC.mkdir(parents=True,exist_ok=True)
    output=dict(summary=summaries,comparisons=comparisons,methods=len(ids),accounts=len(rows),sources=sources,
        limits='既知探索と追加確認。ラージ気配代理、手数料後、採用した既存信号を固定した層の比較。未来の実収益保証ではない。')
    (PUBLIC/'比較集計.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    for symbol in summaries:
        values=[(k,v['全47場']) for k,v in summaries[symbol].items() if not k.startswith(('E','G'))]
        print(symbol)
        for key,s in sorted(values,key=lambda x:(x[1]['reds'],x[1]['mean_loss']))[:15]:
            print(key, '収支',round(s['net']),'赤',s['reds'],'平均赤',round(s['mean_loss']),'最大赤',round(s['max_loss']),'無取引',s['no_trade'])


if __name__=='__main__':main()
