"""4種類のティック機構とIFD・トレール設定を損益計算前に固定する。"""

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np
import numba

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
numba.config.CACHE_DIR = str(HERE/'numba_cache')
import engine

SYMBOLS = ('TOPIX','NK225')


def read(path: Path) -> object:
    """機能: 日本語JSON又は保存pickleを読み取る。

    引数: path(Path)。返り値: 内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(path: Path, value: object) -> None:
    """機能: 新作業内へ保存し、過去成果へ書き込まない。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.pkl':
        path.write_bytes(pickle.dumps(value,protocol=pickle.HIGHEST_PROTOCOL))
    else:
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def digest(path: Path) -> str:
    """機能: 実装と入力のSHA256を得る。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def catalog() -> list[dict]:
    """機能: 八入口・二親・四子・三保有期限を固定する。

    引数: なし。返り値: 全192条件(list[dict])。
    """
    exits = [('F4',0.,0.,4.),('O8A4W4',8.,4.,4.),('O16A8W8',16.,8.,8.),('O8A4W2',8.,4.,2.)]
    out = []
    for family in range(4):
        for strength in range(2):
            for entry in range(2):
                for label,stop,activation,width in exits:
                    for hold in (300.,1800.,3600.):
                        identifier = f'T{family+1}L{strength}_E{entry}_{label}_H{int(hold/60)}'
                        out.append(dict(id=identifier,family=family+1,strength=strength,signal=family*2+strength,
                            entry_type=entry,entry_width=2.,initial_stop=stop,activation=activation,trail_width=width,
                            hold_seconds=hold,parent_ttl=120.,cooldown=30.,method='ifd' if stop==0 else 'ifd_oco'))
    return out


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """機能: 同商品の料金後会計と全期間の含み時価下落を集計する。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 会計(dict)。
    """
    subset = sorted([r for r in rows if r['symbol']==symbol and r['session'] in sessions],key=lambda r:r['session'])
    fields = ('profit','loss','net','gross','fees','wins','losses','flats','trades','winning_lots','losing_lots','flat_lots','net_ticks')
    a = {name:sum(r[name] for r in subset) for name in fields}
    a.update(active_sessions=sum(r['trades']>0 for r in subset),positive_sessions=sum(r['net']>0 for r in subset),sessions=len(subset),
        win_rate=a['wins']/a['trades'] if a['trades'] else None,
        mean_net_ticks=a['net_ticks']/a['trades'] if a['trades'] else None,
        payoff=(a['profit']/a['winning_lots'])/(a['loss']/a['losing_lots']) if a['winning_lots'] and a['losing_lots'] else None,
        max_trade_loss=max((r['max_trade_loss'] for r in subset),default=0.),
        max_session_drawdown=max((r['drawdown'] for r in subset),default=0.),
        ideal_net=sum(r['ideal_net'] for r in subset))
    total = peak = dd = 0.
    for r in subset:
        dd = max(dd,r['drawdown'],peak-total-r['equity_min'])
        peak = max(peak,total+r['equity_max'])
        total += r['net']
    assert abs(a['net']-total)<1e-6
    a['drawdown'] = dd
    a['without_best_session'] = a['net']-max((r['net'] for r in subset),default=0.)
    return a


def account(key: tuple, ready: dict, features: dict, orders: np.ndarray, trades: np.ndarray, curve: np.ndarray, counters: np.ndarray) -> dict:
    """機能: 全返済の取引別利益・損失・枚数と注文固定中値感度を算出する。

    引数: key(tuple)、ready/features(dict)、注文/決済/曲線/統計(ndarray)。返り値: 場会計(dict)。
    """
    symbol = key[1]
    quantity,value,fee = (5,1000.,41.8) if symbol=='TOPIX' else (10,10.,11.)
    net = trades[:,10]
    winner,loser,flat = net>0,net<0,net==0
    fees = int(orders.shape[0]*np.floor(quantity*fee+1e-8))
    assert counters[0]==0 and counters[1] in (0,1),('保存完了場で未返済',key,counters)
    assert len(orders)==2*len(trades)
    assert abs(curve[-1]-net.sum())<1e-5
    assert all(0<=int(o[1])<int(o[0])<len(curve) for o in orders)
    ideal_gross = float(sum(t[3]*(features['mid'][int(t[2])]-features['mid'][int(t[1])])*quantity*value for t in trades))
    dd = np.maximum.accumulate(np.maximum(curve,0.))-curve
    return dict(session=key[0],symbol=symbol,profit=float(net[winner].sum()),loss=float(-net[loser].sum()),net=float(net.sum()),
        gross=float(trades[:,9].sum()),fees=fees,wins=int(winner.sum()),losses=int(loser.sum()),flats=int(flat.sum()),trades=len(trades),
        winning_lots=int(trades[winner,4].sum()),losing_lots=int(trades[loser,4].sum()),flat_lots=int(trades[flat,4].sum()),
        net_ticks=float(net.sum()/(quantity*value*ready['tick'])),ideal_net=ideal_gross-fees,
        drawdown=float(dd.max(initial=0)),equity_min=float(curve.min(initial=0)),equity_max=float(curve.max(initial=0)),
        max_trade_loss=float(-min(0.,net.min(initial=0))),
        hold_median=float(np.median(ready['time_s'][trades[:,2].astype(int)]-ready['time_s'][trades[:,1].astype(int)])) if len(trades) else None,
        max_long=quantity if (trades[:,3]==1).any() else 0,max_short=quantity if (trades[:,3]==-1).any() else 0,
        parent_submitted=int(counters[3]),parent_triggered=int(counters[4]),parent_canceled=int(counters[5]),
        reasons={str(reason):int((orders[:,6]==reason).sum()) for reason in engine.REASONS})


def freeze() -> dict:
    """機能: 条件・選定規則・執行仕様・実装指紋を損益再生前に固定する。

    引数: なし。返り値: 固定書(dict)。
    """
    old = read(ROOT/'work/wave_v68/事前固定.json')
    paths = [HERE/'engine.py',Path(__file__),HERE/'signals/core.py',HERE/'signals/入口仕様.json',HERE/'signals/signals.pkl',
        HERE/'prepared/inputs.pkl',HERE/'prepared/features.pkl',HERE/'prepared/events.pkl']
    fixed = dict(条件=catalog(),全セッション=old['全セッション'],前16=old['前16'],後12=old['後12'],
        初回枚数={'TOPIX':5,'NK225':10},片方向上限={'TOPIX':10,'NK225':20},
        手数料={'TOPIXmini':41.8,'NK225micro':11},円倍率={'TOPIX':1000,'NK225':10},
        主評価='買ask売bid。親予約の次PUSHから監視、成立の次有効原本行で約定。IFD子は新規約定後の次PUSHから監視。',
        子価格='親予約時のask(買)/bid(売)を絶対価格基準とし、子stop/activationは実約定後に相対化しない。OCO同時成立はstop優先。',
        場内返済='既存入力の返済限界limitの60秒前に全返済を予約。新規はlimitの5分前まで。保存終端に強制約定しない。',
        時計='原本seq順。同秒更新も次行遅延。time_sは最終約定時計で受信時計ではない。無効気配は直前有効気配で評価、発注は次有効で執行。',
        価格感度='同じ注文の価格だけ中値へ置換したideal_netは非実行可能な診断。注文・子条件・次入口は再計算しない。',
        選定='4機構ごと前16だけ。両銘柄それぞれ20取引以上・8活動場以上を満たす条件を対象とし、弱い側の1取引平均料金後呼値利益を最大化。両銘柄黒字・1枚平均勝負比1超なら有望、未達なら比較用上位と表示。後12を見た選び直しなし。',
        既知性='保存28は既知。時間順比較は未見検証の証明ではない。',
        保存API取得=0,実注文=0,SHA256={str(p.relative_to(HERE)):digest(p) for p in paths})
    target = HERE/'事前固定.json'
    if target.exists():
        assert read(target)==fixed,'固定後の変更を検出'
    else:
        save(target,fixed)
    return fixed


def run(identifiers: list[str]) -> None:
    """機能: 固定条件を全56口座へ再生し、会計と全売買台帳を保存する。

    引数: identifiers(list[str])。返り値: なし(None)。
    """
    fixed = freeze()
    inputs,features,signals = [read(HERE/path) for path in ('prepared/inputs.pkl','prepared/features.pkl','signals/signals.pkl')]
    assert len(inputs)==len(features)==len(signals)==56
    for config in catalog():
        if identifiers and config['id'] not in identifiers:
            continue
        target = HERE/'results'/(config['id']+'.json')
        if target.exists():
            continue
        rows,ledgers = [],{}
        for key in sorted(inputs):
            r,f = inputs[key],features[key]
            quantity,value,fee = (5,1000.,41.8) if key[1]=='TOPIX' else (10,10.,11.)
            args = (r['time_s'],f['bid'],f['ask'],signals[key][config['signal']],f['reset'],r['tick'],r['start'],r['limit'],quantity,value,fee,
                config['entry_type'],config['entry_width'],config['initial_stop'],config['activation'],config['trail_width'],config['hold_seconds'],config['parent_ttl'],config['cooldown'])
            orders,trades,curve,counters = engine.simulate(*args)
            row = account(key,r,f,orders,trades,curve,counters)
            rows.append(row)
            ledgers[key] = dict(orders=orders,trades=trades,counters=counters,curve_hash=hashlib.sha256(curve.tobytes()).hexdigest())
        ledger = HERE/'ledgers'/(config['id']+'.pkl')
        save(ledger,ledgers)
        periods = {label:{s:aggregate(rows,s,names) for s in SYMBOLS} for label,names in
            [('前16',fixed['前16']),('後12',fixed['後12']),('全28',fixed['全セッション'])]}
        save(target,dict(config=config,rows=rows,periods=periods,ledger_SHA256=digest(ledger)))
        print(config['id'],'56口座完了',flush=True)


def deny(*args: object, **kwargs: object) -> None:
    """機能: 保存データ再生中のネットワーク接続を拒否する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)。例外RuntimeErrorを発生する。
    """
    raise RuntimeError('保存再生からの通信は禁止')


def main() -> None:
    """機能: 保存検証の固定又は指定条件の再生を開始する。

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
        print('192条件・親子時計・前半選定を固定しました')
    else:
        run(args.ids.split(',') if args.ids else [])


if __name__ == '__main__':
    main()
