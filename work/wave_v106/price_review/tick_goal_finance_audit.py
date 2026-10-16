"""純目標6の小会計・利確判断後の赤字化全数と最大悪化UIDを独立に照合する。"""

from collections import defaultdict
from pathlib import Path
import json
import traceback

import numpy as np

import range_finance_audit as A
import e01_trade_finance_audit as M
from budget_finance_audit import prefix_uid


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_tick_net_goal'


def policy_check(gu: dict, out: dict, quotes: dict, config: dict, symbol: str) -> dict:
    """
    機能: 純目標の初先着と次正常quote残UID返済を実GU接頭から独立に検算する。
    引数: gu/out/quotes/config(dict)、symbol(str)は保存基準と当時気配。
    返り値: dictは判断/返済の原seq・気配・各UIDと料金の具体例。再生なし。
    """
    _,_,path=M.inspect_orders(gu,quotes,symbol);unit=(.5 if symbol=='TOPIX' else 10)*(5 if symbol=='TOPIX' else 10)*(1000 if symbol=='TOPIX' else 10)
    goal=unit-2*M.fee(5 if symbol=='TOPIX' else 10,symbol);loss=config['loss_ticks']*unit
    A.equal(config['goal_yen'][symbol],goal,'純目標固定額')
    hits=path['valid']&((path['liquidation']>=goal)|(path['liquidation']<=-loss));positions=np.flatnonzero(hits);control=out['control']
    A.check(control['発動']==bool(len(positions)),'純目標先着発動')
    if not len(positions):np.testing.assert_array_equal(out['orders'],gu['orders']);return dict(発動=False)
    row=int(positions[0]);profit=path['liquidation'][row]>=goal;A.check(control['判断行']==row and control['種別']==('利益目標' if profit else '損失予算'),'純目標初先着row')
    A.equal(control['判断時清算利益'],path['liquidation'][row],'純目標当時清算')
    A.check(control['判断原seq']==quotes['seq'][row],'純目標判断原seq')
    prefix=gu['orders'][:,0]<=row;original=gu['orders'][prefix];uids=gu['order_uids'][prefix]
    np.testing.assert_array_equal(out['orders'][:len(original)],original);np.testing.assert_array_equal(out['order_uids'][:len(original)],uids)
    remaining=prefix_uid(original,uids,row);suffix=out['orders'][len(original):];A.check(len(suffix)==len(remaining),'純目標残UID別')
    fill=row if not remaining else row+1+int(np.flatnonzero(path['valid'][row+1:])[0]);A.check(control['返済行']==fill and control['返済原seq']==quotes['seq'][fill],'純目標次正常原行')
    uid_details=[]
    for j,(o,v) in enumerate(zip(suffix,remaining)):
        side=-v['side'];price=quotes['ask' if side>0 else 'bid'][fill]
        np.testing.assert_array_equal(o,np.array([fill,row,v['cid'],side,v['q'],price,94 if profit else 95,0],float))
        A.check(out['exit_target_uids'][len(original)+j]==v['uid'],'純目標残targetUID')
        uid_details.append(dict(uid=v['uid'],親=v['cid'],保有方向=v['side'],残枚数=v['q'],実返済価格=float(price),当該返済料=M.fee(v['q'],symbol)))
    A.check(not np.any(out['orders'][(out['orders'][:,0]>row)&(out['orders'][:,7]==1)]),'純目標停止後新規0')
    A.equal(control['実返済後収支'],out['summary']['収支'],'純目標実収支');A.equal(control['判断から返済の悪化'],out['summary']['収支']-path['liquidation'][row],'純目標実悪化')
    return dict(発動=True,種類=control['種別'],判断時刻=A.iso(quotes['time_s'][row]),返済時刻=A.iso(quotes['time_s'][fill]),判断原seq=int(quotes['seq'][row]),返済原seq=int(quotes['seq'][fill]),判断bid=float(quotes['bid'][row]),判断ask=float(quotes['ask'][row]),返済bid=float(quotes['bid'][fill]),返済ask=float(quotes['ask'][fill]),目標=float(goal),判断清算=float(path['liquidation'][row]),実収支=out['summary']['収支'],判断から変化=control['判断から返済の悪化'],残UID=uid_details)


