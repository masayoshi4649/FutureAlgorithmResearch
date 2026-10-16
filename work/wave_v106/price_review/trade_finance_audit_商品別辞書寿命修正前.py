"""入口確認36条件の保存会計、同入力reuse、票資格と抽出現金を独立検算する。"""

from collections import defaultdict
import hashlib
import json
import pickle
from pathlib import Path
import sys
import traceback

import numpy as np

import range_finance_audit as A
from local_finance_audit import map_entries, contribution, FIELDS


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/trade_gate'


def fingerprint(prepared: dict, normal: dict, config: dict, mask: np.ndarray, reasons: np.ndarray) -> str:
    """
    機能: 公開IDと入口gate定義以外の全金融入力を独立に直列化する。
    引数: prepared/normal/config(dict)、mask/reasons(ndarray)は同口座入力。
    返り値: strは金融を呼ばないSHA256。正常入力/理由の違いをreuse不可にする。
    """
    excluded={'id','baseline_id','trade_window_seconds','minimum_direction_votes','minimum_direction_balance','gate_scope'}
    c={k:v for k,v in config.items() if k not in excluded}
    h=hashlib.sha256(pickle.dumps((c,prepared['reference_open'],prepared['signal']['trend_width']),protocol=5))
    for k in sorted(normal):
        if k=='entry_id':continue
        v=normal[k];h.update(k.encode('utf8'))
        if isinstance(v,np.ndarray):h.update(str(v.dtype).encode());h.update(pickle.dumps(v.shape));h.update(v.tobytes())
        else:h.update(pickle.dumps(v,protocol=5))
    for v in (mask,reasons):h.update(v.tobytes())
    return h.hexdigest()


def vote_masks(packet: dict, symbol: str, config: dict) -> tuple[dict,np.ndarray,np.ndarray]:
    """
    機能: 保存当時票から独立算式で入口scopeの全行maskと理由を作る。
    引数: packet(dict)、symbol(str)、config(dict)は一読済入力と固定条件。
    返り値: tuple[dict,ndarray,ndarray]は元normal浅複製、確認mask、理由。raw票自体の再抽出なし。
    """
    normal=dict(packet['normals'][config['baseline_id']][symbol]);normal['entry_id']=config['id']
    record=packet['prepared'][symbol]['record'];mask=np.ones(len(record['seq']),bool);reasons=np.zeros(len(mask),np.int32)
    values=packet['trade_features'][symbol][str(config['trade_window_seconds'])]
    family=normal['entry_families'];scope=config['gate_scope']
    targeted=(family>0) if scope=='BOTH' else family==(1 if scope=='C' else 2)
    for row in np.flatnonzero(targeted):
        v=values[int(row)];known=v['reason']==0;A.check(v['known']==known,'票known理由一致')
        if v['reason']==2:
            allowed=False
        else:
            up,down=v['measured_up_votes'],v['measured_down_votes'];total=up+down
            A.check(up>=0 and down>=0 and int(up)==up and int(down)==down,'票整数分母')
            A.check(v['candidate_raw_row']==normal['execution_to_raw_index'][row] and v['candidate_raw_seq']==record['seq'][row],'票当時原seqとmap')
            A.equal(v['candidate_price_time_s'],record['time_s'][row],'票候補時計')
            A.equal(v['cutoff_price_time_s'],record['time_s'][row]-config['trade_window_seconds'],'票窓終端')
            A.check(v['last_vote_raw_row']==v['candidate_raw_row'] and (v['first_vote_raw_row'] is None or v['first_vote_raw_row']<=v['candidate_raw_row']),'票未来rawなし')
            A.check(v['reference_raw_row'] is None or v['reference_raw_row']<v['candidate_raw_row'],'票過去基準')
            balance=int(normal['event'][row])*(up-down)/total if total else None
            if known:
                A.check(v['up_votes']==up and v['down_votes']==down and v['direction_votes']==total,'既知票分母一致')
                A.equal(v['balance'],balance,'票balance')
            else:A.check(v['direction_votes'] is None and v['balance'] is None,'未知を支持票にしない')
            allowed=known and total>=2 and balance>=.25
        A.check(v['accepted']==allowed,'入口票独立採否')
        mask[row]=allowed
        reasons[row]=0 if allowed else 100+v['reason'] if not known else 200 if v['direction_votes']<2 else 201
    return normal,mask,reasons


