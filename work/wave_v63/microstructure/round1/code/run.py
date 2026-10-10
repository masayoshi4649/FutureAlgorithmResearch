"""原板の短期機構をラウンド別に先に固定し、全保存場を再生する。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

from core import candidate_signals, replay, ORDER_COLUMNS, TRADE_COLUMNS, REASONS


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
BASE=WORK.parent/'wave_v60'


def digest(path: Path) -> str:
    """機能: 実装と入力の変更を照合するSHAを求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path,value: dict) -> None:
    """機能: finiteな日本語JSONを保存する。

    引数: path(Path)、value(dict)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def prepare() -> None:
    """機能: 修正済み板から入口を生成し、原本順を保存する。

    引数: なし。返り値: なし(None)。売買損益をまだ計算しない。
    """
    target=HERE/'signals.pkl'
    assert not target.exists(),'入口は固定済みです'
    inputs=pickle.loads((BASE/'inputs.pkl').read_bytes())
    features=pickle.loads((WORK/'tick_features.pkl').read_bytes())
    events=pickle.loads((WORK/'tick_events.pkl').read_bytes())
    output={}
    audits=[]
    for key in sorted(inputs):
        f,ready,e=features[key],inputs[key],events[key]
        arguments=(f['bid'],f['ask'],f['bid_qty'],f['ask_qty'],f['best_ofi'],f['valid'],f['reset'],
            f['exec_buy_qty'],f['exec_sell_qty'],f['exec_unknown_qty'],f['time_s'],
            e['i'],e['side'],e['qty'],e['bestqty'],e['price'],ready['tick'],ready['start'])
        signal=candidate_signals(*arguments)
        cut=len(ready['seq'])//2
        shorter=tuple(a[:cut] if k<11 else a[e['i']<cut] if k<16 else a for k,a in enumerate(arguments))
        prefix=candidate_signals(*shorter)
        assert np.array_equal(prefix,signal[:,:cut])
        output[key]=signal
        audits.append(dict(セッション=key[0],銘柄=key[1],途中切断一致=True,信号数=[int(np.count_nonzero(x)) for x in signal]))
    target.write_bytes(pickle.dumps(output,protocol=pickle.HIGHEST_PROTOCOL))
    save(HERE/'入口の因果照合.json',dict(合格=True,口座数=50,公開='同銘柄rawseq順、256更新以内にresetなし。二銘柄受信時計の代用結合はしない。',
        説明='OFI/深板偏りの継続、または補充完了後の圧力反転。取引時計と受信時計は区別。候補抽出時に出口や将来収益は見ない。',口座別=audits))
    print('短期板6入口を保存、50場prefix完全一致',flush=True)


def settings(round_number: int) -> list[dict]:
    """機能: 各PDCAラウンドで試す条件を結果計算前に列挙する。

    引数: round_number(int)。返り値: 条件一覧(list[dict])。
    """
    result=[]
    if round_number==1:
        for signal in range(6):
            for target,stop in ((4,2),(8,4),(16,8)):
                for hold in (60,600):
                    result.append(dict(id=f'M1_Q{signal//3+1}_L{signal%3}_T{target}_S{stop}_H{hold}',
                        signal=signal,target=target,stop=stop,hold=hold,cooldown=10,protect=0,calibration=0,window=20,required_wins=19))
    else:
        path=HERE/f'round{round_number}'/'条件案.json'
        result=json.loads(path.read_text(encoding='utf-8'))['conditions']
    return result


def summarize(values: list[dict]) -> dict:
    """機能: 同銘柄の費用後の組勝率、勝負比、PFと資産下落を集計する。

    引数: values(list[dict])。返り値: 合計(dict)。活動のない場を勝ちに数えない。
    """
    keys=('gross_profit','gross_loss','fees','net','wins','losses','flats','cycles','profit','loss','win_qty','loss_qty','flat_qty')
    out={k:sum(v[k] for v in values) for k in keys}
    out['win_rate']=out['wins']/out['cycles'] if out['cycles'] else None
    out['pf']=out['profit']/out['loss'] if out['loss'] else None
    avg_win=out['profit']/out['wins'] if out['wins'] else None
    avg_loss=out['loss']/out['losses'] if out['losses'] else None
    out['payoff']=avg_win/avg_loss if avg_win is not None and avg_loss else None
    out['positive_sessions']=sum(v['net']>0 for v in values)
    out['active_sessions']=sum(v['cycles']>0 for v in values)
    out['sessions']=len(values)
    level=peak=dd=0.
    for v in sorted(values,key=lambda x:x['session']):
        dd=max(dd,v['drawdown'],peak-level-v['equity_min'])
        peak=max(peak,level+v['equity_max'])
        level+=v['net']
    out['drawdown']=dd
    out['max_loss_session']=min(v['net'] for v in values)
    out['without_best']=out['net']-max(0,max(v['net'] for v in values))
    out['win95_observed']=out['cycles']>0 and out['win_rate'] is not None and out['win_rate']>=.95
    out['risk_good']=out['net']>0 and (out['losses']==0 or (out['payoff'] or 0)>1)
    out['goal95']=out['win95_observed'] and out['risk_good']
    out['goal95_with_sample']=out['goal95'] and out['cycles']>=50 and out['active_sessions']>=12
    return out


def run(round_number: int) -> None:
    """機能: 先に固定した条件を全50口座で再生し、組会計と全原簿を保存する。

    引数: round_number(int)。返り値: なし(None)。既存ラウンドは上書きしない。
    """
    destination=HERE/f'round{round_number}'
    destination.mkdir(exist_ok=True)
    target=destination/'集計結果.json'
    assert not (destination/'計算開始.json').exists(),'計算済みラウンドを上書きしません'
    configs=settings(round_number)
    paths=[HERE/'core.py',Path(__file__),HERE/'signals.pkl',BASE/'inputs.pkl',BASE/'quotes.pkl']
    save(destination/'実行前固定.json',dict(時刻=datetime.now(timezone.utc).isoformat(),conditions=configs,
        SHA={str(p):digest(p) for p in paths},主評価='買ask売bid・判断の次原本行で約定・全sessionclose',
        手数料='TOPmini41.8/NKmicro11税込片道floor注文単位',注文列=ORDER_COLUMNS,決済列=TRADE_COLUMNS,
        判定='全flat1組fee後>0を勝ち、同値も分母。新規TOP5/NK10・追加なし。平均勝負比>1と総黒字が95%に加えて必要。',
        既知資料=True,実注文=False,現在API=0))
    save(destination/'計算開始.json',dict(開始=datetime.now(timezone.utc).isoformat()))
    inputs=pickle.loads((BASE/'inputs.pkl').read_bytes())
    quotes=pickle.loads((BASE/'quotes.pkl').read_bytes())
    signals=pickle.loads((HERE/'signals.pkl').read_bytes())
    methods=[]
    for config in configs:
        accounts=[]
        ledgers={}
        for key in sorted(inputs):
            ready,q=inputs[key],quotes[key]
            qty,value,fee=(5,1000.,41.8) if key[1]=='TOPIX' else (10,10.,11.)
            orders,trades,equity,counters=replay(ready['time_s'],q['bid'],q['ask'],signals[key][config['signal']],ready['tick'],ready['start'],ready['limit'],
                value,qty,fee,config['target'],config['stop'],config['hold'],config['cooldown'],config['protect'],config['calibration'],config['required_wins'],config['window'])
            assert counters[0]==0,(key,'未返済玉あり')
            net=float(trades[:,11].sum())
            cost=float(orders[:,6].sum())
            gross=trades[:,10]
            winners=trades[:,11]>0
            losers=trades[:,11]<0
            flat=trades[:,11]==0
            assert abs(equity[-1]-net)<1e-6
            assert abs(gross.sum()-cost-net)<1e-6
            curve=np.maximum.accumulate(np.r_[0.,equity])[1:]-equity
            a=dict(session=key[0],symbol=key[1],gross_profit=float(gross[gross>0].sum()),gross_loss=float(-gross[gross<0].sum()),
                fees=cost,net=net,wins=int(winners.sum()),losses=int(losers.sum()),flats=int(flat.sum()),cycles=len(trades),
                profit=float(trades[winners,11].sum()),loss=float(-trades[losers,11].sum()),win_qty=int(trades[winners,5].sum()),loss_qty=int(trades[losers,5].sum()),flat_qty=int(trades[flat,5].sum()),
                drawdown=float(curve.max()),equity_min=float(min(0,equity.min())),equity_max=float(max(0,equity.max())),
                max_long_qty=qty if (trades[:,4]==1).any() else 0,max_short_qty=qty if (trades[:,4]==-1).any() else 0,
                paper_finished=int(counters[1]),paper_window_wins=int(counters[2]),allowed=int(counters[3]),blocked=int(counters[4]),
                hold_median_seconds=float(np.median(ready['time_s'][trades[:,3].astype(int)]-ready['time_s'][trades[:,1].astype(int)])) if len(trades) else None,
                reasons={REASONS[r]:dict(cycles=int((trades[:,12]==r).sum()),net=float(trades[trades[:,12]==r,11].sum())) for r in REASONS})
            accounts.append(a)
            ledgers[key]=dict(orders=orders,trades=trades)
        file=destination/f'{config["id"]}.pkl'
        file.write_bytes(pickle.dumps(ledgers,protocol=pickle.HIGHEST_PROTOCOL))
        summary={s:summarize([a for a in accounts if a['symbol']==s]) for s in ('TOPIX','NK225')}
        methods.append(dict(id=config['id'],config=config,accounts=accounts,summary=summary,ledger=str(file),ledger_SHA=digest(file)))
        print(config['id'],json.dumps({s:dict(net=v['net'],win_rate=v['win_rate'],cycles=v['cycles'],payoff=v['payoff']) for s,v in summary.items()},ensure_ascii=False),flush=True)
    save(target,dict(round=round_number,methods=methods,合格=True,最終玉全返済=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--round',type=int)
    args=parser.parse_args()
    prepare() if args.prepare else run(args.round)
