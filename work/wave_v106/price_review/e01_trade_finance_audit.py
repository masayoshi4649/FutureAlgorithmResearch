"""E01確認24の小会計と抽出UID現金、影GUと場内停止の境界を独立検算する。"""

from collections import defaultdict
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
import json
import statistics
import traceback

import numpy as np

import range_finance_audit as A


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_trade_gate'
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')
SPECIAL={'E01_TRADE_W60_VETO_D0_P1L8','E01_TRADE_W60_CONFIRM_D0_P1L8'}


def metric(nets: list[float]) -> dict:
    """
    機能: 独立親金額又は掲載合計から利益・損失・分母を計算する。
    引数: nets(list[float])は完結親の料金後損益。
    返り値: dictは金額指標。無取引や未完結を勝ちに含めない。
    """
    p=sum(x for x in nets if x>0);l=-sum(x for x in nets if x<0);nw=sum(x>0 for x in nets);nl=sum(x<0 for x in nets)
    return dict(利益=p,損失=l,収支=sum(nets),親数=len(nets),勝ち親=nw,負け親=nl,零親=sum(x==0 for x in nets),PF=p/l if l else None,利益割合=p/(p+l) if p+l else None,平均利益=p/nw if nw else None,平均損失=l/nl if nl else None,平均損益比=(p/nw)/(l/nl) if nw and nl else None)


def row_check(r: dict, q: int) -> None:
    """
    機能: 一商品一場の料金後GL・枚数・無活動の意味を検算する。
    引数: r(dict)、q(int)は保存小会計と初回枚数。
    返り値: None。不活動は成功でない。
    """
    A.equal(r['収支'],r['利益']-r['損失'],'E01行/GL')
    A.equal(r['親数'],r['勝ち親']+r['負け親']+r['零親'],'E01行/親数')
    A.equal(r['新規枚数'],r['親数']*q,'E01行/新規量')
    A.equal(r['新規枚数'],r['勝ち枚数']+r['負け枚数']+r['零枚数'],'E01行/返済量')
    A.equal(r['利益割合'],r['利益']/(r['利益']+r['損失']) if r['利益']+r['損失'] else None,'E01行/share')
    A.check(r['最大買枚数']<=2*q and r['最大売枚数']<=2*q,'E01行/上限')
    A.check(r['全会計合格'],'E01行/完結旗')
    if not r['親数']:A.check(r['収支']==r['利益']==r['損失']==r['費用']==0 and r['利益割合'] is None,'E01行/無活動成功なし')


def aggregate(rows: list[dict], saved: dict) -> dict:
    """
    機能: 33場の保存GLと勝負分母を再集計し、前後半・大勝ち依存も独立記述する。
    引数: rows(list[dict])、saved(dict)は同商品時系列小会計と根集計。
    返り値: dictは全場/活動中央値と上位3除外を分離した安定性。
    """
    p=sum(r['利益'] for r in rows);l=sum(r['損失'] for r in rows);nw=sum(r['勝ち親'] for r in rows);nl=sum(r['負け親'] for r in rows)
    total={k:sum(r[k] for r in rows) for k in ('利益','損失','収支','親数','勝ち親','負け親','零親','費用','新規枚数','勝ち枚数','負け枚数','零枚数')}
    total.update(PF=p/l if l else None,利益割合=p/(p+l) if p+l else None,平均利益=p/nw if nw else None,平均損失=l/nl if nl else None,平均損益比=(p/nw)/(l/nl) if nw and nl else None)
    active=[r for r in rows if r['親数']];wins=[r for r in rows if r['収支']>0];losses=[r for r in rows if r['収支']<0]
    best=sorted(wins,key=lambda r:(-r['収支'],r['session']))[:3]
    total.update(全場=33,活動場=len(active),黒字場=len(wins),赤字場=len(losses),無取引場=33-len(active),中央値=statistics.median(r['収支'] for r in rows),活動場中央値=statistics.median(r['収支'] for r in active) if active else None,上位3利益場除外収支=sum(r['収支'] for r in rows)-sum(r['収支'] for r in best),最大場損失=max(0.,max(-r['収支'] for r in rows)),全33黒字=len(wins)==33)
    for k,v in total.items():A.equal(saved[k],v,'E01集計/'+k if k not in ('平均利益','平均損失','平均損益比','PF','利益割合') else 'E01集計/average_'+k)
    total.update(前16収支=sum(r['収支'] for r in rows[:16]),後17収支=sum(r['収支'] for r in rows[16:]),後17赤字=sum(r['収支']<0 for r in rows[16:]),最悪場=min(rows,key=lambda r:r['収支'])['session'])
    return total


