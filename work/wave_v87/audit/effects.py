"""十二の改修を同条件対照と親組対応で分解し、損失減と利益消失を併記する。"""

from collections import defaultdict
import math
import pickle
from diagnose import ROOT, HERE, read, save, groups, clock

ROUND=ROOT/'work/wave_v87/round1'
FIELDS=('net','gross','fees','campaign_profit','campaign_loss','campaign_profit_share','campaigns',
    'positive_sessions','negative_sessions','no_trade_sessions','max_drawdown','best_session_removed')


def packets(model):
    """
    機能: 完了した十二条件の結果と疎な保存台帳だけを読む。
    引数: model (str)。
    返り値: tuple[dict,dict]の集計と親組対応台帳。
    """
    configs=read(ROUND/'事前固定.json')['catalog'];results={};ledgers={}
    for c in configs:
        ident=c['id'];results[ident]=read(ROUND/model/'results'/f'{ident}.json')
        raw=pickle.loads((ROUND/model/'ledgers'/f'{ident}.pkl').read_bytes())
        output={}
        for (session,symbol),ledger in raw.items():
            for (entry,side),record in groups(ledger).items():
                output[(session,symbol,entry,side)]=record
        ledgers[ident]=output
    return results,ledgers


def matching(old,new,symbol,names):
    """
    機能: 同入口の出口差・消えた入口・追加入口へ純収支差を正確に分解する。
    引数: old/new (dict)、symbol (str)、names (list[str])。
    返り値: dict。元勝ち組の利益を失う副作用も保存する。
    """
    a={k:v for k,v in old.items() if k[1]==symbol and k[0] in names}
    b={k:v for k,v in new.items() if k[1]==symbol and k[0] in names}
    shared=a.keys()&b.keys();removed=a.keys()-b.keys();added=b.keys()-a.keys()
    parts={}
    for label,keys,delta in (
        ('同入口の旧黒字', [k for k in shared if a[k]['net']>0],lambda k:b[k]['net']-a[k]['net']),
        ('同入口の旧赤字', [k for k in shared if a[k]['net']<0],lambda k:b[k]['net']-a[k]['net']),
        ('同入口の旧同額', [k for k in shared if a[k]['net']==0],lambda k:b[k]['net']-a[k]['net']),
        ('消失した旧黒字', [k for k in removed if a[k]['net']>0],lambda k:-a[k]['net']),
        ('消失した旧赤字', [k for k in removed if a[k]['net']<0],lambda k:-a[k]['net']),
        ('消失した旧同額', [k for k in removed if a[k]['net']==0],lambda k:-a[k]['net']),
        ('追加の黒字', [k for k in added if b[k]['net']>0],lambda k:b[k]['net']),
        ('追加の赤字', [k for k in added if b[k]['net']<0],lambda k:b[k]['net']),
        ('追加の同額', [k for k in added if b[k]['net']==0],lambda k:b[k]['net'])):
        parts[label]=dict(組数=len(keys),差額寄与=math.fsum(delta(k) for k in keys))
    net=math.fsum(v['net'] for v in b.values())-math.fsum(v['net'] for v in a.values())
    assert abs(sum(p['差額寄与'] for p in parts.values())-net)<1e-6
    hurt=sorted([k for k in shared if a[k]['net']>0 and b[k]['net']<a[k]['net']],key=lambda k:b[k]['net']-a[k]['net'])
    examples=[]
    for k in hurt[:3]:
        before,after=a[k],b[k];first=before['legs'][0]
        examples.append(dict(セッション=k[0],方向=k[3],新規時刻=clock(first['新規時刻']),建値=first['建値'],
            旧収支=before['net'],新収支=after['net'],差=after['net']-before['net'],
            旧全返済時刻=clock(max(t['返済時刻'] for t in before['legs'])),
            新全返済時刻=clock(max(t['返済時刻'] for t in after['legs'])),
            旧返済脚=before['legs'],新返済脚=after['legs']))
    return dict(元組数=len(a),新組数=len(b),同入口数=len(shared),内訳=parts,収支差=net,
        旧黒字から新赤字へ変わった組数=sum(a[k]['net']>0 and b[k]['net']<0 for k in shared),
        旧黒字の利益を削った組数=len(hurt),旧黒字を削った代表例=examples,
        注記='入口行と方向が一致する親組だけ対応。他の入口には先行売買による経路変更が含まれる。旧将来利益は事後の反証材料で、実運用で既知とは扱わない。')


