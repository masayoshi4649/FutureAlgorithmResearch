"""途中退出6の全小会計と必要保存UID・当時全normal票を独立に検算する。"""

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
SOURCE=ROOT/'work/wave_v106/e01_trade_exit'


def check_policy(gu: dict, out: dict, account: dict, config: dict, symbol: str) -> dict:
    """
    機能: 実GU注文由来の残方向と途中票AND損失から初先着・残UID返済を独立確認する。
    引数: gu/out/account/config(dict)、symbol(str)は保存口座と当時normal票。
    返り値: dictは4損失到達時の票と実停止の記述。価格未来を採否へ渡さない。
    """
    quotes=account['quotes'];observed=account['votes'][str(config['window_seconds'])];_,_,path=M.inspect_orders(gu,quotes,symbol)
    n=len(quotes['bid']);delta=np.zeros(n,np.int64)
    np.add.at(delta,gu['orders'][:,0].astype(np.int64),(gu['orders'][:,3]*gu['orders'][:,4]).astype(np.int64));held=np.cumsum(delta);side=np.sign(held)
    unit=(.5 if symbol=='TOPIX' else 10)*(5 if symbol=='TOPIX' else 10)*(1000 if symbol=='TOPIX' else 10)
    total=observed['up_votes'].astype(np.int64)+observed['down_votes'].astype(np.int64)
    early=(held!=0)&observed['known']&(total>=2)&np.isfinite(observed['balance'])&(side*observed['balance']<=-.25)&(path['liquidation']<=-4*unit)
    profit=path['liquidation']>=unit;hard=path['liquidation']<=-8*unit;hit=path['valid']&(profit|hard|early);positions=np.flatnonzero(hit);control=out['control']
    A.check(control['発動']==bool(len(positions)),'途中票先着発動')
    if not len(positions):np.testing.assert_array_equal(out['orders'],gu['orders']);return dict(発動=False)
    row=int(positions[0]);kind='利益目標' if profit[row] else '損失予算' if hard[row] else '逆票かつ4呼値損失';reason=94 if profit[row] else 95 if hard[row] else 96
    A.check(control['判断行']==row and control['種別']==kind,'途中票初rowと理由')
    A.check(control['判断原seq']==quotes['seq'][row] and control['実残玉方向']==side[row],'途中票実残方向原seq')
    A.equal(control['判断時清算利益'],path['liquidation'][row],'途中票清算時価')
    for k,v in dict(既知票=bool(observed['known'][row]),買票=int(observed['up_votes'][row]),売票=int(observed['down_votes'][row])).items():A.check(control[k]==v,'途中票当時記録')
    balance=float(observed['balance'][row]) if np.isfinite(observed['balance'][row]) else None;A.equal(control['買方向釣合い'],balance,'途中票balance')
    prefix=gu['orders'][:,0]<=row;original=gu['orders'][prefix];uids=gu['order_uids'][prefix]
    np.testing.assert_array_equal(out['orders'][:len(original)],original);np.testing.assert_array_equal(out['order_uids'][:len(original)],uids)
    remaining=prefix_uid(original,uids,row);suffix=out['orders'][len(original):];A.check(len(suffix)==len(remaining),'途中票残UID別')
    fill=row if not remaining else row+1+int(np.flatnonzero(path['valid'][row+1:])[0]);A.check(control['返済行']==fill,'途中票次正常quote')
    for j,(o,v) in enumerate(zip(suffix,remaining)):
        action=-v['side'];price=quotes['ask' if action>0 else 'bid'][fill]
        np.testing.assert_array_equal(o,np.array([fill,row,v['cid'],action,v['q'],price,reason,0],float))
        A.check(out['exit_target_uids'][len(original)+j]==v['uid'],'途中票残UIDtarget')
    A.check(not np.any(out['orders'][(out['orders'][:,0]>row)&(out['orders'][:,7]==1)]),'途中票以後新規0')
    thresholds=np.flatnonzero(path['valid']&(held!=0)&(path['liquidation']<=-4*unit))
    first4=None
    if len(thresholds):
        j=int(thresholds[0]);first4=dict(row=j,時刻=A.iso(quotes['time_s'][j]),原seq=int(quotes['seq'][j]),清算=float(path['liquidation'][j]),実side=int(side[j]),known=bool(observed['known'][j]),買票=int(observed['up_votes'][j]),売票=int(observed['down_votes'][j]),side釣合い=float(side[j]*observed['balance'][j]) if np.isfinite(observed['balance'][j]) else None,AND追加退出=bool(early[j]))
    return dict(発動=True,種類=kind,判断時刻=A.iso(quotes['time_s'][row]),返済時刻=A.iso(quotes['time_s'][fill]),判断清算=float(path['liquidation'][row]),実収支=out['summary']['収支'],次quote変化=out['summary']['収支']-path['liquidation'][row],最初4損失=first4)


