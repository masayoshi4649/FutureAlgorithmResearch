"""完了したR_PRICE台帳の原因だけを読み、売買条件へ事後値を戻さない。"""

import argparse
from collections import defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
RANGE=HERE.parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(RANGE))
import common

DATA=common.module('106R_PRICE原因の保存入力',RANGE/'data.py')
JST=timezone(timedelta(hours=9))


def clock(record: dict, row: int) -> dict:
    """
    機能: 原normal行と価格代理時計を同時に記載する。
    引数: record(dict)、row(int)は正常保存列と原行。
    返り値: dictはrow/seq/JST。板受信時刻や注文遅延へ変換しない。
    """
    return dict(row=int(row),raw_seq=int(record['seq'][row]),price_time_s=float(record['time_s'][row]),
        JST=datetime.fromtimestamp(float(record['time_s'][row]),JST).isoformat())


def extrema(record: dict, trade: np.ndarray) -> dict:
    """
    機能: 実保有区間の清算BBOで最大順逆行と料込最高清算額を算出する。
    引数: record(dict)、trade(ndarray)は正常列と完結親。
    返り値: dictは事後値。未観測極値を補完せず、入口への正答率と呼ばない。
    """
    entry,exit=int(trade[2]),int(trade[3]);side=int(trade[4]);q=int(trade[5]);E=float(trade[6])
    indexes=np.arange(entry,exit+1);bid,ask=record['bid'][indexes],record['ask'][indexes]
    valid=record['quote_valid'][indexes]&np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid)
    indexes=indexes[valid];assert len(indexes)
    price=record['bid'][indexes] if side==1 else record['ask'][indexes]
    movement=side*(price-E);best,worst=int(np.argmax(movement)),int(np.argmin(movement))
    multiplier=1000. if record['symbol']=='TOPIX' else 10.;fee=float(trade[8]+trade[9]);net=movement*q*multiplier-fee
    maximum=float(net[best]);actual=float(trade[11])
    return dict(MFE_ticks=max(0.,float(movement[best]))/record['tick'],MAE_ticks=max(0.,float(-movement[worst]))/record['tick'],
        best_liquidation_net=maximum,best_clock=clock(record,int(indexes[best])),worst_clock=clock(record,int(indexes[worst])),
        positive_equity_seen=bool(maximum>1e-5),profit_given_back=max(0.,maximum-actual) if maximum>1e-5 else 0.,
        normal_quote_observations=len(indexes),definition='費用後最高清算額が正の場合だけ利益返しを記載。MFE/MAEは清算側BBO、事後の観測正常行だけ。')


def mode_path(record: dict, states: np.ndarray, trade: np.ndarray) -> dict:
    """
    機能: 保有区間で保存済み因果状態が変わった最初の原行と反対TRENDを記載する。
    引数: record(dict)、states(ndarray[int8])、trade(ndarray)は価格・過去六点状態・親。
    返り値: dictは事後の状態経路。現24手法にmode退出を追加していない。
    """
    entry,exit=int(trade[2]),int(trade[3]);side=int(trade[4]);indexes=np.arange(entry,exit+1)
    values=states[indexes];different=indexes[values!=states[entry]];opposing=indexes[values==-2*side]
    known_trend=indexes[(values==2)|(values==-2)]
    return dict(decision_mode=int(states[int(trade[15])]),fill_mode=int(states[entry]),exit_mode=int(states[exit]),
        first_change=clock(record,int(different[0])) if len(different) else None,
        first_known_trend=clock(record,int(known_trend[0])) if len(known_trend) else None,
        first_opposing_trend=clock(record,int(opposing[0])) if len(opposing) else None,
        observed_opposing_trend=bool(len(opposing)),
        row_counts={str(code):int(np.count_nonzero(values==code)) for code in (0,1,2,-2,3)},
        definition='0UNKNOWN/1RANGE/2買方向TREND/-2売方向TREND/3NEUTRAL。行数は原normal数であり独立試行数ではない。')


