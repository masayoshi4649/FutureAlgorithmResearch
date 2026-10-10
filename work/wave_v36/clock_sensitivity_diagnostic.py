"""保存台帳だけでQ034の時間窓感度を分解する。売買を再実行しない。"""

from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
VARIANTS={'V000':'C100','C080':'C080','C120':'C120'}


def read(path: Path):
    """機能: 通常又は圧縮された保存済みJSONを読む。

    引数: path (Path)。返り値: 保存内容 (object)。
    """
    payload=path.read_bytes()
    return json.loads(gzip.decompress(payload) if path.suffix=='.gz' else payload)


def average(values: list[float]) -> float | None:
    """機能: 空集合を0と誤認しない平均を求める。

    引数: values (list[float])。返り値: 平均又はNone (float|None)。
    """
    return float(sum(values)/len(values)) if values else None


def stamp(value: float) -> str:
    """機能: 保存原本の秒時刻を日本時間へ表す。

    引数: value (float)。返り値: ISO時刻 (str)。
    """
    return datetime.fromtimestamp(value,ZoneInfo('Asia/Tokyo')).isoformat()


def aggregate(rows: list[dict], cycles: list[dict], episodes: list[dict]) -> dict:
    """機能: 金額・完結組・方向・発火数を保存資料だけから集計する。

    引数: rows/cycles/episodes (list[dict])。返り値: 集計 (dict)。部分利確を組の勝ち数へ重複加算しない。
    """
    wins=[r['net_yen'] for r in cycles if r['net_yen']>0]
    losses=[-r['net_yen'] for r in cycles if r['net_yen']<0]
    gross_profit=sum(r['gross_profit_yen'] for r in rows)
    gross_loss=sum(r['gross_loss_yen'] for r in rows)
    net=sum(r['net_yen'] for r in rows)
    assert abs(net-sum(r['net_yen'] for r in cycles))<1e-6
    assert len(cycles)==sum(r['opening_orders'] for r in rows)
    by_side={str(side):dict(cycles=sum(r['side']==side for r in cycles),
        net_yen=sum(r['net_yen'] for r in cycles if r['side']==side)) for side in (1,-1)}
    accepted=[r for r in episodes if r['accepted']]
    return dict(gross_profit_yen=gross_profit,gross_loss_yen=gross_loss,net_yen=net,
        profit_units=sum(r['profit_units'] for r in rows),loss_units=sum(r['loss_units'] for r in rows),
        opening_orders=len(cycles),winning_cycles=len(wins),losing_cycles=len(losses),
        zero_cycles=len(cycles)-len(wins)-len(losses),mean_win_cycle_yen=average(wins),mean_loss_cycle_yen=average(losses),
        mean_payoff_ratio=average(wins)/average(losses) if wins and losses else None,
        leg_pf=gross_profit/gross_loss if gross_loss else None,
        two_largest_wins=sorted(wins,reverse=True)[:2],remove_two_best_net=net-sum(sorted(wins,reverse=True)[:2]),
        direction=by_side,price_setups=len(episodes),confirmed_setups=sum(r['resolution']=='confirmed' for r in episodes),
        volume_pass_setups=sum(r['proxy_pass'] for r in episodes),accepted_episodes=len(accepted),
        accepted_reversal=sum(r['response_branch']=='reversal' for r in accepted),
        accepted_breakout=sum(r['response_branch']=='breakout' for r in accepted),
        adopted_setup_ratio=len(accepted)/len(episodes) if episodes else None)


def entries(ledger: dict, ready: dict) -> list[dict]:
    """機能: 完結組を新規原本seq・方向・枚数・価格・固定ATRへ結ぶ。

    引数: ledger/ready (dict)。返り値: 組別の新規と全返済収支 (list[dict])。
    """
    orders=np.asarray(ledger['orders'],float).reshape(-1,8)
    trades=np.asarray(ledger['trades'],float).reshape(-1,11)
    cycles=np.asarray(ledger['cycles'],float).reshape(-1,10)
    output=[];point=ledger['config']['point_value']
    for cycle in cycles:
        group=orders[(orders[:,2]==cycle[0])&(orders[:,7]==1)]
        assert len(group)==1,'共通D273の新規は1組1回'
        order=group[0];row=int(order[0]);legs=trades[trades[:,0]==cycle[0]]
        assert cycle[1]==row and abs(cycle[3]-sum(legs[:,10]))<1e-6
        output.append(dict(session=ledger['session'],symbol=ledger['symbol'],campaign=int(cycle[0]),
            entry_row=row,entry_rawseq=int(ready['seq'][row]),entry_time=stamp(float(ready['time_s'][row])),
            side=int(order[3]),quantity=int(order[4]),entry_price=float(order[5]),
            initial_atr=float(cycle[5]),initial_risk_points=float(cycle[4]),
            net_yen=float(cycle[3]*point),exit_row=int(cycle[2]),
            exit_time=stamp(float(ready['time_s'][int(cycle[2])])),
            exit_prices=[float(t[5]) for t in legs],exit_quantities=[int(t[3]) for t in legs]))
    assert len(output)==sum(orders[:,7]==1)
    return output


