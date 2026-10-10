"""場内完結の全条件を、銘柄別会計と事前に固定した選定基準で比較する。"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import statistics
import re


HERE=Path(__file__).resolve().parent
SYMBOLS=('TOPIX','NK225')
WEEKS=('2026-09-21','2026-09-28','2026-10-05')


def load(branch: str) -> list[dict]:
    """機能: 二つの売買器の軽量出力を同じ条件単位へまとめる。

    引数: branch(str)はdirectional又はinventory。返り値: 全条件(list[dict])。
    """
    source=json.loads((HERE/branch/'集計結果.json').read_text(encoding='utf-8'))
    grouped={}
    for m in source['methods']:
        key=m.get('condition_id',m['id'])
        target=grouped.setdefault(key,dict(id=key,family=m['family'],primary=False,config=m.get('config',m),accounts=[],branch=branch,native_hold={}))
        target['primary'] |= bool(m.get('primary',False))
        if branch=='directional':
            target['native_hold']={mode:{s:m[name][s].get('hold_median_minutes') for s in SYMBOLS}
                for mode,name in (('quote','summary'),('mid','mid_summary'))}
        else:
            target['native_hold'][m['price_mode']]={s:m['summary'][s].get('hold_median_minutes') for s in SYMBOLS}
        for original in m['accounts']:
            a=dict(original)
            a['price_mode']=a.get('price_mode',m.get('price_mode','quote'))
            a['profit']=a.get('profit',a.get('closed_net_profit'))
            a['loss']=a.get('loss',a.get('closed_net_loss'))
            assert a['profit'] is not None and a['loss'] is not None
            a['week']=a.get('week',str((datetime.fromisoformat(a['session'][:10])-timedelta(days=datetime.fromisoformat(a['session'][:10]).weekday())).date()))
            assert abs(a['gross_profit']-a['gross_loss']-a['fees']-a['net'])<1e-4
            assert abs(a.get('unrealized_end',0.))<1e-7
            target['accounts'].append(a)
    expected=270 if branch=='directional' else 180
    assert len(grouped)==expected,(branch,len(grouped))
    return list(grouped.values())


def accounts(method: dict, symbol: str, mode: str='quote', weeks: tuple=WEEKS) -> list[dict]:
    """機能: 条件の銘柄・価格方式・先行期間だけを抽出する。

    引数: method(dict)、symbol/mode(str)、weeks(tuple)。返り値: 口座一覧(list[dict])。
    """
    return sorted((a for a in method['accounts'] if a['symbol']==symbol and a['price_mode']==mode and a['week'] in weeks),key=lambda a:a['session'])


def aggregate(values: list[dict]) -> dict:
    """機能: 決済済み場の金額・枚数・全含み資産の最大下落を再集計する。

    引数: values(list[dict])。返り値: 集計(dict)。異なる商品を足し合わせない。
    """
    keys=('gross_profit','gross_loss','fees','net','profit','loss','win_qty','loss_qty','flat_qty','cycles')
    out={k:sum(a[k] for a in values) for k in keys}
    out['pf']=out['profit']/out['loss'] if out['loss'] else None
    win=out['profit']/out['win_qty'] if out['win_qty'] else None
    loss=out['loss']/out['loss_qty'] if out['loss_qty'] else None
    out['payoff']=win/loss if win is not None and loss else None
    out['positive_sessions']=sum(a['net']>0 for a in values)
    out['active_sessions']=sum(a['cycles']>0 for a in values)
    out['without_best']=out['net']-max(0.,max((a['net'] for a in values),default=0.))
    level=peak=drawdown=0.
    for a in values:
        drawdown=max(drawdown,a['drawdown'],peak-(level+a['equity_min']))
        peak=max(peak,level+a['equity_max'])
        level+=a['net']
    out['drawdown']=drawdown
    out['max_long_qty']=max((a['max_long_qty'] for a in values),default=0)
    out['max_short_qty']=max((a['max_short_qty'] for a in values),default=0)
    out['sessions']=len(values)
    out['win_rate_qty']=out['win_qty']/(out['win_qty']+out['loss_qty']+out['flat_qty']) if out['win_qty']+out['loss_qty']+out['flat_qty'] else None
    holds=[t for a in values for t in a.get('group_hold_minutes',a.get('holding_values',[]))]
    out['hold_median_minutes']=statistics.median(holds) if holds else None
    out['hold_mean_minutes']=statistics.mean(holds) if holds else None
    return out


def score(value: dict) -> float:
    """機能: 費用後PFをゼロ取引・無損失を区別して比較値へ変換する。

    引数: value(dict)。返り値: 順位用数値(float)。
    """
    return value['profit']/value['loss'] if value['loss'] else (1e12 if value['profit']>0 else 0.)


def neighbors(method: dict, methods: list[dict], symbol: str) -> list[dict]:
    """機能: 保有上限・幅・積極度を一軸だけ隣接設定へ変えた既存結果を抽出する。

    引数: method(dict)、methods(list[dict])、symbol(str)。返り値: 隣接比較(list[dict])。
    売買の再計算や、新しい条件追加は行わない。
    """
    family=[m for m in methods if m['family']==method['family']]
    parsed={m['id']:re.search(r'_H(\d+)_(W\d+|D\d+)_(A\d)',m['id']).groups() for m in family}
    choices=[sorted({v[i] for v in parsed.values()},key=lambda x:int(re.sub(r'\D','',x))) for i in range(3)]
    base=parsed[method['id']]
    found=[]
    for m in family:
        setting=parsed[m['id']]
        differences=[i for i in range(3) if base[i]!=setting[i]]
        if len(differences)!=1:
            continue
        i=differences[0]
        if abs(choices[i].index(base[i])-choices[i].index(setting[i]))!=1:
            continue
        found.append(dict(id=m['id'],axis=('保有上限','幅','積極度')[i],setting=setting[i],values=aggregate(accounts(m,symbol))))
    return found


def rank(methods: list[dict], weeks: tuple=WEEKS, minimum: int=20, active: int=8, positive_only: bool=False) -> list[dict]:
    """機能: 各銘柄の必要取引数を満たす条件を、小さい方のPFで順位づけする。

    引数: methods(list[dict])、weeks(tuple)、minimum/active(int)、positive_only(bool)。
    返り値: 正負と集計を含む順位(list[dict])。円収支は銘柄間で合算しない。
    """
    candidates=[]
    for m in methods:
        values={s:aggregate(accounts(m,s,weeks=weeks)) for s in SYMBOLS}
        if any(v['cycles']<minimum or v['active_sessions']<active for v in values.values()):
            continue
        positive=all(v['net']>0 for v in values.values())
        if positive_only and not positive:
            continue
        candidates.append(dict(id=m['id'],branch=m['branch'],positive_both=positive,score=min(score(v) for v in values.values()),values=values))
    return sorted(candidates,key=lambda v:(not v['positive_both'],-v['score'],v['id']))


def main() -> None:
    """機能: 全条件の安定性、時間軸・積極度、週順選定と現在確認候補を記録する。

    引数: なし。返り値: なし(None)。売買器・取引条件は変更しない。
    """
    result={}
    selected={}
    for branch in ('directional','inventory'):
        methods=load(branch)
        summary={m['id']:{s:aggregate(accounts(m,s)) for s in SYMBOLS} for m in methods}
        stable=[]
        risk_reward=[]
        for m in methods:
            v=summary[m['id']]
            qualifies=all(a['net']>0 and a['without_best']>0 and a['cycles']>=20 and a['active_sessions']>=8 for a in v.values())
            qualifies &= all(aggregate(accounts(m,s,weeks=(w,)))['net']>0 for s in SYMBOLS for w in WEEKS)
            if qualifies:
                stable.append(m['id'])
                if all((a['payoff'] or 0)>1 for a in v.values()):
                    risk_reward.append(m['id'])
        ranking=rank(methods)
        selected[branch]=ranking[0] if ranking else None
        sequence=[]
        for training,test in ((WEEKS[:1],WEEKS[1]),(WEEKS[:2],WEEKS[2])):
            earlier=rank(methods,training,minimum=10,active=0,positive_only=True)
            chosen=earlier[0] if earlier else None
            item=dict(training=list(training),testing=test,selected=chosen)
            if chosen:
                m=next(m for m in methods if m['id']==chosen['id'])
                item['next_week']={s:aggregate(accounts(m,s,weeks=(test,))) for s in SYMBOLS}
            sequence.append(item)
        positive={mode:{s:sum(aggregate(accounts(m,s,mode))['net']>0 for m in methods) for s in SYMBOLS}
                  for mode in ('quote','mid')+(('passive',) if branch=='inventory' else ())}
        common={mode:sum(all(aggregate(accounts(m,s,mode))['net']>0 for s in SYMBOLS) for m in methods)
                for mode in positive}
        symbol_ranking={s:sorted([dict(id=m['id'],values=summary[m['id']][s]) for m in methods
            if summary[m['id']][s]['cycles']>=20 and summary[m['id']][s]['active_sessions']>=8],
            key=lambda v:(-v['values']['net'],v['id']))[:5] for s in SYMBOLS}
        adjacent={s:neighbors(next(m for m in methods if m['id']==v[0]['id']),methods,s) for s,v in symbol_ranking.items() if v}
        result[branch]=dict(count=len(methods),positive=positive,common_positive=common,stable=stable,
            stable_and_payoff=risk_reward,ranking=ranking[:5],symbol_ranking=symbol_ranking,neighbors=adjacent,summary=summary,sequence=sequence)
    (HERE/'比較と選定.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    fixed=dict(selected=selected,selection_rule='各20決済/8稼働場。共通黒字優先、小さい方のPF順、同点ID。なければ赤字参考。',
        frozen_at=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        sources={b:hashlib.sha256((HERE/b/'集計結果.json').read_bytes()).hexdigest() for b in result},
        note='現在データ取得前の候補固定。保存25場は既知、選定は事後比較である。')
    target=HERE/'live'/'候補固定.json'
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        previous=json.loads(target.read_text(encoding='utf-8'))
        assert previous['selected']==fixed['selected'] and previous['sources']==fixed['sources']
    else:
        target.write_text(json.dumps(fixed,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({b:{k:v[k] for k in ('count','positive','common_positive','stable','stable_and_payoff')} for b,v in result.items()},ensure_ascii=False))


if __name__=='__main__':
    main()
