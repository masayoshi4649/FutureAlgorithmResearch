"""始値・前場終値、方向制限、追跡幅、連敗休止を事前固定して比較する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
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

SYMBOLS = ('TOPIX', 'NK225')
PAUSES = ('休止なし','2連敗で10分','2連敗で30分','2連敗で収束待ち','2連敗で10分かつ収束','3連敗で30分')
REFERENCES = ('観測始値','前保存セッション終値','両基準の方向一致','過去60秒の価格')


def load(path: Path) -> object:
    """機能: 保存JSON又はpickleを読み取る。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(path: Path, value: object) -> None:
    """機能: 今回作業の中だけへ結果を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.pkl':
        path.write_bytes(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def digest(path: Path) -> str:
    """機能: 保存内容の指紋を読み取る。

    引数: path(Path)。返り値: SHA256(str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4*1024*1024):
            value.update(chunk)
    return value.hexdigest()


def catalog() -> list[dict]:
    """機能: 主288条件と対照192条件の設定を結果を見ずに列挙する。

    引数: なし。返り値: 全480条件(list[dict])。
    """
    out = []
    for group in ('主案','逆方向対照','基準跨ぎ返済なし','60秒方向対照'):
        refs = (3,) if group == '60秒方向対照' else range(3)
        pauses = range(6) if group in ('主案','60秒方向対照') else (0,)
        prefix = {'主案':'A','逆方向対照':'X','基準跨ぎ返済なし':'K','60秒方向対照':'M'}[group]
        for ref in refs:
            for entry in range(2):
                for band_i, band in enumerate((0., .00025)):
                    for width in (.0005, .001, .002, .004):
                        for pause in pauses:
                            ident = f'{prefix}{ref}_E{entry}_B{band_i}_W{int(width*10000):02}_P{pause}'
                            out.append(dict(id=ident,group=group,reference=ref,entry_type=entry,band=band,
                                            width_fraction=width,pause_mode=pause,inverse=group=='逆方向対照',
                                            exit_on_reverse=group!='基準跨ぎ返済なし',
                                            entry_fraction=.00025,hold_seconds=3600.,cooldown=30.,convergence_seconds=30.))
    assert len(out) == 480
    return out


def metric(a: dict) -> dict:
    """機能: 全明細の費用後金額から損失割合と平均損益を計算する。

    引数: a(dict)。返り値: 指標を追加した同じ会計(dict)。
    """
    p, loss, count = a['profit'], a['loss'], a['trades']
    a.update(money_loss_share=loss/(p+loss) if p+loss else None,
             profit_loss_ratio=p/loss if loss else None,
             average_win=p/a['wins'] if a['wins'] else None,
             average_loss=loss/a['losses'] if a['losses'] else None,
             average_net=a['net']/count if count else None,
             win_rate=a['wins']/count if count else None,
             payoff=(p/a['wins'])/(loss/a['losses']) if a['wins'] and a['losses'] else None,
             average_hold_seconds=a['hold_seconds']/count if count else None)
    return a


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """機能: 同じ銘柄の金額・枚数・休止を合算し、比率を合計金額から計算する。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 集計(dict)。
    """
    subset = sorted((r for r in rows if r['symbol'] == symbol and r['session'] in sessions), key=lambda r:r['session'])
    fields = ('profit','loss','net','gross','fees','wins','losses','flats','trades','winning_lots','losing_lots',
              'flat_lots','pause_count','resume_count','paused_seconds','resumed_trades','resumed_net','hold_seconds','spread_drag')
    a = {k:sum(r[k] for r in subset) for k in fields}
    a.update(active_sessions=sum(r['trades'] > 0 for r in subset),positive_sessions=sum(r['net'] > 0 for r in subset),
             max_trade_loss=max((r['max_trade_loss'] for r in subset), default=0.),
             without_best_session=a['net']-max((r['net'] for r in subset), default=0.),
             max_long=max((r['max_long'] for r in subset), default=0),max_short=max((r['max_short'] for r in subset), default=0),
             missing_reference_sessions=sum(r['missing_reference'] for r in subset))
    total = peak = dd = 0.
    for r in subset:
        dd = max(dd, r['drawdown'], peak-total-r['equity_min'])
        peak = max(peak, total+r['equity_max'])
        total += r['net']
    a['drawdown'] = dd
    return metric(a)


