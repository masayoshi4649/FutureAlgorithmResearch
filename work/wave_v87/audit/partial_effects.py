"""一部の早い利確で確保した額と、残せなかった旧利益を同じ入口で分ける。"""

import math
import pickle
from diagnose import ROOT,HERE,read,save,groups,clock
from boundaries import module

shared=module('監査87親組比較部品',HERE/'effects.py')
ROUND=ROOT/'work/wave_v87/round2'


def load(model,configs):
    """
    機能: 保存された八条件の会計・親組・先行返済の情報を整理する。
    引数: model (str)、configs (list[dict])。
    返り値: tuple[dict,dict,dict]。
    """
    results={};records={};raw={}
    for config in configs:
        ident=config['id'];results[ident]=read(ROUND/model/'results'/f'{ident}.json')
        raw[ident]=pickle.loads((ROUND/model/'ledgers'/f'{ident}.pkl').read_bytes())
        records[ident]={(session,symbol,entry,side):record
            for (session,symbol),ledger in raw[ident].items() for (entry,side),record in groups(ledger).items()}
    return results,records,raw


def affected(old,new,symbol,names):
    """
    機能: 狭い部分返済が実際に起きた親組の最終改善・悪化を同入口で確認する。
    引数: old/new (dict)、symbol (str)、names (list[str])。
    返り値: dict。途中の部分利益を最終利益と混同しない。
    """
    pairs=[]
    for key,b in new.items():
        if key[1]!=symbol or key[0] not in names or key not in old:continue
        narrow=[t for t in b['legs'] if t['理由']==73]
        if not narrow:continue
        a=old[key];first=b['legs'][0]
        pairs.append(dict(セッション=key[0],方向=key[3],新規時刻=clock(first['新規時刻']),建値=first['建値'],
            元収支=a['net'],新収支=b['net'],差=b['net']-a['net'],
            先行分の料金配賦後収支=math.fsum(t['収支'] for t in narrow),
            先行分以外の料金配賦後収支=math.fsum(t['収支'] for t in b['legs'] if t['理由']!=73),
            元全返済時刻=clock(max(t['返済時刻'] for t in a['legs'])),
            新全返済時刻=clock(max(t['返済時刻'] for t in b['legs'])),元返済脚=a['legs'],新返済脚=b['legs']))
    gain=[p for p in pairs if p['差']>1e-7];hurt=[p for p in pairs if p['差']<-1e-7]
    return dict(同入口で先行返済があった親組数=len(pairs),改善組数=len(gain),悪化組数=len(hurt),
        同額組数=len(pairs)-len(gain)-len(hurt),差額=math.fsum(p['差'] for p in pairs),
        先行分の配賦後利益合計=math.fsum(p['先行分の料金配賦後収支'] for p in pairs),
        先行利確しても親組赤字の件数=sum(p['先行分の料金配賦後収支']>0 and p['新収支']<0 for p in pairs),
        元黒字の利益を削った親組数=sum(p['元収支']>0 and p['差']<0 for p in pairs),
        元黒字から新赤字の親組数=sum(p['元収支']>0 and p['新収支']<0 for p in pairs),
        最も確保に寄与した例=sorted(gain,key=lambda p:p['差'],reverse=True)[:3],
        最も旧利益を失った例=sorted(hurt,key=lambda p:p['差'])[:3],
        全同入口の部分返済親組=pairs)


def main():
    """
    機能: 固定主仮説Q40_B0と八条件を、旧GU・床有無の同条件で比較する。
    引数: なし。
    返り値: None。新条件や後付けの採用条件を作らない。
    """
    fixed=read(ROUND/'事前固定.json');models={}
    for model in fixed['models']:
        results,records,raw=load(model,fixed['catalog']);summaries=[];floor_pairs=[]
        for ident,packet in results.items():
            periods={}
            for period in ('前16','後14','全30'):
                product={}
                for symbol in ('TOPIX','NK225'):
                    new=packet['periods'][period][symbol];old=results['Q00_B0']['periods'][period][symbol]
                    fields={k:new[k] for k in shared.FIELDS}
                    product[symbol]=dict(集計=fields,
                        元GUとの差={k:new[k]-old[k] if new[k] is not None and old[k] is not None else None for k in shared.FIELDS},
                        買売=shared.directional(records[ident],symbol,fixed[period]),
                        親組対応=shared.matching(records['Q00_B0'],records[ident],symbol,fixed[period]),
                        実際の先行返済があった組=affected(records['Q00_B0'],records[ident],symbol,fixed[period]))
                periods[period]=product
            summaries.append(dict(条件=ident,固定主仮説=ident=='Q40_B0',期間別=periods,
                全30場差={s:shared.session_difference(results['Q00_B0'],packet,s) for s in ('TOPIX','NK225')}))
        for percent in (0,20,40,60):
            a,b=f'Q{percent:02d}_B0',f'Q{percent:02d}_B1'
            for period in ('前16','後14','全30'):
                for symbol in ('TOPIX','NK225'):
                    old,new=results[a]['periods'][period][symbol],results[b]['periods'][period][symbol]
                    floor_pairs.append(dict(元=a,床追加=b,期間=period,商品=symbol,
                        差={k:new[k]-old[k] if new[k] is not None and old[k] is not None else None for k in shared.FIELDS},
                        親組対応=shared.matching(records[a],records[b],symbol,fixed[period])))
        models[model]=dict(全8条件=summaries,親組床だけの有無比較=floor_pairs)
        print(model,'部分確保の全8条件分解完了',flush=True)
    save('全8部分確保条件の同入口差分と犠牲利益.json',dict(主仮説='Q40_B0',結果からの主仮説差替え=False,
        モデル別=models,注記=['主評価は全返済した親組の手数料後収支。先行部分だけの利益率を手法全体の利益率としない。',
            '元と同じ入口行・方向の親組を対応。旧将来の大勝ちは後から判明した比較結果で、実際の出口では未知。',
            '全30場既知。買い・売り・期間別は説明にだけ用い、成績の良い部分を事後に採用し直していない。']))


if __name__=='__main__':
    main()
