"""実市場なしで、十二条件の注文・玉・全tick時価を外部期待値と照合する。"""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
sys.path.insert(0,str(WORK))
import engine125 as E
import catalog125 as C

OI={k:i for i,k in enumerate(E.ORDER_COLUMNS)}
TI={k:i for i,k in enumerate(E.TRADE_COLUMNS)}
CI={k:i for i,k in enumerate(E.CURVE_COLUMNS)}
CHECKS=Counter()
DETAILS=[]


def check(value: bool,name: str) -> None:
    """
    機能: 独立した期待条件を照合し、失敗時に金融前で停止する。
    引数: value(bool)は条件、name(str)は確認名。
    返り値: None。
    """
    assert bool(value),name
    CHECKS[name]+=1


def near(actual: object,expected: object,name: str) -> None:
    """
    機能: 金額の演算丸めだけを許容して外部期待値を照合する。
    引数: actual/expected(object)は配列又は数、name(str)は確認名。
    返り値: None。
    """
    check(np.allclose(actual,expected,rtol=1e-12,atol=1e-5,equal_nan=True),name)


def fixture(prices: list[float],times: list[float],feature: str='none',fr: list[int]|None=None) -> tuple[dict,dict,dict]:
    """
    機能: 人工価格・同clock原順・人工確定足だけから入力を作る。
    引数: prices/times(list[float])、feature(str)、fr(list[int]|None)は価格と状態の公開原行。
    返り値: tuple[dict,dict,dict]は気配・状態・商品設定。実市場値は使用しない。
    """
    p=np.asarray(prices,float);t=np.asarray(times,float)
    q=dict(row=np.arange(len(p),dtype=np.int64),time=t,last=p,bid=p-.5,ask=p+.5)
    base=np.array([1000.,999.,1008.,992.,1000.,.5,4.,4.,1.,.5,60.,4.])
    if feature=='none':base[:]=np.nan
    elif feature=='range':base[5]=.1;base[6]=0.;base[9]=.1
    rows=np.asarray([0] if fr is None else fr,dtype=np.int64)
    f=dict(feature_rows=rows,features=np.tile(base,(len(rows),1)))
    config=dict(cap=10,multiplier=1000.,fee=41.8,observed_tick=.5,session_start=0.,
        entry_end=2400.,close_time=3000.,session_end=3360.)
    return q,f,config


def evaluate(q: dict,f: dict,config: dict,spec: dict) -> tuple:
    """
    機能: 通常JITとPython本体を同じ人工へ適用し、全返却配列を比較する。
    引数: q/f/config/spec(dict)は人工入力と固定条件。
    返り値: tupleは通常版の注文・玉・曲線・集計。金融標本ではない。
    """
    accelerated=E.evaluate(q,f,config,spec)
    saved=E.replay
    try:
        E.replay=saved.py_func
        plain=E.evaluate(q,f,config,spec)
    finally:E.replay=saved
    for i in range(3):
        check(np.array_equal(accelerated[i],plain[i],equal_nan=True),'通常高速の全配列同値')
    for key in accelerated[3]:near(accelerated[3][key],plain[3][key],'通常高速の全summary同値')
    accounting(q,config,accelerated)
    return accelerated


