"""E01と改修十六条件の注文をFIFOで読み替え、手数料・全期間会計を独立検算する。"""

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
    symbol=ready['symbol'];scale=VALUES[symbol];price=ready['last'];size=SIZES[symbol]
    assert ledger['config']['initial_qty']==size and ledger['config']['audit_cap']==CAPS[symbol]
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
        assert long_qty>=0 and short_qty>=0 and long_qty<=size and short_qty<=size
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


def main():
    """機能: 全32出力のFIFO会計を検算し、旧指定E01の23場台帳と全期間を照合する。

    引数: なし。返り値: なし(None)。全出力が揃ってから実行し、監査先だけへ保存する。
    """
    fixed=read(WORK/'事前固定.json');ids=[c['id'] for c in fixed['条件']]
    assert len(ids)==16 and len(fixed['全セッション'])==28
    inputs={}
    for folder in (WORK/'prepared').iterdir():
        path=folder/'new_inputs.pkl'
        if not path.exists():continue
        more=pickle.loads(path.read_bytes());assert not set(more)&set(inputs);inputs.update(more)
    assert len(inputs)==56
    old=[];folders=[ROOT/'work/wave_v49/early']+[ROOT/'work/wave_v50'/n for n in read(ROOT/'work/wave_v50/追加結果一覧.json')]
    for folder in folders:old.extend(read(folder/'ledgers/E01.json.gz'))
    old={ (l['session'],l['symbol']):l for l in old};assert len(old)==46
    paths=[WORK/model/(identifier+'.json.gz') for model in ('specified','observed') for identifier in ids]
    assert all(p.exists() for p in paths),'全32結果の完了待ち'
    account_count=order_count=trade_count=campaign_count=old_count=0;reports=[]
    for path in paths:
        result=read(path);assert result['variant']['id']==path.stem.removesuffix('.json')
        model=result['model'];rows=[]
        assert len(result['rows'])==len(result['ledgers'])==56
        for actual,ledger in zip(result['rows'],result['ledgers']):
            key=(ledger['session'],ledger['symbol']);ready=inputs[key]
            row,details,raw=measure(ready,ledger,model);same(actual,row);rows.append(row)
            if model=='specified' and result['variant']['id']=='E01' and key in old:
                same(ledger['orders'],old[key]['orders']);same(ledger['cycles'],old[key]['cycles']);same(raw,old[key]['trades']);old_count+=1
            account_count+=1;order_count+=len(ledger['orders']);trade_count+=len(details);campaign_count+=len(ledger['cycles'])
        periods={label:{s:aggregate(rows,s,names) for s in ('TOPIX','NK225')} for label,names in (
            ('前16',fixed['前16']),('後12',fixed['後12']),('全28',fixed['全セッション']),('直近3',fixed['全セッション'][-3:]))}
        same(result['periods'],periods)
        reports.append(dict(モデル=model,条件=result['variant']['id'],口座数=56,FIFOと料金と全期間一致=True,
            SHA256=hashlib.sha256(path.read_bytes()).hexdigest()))
        print(model,result['variant']['id'],'FIFO会計・全原板時価・期間合算一致',flush=True)
    assert old_count==46
    report=dict(結論='指定条件と観測価格の全32条件・56口座会計を注文FIFOで独立再構成し、決済詳細・料金・残玉ゼロ・上限・組・全期間・料金後最大下落が一致。旧指定E01の全23場の生台帳も一致。',
        条件数=len(paths),口座照合数=account_count,注文照合数=order_count,決済照合数=trade_count,組照合数=campaign_count,
        旧指定E01台帳一致口座数=old_count,条件別=reports,親会計関数使用=False,API追加取得数=0,原本書込数=0,
        注意=['指定条件価格の理想再生と発動行の最終約定価格再生を別に集計。いずれもラージの約定値がmicro/mini実約定を保証するものではない。',
        'FIFO会計は保存注文の妥当性と会計を検査する。入口の予測力を証明したり、保存後の足修正や通信時間を復元したりするものではない。'],
        コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'E01と改修全32条件の独立FIFO会計.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('結論','条件数','口座照合数','注文照合数','決済照合数','組照合数','旧指定E01台帳一致口座数')},ensure_ascii=False))


if __name__=='__main__':main()
