"""共通満額入口を固定し、32管理条件を全玉会計で比較する。"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import pickle
import socket

import numpy as np
import numba

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
numba.config.CACHE_DIR = str(HERE/'numba_cache')
import engine
import net

SOURCES = ('T1L1','T2L0','T3L1','T4L0','E01P','R01P')
SYMBOLS = ('TOPIX','NK225')
FIELDS = ('kind','stop','activation','trail','hold_seconds','grid','step_fraction','cover_activation','cover_trail',
          'basket_stop','basket_activation','basket_trail','flip_fraction','partial_level','partial_fraction',
          'tighten_minutes','ratchet_step','ratchet_keep','grid_mode')


def load(path: Path) -> object:
    """機能: 保存済みのJSON又は台帳を読み取る。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(path: Path, value: object) -> None:
    """機能: 今回作業内へだけ結果を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.pkl':
        path.write_bytes(pickle.dumps(value,protocol=pickle.HIGHEST_PROTOCOL))
    else:
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def catalog() -> list[dict]:
    """機能: 管理32設定と6入口の組合せを結果閲覧前に定義する。

    引数: なし。返り値: 管理条件(list[dict])。
    """
    base = dict(kind=0,stop=16.,activation=8.,trail=8.,hold_seconds=3600.,grid=4.,step_fraction=.25,
                cover_activation=4.,cover_trail=2.,basket_stop=0.,basket_activation=0.,basket_trail=0.,
                flip_fraction=.5,partial_level=8.,partial_fraction=.5,tighten_minutes=15.,
                ratchet_step=8.,ratchet_keep=2.,grid_mode=0)
    managers = [dict(base,manager='B00',name='満額IFDトレール基準',group='基準',paired=False)]
    specs = [(4.,.25,4.,2.,16.,3600.,0,0.,0.),(4.,.25,4.,4.,16.,3600.,0,0.,0.),
             (8.,.25,4.,4.,32.,3600.,0,0.,0.),(4.,.5,4.,2.,16.,3600.,0,0.,0.),
             (8.,.5,8.,4.,32.,3600.,0,0.,0.),(4.,.25,4.,2.,16.,1800.,0,0.,0.),
             (4.,.25,4.,2.,16.,3600.,1,8.,4.),(8.,.5,8.,4.,32.,3600.,1,16.,8.)]
    for j,(grid,fraction,active,width,risk,hold,mode,ba,bw) in enumerate(specs,1):
        config = dict(base,kind=1,stop=32.,grid=grid,step_fraction=fraction,cover_activation=active,
                      cover_trail=width,basket_stop=risk,hold_seconds=hold,grid_mode=mode,
                      basket_activation=ba,basket_trail=bw)
        managers.append(dict(config,manager=f'H{j:02}',name='段階保険の両建て',group='保険両建て',paired=False))
        managers.append(dict(config,manager=f'N{j:02}',name='同判断の元玉縮小と復帰',group='縮小復帰',paired=True,paired_manager=f'H{j:02}'))
    for j,(grid,fraction,threshold) in enumerate(((4.,.25,.5),(4.,.25,1.),(8.,.25,.5),(4.,.5,.5)),1):
        managers.append(dict(base,kind=2,stop=32.,grid=grid,step_fraction=fraction,basket_stop=16.,
                             flip_fraction=threshold,manager=f'F{j:02}',name='保険を残して方向持ち替え',group='持ち替え',paired=False))
    for j,(level,fraction) in enumerate(((4.,.25),(4.,.5),(8.,.25),(8.,.5)),1):
        managers.append(dict(base,kind=3,partial_level=level,partial_fraction=fraction,
                             manager=f'P{j:02}',name='順行後の分割利確',group='分割利確',paired=False))
    for j,minutes in enumerate((5.,15.),1):
        managers.append(dict(base,kind=4,tighten_minutes=minutes,
                             manager=f'T{j:02}',name='時間経過でトレール短縮',group='時間短縮',paired=False))
    for j,(step,keep) in enumerate(((4.,0.),(4.,2.),(8.,0.),(8.,2.)),1):
        managers.append(dict(base,kind=5,activation=step,ratchet_step=step,ratchet_keep=keep,
                             manager=f'R{j:02}',name='利益の段階固定',group='利益固定',paired=False))
    assert len(managers)==31
    # 全玉を保護する独立対照を追加し、管理32設定とする。
    managers.append(dict(base,kind=0,basket_stop=8.,basket_activation=8.,basket_trail=4.,
                         manager='Q01',name='全玉損益の損失枠と利益保護',group='全玉保護',paired=False))
    return [dict(m,source=source,source_index=i,id=source+'_'+m['manager']) for i,source in enumerate(SOURCES) for m in managers]


def freeze() -> None:
    """機能: 管理・入口・比較方法・実装指紋を損益再生前に固定する。

    引数: なし。返り値: なし(None)。既存の固定があれば上書きしない。
    """
    path = HERE/'事前固定.json'
    assert not path.exists(),'既存の事前固定は上書きしない'
    old = load(ROOT/'work/wave_v69/事前固定.json')
    paths = [HERE/'engine.py',HERE/'net.py',HERE/'study.py',HERE/'inputs/signals.pkl',HERE/'inputs/schedule.pkl',
             HERE/'inputs/入口仕様.json',HERE/'inputs/共通入口スケジュール仕様.json',ROOT/'work/wave_v69/prepared/inputs.pkl',
             ROOT/'work/wave_v69/prepared/features.pkl']
    save(path,dict(条件=catalog(),全セッション=old['全セッション'],前16=old['前16'],後12=old['後12'],
                   共通入口='6入口部品。満額初回を同じ約定列へ固定、初回から3630秒は次親予約禁止。早期全返済後も同枠を維持。',
                   初回と片方向上限={'TOPIX':10,'NK225':20},円倍率={'TOPIX':1000.,'NK225':10.},片道料金={'TOPIX':41.8,'NK225':11.},
                   料金='新規・返済の1注文合計を切捨て。入口と返済の明細配賦は累積切捨て差分。',
                   主評価='入口から全玉返済までの一組損益。決済明細の利益損失・枚数も別表示し、保険玉勝率だけでは採用しない。',
                   対照='純保険8条件は同時刻・同枚数の元玉縮小復帰も実行し、全玉時価と終端の差を説明。',
                   選定='前16のみ。両銘柄20組・8活動場以上から、元基準に対する1組平均の手数料後呼値収支改善の弱い銘柄を最大化。両方黒字、平均勝組損益/平均負組損益>1なら有望。物理保険の首位と同判断ネット対照、その他管理首位を説明。後12で選び直さない。',
                   既知性='28場は既存研究で既知。未来参照なしだが完全未見ではない。',
                   参照気配='ラージ板をミニ・マイクロ仮想約定に使用。深さ・実商品気配・通信/取消競合なし。',
                   保険開始='保険新規の当行には保険トレールを監視せず、次観測から開始。保険は手動管理アルゴ、個別IFD玉の独立トレールではない。',
                   利益固定='観測で更新した保護線は次観測以降に成立判定。元玉子の基準は親予約時価格、分割利確では再基準化しない。',
                   保険利確='判断時点の清算気配で保険合計gross>往復見込料金、反転トレール成立を要求。次行fillで利益から損失に変わる場合も記録。',
                   途中持替='初期保険が上限の指定割合以上かつ共通入口信号が反対。元方向全返済、保険方向を主方向とし不足を次観測判断で追加。1組1回まで。',
                   API取得=0,実注文=0,SHA256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}))


def arguments(config: dict, key: tuple, ready: dict, features: dict, signals: dict, schedule: dict) -> tuple:
    """機能: 固定管理と保存原本をエンジンの引数へ接続する。

    引数: config/ready/features/signals/schedule(dict)、key(tuple)。返り値: 引数(tuple)。
    """
    r,f = ready[key],features[key]
    cap,value,fee = (10,1000.,41.8) if key[1]=='TOPIX' else (20,10.,11.)
    return (r['time_s'],f['bid'],f['ask'],signals[key][config['source_index']],schedule[key][config['source_index']],
            r['tick'],r['limit'],cap,value,fee,*[config[name] for name in FIELDS])


def account(key: tuple, ready: dict, orders: np.ndarray, trades: np.ndarray, curve: np.ndarray, counters: object) -> dict:
    """機能: 明細利益と全玉一組利益を分離し、最大下落・枚数・料金を記録する。

    引数: key(tuple)、ready(dict)、orders/trades/curve(ndarray)、counters(ndarray又はdict)。返り値: 場会計(dict)。
    """
    cap,value,fee = (10,1000.,41.8) if key[1]=='TOPIX' else (20,10.,11.)
    if isinstance(counters,dict):
        maxlong,maxshort = counters['最大買い保有'],counters['最大売り保有']
        assert counters['終端買い保有']==counters['終端売り保有']==counters['継続組数']==0
    else:
        maxlong,maxshort = int(counters[0]),int(counters[1])
        assert counters[2]==counters[3]==counters[4]==0,('未返済',key,counters)
    assert maxlong<=cap and maxshort<=cap
    assert all(0<=int(o[1])<int(o[0])<len(curve) for o in orders)
    totalfees = sum(math.floor(int(o[4])*fee+1e-8) for o in orders)
    assert int(trades[:,7:9].sum())==totalfees
    details = trades[:,10]
    ids = sorted(set(orders[:,2].astype(int)))
    groups = np.array([float(details[trades[:,0]==cid].sum()) for cid in ids])
    assert abs(float(details.sum())-float(curve[-1]))<1e-5
    won,lost = details>0,details<0
    a = dict(session=key[0],symbol=key[1],profit=float(details[won].sum()),loss=float(-details[lost].sum()),net=float(details.sum()),
             gross=float(trades[:,9].sum()),fees=totalfees,wins=int(won.sum()),losses=int(lost.sum()),trades=len(trades),
             winning_lots=int(trades[won,4].sum()),losing_lots=int(trades[lost,4].sum()),flat_lots=int(trades[details==0,4].sum()),
             campaign_profit=float(groups[groups>0].sum()),campaign_loss=float(-groups[groups<0].sum()),campaigns=len(groups),
             campaign_wins=int((groups>0).sum()),campaign_losses=int((groups<0).sum()),campaign_flats=int((groups==0).sum()),
             drawdown=float((np.maximum.accumulate(np.maximum(curve,0.))-curve).max()),equity_min=float(curve.min()),equity_max=float(curve.max()),
             max_long=maxlong,max_short=maxshort,max_campaign_loss=float(max(0.,-groups.min())) if len(groups) else 0.,
             core_net=float(details[trades[:,11]==0].sum()),cover_net=float(details[trades[:,11]==1].sum()),
             net_ticks=float(details.sum()/(cap*tick_of(ready,key)*value)),
             reasons={str(reason):int(((orders[:,6]==reason)&(orders[:,7]==0)).sum()) for reason in engine.REASONS})
    return a


def tick_of(ready: dict, key: tuple) -> float:
    """機能: 参照ラージの値幅単位を取得する。

    引数: ready(dict)、key(tuple)。返り値: 呼値幅(float)。
    """
    return float(ready[key]['tick'])


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """機能: 同銘柄の明細・一組会計と全期間時価下落を集計する。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 集計(dict)。
    """
    subset = sorted([r for r in rows if r['symbol']==symbol and r['session'] in sessions],key=lambda r:r['session'])
    fields = ('profit','loss','net','gross','fees','wins','losses','trades','winning_lots','losing_lots','flat_lots',
              'campaign_profit','campaign_loss','campaigns','campaign_wins','campaign_losses','campaign_flats','core_net','cover_net','net_ticks')
    a = {k:sum(r[k] for r in subset) for k in fields}
    a.update(active_sessions=sum(r['campaigns']>0 for r in subset),positive_sessions=sum(r['net']>0 for r in subset),
             campaign_win_rate=a['campaign_wins']/a['campaigns'] if a['campaigns'] else None,
             campaign_payoff=(a['campaign_profit']/a['campaign_wins'])/(a['campaign_loss']/a['campaign_losses']) if a['campaign_wins'] and a['campaign_losses'] else None,
             win_rate=a['wins']/a['trades'] if a['trades'] else None,
             payoff=(a['profit']/a['winning_lots'])/(a['loss']/a['losing_lots']) if a['winning_lots'] and a['losing_lots'] else None,
             mean_net_ticks=a['net_ticks']/a['campaigns'] if a['campaigns'] else None,
             max_long=max((r['max_long'] for r in subset),default=0),max_short=max((r['max_short'] for r in subset),default=0),
             max_campaign_loss=max((r['max_campaign_loss'] for r in subset),default=0),without_best_session=a['net']-max((r['net'] for r in subset),default=0))
    total = peak = dd = 0.
    for r in subset:
        dd = max(dd,r['drawdown'],peak-total-r['equity_min'])
        peak = max(peak,total+r['equity_max'])
        total += r['net']
    a['drawdown'] = dd
    return a


def run(ids: list[str]) -> None:
    """機能: 指定条件とその同判断対照を保存原本だけで再生する。

    引数: ids(list[str])。返り値: なし(None)。
    """
    fixed = load(HERE/'事前固定.json')
    ready = load(ROOT/'work/wave_v69/prepared/inputs.pkl')
    features = load(ROOT/'work/wave_v69/prepared/features.pkl')
    signals = load(HERE/'inputs/signals.pkl')
    schedule = load(HERE/'inputs/schedule.pkl')
    selected = [c for c in fixed['条件'] if not ids or c['id'] in ids]
    for config in selected:
        target = HERE/'results'/(config['id']+'.json')
        if target.exists():
            continue
        rows,ledgers = [],{}
        for key in sorted(ready):
            args = arguments(config,key,ready,features,signals,schedule)
            orders,trades,curve,counters = engine.simulate(*args)
            meta = None
            if config['paired']:
                original_net = float(curve[-1])
                orders,trades,curve,meta = net.pair(args[0],args[1],args[2],orders,args[7],args[8],args[9])
                assert abs(float(curve[-1])-original_net-meta['終了群の理論節約合計円'])<1e-5
                counters = meta
            rows.append(account(key,ready,orders,trades,curve,counters))
            ledgers[key] = dict(orders=orders,trades=trades,counters=counters,
                               curve_hash=hashlib.sha256(curve.tobytes()).hexdigest(),paired_metadata=meta)
        path = HERE/'ledgers'/(config['id']+'.pkl')
        save(path,ledgers)
        periods = {p:{s:aggregate(rows,s,keys) for s in SYMBOLS} for p,keys in
                   [('前16',fixed['前16']),('後12',fixed['後12']),('全28',fixed['全セッション'])]}
        save(target,dict(config=config,rows=rows,periods=periods,ledger_SHA256=hashlib.sha256(path.read_bytes()).hexdigest()))
        print(config['id'],'56口座完了',flush=True)


def deny(*args: object, **kwargs: object) -> None:
    """機能: 保存再生からのネットワーク接続を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)、例外RuntimeErrorを発生する。
    """
    raise RuntimeError('保存再生からの通信は禁止')


def main() -> None:
    """機能: 事前固定又は条件再生を実行する。

    引数: --freeze(bool)、--ids(str)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--ids',default='')
    args = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    if args.freeze:
        freeze()
        print('6入口×32管理を事前固定しました')
    else:
        run(args.ids.split(',') if args.ids else [])


if __name__=='__main__':
    main()
