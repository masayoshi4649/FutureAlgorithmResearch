"""親側候補の保存台帳だけから、銘柄差を入口選別・目標・気配差へ分解する。"""

import json
from pathlib import Path
import pickle

import numpy as np

from run import save,digest


HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
BASE=ROOT.parent/'wave_v60'


def stat(values: list) -> dict:
    """機能: 有限な観測量の件数・平均・中央値を求める。

    引数: values(list)。返り値: 記述統計(dict)。推定の因果性は主張しない。
    """
    a=np.asarray(values,float)
    a=a[np.isfinite(a)]
    return dict(n=len(a),mean=float(a.mean()) if len(a) else None,median=float(np.median(a)) if len(a) else None)


def micro_rows(method: dict) -> list:
    """機能: 短期板の単一建玉台帳を共通列へ変換する。

    引数: method(dict)。返り値: 全決済組の辞書列(list)。追加再生はしない。
    """
    source=pickle.loads(Path(method['ledger']).read_bytes())
    output=[]
    for key,account in source.items():
        for t in account['trades']:
            output.append(dict(session=key[0],symbol=key[1],decision=int(t[0]),entry_i=int(t[1]),
                exit_decision=int(t[2]),exit_i=int(t[3]),side=int(t[4]),qty=int(t[5]),entry=t[6],exit=t[7],
                fee=t[8]+t[9],gross=t[10],net=t[11],reason=int(t[12]),target_ticks=method['config']['target'],
                stop_ticks=method['config']['stop']))
    return output


def directional_rows(method: dict,inputs: dict) -> list:
    """機能: 追加なし方向性台帳を共通列へ変換する。

    引数: method/inputs(dict)。返り値: 全決済組の辞書列(list)。原本seqから判断位置を対応させる。
    """
    assert not method['config']['pyramid']
    source=pickle.loads((ROOT/'directional/round3'/method['ledger']).read_bytes())
    output=[]
    for key,account in source.items():
        ready=inputs[key[:2]]
        assert len(np.unique(account['trades'][:,21]))==len(account['trades'])
        for t in account['trades']:
            target=np.ceil(.5*t[10]/ready['tick']-1e-10) if method['exit_id']=='C' else np.nan
            output.append(dict(session=key[0],symbol=key[1],decision=int(np.searchsorted(ready['seq'],t[18])),
                entry_i=int(t[19]),exit_decision=int(np.searchsorted(ready['seq'],t[14])),exit_i=int(t[20]),
                side=int(t[2]),qty=int(t[3]),entry=t[4],exit=t[5],fee=t[7],gross=t[6],net=t[8],
                reason=int(t[9]),target_ticks=target,stop_ticks=t[10]/ready['tick']))
    return output


