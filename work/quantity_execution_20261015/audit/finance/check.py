"""結果一読と主候補66台帳だけで金額・UID・予約・原行因果を独立検算する。"""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_FLOOR
from fractions import Fraction
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import pickle
from statistics import median
import traceback

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parents[1]
ROOT=HERE.parents[3]
RESULT=WORK/'finance/結果.json'
PLAN=HERE/'結果一読と主候補66台帳の独立実会計監査計画.json'
ART=HERE/'監査器の半分予約と全行現金及びRLEの純人工.json'
OUTPUT=HERE/'全792小会計と主候補66実台帳の独立実会計監査.json'
MAIN='QEXEC_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1'
CAP={'TOPIX':10,'NK225':20}
MULT={'TOPIX':1000,'NK225':10}
TICK={'TOPIX':Fraction(1,2),'NK225':Fraction(10)}
SOURCE_NAMES=('catalog.py','engine.py','artificial.py','metrics/metrics.py','metrics/artificial_metrics.py')
FORMAL_SOURCE_NAMES=('catalog.py','engine.py','artificial.py','input_contract.py','plan.py','finance.py','artificial_root.py',
    'metrics/metrics.py','metrics/artificial_metrics.py')


def sha(path: Path) -> str:
    """
    機能: 私有監査源又は小証跡のSHAを求める。
    引数: path(Path) はsource又は準備資料。
    返り値: str はSHA256。結果・台帳の事前二重hashに使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources() -> dict:
    """
    機能: 監査済み不変五源と今回の検査源を束縛する。
    引数: なし。
    返り値: dict は開始終端指紋。root金融源は完成結果の署名と実ファイルを実行時照合する。
    """
    return dict(監査対象不変源={n:sha(WORK/n) for n in SOURCE_NAMES},監査源=sha(Path(__file__)))


def formal_sources() -> dict:
    """
    機能: 根が正式固定した九源の現指紋を入力読取前と終了時に求める。
    引数: なし。
    返り値: dict[str,str] はルート相対pathとSHA256。実結果又は実入力を開かない。
    """
    return {(WORK/name).relative_to(ROOT).as_posix():sha(WORK/name) for name in FORMAL_SOURCE_NAMES}


def write(path: Path,value: dict) -> None:
    """
    機能: 既存成功/Falseを上書きせず有限JSONを保存する。
    引数: path(Path)、value(dict) は私有新規証跡。
    返り値: None。金融計算・入力復元を行わない。
    """
    assert path.parent==HERE and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def f(value: object) -> Fraction:
    """
    機能: 金額を独立した厳密分数へ変換する。
    引数: value(object) は有限数。真偽・不明は拒否する。
    返り値: Fraction は十進文字列表現の値。
    """
    assert not isinstance(value,(bool,np.bool_)) and isinstance(value,(int,float,np.integer,np.floating,Fraction,Decimal))
    assert math.isfinite(value)
    return Fraction(str(value))


def equal(a: object,b: object) -> None:
    """
    機能: 独立期待と保存の金額又はbool/Noneを比較する。
    引数: a/b(object) は比較値。
    返り値: None。浮動曲線だけ1e−5円以内を許し、未知を零へ補完しない。
    """
    if a is None or b is None or isinstance(a,(bool,np.bool_)) or isinstance(b,(bool,np.bool_)):
        assert a==b and (a is None)==(b is None)
    else:
        assert math.isclose(float(a),float(b),rel_tol=1e-11,abs_tol=1e-5),(a,b)


def fee(q: int,symbol: str) -> int:
    """
    機能: 各実注文料をDecimalで独立にfloorする。
    引数: q(int)、symbol(str) は非負量と商品。
    返り値: int は円料。複数返済をまとめ直さない。
    """
    assert isinstance(q,int) and q>=0
    return int((Decimal(q)*Decimal('41.8' if symbol=='TOPIX' else '11')).to_integral_value(rounding=ROUND_FLOOR))


def amounts(parents: list[dict]) -> dict:
    """
    機能: 完結親netの相殺前利益・損失と主金額比率を独立集計する。
    引数: parents(list[dict]) は対象完結親。
    返り値: dict は主会計。脚の符号又は勝ち場netで置換しない。
    """
    values=[f(p['net_yen']) for p in parents];win=[v for v in values if v>0];loss=[-v for v in values if v<0]
    p=sum(win,Fraction());l=sum(loss,Fraction())
    return dict(利益=float(p),損失=float(l),収支=float(p-l),親数=len(values),勝ち親=len(win),負け親=len(loss),零親=len(values)-len(win)-len(loss),
        利益割合=float(p/(p+l)) if p+l else None,PF=float(p/l) if l else None,
        平均利益=float(p/len(win)) if win else None,平均損失=float(l/len(loss)) if loss else None)


def quantities(legs: list[dict]) -> dict:
    """
    機能: 実返済脚netの符号で実決済量を分ける。
    引数: legs(list[dict]) は対象実脚。
    返り値: dict は勝ち/負け/零枚数。親net符号と混同しない。
    """
    return {name:sum(int(l['q']) for l in legs if (f(l['net_yen'])>0 if sign==1 else f(l['net_yen'])<0 if sign==-1 else f(l['net_yen'])==0))
            for name,sign in (('勝ち枚数',1),('負け枚数',-1),('零枚数',0))}


def period(rows: list[dict],parents: list[dict],legs: list[dict],symbol: str) -> dict:
    """
    機能: 期間の全場分母・場net補填・65/20/平均10万を独立Fractionで計算する。
    引数: rows/parents/legs(list[dict])、symbol(str) は同期間同商品。
    返り値: dict は公開指標の独立期待。NK金額床はNone。
    """
    n=len(rows);assert n>0
    net=[f(r['収支']) for r in rows];wins=[v for v in net if v>0];loss=[-v for v in net if v<0]
    aggregate=amounts(parents);p=f(aggregate['利益']);l=f(aggregate['損失']);total=sum(net,Fraction())
    active=sum(r['親数']>0 for r in rows);worst=max([Fraction()]+loss);avg=sum(wins,Fraction())/len(wins) if wins else None
    s65=bool(p+l and p/(p+l)>=Fraction(13,20));red=Fraction(len(loss),n)<=Fraction(1,5);coverage=avg is not None and worst<=avg
    floor=100000 if symbol=='TOPIX' else None;classic=s65 and red and coverage
    return dict(aggregate=aggregate,session_count=n,active_sessions=active,positive_sessions=len(wins),losing_sessions=len(loss),
        no_trade_sessions=n-active,flat_active_sessions=active-len(wins)-len(loss),red_full_rate=len(loss)/n,red_active_rate=len(loss)/active if active else None,
        mean_session_net_yen=float(total/n),median_session_net_yen=float(median(net)),mean_positive_session_net_yen=float(avg) if avg is not None else None,
        worst_negative_session_abs_yen=float(worst),target65=s65,target_red20=red,target_worst_mean=coverage,all_stability_targets=classic,
        target_floor_yen=floor,target_mean_success=total/n>=floor if floor is not None else None,
        all_main_targets=classic and (floor is None or total/n>=floor),actual_quantity_cap=CAP[symbol],
        net_capacity_points=float(total/(CAP[symbol]*MULT[symbol])),**quantities(legs))


def dictionary(actual: dict,expected: dict) -> int:
    """
    機能: 指標の必要全項目を再帰的に照合する。
    引数: actual/expected(dict) は保存値と独立期待。
    返り値: int は比較数。保存側の追加説明欄は検算値へ使わない。
    """
    count=0
    for key,value in expected.items():
        assert key in actual,key
        if isinstance(value,dict):count+=dictionary(actual[key],value)
        elif isinstance(value,(str,list)):
            assert actual[key]==value;count+=1
        else:equal(actual[key],value);count+=1
    return count


def account(row: dict,parents: list[dict],legs: list[dict],diagnostic: dict) -> int:
    """
    機能: 結果内の全口座で親/脚UID・量・料金配賦・BBO分解を検算する。
    引数: row/diagnostic(dict)、parents/legs(list[dict]) は同場同case。
    返り値: int は比較数。他726口座の実ordersを直接読んだとは主張しない。
    """
    symbol=row['symbol'];checks=0;keys={(int(p['parent']),int(p['uid'])) for p in parents}
    assert len(keys)==len(parents)==len({int(p['parent']) for p in parents})==len({int(p['uid']) for p in parents})
    assert {(int(l['parent']),int(l['uid'])) for l in legs}==keys;checks+=2
    breakdown={int(p['parent']):p for p in diagnostic['parent_breakdown']}
    assert set(breakdown)=={k[0] for k in keys};checks+=1
    for p in parents:
        q=int(p['quantity']);assert q==CAP[symbol];checks+=1
        ll=[l for l in legs if int(l['parent'])==int(p['parent']) and int(l['uid'])==int(p['uid'])]
        assert sum(int(l['q']) for l in ll)==q;checks+=1
        gross=Fraction();cost=fee(q,symbol);entry_alloc=Fraction()
        detail=breakdown[int(p['parent'])];assert int(detail['uid'])==int(p['uid']) and len(detail['legs'])==len(ll);checks+=2
        mid_total=Fraction();cross_total=Fraction()
        for leg,point in zip(ll,detail['legs']):
            amount=int(leg['q']);side=int(leg['side']);assert side==int(p['side']) and side in (-1,1)
            assert int(leg['entry_row'])==int(p['entry_row'])<int(leg['exit_row']);checks+=2
            exact_gross=side*(f(leg['exit_price'])-f(leg['entry_price']))*amount*MULT[symbol]
            allocation=Fraction(fee(q,symbol)*amount,q);exit_cost=fee(amount,symbol)
            equal(leg['gross_yen'],exact_gross);equal(leg['entry_fee_allocated'],allocation);equal(leg['exit_fee'],exit_cost)
            equal(leg['net_yen'],exact_gross-allocation-exit_cost);checks+=4
            assert point['q']==amount and point['side']==side and point['entry_row']==leg['entry_row'] and point['exit_row']==leg['exit_row'];checks+=4
            e,x=point['新規'],point['返済']
            for z in (e,x):assert 0<f(z['bid'])<f(z['ask']) and f(z['bid_qty'])>0 and f(z['ask_qty'])>0;checks+=1
            equal(leg['entry_price'],e['ask'] if side>0 else e['bid']);equal(leg['exit_price'],x['bid'] if side>0 else x['ask']);checks+=2
            assert int(e['raw_seq'])<int(x['raw_seq']) and f(e['price_time_s'])<=f(x['price_time_s']);checks+=2
            mid=side*((f(x['bid'])+f(x['ask']))-(f(e['bid'])+f(e['ask'])))/2*amount*MULT[symbol]
            cross=((f(e['ask'])-f(e['bid']))+(f(x['ask'])-f(x['bid'])))/2*amount*MULT[symbol]
            equal(exact_gross,mid-cross);checks+=1
            mid_total+=mid;cross_total+=cross;gross+=exact_gross;cost+=exit_cost;entry_alloc+=allocation
        equal(entry_alloc,fee(q,symbol));equal(p['gross_yen'],gross);equal(p['fee_yen'],cost);equal(p['net_yen'],gross-cost);checks+=4
        assert int(p['exit_row'])==max(int(l['exit_row']) for l in ll);checks+=1
        checks+=dictionary(detail,{'中値差粗損益':float(mid_total),'気配差負担':float(cross_total),'手数料':cost,'収支':float(gross-cost)})
    expected=dict(**amounts(parents),**quantities(legs),粗損益=float(sum((f(p['gross_yen']) for p in parents),Fraction())),
        費用=sum(fee(CAP[symbol],symbol) for p in parents)+sum(fee(int(l['q']),symbol) for l in legs),
        新規枚数=sum(int(p['quantity']) for p in parents),全会計合格=True)
    checks+=dictionary(row,expected)
    equal(diagnostic['収支'],row['収支']);equal(diagnostic['手数料'],row['費用'])
    equal(f(diagnostic['中値差粗損益'])-f(diagnostic['気配差負担'])-f(diagnostic['手数料']),row['収支']);checks+=3
    return checks


def rle(packed: dict,ncols: int) -> tuple[np.ndarray,np.ndarray,int]:
    """
    機能: 圧縮曲線の行範囲・形状・隣接同値の保存契約を検査する。
    引数: packed(dict)、ncols(int) はcurve_rleと項目数。
    返り値: tuple は区間開始・値・全長。巨大な全曲線へ再展開しない。
    """
    starts=np.asarray(packed['starts']);values=np.asarray(packed['values']);shape=tuple(packed['shape'])
    assert len(shape)==2 and shape[0]>0 and shape[1]==ncols
    assert starts.ndim==1 and np.issubdtype(starts.dtype,np.integer) and len(starts)>0 and starts[0]==0
    assert values.shape==(len(starts),ncols) and np.all(np.diff(starts)>0) and starts[-1]<shape[0]
    same=(values[1:]==values[:-1])|(np.isnan(values[1:])&np.isnan(values[:-1]))
    assert not np.any(same.all(axis=1))
    return starts,values,shape[0]


def ledger(saved: dict,row: dict,parents: list[dict],legs: list[dict],diagnostic: dict) -> tuple[int,int]:
    """
    機能: 主候補実注文からcash/UID/予約を再構成し、全RLE区間と閾値を照合する。
    引数: saved/row/diagnostic(dict)、parents/legs(list[dict]) は同口座保存物。
    返り値: tuple[int,int] は比較数と全原行数。raw入力の読取又は再生を行わない。
    """
    assert saved['completed'] is True and saved['finish'] is True and saved['config']['id']==MAIN
    symbol=row['symbol'];checks=0
    for name,expected in (('parent',parents),('actual_legs',legs)):
        stripped=[{k:v for k,v in p.items() if k not in ('session','symbol','case')} for p in expected]
        assert saved[name]==stripped;checks+=1
    for key in ('利益','損失','収支','親数','費用','新規枚数','勝ち枚数','負け枚数','零枚数'):equal(saved['summary'][key],row[key]);checks+=1
    of=saved['order_fields'];orders=np.asarray(saved['orders']);assert orders.ndim==2 and orders.shape[1]==len(of)
    o={k:of.index(k) for k in of};cf=saved['curve_fields'];c={k:cf.index(k) for k in cf}
    starts,values,n=rle(saved['curve_rle'],len(cf));checks+=1
    def point(index: int) -> np.ndarray:
        """
        機能: 保存RLEから指定行の全項目を参照する。
        引数: index(int) は全原行範囲内。
        返り値: ndarray は当時の保存曲線。未来値へ埋めない。
        """
        assert 0<=index<n
        return values[np.searchsorted(starts,index,side='right')-1]
    next_true=np.full(len(starts)+1,-1,dtype=np.int64)
    for part in range(len(starts)-1,-1,-1):
        next_true[part]=part if values[part,c['execution_normal']]==1 else next_true[part+1]
    def next_normal(source: int) -> int | None:
        """
        機能: 判断行より後の最初executionnormalをRLEだけから探す。
        引数: source(int) は判断行。
        返り値: int|None は次正常原row又は未観測。
        """
        if source+1>=n:return None
        part=np.searchsorted(starts,source+1,side='right')-1
        if values[part,c['execution_normal']]==1:return source+1
        following=int(next_true[part+1])
        return int(starts[following]) if following>=0 else None
    assert np.all(np.isfinite(orders)) and (not len(orders) or np.all(np.diff(orders[:,o['row']])>=0));checks+=1
    book={};cash=Fraction();paid=0;parent_base={};entry_rows={};control=saved['control_events'];ct={k:saved['control_fields'].index(k) for k in saved['control_fields']}
    # ----------------------------------------
    # 当行注文と予約の索引を一度作り、曲線の各区間から全履歴を再走査しない。
    assert not len(orders) or np.all(np.isin(orders[:,o['row']],starts));checks+=1
    orders_by_row=defaultdict(list);controls_by_row=defaultdict(list)
    for order in orders:orders_by_row[int(order[o['row']])].append(order)
    for event in control:
        if int(event[ct['added_reserved_quantity']]):
            event_row=int(event[ct['row']]);part=int(np.searchsorted(starts,event_row))
            assert part<len(starts) and starts[part]==event_row;checks+=1
        controls_by_row[int(event[ct['row']])].append(event)
    reserves=Counter();reserve_total=0;active_uid=None;max_tick={};min_tick={};max_local={};min_local={}
    for begin,value in zip(starts,values):
        begin=int(begin)
        for event in controls_by_row.get(begin,()):
            amount=int(event[ct['added_reserved_quantity']]);assert amount>=0
            if amount:reserves[begin,int(event[ct['parent']]),int(event[ct['reason']])]+=amount;reserve_total+=amount
        for order in orders_by_row.get(begin,()):
            at,source,cid,uid,target,side,q,new,reason=map(int,(order[o[k]] for k in ('row','source_row','parent','uid','target_uid','side','q','new','reason')))
            price=f(order[o['price']]);cost=fee(q,symbol)
            assert at>source and point(at)[c['execution_normal']]==1 and order[o['fee']]==cost;checks+=3
            assert int(order[o['raw_seq']])>int(order[o['source_raw_seq']]);checks+=1
            if new:
                assert at==source+1 and order[o['raw_seq']]==order[o['source_raw_seq']]+1 and uid>=0 and target==-1;checks+=4
                assert active_uid is None and uid not in book and q==CAP[symbol];checks+=3
                parent_base[cid]=cash;entry_rows[cid]=at
                book[uid]=dict(parent=cid,q=q,side=side,price=price)
                active_uid=uid
                max_tick[cid]=-math.inf;min_tick[cid]=math.inf;max_local[cid]=-math.inf;min_local[cid]=math.inf
            else:
                b=book[target];assert target==active_uid and uid==-1 and b['parent']==cid and side==-b['side'] and 0<q<=b['q'];checks+=5
                assert next_normal(source)==at;checks+=1
                key=source,cid,reason;assert reserves[key]>=q;reserves[key]-=q;reserve_total-=q;checks+=1
                ticks=b['side']*(price-b['price'])/TICK[symbol];max_tick[cid]=max(max_tick[cid],float(ticks));min_tick[cid]=min(min_tick[cid],float(ticks))
                b['q']-=q
            cash-=side*q*price*MULT[symbol]+cost;paid+=cost
            if not new and book[target]['q']==0:
                local=float(cash-parent_base[cid]);max_local[cid]=max(max_local[cid],local);min_local[cid]=min(min_local[cid],local)
                active_uid=None
        live=book[active_uid] if active_uid is not None else None
        q=live['q'] if live is not None else 0
        equal(value[c['cash_yen']],cash);equal(value[c['paid_fee_yen']],paid);equal(value[c['held_quantity']],q);checks+=3
        equal(value[c['reserved_quantity']],reserve_total);equal(value[c['reserved_exit_fee_yen']],fee(q,symbol));checks+=2
        assert 0<=value[c['reserved_quantity']]<=q;checks+=1
        known=value[c['price_known']]==1
        assert value[c['execution_normal']] in (0,1) and (value[c['execution_normal']]==0 or known);checks+=1
        if live is None:equal(value[c['liquidation_net_yen']],cash);checks+=1
        elif not known:
            assert math.isnan(value[c['liquidation_net_yen']]) and math.isnan(value[c['gross_ticks']]);checks+=2
        else:
            b=live;cid=b['parent'];ticks=f(value[c['gross_ticks']]);quote=b['price']+b['side']*ticks*TICK[symbol]
            liq=cash+b['side']*q*quote*MULT[symbol]-fee(q,symbol);local=liq-parent_base[cid]
            equal(value[c['liquidation_net_yen']],liq);equal(value[c['parent_local_net_yen']],local);checks+=2
            max_tick[cid]=max(max_tick[cid],float(ticks));min_tick[cid]=min(min_tick[cid],float(ticks))
            max_local[cid]=max(max_local[cid],float(local));min_local[cid]=min(min_local[cid],float(local))
            equal(value[c['peak_gross_ticks']],max_tick[cid]);checks+=1
    assert active_uid is None and not any(b['q'] for b in book.values()) and reserve_total==0 and not any(reserves.values());checks+=4
    equal(cash,row['収支']);equal(paid,row['費用']);equal(saved['final_state']['cash_yen'],cash);equal(saved['final_state']['paid_fee_yen'],paid);checks+=4
    assert saved['final_state']['force_observed']==1;checks+=1
    for p in parents:
        cid=int(p['parent'])
        for name,expected in (('peak_gross_ticks',max_tick[cid]),('worst_gross_ticks',min_tick[cid]),
            ('peak_liquidation_net_yen',max_local[cid]),('worst_liquidation_net_yen',min_local[cid])):
            equal(p[name],expected);checks+=1
    # ----------------------------------------
    # 場線は全量初回mid起点で不変。元midの原BBOは未再読なので比例と実判断だけを検査する。
    ll=values[:,c['session_loss_line_yen']];gg=values[:,c['session_profit_line_yen']];finite=np.isfinite(ll)
    if np.any(finite):
        assert np.all(ll[finite]==ll[finite][0]) and np.all(gg[finite]==gg[finite][0]);checks+=2
        equal(gg[finite][0],f(ll[finite][0])*3);checks+=1
    block_row=None
    for event in control:
        row_i=int(event[ct['row']]);reason=int(event[ct['reason']]);v=point(row_i)
        if reason in (161,162):
            assert v[c['price_known']]==1;checks+=1
            liq=f(v[c['liquidation_net_yen']]);limit=f(v[c['session_loss_line_yen']] if reason==161 else v[c['session_profit_line_yen']])
            assert liq<=-limit if reason==161 else liq>=limit;checks+=1
            block_row=row_i if block_row is None else min(block_row,row_i)
    pubs=np.asarray(saved['publication_events']);pf={k:saved['publication_fields'].index(k) for k in saved['publication_fields']}
    execs=np.asarray(saved['execution_events']);ef={k:saved['execution_fields'].index(k) for k in saved['execution_fields']}
    terminals_by_parent=defaultdict(list)
    for event in execs:
        if int(event[ef['kind']]) in (1,3):terminals_by_parent[int(event[ef['parent']])].append(event)
    for event in pubs:
        row_i=int(event[pf['row']]);accepted=bool(event[pf['accepted']]);cid=int(event[pf['parent']])
        if block_row is not None and row_i>=block_row:assert not accepted;checks+=1
        if accepted:
            assert event[pf['public_spread']]<2*float(TICK[symbol]);checks+=1
            terminal=terminals_by_parent.get(cid,())
            assert len(terminal)==1 and terminal[0][ef['source_row']]==row_i;checks+=2
    return checks,n


def audit_small(data: dict) -> tuple[int,dict,dict,dict,dict]:
    """
    機能: 全792場会計・親脚・12×2全期間を保存小結果だけで検算する。
    引数: data(dict) は一読済み新結果。
    返り値: tuple は比較数と主台帳に渡す口座別index。
    """
    assert data['全合格'] and data['金融'] and len(data['configs'])==12 and len(data['sessions'])==33
    assert data['counts']['新金融口座']==792 and len(data['rows'])==len(data['ledgers'])==len(data['diagnostics'])==792
    ids=[c['id'] for c in data['configs']];sessions=data['sessions'];assert len(set(ids))==12 and len(set(sessions))==33
    def key(v: dict) -> tuple:
        """
        機能: case・場・商品だけで口座を同定する。
        引数: v(dict) は保存レコード。
        返り値: tuple[str,str,str] は口座key。UIDを場を跨いで共有しない。
        """
        return v['case'],v['session'],v['symbol']
    rows={key(r):r for r in data['rows']};diags={key(d):d for d in data['diagnostics']}
    pp=defaultdict(list);ll=defaultdict(list)
    for p in data['parents']:pp[key(p)].append(p)
    for l in data['actual_legs']:ll[key(l)].append(l)
    expected={(c,s,y) for c in ids for s in sessions for y in CAP};assert set(rows)==set(diags)==expected
    checks=0
    for k,row in rows.items():checks+=account(row,pp[k],ll[k],diags[k])
    for cid in ids:
        for symbol in CAP:
            rr=[r for k,r in rows.items() if k[0]==cid and k[2]==symbol]
            ps=[p for k,items in pp.items() if k[0]==cid and k[2]==symbol for p in items]
            ls=[l for k,items in ll.items() if k[0]==cid and k[2]==symbol for l in items]
            target=data['aggregate'][cid][symbol]
            top=sorted((r for r in rr if f(r['収支'])>0),key=lambda r:(-f(r['収支']),r['session']))[:3]
            exclude={r['session'] for r in top};assert target['除外場']==[r['session'] for r in top];checks+=1
            groups={'全場':sessions,'前半':sessions[:16],'後半':sessions[16:],
                'デイ':[s for s in sessions if s.endswith('_Day')],'ナイト':[s for s in sessions if s.endswith('_Night')],
                '上位3黒字場除外':[s for s in sessions if s not in exclude]}
            for name,scope in groups.items():
                rrr=[r for r in rr if r['session'] in scope];pss=[p for p in ps if p['session'] in scope];lss=[l for l in ls if l['session'] in scope]
                checks+=dictionary(target[name],period(rrr,pss,lss,symbol));assert target[name]['sessions']==scope;checks+=1
            for name,side in (('買い',1),('売り',-1)):
                checks+=dictionary(target['方向'][name],dict(**amounts([p for p in ps if p['side']==side]),**quantities([l for l in ls if l['side']==side])))
    return checks,rows,pp,ll,diags


def prepare() -> None:
    """
    機能: 結果未読のまま監査目的・上限・sourceと純算術成功を固定する。
    引数: なし。
    返り値: None。結果の存在を前提にせず、金融又は台帳を開かない。
    """
    assert not PLAN.exists() and not ART.exists()
    source=sources();formal=formal_sources();checks=0
    for symbol in CAP:
        for q in range(1,101):
            expected=Fraction(209,5)*q if symbol=='TOPIX' else Fraction(11)*q
            assert fee(q,symbol)==expected.numerator//expected.denominator;checks+=1
        for values in ((13,-7),(100000,),(),(100,-100),(0,)):
            parents=[dict(net_yen=v) for v in values];a=amounts(parents)
            equal(a['収支'],sum(values));checks+=1
            json.dumps(a,allow_nan=False);checks+=1
    # ----------------------------------------
    # RLE先頭・重複・元形状をpureに検査し、不正時に台帳再読へ進まない。
    sample=dict(shape=(5,2),starts=np.array([0,2,4],np.int64),values=np.array([[1.,np.nan],[2.,np.nan],[3.,4.]]))
    starts,vals,n=rle(sample,2);assert n==5;checks+=1
    for bad in (dict(sample,starts=np.array([1,2,4])),dict(sample,starts=np.array([0,2,2])),dict(sample,shape=(4,2))):
        try:rle(bad,2)
        except AssertionError:checks+=1
        else:raise AssertionError('不正RLEを受理')
    assert source==sources() and formal==formal_sources()
    write(ART,dict(全合格=True,source_SHA256=source,純算術確認=checks,金融結果=0,実台帳=0,原入力=0,API=0))
    write(PLAN,dict(全合格=True,段階='PREPARED_ONLY_FINANCE_UNREAD',source_SHA256=source,正式source_SHA256=formal,
        結果path=RESULT.relative_to(ROOT).as_posix(),結果SHA='根の完成通知後にCLIで固定。未通知実行不可。',
        予定=dict(新結果本文=1,主候補台帳=66,その他台帳=0,原NPZ=0,保存eventNPZ=0,原板=0,cache=0,API=0,金融再生=0),
        読取byte上限=dict(結果=1024**3,主台帳合計=2*1024**3),同bytesOwnedcopy閾値=40*1024**2,
        主候補=MAIN,全体='792rows/親脚UID・fee配賦・実脚BBO金額分解。12×2×全場/前後/昼夜/positive上位3除外。',
        主台帳='66orders/UID/脚/最終cash/全RLE区間。予約数量/first next normal/seq+1/場停止閾値。',
        未測=['他726実ordersの直接読取','原NPZと保存snapshotの値の再照合','全原BBO/Qty/時計の再読','初回budgetmidの原BBO再照合',
             '真受信時刻/実注文遅延/5秒stress/追加二場'],
        予防='開始/読取計数を先保存。不一致時False保全、自動再実行0。',
        人工=dict(path=ART.name,SHA256=sha(ART))))
    print(json.dumps(dict(準備完了=True,純算術確認=checks,planSHA256=sha(PLAN),artSHA256=sha(ART),金融結果読=0),ensure_ascii=False))


def run(expected: str) -> None:
    """
    機能: 根の完成SHA指定後だけ、新結果一読と主66台帳の独立監査を行う。
    引数: expected(str) はroot完成通知の64桁SHA。
    返り値: None。新金融実行・入力再読・失敗再試行は行わない。
    """
    assert isinstance(expected,str) and len(expected)==64 and all(c in '0123456789abcdef' for c in expected)
    plan=json.loads(PLAN.read_text(encoding='utf-8'));source=sources()
    assert source==plan['source_SHA256'] and sha(ART)==plan['人工']['SHA256']
    formal=formal_sources();assert formal==plan['正式source_SHA256']
    assert not any(p.exists() for p in (HERE/'開始.json',HERE/'False.json',OUTPUT))
    stat=RESULT.stat();assert stat.st_size<=plan['読取byte上限']['結果']
    counts=dict(新結果本文=0,主候補台帳=0,その他台帳=0,原NPZ=0,保存eventNPZ=0,原板=0,cache=0,API=0,金融再生=0)
    write(HERE/'開始.json',dict(目的='全小会計と主66台帳の独立実会計監査',計画SHA256=sha(PLAN),期待結果SHA256=expected,
        result_stat_bytes=stat.st_size,byte予算=plan['読取byte上限'],読取計数開始=counts.copy(),source_SHA256=source))
    try:
        counts['新結果本文']+=1;raw=RESULT.read_bytes()
        assert len(raw)==stat.st_size and hashlib.sha256(raw).hexdigest()==expected
        assert (stat.st_size,stat.st_mtime_ns)==(RESULT.stat().st_size,RESULT.stat().st_mtime_ns)
        if len(raw)>plan['同bytesOwnedcopy閾値']:
            owned=HERE/'owned';owned.mkdir();(owned/'結果同bytes.json').write_bytes(raw)
        data=json.loads(raw);del raw
        assert data['source_SHA256']==formal
        for path,digest in data['source_SHA256'].items():
            file=(ROOT/path).resolve();assert file.is_relative_to(ROOT) and sha(file)==digest
        checks,rows,pp,ll,diags=audit_small(data)
        ledgers=[v for v in data['ledgers'] if v['case']==MAIN]
        assert len(ledgers)==66 and {(l['session'],l['symbol']) for l in ledgers}=={(s,y) for s in data['sessions'] for y in CAP}
        assert sum(l['bytes'] for l in ledgers)<=plan['読取byte上限']['主台帳合計']
        curve_rows=0
        for info in ledgers:
            key=info['case'],info['session'],info['symbol'];path=(ROOT/info['path']).resolve()
            assert path.is_relative_to(WORK/'finance/ledgers') and path.parent.name==MAIN
            counts['主候補台帳']+=1;raw=path.read_bytes()
            assert len(raw)==info['bytes'] and hashlib.sha256(raw).hexdigest()==info['SHA256']
            saved=pickle.load(gzip.GzipFile(fileobj=io.BytesIO(raw),mode='rb'));del raw
            amount,length=ledger(saved,rows[key],pp[key],ll[key],diags[key]);checks+=amount;curve_rows+=length
            del saved
        assert counts['主候補台帳']==66 and source==sources() and formal==formal_sources()
        write(OUTPUT,dict(全合格=True,結果SHA256=expected,source_SHA256=source,正式source_SHA256=formal,source開始終端一致=True,
            比較数=checks,全口座=792,親数=len(data['parents']),実脚数=len(data['actual_legs']),期間商品=24,
            主候補台帳=66,主候補全原行のRLE照合=curve_rows,読取計数=counts,
            留保=plan['未測'],主基準='TOP全33net平均10万円＋金額65/赤場20/最大赤<=平均黒。NK円床未指定。'))
        print(json.dumps(dict(全合格=True,比較数=checks,読取計数=counts,SHA256=sha(OUTPUT)),ensure_ascii=False))
    except BaseException:
        write(HERE/'False.json',dict(全合格=False,読取計数=counts,原因=traceback.format_exc(),自動再実行=False))
        raise


def main() -> None:
    """
    機能: 事前prepareと根SHA解除後の一回監査を別段階で受け付ける。
    引数: CLI --prepare 又は --root-finance-complete、--expected-result-sha(str)。
    返り値: None。root通知前の結果読取を行わない。
    """
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--root-finance-complete',action='store_true')
    parser.add_argument('--expected-result-sha');args=parser.parse_args()
    if args.prepare:prepare()
    else:run(args.expected_result_sha)


if __name__=='__main__':
    main()
