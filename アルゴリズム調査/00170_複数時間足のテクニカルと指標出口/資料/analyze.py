"""新規72候補の選択と時系列確認を、凍結した順位規則で分離する。"""
import argparse
import json
import statistics
from pathlib import Path


def dump(path, value):
    """機能: 小容量の集計をUTF-8で保存。引数: path(Path),value(object)。返り値: None。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def metrics(rows):
    """機能: 完全場だけの損失・偏りを同じ分母で計測。引数: rows(list[dict])。返り値: dict。"""
    rows=[r for r in rows if r['complete']]
    values=[r['realized_yen'] for r in rows]
    pos=[x for x in values if x>0]; neg=[x for x in values if x<0]
    profit=sum(r['gross_profit_yen'] for r in rows); loss=sum(r['gross_loss_yen'] for r in rows)
    long_net=sum(r['long_profit_yen']-r['long_loss_yen'] for r in rows)
    short_net=sum(r['short_profit_yen']-r['short_loss_yen'] for r in rows)
    fee_rate=38.5 if rows and rows[0]['symbol']=='NK225' else 41.8
    return {'sessions':len(rows),'profit':profit,'loss':loss,'net':sum(values),
            'pf':profit/loss if loss else None,'profit_share':profit/(profit+loss) if profit+loss else None,
            'positive':len(pos),'negative':len(neg),'flat':sum(x==0 for x in values),
            'no_trade':sum(r['entry_count']==0 for r in rows),
            'median':statistics.median(values) if values else 0,
            'mean_win':statistics.mean(pos) if pos else 0,
            'mean_loss':-statistics.mean(neg) if neg else 0,
            'max_loss':-min(values+[0]),'max_dd':max([r['max_drawdown_yen'] for r in rows]+[0]),
            'net_without_best':sum(values)-max(values+[0]),
            'net_without_best3':sum(values)-sum(sorted([x for x in values if x>0],reverse=True)[:3]),
            'long_net':long_net,'short_net':short_net,
            'long_episodes':sum(r['long_episodes'] for r in rows),'short_episodes':sum(r['short_episodes'] for r in rows),
            'entry_count':sum(r['entry_count'] for r in rows),
            'positive_then_negative':sum(r['positive_then_negative'] for r in rows),
            'fees_reference':sum((r['new_qty']+r['closed_qty'])*fee_rate for r in rows),
            'reference_net_after_fees':sum(values)-sum((r['new_qty']+r['closed_qty'])*fee_rate for r in rows)}


def rank_key(m):
    """機能: 検討期間だけで安定性の順位を固定。引数:m(dict)。返り値:tuple。"""
    flags=[m['net']<=0,m['net_without_best']<=0,m['no_trade']>0,
           m['long_net']<0 or m['short_net']<0 or min(m['long_episodes'],m['short_episodes'])==0]
    n=max(1,m['sessions']);cover=m['negative']/n
    loss_ratio=m['max_loss']/m['mean_win'] if m['mean_win'] else 1e9
    pf=m['pf'] if m['pf'] is not None else (100 if m['profit']>0 else 0)
    return (sum(flags),cover,-m['median'],loss_ratio,-min(pf,100),-m['net'])


def select(source, output):
    """機能: 確認収支を順位へ使わず候補を選択。引数:source/output(Path)。返り値:None。"""
    data=json.loads(source.read_text(encoding='utf-8'));results=data['results'];audits=data['audits']
    splits=[];train={}
    for symbol in ['NK225','TOPIX']:
        ordered=sorted([a for a in audits if a['symbol']==symbol],key=lambda a:a['start_ns'])
        # 全57場なら34場、母数が変わっても開始時刻だけで60%へ分割します。
        cutoff=int(len(ordered)*0.60)
        train[symbol]={a['session'] for a in ordered[:cutoff]}
        for a in ordered:
            first,last=a.get('first_valid_last',0),a.get('last_valid_last',0)
            direction='判定不可' if first<=0 or last<=0 else ('上昇' if last>first else '下落' if last<first else '横ばい')
            splits.append({'symbol':symbol,'session':a['session'],'phase':'検討' if a['session'] in train[symbol] else '確認','direction':direction,'complete':a['complete']})
    chosen=[]
    for symbol in ['NK225','TOPIX']:
        for kind in ['Day','Night']:
            candidates=[]
            for c in data['configs']:
                if c['exit_mode']=='T':continue
                rows=[r for r in results if r['symbol']==symbol and r['config_id']==c['id'] and r['session'].endswith('_'+kind) and r['session'] in train[symbol]]
                m=metrics(rows);candidates.append((rank_key(m),c['id'],m))
            candidates.sort(key=lambda x:(x[0],x[1]));key,method,m=candidates[0]
            base=method.rsplit('_',1)[0]
            chosen.append({'symbol':symbol,'kind':kind,'method_id':method,'algorithm_id':symbol+'_T170_'+method,
                           'control_id':base+'_T','indicator_control_id':base+'_I','train_metrics':m,'ranking_key':key,
                           'label':'検討区間上位。確認成績による選び直しなし'})
    dump(output,{'schema_version':1,'source':'summary.json','policy':'前60%の完全場だけで候補を固定。後40%の収支は選択へ不使用。全既知保存データであり完全未見とは称さない。',
                 'ranking':'検討総赤字・最大黒字依存・無取引・買売片側未確認の4不備数→赤字場率→中央値→最大赤字/平均黒字→PF→収支',
                 'splits':splits,'selected':chosen})
    print(json.dumps({'selected':chosen},ensure_ascii=False,allow_nan=False))


def validate(source, selection, output):
    """機能: 選択を変えず確認区間・上下場別と出口差を測る。引数:3つのPath。返り値:None。"""
    data=json.loads(source.read_text(encoding='utf-8'));chosen=json.loads(selection.read_text(encoding='utf-8'))
    split={(s['symbol'],s['session']):s for s in chosen['splits']};groups=[]
    for g in chosen['selected']:
        obj=dict(g);obj['evaluations']={}
        for mid in dict.fromkeys([g['method_id'],g['control_id'],g['indicator_control_id']]):
            rows=[r for r in data['results'] if r['symbol']==g['symbol'] and r['config_id']==mid and r['session'].endswith('_'+g['kind'])]
            obj['evaluations'][mid]={phase:metrics([r for r in rows if split[(r['symbol'],r['session'])]['phase']==phase]) for phase in ['検討','確認']}
            obj['evaluations'][mid]['全完全場']=metrics(rows)
            obj['evaluations'][mid]['上昇']=metrics([r for r in rows if split[(r['symbol'],r['session'])]['direction']=='上昇'])
            obj['evaluations'][mid]['下落']=metrics([r for r in rows if split[(r['symbol'],r['session'])]['direction']=='下落'])
        groups.append(obj)
    dump(output,{'groups':groups})
    print(json.dumps({'validation':[{'symbol':g['symbol'],'kind':g['kind'],'method':g['method_id'],'check':g['evaluations'][g['method_id']]['確認'],'all':g['evaluations'][g['method_id']]['全完全場']} for g in groups]},ensure_ascii=False))


def main():
    """機能: 選択と事後確認を別操作に分ける。引数:CLI。返り値:None。"""
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['select','validate']);p.add_argument('--source',type=Path,default=Path('summary.json'));p.add_argument('--selection',type=Path,default=Path('rootselection.json'));p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.mode=='select':select(a.source,a.output or a.selection)
    else:validate(a.source,a.selection,a.output or Path('validation.json'))


if __name__=='__main__':main()
