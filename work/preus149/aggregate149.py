"""隔離Goの約定を独立に再会計し、夜単位の前後比較へ集計する。"""

import hashlib
import json
import pickle
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def totals(rows):
    """夜単位の収支と完結親単位の利益損失を集計する。

    引数: rows(list[dict])は同じ条件の完了夜。
    返り値: dictは合計と赤字頻度・深さ・大勝ち除外後収支。
    """
    nets=np.array([r['net'] for r in rows],float)
    red=nets[nets<0]; green=nets[nets>0]
    profit=sum(r['profit'] for r in rows); loss=sum(r['loss'] for r in rows)
    return dict(sessions=len(rows),profit=profit,loss=loss,net=float(nets.sum()),pf=profit/loss if loss else None,
                wins=len(green),losses=len(red),zero=int(np.sum(nets==0)),
                median=float(np.median(nets)) if len(nets) else None,
                maxloss=float(-red.min()) if len(red) else 0,
                avgloss=float(-red.mean()) if len(red) else 0,
                medianloss=float(-np.median(red)) if len(red) else 0,
                ex3=float(nets.sum()-sum(sorted(green,reverse=True)[:3])),
                entries=sum(r['entries'] for r in rows),zero_entries=sum(r['entries']==0 for r in rows))


def group_account(parents):
    """親単位の利益損失を計算する。

    引数: parents(list[dict])は対象区間の親。
    返り値: dictは利益・損失・収支・新規件数。
    """
    return dict(profit=sum(max(0,p['net']) for p in parents),loss=sum(max(0,-p['net']) for p in parents),
                net=sum(p['net'] for p in parents),entries=sum(p['entries'] for p in parents),parents=len(parents))


def account(scene,case):
    """所有IDごとに全約定を追跡しGo出力の現金・利益と照合する。

    引数: scene(dict)は夜の時刻、case(dict)は一条件の全約定。
    返り値: dictは独立会計と親明細。気配・取引判断は生成しない。
    """
    lots={}; parents={}; cash=0.; maxheld=0
    for event in case['events'] or []:
        signal,fill=event['signal'],event['fill']
        side,qty,price=signal['side'],fill['Quantity'],fill['Price']
        assert side in (-1,1) and qty>0 and qty==signal['quantity'] and fill['Fee']==0
        assert event['fill_index']>event['decision_index'] and fill['Time']>=signal['time']
        cash-=side*qty*price*100
        parent=f"{event['phase']}/{signal['owner']}/{signal['campaign']}"
        gain=0.
        if signal['action']=='new':
            assert fill['HoldID'] not in lots
            lots[fill['HoldID']]=dict(parent=parent,side=side,qty=qty,price=price)
            p=parents.setdefault(parent,dict(id=parent,owner=signal['owner'],phase=event['phase'],entry=fill['Time'],exit=fill['Time'],
                                             segment='pre' if fill['Time']<scene['us_open'] else 'post',net=0.,entries=0,quantity=0,side=side))
            p['entries']+=1;p['quantity']+=qty
        else:
            closed=0
            for target in fill['Closed']:
                lot=lots[target['id']]; q=target['quantity']
                assert lot['side']==-side and 0<q<=lot['qty']
                value=lot['side']*q*(price-lot['price'])*100
                gain+=value;closed+=q;lot['qty']-=q
                p=parents[lot['parent']];p['net']+=value;p['exit']=fill['Time']
            assert closed==qty and abs(gain-event['gross'])<1e-6
        maxheld=max(maxheld,*[sum(l['qty'] for l in lots.values() if l['side']==s) for s in (-1,1)])
        assert maxheld<=10
    realized=sum(p['net'] for p in parents.values())
    assert abs(realized-case['Gross'])<1e-6
    remaining=[l for l in lots.values() if l['qty']]
    assert scene['partial'] or not remaining
    if not remaining: assert abs(cash-realized)<1e-6
    assert maxheld==case['max_per_side']
    assert set(parents).issuperset(case['parents'])
    for name,value in case['parents'].items(): assert abs(parents[name]['net']-value)<1e-6
    values=list(parents.values())
    result=group_account(values)
    result.update(session=scene['session'],pre=group_account([p for p in values if p['segment']=='pre']),
                  post=group_account([p for p in values if p['segment']=='post']),
                  parent_details=values,max_per_side=maxheld,unrealized=case['Unrealized'],equity=realized+case['Unrealized'],
                  first_entry=min((p['entry'] for p in values),default=None),
                  first_post_entry=min((p['entry'] for p in values if p['segment']=='post'),default=None),
                  pre_flat_at=case['pre_flat_at'],post_started=case['post_started'])
    assert result['pre']['net']+result['post']['net']==result['net']
    return result