def material() -> tuple[dict,dict,dict]:
    """機能: 保存29場の価格と、参照価格の由来を読み取り専用で接続する。

    引数: なし。返り値: ready/features/参照metadata(tuple[dict,dict,dict])。
    """
    metadata = load(HERE/'inputs/refmetadata.json')
    merged = []
    for kind in ('ready','features'):
        data = {}
        for name in metadata['input_paths'][kind]:
            part = load(ROOT/name)
            assert not set(data)&set(part)
            data.update(part)
        merged.append(data)
    ready, features = merged
    assert len(ready) == 58 and set(ready) == set(features)
    return ready, features, metadata


def prepare(ready: dict, features: dict, metadata: dict) -> dict:
    """機能: 固定基準の方向と過去30/60秒行を、原本順だけで事前計算する。

    引数: ready/features/metadata(dict)。返り値: 共通準備配列(dict)。
    """
    out = {}
    for key, r in sorted(ready.items()):
        f = features[key]
        refs = metadata['references']['|'.join(key)]
        op, prev = refs['ref_open'], refs['ref_prev']
        broken = np.asarray(f['reset'], dtype=np.bool_)
        quality = np.asarray(f['valid'] & np.isfinite(f['bid']) & np.isfinite(f['ask'])
                             & (f['bid'] > 0) & (f['ask'] > f['bid'])
                             & (f['ask']-f['bid'] <= 2*r['tick']+r['tick']*1e-8), dtype=np.bool_)
        lag30 = engine.historical_rows(r['time_s'], broken | ~quality, 30.)
        lag60 = engine.historical_rows(r['time_s'], broken | ~quality, 60.)
        signals = {}
        for ref in range(4):
            for band in (0., .00025):
                signals[(ref,band)] = engine.make_direction(r['last'],lag60,op['value'],op['known_from_i'],
                    np.nan if prev['value'] is None else prev['value'],prev['known_from_i'],ref,band,False)
        out[key] = dict(direction=signals,lag30=lag30,quality=quality,open_price=op['value'],
                        missing_previous=prev['value'] is None)
    return out


def arguments(c: dict, key: tuple, ready: dict, features: dict, prepared: dict) -> tuple:
    """機能: 固定設定を再生器へ接続し、率の値幅をラージ呼値に切り上げる。

    引数: c/ready/features/prepared(dict)、key(tuple)。返り値: 再生引数(tuple)。
    """
    r, f, p = ready[key], features[key], prepared[key]
    tick = r['tick']
    width = max(2., math.ceil(p['open_price']*c['width_fraction']/tick-1e-10))*tick
    entry_width = max(1., math.ceil(p['open_price']*c['entry_fraction']/tick-1e-10))*tick
    direction = p['direction'][(c['reference'],c['band'])]
    if c['inverse']:
        direction = -direction
    qty, value, fee = (10,1000.,41.8) if key[1]=='TOPIX' else (20,10.,11.)
    return (r['time_s'],f['bid'],f['ask'],p['quality'],f['reset'],direction,p['lag30'],tick,r['start'],r['limit'],
            qty,value,fee,width,entry_width,c['entry_type'],c['pause_mode'],c['exit_on_reverse'],
            c['hold_seconds'],c['cooldown'],c['convergence_seconds'])


def account(c: dict, key: tuple, args: tuple, output: tuple, missing_previous: bool) -> dict:
    """機能: 全決済損失を相殺せず集計し、休止解除後の成績も記録する。

    引数: c(dict)、key/args/output(tuple)、missing_previous(bool)。返り値: 場会計(dict)。
    """
    orders, trades, curve, pauses, stats = output
    assert stats[0] == 0 and stats[1] in (0,1), ('場末未返済',key,c['id'],stats)
    assert len(orders) == 2*len(trades)
    assert all(int(o[0]) > int(o[1]) >= 0 for o in orders)
    net = trades[:,10]
    wins, losses, flats = net > 0, net < 0, net == 0
    fees = sum(math.floor(o[4]*args[12]+1e-8) for o in orders)
    assert abs(net.sum()-curve[-1]) < 1e-4 and fees == trades[:,7:9].sum()
    starts = list(pauses[pauses[:,1] == 0,0].astype(int))
    ends = list(pauses[pauses[:,1] == 1,0].astype(int))
    times = args[0]
    paused_seconds = sum(max(0.,min(times[ends[j]],args[9]-60.)-times[i]) if j < len(ends)
                         else max(0.,args[9]-60.-times[i]) for j,i in enumerate(starts))
    resumed = set()
    for end in ends:
        candidates = np.flatnonzero(trades[:,1] > end)
        if len(candidates):
            resumed.add(int(candidates[0]))
    qty, value = args[10], args[11]
    mid = (args[1]+args[2])/2.
    ideal_gross = sum(t[3]*(mid[int(t[2])]-mid[int(t[1])])*qty*value for t in trades)
    a = dict(session=key[0],symbol=key[1],profit=float(net[wins].sum()),loss=float(-net[losses].sum()),
             net=float(net.sum()),gross=float(trades[:,9].sum()),fees=int(fees),wins=int(wins.sum()),losses=int(losses.sum()),
             flats=int(flats.sum()),trades=len(trades),winning_lots=int(trades[wins,4].sum()),
             losing_lots=int(trades[losses,4].sum()),flat_lots=int(trades[flats,4].sum()),
             max_trade_loss=float(max(0.,-net.min())) if len(net) else 0.,
             max_long=qty if np.any(trades[:,3] == 1) else 0,max_short=qty if np.any(trades[:,3] == -1) else 0,
             drawdown=float((np.maximum.accumulate(np.maximum(curve,0.))-curve).max()),
             equity_min=float(curve.min()),equity_max=float(curve.max()),
             pause_count=int(stats[5]),resume_count=int(stats[6]),paused_seconds=float(paused_seconds),
             resumed_trades=len(resumed),resumed_net=float(sum(net[j] for j in resumed)),
             hold_seconds=float(sum(times[int(t[2])]-times[int(t[1])] for t in trades)),
             width=args[13],entry_width=args[14],spread_drag=float(ideal_gross-trades[:,9].sum()),
             missing_reference=missing_previous and c['reference'] in (1,2),
             reasons={str(code):int(((orders[:,6] == code)&(orders[:,7] == 0)).sum()) for code in engine.REASONS})
    return metric(a)