def describe(record: dict, measured: dict, ledger: dict, trade: np.ndarray, config: dict) -> dict:
    """
    機能: 判断RRと実fill、固定線、後のmode・利益返し・返済差を一親ごとに分ける。
    引数: record/measured/ledger/config(dict)、trade(ndarray)は保存入力・台帳・固定設定・実R親。
    返り値: dictは原因材料。改善後のcounterfactual損益を計算しない。
    """
    ident=int(trade[0]);entry,exit,decision=int(trade[2]),int(trade[3]),int(trade[15]);side=int(trade[4]);q=int(trade[5])
    diag=next(d for d in ledger['raw_entry_diagnostics'] if int(d['parent_id'])==ident);episode=diag['episode']
    stop,target=float(episode['stop_price']),float(episode['target_price']);E=float(trade[6]);fee=float(trade[8]+trade[9])
    multiplier=1000. if record['symbol']=='TOPIX' else 10.;epsilon=float(record['tick'])*1e-8
    clearing=float(record['bid'][entry] if side==1 else record['ask'][entry]);broken=side*(clearing-stop)<=epsilon
    actual_risk=side*(E-stop)*q*multiplier+fee;actual_room=side*(target-E)*q*multiplier-fee
    exit_order=next(o for o in ledger['orders'] if int(o[2])==ident and not o[7]);exit_decision=int(exit_order[1])
    decision_quote=float(record['bid'][exit_decision] if side==1 else record['ask'][exit_decision])
    decision_net=side*(decision_quote-E)*q*multiplier-fee
    ext=extrema(record,trade);modes=mode_path(record,measured['states'][str(config['range_er'])],trade)
    final_net=float(trade[11]);reason=int(trade[13])
    if broken:category='実fill時に固定stop外'
    elif reason==10 and final_net<decision_net-1e-5:category='中心到達判断後の次quote悪化'
    elif reason==11 and modes['observed_opposing_trend']:category='反対TREND観測後も固定stopまで保持'
    elif final_net<0 and ext['positive_equity_seen']:category='費用後順行利益を返して赤字'
    elif final_net<0:category='費用後順行利益なく局所反発不成立'
    else:category='固定中心又は予定返済で黒字'
    return dict(parent_id=ident,side='買い' if side==1 else '売り',quantity=q,net=final_net,category=category,
        decision=dict(clock=clock(record,decision),bid=float(record['bid'][decision]),ask=float(record['ask'][decision]),
            entry_mode=episode['entry_mode'],fixed_low=episode['fixed_low'],fixed_high=episode['fixed_high'],fixed_centre=episode['fixed_centre'],
            rounded_stop=stop,rounded_target=target,planned_entry=episode['planned_entry'],
            planned_net_profit=episode['planned_net_profit'],planned_net_loss=episode['planned_net_loss'],
            planned_RR=episode['fee_included_ratio'],own_six=episode['own_six'],peer_six=episode['peer_six'],
            prior_quote=clock(record,int(episode['prior_quote_row']))),
        fill=dict(clock=clock(record,entry),actual_price=E,exact_roundtrip_fees=fee,
            adverse_gap_ticks=side*(E-float(episode['planned_entry']))/record['tick'],
            price_time_delta_seconds=float(record['time_s'][entry]-record['time_s'][decision]),
            normal_row_delta=entry-decision,signed_initial_net_risk=actual_risk,net_target_room=actual_room,
            actual_RR=actual_room/actual_risk if actual_risk>0 and not broken else None,
            fixed_stop_broken=bool(broken),target_already_reached=bool(side*(clearing-target)>=-epsilon),
            known_trend_on_fill=diag['fill_known_trend']),
        held=dict(mode=modes,extrema=ext),
        exit=dict(reason=reason,decision_clock=clock(record,exit_decision),fill_clock=clock(record,exit),
            decision_liquidation_net=decision_net,actual_net=final_net,
            next_quote_deterioration=decision_net-final_net,actual_price=float(trade[7])),
        qualifiers=dict(fill_stop_broken=bool(broken),opposing_trend_observed=modes['observed_opposing_trend'],
            positive_equity_seen=ext['positive_equity_seen'],target_then_worse=bool(reason==10 and final_net<decision_net-1e-5)),
        limitation='RRは予定線の比率で勝つ確率ではない。反対TREND退出は今回24へ未追加。時点/分類だけを示し、その後の金融改善と混同しない。')


def add_group(groups: dict, name: str, item: dict) -> None:
    """
    機能: 全R親の同じ事後分類へ、黒字反証と正しい親分母を加える。
    引数: groups(dict)、name(str)、item(dict)は分類集計と一親の説明。
    返り値: None。損失親だけから予防効果を作らない。
    """
    value=groups.setdefault(name,dict(parents=0,wins=0,losses=0,profit=0.,loss=0.,net=0.))
    net=item['net'];value['parents']+=1;value['wins']+=int(net>1e-5);value['losses']+=int(net<-1e-5)
    value['profit']+=max(0.,net);value['loss']+=max(0.,-net);value['net']+=net


