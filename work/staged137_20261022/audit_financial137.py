"""保存済み注文だけから、日経ミニ数量比較の現金・FIFO会計を独立照合する。"""

from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path
import pickle
import statistics
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path):
    """
    機能: 保存済みJSONを読む。
    引数: path(Path)は位置。
    返り値: dict又はlistは内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    """
    機能: 保存物の内容指紋を計算する。
    引数: path(Path)は位置。
    返り値: strはSHA256。
    """
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def equal(a, b):
    """
    機能: 小数丸めだけを許した会計一致を要求する。
    引数: a/b(float)は比較値。
    返り値: None。不一致で停止する。
    """
    assert abs(a-b) < 1e-7, (a,b)


def ledger(orders, times, bid, ask, normal, original_keys=None):
    """
    機能: 新規玉のFIFOと全注文の現金差額を別々に積算する。
    引数: orders/times/bid/ask/normal(ndarray)、original_keys(set又はNone)は保存素材。
    返り値: dictは親・脚・最大枚数・注文数・次正常行検査件数。
    """
    inventory = defaultdict(deque)
    parent = defaultdict(lambda: dict(gross=0., fees=0, entries=0, quantity=0, cash=0., legs={}))
    held = {1:0, -1:0}; largest=0; entries=quantity=delayed=fixed=0
    for o in orders:
        i,d,cid,side,qty = (int(v) for v in o[:5])
        px=float(o[5]); reason=int(o[6]); new=int(o[7]); leg=int(o[8]); fee=int(o[9])
        assert side in (-1,1) and qty>0 and 0<=d<i<len(times)
        assert np.isfinite(px) and px>0 and fee==int(qty*385//10)
        assert normal[np.searchsorted(normal,i)]==i
        equal(px, ask[i] if side==1 else bid[i])
        if reason in (901,902) or original_keys is None or leg>=10:
            assert normal[np.searchsorted(normal,d,side='right')]==i, (cid,leg,d,i)
            delayed+=1
        else:
            oid=cid-10000 if leg==2 else cid
            assert (i,d,oid,side,px,reason,new) in original_keys
            fixed+=1
        p=parent[cid]
        item=p['legs'].setdefault(leg, dict(gross=0.,fees=0,entries=0,quantity=0,cash=0.))
        p['fees']+=fee; item['fees']+=fee
        cash=-side*qty*px*100.
        p['cash']+=cash;item['cash']+=cash
        key=(cid,leg)
        if new:
            assert not inventory[key], ('同一脚の未返済中の再建て',key)
            inventory[key].append([qty,px,side])
            held[side]+=qty; entries+=1;quantity+=qty
            p['entries']+=1;p['quantity']+=qty;item['entries']+=1;item['quantity']+=qty
            p.setdefault('side',side);p.setdefault('entry',i)
        else:
            left=qty
            while left:
                assert inventory[key]
                lot=inventory[key][0];assert lot[2]==-side
                used=min(left,lot[0]);gain=lot[2]*(px-lot[1])*used*100.
                p['gross']+=gain;item['gross']+=gain
                lot[0]-=used;left-=used
                if lot[0]==0:inventory[key].popleft()
            held[-side]-=qty
        p['exit']=i
        assert 0<=held[1]<=10 and 0<=held[-1]<=10
        largest=max(largest,*held.values())
    assert all(not x for x in inventory.values()) and held=={1:0,-1:0}
    for p in parent.values():
        equal(p['gross'],p['cash']);p['net']=p['gross']-p['fees']
        for leg in p['legs'].values():
            equal(leg['gross'],leg['cash']);leg['net']=leg['gross']-leg['fees']
    profits=sum(p['net'] for p in parent.values() if p['net']>0)
    losses=-sum(p['net'] for p in parent.values() if p['net']<0)
    return dict(profit=profits,loss=losses,net=profits-losses,gross=sum(p['gross'] for p in parent.values()),
                fees=sum(p['fees'] for p in parent.values()),parents=dict(parent),entries=entries,
                quantity=quantity,max_per_side=largest,normal_fill_checks=delayed,fixed_notifications=fixed)


def summary(rows):
    """
    機能: 銘柄内の勝敗頻度と平均的な勝ち負けを集計する。
    引数: rows(list[dict])は保存場会計。
    返り値: dictは比較尺度。
    """
    v=[r['net'] for r in rows]; wins=[x for x in v if x>0];losses=[-x for x in v if x<0]
    return dict(sessions=len(rows),black=len(wins),red=len(losses),flat=sum(x==0 for x in v),
                no_trade=sum(r['entries']==0 for r in rows),net=sum(v),median=statistics.median(v),
                mean_win=statistics.mean(wins) if wins else 0.,mean_loss=statistics.mean(losses) if losses else 0.,
                worst_loss=max(losses,default=0.),profit=sum(r['profit'] for r in rows),loss=sum(r['loss'] for r in rows),
                without_top3=sum(v)-sum(sorted(wins,reverse=True)[:3]),quantity=sum(r['quantity'] for r in rows))


def main():
    """
    機能: 金融再生せず保存注文・元通知・原行入力を全条件で独立照合する。
    引数: なし。
    返り値: None。監査JSONと短いMarkdownを保存する。
    """
    result=read(HERE/'結果.json');plan=read(HERE/'試行計画.json')
    rows={(r['session'],r['method']):r for r in result['rows']}
    caches={r['session']:r for r in result['cache']}
    totals=defaultdict(int);checked=[];paired=[];added=[];early=[];references=[]
    for item in plan['inputs']:
        scene=item['session'];cache=caches[scene]
        for spec in (item['input'],item['orders'],cache):
            assert digest(ROOT/spec['path'])==spec['sha256']
        packet=pickle.loads((ROOT/item['input']['path']).read_bytes())
        key=(scene,'NK225');ready=packet['inputs'][key];q=packet['quotes'][key]
        ts=ready['time_s'];bid=q['bid'];ask=q['ask']
        good=q['quote_valid'] & np.isfinite(bid) & np.isfinite(ask) & (bid>0) & (ask>bid)
        normal=np.flatnonzero(good)
        with np.load(ROOT/item['orders']['path'],allow_pickle=False) as old:
            core=old[item['prefix']+'core_orders'];extra=old[item['prefix']+'extra_orders']
            oldkeys={(int(o[0]),int(o[1]),int(o[2]),int(o[3]),float(o[5]),int(o[6]),int(o[7])) for o in np.concatenate((core,extra))}
        with np.load(ROOT/cache['path'],allow_pickle=False) as saved:
            methods=[m for (s,m) in rows if s==scene]
            for method in methods:
                orders=saved[method]
                a=ledger(orders,ts,bid,ask,normal,None if method.startswith('R') else oldkeys)
                r=rows[(scene,method)]
                for name in ('profit','loss','net','gross','fees','entries','quantity','max_per_side'):
                    equal(a[name],r[name]);totals['場会計項目']+=1
                saved_parents={int(p['id']):p for p in r['parents']}
                assert a['parents'].keys()==saved_parents.keys()
                for cid,p in a['parents'].items():
                    other=saved_parents[cid]
                    for name in ('gross','fees','net','side','entry','exit'):
                        equal(p[name],other[name]);totals['親会計項目']+=1
                    assert set(p['legs'])==set(map(int,other['legs']))
                    for leg,d in p['legs'].items():
                        for name in ('gross','fees','net','entries','quantity'):
                            equal(d[name],other['legs'][str(leg)][name]);totals['脚会計項目']+=1
                        if leg==1 and not method.startswith(('R','H')) and d['entries']:
                            legorders=orders[(orders[:,2]==cid)&(orders[:,8]==1)]
                            added.append(dict(session=scene,method=method,parent=cid,**d,
                                time=datetime.fromtimestamp(ts[int(legorders[0,0])],ZoneInfo('Asia/Tokyo')).isoformat(),
                                orders=legorders.tolist(),initial_net=p['legs'][0]['net']))
                totals['注文']+=len(orders);totals['次正常原行']+=a['normal_fill_checks'];totals['固定元通知']+=a['fixed_notifications']
                checked.append(dict(session=scene,method=method,net=a['net'],orders=len(orders)))
                if method.startswith('H_'):
                    segment=saved[method+'_early']
                    e=ledger(segment,ts,bid,ask,normal,None)
                    equal(a['net'],rows[(scene,'B05')]['net']+e['net'])
                    equal(a['fees'],rows[(scene,'B05')]['fees']+e['fees'])
                    if len(segment):
                        assert ts[int(segment[-1,0])] < ready['us_open']-850., ('米前返済が遅延',scene,method)
                    early.append(dict(session=scene,method=method,net=e['net'],profit=e['profit'],loss=e['loss'],entries=e['entries'],quantity=e['quantity']))
            for baseline,change in [('B02','P02a'),('B02','P02b'),('B02','C02a'),('B02','C02b'),('B03','C03')]:
                original=saved[baseline];altered=saved[change]
                assert np.array_equal(original,altered[altered[:,8]!=1])
                legs=[x for x in added if x['session']==scene and x['method']==change]
                delta=sum(x['net'] for x in legs)
                equal(delta,rows[(scene,change)]['net']-rows[(scene,baseline)]['net'])
                paired.append(dict(session=scene,baseline=baseline,change=change,delta=delta,
                    base_net=rows[(scene,baseline)]['net'],change_net=rows[(scene,change)]['net']))
        references.append(dict(session=scene,input=item['input'],source_orders=item['orders'],new_orders=cache))
        print(scene,'独立照合完了',flush=True)
    summaries={m:{'all':summary([r for (s,n),r in rows.items() if n==m]),
                  'day':summary([r for (s,n),r in rows.items() if n==m and s.endswith('_Day')]),
                  'night':summary([r for (s,n),r in rows.items() if n==m and s.endswith('_Night')])}
               for m in sorted({m for s,m in rows})}
    contrasts={}
    for base,method in [('B05','B02'),('B05','B03'),('B05','C02a'),('B05','C03'),('B05','CT02'),('B02','C02a'),('B03','C03')]:
        pairs=[(rows[(s,base)],r) for (s,m),r in rows.items() if m==method]
        contrasts[f'{base}→{method}']=dict(delta=sum(b['net']-a['net'] for a,b in pairs),
            win_to_loss=[a['session'] for a,b in pairs if a['net']>0 and b['net']<0],
            loss_to_win=[a['session'] for a,b in pairs if a['net']<0 and b['net']>0],
            improved=sum(b['net']>a['net'] for a,b in pairs),worsened=sum(b['net']<a['net'] for a,b in pairs))
    add_summary={}
    for m in sorted({a['method'] for a in added}):
        a=[x for x in added if x['method']==m];v=[x['net'] for x in a]
        add_summary[m]=dict(parents=len(a),positive=sum(x>0 for x in v),negative=sum(x<0 for x in v),
            net=sum(v),without_top3=sum(v)-sum(sorted([x for x in v if x>0],reverse=True)[:3]),
            worst=sorted(a,key=lambda x:x['net'])[:3])
    early_summary={m:summary([x for x in early if x['method']==m and x['session'].endswith('_Night')]) for m in sorted({x['method'] for x in early})}
    out=dict(passed=True,accounts=len(checked),checks=dict(totals),source_result_sha256=digest(HERE/'結果.json'),
        summaries=summaries,contrasts=contrasts,addition_contribution=add_summary,pre_us=early_summary,
        paired_addition=paired,checked=checked,references=references,financial_replays=0,api=0,
        note='固定影通知を使う数量層。実Go mini状態や実mini板の再現と同一ではない。保存会計の独立検算は新しい有効性標本に数えない。')
    (HERE/'audit_financial137.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 日経ミニ段階投入の独立会計監査','',f'保存{len(checked)}場会計・{totals["注文"]:,}注文を独立FIFOと現金差額で照合し、全て一致。金融再生0、API0。','',
           '| 条件 | 累計 | 黒字／赤字／無取引 | 平均赤字 | 最大赤字 | 上位3黒字を除く収支 |','|---|---:|---:|---:|---:|---:|']
    for method in ('B05','B02','B03','C02a','C02b','C03','CT02'):
        s=summaries[method]['all'];lines.append(f'| {method} | {s["net"]:+,.0f}円 | {s["black"]}／{s["red"]}／{s["no_trade"]} | {s["mean_loss"]:,.0f}円 | {s["worst_loss"]:,.0f}円 | {s["without_top3"]:+,.0f}円 |')
    lines += ['','少量化で1回の損失を減らす効果と、追撃による上積みは別。B02とC02a、B03とC03は初期脚・補完脚の全注文が完全一致し、差額は追加脚だけに一致した。','',
              '| 追撃方式 | 追加した親 | 追加分が負 | 追加分収支 | 上位3追加益を除く収支 |','|---|---:|---:|---:|---:|']
    for m in ('P02a','P02b','C02a','C02b','C03','CT02'):
        s=add_summary[m];lines.append(f'| {m} | {s["parents"]} | {s["negative"]} | {s["net"]:+,.0f}円 | {s["without_top3"]:+,.0f}円 |')
    lines += ['','米国前だけの追加寄与は全6方式で累計赤字。新造R系も全45場で取引したが、全候補が累計赤字。追加して活動を増やすこと自体は安定化を保証しなかった。','',
              '元通知は内容指紋・判断行・約定行・売買側・価格・理由で照合。追加901/902および新造注文は判断より後の最初の正常原行と一致。各脚・各親・場全体の費用と純収支、両方向上限10枚、全玉返済を確認した。','',
              'ここでの基準は既存通知を固定した数量層であり、Go本体を日経mini10枚へ変更した完全再現ではない。実mini気配・待ち順位・部分約定は未検証。']
    (HERE/'audit_financial137.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,accounts=len(checked),checks=dict(totals)),ensure_ascii=False))


if __name__=='__main__':
    main()