def main() -> None:
    """
    機能: 全6小会計396・利確発動後結果全数と固定抽出UID台帳を一回検算する。
    引数: なし。新金融/原NPZ/現在APIを呼ばない。
    返り値: Noneは保存独立証跡。全396実台帳の監査とは称さない。
    """
    target=HERE/'tick_goal_全6小会計と利確後悪化及びUIDの独立監査.json';A.check(not target.exists(),'純目標再監査なし')
    s=A.read_json(SOURCE/'finance/結果.json');fixed=A.read_json(SOURCE/'金融前の固定.json');plan=A.read_json(SOURCE/'試行計画.json')
    before={p:A.sha(ROOT/p) for p in fixed['source_SHA256']};A.check(before==fixed['source_SHA256']==s['source_SHA256'],'純目標固定源')
    A.check(s['全合格'] and s['configs']==fixed['configs']==plan['spec']['entry']['conditions'] and s['新政策会計']==396,'純目標全配置数')
    A.check(s['read_counts']==dict(input一読=33,GU一読=132,比較一読=264,新政策会計=396),'純目標根読取数')
    A.check(s['engine再生']==s['元paper再計算']==s['原NPZ読取']==s['現在snapshot読取']==s['原book読取']==s['API取得']==0,'純目標根禁止範囲')
    configs={c['id']:c for c in s['configs']};rows={};ledgers={};samples=set();stability={};profitstats={};worst={};deltas={i:{b:{m:defaultdict(float) for m in ('TOPIX','NK225')} for b in ('P1L8','P1L4')} for i in configs}
    for ident,c in configs.items():
        v=s['results'][ident];A.check(len(v['rows'])==66 and len({(r['session'],r['symbol']) for r in v['rows']})==66,'純目標全行一意');stability[ident]={};profitstats[ident]={};ledgers[ident]={(p['session'],p['symbol']):p for p in v['ledgers']}
        for symbol in ('TOPIX','NK225'):
            rr=[r for r in v['rows'] if r['symbol']==symbol]
            for r in rr:M.row_check(r,5 if symbol=='TOPIX' else 10);rows[ident,r['session'],symbol]=r
            stability[ident][symbol]=M.aggregate(rr,v['symbols'][symbol]);active=[r for r in rr if r['親数']]
            if active:samples.add((ident,active[0]['session'],symbol))
            ds=[d for d in s['各場寄与'][ident] if d['symbol']==symbol];prof=[]
            for d in ds:
                co=d['control'];r=rows[ident,d['session'],symbol]
                if co['発動']:
                    A.equal(co['実返済後収支'],r['収支'],'純目標全件control収支');A.equal(co['判断から返済の悪化'],r['収支']-co['判断時清算利益'],'純目標全件control差')
                    if co['種別']=='利益目標':
                        A.check(co['判断時清算利益']>=c['goal_yen'][symbol],'純目標全件profit到達');prof.append(co)
                        candidate=(-co['判断から返済の悪化'],ident,d['session'],symbol)
                        if symbol not in worst or candidate[0]>worst[symbol][0] or (candidate[0]==worst[symbol][0] and candidate[1:3]<worst[symbol][1:3]):worst[symbol]=candidate
                for base in ('P1L8','P1L4'):
                    b=next(r for r in fixed['modes'][c['mode']]['comparisons'][base]['rows'] if r['session']==d['session'] and r['symbol']==symbol);delta=d['comparisons'][base]
                    A.equal(delta['収支変化'],r['収支']-b['収支'],'純目標全件基準差');A.equal(delta['収支変化'],delta['避けた基準損失']-delta['失った基準利益']+delta['共通入口の出口変化']+delta['新たな入口の収支'],'純目標全件5寄与')
                    for k in M.FIELDS:deltas[ident][base][symbol][k]+=delta[k]
            profitstats[ident][symbol]=dict(全場=33,利益目標発動=len(prof),発動後赤字=sum(c['実返済後収支']<0 for c in prof),発動後零=sum(c['実返済後収支']==0 for c in prof),発動後黒字=sum(c['実返済後収支']>0 for c in prof),発動後目標未達=sum(c['実返済後収支']<c['目標'] for c in prof),悪化件数=sum(c['判断から返済の悪化']<0 for c in prof),判断から変化合計=sum(c['判断から返済の悪化'] for c in prof),悪化総額=sum(max(-c['判断から返済の悪化'],0) for c in prof),最大悪化=max([0.]+[-c['判断から返済の悪化'] for c in prof]))
        for base in ('P1L8','P1L4'):
            for symbol in ('TOPIX','NK225'):
                for k in M.FIELDS:A.equal(deltas[ident][base][symbol][k],s['diagnosis'][ident][base][symbol][k],'純目標全33寄与')
    for _,ident,session,symbol in worst.values():samples.add((ident,session,symbol))
    p=HERE/'tick_goal_独立保存監査の事前抽出計画.json';A.check(not p.exists(),'純目標抽出新規');p.write_text(json.dumps(dict(抽出=[list(v) for v in sorted(samples)],規則='各6条件商品初活動場＋商品別利益目標発動後最大悪化。同額時ID/場辞書順、input読取前固定。',最大悪化=worst,小会計=396,NPZ=0,金融再生=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    reads={};inputs={};checked=[];specific=[]
    for session in s['sessions']:
        selected=[v for v in sorted(samples) if v[1]==session]
        if not selected:continue
        packet=A.unpack(fixed['input_cache'][session],inputs);cache={}
        for ident,_,symbol in selected:
            c=configs[ident];quotes=packet['accounts'][symbol]['quotes'];b=fixed['modes'][c['mode']];key=session+'|'+symbol
            for label,item in [('GU',b['GU_ledgers'][key])]+[(label,b['comparisons'][label]['ledgers'][key]) for label in ('P1L8','P1L4')]:
                token=c['mode'],symbol,label
                if token not in cache:cache[token]=A.unpack(item,reads)
            out=A.unpack(ledgers[ident][session,symbol],reads);parents=M.inspect_orders(out,quotes,symbol)[0];diag=policy_check(cache[c['mode'],symbol,'GU'],out,quotes,c,symbol)
            for label in ('P1L8','P1L4'):
                old=M.inspect_orders(cache[c['mode'],symbol,label],quotes,symbol)[0];delta=M.contribution(old,parents);d=next(d for d in s['各場寄与'][ident] if d['session']==session and d['symbol']==symbol)['comparisons'][label]
                for k in M.FIELDS:A.equal(d[k],delta[k],'純目標抽出独立5寄与')
                expected={(k,old[k]['net'],parents[k]['net']) for k in old.keys()&parents.keys() if old[k]['net']>0 and parents[k]['net']<0}
                A.check(expected=={(v['parent'],v['base_net'],v['new_net']) for v in d['元勝ち親が赤字化']},'純目標抽出勝ち赤字化')
            diag.update(id=ident,session=session,symbol=symbol,最大悪化選定=(symbol in worst and ident==worst[symbol][1] and session==worst[symbol][2]),費用=out['summary']['費用']);specific.append(diag)
            checked.append(dict(id=ident,session=session,symbol=symbol,orders=len(out['orders']),parents=len(parents),SHA256=ledgers[ident][session,symbol]['SHA256']))
        del packet,cache
        print(session+'：純目標後の気配戻りと残UIDを独立検算',flush=True)
    A.check(before=={p:A.sha(ROOT/p) for p in before},'純目標source終端一致')
    proof=dict(全合格=True,scope='全6×33×2小会計396/2対照5寄与/全利益目標control集計、固定抽出UID・次quote検算。全396実台帳監査とは称さない。',小会計=396,安定性=stability,利益目標発動後の全数統計=profitstats,最大悪化選定=worst,抽出実例=specific,全33寄与=deltas,抽出実台帳=len(checked),検算台帳=checked,検査数=dict(A.COUNT),検査合計=sum(A.COUNT.values()),抽出計画SHA256=A.sha(p),入力読取=dict(packet=len(inputs),保存台帳=len(reads),原NPZ=0,現在API=0),新金融再生=0,source_SHA256=before,source開始終端一致=True,入力SHA256={**inputs,**reads},レビューsource_SHA256=A.sha(Path(__file__)),正本SHA256=A.sha(SOURCE/'finance/結果.json'),制約=['発動後赤字化は固定目標で一旦判断した後の次q悪化。実quoteを戻し変更した金融は再生しない。','場全体目標で各親1tick利確と同義でない。UID別floorと過去親損益を含む。','全33既知比較、同条件両商品安定性と商品別観測を分ける。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8');print('純目標6保存独立監査合格',len(checked),sum(A.COUNT.values()),flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        p=HERE/'tick_goal_独立保存監査のFalse.json';assert not p.exists();p.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),検査件数=dict(A.COUNT),新金融再生=0,NPZ=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8');raise