def economic_row(row: dict) -> dict:
    """
    機能: 掲載会計からscope表示とreuse識別以外の経済字段を抽出する。
    引数: row(dict)は同場同商品会計。
    返り値: dictは完全同入力に要求する小経済一致。
    """
    return {k:v for k,v in row.items() if k not in ('economic_alias','selected_C','selected_R')}


def main() -> None:
    """
    機能: 正式36金融の全小会計と機械選定台帳を、再生なしで一回検算する。
    引数: なし。根の正式完了通知後だけ実行する。
    返り値: Noneは保存独立監査証跡。全1129実台帳監査とは称さない。
    """
    target=HERE/'trade_全36小会計とreuse及び入口票の独立保存監査.json';A.check(not target.exists(),'再監査なし')
    fixed=A.read_json(SOURCE/'金融開始前の固定_v2.json');results=A.read_json(SOURCE/'finance/results.json')
    meta=A.read_json(SOURCE/'全33場の取引更新代理準備_v2.json');priorpath=ROOT/'work/wave_v106/range_price/finance/results.json';prior=A.read_json(priorpath)
    before={p:A.sha(ROOT/p) for p in fixed['source_SHA256']};A.check(before==fixed['source_SHA256']==results['source_SHA256'],'固定源不変')
    A.check(results['configs']==fixed['configs'] and results['sessions']==fixed['sessions']==meta['sessions'],'固定配置と場')
    A.check(results['全合格'] and results['account_count']==2376 and results['actual_financial_accounts']==1129 and len(results['economic_aliases'])==1247,'実reuse件数分離')
    A.check(results['baseline_replays']==results['original_book_reads']==results['current_API_reads']==0,'根禁止範囲')
    A.check(A.sha(priorpath)==fixed['baseline_results_SHA256'] and A.sha(SOURCE/'全33場の取引更新代理準備_v2.json')==fixed['input_metadata_SHA256'],'基準入力指紋')
    sessions=results['sessions'];configs={c['id']:c for c in results['configs']};rows={};stability={};samples=set();worst={};base_rows={}
    for ident,c in configs.items():
        case=results['cases'][ident];A.check(len(case['rows'])==66 and len({(r['session'],r['symbol']) for r in case['rows']})==66,'掲載一意');stability[ident]={};worst[ident]={}
        for symbol in ('TOPIX','NK225'):
            selected=[r for r in case['rows'] if r['symbol']==symbol]
            for r in selected:A.row_check(r,c['quantity'][symbol]);rows[ident,r['session'],symbol]=r
            stability[ident][symbol]=A.summary_check(selected,case['summary'][symbol],sessions)
            active=[r for r in selected if r['campaigns']]
            if active:samples.add((ident,active[0]['session'],symbol))
            negative=sorted((r for r in selected if r['net']<0),key=lambda r:(r['net'],r['session']))[:3];worst[ident][symbol]={r['session'] for r in negative}
            if c['gate_scope']=='C':samples.update((ident,r['session'],symbol) for r in negative)
        for r in prior['cases'][c['baseline_id']]['rows']:base_rows[c['baseline_id'],r['session'],r['symbol']]=r
    plan=dict(抽出=sorted(samples),規則='全36条件商品の時系列最初の活動場＋scopeC各条件商品赤字上位3場。alias引用元と同量基準は必要時のみ。',packet上限=33,金融再生=0,NPZ=0)
    planpath=HERE/'trade_保存監査の事前抽出計画.json';A.check(not planpath.exists(),'抽出計画新規');planpath.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    aliasindex={(v['id'],v['session'],v['symbol']):v for v in results['economic_aliases']};A.check(len(aliasindex)==1247,'alias鍵一意')
    sys.path.insert(0,str(SOURCE));account=A.load_module('独立trade保存物理会計',SOURCE/'engine/accounting.py')
    reads={};inputs={};checked=[];causes={};deltas={i:{s:defaultdict(float) for s in ('TOPIX','NK225')} for i in configs};actual=aliascount=0
    for session in sessions:
        packet=A.unpack(meta['cache'][session],inputs);ds=A.read_json(SOURCE/'finance/contributions'/f'{session}.json')
        saved={};oldcache={}
        for symbol in ('TOPIX','NK225'):
            prepared=packet['prepared'][symbol];record=prepared['record'];memo={};projection={}
            for ident,c in configs.items():
                normal,mask,reasons=vote_masks(packet,symbol,c);fp=fingerprint(prepared,normal,c,mask,reasons);projection[ident]=(normal,mask,reasons,fp)
                expected_alias=None
                if fp in memo:
                    original=memo[fp];expected_alias=dict(session=session,symbol=symbol,id=ident,reused_from=original,input_SHA256=fp)
                    A.check(aliasindex.get((ident,session,symbol))==expected_alias,'alias全入力指紋')
                    A.check(economic_row(rows[ident,session,symbol])==economic_row(rows[original,session,symbol]),'alias小経済同値');aliascount+=1
                else:memo[fp]=ident;actual+=1;A.check((ident,session,symbol) not in aliasindex,'実金融別入力')
                A.check(rows[ident,session,symbol]['economic_alias']==expected_alias,'掲載alias接続')
                A.equal(rows[ident,session,symbol]['selected_C'],int(np.count_nonzero((normal['entry_families']==1)&mask)),'C候補許可数')
                A.equal(rows[ident,session,symbol]['selected_R'],int(np.count_nonzero((normal['entry_families']==2)&mask)),'R候補許可数')
                d=ds[ident][symbol];base=base_rows[c['baseline_id'],session,symbol]
                A.equal(d['収支変化'],rows[ident,session,symbol]['net']-base['net'],'全場基準差')
                A.equal(d['収支変化'],d['避けた基準損失']-d['失った基準利益']+d['共通入口の出口変化']+d['新たな入口の収支'],'全場5寄与恒等式')
                for field in FIELDS:deltas[ident][symbol][field]+=d[field]
            selected=sorted(i for i,s,m in samples if s==session and m==symbol)
            need=set(selected)
            for ident in selected:
                alias=aliasindex.get((ident,session,symbol))
                if alias:need.add(alias['reused_from'])
            for ident in configs:
                if ident not in need:continue
                item=results['cases'][ident]['ledgers'][session][symbol];out=A.unpack(item,reads)
                for field in ('curve','source_curve','target_trace'):out[field]=A.expand(out[field],len(record['seq']))
                normal,mask,reasons,fp=projection[ident];A.check(out['execution_input_SHA256']==fp,'台帳執行入力SHA')
                np.testing.assert_array_equal(out['entry_filter'],mask);np.testing.assert_array_equal(out['filter_reason'],reasons)
                A.check(out['selection_diagnostics']==normal['decisions'],'当時根拠列一致')
                A.physical(record,out,rows[ident,session,symbol]);A.causality(record,out,normal,configs[ident])
                verified=account.inspect((session,symbol),record,out,normal);A.compare_totals(rows[ident,session,symbol],A.totals([verified]),'保存四引数会計')
                for order in out['orders'][out['orders'][:,7]==1]:A.check(mask[int(order[1])],'実公開時vote許可')
                saved[ident]=out;checked.append(dict(id=ident,session=session,symbol=symbol,parents=len(out['trades']),orders=len(out['orders']),SHA256=item['SHA256']))
            for ident in selected:
                out=saved[ident];c=configs[ident];alias=aliasindex.get((ident,session,symbol))
                if alias:
                    for field in ('orders','trades','growth_cohorts','curve','source_curve','target_trace'):np.testing.assert_array_equal(out[field],saved[alias['reused_from']][field]);A.COUNT['抽出alias実経済exact']+=1
                baseid=c['baseline_id']
                if baseid not in oldcache:
                    old=A.unpack(prior['cases'][baseid]['ledgers'][session][symbol],reads);oldcache[baseid]=map_entries(old,record);del old
                d=contribution(oldcache[baseid],map_entries(out,record))
                for field in FIELDS:A.equal(ds[ident][symbol][field],d[field],'抽出同入口独立5寄与')
                if c['gate_scope']=='C' and session in worst[ident][symbol]:
                    ps=A.cost_trades(record,out);negative=[p for p in ps if p['収支']<0]
                    for p in ps:
                        t=next(t for t in out['trades'] if int(t[0])==p['parent']);dr=int(t[15]);p['family']='C' if int(t[1])==0 else 'R';p['当時公開票']=packet['trade_features'][symbol][str(c['trade_window_seconds'])][dr]
                    causes.setdefault(ident,{}).setdefault(symbol,[]).append(dict(session=session,収支=rows[ident,session,symbol]['net'],負親数=len(negative),C負親=sum(p['family']=='C' for p in negative),R負親=sum(p['family']=='R' for p in negative),最初負親=negative[0] if negative else None,最悪負親=min(negative,key=lambda p:p['収支']) if negative else None,mid変動粗損益=sum(p['mid変動粗損益'] for p in ps),気配差負担=sum(p['往復気配差負担'] for p in ps),料金=sum(p['手数料'] for p in ps),基準との差=d))
            del saved,projection,memo
        del packet
        print(session+'：全票/alias入力と抽出台帳を独立検算',flush=True)
    A.check(actual==1129 and aliascount==1247 and len(inputs)==33,'実reuseと入力読取終端')
    for ident in configs:
        for symbol in ('TOPIX','NK225'):
            for field in FIELDS:A.equal(deltas[ident][symbol][field],results['diagnosis'][ident][symbol][field],'全33寄与加算')
    A.check(before=={p:A.sha(ROOT/p) for p in before},'source開始終端一致')
    proof=dict(全合格=True,scope='全36×33×2小会計2376、1247reuse入力全数、事前抽出実台帳。全1129新実台帳の会計監査とは称さない。',小会計全数=2376,実再生=actual,経済reuse=aliascount,抽出実台帳数=len(checked),抽出計画SHA256=A.sha(planpath),検査件数=dict(A.COUNT),検査合計=sum(A.COUNT.values()),安定性=stability,Cscope赤字上位3=causes,全33寄与=deltas,検算台帳=checked,入力読取=dict(packet=len(inputs),保存台帳=len(reads),NPZ=0,原book=0,API=0),金融再生=0,registry変更=0,source_SHA256=before,source開始終端一致=True,入力SHA256={**inputs,**reads},レビューsource_SHA256=A.sha(Path(__file__)),正本SHA256={str(p.relative_to(ROOT)):A.sha(p) for p in (SOURCE/'finance/results.json',SOURCE/'金融開始前の固定_v2.json',SOURCE/'試行計画_v2.json')},限界=['当時票の原seq/map/分母/採否を保存featuresで検算。原NPZ票再生成は0で、上流純人工と固定源へ委譲。','reuseは同全入力の同経済。独立した予測成功や新金融1129より多い成功を主張しない。','scope対象外でも共有保有・休止を通じ後続実入口は変わり得る。避け損失はすべて方向予測改善ではない。','全33は既知比較、sample6点と代理票は真の全tick/攻撃注文量/受信時間ではない。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print('trade保存独立監査合格',len(checked),sum(A.COUNT.values()),flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        p=HERE/'trade_独立保存監査のFalse.json'
        assert not p.exists()
        p.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),検査件数=dict(A.COUNT),金融再生=0,NPZ=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        raise
