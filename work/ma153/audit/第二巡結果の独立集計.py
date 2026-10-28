"""第二巡保存約定を独立に足し直す。売買規則を再実行しない。"""
from pathlib import Path
from collections import defaultdict
import json, math

BASE=Path(__file__).resolve().parents[1]


def check(actual,expected,label):
    """機能: 数値会計の一致を確認する。引数: actual/expected(float),label(str)。返り値: なし。"""
    assert abs(actual-expected)<1e-6,(label,actual,expected)


def main():
    """機能: 全保存約定からlot/親/配賦損益を再構成する。引数: なし。返り値: なし。"""
    report=json.loads((BASE/'round2/report153r2.json').read_text(encoding='utf-8'))
    rows={(m['symbol'],m['id'],r['session']):r for m in report['methods'] for r in m['rows']}
    rows.update({(r['symbol'],r['id'],r['session']):r for r in report['partial']})
    totals=defaultdict(lambda:defaultdict(float));counts=defaultdict(int)
    for path in sorted((BASE/'round2/results_go').glob('*.json')):
        saved=json.loads(path.read_text(encoding='utf-8'))
        for c in saved['cases']:
            key=(c['Symbol'],c['Config']['id'],c['Session']);row=rows[key]
            lots={};parents=defaultdict(float);direction_net=defaultdict(float);net=profit=loss=0.;holding=0;maximum=0;entryqty=0
            for e in c['Events']:
                counts['events']+=1;o=e['Order'];q=o['Quantity']
                assert e['FillIndex']>o['DecisionIndex'] and e['FillTime']>=o['DecisionTime']
                check(e['Price'],e['FillAsk'] if o['Side']>0 else e['FillBid'],key)
                if o['Action']=='new':
                    lid=len(lots)+1;lots[lid]={'side':o['Side'],'price':e['Price'],'initial':q,'remaining':q,'net':0.};holding+=q;entryqty+=q;check(e['Gross'],0,key)
                else:
                    subtotal=0.;amount=0
                    for d in e['Closed']:
                        l=lots[d['LotID']];assert l['side']==-o['Side'] and l['remaining']>=d['Quantity']
                        check(d['EntryPrice'],l['price'],key);check(d['ExitPrice'],e['Price'],key)
                        realized=l['side']*d['Quantity']*(e['Price']-l['price'])*c['PointValue'];check(realized,d['Gross'],key)
                        l['remaining']-=d['Quantity'];l['net']+=realized;subtotal+=realized;amount+=d['Quantity']
                        profit+=max(realized,0);loss+=max(-realized,0)
                    assert amount==q;holding-=q;check(subtotal,e['Gross'],key);direction_net[-o['Side']]+=e['Gross']
                assert 0<=holding<=10
                maximum=max(maximum,holding);net+=e['Gross'];parents[o['ParentID']]+=e['Gross']
            for l in c['Lots']:
                v=lots[l['ID']];assert v['remaining']==l['Quantity'] and v['initial']==l['Initial'];check(v['net'],l['Realized'],key)
            for par in c['Parents']+([c['open_parent']] if c.get('open_parent') else []):check(parents[par['ID']],par['Realized'],key)
            check(net,c['Gross'],key);check(net,row['net'],key);check(profit,row['profit'],key);check(loss,row['loss'],key);check(entryqty,row['entry_quantity'],key);assert maximum==row['max_qty'] and holding==row['remaining_qty']
            counts['partial' if c['Partial'] else 'complete']+=1;counts['lots']+=len(lots)
            if not c['Partial']:
                assert holding==0 and c['Pending'] is None
                total=totals[(c['Symbol'],c['Config']['id'])]
                total['net']+=net;total['profit']+=profit;total['loss']+=loss;total['entry_quantity']+=entryqty;total['sessions']+=1;total['long_net']+=direction_net[1];total['short_net']+=direction_net[-1]
    metrics=[]
    for m in report['methods']:
        key=(m['symbol'],m['id']);s=totals[key]
        for k in ('net','profit','loss','entry_quantity','sessions'):check(s[k],m['summary'][k],key)
        check(s['long_net']+s['short_net'],s['net'],key)
        metrics.append({'symbol':key[0],'id':key[1],**s,'net_per_entry_contract':s['net']/s['entry_quantity']})
    (BASE/'audit/第二巡結果の独立検算.json').write_text(json.dumps({'counts':counts,'methods':metrics,'scope':'保存結果の約定・FIFO配賦・lot・親・集計の独立再会計。売買の再生なし。'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(counts),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