def entry_key(row: dict, economic: bool=True) -> tuple:
    """機能: セッション内原本seqで厳密対応し、近い時刻だけでは結ばない。

    引数: row (dict)、economic (bool)。返り値: 同一性キー (tuple)。
    """
    key=(row['session'],row['symbol'],row['entry_rawseq'])
    return key+(row['side'],row['quantity'],row['entry_price']) if economic else key


def compare_entries(base: list[dict], changed: list[dict]) -> dict:
    """機能: 共通入口の差と、片側だけの新規の寄与へ収支差を恒等分解する。

    引数: base/changed (list[dict])。返り値: 同一性件数と寄与 (dict)。因果効果の推定ではない。
    """
    a={entry_key(r):r for r in base};b={entry_key(r):r for r in changed}
    assert len(a)==len(base) and len(b)==len(changed)
    common=sorted(a.keys()&b.keys());old_only=[a[k] for k in sorted(a.keys()-b.keys())]
    new_only=[b[k] for k in sorted(b.keys()-a.keys())]
    pairs=[dict(base=a[k],changed=b[k],net_difference_yen=b[k]['net_yen']-a[k]['net_yen'],
        same_atr_risk=a[k]['initial_atr']==b[k]['initial_atr'] and a[k]['initial_risk_points']==b[k]['initial_risk_points']) for k in common]
    difference=sum(r['net_yen'] for r in changed)-sum(r['net_yen'] for r in base)
    common_diff=sum(r['net_difference_yen'] for r in pairs)
    old_sum=sum(r['net_yen'] for r in old_only);new_sum=sum(r['net_yen'] for r in new_only)
    assert abs(difference-(common_diff+new_sum-old_sum))<1e-6
    return dict(base_entries=len(base),changed_entries=len(changed),
        same_raw_entry_rows=len({entry_key(r,False) for r in base}&{entry_key(r,False) for r in changed}),
        same_raw_side_quantity_price=len(common),same_entry_and_atr_risk=sum(r['same_atr_risk'] for r in pairs),
        old_only_count=len(old_only),new_only_count=len(new_only),net_difference_yen=difference,
        common_exit_difference_yen=common_diff,old_only_net_yen=old_sum,new_only_net_yen=new_sum,
        common_pairs=pairs,old_only=old_only,new_only=new_only)


def setup_key(row: dict) -> tuple:
    """機能: 異なる窓の準備をIDではなく同じ原本seqと固定価格属性でだけ対応させる。

    引数: row (dict)。返り値: 厳密な準備キー (tuple)。
    """
    return tuple(row[k] for k in ('session','symbol','setup_seq','setup_side','setup_mid','band_price','setup_atr','confirmation_width'))


def compare_setups(base: list[dict], changed: list[dict]) -> dict:
    """機能: 共通準備に限り凍結スコア・反応・相手判定の変化を記述する。

    引数: base/changed (list[dict])。返り値: 厳密対応の件数 (dict)。近接時刻を同一視しない。
    """
    a={setup_key(r):r for r in base};b={setup_key(r):r for r in changed}
    common=a.keys()&b.keys();counter=Counter()
    for key in common:
        x,y=a[key],b[key]
        counter['score_changed']+=int(x['stable_volume_score']!=y['stable_volume_score'])
        counter['volume_pass_changed']+=int(x['proxy_pass']!=y['proxy_pass'])
        response_same=(x['confirmation_seq'],x['response_direction'])==(y['confirmation_seq'],y['response_direction'])
        counter['same_confirmed_response']+=int(response_same and x['confirmation_seq'] is not None)
        counter['resolution_changed']+=int((x['resolution'],x['confirmation_seq'],x['response_direction'])!=(y['resolution'],y['confirmation_seq'],y['response_direction']))
        counter['peer_pass_changed_at_same_confirmation']+=int(response_same and x['confirmation_seq'] is not None and x['peer_pass']!=y['peer_pass'])
        counter['accepted_changed']+=int(x['accepted']!=y['accepted'])
        counter['base_accepted_on_common_setup']+=int(x['accepted'])
        counter['changed_accepted_on_common_setup']+=int(y['accepted'])
        counter['both_accepted_same_confirmation']+=int(x['accepted'] and y['accepted'] and response_same)
    return dict(base_setups=len(base),changed_setups=len(changed),same_raw_setup_and_frozen_price=len(common),
        same_raw_setup_seq=len({(r['session'],r['symbol'],r['setup_seq']) for r in base}&{(r['session'],r['symbol'],r['setup_seq']) for r in changed}),
        old_only_setups=len(a)-len(common),new_only_setups=len(b)-len(common),**dict(counter))