def directional(records,symbol,names):
    """
    機能: 買いと売りの親組収支・利益・損失・料金を同じ商品内で分ける。
    引数: records (dict)、symbol (str)、names (list[str])。
    返り値: dict。
    """
    result={}
    for side,label in ((1,'買い'),(-1,'売り')):
        values=[v for k,v in records.items() if k[1]==symbol and k[0] in names and k[3]==side]
        profit=math.fsum(max(0.,v['net']) for v in values);loss=math.fsum(max(0.,-v['net']) for v in values)
        result[label]=dict(親組数=len(values),利益=profit,損失=loss,収支=profit-loss,
            手数料=math.fsum(v['fee'] for v in values),金額利益割合=profit/(profit+loss) if profit+loss else None)
    return result


def session_difference(a,b,symbol):
    """
    機能: 改善が一場だけに依存するか、全場収支差と最大改善場除外で確認する。
    引数: a/b (dict)、symbol (str)。
    返り値: dict。
    """
    old={r['session']:r for r in a['rows'] if r['symbol']==symbol}
    new={r['session']:r for r in b['rows'] if r['symbol']==symbol}
    rows=[dict(セッション=s,元収支=old[s]['net'],新収支=new[s]['net'],差=new[s]['net']-old[s]['net']) for s in sorted(old)]
    best=max(rows,key=lambda r:r['差']);worst=min(rows,key=lambda r:r['差'])
    return dict(改善場数=sum(r['差']>1e-7 for r in rows),悪化場数=sum(r['差']<-1e-7 for r in rows),
        同額場数=sum(abs(r['差'])<=1e-7 for r in rows),最大改善場=best,最大悪化場=worst,
        最大改善一場を除く収支差=math.fsum(r['差'] for r in rows)-best['差'],全30差額=rows)


def main():
    """
    機能: 主仮説と全十二条件について期間・売買方向・損失と利益の交換をまとめる。
    引数: なし。
    返り値: None。新たな条件の採用やパラメータ変更は行わない。
    """
    fixed=read(ROUND/'事前固定.json');all_models={}
    for model in fixed['models']:
        results,ledgers=packets(model);summaries=[];pairs=[]
        for ident,packet in results.items():
            periods={}
            for period in ('前16','後14','全30'):
                product={}
                for symbol in ('TOPIX','NK225'):
                    metrics={k:packet['periods'][period][symbol][k] for k in FIELDS}
                    base=results['R0_S75']['periods'][period][symbol]
                    delta={k:metrics[k]-base[k] if metrics[k] is not None and base[k] is not None else None for k in FIELDS}
                    product[symbol]=dict(集計=metrics,旧P1との差=delta,
                        買売=directional(ledgers[ident],symbol,fixed[period]),
                        親組分解=matching(ledgers['R0_S75'],ledgers[ident],symbol,fixed[period]))
                periods[period]=product
            summaries.append(dict(条件=ident,固定主仮説=ident=='R3_S50',期間別=periods,
                全場差={s:session_difference(results['R0_S75'],packet,s) for s in ('TOPIX','NK225')}))
        comparisons=[]
        for stop in ('75','50','25'):
            comparisons += [('入口制約のみ',f'R0_S{stop}',f'R{gate}_S{stop}') for gate in (1,2,3)]
        for gate in range(4):
            comparisons += [('初期停止短縮のみ',f'R{gate}_S75',f'R{gate}_S{stop}') for stop in ('50','25')]
        for part,old,new in comparisons:
            for period in ('前16','後14','全30'):
                for symbol in ('TOPIX','NK225'):
                    a,b=results[old]['periods'][period][symbol],results[new]['periods'][period][symbol]
                    differences={k:b[k]-a[k] if b[k] is not None and a[k] is not None else None for k in FIELDS}
                    pairs.append(dict(変更部品=part,元=old,改修=new,期間=period,商品=symbol,差=differences,
                        親組分解=matching(ledgers[old],ledgers[new],symbol,fixed[period])))
        all_models[model]=dict(全12条件=summaries,部品を揃えた比較=pairs)
        print(model,'12条件と部品102比較の原因分解完了',flush=True)
    save('全12条件の改善と旧勝ち取り逃し分解.json',dict(主仮説='R3_S50',結果による主仮説の差替え=False,
        会計='各銘柄の手数料後親組。気配差を混ぜず観測価格と指定線を別評価。',モデル別=all_models,
        制約='全30場既知の探索確認。改善場数や最大一場除外は事後診断であり翌場条件には用いていない。'))


if __name__=='__main__':
    main()
