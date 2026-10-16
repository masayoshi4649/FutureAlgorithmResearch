"""未読の人工BBOとsigned出来高票で金額分解、495唯一金融と99aliasの分母を固定する。"""

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


def informed(symbol: str,move: float,cid: int,entry_id: str) -> tuple:
    """
    機能: 一実親へ当該公開signed票と薄い価格票を付けて人工型を作る。
    引数: symbol/entry_id(str)、move(float)、cid(int) は商品・入口・順行幅・親。
    返り値: tuple は人工親とorigin。実結果又は入力を読まない。
    """
    p,o=parent(symbol,1,move,1.,cid);pub=p['entry']['判断'];pub['own_known']=True;pub['peer_known']=True
    p.update(publication_kind=0,published_entry_information=dict(entry_id=entry_id,accepted=True,volume_accepted=True,price_accepted=False,
        volume=dict(known=True,window_seconds=60,up_votes=3,down_votes=1,direction_votes=4,balance=.5,
        candidate_raw_row=pub['raw_index'],candidate_raw_seq=pub['raw_seq'],candidate_price_time_s=pub['price_time_s'])),
        published_own_count=1,published_peer_count=1,published_own_balance=1.,published_peer_balance=1.,
        published_own_known=True,published_peer_known=True,published_adverse_ticks=0,published_price_cap=p['entry']['price'],
        target_yen=1000.,arm_yen=None,parent_stop_yen=3000.)
    return p,o


def fixture() -> tuple:
    """
    機能: 新六表示/33場と旧親消失・新参加・共通出口差を明示人工だけで作る。
    引数: なし。
    返り値: tuple は新result/fixed/旧projection。正式297金融の証跡ではない。
    """
    sessions=['人工%02d_%s'%(i,'Day' if i%2==0 else 'Night') for i in range(33)];configs=[]
    for entry_id in ('PRICE_BOTH','VOL_SELECTED','VOL25','VOL25_PRICE_BOTH'):
        for exit_id in ('TARGET','TIGHT_TRAIL','WIDE_TRAIL'):
            cid='E01_EVID_'+entry_id+'_'+exit_id
            configs.append(dict(id=cid,entry_id=entry_id,paired_previous_id='E01_INFO_'+entry_id+'_'+exit_id,
                actual_financial=entry_id in ('VOL_SELECTED','VOL25'),enable_opposed_price_exit=False,
                actual_financial_by_symbol={'TOPIX':entry_id in ('VOL_SELECTED','VOL25'),'NK225':entry_id=='VOL_SELECTED'},
                economic_source_id_by_symbol={s:'E01_EVID_VOL_SELECTED_'+exit_id if s=='NK225' and entry_id=='VOL25' else cid for s in analysis.CAP},
                volume_balance_threshold={'TOPIX':.5 if entry_id=='VOL_SELECTED' else .25,'NK225':.25}))
    source={'人工型':'明示人工'};results={};profiles={};bounds={};old={};activity={}
    for c in (v for v in configs if v['actual_financial']):
        cid=c['id'];rows=[];pp=[];bb=[];previous=[]
        for symbol in analysis.CAP:
            for session in sessions:
                own=[];origins=[]
                if session==sessions[0]:
                    for cid_old,move in ((0,3.),(1,-1.),(3,2.)):
                        p,o=informed(symbol,move,cid_old,c['entry_id']);p['session']=session
                        previous.append(analysis.decompose(p,o))
                    for cid_new,move in ((0,4.),(2,-2.)):
                        p,o=informed(symbol,move,cid_new,c['entry_id']);p['session']=session
                        if symbol=='NK225' and c['entry_id']=='VOL25':p['economic_alias_source_id']=c['economic_source_id_by_symbol'][symbol]
                        own.append(p);origins.append(o)
                pp.extend(own);bb.append(dict(session=session,symbol=symbol,actual_origins=origins,judgments=[]))
                gain=sum(max(0,p['net_yen']) for p in own);loss=sum(max(0,-p['net_yen']) for p in own)
                rows.append(dict(session=session,symbol=symbol,親数=len(own),利益=gain,損失=loss,収支=gain-loss,費用=sum(p['fees_yen'] for p in own)))
        results[c['id']]=dict(rows=rows);profiles[cid]=pp;bounds[cid]=bb;old[c['paired_previous_id']]=previous;activity[cid]=[]
    fixed=dict(configs=configs,sessions=sessions,source_SHA256=source,case_SHA256={'型case':'明示人工'})
    result=dict(全合格=True,source開始終端一致=True,configs=configs,sessions=sessions,source_SHA256=source,case_SHA256=fixed['case_SHA256'],
        counts={'既input一読':33,'価格票準備口座':66,'新account金融':297,'内部同値会計再利用':99},
        新account金融=297,内部同値会計再利用=99,旧経済同値保存会計=396,掲載口座=792,
        results=results,actual_parent_diagnostics=profiles,boundary=bounds,activity=activity,
        reused_economic_cases={c['id']:{} for c in configs if not c['actual_financial']},
        internal_aliases=[{} for c in configs if c['entry_id']=='VOL25'])
    previous=dict(全合格=True,all_parent_decomposition=old,activity={cid:[] for cid in old})
    return result,fixed,previous


def run() -> None:
    """
    機能: 価格/料の分解、公開キー対応、五寄与恒等式と不一致拒否を型固定する。
    引数: なし。
    返り値: None。新旧結果又は旧診断本文をまだ読まない。
    """
    source={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')};checks=0
    for symbol in analysis.CAP:
        for side in (1,-1):
            for move in (-2.,0.,.5,1.,3.):
                for spread in (1.,2.,4.):
                    p,o=parent(symbol,side,move,spread);d=analysis.decompose(p,o)
                    assert analysis.close(d['actual_gross_yen']-d['order_fees_yen'],p['net_yen']);checks+=1
    result,fixed,previous=fixture();out=analysis.analyze(result,fixed,previous);checks+=out['検算件数']
    for case in out['paired_parents'].values():
        for change in case.values():
            assert len(change['common'])==1 and len(change['removed'])==2 and len(change['added'])==1
            c=change['contribution'];assert c['avoided_loss']>0 and c['lost_profit']>0 and c['common_entry_exit_difference']>0 and c['new_entry_net']<0;checks+=5
    # 同じ公開なら実CID/UID番号が変わっても共通親。公開原seqを変えた場合だけ別参加。
    p,o=informed('TOPIX',3.,0,'VOL_SELECTED');before=analysis.decompose(p,o);after=copy.deepcopy(before)
    after['parent']=99;after['actual_uid']=77
    same=analysis.counterpart([before],[after]);assert len(same['common'])==1 and not same['removed'] and not same['added'];checks+=1
    after['entry']['判断']['raw_seq']+=1
    different=analysis.counterpart([before],[after]);assert not different['common'] and len(different['removed'])==len(different['added'])==1;checks+=1
    try:analysis.counterpart([before,before],[])
    except AssertionError:checks+=1
    else:raise AssertionError('重複公開キーを拒否しない')
    assert source=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')}
    target=HERE/'新旧公開キーと五寄与及び実料の純人工.json';assert not target.exists()
    target.write_text(json.dumps(dict(全合格=True,確認数=checks,source_SHA256=source,型比較条件=12,型新表示=6,型場=33,
        金融=0,新結果=0,旧診断本文=0,旧金融本文=0,input=0,台帳=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('111対応診断純人工 '+str(checks)+'確認合格。新旧本文未読。',flush=True)


if __name__=='__main__':run()


