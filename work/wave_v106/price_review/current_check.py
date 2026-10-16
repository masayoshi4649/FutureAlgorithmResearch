"""現在場を読まず、独立手計算の完結/未返済/未約定接頭と固定consumerを検査する。"""

from copy import deepcopy
from decimal import Decimal,ROUND_FLOOR
import json
from pathlib import Path

import numpy as np

from range_engine_check import load,digest


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OWNER=ROOT/'work/wave_v106/current_session'


def fixture(symbol: str, side: int, kind: str) -> tuple:
    """
    機能: 金融engineを呼ばず、実注文cashから完結1親と開いた接頭を独立に作る。
    引数: symbol(str)、side(int)、kind(str)はopen/pending/exit_pending/empty。
    返り値: tuple[dict,dict,dict,dict,dict]は入力、手計算台帳、正常候補、設定、期待会計。
    """
    tick,base,mult=(.5,4000.,1000.) if symbol=='TOPIX' else (10.,68000.,10.)
    q=5 if symbol=='TOPIX' else 10;unit=Decimal('41.8') if symbol=='TOPIX' else Decimal('11')
    fee=int((unit*Decimal(q)).to_integral_value(rounding=ROUND_FLOOR));n=8
    stamp=np.array([300.,301.,302.,310.,311.,350.,351.,360.]);bid=np.full(n,base);bid[3:5]=base+2*tick;bid[5:]=base
    ask=bid+tick
    if side<0:bid,ask=2*base-ask,2*base-bid
    valid=np.ones(n,bool);valid[-1]=False
    record=dict(symbol=symbol,tick=tick,start=0.,limit=1000.,time_s=stamp,seq=np.arange(1000,1008,dtype=np.int64),
        bid=bid,ask=ask,quote_valid=valid)
    config=dict(quantity={symbol:q},caps={symbol:2*q},start_offset=300.,cut_offset=300.)
    normal=dict(event=np.zeros(n,np.int8),support_price=np.full(n,np.nan),entry_quality=np.ones(n,bool),entry_reset=np.zeros(n,bool),
        execution_to_raw_index=np.arange(11,19,dtype=np.int64),decisions=[],entry_families=np.zeros(n,np.int8),
        entry_modes=np.zeros(n,np.int8),entry_stop_prices=np.full(n,np.nan),entry_limit_prices=np.full(n,np.nan),
        range_pending_trend=np.zeros(n,bool),quiet=np.zeros(n,bool),quiet_start_s=np.full(n,np.nan))
    orders=[];events=[];trades=[];diagnostics=[]
    def post(parent: int, row: int, source: int, limit: bool=False) -> None:
        """
        機能: 当時正常行で新規候補と予約イベントだけを作る。
        引数: parent/row/source(int)、limit(bool)は識別・行・源・指値指定。
        返り値: None。保有や料金は約定まで作らない。
        """
        support=base-side*4*tick;normal['event'][row]=side;normal['entry_families'][row]=source+1
        normal['support_price'][row]=support;normal['entry_modes'][row]=2 if limit else 1;normal['entry_stop_prices'][row]=support
        normal['entry_limit_prices'][row]=record['bid' if side>0 else 'ask'][row]
        meta=dict(row=row,normal_row=row,raw_row=int(normal['execution_to_raw_index'][row]),raw_seq=int(record['seq'][row]),
            side=side,support_price=support,selected_support_roots=[dict(anchor_raw_seq=999)] if source==0 else [],stop_price=support)
        normal['decisions'].append(meta)
        events.append([row,parent,source,1,side,q,row,support,0,stamp[row],parent,0])
    def fill(parent: int, row: int, decision: int, source: int, uid: int) -> None:
        """
        機能: 公表後の次正常quoteで現金と実保有の新規注文を作る。
        引数: parent/row/decision/source/uid(int)は注文の物理識別。
        返り値: None。金融engineの自己結果へ依存しない。
        """
        price=record['ask' if side>0 else 'bid'][row]
        orders.append([row,decision,parent,source,side,q,price,1,11,fee,stamp[decision],stamp[row],0,parent,11,side,uid])
        events.append([row,parent,source,4,side,q,decision,price,0,stamp[decision],parent,0])
        diagnostics.append(dict(parent_id=parent,decision_raw_row=int(normal['execution_to_raw_index'][decision]),fill_raw_row=int(normal['execution_to_raw_index'][row]),
            decision_raw_seq=int(record['seq'][decision]),fill_raw_seq=int(record['seq'][row])))
    if kind!='empty':
        post(1,1,0);fill(1,2,1,0,1)
        if kind=='exit_pending':
            events.append([3,1,0,2,side,q,3,0,0,stamp[3],1,0]);n=4
        else:
            events.append([3,1,0,2,side,q,3,0,0,stamp[3],1,0])
            price=record['bid' if side>0 else 'ask'][4];orders.append([4,3,1,0,-side,q,price,0,10,fee,stamp[3],stamp[4],0,1,10,side,2])
            events.append([4,1,0,5,side,q,3,price,0,stamp[3],1,0])
            opening=orders[0][6];gross=side*q*(price-opening)*mult
            trades.append([1,0,2,4,side,q,opening,price,fee,fee,gross,gross-2*fee,11,10,1,1])
            post(2,5,1,kind=='pending')
            if kind!='pending':fill(2,6,5,1,3)
    for key,value in record.items():
        if isinstance(value,np.ndarray):record[key]=value[:n]
    for key,value in normal.items():
        if isinstance(value,np.ndarray):normal[key]=value[:n]
    a=np.array(orders,float).reshape(-1,17);e=np.array(events,float).reshape(-1,12);t=np.array(trades,float).reshape(-1,16)
    curve=[];trace=[];cash=0.;held=0;pl=ps=pe=0;last=None
    for row in range(n):
        if record['quote_valid'][row]:last=row
        for o in a[a[:,0]==row]:cash-=o[4]*o[5]*o[6]*mult+o[9];held+=int(o[4]*o[5])
        for event in e[e[:,0]==row]:
            code=int(event[3]);change=q if code==1 else -q if code==4 else 0
            if side>0:pl+=change
            else:ps+=change
            if code==2:pe+=q
            if code==5:pe-=q
        mark=cash
        if held:
            mark+=held*record['bid' if held>0 else 'ask'][last]*mult-fee
        curve.append(mark);trace.append([max(held,0),max(-held,0),max(held,0)+pl,max(-held,0)+ps,pl+ps,pe])
    output=dict(orders=a,trades=t,events=e,raw_entry_diagnostics=diagnostics,curve=np.array(curve),target_trace=np.array(trace))
    realized=float(t[:,11].sum())
    expected=dict(realized=realized,curve=curve[-1],open=curve[-1]-realized,held=abs(held),pending=pl+ps,exit_pending=pe,
        fees=float(a[:,9].sum()),reserved=fee if held else 0,closed=len(t))
    return record,output,normal,config,expected