def accounting(q: dict,config: dict,result: tuple) -> None:
    """
    機能: 売買実装を使わず、全注文から数量・料金・全tick清算評価と完結群を再計算する。
    引数: q/config(dict)、result(tuple)は人工気配・倍率と保存返却値。
    返り値: None。代理精算と通常約定を分離し、未返済を利益0に置換しない。
    """
    orders,trades,curve,summary=result;mult=config['multiplier'];fee=config['fee'];cap=config['cap']
    check(all(np.isfinite(a).all() for a in (orders,trades,curve)),'保存台帳は有限')
    check(len(set(orders[:,OI['order_uid']]))==len(orders),'注文UID一意')
    check(len(set(trades[:,TI['group_id']]))==len(trades),'完結group一意')
    cash=realized=qty=side=notional=entry_fee=high=dd=minimum=0.
    current_group=0;index=0;last_clock=-math.inf;states={};group_entries={};valid_rows=[]
    max_long=max_short=0
    for i,raw in enumerate(q['row']):
        now=q['time'][i];last=q['last'][i];bid=q['bid'][i];ask=q['ask'][i]
        if not (np.isfinite([now,last,bid,ask]).all() and config['session_start']<=now<=config['session_end']
            and now>=last_clock and last>0 and 0<bid<=ask):continue
        last_clock=now;valid_rows.append(i)
        while index<len(orders) and int(orders[index,OI['fill_row']])==raw:
            order=orders[index];kind=int(order[OI['kind']]);direction=int(order[OI['side']]);amount=int(order[OI['quantity']])
            group=int(order[OI['group_id']]);price=order[OI['price']];charge=math.floor(amount*fee+1e-9)
            check(raw>order[OI['decision_row']],'判断と同じ原行で約定しない')
            near(price,ask if direction==1 else bid,'買ask売bidの実気配')
            near(charge,order[OI['fee']],'一注文数量から料金floor')
            if kind==1:
                if qty==0:side=direction;current_group=group;notional=entry_fee=0.
                check(direction==side and group==current_group,'純方向とgroupの保存')
                qty+=amount;notional+=amount*price;entry_fee+=charge;cash-=charge
                group_entries.setdefault(group,[]).append(order)
            else:
                check(kind==2 and amount==qty and direction==-side and group==current_group,'反転前に旧方向全返済')
                gross=side*(price*qty-notional)*mult;net=gross-entry_fee-charge
                cash+=gross-charge;realized+=net;qty=side=notional=entry_fee=0.
                near(order[OI['realized_net']],net,'通常返済純損益の外部算術')
            check(0<=qty<=cap,'全原行で数量上限')
            near(order[OI['position_after']],side*qty,'保存保有数量の一致')
            near(order[OI['cash_after']],cash,'保存現金の一致')
            near(order[OI['average_entry_after']],notional/qty if qty else 0.,'保存平均建値の一致')
            index+=1
        equity=cash+(side*((bid if side==1 else ask)*qty-notional)*mult-math.floor(qty*fee+1e-9) if qty else 0.)
        high=max(high,equity);dd=max(dd,high-equity);minimum=min(minimum,equity)
        max_long=max(max_long,qty if side==1 else 0);max_short=max(max_short,qty if side==-1 else 0)
        states[int(raw)]=[equity,cash,realized,qty if side==1 else 0.,qty if side==-1 else 0.,high-equity]
    check(index==len(orders),'全注文が有効原行へ対応')
    for row in curve:
        state=states[int(row[CI['row']])]
        near(row[[CI[k] for k in ('equity','cash','realized_net','long','short','drawdown')]],state,'曲線全保存行の独立時価')
    for trade in trades:
        group=int(trade[TI['group_id']]);entries=group_entries[group]
        amount=sum(o[OI['quantity']] for o in entries);total=sum(o[OI['quantity']]*o[OI['price']] for o in entries)
        charges=sum(o[OI['fee']] for o in entries);direction=trade[TI['side']]
        near(trade[TI['quantity']],amount,'完結数量は全初回追加の和')
        near(trade[TI['entry_notional']],total,'完結建値名目の保存')
        near(trade[TI['average_entry']],total/amount,'完結平均建値の保存')
        gross=direction*(trade[TI['exit_price']]*amount-total)*mult
        exit_fee=math.floor(amount*fee+1e-9);net=gross-charges-exit_fee
        near(trade[TI['gross']],gross,'完結粗損益の外部算術');near(trade[TI['entry_fees']],charges,'全新規料金保存')
        near(trade[TI['exit_fee']],exit_fee,'返済料金floor');near(trade[TI['net']],net,'完結純損益の外部算術')
        if trade[TI['proxy_flag']]:
            check(trade[TI['exit_row']]==-1,'代理に架空fillrowなし')
            check(not any(o[OI['kind']]==2 and o[OI['group_id']]==group for o in orders),'代理に架空返済注文なし')
            ref=int(trade[TI['reference_row']]);j=int(np.flatnonzero(q['row']==ref)[0])
            check(config['session_end']-360<=q['time'][j]<=config['session_end'],'代理は直前六分以内')
            near(trade[TI['exit_price']],q['bid'][j] if direction==1 else q['ask'][j],'代理は参照原行BBO')
            cash+=gross-exit_fee;realized+=net;qty=side=notional=entry_fee=0.
    near(summary['cash'],cash,'summary現金の外部算術')
    near(summary['profit'],np.maximum(trades[:,TI['net']],0).sum(),'全勝群利益合計')
    near(summary['loss'],np.maximum(-trades[:,TI['net']],0).sum(),'全負群損失合計')
    near(summary['unclosed_quantity'],qty,'残玉数量を隠さない')
    near(summary['max_long'],max_long,'全tick最大買数量');near(summary['max_short'],max_short,'全tick最大売数量')
    near(summary['max_drawdown'],dd,'全tickDD');near(summary['min_equity'],minimum,'全tick最悪評価')
    near(summary['fees_paid'],orders[:,OI['fee']].sum()+trades[trades[:,TI['proxy_flag']]==1,TI['exit_fee']].sum(),'通常代理の全料金')
    closed_qty=trades[:,TI['quantity']].sum();new_qty=orders[orders[:,OI['kind']]==1,OI['quantity']].sum()
    near(new_qty,closed_qty+qty,'全数量保存')
    if qty==0:near(summary['net'],trades[:,TI['net']].sum(),'flat口座の全純損益一致')
    else:near(summary['net'],states[int(q['row'][valid_rows[-1]])][0],'未返済口座は最終気配清算時価')


