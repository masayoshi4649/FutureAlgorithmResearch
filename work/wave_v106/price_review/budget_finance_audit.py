"""停止予算18の全小会計と固定抽出UID、L2即停止・勝ち赤字化を独立検算する。"""

from collections import defaultdict
from pathlib import Path
import json
import traceback

import numpy as np

import range_finance_audit as A
import e01_trade_finance_audit as M


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_trade_budget'


def prefix_uid(orders: np.ndarray, uids: np.ndarray, row: int) -> list[dict]:
    """
    機能: 閾値判断行以下の実注文だけから残UIDと数量を独立に復元する。
    引数: orders/uids(ndarray)、row(int)は元GU実注文と当時判断行。
    返り値: list[dict]は残玉。元の将来返済や玉配列は使わない。
    """
    held={}
    for i,o in enumerate(orders):
        if o[0]>row:break
        cid,side,q,new=map(int,(o[2],o[3],o[4],o[7]))
        if new:held[int(uids[i])]=dict(uid=int(uids[i]),cid=cid,side=side,q=q)
        else:
            left=q
            for v in held.values():
                if v['cid']!=cid or v['side']!=-side or v['q']==0:continue
                amount=min(left,v['q']);v['q']-=amount;left-=amount
                if not left:break
            A.check(left==0,'予算接頭UID返済量')
    return [v for v in held.values() if v['q']]


def policy_check(gu: dict, out: dict, quotes: dict, c: dict, symbol: str) -> dict:
    """
    機能: 旧GU当時清算の初閾値と次quote残UID返済・停止後新規0を独立に照合する。
    引数: gu/out/quotes/c(dict)、symbol(str)は保存基準と新政策。
    返り値: dictは停止時点の原seq・価格・spread・料の事後診断。金融再生なし。
    """
    _,_,path=M.inspect_orders(gu,quotes,symbol);unit=(.5 if symbol=='TOPIX' else 10)*(5 if symbol=='TOPIX' else 10)*(1000 if symbol=='TOPIX' else 10)
    profit=c['profit_ticks']*unit;loss=c['loss_ticks']*unit
    hit=path['valid']&((path['liquidation']>=profit)|(path['liquidation']<=-loss));indices=np.flatnonzero(hit);control=out['control']
    A.check(control['発動']==bool(len(indices)),'予算初閾値発動');A.equal(control['目標'],profit,'予算利益幅');A.equal(control['損失予算'],loss,'予算損失幅')
    if not len(indices):
        np.testing.assert_array_equal(out['orders'],gu['orders']);np.testing.assert_array_equal(out['order_uids'],gu['order_uids']);return dict(発動=False)
    row=int(indices[0]);profit_hit=path['liquidation'][row]>=profit;expected_kind='利益目標' if profit_hit else '損失予算'
    A.check(control['判断行']==row and control['種別']==expected_kind,'予算先着と種類')
    A.check(control['判断原seq']==quotes['seq'][row],'予算判断原seq');A.equal(control['判断価格時計'],quotes['time_s'][row],'予算判断時計')
    A.equal(control['判断時清算利益'],path['liquidation'][row],'予算判断純清算')
    prefix=gu['orders'][:,0]<=row;original=gu['orders'][prefix];uids=gu['order_uids'][prefix]
    np.testing.assert_array_equal(out['orders'][:len(original)],original);np.testing.assert_array_equal(out['order_uids'][:len(original)],uids)
    A.check(control['元接頭注文件数']==len(original),'予算保持接頭数')
    remaining=prefix_uid(original,uids,row);suffix=out['orders'][len(original):]
    A.check(len(suffix)==len(remaining)==control['残UID別注文数'],'予算残UID別数')
    fill=row if not remaining else row+1+int(np.flatnonzero(path['valid'][row+1:])[0])
    A.check(control['返済行']==fill and control['返済原seq']==quotes['seq'][fill],'予算次正常清算原行')
    for j,(o,v) in enumerate(zip(suffix,remaining)):
        side=-v['side'];price=quotes['ask' if side>0 else 'bid'][fill]
        A.check(np.array_equal(o,np.array([fill,row,v['cid'],side,v['q'],price,94 if profit_hit else 95,0],float)),'予算残UID実注文exact')
        A.check(out['order_uids'][len(original)+j]==-1 and out['exit_target_uids'][len(original)+j]==v['uid'],'予算返済targetUID')
    A.check(not np.any(out['orders'][(out['orders'][:,0]>row)&(out['orders'][:,7]==1)]),'予算停止後新規0')
    A.equal(control['実返済後収支'],out['summary']['収支'],'予算実返済net');A.equal(control['判断から返済の悪化'],out['summary']['収支']-path['liquidation'][row],'予算次quote悪化')
    first_new=original[original[:,7]==1]
    immediate=len(first_new)==1 and first_new[0,0]==row and len(original)==1
    diagnostic=dict(発動=True,種別=expected_kind,判断行=row,判断時刻=A.iso(quotes['time_s'][row]),返済時刻=A.iso(quotes['time_s'][fill]),判断原seq=int(quotes['seq'][row]),返済原seq=int(quotes['seq'][fill]),入口直後停止=bool(immediate),当時気配差=float(quotes['ask'][row]-quotes['bid'][row]),判断清算=float(path['liquidation'][row]),実収支=out['summary']['収支'],次quote悪化=control['判断から返済の悪化'])
    if immediate:
        o=original[0];symbolq=int(o[4]);diagnostic.update(入口=float(o[5]),方向=int(o[3]),気配差負担=float((quotes['ask'][row]-quotes['bid'][row])*symbolq*(1000 if symbol=='TOPIX' else 10)),往復料=2*M.fee(symbolq,symbol))
    return diagnostic


