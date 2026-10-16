"""常設利確十二対照の保存小会計と、第一到達順・抽出単一玉経済を独立照合する。"""

from collections import defaultdict
from pathlib import Path
import json
import statistics
import traceback

import numpy as np
import range_finance_audit as A
import e01_trade_finance_audit as M

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_resting_takeprofit'
QTY={'TOPIX':5,'NK225':10}
TICK={'TOPIX':.5,'NK225':10.}
MULT={'TOPIX':1000.,'NK225':10.}


def aggregate(rows: list[dict], saved: dict) -> dict:
    """
    機能: 全33の収益・活動勝率・集中度を正本の集計関数なしで再計算する。
    引数: rows(list[dict])は同一商品場行、saved(dict)は保存集計。
    返り値: dictは再集計値と前後半・損益比。無取引は勝ちに含めない。
    """
    active=[r for r in rows if r['親数']];wins=[r['収支'] for r in rows if r['収支']>0];losses=[-r['収支'] for r in rows if r['収支']<0]
    g=sum(wins);l=sum(losses)
    result=dict(利益=g,損失=l,収支=g-l,利益割合=g/(g+l) if g+l else None,PF=g/l if l else None,
        全場=33,活動場=len(active),黒字場=len(wins),赤字場=len(losses),無取引場=33-len(active),
        活動黒字率=len(wins)/len(active) if active else None,中央値=statistics.median(r['収支'] for r in rows),
        上位3利益場除外収支=g-l-sum(sorted(wins,reverse=True)[:3]),最大場損失=max([0.]+losses),
        勝ち枚数=sum(r['勝ち枚数'] for r in rows),負け枚数=sum(r['負け枚数'] for r in rows),費用=sum(r['費用'] for r in rows),
        平均利益=sum(wins)/len(wins) if wins else None,平均損失=sum(losses)/len(losses) if losses else None,
        親数=len(active),勝ち親=len(wins),負け親=len(losses))
    for name,value in result.items():A.equal(saved[name],value,'常設全33/'+name)
    result.update(前16収支=sum(r['収支'] for r in rows[:16]),後17収支=sum(r['収支'] for r in rows[16:]),
        活動中央値=statistics.median(r['収支'] for r in active) if active else None,
        平均勝ち負け比=(g/len(wins))/(l/len(losses)) if wins and losses else None,
        損益分岐勝率=(l/len(losses))/((g/len(wins))+(l/len(losses))) if wins and losses else None,
        最大利益場比率=max(wins)/g if wins else None)
    return result


def first_index(mask: np.ndarray, lower: int) -> int:
    """
    機能: 指定行以降の初成立位置を集合検索で得る。
    引数: mask(ndarray[bool])、lower(int)は条件列と開始行。
    返り値: intは成立行。未成立は列長とする。
    """
    found=np.flatnonzero(mask[lower:]);return lower+int(found[0]) if len(found) else len(mask)