def fee(q: int, symbol: str) -> int:
    """
    機能: 独立Decimalで実注文ごとの料金を切り捨てる。
    引数: q(int)、symbol(str)は枚数と商品。
    返り値: intは円料金。複数UIDの残玉を合算しない。
    """
    return int((Decimal(q)*Decimal('41.8' if symbol=='TOPIX' else '11')).to_integral_value(rounding=ROUND_FLOOR))


def inspect_orders(out: dict, quotes: dict, symbol: str, compare: bool=True) -> tuple[dict,list[dict],dict]:
    """
    機能: 保存注文からUID FIFO・現金・残返済費込み全行曲線を独立に復元する。
    引数: out/quotes(dict)、symbol(str)、compare(bool)は台帳と物理quote、保存会計比較有無。
    返り値: tuple[dict,list,dict]は親会計、実部分返済、全行清算経路。未来玉テンプレート不使用。
    """
    orders=out['orders'];uids=out['order_uids'];targets=out.get('exit_target_uids',np.full(len(orders),-1,np.int64));n=len(quotes['bid']);m=1000 if symbol=='TOPIX' else 10
    valid=quotes['quote_valid']&np.isfinite(quotes['bid'])&np.isfinite(quotes['ask'])&(quotes['bid']>0)&(quotes['bid']<quotes['ask'])
    cash=np.zeros(n);hold=np.zeros(n,np.int64);charges=np.zeros(n,np.int64);reserve=np.zeros(n,np.int64);states={};parents={};legs=[];fees=[];lastrow=0
    for j,o in enumerate(orders):
        row,decision,cid,side,q,new=map(int,(o[0],o[1],o[2],o[3],o[4],o[7]));price=o[5];f=fee(q,symbol)
        A.check(0<=decision<row<n and valid[row] and side in (-1,1) and q>0,'E01注文/原行と同行禁止')
        A.check(price==quotes['ask' if side>0 else 'bid'][row],'E01注文/実BBO')
        A.check(row>=lastrow,'E01注文/時系列');reserve[lastrow:row]=sum(fee(v['remaining'],symbol) for v in states.values() if v['remaining']);lastrow=row
        cash[row]-=side*q*price*m+f;hold[row]+=side*q;charges[row]+=f;fees.append(f)
        parents.setdefault(cid,dict(net=0.,gross=0.,fees=0,quantity=0,side=side,entry=row,exit=row));parents[cid]['fees']+=f
        if new:
            uid=int(uids[j]);A.check(uid>=0 and uid not in states and int(targets[j])==-1,'E01新UID一意')
            states[uid]=dict(uid=uid,cid=cid,side=side,quantity=q,remaining=q,price=price,fee=f,row=row)
            parents[cid]['quantity']+=q
        else:
            A.check(uids[j]==-1,'E01返済UID区別');remaining=q
            for uid,v in states.items():
                if v['cid']!=cid or v['side']!=-side or not v['remaining'] or (targets[j]>=0 and uid!=targets[j]):continue
                amount=min(remaining,v['remaining']);gross=v['side']*amount*(price-v['price'])*m
                net=gross-v['fee']*amount/v['quantity']-f*amount/q
                legs.append(dict(uid=uid,parent=cid,side=v['side'],quantity=amount,net=net,gross=gross,entry=v['row'],exit=row));parents[cid]['gross']+=gross;parents[cid]['exit']=row
                v['remaining']-=amount;remaining-=amount
                if remaining==0:break
            A.check(remaining==0,'E01部分FIFO返済量')
    reserve[lastrow:]=sum(fee(v['remaining'],symbol) for v in states.values() if v['remaining'])
    cash=np.cumsum(cash);hold=np.cumsum(hold);paid=np.cumsum(charges);last=np.maximum.accumulate(np.where(valid,np.arange(n),-1));idx=np.maximum(last,0)
    equity=cash+hold*np.where(hold>=0,quotes['bid'][idx],quotes['ask'][idx])*m;liquidation=equity-reserve
    A.check(not hold[-1] and not reserve[-1] and all(v['remaining']==0 for v in states.values()),'E01終端flatUID')
    A.check(np.max(np.abs(hold),initial=0)<=(10 if symbol=='TOPIX' else 20),'E01全行保有上限')
    for cid,p in parents.items():p['net']=p['gross']-p['fees']
    if compare:
        np.testing.assert_array_equal(out['order_fees'],fees)
        for k,v in dict(equity_yen=equity,liquidation_yen=liquidation,reserved_exit_fees=reserve,long_qty=np.maximum(hold,0),short_qty=np.maximum(-hold,0)).items():
            if k not in out:
                A.check('curve_points' in out and k in ('liquidation_yen','reserved_exit_fees','long_qty','short_qty'),'旧対照未保存列を独立復元値と分離');continue
            actual=out[k];actual=A.expand(actual,n) if isinstance(actual,dict) else actual;np.testing.assert_allclose(actual,v,atol=1e-7,rtol=0);A.COUNT['E01独立全行/'+k]+=n
        expected=metric([p['net'] for p in parents.values()]);expected.update(費用=sum(fees),新規枚数=sum(p['quantity'] for p in parents.values()),勝ち枚数=sum(v['quantity'] for v in legs if v['net']>0),負け枚数=sum(v['quantity'] for v in legs if v['net']<0),零枚数=sum(v['quantity'] for v in legs if v['net']==0),注文件数=len(orders))
        for k,v in expected.items():A.equal(out['summary'][k],v,'E01現金/'+k if k not in ('PF','利益割合','平均利益','平均損失','平均損益比') else 'E01現金/average_'+k)
        stored={p['親']:p for p in out['parent']}
        for cid,p in parents.items():A.equal(stored[cid]['収支'],p['net'],'E01親現金');A.equal(stored[cid]['費用'],p['fees'],'E01親/fees')
    return parents,legs,dict(equity=equity,liquidation=liquidation,states=states,valid=valid)