def run() -> None:
    """
    機能: 確定sourceを変更せず、独立手計算の接頭会計と静的consumerを確認する。
    引数: なし。現在API/NDJSON/現input/現金融を読まない。
    返り値: Noneは私有の非金融証跡。原依存snapshot数学は不変更。
    """
    target=HERE/'current_固定入力と途中会計の独立人工.json';assert not target.exists()
    paths=[OWNER/name for name in ('core.py','prepare.py','common.py','runner.py','partial_accounting.py','finance_artificial.py','finance_runtime/interface.py','finance_runtime/engine/core.py')]
    before={str(p.relative_to(ROOT)):digest(p) for p in paths};account=load('独立現場partial会計',OWNER/'partial_accounting.py')
    counts={};total=0
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            for kind in ('open','pending','exit_pending','empty'):
                r,o,c,config,expected=fixture(symbol,side,kind);actual=account.inspect(r,o,c,config)
                for key,value in dict(realized_net=expected['realized'],actual_liquidation_value=expected['curve'],open_mark_net=expected['open'],
                    pending_entry=expected['pending'],pending_exit=expected['exit_pending'],total_paid_fees=expected['fees'],reserved_exit_fees=expected['reserved'],
                    closed_campaigns=expected['closed']).items():assert actual[key]==value,(symbol,side,kind,key,actual[key],value);total+=1
                assert actual['held_long']+actual['held_short']==expected['held'];total+=1
                assert actual['finish'] is False and actual['realized_net']+actual['open_mark_net']==actual['actual_liquidation_value'];total+=1
                if kind in ('exit_pending','empty'):assert actual['profit_share'] is None and actual['winning_campaigns']==0;total+=1
                if kind=='open':assert actual['quote_invalid_at_end'] and actual['clearing_quote_row']==6;total+=1
                if kind=='pending':assert not actual['open_positions'] and actual['reserved_exit_fees']==0;total+=1
                if kind=='empty':assert actual['actual_liquidation_value']==actual['total_paid_fees']==0;total+=1
                counts[symbol+str(side)+kind]=True
    # ----------------------------------------
    # 根consumerの正式再生はせず、経路をsourceとして確認し入力/登録/終端guardへ束縛する。
    runner=(OWNER/'runner.py').read_text(encoding='utf8');core=(OWNER/'core.py').read_text(encoding='utf8');prepare=(OWNER/'prepare.py').read_text(encoding='utf8')
    assert 'quantity=config[\'quantity\'][symbol],finish=False' in runner
    assert "matches[0]['spec']==plan['spec']" in runner and 'meta[\'configs\']==core.configs()' in runner
    assert 'normal=packet[\'normal_cases\'][config[\'id\']][symbol]' in runner
    assert "assert packet['session']==core.SESSION and packet['configs']==core.configs()" in runner
    assert "diagnostic['本文行数']==snapshots[symbol]['sequence']" in prepare and "len({v['generation'] for v in snapshots.values()})==1" in prepare
    assert "value['entry_quality']=c['entry_quality'].copy();value['entry_reset']=c['entry_reset'].copy()" in core
    assert "stamps[-1]<record['limit']-60." in prepare
    fixed=json.loads((OWNER/'現在入力の結果前固定.json').read_text(encoding='utf8'))
    assert [c['id'] for c in fixed['configs']]==['AUTO_ER40_M2_LIMIT','R_ONLY_ER40_M2_LIMIT','C_ONLY_B2_ER40_B4']
    assert digest(OWNER/'finance_runtime/engine/core.py')==digest(ROOT/'work/wave_v106/range_price/engine/core.py')
    assert before=={str(p.relative_to(ROOT)):digest(p) for p in paths}
    result=dict(全合格=True,scope='現在場内容を読まない固定入力/consumer静的及び手計算partialの独立人工',
        独立手計算人工口座=len(counts),数値検査件数=total,人工=counts,source_SHA256=before,レビューsource_SHA256=digest(Path(__file__)),
        開始終端source一致=True,現Night内容読取=0,現入力gzip読取=0,金融再生=0,API=0,
        確認='未返済は入口料と残返済料を含む当時清算時価、closed netとは別。未約定は保有・料金0。末尾不正quoteは過去正常清算気配だけを保持。取得最終行へ強制返済しない。',
        制約=['単一位置・増玉なし・全量5/10枚だけの会計。一般の部分数量返済・複数UID両建てへ適用しない。',
            '現在場は通常終端前の接頭。結果後に全Nightの勝敗へ読み替えない。',
            '受信時計がないためCurrentPriceTime代理の制限を維持。取得完了時刻は原行の受信時刻ではない。',
            'consumerのsource_curveは公開会計の数値入力に使われず、partial会計自身は合算curveと予約/保有traceを検算する。'])
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('現在場の独立手計算partial',len(counts),'口座',total,'検査合格',flush=True)


if __name__=='__main__':run()