def expected(account: dict, entry: dict | None, config: dict) -> dict:
    """
    機能: 保存気配への第一到達集合から元政策の期待予約順だけを算出する。
    引数: account/entry/config(dict|None)は固定入力・最初実入口・設定。
    返り値: dictは監査用期待値。政策関数の再生や新金融の探索を行わない。
    """
    q=account['quotes'];n=len(q['bid']);symbol=account['symbol'];qty=QTY[symbol]
    ok=q['quote_valid']&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0)&(q['ask']>q['bid'])
    A.check(np.isfinite(q['time_s']).all() and q['time_s'][-1]>=account['record']['limit'],'常設完成時計')
    if entry is None:return dict(active=False,net=0.,gain=0.,loss=0.,fees=0,qty=0,ok=ok)
    o=np.asarray(entry['order']);er,dr,cid,side,qty=map(int,o[:5]);E=float(o[5])
    A.check(0<=dr<er<n and o[7]==1 and qty==QTY[symbol] and side in (-1,1),'常設入口前向き')
    A.check(ok[er] and E==q['ask' if side>0 else 'bid'][er],'常設実入口BBO')
    A.check(not account['quiet'][er] and not account['quiet_force'][er] and q['time_s'][er]<account['record']['limit'],'常設入口場内')
    A.check(entry['fill_raw_seq']==q['seq'][er] and entry['decision_raw_seq']==q['seq'][dr],'常設入口原seq')
    A.equal(entry['fill_price_time_s'],q['time_s'][er],'常設入口clock');A.equal(entry['decision_price_time_s'],q['time_s'][dr],'常設公開clock')
    clear=q['bid' if side>0 else 'ask'];target=E+side*TICK[symbol];stop=E-side*config['stop_ticks']*TICK[symbol]
    tr=first_index(account['quiet']|account['quiet_force']|(q['time_s']>=account['record']['limit']),er)
    sr=first_index(ok&(side*(clear-stop)<=0),er);pr=first_index(ok&(side*(clear-target)>=0),er+1)
    hit=min(sr,pr);original=-1;pending=None;timer=-1
    if tr<=hit:
        timer=tr;fill=first_index(ok,max(er+1,tr));decision=max(er,tr-1)
        reason='場内期限' if q['time_s'][tr]>=account['record']['limit'] else '既知quiet';price=float(clear[fill])
    elif hit==pr and config['method']=='RESTING':
        fill=pr;decision=er;reason='常設利確指値';price=target
    else:
        original=hit;pending='損切り' if hit==sr else '利確判断後成行'
        fill=first_index(ok,hit+1)
        if tr<=fill:
            timer=tr;fill=first_index(ok,max(er+1,tr));decision=max(er,tr-1)
            reason='場内期限' if q['time_s'][tr]>=account['record']['limit'] else '既知quiet'
        else:decision=hit;reason=pending
        price=float(clear[fill])
    A.check(fill<n and fill>er,'常設場内実返済')
    fee=2*M.fee(qty,symbol);gross=side*qty*(price-E)*MULT[symbol];net=gross-fee
    return dict(active=True,er=er,dr=dr,cid=cid,side=side,qty=qty,E=E,target=target,stop=stop,
        fill=fill,decision=decision,reason=reason,price=price,timer=timer,original=original,pending=pending,
        gross=gross,net=net,gain=max(net,0),loss=max(-net,0),fees=fee,uid=int(entry['uid']),ok=ok,
        stop_first=sr,target_first=pr,timer_first=tr)