def entry_gate(account: dict, out: dict, config: dict) -> None:
    """
    機能: 当時公開rowの票・物理初約定・影feed保持を保存資料だけで確認する。
    引数: account/out/config(dict)は一読入力・台帳・固定政策。
    返り値: None。非公開rowでの確認取消や保有終了を作らない。
    """
    feed=account['feed'];quotes=account['quotes'];record=account['record'];features=account['trade_features'][str(config['window_seconds'])];mapping=account['mapping']
    mask=np.ones(len(record['price']),bool);reason=np.zeros(len(mask),np.int32)
    for e in feed[feed[:,7]==1]:
        row=int(e[0]);v=features[row];known=v['known'];total=v['direction_votes']
        if v['reason']!=2:
            A.check(v['candidate_raw_row']==mapping[row] and v['candidate_raw_seq']==record['seq'][row],'E01票原seq/map')
            A.equal(v['candidate_price_time_s'],record['time_s'][row],'E01票時計')
        if config['mode']=='CONFIRM':allow=known and total>=2 and v['balance']>=.25
        else:allow=not(known and total>=2 and v['balance']<=-.25)
        mask[row]=allow;reason[row]=0 if allow else 100+v['reason'] if not known else 200 if total<2 else 201 if config['mode']=='CONFIRM' else 202
    for k,expected in (('gate_accepted',mask),('gate_reasons',reason)):
        actual=out[k];actual=A.expand(actual,len(mask)) if isinstance(actual,dict) else actual;np.testing.assert_array_equal(actual,expected)
    A.check(out['shadow_feed_SHA256']==account['paper_SHA256'],'E01影paper指紋')
    shadow=out['shadow_GU_orders'];valid=quotes['quote_valid']&np.isfinite(quotes['bid'])&np.isfinite(quotes['ask'])&(quotes['bid']>0)&(quotes['bid']<quotes['ask'])
    for o in shadow[shadow[:,7]==1]:
        row,decision,cid,side=map(int,(o[0],o[1],o[2],o[3]));A.check(mask[decision],'E01公開mask許可')
        e=feed[(feed[:,0]==decision)&(feed[:,2]==cid)&(feed[:,7]==1)];A.check(len(e)==1,'E01元公開一意');e=e[0]
        reached=valid.copy()
        if config['execution']=='D20':
            line=e[5]-side*.2*e[9];line=np.floor(line/record['tick']+1e-12)*record['tick'] if side>0 else np.ceil(line/record['tick']-1e-12)*record['tick']
            reached&=quotes['ask']<=line if side>0 else quotes['bid']>=line
        expected=decision+1+int(np.flatnonzero(reached[decision+1:])[0]);A.check(row==expected,'E01初公開後BBO到達')


