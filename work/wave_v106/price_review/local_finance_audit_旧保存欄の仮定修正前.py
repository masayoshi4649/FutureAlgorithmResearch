"""局所12実再生と6保存派生を分け、全小会計と機械抽出台帳を独立監査する。"""

from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np

import range_finance_audit as A


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/local_phase'
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def short_oracle(packet: dict, symbol: str) -> None:
    """
    機能: 保存された全行三点を当時の自己中値/厳密過去peerから再構成する。
    引数: packet(dict)、symbol(str)は一回読んだ準備cacheと商品。
    返り値: None。新候補や金融注文を生成しない。
    """
    record=packet['prepared'][symbol]['record'];m=packet['measured'][symbol];index=m['normal_sample_index']
    own=np.column_stack((m['sample_tables']['own']['midpoint'][index,-3:-1],(record['bid']+record['ask'])/2))
    peer=m['sample_tables']['peer']['midpoint'][index,-3:]
    for label,points,baseknown,tick in (('own',own,m['own_known']&m['qok'],record['tick']),
        ('peer',peer,m['peer_known'],packet['prepared']['NK225' if symbol=='TOPIX' else 'TOPIX']['record']['tick'])):
        saved=packet['short'][symbol][label];valid=baseknown&np.all(np.isfinite(points)&(points>0),axis=1)
        net=(points[:,2]-points[:,0])/tick;tv=(np.abs(points[:,1]-points[:,0])+np.abs(points[:,2]-points[:,1]))/tick
        er=np.divide(np.abs(net),tv,out=np.zeros(len(net)),where=tv>0);direction=np.zeros(len(net),np.int8)
        strong=valid&(er>=.6)&(np.abs(net)>=2);direction[strong]=np.where(net[strong]>0,1,-1)
        np.testing.assert_array_equal(saved['points'],points);np.testing.assert_array_equal(saved['known'],valid);np.testing.assert_array_equal(saved['direction'],direction)
        np.testing.assert_array_equal(saved['net_ticks'][valid],net[valid]);np.testing.assert_array_equal(saved['ER'][valid],er[valid]);A.COUNT['全行独立三点資格']+=len(net)
        if label=='peer':A.check(np.all(m['sample_tables']['peer']['times'][index[valid],-1]<record['time_s'][valid]),'厳密過去peer選択')


def diagnostic_units(output: dict, symbol: str) -> None:
    """
    機能: 半量派生も含め、実リスク円とraw_r価格幅及び予算円の単位を検査する。
    引数: output(dict)、symbol(str)は保存台帳と商品。
    返り値: None。code2価格幅を金額のように半量化する誤りを拒否する。
    """
    mult=1000 if symbol=='TOPIX' else 10;q=output['quantity'];columns=output['control_stat_columns'];stats=output['control_stats']
    budget=output['initial_width']*q*mult*output['component_settings']['session_budget_multiple']
    A.equal(stats[columns.index('session_budget_yen')],budget,'診断単位/予算円')
    A.check(not stats[columns.index('session_brake_enabled')] and not stats[columns.index('brake_latched')],'brake部品off')
    for event in output['control_events']:
        code=int(event[4]);parent=int(event[3]);j=output['judgments'][output['judgments'][:,3]==parent]
        if not len(j):continue
        risk=float(j[0,27])
        if code in (1,10):A.equal(event[11],risk,'診断単位/initialrisk円')
        if code==2:A.equal(event[11],risk/(q*mult),'診断単位/raw_r価格幅')


def map_entries(output: dict, record: dict) -> dict:
    """
    機能: 保存の実親を原入口seqと売買へ対応し、元金融の寄与関数に依存しない。
    引数: output/record(dict)は台帳と正常原seq。
    返り値: dictは同入口実親。sourceも残しC/Rの取り違えを検出する。
    """
    result={}
    for t in output['trades']:
        key=str(int(record['seq'][int(t[15])]))+'|'+str(int(t[4]));A.check(key not in result,'寄与入口一意')
        result[key]=dict(net=float(t[11]),entry_row=int(t[2]),entry=float(t[6]),source=int(t[1]),q=int(t[5]),exit_row=int(t[3]))
    return result


def contribution(old: dict, new: dict) -> dict:
    """
    機能: 実入口の消失・新增・共通の損益変化を独立集合式で分ける。
    引数: old/new(dict)は同量・同入力の元親と変更親。
    返り値: dictは5項目。消失を全て予測成功とは呼ばない。
    """
    removed=set(old)-set(new);added=set(new)-set(old);common=set(old)&set(new)
    for key in common:
        A.check(all(old[key][k]==new[key][k] for k in ('entry_row','entry','source','q')),'共通入口実価格枚数源同値')
    return dict(収支変化=sum(x['net'] for x in new.values())-sum(x['net'] for x in old.values()),
        避けた基準損失=sum(-old[k]['net'] for k in removed if old[k]['net']<0),
        失った基準利益=sum(old[k]['net'] for k in removed if old[k]['net']>0),
        共通入口の出口変化=sum(new[k]['net']-old[k]['net'] for k in common),新たな入口の収支=sum(new[k]['net'] for k in added))


