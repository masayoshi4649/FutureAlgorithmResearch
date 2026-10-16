"""結果未読の人工BBOでmid分解、紙上/Native数量とON比較の分母を固定する。"""

import copy
import hashlib
import json
from pathlib import Path
import analysis

HERE=Path(__file__).resolve().parent


def parent(symbol: str,side: int,move: float,spread: float,cid: int=0) -> tuple:
    """
    機能: 当該BBO成行の全量一UID親と価格式を持つ明示人工を作る。
    引数: symbol(str)、side/cid(int)、move/spread(float) は商品・方向・mid移動/最終幅。
    返り値: tuple は実親型と十四列origin。金融engineは運転しない。
    """
    q=analysis.CAP[symbol];tick=.5 if symbol=='TOPIX' else 10.;base=4000. if symbol=='TOPIX' else 65000.
    e_bid=base;e_ask=base+tick;exit_mid=(e_bid+e_ask)/2+side*move*tick
    x_bid=exit_mid-spread*tick/2;x_ask=exit_mid+spread*tick/2
    ep=e_ask if side>0 else e_bid;xp=x_bid if side>0 else x_ask
    numerator,denominator=analysis.RATE[symbol];charge=q*numerator//denominator;net=side*(xp-ep)*q*analysis.MULT[symbol]-charge*2
    v=5 if symbol=='TOPIX' else 10;remain=3 if symbol=='TOPIX' else 6
    def point(row: int,bid: float,ask: float,remaining: int,local: float) -> dict:
        """
        機能: 代理時計/原seqと同観測のpaper残量を持つ人工点を作る。
        引数: row/remaining(int)、bid/ask/local(float) は行・紙上量・BBO・局所清算。
        返り値: dict は正常人工観測点。Native数量をpaper量へ変えない。
        """
        return dict(normal_row=row,raw_seq=row*2+1,raw_index=row*2,price_time_s=1790900000.+row,
            bid=bid,ask=ask,Last=(bid+ask)/2,normal=True,parent_liquidation_yen=local,paper_parent=7,
            paper_direction=side,paper_remaining_quantity=remaining)
    row=310+cid*30;e=point(row+1,e_bid,e_ask,v,-(tick*q*analysis.MULT[symbol]+charge*2));x=point(row+20,x_bid,x_ask,remain,net)
    entry=dict(row=row+1,source_row=row,quantity=q,price=ep,fee_yen=charge,reason=90,判断=point(row,e_bid,e_ask,v,0.),約定=e)
    exit_event=dict(row=row+20,source_row=row+19,quantity=q,price=xp,fee_yen=charge,reason=140,判断=point(row+19,x_bid,x_ask,remain,net),約定=x)
    p=dict(session='人工00_Day',symbol=symbol,parent=cid,paper_parent=7,side=side,entry=entry,exits=[exit_event],
        entry_quantity=q,maximum_held_quantity=q,fees_yen=charge*2,net_yen=net,publication_kind=0 if cid==0 else 1,
        notional_yen=ep*q*analysis.MULT[symbol],parent_mfe_yen=max(1000.,net),holding_price_proxy_seconds=19.,
        first_parent_liquidation_argmax=point(row+2,e_bid,e_ask,v,max(1000.,net)),
        first_parent_liquidation_argmin=e)
    origin=[cid,7,row+1,row,side,q,ep,p['notional_yen'],0.,base,4*tick,ep,0.,cid]
    return p,origin