def main() -> None:
    """
    機能: 全6小会計396と固定抽出UID・2対照の5寄与を保存資料だけで一回検査する。
    引数: なし。金融engine/原NPZ/APIを呼ばない。
    返り値: Noneは独立監査証跡。全396台帳監査とは称さない。
    """
    target=HERE/'exit_全6小会計と抽出途中票UIDの独立監査.json';A.check(not target.exists(),'退出6再監査なし')
    s=A.read_json(SOURCE/'finance/結果.json');fixed=A.read_json(SOURCE/'金融前の固定.json');meta=A.read_json(SOURCE/'全33場の保有中取引更新票.json')
    before={p:A.sha(ROOT/p) for p in fixed['source_SHA256']};A.check(before==fixed['source_SHA256']==s['source_SHA256'],'退出固定源')
    A.check(s['全合格'] and s['新政策会計']==396 and s['configs']==fixed['configs'] and s['sessions']==fixed['sessions'],'退出6固定配置場')
    A.check(s['engine再生']==s['元paper再生']==s['原NPZ読取']==s['原book']==s['API']==0,'退出6根禁止範囲')
    configs={c['id']:c for c in s['configs']};samples=set();stability={};ledgers={};deltas={i:{b:{m:defaultdict(float) for m in ('TOPIX','NK225')} for b in ('P1L8','P1L4')} for i in configs};winner=[]
    for ident,c in configs.items():
        v=s['results'][ident];A.check(len(v['rows'])==66 and len({(r['session'],r['symbol']) for r in v['rows']})==66,'退出全行一意');ledgers[ident]={(p['session'],p['symbol']):p for p in v['ledgers']};stability[ident]={}
        rowmap={(r['session'],r['symbol']):r for r in v['rows']}
        for symbol in ('TOPIX','NK225'):
            rr=[r for r in v['rows'] if r['symbol']==symbol]
            for r in rr:M.row_check(r,5 if symbol=='TOPIX' else 10)
            stability[ident][symbol]=M.aggregate(rr,v['symbols'][symbol]);active=[r for r in rr if r['親数']]
            if active:samples.add((ident,active[0]['session'],symbol));samples.add((ident,min(active,key=lambda r:(r['収支'],r['session']))['session'],symbol))
        for base in ('P1L8','P1L4'):
            base_rows={(r['session'],r['symbol']):r for r in fixed['bindings'][c['mode']][base]['rows']}
            for d in s['各場寄与'][ident][base]:
                m=d['symbol'];A.equal(d['収支変化'],rowmap[d['session'],m]['収支']-base_rows[d['session'],m]['収支'],'退出全行基準差')
                A.equal(d['収支変化'],d['避けた基準損失']-d['失った基準利益']+d['共通入口の出口変化']+d['新たな入口の収支'],'退出全行5寄与')
                for k in M.FIELDS:deltas[ident][base][m][k]+=d[k]
                if base=='P1L8':
                    for t in d['元勝ち親が赤字化']:winner.append((m,t['base_net'],ident,d['session']))
            for m in ('TOPIX','NK225'):
                for k in M.FIELDS:A.equal(s['diagnosis'][ident][base][m][k],deltas[ident][base][m][k],'退出全33寄与')
    for m in ('TOPIX','NK225'):
        ww=[v for v in winner if v[0]==m]
        if ww:
            best=max(ww,key=lambda v:(v[1],v[2],v[3]));samples.add((best[2],best[3],m))
    p=HERE/'exit_独立保存監査の抽出計画.json';A.check(not p.exists(),'退出抽出計画新規');p.write_text(json.dumps(dict(抽出=[list(v) for v in sorted(samples)],規則='6条件各商品初活動場と最悪活動場＋P1L8最大基準利益の勝ち赤字化を各商品。入力読取前選定。',小会計=396,金融再生=0,NPZ=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    reads={};inputs={};checked=[];causes=[]
    for session in s['sessions']:
        selected=[v for v in sorted(samples) if v[1]==session]
        if not selected:continue
        packet=A.unpack(meta['cache'][session],inputs);cache={}
        for symbol in {v[2] for v in selected}:
            a=packet['accounts'][symbol];r=a['record']
            for z in a['votes'].values():
                np.testing.assert_array_equal(z['candidate_raw_seq'],r['seq']);np.testing.assert_array_equal(z['candidate_price_time_s'],r['time_s'])
                A.check(np.all((z['reference_raw_row']<z['candidate_raw_row'])|~z['known']),'退出途中票過去基準')
                A.check(np.all((z['first_vote_raw_row']<=z['candidate_raw_row'])|(z['first_vote_raw_row']==-1)),'退出途中票未来行なし')
        for ident,_,symbol in selected:
            c=configs[ident];a=packet['accounts'][symbol];q=a['quotes'];binding=fixed['bindings'][c['mode']];key=session+'|'+symbol
            for b in ('GU','P1L8','P1L4'):
                token=c['mode'],symbol,b
                if token not in cache:cache[token]=A.unpack(binding[b]['ledgers'][key],reads)
            gu=cache[c['mode'],symbol,'GU'];out=A.unpack(ledgers[ident][session,symbol],reads);parents=M.inspect_orders(out,q,symbol)[0];diagnosis=check_policy(gu,out,a,c,symbol)
            for b in ('P1L8','P1L4'):
                old=M.inspect_orders(cache[c['mode'],symbol,b],q,symbol)[0];d=M.contribution(old,parents);saved=next(v for v in s['各場寄与'][ident][b] if v['session']==session and v['symbol']==symbol)
                for k in M.FIELDS:A.equal(saved[k],d[k],'退出抽出独立5寄与')
                expected={(k,old[k]['net'],parents[k]['net']) for k in old.keys()&parents.keys() if old[k]['net']>0 and parents[k]['net']<0}
                A.check(expected=={(v['parent'],v['base_net'],v['new_net']) for v in saved['元勝ち親が赤字化']},'退出抽出勝ち赤字化')
            diagnosis.update(id=ident,session=session,symbol=symbol,費用=out['summary']['費用'],親数=len(parents));causes.append(diagnosis);checked.append(dict(id=ident,session=session,symbol=symbol,parents=len(parents),orders=len(out['orders']),SHA256=ledgers[ident][session,symbol]['SHA256']))
        del packet,cache
        print(session+'：途中票とUID停止接頭を独立検算',flush=True)
    A.check(before=={p:A.sha(ROOT/p) for p in before},'退出source終端一致')
    proof=dict(全合格=True,scope='退出6×33×2の小会計396全数、2保存対照の寄与全数、必要抽出UID台帳と同normal途中票。全396台帳監査とは称さない。',小会計=396,抽出実台帳=len(checked),安定性=stability,途中判断と4損失時の票=causes,全33寄与=deltas,検査数=dict(A.COUNT),検査合計=sum(A.COUNT.values()),検算台帳=checked,抽出計画SHA256=A.sha(p),入力読取=dict(packet=len(inputs),保存台帳=len(reads),原NPZ=0,API=0),新金融再生=0,source_SHA256=before,source開始終端一致=True,入力SHA256={**inputs,**reads},レビューsource_SHA256=A.sha(Path(__file__)),正本SHA256=A.sha(SOURCE/'finance/結果.json'),制約=['当時保有票は新cache。原NPZ票再生成0、全normal数学は金融前独立人工・固定源へ委譲。','反対票でも4損失前なら退出しない。追加退出は未知hold、P1/hard8は維持。','将来の価格から退出条件を選ばず、既知33の頑健性/勝ち反証としてだけ評価。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8');print('退出6保存独立監査合格',len(checked),sum(A.COUNT.values()),flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        p=HERE/'exit_独立保存監査のFalse.json';assert not p.exists();p.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),検査件数=dict(A.COUNT),金融再生=0,NPZ=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8');raise
