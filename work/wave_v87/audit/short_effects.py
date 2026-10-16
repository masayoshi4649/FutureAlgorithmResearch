"""最新支持十条件の入口変更を、見送った旧勝敗・追加経路・料金へ独立に分解する。"""

import hashlib
import math
import pickle
from diagnose import ROOT,HERE,read,save,groups
from boundaries import module

shared=module('監査87支持の親組分解部品',HERE/'effects.py')
ROUND=ROOT/'work/wave_v87/round3'


def amounts(values):
    """
    機能: 親組の料金前後と勝敗金額を加算する。
    引数: values(iterable[dict])。
    返り値: dict。
    """
    values=list(values)
    return dict(親組数=len(values),料金前=math.fsum(v['gross'] for v in values),
        料金=math.fsum(v['fee'] for v in values),料金後=math.fsum(v['net'] for v in values),
        黒字組数=sum(v['net']>0 for v in values),赤字組数=sum(v['net']<0 for v in values),
        総利益=math.fsum(max(0,v['net']) for v in values),総損失=math.fsum(max(0,-v['net']) for v in values))


def entrance_parts(old,new,symbol,names):
    """
    機能: 同行同方向・消えた旧入口・新しい入口へ料金前後を分ける。
    引数: old/new(dict)、symbol(str)、names(list[str])。
    返り値: dict。消えた入口には先行売買による経路変更も含む。
    """
    a={k:v for k,v in old.items() if k[1]==symbol and k[0] in names}
    b={k:v for k,v in new.items() if k[1]==symbol and k[0] in names}
    common=a.keys()&b.keys();removed=a.keys()-b.keys();added=b.keys()-a.keys()
    old_same=amounts(a[k] for k in common);new_same=amounts(b[k] for k in common)
    gone=amounts(a[k] for k in removed);extra=amounts(b[k] for k in added)
    delta={k:new_same[k]-old_same[k] for k in ('料金前','料金','料金後')}
    for name,key in (('料金前','gross'),('料金','fee'),('料金後','net')):
        expected=math.fsum(v[key] for v in b.values())-math.fsum(v[key] for v in a.values())
        assert abs(delta[name]-gone[name]+extra[name]-expected)<1e-6
    return dict(同行同方向の元=old_same,同行同方向の新=new_same,同行同方向の差=delta,
        消失した旧入口=gone,追加の新入口=extra,
        旧黒字を見送った収支損失=-math.fsum(a[k]['net'] for k in removed if a[k]['net']>0),
        旧赤字を見送った収支改善=-math.fsum(a[k]['net'] for k in removed if a[k]['net']<0),
        説明='同じ入力行・売買方向を対応する。指定価格モデルでは同じ行でも指値と再公開成行の約定価格が異なる場合がある。消失は直接の支持見送りに限らず、先行売買の保有変更や注文準備の時点変更を含む。')


def packets(model,configs):
    """
    機能: 固定十条件の保存集計と親組を読み取り、指紋を照合する。
    引数: model(str)、configs(list[dict])。
    返り値: tuple[dict,dict]。
    """
    results={};records={}
    for config in configs:
        ident=config['id'];p=ROUND/model/'results'/f'{ident}.json';result=read(p)
        ledger_path=ROUND/model/'ledgers'/f'{ident}.pkl'
        assert hashlib.sha256(ledger_path.read_bytes()).hexdigest()==result['ledger_SHA256']
        raw=pickle.loads(ledger_path.read_bytes())
        results[ident]=result
        records[ident]={(session,symbol,entry,side):r for (session,symbol),ledger in raw.items()
            for (entry,side),r in groups(ledger).items()}
    return results,records


def main():
    """
    機能: 同一親方式F0との料金前後・活動数・入口変更を全十条件の前後半に分ける。
    引数: なし。
    返り値: None。固定主GU_F2/P1_F2を結果から差し替えない。
    """
    fixed=read(ROUND/'事前固定.json');models={}
    for model in fixed['models']:
        results,records=packets(model,fixed['catalog']);summaries=[];parts=[]
        for config in fixed['catalog']:
            ident=config['id'];baseline=config['parent_id']+'_F0';packet=results[ident]
            periods={}
            for period in ('前16','後14','全30'):
                product={}
                for symbol in ('TOPIX','NK225'):
                    new=packet['periods'][period][symbol];old=results[baseline]['periods'][period][symbol]
                    metrics={name:new[name] for name in shared.FIELDS}
                    metrics['活動場数']=len(fixed[period])-new['no_trade_sessions']
                    metrics['平均料金後収支']=new['net']/new['campaigns'] if new['campaigns'] else None
                    mapping=shared.matching(records[baseline],records[ident],symbol,fixed[period])
                    money=entrance_parts(records[baseline],records[ident],symbol,fixed[period])
                    assert mapping['元組数']==old['campaigns'] and mapping['新組数']==new['campaigns']
                    assert abs(mapping['収支差']-(new['net']-old['net']))<1e-6
                    product[symbol]=dict(集計=metrics,
                        同親方式F0との差={k:new[k]-old[k] if new[k] is not None and old[k] is not None else None for k in shared.FIELDS},
                        買売=shared.directional(records[ident],symbol,fixed[period]),
                        入口対応=mapping,入口変更の料金前後=money)
                periods[period]=product
            summaries.append(dict(条件=ident,元条件=baseline,固定主仮説=ident in ('GU_F2','P1_F2'),期間別=periods,
                場別差={s:shared.session_difference(results[baseline],packet,s) for s in ('TOPIX','NK225')}))
        # ----------------------------------------
        # 最新化・極値後・他市場追加を、同じ親方式と他部品を揃えて分ける。
        for parent in ('GU','P1'):
            for label,a,b in (('自己支持の最新化',0,1),('自己極値後だけ追加',1,2),('相手支持だけ追加',1,3),('相手極値後支持を追加',2,4),('双方極値後だけ追加',3,4)):
                old_id,new_id=f'{parent}_F{a}',f'{parent}_F{b}'
                for period in ('前16','後14','全30'):
                    for symbol in ('TOPIX','NK225'):
                        old=results[old_id]['periods'][period][symbol];new=results[new_id]['periods'][period][symbol]
                        parts.append(dict(変更=label,元=old_id,新=new_id,期間=period,商品=symbol,
                            差={k:new[k]-old[k] if new[k] is not None and old[k] is not None else None for k in shared.FIELDS},
                            入口変更の料金前後=entrance_parts(records[old_id],records[new_id],symbol,fixed[period])))
        models[model]=dict(全10条件=summaries,部品差だけの比較=parts)
        print(model,'十条件の入口変更と料金前後を分解',flush=True)
    save('全10支持条件の入口変更と料金前後の独立分解.json',dict(固定主仮説=['GU_F2','P1_F2'],主の差替え=False,
        モデル別=models,注記=['親組全返済の収支で評価し、決済脚だけの高勝率へ置き換えない。',
            '主モデルは観測CurrentPriceであり、売買気配差を再現した成績ではない。料金を差し引き、追加固定遅延は置かない。',
            '全30場は既知。前16/後14、旧勝敗、活動数は診断であり、新たに成績の良い条件を選ぶための未知検証ではない。']))


if __name__=='__main__':
    main()