def freeze() -> None:
    """機能: 候補・前後分割・採点と実装指紋を損益再生前に固定する。

    引数: なし。返り値: なし(None)。既存固定は上書きしない。
    """
    target = HERE/'事前固定.json'
    assert not target.exists()
    meta = load(HERE/'inputs/refmetadata.json')
    sessions = meta['sessions']
    files = [Path(__file__),HERE/'engine.py',HERE/'inputs/refmetadata.json',HERE/'inputs/prepare_refs.py',
             HERE/'theory/基準価格と連敗休止の事前仮説.json']
    save(target,dict(条件=catalog(),全29=sessions,前16=sessions[:16],後13=sessions[16:],
        方針='銘柄別の全決済金額を採点。利益と損失を一組内で相殺せず各負けを全て含む。',
        主条件数=288,対照条件数=192,枚数={'TOPIX':10,'NK225':20},
        選定='前16のみ、主案の基準別3代表。両銘柄20取引・8活動場以上の中で悪い側の金額損失割合を最小化。同率なら両率平均、取引数、ID順。未充足なら両銘柄1取引以上の説明例を同順で選び、採用未達を明示。後13の結果で代表を変更しない。',
        確認基準='後13で両銘柄とも費用後黒字、平均勝ち/平均負け>1、最大黒字場を除いて黒字なら今回の有望条件。それ以外を成功と呼ばない。既知データの再探索なので独立の将来検証ではない。',
        値幅='観測始値の0.05/0.1/0.2/0.4%。ラージ呼値へ切上げ、最小2呼値。新規追跡幅と収束の反発幅は始値0.025%、最小1呼値。ATR不使用。',
        注文='新規は方向一致後の次有効気配、又は追跡安値/高値からの反発条件成立後の次有効気配。初期値からの順行でも追跡新規が成立する。買ask売bid、実建値から即時追跡、逆行幅=追跡幅。全量返済。',
        途中='主案は許可方向が反対へ変われば返済。中立で返済はしない。この返済を無効にした対照を休止なしで用意する。',
        休止='0なし、二敗10分、二敗30分、二敗収束、二敗10分かつ収束、三敗30分。敗北は一取引の両側料金後マイナス。勝ちと休止終了で連敗数0、同値は維持。',
        収束='現在許可方向の逆向き中値極値が30秒更新されず、極値から始値0.025%反発、かつ30秒前より両気配が同方向1呼値進む。方向変更/中立/品質不明で監視を準備し直す。',
        固定制約='入口は開始5分後から返済limit5分前まで。返済limit60秒前に全返済判断。通常再入場は返済から30秒後、保有60分で返済判断。休止中は新規のみ止める。',
        資料基準='始値欄のtimestampを照合、古ければ最初観測CurrentPrice。前終値は直前保存場の最終CurrentPriceで公式終値保証なし。最初場の前値欠測は補完しない。',
        対照='同設定の休止なし、基準と逆向き、基準跨ぎ返済なし、過去60秒方向。最後は固定基準を持たない別入口であり、完全同一入口のフィルター解除ではない。',
        限界='ラージ板の代理約定、CurrentPriceTime代理時計。参加者の実取得原価・心理・新規返済内訳・実商品の深さは観測できない。',
        API取得=0,実注文=0,SHA256={str(p.relative_to(ROOT)):digest(p) for p in files},入力SHA256=meta['input_SHA256']))