def summarize(rows: list,symbol: str,inputs: dict,quotes: dict,reason_map: dict) -> dict:
    """機能: 同注文中値、実返済理由、目標到達と幅の比率を銘柄ごとに求める。

    引数: rows(list)、symbol(str)、inputs/quotes/reason_map(dict)。返り値: 観測された銘柄別差(dict)。
    将来価格は保有区間の説明専用で、入口条件へ戻さない。
    """
    chosen=[r for r in rows if r['symbol']==symbol]
    value=1000. if symbol=='TOPIX' else 10.
    nets=[r['net'] for r in chosen]
    winners=[x for x in nets if x>0]
    losers=[-x for x in nets if x<0]
    aw=float(np.mean(winners)) if winners else None
    al=float(np.mean(losers)) if losers else None
    observations={name:[] for name in ('same_order_mid_net','spread_entry_ticks','spread_exit_ticks','target_percent',
        'stop_percent','target_ticks','stop_ticks','fee_ticks','cost_price_ticks','hold_seconds',
        'mfe_ticks','mae_ticks','prior5_range_ticks','prior5_range_over_target','realized_net_R')}
    target_before_exit=stop_before_exit=0
    reason={name:dict(count=0,net=0.) for name in reason_map.values()}
    for r in chosen:
        key=(r['session'],symbol)
        ready,q=inputs[key],quotes[key]
        ei,xi,di,xd=r['entry_i'],r['exit_i'],r['decision'],r['exit_decision']
        tick=ready['tick']
        mid_gross=r['side']*(q['mid'][xi]-q['mid'][ei])*r['qty']*value
        liquidation=q['bid'] if r['side']>0 else q['ask']
        path=r['side']*(liquidation[ei:xd+1]-r['entry'])/tick
        mfe=float(np.max(path,initial=0))
        mae=float(-np.min(path,initial=0))
        target_before_exit+=np.isfinite(r['target_ticks']) and mfe>=r['target_ticks']-1e-9
        stop_before_exit+=mae>=r['stop_ticks']-1e-9
        left=int(np.searchsorted(ready['time_s'],ready['time_s'][di]-300,side='left'))
        previous=q['mid'][left:di+1]
        span=(float(previous.max())-float(previous.min()))/tick
        vals=dict(same_order_mid_net=mid_gross-r['fee'],spread_entry_ticks=(q['ask'][ei]-q['bid'][ei])/tick,
            spread_exit_ticks=(q['ask'][xi]-q['bid'][xi])/tick,target_percent=r['target_ticks']*tick/r['entry']*100,
            stop_percent=r['stop_ticks']*tick/r['entry']*100,target_ticks=r['target_ticks'],stop_ticks=r['stop_ticks'],
            fee_ticks=r['fee']/(r['qty']*value*tick),cost_price_ticks=(mid_gross-r['gross'])/(r['qty']*value*tick),
            hold_seconds=ready['time_s'][xi]-ready['time_s'][ei],mfe_ticks=mfe,mae_ticks=mae,
            prior5_range_ticks=span,prior5_range_over_target=span/r['target_ticks'],
            realized_net_R=r['net']/(r['stop_ticks']*tick*r['qty']*value))
        for name,val in vals.items():
            observations[name].append(val)
        reason[reason_map[r['reason']]]['count']+=1
        reason[reason_map[r['reason']]]['net']+=r['net']
    return dict(groups=len(chosen),wins=len(winners),losses=len(losers),net=sum(nets),gross=sum(r['gross'] for r in chosen),
        fees=sum(r['fee'] for r in chosen),win_rate=len(winners)/len(chosen) if chosen else None,
        mean_win=aw,mean_loss=al,payoff=aw/al if aw and al else None,
        descriptive_break_even_win_rate=al/(aw+al) if aw and al else None,
        same_orders_mid_net=sum(observations['same_order_mid_net']),
        same_orders_price_difference=sum(observations['same_order_mid_net'])-sum(nets),
        target_reached_before_exit_decision=int(target_before_exit),stop_reached_before_exit_decision=int(stop_before_exit),
        reasons=reason,observations={name:stat(values) for name,values in observations.items()},
        direction={str(side):dict(groups=sum(r['side']==side for r in chosen),net=sum(r['net'] for r in chosen if r['side']==side)) for side in (-1,1)})


def compare_rows(base: list,target: list,symbol: str) -> dict:
    """機能: 同一判断原本行・方向の共通入口と、変更で増減した入口を分ける。

    引数: base/target(list)、symbol(str)。返り値: 共通集合の会計分解(dict)。
    銘柄間で同時刻を同じ事件とみなす比較は行わない。
    """
    a={(r['session'],r['decision'],r['side']):r for r in base if r['symbol']==symbol}
    b={(r['session'],r['decision'],r['side']):r for r in target if r['symbol']==symbol}
    common=a.keys()&b.keys()
    removed=a.keys()-b.keys()
    added=b.keys()-a.keys()
    delta=sum(b[k]['net']-a[k]['net'] for k in common)
    removed_net=sum(a[k]['net'] for k in removed)
    added_net=sum(b[k]['net'] for k in added)
    assert np.isclose(sum(r['net'] for r in b.values())-sum(r['net'] for r in a.values()),delta+added_net-removed_net)
    return dict(common=len(common),removed=len(removed),added=len(added),common_net_before=sum(a[k]['net'] for k in common),
        common_net_after=sum(b[k]['net'] for k in common),common_delta=delta,removed_net=removed_net,added_net=added_net,
        removed_win_rate=sum(a[k]['net']>0 for k in removed)/len(removed) if removed else None,
        added_win_rate=sum(b[k]['net']>0 for k in added)/len(added) if added else None)


def shadow_diagnostic(method: dict,base: dict,rows: list,baseline_rows: list) -> dict:
    """機能: 無選別口座と同じ影取引の既完了組から、入口時点の窓成績を確認する。

    引数: method/base(dict)、rows/baseline_rows(list)。返り値: 銘柄別の過去窓と実取引の比較(dict)。
    全未来の影成績を入口へ使わず、当該判断行までの決済だけを参照する。
    """
    out={}
    window=method['config']['window']
    for symbol in ('TOPIX','NK225'):
        rates=[]
        finished=[]
        for account in method['accounts']:
            if account['symbol']!=symbol:
                continue
            session=account['session']
            prior=[r for r in baseline_rows if r['session']==session and r['symbol']==symbol]
            assert len(prior)==account['paper_finished']
            exits=np.array([r['exit_i'] for r in prior])
            pnls=np.array([r['net'] for r in prior])
            for actual in rows:
                if actual['session']!=session or actual['symbol']!=symbol:
                    continue
                n=int(np.searchsorted(exits,actual['decision'],side='right'))
                assert n>=window
                rate=float(np.mean(pnls[n-window:n]>0))
                assert round(rate*window)>=method['config']['required_wins']
                rates.append(rate)
                finished.append(n)
        accounts=[a for a in method['accounts'] if a['symbol']==symbol]
        out[symbol]=dict(window=window,required_wins=method['config']['required_wins'],
            historical_win_rate_at_entry=stat(rates),finished_shadows_at_entry=stat(finished),
            shadow_finished=sum(a['paper_finished'] for a in accounts),allowed=sum(a['allowed'] for a in accounts),
            blocked=sum(a['blocked'] for a in accounts),actual_win_rate=method['summary'][symbol]['win_rate'],
            uncalibrated=base['summary'][symbol],entry_set=compare_rows(baseline_rows,rows,symbol))
    return out