def main() -> None:
    """
    機能: 通常・代理・反転・費用・欠測・接頭の人工を実行して源SHAに拘束する。
    引数: なし。
    返り値: None。実市場・保存価格配列・金融・登録・APIは0。
    """
    engine_sha=hashlib.sha256((WORK/'engine125.py').read_bytes()).hexdigest()
    catalog_sha=hashlib.sha256((WORK/'catalog125.py').read_bytes()).hexdigest()
    specs=C.specifications();check(len(specs)==12,'固定十二条件')
    base=next(s for s in specs if s['id']=='A00');broad=next(s for s in specs if s['id']=='B03')
    q,f,config=fixture([1000,1001,1001,1001,1011,1011,1011],[0,1800,1800,1801,3000,3000,3001])
    for spec in specs:
        result=evaluate(q,f,config,spec);o,t,c,s=result
        check(len(o)==2 and len(t)==1,'全条件の非空通常往復')
        near(o[0,OI['quantity']],5,'初回は通常半上限')
        check(o[0,OI['decision_row']]==1 and o[0,OI['fill_row']]==2,'同clock次原行約定')
        near(t[0,TI['net']],44582.,'通常終端の外部期待44582円')
        check(t[0,TI['exit_reason']]==15 and s['unclosed_quantity']==0,'通常返済終端flat')
        mirror={k:v.copy() for k,v in q.items()};mirror['last']=2000-q['last'];mirror['bid']=2000-q['ask'];mirror['ask']=2000-q['bid']
        mirrored=evaluate(mirror,f,config,spec)
        near(mirrored[1][:,TI['net']],t[:,TI['net']],'買売鏡像の同一純益')
        near(mirrored[0][:,OI['side']],-o[:,OI['side']],'買売鏡像の方向交換')
    for cutoff in (2,3,4):
        part={k:v[:cutoff].copy() for k,v in q.items()};prefix=evaluate(part,f,config,base)
        if cutoff==2:check(len(prefix[0])==len(prefix[1])==0,'最終判断に架空次行新規なし')
        else:
            near(prefix[3]['unclosed_quantity'],5,'末尾不足は残玉保持')
            near(prefix[3]['net'],-5418.,'未清算は費用後時価マイナス5418円')
        full=evaluate(q,f,config,base)
        check(np.array_equal(prefix[0],full[0][full[0][:,OI['fill_row']]<cutoff]),'未来切断で通常注文接頭不変')
    proxyq={k:v[:4].copy() for k,v in q.items()};proxyq['time'][-1]=3000.;proxyq['last'][-1]=1011.;proxyq['bid'][-1]=1010.5;proxyq['ask'][-1]=1011.5
    proxy=evaluate(proxyq,f,config,base)
    check(len(proxy[0])==1 and len(proxy[1])==1 and proxy[1][0,TI['proxy_flag']]==1,'通常注文なしの代理全返済')
    near(proxy[3]['net'],44582.,'代理終端の外部期待44582円')
    stopq,stopf,stopc=fixture([1000,1001,1001,990,980,980,980],[0,1800,1800,1801,1802,3000,3001])
    stopped=evaluate(stopq,stopf,stopc,base)
    near(stopped[1][0,TI['net']],-110418.,'gap停止は実返済気配でマイナス110418円')
    check(stopped[1][0,TI['exit_price']]<stopped[1][0,TI['initial_stop']],'stop価格へ架空約定しない')
    wideexit={k:v.copy() for k,v in stopq.items()};wideexit['bid'][4]=900.;wideexit['ask'][4]=1100.
    urgent=evaluate(wideexit,stopf,stopc,base)
    near(urgent[1][0,TI['exit_price']],900.,'返済には広幅新規gateを使わない')
    near(urgent[1][0,TI['net']],-507918.,'広い返済気配の損失も全額記録')
    addq,addf,addc=fixture([1000,1001,1001,1007,1008,1007,1012,1012],[0,1800,1800,1801,1802,1803,3000,3001],'trend')
    added=evaluate(addq,addf,addc,broad)
    check(len(added[0])==3 and added[3]['add_orders']==1,'順行後の追加は一回だけ')
    near(added[1][0,TI['net']],64164.,'初回追加料金を含む外部期待64164円')
    for cap in (2,3,20):
        local=dict(addc,cap=cap);value=evaluate(addq,addf,local,broad)
        near(value[3]['max_long'],cap,'追加後も上限まで')
        if cap==3:near(value[1][0,TI['net']],15751.,'一枚と二枚を別発注した料金249円')
    flipq,flipf,flipc=fixture([1000,996,996,1001,1002,1002,1002,1002],[60,70,80,90,100,110,3000,3001],'trend')
    flipped=evaluate(flipq,flipf,flipc,broad)
    exits=flipped[0][flipped[0][:,OI['kind']]==2];entries=flipped[0][flipped[0][:,OI['kind']]==1]
    check(len(exits)>=2 and len(entries)>=2,'反転の非空往復')
    check(exits[0,OI['fill_row']]<entries[1,OI['fill_row']],'反転前に実返済済み')
    for name,edit in [('Lastゼロ',('last',0.)),('Last負数',('last',-1.)),('LastNaN',('last',np.nan)),
        ('Last無限',('last',np.inf)),('気配NaN',('bid',np.nan)),('気配逆転',('bid',2000.)),('時計逆行',('time',1799.))]:
        bad={k:v.copy() for k,v in q.items()};bad[edit[0]][2]=edit[1]
        value=evaluate(bad,f,config,base)
        check(value[0][0,OI['fill_row']]==3,'異常原行を約定へ使わない:'+name)
    for age,expected in ((120,1),(121,0)):
        aq,af,ac=fixture([1000,999,1000,1000],[69,100,age,age+1],'trend')
        value=evaluate(aq,af,ac,base)
        check(value[3]['entry_orders']==expected,'公開分の秒差を含むpeer年齢境界'+str(age))
    for family,reason,prices in (
        ('A',1,[1000,999,1000,1000,1005,1005]),
        ('B',2,[1000,996,1000,1000,1005,1005]),
        ('C',3,[1000,1000,1000,1000,1005,1005])):
        primaryq,primaryf,primaryc=fixture(prices,[60,70,80,81,3000,3001],'trend')
        spec=next(s for s in specs if s['id']==family+'00')
        value=evaluate(primaryq,primaryf,primaryc,spec)
        check(len(value[1])==1 and value[1][0,TI['entry_reason']]==reason,'期限代用でない各家族の非空入口:'+family)
        near(value[1][0,TI['net']],19582.,'各家族通常入口の外部期待19582円')
    rangeq,rangef,rangec=fixture([992,992.5,993,993,1000,1000,1000,1000],[60,70,80,81,100,101,3000,3001],'range')
    ranged=evaluate(rangeq,rangef,rangec,next(s for s in specs if s['id']=='C00'))
    check(ranged[1][0,TI['entry_reason']]==4 and ranged[1][0,TI['exit_reason']]==14,'往復中心回帰の非空入口出口')
    near(ranged[1][0,TI['net']],29582.,'往復中心回帰の外部期待29582円')
    for mode in ('A','C'):
        spec=next(s for s in specs if s['id']==mode+'00')
        prices=[1000,999,1000,1000] if mode=='A' else [992,992.5,993,993]
        aq,af,ac=fixture(prices,[60,70,80,81],'trend' if mode=='A' else 'range',[0,2])
        af['features'][1]=np.nan
        value=evaluate(aq,af,ac,spec)
        check(value[3]['entry_orders']==0,'fresh欠測で準備取消:'+mode)
    wide={k:v.copy() for k,v in q.items()};wide['bid'][1]=995;wide['ask'][1]=1007
    value=evaluate(wide,f,config,base)
    check(value[0][0,OI['decision_row']]==2 and value[0][0,OI['fill_row']]==3,'広幅期限は狭い正常気配を待つ')
    widefill,_,_=fixture([1000,1001,1001,1001,1001,1011,1011],[0,1800,1800,1801,1802,3000,3001])
    widefill['bid'][2]=995;widefill['ask'][2]=1007
    value=evaluate(widefill,f,config,base)
    check(value[0][0,OI['decision_row']]>=3 and value[3]['canceled_entries']>=1,'次fill広幅は取消し再判断')
    full=evaluate(q,f,config,base)
    for cut in (2,3,4):
        changed={k:v.copy() for k,v in q.items()}
        changed['last'][cut:]=np.array([1200. if i%2 else 800. for i in range(len(q['row'])-cut)])
        changed['bid'][cut:]=changed['last'][cut:]-.5;changed['ask'][cut:]=changed['last'][cut:]+.5
        altered=evaluate(changed,f,config,base)
        check(np.array_equal(altered[0][altered[0][:,OI['fill_row']]<cut],full[0][full[0][:,OI['fill_row']]<cut]),'未来価格改変で通常注文接頭不変')
        for raw in q['row'][:cut]:
            old=full[2][full[2][:,CI['row']]==raw];new=altered[2][altered[2][:,CI['row']]==raw]
            if len(old) and len(new):near(new,old,'未来改変で保存時価の接頭不変')
    check(hashlib.sha256((WORK/'engine125.py').read_bytes()).hexdigest()==engine_sha,'実行中源不変')
    check(hashlib.sha256((WORK/'catalog125.py').read_bytes()).hexdigest()==catalog_sha,'条件源不変')
    proof=dict(passed=True,engine_sha256=engine_sha,catalog_sha256=catalog_sha,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),checks=dict(CHECKS),
        check_count=sum(CHECKS.values()),financial_replays=0,original_market_reads=0,saved_price_array_reads=0,
        API=0,real_orders=0,registry_changes=0,
        limitation='人工で売買・料金・原順・時価の仕様を検査したもので、方向予測の勝率・日次活動・0.5%利益を測定したものではない。')
    target=HERE/'十二仕様と全tick会計及び因果境界の独立人工_v2.json'
    check(not target.exists(),'独立証跡の上書き拒否')
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,path=target.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        engine_sha256=engine_sha,catalog_sha256=catalog_sha,check_count=sum(CHECKS.values())),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