def contribution(old: dict, new: dict) -> dict:
    """
    機能: 親cid集合から消えた損失・消えた利益・新增・共通の差を再計算する。
    引数: old/new(dict[int,dict])は同紙上親の実会計。
    返り値: dictは5寄与。拒否原因の予測成功とは同義でない。
    """
    removed=set(old)-set(new);added=set(new)-set(old);both=set(old)&set(new)
    return dict(収支変化=sum(p['net'] for p in new.values())-sum(p['net'] for p in old.values()),避けた基準損失=sum(-old[k]['net'] for k in removed if old[k]['net']<0),失った基準利益=sum(old[k]['net'] for k in removed if old[k]['net']>0),共通入口の出口変化=sum(new[k]['net']-old[k]['net'] for k in both),新たな入口の収支=sum(new[k]['net'] for k in added))


def main() -> None:
    """
    機能: 根完了後に1650小会計全数と固定抽出UID台帳を一回監査する。
    引数: なし。金融・NPZ・現在場APIを呼ばない。
    返り値: Noneは独立証跡。全1650保存台帳検査とは呼ばない。
    """
    target=HERE/'e01_trade_全24小会計と抽出UID及び停止接頭の独立監査.json';A.check(not target.exists(),'E01同監査なし')
    results=A.read_json(SOURCE/'finance/結果.json');fixed=A.read_json(SOURCE/'金融事前固定.json');meta=A.read_json(SOURCE/'全33場のE01取引更新準備.json')
    source={p:A.sha(ROOT/p) for p in fixed['実装SHA256']};A.check(source==fixed['実装SHA256'],'E01固定源')
    A.check(results['全合格'] and results['新gateengine']==792 and results['新政策会計']==1584 and results['新基準政策会計']==66 and results['合計会計']==1650,'E01実会計分離')
    A.check(results['元paper再計算']==results['旧engine再生']==results['原book']==results['API']==0,'E01根再生範囲')
    plan=A.read_json(SOURCE/'試行計画.json')
    A.check(results['configs']==plan['spec']['entry']['conditions'] and results['sessions']==meta['sessions']==plan['spec']['data']['sessions'],'E01全条件場不変')
    for b in fixed['基準'].values():A.check(A.sha(ROOT/b['source']['path'])==b['source']['sha256'],'E01旧小会計指紋')
    sessions=results['sessions'];configs={c['id']:c for c in results['configs']};rows={};stability={};samples=set();ledgers={}
    for ident,case in results['results'].items():
        A.check(len(case['rows'])==66 and len({(r['session'],r['symbol']) for r in case['rows']})==66,'E01全行一意');stability[ident]={}
        ledgers[ident]={(p['session'],p['symbol']):p for p in case['ledgers']}
        for symbol in ('TOPIX','NK225'):
            rr=[r for r in case['rows'] if r['symbol']==symbol];A.check([r['session'] for r in rr]==sessions,'E01場順序')
            for r in rr:row_check(r,5 if symbol=='TOPIX' else 10);rows[ident,r['session'],symbol]=r
            stability[ident][symbol]=aggregate(rr,case['symbols'][symbol]);active=[r for r in rr if r['親数']]
            if active:samples.add((ident,active[0]['session'],symbol))
            if ident in SPECIAL:samples.update((ident,r['session'],symbol) for r in rr if r['収支']<0)
    for symbol in ('TOPIX','NK225'):
        rr=[r for r in results['new_D0_P1L8']['rows'] if r['symbol']==symbol]
        for r in rr:row_check(r,5 if symbol=='TOPIX' else 10)
        aggregate(rr,results['new_D0_P1L8']['symbols'][symbol])
    planpath=HERE/'e01_trade_独立保存監査の抽出計画.json';plan=dict(抽出=[list(v) for v in sorted(samples)],規則='各24政策商品初活動場＋W60 VETO/CONFIRM D0 P1L8の全赤字場',小会計=1650,packet上限=33,金融再生=0,NPZ=0)
    if planpath.exists():A.check(A.read_json(planpath)==plan,'E01保存抽出計画不変')
    else:planpath.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    base_rows={k:{(r['session'],r['symbol']):r for r in v['rows']} for k,v in fixed['基準'].items()};base_rows['D0_P1L8']={(r['session'],r['symbol']):r for r in results['new_D0_P1L8']['rows']}
    all_delta={i:{s:defaultdict(float) for s in ('TOPIX','NK225')} for i in configs}
    for ident,c in configs.items():
        for d in results['各場寄与'][ident]:
            symbol=d['symbol'];base=base_rows[c['execution']+'_'+c['exit']][d['session'],symbol]
            A.equal(d['収支変化'],rows[ident,d['session'],symbol]['収支']-base['収支'],'E01全行基準差');A.equal(d['収支変化'],d['避けた基準損失']-d['失った基準利益']+d['共通入口の出口変化']+d['新たな入口の収支'],'E01全行5寄与')
            for k in FIELDS:all_delta[ident][symbol][k]+=d[k]
        for symbol in ('TOPIX','NK225'):
            for k in FIELDS:A.equal(all_delta[ident][symbol][k],results['diagnosis'][ident][symbol][k],'E01全33寄与和')
    reads={};inputs={};checked=[];causes={};observed_schemas={};newbase={(p['session'],p['symbol']):p for p in results['new_D0_P1L8']['ledgers']}
    for session in sessions:
        selected=[v for v in sorted(samples) if v[1]==session]
        if not selected:continue
        packet=A.unpack(meta['cache'][session],inputs);basecache={}
        for ident,_,symbol in selected:
            c=configs[ident];a=packet['accounts'][symbol];out=A.unpack(ledgers[ident][session,symbol],reads);parents,legs,path=inspect_orders(out,a['quotes'],symbol);entry_gate(a,out,c)
            if c['exit']=='P1L8':
                shadow=dict(orders=out['shadow_GU_orders'],order_uids=out['shadow_GU_uids']);_,_,shadowpath=inspect_orders(shadow,a['quotes'],symbol,False)
                unit=(.5 if symbol=='TOPIX' else 10)*(5 if symbol=='TOPIX' else 10)*(1000 if symbol=='TOPIX' else 10);hit=shadowpath['valid']&((shadowpath['liquidation']>=unit)|(shadowpath['liquidation']<=-8*unit));first=np.flatnonzero(hit)
                control=out['control'];A.check(control['発動']==bool(len(first)),'E01停止当時発動')
                if len(first):
                    row=int(first[0]);A.check(control['判断行']==row,'E01停止先着行');prefix=shadow['orders'][:,0]<=row;np.testing.assert_array_equal(out['orders'][:prefix.sum()],shadow['orders'][prefix]);np.testing.assert_array_equal(out['order_uids'][:prefix.sum()],shadow['order_uids'][prefix])
                    A.check(not np.any(out['orders'][(out['orders'][:,0]>row)&(out['orders'][:,7]==1)]),'E01停止後新規0')
                    np.testing.assert_allclose(path['liquidation'][:row+1],shadowpath['liquidation'][:row+1],atol=1e-7,rtol=0)
                    A.equal(control['判断時清算利益'],shadowpath['liquidation'][row],'E01停止時価')
                    remaining=out['orders'][prefix.sum():]
                    if len(remaining):
                        nextquote=row+1+int(np.flatnonzero(path['valid'][row+1:])[0]);A.check(np.all(remaining[:,0]==nextquote) and np.all(remaining[:,1]==row),'E01残UID次quote清算')
            key=c['execution']+'_'+c['exit']
            if (key,symbol) not in basecache:
                item=newbase[session,symbol] if key=='D0_P1L8' else fixed['基準'][key]['ledgers'][session+'|'+symbol]
                old=A.unpack(item,reads);observed_schemas.setdefault(key,sorted(old.keys()));basecache[key,symbol]=inspect_orders(old,a['quotes'],symbol)[0];del old
            delta=contribution(basecache[key,symbol],parents);d=next(d for d in results['各場寄与'][ident] if d['session']==session and d['symbol']==symbol)
            for k in FIELDS:A.equal(d[k],delta[k],'E01抽出実親5寄与')
            checked.append(dict(id=ident,session=session,symbol=symbol,orders=len(out['orders']),parents=len(parents),fees=out['summary']['費用'],SHA256=ledgers[ident][session,symbol]['SHA256']))
            if ident in SPECIAL and rows[ident,session,symbol]['収支']<0:
                control=out['control'];causes.setdefault(ident,{}).setdefault(symbol,[]).append(dict(session=session,収支=rows[ident,session,symbol]['収支'],停止=control,最初負親=next((dict(parent=k,**p) for k,p in parents.items() if p['net']<0),None),最大負親=dict(parent=min(parents,key=lambda k:parents[k]['net']),**min(parents.values(),key=lambda p:p['net'])) if parents else None,寄与=delta))
            del out
        del packet
        print(session+'：E01抽出UID・停止接頭・影GUを独立検算',flush=True)
    A.check(len(inputs)<=33,'E01入力上限');A.check(source=={p:A.sha(ROOT/p) for p in source},'E01source終端一致')
    proof=dict(全合格=True,scope='全24×33×2小会計1584＋新D0P1L8基準66。事前抽出実台帳のUID/部分FIFO/料/密曲線/元影GU/停止接頭。全1650保存台帳検査とは称さない。',小会計=1650,新gateengine=792,旧基準の実保存keys=observed_schemas,抽出実台帳=len(checked),検査数=dict(A.COUNT),検査合計=sum(A.COUNT.values()),抽出計画SHA256=A.sha(planpath),安定性=stability,二政策全赤字場=causes,全33寄与=all_delta,検算台帳=checked,入力読取=dict(packet=len(inputs),保存台帳=len(reads),NPZ=0,現Night=0,API=0),金融再生=0,source_SHA256=source,source開始終端一致=True,入力SHA256={**inputs,**reads},レビューsource_SHA256=A.sha(Path(__file__)),正本SHA256=A.sha(SOURCE/'finance/結果.json'),制約=['影GUのlimit_events/execution_events/execution_statesに停止後の予約が残ってもactual注文/UID/費用/持株として数えない。','旧reference対照のliquidation_yen/残返済料/long_qty/short_qtyは未保存。実注文から独立復元し、旧equity_yen/parent/料だけ保存値へ照合。','保存原票と原seq/map・公開maskを検算。原NPZから票方向を再生成せず上流独立人工へ委譲。','全33既知比較。小利益policyの勝場数と総金額PF・大勝ち除外は別。','BBO全枚約定はラージによる代理、queue順や実到着時間を保証しない。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8');print('E01保存独立監査合格',len(checked),sum(A.COUNT.values()),flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        p=HERE/'e01_trade_独立保存監査のFalse_旧対照schema分離後.json';assert not p.exists();p.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),検査件数=dict(A.COUNT),金融再生=0,NPZ=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8');raise