def main() -> None:
    """機能: 三候補と少数両市場黒字の対照を、保存結果だけで説明する。

    引数: なし。返り値: なし(None)。元コード・元結果・売買条件を変更しない。
    """
    inputs=pickle.loads((BASE/'inputs.pkl').read_bytes())
    quotes=pickle.loads((BASE/'quotes.pkl').read_bytes())
    micro=json.loads((ROOT/'microstructure/round3/集計結果.json').read_text(encoding='utf8'))
    directional=json.loads((ROOT/'directional/round3/集計結果.json').read_text(encoding='utf8'))
    micros={m['id']:m for m in micro['methods']}
    dirs={m['id']:m for m in directional['methods']}
    ids=['M3_Q1_L1_T16_S8_H600_保有30分_校正10_60','M3_Q2_L0_T16_S8_H600_保有30分_校正5_60',
         'M3_Q2_L0_T16_S8_H600_保有30分_校正10_60']
    result=dict(目的='候補3つの銘柄差と、少数両銘柄黒字対照の事後診断。新規売買計算・条件変更なし。',
        限界=['全25場既読で候補自体も事後選定。将来の銘柄固有性を証明しない。',
              '銘柄間の円を直接比較せず、勝率・平均勝負比・呼値・初期リスク比を併記。',
              '同注文中値は説明用の価格差分解。中値で実際に約定する主張ではない。',
              '共通入口は同銘柄・同セッション・同判断原本行・同方向。銘柄間の時計を真の同時性に代用しない。'],候補=[])
    all_rows={}
    for name in ids:
        m=micros[name]
        base_id=name.split('_校正')[0]+'_校正0_0'
        base=micros[base_id]
        rows=micro_rows(m)
        br=micro_rows(base)
        all_rows[name]=rows
        entry=dict(id=name,config=m['config'],summary=m['summary'],
            measured={s:summarize(rows,s,inputs,quotes,{1:'目標',2:'損切り',3:'期限',4:'場内',5:'保護'}) for s in ('TOPIX','NK225')},
            shadow_selection=shadow_diagnostic(m,base,rows,br))
        result['候補'].append(entry)
    name='R3_DEPTH_C_quote'
    m=dirs[name]
    rows=directional_rows(m,inputs)
    candidates=pickle.loads((ROOT/'directional/round3/入口候補.pkl').read_bytes())
    reason_map={1:'損切り',2:'トレール',3:'期限',4:'場内',5:'日予算',6:'目標',7:'保護'}
    result['候補'].append(dict(id=name,config=m['config'],summary=m['summary'],
        measured={s:summarize(rows,s,inputs,quotes,reason_map) for s in ('TOPIX','NK225')},
        candidates={s:{kind:sum(len(v[kind]) for k,v in candidates.items() if k[1]==s) for kind in ('P2','WAIT','FLOW','DEPTH')} for s in ('TOPIX','NK225')},
        same_entry_exit_comparison={s:compare_rows(directional_rows(dirs['R3_DEPTH_T_quote'],inputs),rows,s) for s in ('TOPIX','NK225')}))
    result['校正5と10の入口集合差']={s:compare_rows(all_rows[ids[1]],all_rows[ids[2]],s) for s in ('TOPIX','NK225')}
    result['入力SHA']={str(p.relative_to(ROOT)):digest(p) for p in (ROOT/'microstructure/round3/集計結果.json',ROOT/'directional/round3/集計結果.json')}
    save(HERE/'候補3つの銘柄差.json',result)
    for m in result['候補']:
        print(m['id'])
        for s,v in m['measured'].items():
            print(s,{k:v[k] for k in ('groups','net','same_orders_mid_net','win_rate','payoff','descriptive_break_even_win_rate','reasons')})


if __name__=='__main__':
    main()