def run() -> None:
    """
    機能: 完了24結果だけから全R親の反証分母と最大赤字場の具体親を保存する。
    引数: なし。
    返り値: None。各場input一読・台帳順読、金融関数を一切呼ばない。
    """
    target=HERE/'全24のR損失場と判断約定及びmode変化.json';assert not target.exists()
    results=common.read(RANGE/'results.json');assert results['全合格'] and len(results['configs'])==24
    inputs=common.read(RANGE/'全33場の価格境界反発準備.json');assert inputs['全合格']
    selected={};output={};ledger_reads=0
    for cfg in results['configs']:
        ident=cfg['id'];output[ident]={};selected[ident]={}
        for symbol in ('TOPIX','NK225'):
            active=[r for r in results['cases'][ident]['rows'] if r['symbol']==symbol and r['sources']['O06']['campaigns']>0]
            chosen=[]
            if active:
                worst=min(active,key=lambda r:(r['sources']['O06']['net'],r['session']))
                largest=max(active,key=lambda r:(r['sources']['O06']['loss'],-results['sessions'].index(r['session'])))
                if worst['sources']['O06']['net']<0:chosen.append(worst['session'])
                if largest['sources']['O06']['loss']>0 and largest['session'] not in chosen:chosen.append(largest['session'])
            selected[ident][symbol]=set(chosen)
            output[ident][symbol]=dict(all_R=dict(parents=0,wins=0,losses=0,profit=0.,loss=0.,net=0.),
                groups={},qualifiers={},directions={},selected_sessions={s:dict(parents=[],R_source_row=next(r['sources']['O06'] for r in active if r['session']==s)) for s in chosen})
    for session in results['sessions']:
        packet=DATA.load_session(session)
        for cfg in results['configs']:
            ident=cfg['id']
            for symbol in ('TOPIX','NK225'):
                aggregate=output[ident][symbol]
                row=next(r for r in results['cases'][ident]['rows'] if r['symbol']==symbol and r['session']==session)
                if row['sources']['O06']['campaigns']==0:continue
                item=results['cases'][ident]['ledgers'][session][symbol];ledger=common.unpack(item);ledger_reads+=1
                record=packet['prepared'][symbol]['record'];items=[]
                for trade in ledger['trades'][ledger['trades'][:,1]==1]:
                    detail=describe(record,packet['measured'][symbol],ledger,trade,cfg);items.append(detail)
                    all_group={'all':aggregate['all_R']};add_group(all_group,'all',detail)
                    add_group(aggregate['groups'],detail['category'],detail);add_group(aggregate['directions'],detail['side'],detail)
                    for key,flag in detail['qualifiers'].items():add_group(aggregate['qualifiers'],key+('=true' if flag else '=false'),detail)
                assert len(items)==row['sources']['O06']['campaigns'] and abs(sum(d['net'] for d in items)-row['sources']['O06']['net'])<1e-4
                if session in selected[ident][symbol]:
                    negatives=sorted((d for d in items if d['net']<0),key=lambda d:(d['net'],d['parent_id']))[:3]
                    aggregate['selected_sessions'][session].update(parents=negatives,ledger_source=item)
        del packet
    for ident in output:
        for symbol,value in output[ident].items():
            expected=sum(r['sources']['O06']['campaigns'] for r in results['cases'][ident]['rows'] if r['symbol']==symbol)
            assert value['all_R']['parents']==expected
    common.write(target,dict(全合格=True,事後診断専用=True,金融結果参照あり=True,results=output,
        input_cache_reads=len(results['sessions']),ledger_reads=ledger_reads,新金融再生=0,原板読取=0,API取得=0,
        SHA256={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in (Path(__file__),RANGE/'results.json',RANGE/'全33場の価格境界反発準備.json')},
        限界=['全R親の同じ分類に黒字も残す。最大赤字例だけで改善効果を断定しない。',
            '新反対TRENDで返済するcounterfactual金融は今回行わない。','6sample/価格代理時計/large BBO代用の限界を保持。']))
    print('R全親分類と最大損失場の診断を保存、金融再生0',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='完了したR_PRICEの原因だけを診断する')
    parser.add_argument('--root-results-diagnosis-approved',action='store_true',required=True)
    parser.parse_args();run()
