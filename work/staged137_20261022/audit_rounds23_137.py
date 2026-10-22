"""第二・第三巡の保存注文を、金融再生せず独立会計と変更部品で照合する。"""

from collections import defaultdict
import json
from pathlib import Path
import pickle
import numpy as np
from audit_financial137 import ledger, read, digest, equal, summary

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def compare(saved, measured):
    """
    機能: 独立会計を保存済み場・親・脚会計へ照合する。
    引数: saved/measured(dict)は保存値と独立値。
    返り値: intは一致項目数。
    """
    count=0
    for key in ('net','profit','loss','gross','fees','entries','quantity','max_per_side'):
        equal(saved[key],measured[key]);count+=1
    ps={int(x['id']):x for x in saved['parents']}
    assert ps.keys()==measured['parents'].keys()
    for pid,p in measured['parents'].items():
        for key in ('gross','fees','net','entry','exit','side'):
            equal(p[key],ps[pid][key]);count+=1
        for leg,item in p['legs'].items():
            for key in ('gross','fees','net','entries','quantity'):
                equal(item[key],ps[pid]['legs'][str(leg)][key]);count+=1
    return count


def main():
    """
    機能: 米国前移植と追撃停止幅の保存結果を独立検算する。
    引数: なし。
    返り値: None。全巡が揃っていれば同じ監査ファイルへ完全結果を保存する。
    """
    first=read(HERE/'結果.json');firstrows={(x['session'],x['method']):x for x in first['rows']}
    outputs={};totals=defaultdict(int);earlyrows=[];deltas=[];stopchanges=[];lastlag=[];addition_values=defaultdict(list)
    old=read(ROOT/'work/visual_pdca129_20261020/round7/固定計画.json')
    native=next(c for c in old['configs'] if c['id']=='NV25')
    for number,planfile in ((2,'第二巡計画.json'),(3,'第三巡計画.json')):
        if not (HERE/f'結果{number}.json').exists():continue
        result=read(HERE/f'結果{number}.json');plan=read(HERE/planfile)
        rows={(x['session'],x['method']):x for x in result['rows']};caches={x['session']:x for x in result['cache']}
        if number==2:
            expected=dict(native);expected['phase']=2
            assert expected==plan['configs']['native']
        for item in plan['inputs']:
            scene=item['session'];cache=caches[scene]
            for r in (item['input'],item['orders'],cache):assert digest(ROOT/r['path'])==r['sha256']
            packet=pickle.loads((ROOT/item['input']['path']).read_bytes());key=(scene,'NK225')
            ready=packet['inputs'][key];q=packet['quotes'][key];ts=ready['time_s'];bid=q['bid'];ask=q['ask']
            good=q['quote_valid']&np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid);normal=np.flatnonzero(good)
            prefix='' if item['prefix']=='なし' else item['prefix']
            with np.load(ROOT/item['orders']['path'],allow_pickle=False) as oldorders:
                source=np.concatenate([oldorders[prefix+'core_orders'],oldorders[prefix+'extra_orders']])
                keys={(int(o[0]),int(o[1]),int(o[2]),int(o[3]),float(o[5]),int(o[6]),int(o[7])) for o in source}
            with np.load(ROOT/cache['path'],allow_pickle=False) as new, np.load(HERE/'measurement'/f'{scene}.npz',allow_pickle=False) as oldcache:
                for (s,method),saved in rows.items():
                    if s!=scene:continue
                    orders=new[method];measured=ledger(orders,ts,bid,ask,normal,keys)
                    totals['会計項目']+=compare(saved,measured);totals['注文']+=len(orders)
                    totals['次正常行']+=measured['normal_fill_checks'];totals['元通知']+=measured['fixed_notifications']
                    if number==2 and method!='CT00':
                        base='B05' if method.startswith('NB_') else 'CT02'
                        ec=method.split('_',1)[1];early=new[ec]
                        assert np.array_equal(orders[orders[:,8]<20],oldcache[base])
                        equal(saved['net'],firstrows[(scene,base)]['net']+ledger(early,ts,bid,ask,normal,None)['net'])
                    if number==3:
                        base='CT02' if method.startswith('CW') else 'C02a'
                        prior=oldcache[base]
                        assert np.array_equal(orders[orders[:,8]!=1],prior[prior[:,8]!=1])
                        assert np.array_equal(orders[orders[:,7]==1],prior[prior[:,7]==1])
                        stopchanges.append(dict(session=scene,method=method,base=base,delta=saved['net']-firstrows[(scene,base)]['net']))
                        for p in measured['parents'].values():
                            if 1 in p['legs']:
                                addition_values[method].append(p['legs'][1]['net'])
                if number==2:
                    ct=new['CT00'];prior=oldcache['CT02'];assert np.array_equal(ct,prior[prior[:,8]!=1])
                    deltas.append(dict(session=scene,base='CT00',change='CT02',delta=firstrows[(scene,'CT02')]['net']-rows[(scene,'CT00')]['net']))
                    if scene.endswith('_Night'):
                        seed=new['仮想米前通知']
                        end=ready['us_open']-900.;endrow=np.searchsorted(ts,end,side='left')
                        maximum=normal[np.searchsorted(normal,endrow,side='right')]
                        seedkeys={(int(o[0]),int(o[1]),int(o[2]),int(o[3]),float(o[5]),int(o[6]),int(o[7])) for o in seed}
                        for ec in ('E5','E2','EC2'):
                            early=new[ec];measured=ledger(early,ts,bid,ask,normal,None)
                            for o in early:
                                if int(o[6]) not in (901,902):
                                    assert (int(o[0]),int(o[1]),int(o[2])-30000,int(o[3]),float(o[5]),int(o[6]),int(o[7])) in seedkeys
                                if int(o[7]):assert ts[int(o[1])]<end and ts[int(o[0])]<end
                            if len(early):
                                assert early[-1,0]<=maximum
                                lastlag.append(dict(session=scene,method=ec,last_minus_deadline=float(ts[int(early[-1,0])]-end)))
                            earlyrows.append(dict(session=scene,method=ec,**{k:measured[k] for k in ('net','profit','loss','entries','quantity')}))
            print(scene,f'第{number}巡独立照合',flush=True)
        outputs[str(number)]=dict(accounts=len(rows),result_sha256=digest(HERE/f'結果{number}.json'),
            summaries={m:{'all':summary([r for (s,n),r in rows.items() if n==m]),
                          'day':summary([r for (s,n),r in rows.items() if n==m and s.endswith('_Day')]),
                          'night':summary([r for (s,n),r in rows.items() if n==m and s.endswith('_Night')])}
                       for m in sorted({m for s,m in rows})})
    earlysum={m:summary([x for x in earlyrows if x['method']==m]) for m in sorted({x['method'] for x in earlyrows})}
    additions={m:dict(parents=len(v),positive=sum(x>0 for x in v),negative=sum(x<0 for x in v),
        net=sum(v),without_top3=sum(v)-sum(sorted([x for x in v if x>0],reverse=True)[:3])) for m,v in addition_values.items()}
    evidence=dict(passed=True,completed_rounds=list(outputs),rounds=outputs,checks=dict(totals),
        pre_us=earlysum,pre_us_last_fill=lastlag,ct02_minus_ct00=deltas,stop_width_changes=stopchanges,
        addition_contribution=additions,
        financial_replays=0,api=0,note='保存済み会計の独立検算であり、新しい金融標本ではない。第二巡はNV25のphaseだけ2に変更し終端を米国開始15分前へ限定。')
    (HERE/'audit_rounds23_137.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 第二・第三巡の独立監査','',f'完了巡: {", ".join(outputs)}。注文{totals["注文"]:,}件・会計項目{totals["会計項目"]:,}件が一致。金融再生0、API0。','',
           '第二巡は保存NV25からphaseだけを変更したこと、米国開始15分前までの新規・終端の次正常行返済・元後半の注文不変を確認。第三巡は初期玉と全新規列が第一巡と完全一致し、差は追撃返済だけ。','',
           '| 巡・条件 | 全場収支 | 黒字／赤字／無取引 | 平均赤字 | 最大赤字 | 上位3黒字を除く収支 |','|---|---:|---:|---:|---:|---:|']
    for number,body in outputs.items():
        for method,p in body['summaries'].items():
            s=p['all'];lines.append(f'| {number}・{method} | {s["net"]:+,.0f}円 | {s["black"]}／{s["red"]}／{s["no_trade"]} | {s["mean_loss"]:,.0f}円 | {s["worst_loss"]:,.0f}円 | {s["without_top3"]:+,.0f}円 |')
    lines+=['','| 米国前の単独寄与 | 収支 | 黒字／赤字／無取引 |','|---|---:|---:|']
    for method,s in earlysum.items():lines.append(f'| {method} | {s["net"]:+,.0f}円 | {s["black"]}／{s["red"]}／{s["no_trade"]} |')
    lines+=['','| 第三巡の追撃分 | 追加親の勝ち／負け | 追加収支 | 追加益上位3親を除く |','|---|---:|---:|---:|']
    for method,s in additions.items():lines.append(f'| {method} | {s["positive"]}／{s["negative"]} | {s["net"]:+,.0f}円 | {s["without_top3"]:+,.0f}円 |')
    lines+=['','既知45場を見た後の改善である。実mini板、実受信時計、Go本体の数量状態まで同値という検査ではない。']
    (HERE/'audit_rounds23_137.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,completed_rounds=list(outputs),checks=dict(totals)),ensure_ascii=False))


if __name__=='__main__':
    main()