def inspect_ledger(out: dict, account: dict, entry: dict | None, ex: dict, config: dict) -> dict:
    """
    機能: 抽出保存台帳の予約系譜・指定指値・現金・費用・全行保有を手計算と照合する。
    引数: out/account/ex/config(dict)、entry(dict|None)は保存台帳と独立期待値。
    返り値: dictは実時刻・原seq・リスク/利幅を含む実例。
    """
    q=account['quotes'];n=len(q['bid']);symbol=account['symbol'];c=out['control'];o=np.asarray(out['orders'])
    A.check(out['summary']['session']==account['session'] and out['summary']['symbol']==symbol,'常設台帳鍵')
    if not ex['active']:
        A.check(len(o)==len(out['parent'])==0 and not c['発動'],'常設不活動は勝ちなし')
        for name in ('equity_yen','liquidation_yen','long_qty','short_qty'):A.check(not np.any(A.expand(out[name],n)),'常設未取引curve零')
        return dict(発動=False)
    er,fr,d,side,qty,E=ex['er'],ex['fill'],ex['decision'],ex['side'],ex['qty'],ex['E']
    code={'常設利確指値':101,'利確判断後成行':102,'損切り':103,'既知quiet':104,'場内期限':105}[ex['reason']]
    np.testing.assert_array_equal(o,np.vstack([entry['order'],[fr,d,ex['cid'],-side,qty,ex['price'],code,0]]))
    np.testing.assert_array_equal(out['order_uids'],[ex['uid'],-1]);A.check(len(out['parent'])==1,'常設単一親')
    p=out['parent'][0]
    for key,val in dict(親=ex['cid'],新規行=er,最終返済行=fr,方向=side,枚数=qty,費用=ex['fees'],粗損益=ex['gross'],収支=ex['net']).items():A.equal(p[key],val,'常設親/'+key)
    for key,val in dict(発動=True,種別=ex['reason'],新規行=er,利確公開行=er,固定利確価格=ex['target'],固定損切り価格=ex['stop'],判断行=d,返済行=fr,timer開始行=ex['timer'],pending=ex['pending'],元観測予約判断行=ex['original']).items():A.check(c[key]==val,'常設独立系譜/'+key)
    A.check(c['単一親'] and c['最初実newfillのみ'] and not c['原GU出口使用'] and c['同新規行利確不可'],'常設範囲制約')
    expected_equity=np.zeros(n);expected_liq=np.zeros(n);held=np.zeros(n,dtype=np.int64)
    # ----------------------------------------
    # 前正常清算気配の当時保有時価と、一注文ずつの予約返済料を独立に復元する。
    last=np.maximum.accumulate(np.where(ex['ok'],np.arange(n),-1));marks=q['bid' if side>0 else 'ask'][last[er:fr]]
    expected_equity[er:fr]=side*qty*(marks-E)*MULT[symbol]-M.fee(qty,symbol)
    expected_liq[er:fr]=expected_equity[er:fr]-M.fee(qty,symbol);held[er:fr]=qty
    expected_equity[fr:]=expected_liq[fr:]=ex['net']
    np.testing.assert_allclose(A.expand(out['equity_yen'],n),expected_equity,atol=1e-7,rtol=0)
    np.testing.assert_allclose(A.expand(out['liquidation_yen'],n),expected_liq,atol=1e-7,rtol=0)
    for name,direction in [('long_qty',1),('short_qty',-1)]:np.testing.assert_array_equal(A.expand(out[name],n),held if side==direction else np.zeros(n,dtype=np.int64))
    A.check(held.max()<=10 if symbol=='TOPIX' else held.max()<=20,'常設保有上限')
    return dict(発動=True,理由=ex['reason'],方向=side,新規時刻=A.iso(q['time_s'][er]),利確公開時刻=A.iso(q['time_s'][er]),判断時刻=A.iso(q['time_s'][d]),返済時刻=A.iso(q['time_s'][fr]),新規原seq=int(q['seq'][er]),判断原seq=int(q['seq'][d]),返済原seq=int(q['seq'][fr]),新規価格=E,利確線=ex['target'],損切線=ex['stop'],返済価格=ex['price'],返済bid=float(q['bid'][fr]),返済ask=float(q['ask'][fr]),費用=ex['fees'],粗損益=ex['gross'],収支=ex['net'],元予約判断行=ex['original'],timer開始行=ex['timer'],判断上の損切幅=config['stop_ticks'],費用後の固定利益=TICK[symbol]*qty*MULT[symbol]-ex['fees'])