def main() -> None:
    """
    機能: 正式18完了後の小会計全数と事前抽出保存台帳を再生なしで一回監査する。
    引数: なし。原NPZ/現在場/API/engineを呼ばない。
    返り値: Noneは独立監査証跡。全1056新台帳会計監査とは称さない。
    """
    target=HERE/'budget_全18小会計と抽出停止UIDの独立監査.json';A.check(not target.exists(),'予算再監査なし')
    s=A.read_json(SOURCE/'finance/結果.json');fixed=A.read_json(SOURCE/'金融前の固定.json');plan=A.read_json(SOURCE/'試行計画.json')
    before={p:A.sha(ROOT/p) for p in fixed['source_SHA256']};A.check(before==fixed['source_SHA256']==s['source_SHA256'],'予算固定source')
    A.check(s['configs']==fixed['configs']==plan['spec']['entry']['conditions'] and s['sessions']==fixed['sessions'],'予算条件場不変')
    A.check(s['全合格'] and s['新政策会計']==1056 and s['read_counts']=={'保存input一読':33,'保存GU一読':132,'P1L8保存比較一読':132,'新政策会計':1056,'保存P1L8再利用':132},'予算根実新再利用件数')
    A.check(s['engine再生']==s['原NPZ読取']==s['現在snapshot読取']==s['原book読取']==s['API取得']==s['元paper再計算']==0,'予算禁止範囲')
    configs={c['id']:c for c in s['configs']};rows={};ledgers={};stability={};samples=set();immediate_candidates=[];turned_candidates=[];all_diff={i:{m:defaultdict(float) for m in ('TOPIX','NK225')} for i in configs}
    for ident,c in configs.items():
        v=s['results'][ident];A.check(len(v['rows'])==66 and len({(r['session'],r['symbol']) for r in v['rows']})==66,'予算全行一意');stability[ident]={};ledgers[ident]={(l['session'],l['symbol']):l for l in v['ledgers']}
        base={(r['session'],r['symbol']):r for r in fixed['modes'][c['mode']]['baseline_rows']}
        for symbol in ('TOPIX','NK225'):
            rr=[r for r in v['rows'] if r['symbol']==symbol];A.check([r['session'] for r in rr]==s['sessions'],'予算場順')
            for r in rr:M.row_check(r,5 if symbol=='TOPIX' else 10);rows[ident,r['session'],symbol]=r
            stability[ident][symbol]=M.aggregate(rr,v['symbols'][symbol]);A.equal(v['symbols'][symbol]['活動黒字率'],sum(r['収支']>0 for r in rr)/sum(r['親数']>0 for r in rr) if any(r['親数'] for r in rr) else None,'予算集計/rate')
            A.equal(v['symbols'][symbol]['注文件数'],sum(r['注文件数'] for r in rr),'予算集計注文数')
            active=[r for r in rr if r['親数']]
            if active:samples.add((ident,active[0]['session'],symbol));samples.add((ident,min(active,key=lambda r:(r['収支'],r['session']))['session'],symbol))
        for d in s['各場寄与'][ident]:
            symbol=d['symbol'];r=rows[ident,d['session'],symbol];b=base[d['session'],symbol]
            A.equal(d['収支変化'],r['収支']-b['収支'],'予算全行基準差');A.equal(d['収支変化'],d['避けた基準損失']-d['失った基準利益']+d['共通入口の出口変化']+d['新たな入口の収支'],'予算全行5寄与')
            for k in M.FIELDS:all_diff[ident][symbol][k]+=d[k]
            if c['saved_alias']:
                A.check(r==b,'予算alias小会計exact');A.check(ledgers[ident][d['session'],symbol]['saved_alias'] and all(d[k]==0 for k in M.FIELDS),'予算aliasは新改善なし')
            if c['profit_ticks']==1 and c['loss_ticks']==2 and d['control']['発動'] and d['control']['種別']=='損失予算' and d['control']['元接頭注文件数']==1:immediate_candidates.append((ident,d['session'],symbol))
            for t in d['元勝ち親が赤字化']:turned_candidates.append((symbol,t['base_net'],ident,d['session'],t['parent']))
        for symbol in ('TOPIX','NK225'):
            for k in M.FIELDS:A.equal(all_diff[ident][symbol][k],s['diagnosis'][ident][symbol][k],'予算全33寄与和')
            for kind in ('元勝ち親が赤字化','元負け親が黒字化'):A.equal(s['diagnosis'][ident][symbol][kind],sum(len(d[kind]) for d in s['各場寄与'][ident] if d['symbol']==symbol),'予算親反証件数')
    for mode in ('CONFIRM','VETO'):
        for symbol in ('TOPIX','NK225'):
            candidate=next((v for v in immediate_candidates if configs[v[0]]['mode']==mode and v[2]==symbol),None)
            if candidate:samples.add(candidate)
    winner_counter={}
    for symbol in ('TOPIX','NK225'):
        candidates=[v for v in turned_candidates if v[0]==symbol]
        if candidates:
            choice=max(candidates,key=lambda v:(v[1],v[2],v[3]));winner_counter[symbol]=choice;samples.add((choice[2],choice[3],symbol))
    p=HERE/'budget_独立保存監査の事前抽出計画.json';A.check(not p.exists(),'予算抽出計画新規');p.write_text(json.dumps(dict(抽出=[list(v) for v in sorted(samples)],規則='各18条件商品初活動＋最悪活動場、P1L2 mode/商品初の損失発動・接頭1注文、商品別元勝ち赤字化最大基準利益例。入力を読む前に選定。',最大勝ち赤字化=winner_counter,小会計1188=True,新金融1056=True,alias132=True,NPZ=0,engine再生=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    reads={};inputs={};checked=[];diagnosis=[]
    for session in s['sessions']:
        selected=[v for v in sorted(samples) if v[1]==session]
        if not selected:continue
        packet=A.unpack(fixed['input_cache'][session],inputs);cache={}
        for ident,_,symbol in selected:
            c=configs[ident];a=packet['accounts'][symbol];quotes=a['quotes'];binding=fixed['modes'][c['mode']];key=session+'|'+symbol
            for label,items in (('GU',binding['GU_ledgers']),('BASE',binding['baseline_ledgers'])):
                token=c['mode'],symbol,label
                if token not in cache:cache[token]=A.unpack(items[key],reads)
            gu=cache[c['mode'],symbol,'GU'];base=cache[c['mode'],symbol,'BASE']
            out=base if c['saved_alias'] else A.unpack(ledgers[ident][session,symbol],reads)
            parents,_,_=M.inspect_orders(out,quotes,symbol);oldparents=M.inspect_orders(base,quotes,symbol)[0]
            diag=policy_check(gu,out,quotes,c,symbol);d=M.contribution(oldparents,parents);saved=next(v for v in s['各場寄与'][ident] if v['session']==session and v['symbol']==symbol)
            for k in M.FIELDS:A.equal(saved[k],d[k],'予算抽出独立寄与')
            expected={(k,oldparents[k]['net'],parents[k]['net']) for k in oldparents.keys()&parents.keys() if oldparents[k]['net']>0 and parents[k]['net']<0}
            A.check(expected=={(v['parent'],v['base_net'],v['new_net']) for v in saved['元勝ち親が赤字化']},'予算勝ち赤字化実親')
            diag.update(id=ident,session=session,symbol=symbol,実収支=out['summary']['収支'],費用=out['summary']['費用'],元勝ち赤字化=saved['元勝ち親が赤字化'],親数=len(parents));diagnosis.append(diag)
            if symbol in winner_counter and ident==winner_counter[symbol][2] and session==winner_counter[symbol][3]:
                cid=winner_counter[symbol][4];t=parents[cid];o=out['orders'][(out['orders'][:,2]==cid)&(out['orders'][:,7]==1)][0];e=out['orders'][(out['orders'][:,2]==cid)&(out['orders'][:,7]==0)][-1]
                diag['最大失った勝ち実例']=dict(parent=cid,元P1L8=oldparents[cid]['net'],新政策=t['net'],入口原seq=int(quotes['seq'][int(o[0])]),入口時刻=A.iso(quotes['time_s'][int(o[0])]),入口価格=float(o[5]),返済原seq=int(quotes['seq'][int(e[0])]),返済時刻=A.iso(quotes['time_s'][int(e[0])]),返済価格=float(e[5]))
            checked.append(dict(id=ident,session=session,symbol=symbol,parents=len(parents),orders=len(out['orders']),saved_alias=c['saved_alias']))
        del packet,cache
        print(session+'：停止予算のUID接頭と失った勝ちを検算',flush=True)
    A.check(len(inputs)<=33,'予算input上限');A.check(before=={p:A.sha(ROOT/p) for p in before},'予算source終端一致')
    proof=dict(全合格=True,scope='表示18×33×2小会計1188全数、新1056/旧alias132を区別。事前抽出実UID台帳/初閾値/勝ち赤字化。全1056新台帳会計監査とは称さない。',小会計=1188,新政策=1056,alias=132,抽出実台帳=len(checked),検査数=dict(A.COUNT),検査合計=sum(A.COUNT.values()),安定性=stability,実停止と勝ち反証=diagnosis,全33寄与=all_diff,検算台帳=checked,抽出計画SHA256=A.sha(p),入力読取=dict(packet=len(inputs),保存台帳=len(reads),原NPZ=0,現在API=0),新金融再生=0,engine再生=0,source_SHA256=before,source開始終端一致=True,入力SHA256={**inputs,**reads},レビューsource_SHA256=A.sha(Path(__file__)),正本SHA256=A.sha(SOURCE/'finance/結果.json'),制約=['L2/L4は初回枚数×tickの口座清算予算。入口spread/料だけで到達し得る。実損失の保証上限ではない。','旧GU当時実注文接頭からのみ残UIDを復元。旧将来trade/state/virtual feedを新保有へ使わない。','全33は既知比較で、最大利益3場除外も事後の頑健性点検。alias2条件を新しい予測成功と数えない。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8');print('予算保存独立監査合格',len(checked),sum(A.COUNT.values()),flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        p=HERE/'budget_独立保存監査のFalse.json';assert not p.exists();p.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),検査件数=dict(A.COUNT),金融再生=0,NPZ=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8');raise