def main() -> None:
    """
    機能: 根正式金融完了後に1188小会計・66実派生・固定抽出の新台帳を一回検算する。
    引数: なし。元板/NPZ/API/金融executeを呼ばない。
    返り値: Noneは私有保存監査証跡。全792実台帳の検査と誤称しない。
    """
    destination=HERE/'local_全33小会計と保存C及び抽出新台帳の独立監査.json';A.check(not destination.exists(),'同監査再実行なし')
    fixed=A.read_json(SOURCE/'事前固定.json');results=A.read_json(SOURCE/'finance/results.json');meta=A.read_json(SOURCE/'全33場の直近位相準備.json')
    before={n:A.sha(ROOT/n) for n in fixed['source_SHA256']};A.check(before==fixed['source_SHA256'],'事前固定源一致')
    A.check(results['configs']==fixed['configs'] and results['sessions']==fixed['sessions'],'全条件入力固定')
    A.check(results['account_count']==792 and results['display_account_count']==1188 and results['actual_financial_conditions']==12 and results['alias_conditions']==6,'実派生件数分離')
    A.check(results['alias_replays']==results['baseline_replays']==results['original_book_reads']==results['current_API_reads']==0,'根再生範囲')
    sessions=results['sessions'];configs={c['id']:c for c in results['configs']};stability={};rows={};samples=set();worst={}
    for ident,case in results['cases'].items():
        A.check(len(case['rows'])==66 and len({(r['session'],r['symbol']) for r in case['rows']})==66,'全掲載商品場一意');stability[ident]={};worst[ident]={}
        for symbol in ('TOPIX','NK225'):
            selected=[r for r in case['rows'] if r['symbol']==symbol]
            for r in selected:A.row_check(r,configs[ident]['quantity'][symbol]);rows[ident,r['session'],symbol]=r
            stability[ident][symbol]=A.summary_check(selected,case['summary'][symbol],sessions)
            negatives=sorted([r for r in selected if r['net']<0],key=lambda r:(r['net'],r['session']))[:3]
            worst[ident][symbol]=[r['session'] for r in negatives]
            if configs[ident]['local_policy']!='ALIGNED':
                active=[r for r in selected if r['campaigns']]
                if active:samples.add((ident,active[0]['session'],symbol))
                samples.update((ident,r['session'],symbol) for r in negatives)
    alias_id=next(c['id'] for c in configs.values() if c['local_policy']=='ALIGNED')
    cr={(r['session'],r['symbol']):r for r in results['derived_C_comparator']['rows']};A.check(len(cr)==66,'C半量66口座')
    for ident,c in configs.items():
        if c['local_policy']=='ALIGNED':
            for r in results['cases'][ident]['rows']:
                A.compare_totals(r,A.totals([cr[r['session'],r['symbol']]]),'ALIGNED半量引用数値');A.check(r['derived'] and r['selected_R']==0,'ALIGNEDは新R活動なし')
    # ----------------------------------------
    # 保存派生66口座は全て読む。新実金融は初回活動と各赤字上位3の機械抽出だけ。
    plan=dict(新実抽出=sorted(samples),C全実派生=66,根金融再生=0,新実抽出規則='各条件商品で時系列最初の活動＋赤字上位3。入力読取前に機械選定。')
    (HERE/'local_独立保存監査の抽出計画.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    sys.path.insert(0,str(SOURCE));import selection;import derivation
    account=A.load_module('独立局所保存会計検査',SOURCE/'engine/accounting.py');reads={};inputs={};checked=[];causes={};sample_contributions=[]
    for session in sessions:
        packet=A.unpack(meta['cache'][session],inputs)
        for symbol in ('TOPIX','NK225'):short_oracle(packet,symbol)
        selected=sorted(key for key in samples if key[1]==session)
        selected.extend((alias_id,session,symbol) for symbol in ('TOPIX','NK225'))
        baseline_cache={}
        saved_deltas=A.read_json(SOURCE/'finance/session_contributions'/f'{session}.json')
        for ident,_,symbol in selected:
            item=results['cases'][ident]['ledgers'][session][symbol];out=A.unpack(item,reads);record=packet['prepared'][symbol]['record'];r=rows[ident,session,symbol]
            A.check(out['row_count']==len(record['seq']),'正常列行数一致')
            for name in ('curve','source_curve','target_trace'):out[name]=A.expand(out[name],out['row_count'])
            normal=derivation.c_normal(packet,symbol) if configs[ident]['local_policy']=='ALIGNED' else selection.build(packet,symbol,configs[ident])
            A.physical(record,out,r);A.causality(record,out,normal,configs[ident]);diagnostic_units(out,symbol)
            verified=account.inspect((session,symbol),record,out,normal);A.compare_totals(r,A.totals([verified]),'四引数保存会計')
            A.check(out['selection_diagnostics']==normal['decisions'],'当時保存根拠一致')
            checked.append(dict(id=ident,session=session,symbol=symbol,derived=bool(item['derived']),parents=len(out['trades']),orders=len(out['orders']),SHA256=item['SHA256']))
            mapping=map_entries(out,record);baseid=configs[ident]['base_id'];key=baseid,symbol
            if key not in baseline_cache:
                olditem=results['baselines'][baseid]['ledgers'][session][symbol];old=A.unpack(olditem,reads);baseline_cache[key]=map_entries(old,record);del old
            delta=contribution(baseline_cache[key],mapping)
            for field in FIELDS:A.equal(saved_deltas[ident][symbol][field],delta[field],'実親集合の5寄与')
            sample_contributions.append(dict(id=ident,session=session,symbol=symbol,**delta))
            if session in worst[ident][symbol]:
                parents=A.cost_trades(record,out)
                losses=[p for p in parents if p['収支']<0]
                causes.setdefault(ident,{})[symbol]=causes.get(ident,{}).get(symbol,[])+[dict(session=session,収支=r['net'],
                    負親数=len(losses),最初の負親=losses[0] if losses else None,最悪負親=min(losses,key=lambda p:p['収支']) if losses else None,
                    寄与5項目=delta)]
            del out,normal
        del packet
        print(session+'：保存C全数と抽出新局所台帳の会計/位相/寄与',flush=True)
    # ----------------------------------------
    # 全1188行の損益差と保存寄与加算を検査。元同入口出口は固定で差の分類は事後だけ。
    all_delta={ident:{s:defaultdict(float) for s in ('TOPIX','NK225')} for ident in configs}
    for session in sessions:
        ds=A.read_json(SOURCE/'finance/session_contributions'/f'{session}.json')
        for ident,c in configs.items():
            for symbol in ('TOPIX','NK225'):
                d=ds[ident][symbol];base=next(r for r in results['baselines'][c['base_id']]['rows'] if r['session']==session and r['symbol']==symbol)
                A.equal(d['収支変化'],rows[ident,session,symbol]['net']-base['net'],'全行元基準差')
                A.equal(d['収支変化'],d['避けた基準損失']-d['失った基準利益']+d['共通入口の出口変化']+d['新たな入口の収支'],'全行5寄与恒等式')
                for field in FIELDS:all_delta[ident][symbol][field]+=d[field]
    for ident in configs:
        for symbol in ('TOPIX','NK225'):
            for field in FIELDS:A.equal(all_delta[ident][symbol][field],results['diagnosis'][ident][symbol][field],'全33寄与合計')
    A.check(before=={n:A.sha(ROOT/n) for n in before},'監査開始終端source一致')
    proof=dict(全合格=True,scope='表示1188小会計全数、保存派生C66台帳全数、独立事前抽出の新実台帳。新792台帳の全数検査とは呼ばない。',
        新実金融条件=12,新実金融口座=792,表示条件=18,表示小会計口座=1188,ALIGNED別名=6,C全数実派生=66,
        抽出新実台帳数=sum(not x['derived'] for x in checked),基準保存台帳照合='抽出比較に必要な同場同量6AUTOだけを一回ずつ読む。再生0。',
        抽出計画SHA256=A.sha(HERE/'local_独立保存監査の抽出計画.json'),検査件数=dict(A.COUNT),合計=sum(A.COUNT.values()),
        安定性=stability,最大赤字3場の親と失った勝ちの寄与=causes,抽出実親の独立寄与=sample_contributions,全33寄与=all_delta,実検査台帳=checked,
        入力読取=dict(local_packet=len(inputs),実台帳=len(reads),原本=0,NPZ=0,API=0),金融再生=0,registry変更=0,
        入力SHA256={**inputs,**reads},source_SHA256=before,source開始終端一致=True,レビューsource_SHA256=A.sha(Path(__file__)),
        正本SHA256={str(p.relative_to(ROOT)):A.sha(p) for p in (SOURCE/'finance/results.json',SOURCE/'事前固定.json',SOURCE/'試行計画.json')},
        限界=['ALIGNED6は既知33でR候補が消えた同一C戦略。新しい6勝や方向予測成功に数えない。',
            '入口の消失には局所拒否・取消以外に、別の保有による忙しさと休止の経路差がある。避けた損失は全て予測改善ではない。',
            '全33は既知研究データ。最大黒字3場除外/前後半/買売は事後の頑健性点検、未来選別へ使わない。',
            'CurrentPriceTimeは受信時計でない。sample三点を全quote経路と呼ばず、見えない数量補充を新たに実証していない。'])
    destination.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print('局所保存金融の独立監査合格',len(checked),'台帳',sum(A.COUNT.values()),'検査',flush=True)


if __name__=='__main__':main()