def main():
    """全16条件の25夜を同じ会計で集計し、既存保存D07とは別に比較する。

    引数: なし。
    返り値: None。report149.jsonへ全結果を保存する。
    """
    configs=json.loads((HERE/'configs149.json').read_text(encoding='utf-8-sig'))
    folders=[HERE/'results_go']
    if (HERE/'configs_round2.json').exists():
        configs+=json.loads((HERE/'configs_round2.json').read_text(encoding='utf-8-sig'))
        folders.append(HERE/'results_round2')
    byid={c['id']:dict(id=c['id'],description=c['description'],config=c,rows=[]) for c in configs}
    partial=[]; signatures={c['id']:[] for c in configs}; baseline=[]
    manifest=json.loads((HERE/'data/原資料一覧149.json').read_text(encoding='utf-8-sig'))
    for path in [p for folder in folders for p in sorted(folder.glob('*_Night.json'))]:
        saved=json.loads(path.read_text(encoding='utf-8'))
        scene=saved['scene']
        assert len(saved['cases'])==(16 if path.parent.name=='results_go' else 4)
        if not scene['partial']:
            with (ROOT/'work/preus148/inputs'/f"{scene['session']}.pkl").open('rb') as stream:
                old_packet=pickle.load(stream)
        for case in saved['cases']:
            identifier=case['config']['id']
            row=account(scene,case)
            if scene['partial']:
                partial.append(dict(id=identifier,**row))
            else:
                row['direction']=old_packet['label']['direction']
                row['first_post_delay_minutes']=(row['first_post_entry']-scene['us_open'])/60 if row['first_post_entry'] is not None else None
                byid[identifier]['rows'].append(row)
                semantic=[(e['signal']['owner'],e['signal']['action'],e['signal']['side'],e['fill']['Quantity'],e['fill']['Price'],e['fill']['Time']) for e in case['events'] or []]
                signatures[identifier].append((scene['session'],semantic))
                if identifier=='C00':
                    old=old_packet['baseline']
                    old_net=float(-np.sum(old[:,3]*old[:,4]*old[:,5])*100)
                    baseline.append(dict(session=scene['session'],saved145=old_net,current_go=row['net'],difference=row['net']-old_net))
    expected=[s['session'] for s in manifest['sessions'] if not s['partial']]
    for method in byid.values():
        assert [r['session'] for r in method['rows']]==expected
        method['summary']=totals(method['rows'])
        for segment in ('pre','post'): method[segment]=totals([r[segment] for r in method['rows']])
        method['by_direction']={direction:totals([r for r in method['rows'] if r['direction']==direction])
                                for direction in sorted(set(r['direction'] for r in method['rows']))}
        delays=[r['first_post_delay_minutes'] for r in method['rows'] if r['first_post_delay_minutes'] is not None]
        method['post_delay']=dict(n=len(delays),minimum=min(delays) if delays else None,median=float(np.median(delays)) if delays else None)
    equivalent=[]
    ids=list(byid)
    for i,one in enumerate(ids):
        for two in ids[i+1:]:
            if signatures[one]==signatures[two]: equivalent.append([one,two])
    report=dict(methods=list(byid.values()),partial=partial,old_baseline_comparison=baseline,equivalent_paths=equivalent,
                definition='利益損失は同一担当・同一親の全返済収支で分類。前後は親の初回新規約定が米国開始より前か後かで所属。Rは状態も分離。途中場は25夜集計から除外。',
                validation=dict(expected_complete_nights=len(expected),all_orders_independently_accounted=True,cap_and_ids_checked=True,fee=0,point_value=100))
    (HERE/'report149.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({m['id']:dict(net=m['summary']['net'],pre=m['pre']['net'],post=m['post']['net'],losses=m['summary']['losses'],ex3=m['summary']['ex3']) for m in byid.values()},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