def run_one(c: dict, ready: dict, features: dict, meta: dict, prepared: dict, fixed: dict) -> str:
    """機能: 一条件を全58口座へ適用して、全明細台帳と期間会計を保存する。

    引数: c/ready/features/meta/prepared/fixed(dict)。返り値: 条件ID(str)。
    """
    target = HERE/'results'/(c['id']+'.json')
    if target.exists():
        return c['id']
    rows, ledger = [], {}
    for key in sorted(ready):
        args = arguments(c,key,ready,features,prepared)
        out = engine.simulate(*args)
        rows.append(account(c,key,args,out,prepared[key]['missing_previous']))
        ledger[key] = dict(orders=out[0],trades=out[1],pauses=out[3],stats=out[4],
                           curve_hash=hashlib.sha256(out[2].tobytes()).hexdigest())
    path = HERE/'ledgers'/(c['id']+'.pkl')
    save(path,ledger)
    periods = {name:{s:aggregate(rows,s,fixed[name]) for s in SYMBOLS} for name in ('前16','後13','全29')}
    save(target,dict(config=c,rows=rows,periods=periods,ledger_SHA256=digest(path)))
    return c['id']


def select() -> None:
    """機能: 前16だけから基準別代表を選び、後13は代表を変えず確認する。

    引数: なし。返り値: なし(None)。
    """
    results = [load(p) for p in sorted((HERE/'results').glob('*.json'))]
    assert len(results) == 480
    selected = []
    for reference in range(3):
        pool = [r for r in results if r['config']['group'] == '主案' and r['config']['reference'] == reference]
        qualified = [r for r in pool if all(r['periods']['前16'][s]['trades'] >= 20 and r['periods']['前16'][s]['active_sessions'] >= 8 for s in SYMBOLS)]
        eligible = bool(qualified)
        if not qualified:
            qualified = [r for r in pool if all(r['periods']['前16'][s]['trades'] > 0 for s in SYMBOLS)]
        assert qualified
        def score(r: dict) -> tuple:
            """機能: 両銘柄の悪い側の金額比率を先に評価する。

            引数: r(dict)。返り値: 昇順の評価値(tuple)。
            """
            a = [r['periods']['前16'][s] for s in SYMBOLS]
            return (max(x['money_loss_share'] for x in a),sum(x['money_loss_share'] for x in a),-sum(x['trades'] for x in a),r['config']['id'])
        choice = min(qualified,key=score)
        follow = choice['periods']['後13']
        passed = all(follow[s]['net'] > 0 and follow[s]['payoff'] is not None and follow[s]['payoff'] > 1
                     and follow[s]['without_best_session'] > 0 for s in SYMBOLS)
        selected.append(dict(id=choice['config']['id'],reference=reference,eligible=eligible,
                             score=score(choice),後13有望条件=passed))
    save(HERE/'前半選定.json',dict(代表=selected,前16だけで選択=True,後13で変更なし=True))
    print(json.dumps(selected,ensure_ascii=False))


def deny(*args: object, **kwargs: object) -> None:
    """機能: 保存再生中の外部接続を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)、RuntimeErrorを送出する。
    """
    raise RuntimeError('保存データ検証からの通信は禁止')


def main() -> None:
    """機能: 事前固定、全条件再生又は前半選定を実行する。

    引数: --freeze/--select(bool)、--workers(int)、--ids(str)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--select',action='store_true')
    parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--ids',default='')
    args = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    if args.freeze:
        freeze()
        print('480条件と前後分割を固定しました',flush=True)
        return
    if args.select:
        select()
        return
    fixed = load(HERE/'事前固定.json')
    assert all(digest(ROOT/p) == h for p,h in fixed['SHA256'].items())
    ready,features,meta = material()
    prepared = prepare(ready,features,meta)
    configs = [c for c in fixed['条件'] if not args.ids or c['id'] in args.ids.split(',')]
    first = configs[0]
    engine.simulate(*arguments(first,sorted(ready)[0],ready,features,prepared))
    with ThreadPoolExecutor(max_workers=max(1,min(12,args.workers))) as pool:
        tasks = [pool.submit(run_one,c,ready,features,meta,prepared,fixed) for c in configs]
        for i, task in enumerate(as_completed(tasks),1):
            ident = task.result()
            if i % 12 == 0 or i == len(tasks):
                print(f'{i}/{len(tasks)}条件の58口座完了（{ident}）',flush=True)


if __name__ == '__main__':
    main()