def main() -> None:
    """機能: 全13/後7・方向・セッション・厳密共通入口の内訳を保存する。

    引数: なし。返り値: なし (None)。売買・新条件探索・採否の変更はしない。
    """
    files=[HERE.parent/'wave_v23/inputs.pkl']
    for variant,clock in VARIANTS.items():
        files += [HERE/folder/('Q034__'+variant+suffix) for folder,suffix in
            (('sessions','.json.gz'),('ledgers','.json.gz'),('summaries','.json'))]
        files += [HERE/'episodes'/('Q034__'+clock+'.json.gz')]
    before={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    inputs=pickle.loads(files[0].read_bytes());sessions=sorted({k[0] for k in inputs});late=set(sessions[6:])
    allrows,allcycles,allepisodes={}, {}, {}
    for variant,clock in VARIANTS.items():
        allrows[variant]=read(HERE/'sessions'/('Q034__'+variant+'.json.gz'))
        ledgers=read(HERE/'ledgers'/('Q034__'+variant+'.json.gz'))
        allcycles[variant]=[r for ledger in ledgers for r in entries(ledger,inputs[ledger['session'],ledger['symbol']])]
        allepisodes[variant]=[dict(ep,session=item['session'],symbol=item['symbol']) for item in
            read(HERE/'episodes'/('Q034__'+clock+'.json.gz')) for ep in item['episodes']]
    periods={};comparisons={};setup_comparisons={};session_rows=[]
    for phase,names in [('全13',set(sessions)),('後7',late)]:
        periods[phase]={};comparisons[phase]={};setup_comparisons[phase]={}
        for symbol in ('TOPIX','NK225'):
            periods[phase][symbol]={};comparisons[phase][symbol]={};setup_comparisons[phase][symbol]={}
            select=lambda values:[r for r in values if r['symbol']==symbol and r['session'] in names]
            for variant in VARIANTS:
                periods[phase][symbol][variant]=aggregate(select(allrows[variant]),select(allcycles[variant]),select(allepisodes[variant]))
                summary=read(HERE/'summaries'/('Q034__'+variant+'.json'))
                assert periods[phase][symbol][variant]['net_yen']==summary['all_symbols' if phase=='全13' else 'symbols'][symbol]['net_yen']
                if variant!='V000':
                    comparisons[phase][symbol][variant]=compare_entries(select(allcycles['V000']),select(allcycles[variant]))
                    setup_comparisons[phase][symbol][variant]=compare_setups(select(allepisodes['V000']),select(allepisodes[variant]))
    for session in sessions:
        for symbol in ('TOPIX','NK225'):
            item=dict(session=session,symbol=symbol,phase='後7' if session in late else '初期6',variants={})
            for variant in VARIANTS:
                select=lambda values:[r for r in values if r['symbol']==symbol and r['session']==session]
                item['variants'][variant]=aggregate(select(allrows[variant]),select(allcycles[variant]),select(allepisodes[variant]))
            for variant in ('C080','C120'):
                item['variants'][variant]['difference_from_base_yen']=item['variants'][variant]['net_yen']-item['variants']['V000']['net_yen']
            session_rows.append(item)
    result=dict(対象='Q034の固定120秒と96/144秒窓だけを保存資料から診断',期間=periods,
        厳密共通入口=comparisons,厳密共通価格準備=setup_comparisons,セッション別=session_rows,
        対応定義='原本entry seqを同じsession/symbol内で比較。方向/枚数/価格一致を別計数し、A0と初期リスク一致も区別。episode_idや近い時刻では対応させない。',
        平均定義='新規1回から全返済までの組の純損益。部分利確脚を勝ち組へ重複計数しない。PFは全返済脚の総利益/総損失。',
        分解限界='同じ原本行で入った組と片側だけの組の収支差の恒等分解。除外又は追加だけの因果効果ではない。',
        参照SHA256=before,実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        保存資料前後不変=True,新売買再生=False,新条件探索=False,採否変更=False,API取得数=0,現在保存物使用=False)
    assert before=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (HERE/'時間窓感度の内訳.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(保存完了=True,共通準備=setup_comparisons['後7']),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
