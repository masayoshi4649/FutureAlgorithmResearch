"""第四段階の保存台帳を初回玉・追加玉・床・価格飛びへ分解する。売買再生は行わない。"""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import argparse
import importlib.util
import json
import pickle
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
JST=timezone(timedelta(hours=9))
PAIRS=[('GU','S1'),('GU','S2'),('S2','J1_N'),('J1_N','J1_R'),('J1_N','J1_Z'),
       ('S2','J1_R'),('S2','J1_Z'),('S2','D05_R'),('D05_R','D05_Z'),
       ('D05_R','D10_R'),('D05_R','L05_R'),('L05_R','L05_Z'),('J1_R','D05_R')]


def module(name,path):
    """
    機能: 既存資料を読む補助関数だけを固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    out=importlib.util.module_from_spec(spec);sys.modules[name]=out;spec.loader.exec_module(out)
    return out


helper=module('wave87_allocation_helper',ROOT/'work/wave_v86/analysis/independent.py')


def stamp(value):
    """
    機能: 代理時計を日本時間へ変換する。
    引数: value(float)。
    返り値: str。
    """
    return datetime.fromtimestamp(float(value),JST).isoformat()


def trade_summary(trades):
    """
    機能: 複数の新規・返済脚を料金付きで合算する。
    引数: trades(list[dict])。
    返り値: dict。ここでの利益・損失は決済脚単位。
    """
    return dict(legs=len(trades),lots=sum(int(x['枚数']) for x in trades),
        gross=float(sum(x['利益損失前'] for x in trades)),fees=float(sum(x['手数料'] for x in trades)),
        net=float(sum(x['収支'] for x in trades)),
        profit=float(sum(max(x['収支'],0.) for x in trades)),
        loss=float(sum(max(-x['収支'],0.) for x in trades)))


def entry_key(c):
    """
    機能: 親組の最初の原本新規行と方向だけで対応付ける。
    引数: c(dict)。
    返り値: tuple。
    """
    return c['session'],c['symbol'],c['entry_seq'],c['direction']


def extract(accounts,result,inputs):
    """
    機能: 追加を含む親組会計と、床超過の実行順を保存台帳から復元する。
    引数: accounts/result/inputs(dict)。
    返り値: list[dict]。注文の新規再生・閾値探索は行わない。
    """
    output=[]
    config=result['config']
    for key,account in sorted(accounts.items()):
        r=inputs[key]
        value=1000. if key[1]=='TOPIX' else 10.
        groups=defaultdict(list)
        for t in account['net_trades']:groups[int(t['組'])].append(t)
        local=[]
        for cyc in account['cycles']:
            cid,first,last,side=int(cyc[0]),int(cyc[1]),int(cyc[2]),int(cyc[8])
            trades=groups[cid]
            ordermask=account['orders'][:,2]==cid
            orders=account['orders'][ordermask]
            fees=account['fees'][ordermask]
            initial_order=orders[(orders[:,0]==first)&(orders[:,7]==1)]
            assert len(initial_order)==1
            initial_qty=int(initial_order[0,4]);initial_price=float(initial_order[0,5]);atr=float(cyc[5])
            initial_trades=[t for t in trades if int(t['新規行'])==first]
            additional_trades=[t for t in trades if int(t['新規行'])!=first]
            summary=trade_summary(trades)
            initial=trade_summary(initial_trades);additional=trade_summary(additional_trades)
            assert abs(summary['fees']-float(fees.sum()))<1e-6
            assert abs(summary['net']-initial['net']-additional['net'])<1e-6
            events=account['allocation_events'][account['allocation_events'][:,1]==cid]
            adds=events[events[:,2]==2]
            floors=events[events[:,2]==3]
            stops=events[events[:,2]==6]
            budget=initial_qty*.75*atr*value
            # ----------------------------------------
            # 全既約定を現在値で評価するだけ。将来の指示・返済は生成しない。
            span=last-first+1
            cash_delta=np.zeros(span);qty_delta=np.zeros(span);fee_delta=np.zeros(span)
            oi=orders[:,0].astype(int)-first
            np.add.at(cash_delta,oi,-orders[:,3]*orders[:,4]*orders[:,5]*value)
            np.add.at(qty_delta,oi,orders[:,3]*orders[:,4])
            np.add.at(fee_delta,oi,fees)
            quantity=np.cumsum(qty_delta)
            marked=np.cumsum(cash_delta)+quantity*r['last'][first:last+1]*value-np.cumsum(fee_delta)
            good=np.isfinite(marked)&np.isfinite(r['last'][first:last+1])&(r['last'][first:last+1]>0)
            assert quantity[-1]==0 and abs(marked[-1]-summary['net'])<1e-5
            valid_rows=np.flatnonzero(good)
            min_index=int(valid_rows[np.argmin(marked[good])])
            max_index=int(valid_rows[np.argmax(marked[good])])
            final_orders=orders[(orders[:,0]==last)&(orders[:,7]==0)]
            final_qty=int(final_orders[:,4].sum())
            assert final_qty>0
            final_price=float(np.average(final_orders[:,5],weights=final_orders[:,4]))
            active=floors[floors[:,0]<last]
            floor=None
            if len(active):
                f=active[-1]
                floor_price=float(f[6]);floor_row=int(f[0])
                execution_loss=side*(floor_price-final_price)*final_qty*value
                floor_net=summary['net']+execution_loss
                before=np.flatnonzero(np.isfinite(r['last'][:last])&(r['last'][:last]>0))
                previous=int(before[-1]) if len(before) else None
                floor=dict(row=floor_row,jst=stamp(r['time_s'][floor_row]),price=floor_price,
                    age_seconds=float(r['time_s'][last]-r['time_s'][floor_row]),
                    line_to_fill_adverse_points=float(side*(floor_price-final_price)),
                    line_to_fill_net_change=float(-execution_loss),
                    last_exit_quantity=final_qty,net_if_final_exit_at_floor=float(floor_net),
                    previous_valid_row=previous,
                    previous_valid_price=float(r['last'][previous]) if previous is not None else None,
                    last_observation_gap_seconds=float(r['time_s'][last]-r['time_s'][previous]) if previous is not None else None)
            exceeded=summary['net'] < -budget-1e-6
            if not exceeded:
                category='最終親組収支は初回名目予算内'
            elif not len(adds):
                category='追加前に終了・新床は未発動'
            elif not config['floor_mode']:
                category='新床なし・既存1ATR予算による返済等'
            elif floor and floor['net_if_final_exit_at_floor'] >= -budget-1e-5:
                category='床価格なら予算内だが返済価格が通過'
            elif not floor:
                category='追加後の床有効前に返済'
            else:
                category='床だけでは説明しきれない予算超過'
            item=dict(session=key[0],symbol=key[1],campaign=cid,direction=side,
                entry_row=first,entry_seq=int(r['seq'][first]),entry_jst=stamp(r['time_s'][first]),
                exit_row=last,exit_jst=stamp(r['time_s'][last]),initial_qty=initial_qty,
                initial_price=initial_price,atr=atr,budget=budget,max_held=int(cyc[6]),
                gross=summary['gross'],fees=summary['fees'],net=summary['net'],
                initial_legs=initial,additional_legs=additional,add_count=len(adds),
                initial_exit_reasons={str(reason):trade_summary([t for t in initial_trades if int(t['理由'])==reason])
                    for reason in sorted(set(int(t['理由']) for t in initial_trades))},
                total_opened=int(orders[orders[:,7]==1,4].sum()),
                exit_reasons=sorted(set(int(x[6]) for x in final_orders)),
                full_exit_price=final_price,full_exit_qty=final_qty,
                actual_worst_mark=float(marked[min_index]),worst_mark_row=first+min_index,
                worst_mark_jst=stamp(r['time_s'][first+min_index]),
                actual_best_mark=float(marked[max_index]),best_mark_row=first+max_index,
                best_mark_to_final=float(marked[max_index]-summary['net']),
                budget_exceeded=exceeded,budget_excess=max(0.,-summary['net']-budget),
                budget_category=category,last_active_floor=floor,
                add_stops=[dict(row=int(e[0]),jst=stamp(r['time_s'][int(e[0])]),reason=int(e[12])) for e in stops],
                additions=[])
            for e in adds:
                addrow=int(e[0]);same=floors[floors[:,0]==addrow]
                afterline=float(same[-1,6]) if len(same) else None
                item['additions'].append(dict(row=addrow,source=int(e[3]),
                    jst=stamp(r['time_s'][addrow]),qty=int(e[5]),price=float(e[6]),opened=int(e[7]),
                    initial_price_advance_atr=float(side*(e[6]-initial_price)/atr),
                    mark_after_fill=float(marked[addrow-first]),floor_published_after_fill=afterline,
                    remaining_retrace_atr=(float(side*(e[6]-afterline)/atr) if afterline is not None else None)))
            local.append(item)
        saved=next(x for x in result['rows'] if (x['session'],x['symbol'])==key)
        sums=helper.summarize(local)
        for a,b in [('net','net'),('gross','gross'),('fees','fees'),('cycles','cycles'),('profit','cycle_profit'),('loss','cycle_loss')]:
            assert abs(sums[a]-saved[b])<1e-6,(key,a,sums[a],saved[b])
        output.extend(local)
    return output


def compare(before,after,symbol,sessions):
    """
    機能: 共通の最初入口ごとに初回玉変化と追加玉変化を分離する。
    引数: before/after(list[dict])、symbol(str)、sessions(set[str])。
    返り値: dict。完全な因果分解とは呼ばず、入口経路変更も残す。
    """
    left={entry_key(c):c for c in before if c['symbol']==symbol and c['session'] in sessions}
    right={entry_key(c):c for c in after if c['symbol']==symbol and c['session'] in sessions}
    assert len(left)==sum(c['symbol']==symbol and c['session'] in sessions for c in before)
    assert len(right)==sum(c['symbol']==symbol and c['session'] in sessions for c in after)
    keys=left.keys()&right.keys()
    initial_change=sum(right[k]['initial_legs']['net']-left[k]['initial_legs']['net'] for k in keys)
    additional_change=sum(right[k]['additional_legs']['net']-left[k]['additional_legs']['net'] for k in keys)
    added=[right[k] for k in right.keys()-left.keys()]
    removed=[left[k] for k in left.keys()-right.keys()]
    delta=sum(c['net'] for c in right.values())-sum(c['net'] for c in left.values())
    assert abs(delta-initial_change-additional_change-sum(c['net'] for c in added)+sum(c['net'] for c in removed))<1e-6
    ratios=[]
    for k in keys:
        ratio=right[k]['initial_qty']/left[k]['initial_qty']
        ratios.append(dict(session=right[k]['session'],entry_jst=right[k]['entry_jst'],
            quantity_ratio=ratio,gross_difference_from_initial_scaling=right[k]['gross']-ratio*left[k]['gross'],
            before_net=left[k]['net'],after_net=right[k]['net'],net_change=right[k]['net']-left[k]['net']))
    return dict(before=helper.summarize(list(left.values())),after=helper.summarize(list(right.values())),
        common_entries=len(keys),追加入口=helper.summarize(added),消失入口=helper.summarize(removed),
        収支差=delta,共通初回玉収支差=initial_change,共通追加玉収支差=additional_change,
        差分会計一致=True,同入口差分=ratios)


def main():
    """
    機能: 全二十二保存結果の完了後、予算超過と数量部品の効果を診断する。
    引数: なし。
    返り値: None。今回analysis以外へ書き込まない。
    """
    parser=argparse.ArgumentParser(description='少枚数・順行追加の保存結果を独立分解する')
    parser.add_argument('--round',choices=['round4','round6'],default='round6')
    args=parser.parse_args()
    target=HERE.parent/args.round
    fixed=helper.read(target/'事前固定.json')
    identifiers=[c['id'] for c in fixed['catalog']]
    missing=[str(target/m/'results'/(i+'.json')) for m in fixed['models'] for i in identifiers
             if not (target/m/'results'/(i+'.json')).exists()]
    if missing:raise RuntimeError('全二十二結果の完了待ち: '+str(len(missing))+'件')
    prepare=module('wave87_allocation_prepare',ROOT/'work/wave_v85/prepare.py')
    inputs,signals,hashes=prepare.load_inputs(verify=True)
    del signals
    assert hashes==fixed['input_SHA256']
    sources={};summaries=[];comparisons=[];details=[];examples=[]
    for model in fixed['models']:
        campaigns={}
        for ident in identifiers:
            result_path=target/model/'results'/(ident+'.json')
            ledger_path=target/model/'ledgers'/(ident+'.pkl')
            result=helper.read(result_path)
            assert helper.sha(ledger_path)==result['ledger_SHA256']
            accounts=pickle.loads(ledger_path.read_bytes())
            local=extract(accounts,result,inputs)
            canonical=ident.removeprefix('A_')
            campaigns[canonical]=local
            sources[str(result_path.relative_to(ROOT))]=helper.sha(result_path)
            sources[str(ledger_path.relative_to(ROOT))]=result['ledger_SHA256']
            for period in ('前16','後14','全30'):
                for symbol in ('TOPIX','NK225'):
                    subset=[x for x in local if x['symbol']==symbol and x['session'] in fixed[period]]
                    budget_groups=defaultdict(list)
                    for x in subset:budget_groups[x['budget_category']].append(x)
                    summaries.append(dict(model=model,id=ident,base_id=canonical,period=period,symbol=symbol,
                        **helper.summarize(subset),
                        initial_gross=sum(x['initial_legs']['gross'] for x in subset),
                        initial_fees=sum(x['initial_legs']['fees'] for x in subset),
                        initial_net=sum(x['initial_legs']['net'] for x in subset),
                        additional_gross=sum(x['additional_legs']['gross'] for x in subset),
                        additional_fees=sum(x['additional_legs']['fees'] for x in subset),
                        additional_net=sum(x['additional_legs']['net'] for x in subset),
                        actual_add_orders=sum(x['add_count'] for x in subset),
                        max_held=max((x['max_held'] for x in subset),default=0),
                        max_parent_loss=max(0.,max((-x['net'] for x in subset),default=0)),
                        budget_groups={k:helper.summarize(v) for k,v in budget_groups.items()},
                        added_and_exceeded=helper.summarize([x for x in subset if x['add_count'] and x['budget_exceeded']]),
                        旧1ATR予算返済組=helper.summarize([x for x in subset if 32 in x['exit_reasons']]),
                        床返済組=helper.summarize([x for x in subset if 76 in x['exit_reasons']])))
            details.extend(dict(x,model=model,id=ident) for x in local)
            for symbol in ('TOPIX','NK225'):
                examples.extend(dict(x,model=model,id=ident) for x in
                    sorted((x for x in local if x['symbol']==symbol and x['add_count'] and x['budget_exceeded']),
                           key=lambda x:x['budget_excess'],reverse=True)[:3])
            print(model,ident,'数量・親組会計・床照合済み',flush=True)
            del accounts
        for before,after in PAIRS:
            for period in ('前16','後14','全30'):
                for symbol in ('TOPIX','NK225'):
                    comparisons.append(dict(model=model,before_id=before,after_id=after,period=period,symbol=symbol,
                        **compare(campaigns[before],campaigns[after],symbol,set(fixed[period]))))
    output=dict(実行元=args.round,定義=dict(
        範囲='全22保存結果だけの読取。新しい売買再生・パラメータ探索なし。全30場既知。',
        親組='最初の入口から全返済まで。初回と追加の全新規/返済料金・全脚損益を合算する。',
        比較='最初の原本新規行と方向で照合。初回玉の返済経路自体も追加・床で変わるため、追加脚だけで全効果とはしない。',
        少枚数='整数切捨てでB00/部分利確の割合が変わる。元GUの単純な金額換算とは区別する。',
        予算='初回枚数×0.75ATR×円倍率の名目額。新床は追加後にだけ有効。初回だけの損切りは料金・丸め・価格飛びで名目額を超える場合がある。',
        新床なし='J1_Nにも元GUの実組1ATR損失予算による次行全返済は残る。無制限の保有ではなく、新しい0.75ATR又は0円の価格床だけを追加しない対照。',
        通過='最後に公開済みの床へ最終返済部分だけを置換した反実仮想の会計で差額を説明する。これを実現可能損益や新手法の成績とはしない。',
        時価='保有中の現在値評価は既払料金控除。将来返済料金は最終実収支だけに反映。新注文は生成していない。',
        時計='CurrentPriceTime代理時計。隣接原本行の同時計は情報更新の無さと同義ではない。'),
        input_SHA256=hashes,source_SHA256=sources,期間成績=summaries,対照=comparisons,
        追加後予算超過の最大例=examples,全親組=details)
    path=HERE/'第四段階の数量効果と予算超過診断.json'
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('診断保存',path,'親組',len(details),flush=True)


if __name__=='__main__':
    main()
