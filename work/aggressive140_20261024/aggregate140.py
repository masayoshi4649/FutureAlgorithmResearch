"""保存された試行の表示訂正と二巡目を重複なく集計する。"""

import argparse
import json
from pathlib import Path
import numpy as np
import analyze140 as a

HERE=Path(__file__).resolve().parent


def merged(new=False):
    """
    機能: 保存の誤表示だけを訂正した第一巡と正しく保存した第二巡を結合する。
    引数: new(bool)は追加3場の指定。
    返り値: tuple[list[dict],list[dict]]は単独口座とペア口座。会計の二重加算をしない。
    """
    first=a.read('new/結果140.json' if new else 'known/結果140_表示訂正版.json')
    second=a.read('round2_new/結果140.json' if new else 'round2_known/結果140.json')
    result={(r['symbol'],r['method'],r['session']):r for r in first['rows']}
    for row in second['rows']:
        key=row['symbol'],row['method'],row['session']
        if key in result:
            for field in ('profit','loss','net','fees','entries','quantity'):
                assert abs(row[field]-result[key][field])<1e-6,(key,field)
        result[key]=row
    return list(result.values()),second['pair_rows']


def labels():
    """
    機能: 固定設定から各運用の名称を得る。
    引数: なし。
    返り値: dict[str,str]は表示名。
    """
    result=a.names();plan=a.read('第二巡計画140.json')
    for c in plan['configs']['active']:
        result['S'+c['id'][1:]]='現行と独立枠：'+result[c['id']]
    for c in plan['configs']['pair']:result[c['id']]=f"整数ペア{c['window']}分：{c['name']}"
    return result


def summarize(rows,pairs,scope):
    """
    機能: 商品内の活動と損失・大勝ち依存を集計する。
    引数: rows/pairs(list[dict])、scope(str)は会計と評価区分。
    返り値: tuple[list[dict],list[dict]]は全体と昼夜・方向別。
    """
    names=labels();summary=[];parts=[]
    for symbol in ('NK225','TOPIX','PAIR'):
        allrows=pairs if symbol=='PAIR' else [r for r in rows if r['symbol']==symbol]
        for method in sorted({r['method'] for r in allrows}):
            selected=[r for r in allrows if r['method']==method]
            summary.append(a.stats(selected,method,symbol,scope,names[method]))
            for group in ('Day','Night','上昇','下落'):
                subset=[r for r in selected if r['kind']==group] if group in ('Day','Night') else [r for r in selected if 'market_change' in r and (r['market_change']>0 if group=='上昇' else r['market_change']<0)]
                if subset:parts.append(dict(a.stats(subset,method,symbol,scope,names[method]),group=group))
    return summary,parts


def execute(final=False):
    """
    機能: 既知範囲の候補比較又は固定候補の全50場資料を作る。
    引数: final(bool)は未見範囲の再生後の最終資料作成指定。
    返り値: None。既存の原会計は変更しない。
    """
    rows,pairs=merged();summary,parts=summarize(rows,pairs,'known')
    a.save('第二巡集計140.json' if not final else '最終既知集計140.json',dict(summary=summary,parts=parts))
    for symbol in ('NK225','TOPIX','PAIR'):
        candidates=[s for s in summary if s['symbol']==symbol]
        print(symbol,'既知47場',flush=True)
        ordered=sorted(candidates,key=lambda s:(s['flat']>0,s['losses'],-s['ex_top3'],-s['median']))
        for r in ordered[:15]:print({k:r[k] for k in ('method','net','losses','flat','avg_loss','worst','ex_top3','entries','first_minutes')},flush=True)
    if not final:return
    fixed=a.read('固定候補140.json');more,morepairs=merged(True)
    selected=[{'symbol':s,'method':m,'name':labels()[m]} for s in ('NK225','TOPIX') for m in ['B5']+fixed[s]]
    keys={(s['symbol'],s['method']) for s in selected}
    detail=[r for r in rows+more if (r['symbol'],r['method']) in keys]
    pairdetail=[r for r in pairs+morepairs if r['method'] in fixed.get('PAIR',[])]
    finalsummary=[];finalparts=[];pairsummary=[]
    for scope,subset,ps in [('all',detail,pairdetail),('known',[r for r in detail if r['split']=='既知47場'],[r for r in pairdetail if r['split']=='既知47場']),('new',more,morepairs)]:
        ss,pp=summarize(subset,ps,scope)
        finalsummary.extend(s for s in ss if s['symbol']!='PAIR');pairsummary.extend(s for s in ss if s['symbol']=='PAIR');finalparts.extend(pp)
    for r in detail:
        assert np.isclose(r['net'],r['profit']-r['loss']) and np.isclose(r['net'],r['gross']-r['fees'])
    a.save('report_data140.json',dict(summary=finalsummary,rows=detail,selected=selected,pair_rows=pairdetail,pair_summary=pairsummary,parts=finalparts))
    print('全50場候補',flush=True)
    for s in finalsummary+pairsummary:
        if s['scope']!='known':print({k:s[k] for k in ('symbol','method','scope','net','wins','losses','flat','avg_loss','worst','ex_top3','entries')},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--final',action='store_true');execute(p.parse_args().final)