def fixture() -> tuple:
    """
    機能: 十二case/全33場の型と保存ONの各場net比較を明示人工だけで構成する。
    引数: なし。
    返り値: tuple はresult/fixed。実金融792を実行した証跡にはしない。
    """
    sessions=['人工%02d_%s'%(i,'Day' if i%2==0 else 'Night') for i in range(33)];configs=[]
    for mode in ('ORIGIN','PULL','BREAK','ADAPTIVE'):
        for exit_id in ('TARGET','TIGHT_TRAIL','WIDE_TRAIL'):
            configs.append(dict(id='E01_NO_PRICE_EXIT_'+mode+'_'+exit_id,paired_on_id='E01_PROTECT_'+mode+'_'+exit_id,enable_opposed_price_exit=False))
    source={'人工数学':'明示人工'};cases={};profiles={};bounds={};paired={}
    for i,c in enumerate(configs):
        cid=c['id'];rows=[];parents=[];bound=[];periods={};on={}
        for s in analysis.CAP:
            own=[];scene=[]
            for session in sessions:
                ps=[];origins=[]
                if session==sessions[0]:
                    for j,move in enumerate((3.,-1.)):
                        p,o=parent(s,1,move,1.,j);ps.append(p);origins.append(o)
                own.extend(ps);bound.append(dict(session=session,symbol=s,actual_origins=origins,judgments=[]))
                gain=sum(max(0.,p['net_yen']) for p in ps);loss=sum(max(0.,-p['net_yen']) for p in ps)
                row=dict(session=session,symbol=s,親数=len(ps),利益=gain,損失=loss,収支=gain-loss,費用=sum(p['fees_yen'] for p in ps));rows.append(row)
                scene.append(dict(session=session,net_yen=row['収支'],parent_count=len(ps)))
            parents.extend(own);net=sum(p['net_yen'] for p in own)
            full=dict(aggregate={'収支':net},economic=dict(session_count=33,by_session=scene),
                stability=dict(positive_sessions=int(net>0),losing_sessions=int(net<0),no_trade_sessions=32))
            periods[s]={'全33':full,'上位3正収支場除外':copy.deepcopy(full)}
            previous=copy.deepcopy(full);previous['aggregate']['収支']-=1000*(i%3-1);previous['economic']['by_session'][0]['net_yen']-=1000*(i%3-1)
            on[s]={'全場':previous,'上位三除外':copy.deepcopy(previous),'買売':{}}
        cases[cid]=dict(rows=rows,periods=periods);profiles[cid]=parents;bounds[cid]=bound;paired[cid]=dict(on_id=c['paired_on_id'],saved_on=on)
    fixed=dict(configs=configs,sessions=sessions,source_SHA256=source,case_SHA256={'人工case':'明示人工'})
    result=dict(全合格=True,source開始終端一致=True,configs=configs,sessions=sessions,source_SHA256=source,case_SHA256=fixed['case_SHA256'],
        counts={'既input一読':33,'価格票準備口座':66,'新account金融':792},results=cases,actual_parent_diagnostics=profiles,boundary=bounds,paired_saved_on=paired)
    return result,fixed


def run() -> None:
    """
    機能: 買売/商品/横断幅の数式と不一致拒否、各場net/trim比較の型を固定する。
    引数: なし。
    返り値: None。結果/packet/台帳/API未読の人工証跡を保存する。
    """
    sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')};checks=0;labels=set()
    for s in analysis.CAP:
        for side in (1,-1):
            for move in (-2.,0.,.5,1.,3.):
                for spread in (1.,2.,4.):
                    p,o=parent(s,side,move,spread);d=analysis.decompose(p,o);labels.add(d['cause'])
                    assert analysis.close(d['gross_direction_mid_yen']-d['crossing_disadvantage_yen']-d['order_fees_yen'],p['net_yen'])
                    assert d['entry_paper_remaining_quantity']!=p['entry_quantity'] and d['exit_paper_remaining_quantity'] in (3,6);checks+=1
    assert 'mid方向が逆行' in labels and 'mid順行しても気配差と料を回収できない' in labels
    result,fixed=fixture();out=analysis.analyze(result,fixed);checks+=out['検算件数']
    for s in analysis.CAP:assert out['net_change_counts'][s]==dict(improved=4,worsened=4,unchanged=4);checks+=1
    for kind in range(5):
        p,o=parent('TOPIX',1,3.,1.)
        if kind==0:p['entry_quantity']=5
        elif kind==1:p['fees_yen']+=1
        elif kind==2:p['entry']['price']+=.5
        elif kind==3:p['exits'].append(copy.deepcopy(p['exits'][0]))
        else:p['exits'][0]['reason']=152
        try:analysis.decompose(p,o)
        except AssertionError:checks+=1
        else:raise AssertionError('不一致を拒否しない')
    assert sources=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')}
    target=HERE/'mid方向と横断不利及び実料の純人工.json';assert not target.exists()
    target.write_text(json.dumps(dict(全合格=True,確認数=checks,source_SHA256=sources,型case=12,型場=33,結果読取=0,packet=0,台帳=0,新金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('mid分解診断人工合格 '+str(checks)+'確認。実結果未読。')


if __name__=='__main__':run()