def main() -> None:
    """
    機能: 全792小会計・396同入口法比較と固定抽出実台帳を一度独立検算する。
    引数: なし。保存33入力一読、必要台帳一読。新金融/API/原NPZなし。
    返り値: Noneは小監査証跡。全792実台帳を読んだとは主張しない。
    """
    target=HERE/'resting_全12小会計と同入口二法及び固定一玉の独立監査.json';A.check(not target.exists(),'常設再監査禁止')
    s=A.read_json(SOURCE/'finance/結果.json');f=A.read_json(SOURCE/'金融前の固定.json');plan=A.read_json(SOURCE/'試行計画.json')
    before={p:A.sha(ROOT/p) for p in f['source_SHA256']}
    A.check(before==f['source_SHA256']==s['source_SHA256']==plan['spec']['implementation'],'常設固定source同一')
    A.check(s['全合格'] and s['source開始終端一致'] and s['configs']==f['configs']==plan['spec']['entry']['conditions'],'常設固定配置')
    A.check(s['新政策会計']==792 and s['read_counts']==dict(新input読取=33,新bracket会計=792),'常設根会計件数')
    A.check(s['入口engine再生']==s['元GU出口使用']==s['原NPZ']==s['API']==0,'常設根再生制約')
    A.check(f['計画SHA256']==A.sha(SOURCE/'試行計画.json'),'常設事前計画')
    configs={c['id']:c for c in s['configs']};rows={};items={};samples=set();stability={};pairs={};events={};directions={}
    for ident,c in configs.items():
        result=s['results'][ident];A.check(len(result['rows'])==len(result['ledgers'])==66,'常設全行66')
        items[ident]={(p['session'],p['symbol']):p for p in result['ledgers']};A.check(len(items[ident])==66,'常設台帳鍵一意')
        stability[ident]={};events[ident]={};directions[ident]={}
        for symbol in QTY:
            rr=[r for r in result['rows'] if r['symbol']==symbol];A.check([r['session'] for r in rr]==s['sessions'],'常設場順')
            for r in rr:
                qty=QTY[symbol];net=r['収支'];parent=r['親数'];A.check(parent in (0,1) and r['全会計合格'],'常設全行親会計')
                for key,val in dict(利益=max(net,0),損失=max(-net,0),勝ち親=int(net>0),負け親=int(net<0),零親=int(parent and net==0),勝ち枚数=qty if net>0 else 0,負け枚数=qty if net<0 else 0,零枚数=qty if parent and net==0 else 0,新規枚数=qty*parent,費用=2*M.fee(qty,symbol)*parent,注文件数=2*parent).items():A.equal(r[key],val,'常設全行/'+key)
                A.check(parent or net==0,'常設未取引損益零');rows[ident,r['session'],symbol]=r
            stability[ident][symbol]=aggregate(rr,result['symbols'][symbol]);active=[r for r in rr if r['親数']]
            if active:
                samples.add((ident,active[0]['session'],symbol));samples.add((ident,min(active,key=lambda r:(r['収支'],r['session']))['session'],symbol))
            events[ident][symbol]=defaultdict(int);directions[ident][symbol]={str(side):dict(親数=0,利益=0.,損失=0.,収支=0.) for side in (-1,1)}
    A.check(len(s['利確二法の各場比較'])==396,'常設二法396比較')
    for d in s['利確二法の各場比較']:
        stem=f"E01_FIRST_W60_{d['mode']}_TP1_S{d['stop']}_";key=d['session'],d['symbol'];a=rows[(stem+'NEXT_MARKET',)+key];b=rows[(stem+'RESTING',)+key]
        A.check(d['成行']==a and d['常設']==b,'常設同入口比較元');delta=b['収支']-a['収支']
        for k,v in dict(収支変化=delta,避けた基準損失=0,失った基準利益=0,共通入口の出口変化=delta,新たな入口の収支=0,元勝ち親が赤字化=int(a['収支']>0 and b['収支']<0)).items():A.equal(d[k],v,'常設法差/'+k)
        token=f"{d['mode']}_S{d['stop']}";stats=pairs.setdefault(token,{}).setdefault(d['symbol'],dict(全場=0,差額=0.,改善場=0,悪化場=0,同値場=0,利益化場=0,赤字化場=0))
        stats['全場']+=1;stats['差額']+=delta;stats['改善場']+=delta>0;stats['悪化場']+=delta<0;stats['同値場']+=delta==0;stats['利益化場']+=a['収支']<=0<b['収支'];stats['赤字化場']+=a['収支']>=0>b['収支']
    sampleplan=HERE/'resting_独立保存監査の事前抽出計画.json';A.check(not sampleplan.exists(),'常設抽出計画新規')
    sampleplan.write_text(json.dumps(dict(抽出=[list(v) for v in sorted(samples)],規則='各条件商品の先頭活動場＋最悪活動場。同額は場名順。入力読取前固定。追加timerは入力到達順で最初の実timerのみ。',全数小会計792=792,法比較396=396,入力33各一読=True,原NPZ=0,API=0,金融再生=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    reads={};inputs={};checked=[];specific=[];timerselected=set();all_expected=0
    for session in s['sessions']:
        packet=A.unpack(f['cache'][session],inputs);A.check(packet['session']==session,'常設input場鍵')
        for symbol,account in packet['accounts'].items():
            A.check(account['session']==session and account['symbol']==symbol,'常設口座鍵')
            per={}
            for ident,c in configs.items():
                entry=account['entries'][c['mode']];ex=expected(account,entry,c);per[ident]=ex;all_expected+=1;r=rows[ident,session,symbol]
                for key,val in dict(収支=ex['net'],利益=ex['gain'],損失=ex['loss'],費用=ex['fees'],親数=int(ex['active']),新規枚数=ex['qty']).items():A.equal(r[key],val,'常設全792第一到達/'+key)
                if ex['active']:
                    events[ident][symbol][ex['reason']]+=1;di=directions[ident][symbol][str(ex['side'])];di['親数']+=1;di['利益']+=ex['gain'];di['損失']+=ex['loss'];di['収支']+=ex['net']
                    token=ident,symbol
                    if ex['timer']>=0 and token not in timerselected:samples.add((ident,session,symbol));timerselected.add(token)
                if (ident,session,symbol) in samples:
                    out=A.unpack(items[ident][session,symbol],reads);A.check(out['summary']==r,'常設抽出台帳小会計')
                    diag=inspect_ledger(out,account,entry,ex,c);diag.update(id=ident,session=session,symbol=symbol)
                    checked.append(dict(id=ident,session=session,symbol=symbol,SHA256=items[ident][session,symbol]['SHA256']));specific.append(diag)
            for mode in ('CONFIRM','VETO'):
                for stop in (4,8,16):
                    stem=f'E01_FIRST_W60_{mode}_TP1_S{stop}_';a=per[stem+'NEXT_MARKET'];b=per[stem+'RESTING']
                    A.check(a['active']==b['active'],'常設二法同参加')
                    if a['active']:
                        A.check(all(a[k]==b[k] for k in ('er','dr','cid','side','qty','E','target','stop','uid')),'常設二法同入口全項')
        del packet
        print(session+'：第一到達・同入口二法・抽出全行curve照合',flush=True)
    A.check(all_expected==792 and len(inputs)==33,'常設全数範囲');A.check(before=={p:A.sha(ROOT/p) for p in before},'常設source終端同一')
    representative=stability['E01_FIRST_W60_CONFIRM_TP1_S16_RESTING']['NK225']
    proof=dict(全合格=True,scope='全12×33×2小会計792、396同入口利確法差。保存入力33の第一到達/予約制約全792。固定抽出台帳の親・料金・全行保有/清算。新政策再生ではなく固定結果の期待拘束照合。',
        小会計=792,利確二法比較=396,全入力第一到達検査=all_expected,安定性=stability,同入口二法差=pairs,退出理由全数=events,商品別買売実測=directions,
        高勝率でも金額未達=dict(id='E01_FIRST_W60_CONFIRM_TP1_S16_RESTING',symbol='NK225',勝ち=representative['勝ち親'],取引=representative['親数'],勝率=representative['活動黒字率'],利益割合=representative['利益割合'],利益=representative['利益'],損失=representative['損失'],収支=representative['収支'],平均勝ち=representative['平均利益'],平均負け=representative['平均損失'],損益分岐勝率=representative['損益分岐勝率']),
        抽出台帳=len(checked),検算台帳=checked,抽出具体例=specific,timer実資料検算=len(timerselected),検査数=dict(A.COUNT),検査合計=sum(A.COUNT.values()),
        source_SHA256=before,source開始終端一致=True,正本SHA256=A.sha(SOURCE/'finance/結果.json'),抽出計画SHA256=A.sha(sampleplan),レビューsource_SHA256=A.sha(Path(__file__)),
        入力読取=dict(保存packet=len(inputs),保存新台帳=len(reads),原NPZ=0,原book=0,現在snapshot=0,API=0),入力SHA256={**inputs,**reads},新金融再生=0,
        制約=['常設はBBO価格到達で固定line全量約定の仮定。実小型板のqueueや実約定は証明しない。','同入口RESTING対NEXTだけ注文方法の差。旧GU又は場全体goalとの比較は入口範囲・退出が変わるため注文寄与に還元しない。','全33は既知。95%は決済親の勝率であり金額80%と別。','支持/活動資格は保存元入口へ委譲し再選抜しない。全792実ledgerを読んだ監査とは称さない。','実timer資料がなければ予約競合の資格は金融前独立48人工へ委譲。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8');print('常設十二保存独立監査合格',len(checked),sum(A.COUNT.values()),flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        p=HERE/'resting_独立保存監査のFalse.json';assert not p.exists();p.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),検査件数=dict(A.COUNT),新金融再生=0,原NPZ=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8');raise
