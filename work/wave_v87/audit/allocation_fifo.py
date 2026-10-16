"""複数建値と可変初回枚数を含む注文をFIFOで読み替え、料金・親組を独立検算する。"""

# 旧独立会計から初回枚数と保有上限の検査だけを可変数量へ一般化する。
# 元コードSHA256: d9ddd95ca2e421226f8e4abc80e537526fd0e8ad2ab9fd8e2d2b528de5b7efff

from collections import Counter, defaultdict, deque
from decimal import Decimal, ROUND_FLOOR
import gzip
import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=HERE.parents[2]
FEES={'TOPIX':Decimal('41.8'),'NK225':Decimal('11')}
VALUES={'TOPIX':1000,'NK225':10}
SIZES={'TOPIX':5,'NK225':10}
CAPS={'TOPIX':10,'NK225':20}
ADDITIVE=('gross','fees','net','profit','loss','wins','losses','flats','winning_lots','losing_lots','flat_lots',
    'campaigns','campaign_wins','campaign_losses','campaign_profit','campaign_loss','sum_r')


def read(path):
    """機能: 保存済み通常又は圧縮JSONを読み込む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    raw=path.read_bytes();return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def same(actual,expected):
    """機能: 構造を一致させ、小数計算順序による丸めだけを許容して照合する。

    引数: actual/expected(object)。返り値: なし(None)。不一致は例外。
    """
    if isinstance(actual,dict):
        assert actual.keys()==expected.keys(),(actual.keys(),expected.keys())
        for key in actual:same(actual[key],expected[key])
    elif isinstance(actual,list):
        assert len(actual)==len(expected),(len(actual),len(expected))
        for a,b in zip(actual,expected):same(a,b)
    elif isinstance(actual,float):assert math.isclose(actual,expected,rel_tol=1e-10,abs_tol=1e-5),(actual,expected)
    else:assert actual==expected,(actual,expected)


def ratios(row):
    """機能: 決済回数・枚数・組の利益損失比を同じ銘柄内で独立計算する。

    引数: row(dict)。返り値: なし(None)。辞書へ率を追記する。
    """
    row['win_rate']=row['wins']/max(1,row['wins']+row['losses']+row['flats'])
    for name,wins,losses,gain,loss in (('payoff','wins','losses','profit','loss'),
        ('lot_payoff','winning_lots','losing_lots','profit','loss'),
        ('campaign_payoff','campaign_wins','campaign_losses','campaign_profit','campaign_loss')):
        row[name]=(row[gain]/row[wins])/(row[loss]/row[losses]) if row[wins] and row[losses] else None


def measure(ready,ledger,model):
    """機能: 注文をFIFO建玉台帳へ変換し、部分返済料金と全原板行時価を別計算する。

    引数: ready/ledger(dict)、model(str)。返り値: 集計・決済詳細・旧形式生決済(tuple)。
    """
    symbol=ready['symbol'];scale=VALUES[symbol];price=ready['last'];size=ledger['config']['initial_qty']
    assert 1<=size<=CAPS[symbol] and ledger['config']['audit_cap']==CAPS[symbol]
    queues=defaultdict(deque);details=[];raw_trades=[];charges=[];campaigns=defaultdict(list)
    campaign_max=defaultdict(int);campaign_start={};campaign_dir={};events=[]
    long_qty=short_qty=max_long=max_short=0;realized=cost=fees=0.;leg=0;last_row=-1
    for order in ledger['orders']:
        i,source,cid,side,qty=int(order[0]),int(order[1]),int(order[2]),int(order[3]),int(order[4])
        p=float(order[5]);reason=int(order[6]);is_entry=int(order[7])
        assert 0<=source<i<len(price) and i>=last_row and side in (-1,1) and qty>0
        assert math.isfinite(p) and p>0 and is_entry in (0,1)
        assert ready['time_s'][i]<ready['limit']+600
        if model=='observed':assert p==price[i],(ledger['session'],symbol,i,p,price[i])
        last_row=i
        fee=int((Decimal(qty)*FEES[symbol]).to_integral_value(rounding=ROUND_FLOOR));charges.append(fee);fees+=fee
        if is_entry:
            queues[cid,side].append(dict(row=i,qty=qty,initial_qty=qty,price=p,fee=fee,leg=leg))
            campaign_start.setdefault(cid,i);campaign_dir.setdefault(cid,side);leg+=1;cost+=side*qty*p
            if side==1:long_qty+=qty
            else:short_qty+=qty
        else:
            remaining=qty;position_side=-side;pending=queues[cid,position_side]
            while remaining:
                assert pending,(ledger['session'],symbol,'無建玉返済',order)
                lot=pending[0];q=min(remaining,lot['qty']);e=lot['row']
                gross=position_side*q*(p-lot['price'])*scale
                allocated=q*(lot['fee']/lot['initial_qty']+fee/qty);net=gross-allocated
                detail=dict(組=cid,方向=position_side,枚数=q,新規行=e,返済行=i,新規原本行=int(ready['seq'][e]),返済原本行=int(ready['seq'][i]),
                    新規時刻=float(ready['time_s'][e]),返済時刻=float(ready['time_s'][i]),建値=lot['price'],返済値=p,理由=reason,
                    利益損失前=gross,手数料=allocated,収支=net)
                details.append(detail);campaigns[cid].append(detail)
                raw_trades.append([float(cid),float(lot['leg']),float(position_side),float(q),lot['price'],p,float(e),float(i),0.,float(reason),gross/scale])
                realized+=gross;cost-=position_side*q*lot['price'];lot['qty']-=q;remaining-=q
                if lot['qty']==0:pending.popleft()
            if position_side==1:long_qty-=qty
            else:short_qty-=qty
        assert long_qty>=0 and short_qty>=0
        assert long_qty<=CAPS[symbol] and short_qty<=CAPS[symbol]
        campaign_max[cid]=max(campaign_max[cid],long_qty+short_qty)
        max_long=max(max_long,long_qty);max_short=max(max_short,short_qty)
        event=(i,long_qty-short_qty,cost,realized,fees)
        if events and events[-1][0]==i:events[-1]=event
        else:events.append(event)
    assert long_qty==0 and short_qty==0 and all(not q for q in queues.values())
    same(ledger['fees'],charges);same(ledger['trades'],details)
    # ----------------------------------------
    # 注文変更区間ごとに原板last時価を計算する。親のcurveとaccountは参照しない。
    peak=drawdown=0.;terminal=0.
    for n,(i,net_qty,signed_cost,cash,total_fees) in enumerate(events):
        end=events[n+1][0] if n+1<len(events) else len(price)
        equity=price[i:end]*(net_qty*scale)-signed_cost*scale+cash-total_fees
        highs=np.maximum(np.maximum.accumulate(equity),peak)
        drawdown=max(drawdown,float(np.max(highs-equity,initial=0.)))
        peak=float(highs[-1]);terminal=float(equity[-1])
    assert math.isclose(terminal,math.fsum(x['収支'] for x in details),rel_tol=1e-10,abs_tol=1e-5)
    same(sorted(campaigns),[int(c[0]) for c in ledger['cycles']])
    grouped=[];risks=[]
    for c in ledger['cycles']:
        cid=int(c[0]);parts=campaigns[cid]
        gross=math.fsum(d['利益損失前'] for d in parts)
        assert int(c[1])==campaign_start[cid] and int(c[2])==max(d['返済行'] for d in parts)
        assert int(c[6])==campaign_max[cid] and int(c[7])==campaign_max[cid]
        assert int(c[8])==campaign_dir[cid] and int(c[9])==parts[-1]['理由']
        assert math.isclose(c[3]*scale,gross,rel_tol=1e-10,abs_tol=1e-5)
        assert c[4]>0 and math.isclose(c[4],size*c[5],rel_tol=1e-10,abs_tol=1e-8)
        grouped.append(math.fsum(x['収支'] for x in parts));risks.append(c[4]*scale)
    winner=[d for d in details if d['収支']>0];loser=[d for d in details if d['収支']<0];flat=[d for d in details if d['収支']==0]
    row=dict(session=ready['session'],symbol=symbol,gross=math.fsum(d['利益損失前'] for d in details),fees=sum(charges),net=math.fsum(d['収支'] for d in details),
        profit=math.fsum(d['収支'] for d in winner),loss=-math.fsum(d['収支'] for d in loser),wins=len(winner),losses=len(loser),flats=len(flat),
        winning_lots=sum(d['枚数'] for d in winner),losing_lots=sum(d['枚数'] for d in loser),flat_lots=sum(d['枚数'] for d in flat),
        campaigns=len(grouped),campaign_wins=sum(x>0 for x in grouped),campaign_losses=sum(x<0 for x in grouped),
        campaign_profit=math.fsum(x for x in grouped if x>0),campaign_loss=-math.fsum(x for x in grouped if x<0),
        sum_r=math.fsum(x/r for x,r in zip(grouped,risks)),max_drawdown=drawdown,max_long=max_long,max_short=max_short,
        reason_counts={str(r):sum(d['理由']==r for d in details) for r in (1,2,7,8,9,30,32)})
    assert math.isclose(row['net'],row['gross']-row['fees'],rel_tol=1e-10,abs_tol=1e-5)
    assert math.isclose(math.fsum(d['手数料'] for d in details),row['fees'],rel_tol=1e-10,abs_tol=1e-5)
    ratios(row);return row,details,raw_trades


def aggregate(rows,symbol,names):
    """機能: 一銘柄のセッション会計を期間ごとに独立合算する。

    引数: rows(list[dict])、symbol(str)、names(list[str])。返り値: 期間会計(dict)。
    """
    chosen=[r for r in rows if r['symbol']==symbol and r['session'] in names]
    result={name:math.fsum(r[name] for r in chosen) if name in ('gross','net','profit','loss','campaign_profit','campaign_loss','sum_r') else sum(r[name] for r in chosen) for name in ADDITIVE}
    result.update(positive_sessions=sum(r['net']>0 for r in chosen),negative_sessions=sum(r['net']<0 for r in chosen),
        active_sessions=sum(r['campaigns']>0 for r in chosen),sessions=len(chosen),max_session_drawdown=max((r['max_drawdown'] for r in chosen),default=0))
    ratios(result);result['mean_r']=result['sum_r']/max(1,result['campaigns']);return result

