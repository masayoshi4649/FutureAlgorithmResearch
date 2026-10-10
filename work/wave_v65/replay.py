"""候補3の入口へ、百分率損切りと利益開始後の追跡返済を組み合わせる。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
from numba import njit


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査/00062_候補3の全力新規と利益保護トレール'
INPUTS = HERE.parent / 'wave_v60/inputs.pkl'
QUOTES = HERE.parent / 'wave_v60/quotes.pkl'
SIGNALS = HERE.parent / 'wave_v63/directional/round3/入口候補.pkl'
OLD = HERE.parent / 'wave_v63/directional/round3/ledgers/R3_DEPTH_C_quote.pkl'


def save(path: Path, data: object) -> None:
    """機能: 非有限値を拒否してUTF-8の検証情報を保存する。

    引数: path(Path)、data(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def configurations() -> list[dict]:
    """機能: 主案と事前に指定した幅の感度12条件を構成する。

    引数: なし。返り値: 損切り幅3通りと追跡幅4通り(list[dict])。
    最初の利益保護線は0.1%に固定し、開始幅は保護線と追跡幅の和とする。
    """
    return [dict(id=f'S{stop*100:.2f}_T{trail*100:.2f}', stop=stop, trail=trail,
                 arm=.001 + trail, floor=.001, primary=stop == .001 and trail == .0001)
            for stop in (.001, .0015, .002) for trail in (.0001, .0002, .0005, .001)]


@njit(cache=True)
def trace(times: np.ndarray, bid: np.ndarray, ask: np.ndarray, decision: int, side: int,
          stop: float, arm: float, trail: float, floor: float, cutoff: float) -> tuple:
    """機能: 次行新規約定から、一方向の保護線を原板順だけで追跡する。

    引数: times/bid/ask(ndarray)、decision/side(int)、各割合/cutoff(float)。
    返り値: 返済判断行、約定行、開始行、保護線利益幅、最大順行幅、理由(tuple)。
    理由1は初期損切り、2は追跡返済、4は監視区間終了前の返済。
    """
    entry = decision + 1
    anchor = ask[entry] if side > 0 else bid[entry]
    best, active, armed_i = -1.e100, False, -1
    line = -anchor * stop
    for i in range(entry, len(times)):
        liquidation = bid[i] if side > 0 else ask[i]
        gain = side * (liquidation - anchor)
        best = max(best, gain)
        if not active and best >= anchor * arm - 1.e-9:
            active, armed_i = True, i
        if active:
            line = max(line, anchor * floor, best - anchor * trail)
        reason = 4 if times[i] >= cutoff else (2 if active else 1) if gain <= line + 1.e-9 else 0
        if reason:
            return i, i + 1, armed_i, line, max(0., best), reason
    return -1, -1, armed_i, line, max(0., best), 0


def one(ready: dict, quotes: dict, decision: int, side: int, config: dict) -> dict:
    """機能: 1入口の次行約定と百分率返済、手数料を算出する。

    引数: ready/quotes/config(dict)、decision/side(int)。返り値: 全約定と損益(dict)。
    返済後の最大順行は原因採点だけに使い、売買判断へ与えない。
    """
    topix = ready['symbol'] == 'TOPIX'
    qty, value, fee = (10, 1000., 418) if topix else (20, 10., 220)
    entry_i = decision + 1
    assert quotes['time_s'][entry_i] < ready['limit'] - 300.
    d, x, armed_i, line, peak, reason = trace(quotes['time_s'], quotes['bid'], quotes['ask'], decision, side,
        config['stop'], config['arm'], config['trail'], config['floor'], ready['limit'] - 60.)
    assert d >= entry_i and x == d + 1 and x < len(quotes['seq'])
    assert quotes['time_s'][x] < ready['limit'] + 300.
    entry_price = float(quotes['ask'][entry_i] if side > 0 else quotes['bid'][entry_i])
    exit_price = float(quotes['bid'][x] if side > 0 else quotes['ask'][x])
    gross = side * (exit_price - entry_price) * qty * value
    row = dict(session=ready['session'], symbol=ready['symbol'], side=side, qty=qty, value=value,
        decision_i=decision, entry_i=entry_i, exit_decision_i=int(d), exit_i=int(x), armed_i=int(armed_i),
        decision_seq=int(ready['seq'][decision]), entry_seq=int(ready['seq'][entry_i]),
        exit_decision_seq=int(ready['seq'][d]), exit_seq=int(ready['seq'][x]),
        decision_time=float(ready['time_s'][decision]), entry_time=float(ready['time_s'][entry_i]),
        exit_decision_time=float(ready['time_s'][d]), exit_time=float(ready['time_s'][x]),
        entry_price=entry_price, exit_price=exit_price, gross=gross, entry_fee=fee, exit_fee=fee,
        fees=fee * 2, net=gross - fee * 2, reason=int(reason), protected=armed_i >= 0,
        stop_gain=float(line), peak_gain=float(peak), hold_minutes=float((ready['time_s'][x]-ready['time_s'][entry_i])/60.),
        protected_target_shortfall=bool(armed_i >= 0 and side * (exit_price-entry_price) < entry_price*config['floor']-1.e-9))
    # ----------------------------------------
    # 下記は全返済決定後にのみ行う事後採点。入口・出口エンジンには渡さない。
    liquidation = quotes['bid'][entry_i:] if side > 0 else quotes['ask'][entry_i:]
    maximum = float(np.max(side * (liquidation - entry_price)))
    row['eventual_target'] = maximum >= entry_price * .001 - 1.e-9
    row['stopped_then_eventual_target'] = reason == 1 and row['eventual_target']
    return row


def summarize(rows: list[dict]) -> dict:
    """機能: 手数料後の勝敗、金額、枚数と平均損益比を集計する。

    引数: rows(list[dict])。返り値: 集計(dict)。無取引を勝ちには含めない。
    """
    win = [r for r in rows if r['net'] > 0]
    loss = [r for r in rows if r['net'] < 0]
    profit, damage = sum(r['net'] for r in win), -sum(r['net'] for r in loss)
    avg_win, avg_loss = (profit / len(win) if win else None), (damage / len(loss) if loss else None)
    return dict(trades=len(rows), wins=len(win), losses=len(loss), flats=sum(r['net']==0 for r in rows),
        win_rate=len(win)/len(rows) if rows else None, profit=profit, loss=damage, net=profit-damage,
        gross=sum(r['gross'] for r in rows), fees=sum(r['fees'] for r in rows),
        win_qty=sum(r['qty'] for r in win), loss_qty=sum(r['qty'] for r in loss),
        flat_qty=sum(r['qty'] for r in rows if r['net']==0),
        avg_win=avg_win, avg_loss=avg_loss, payoff=avg_win/avg_loss if avg_loss and avg_win is not None else None,
        pf=profit/damage if damage else None, protected=sum(r['protected'] for r in rows),
        protected_shortfall=sum(r['protected_target_shortfall'] for r in rows),
        stopped_then_target=sum(r['stopped_then_eventual_target'] for r in rows),
        stop_count=sum(r['reason']==1 for r in rows), trail_count=sum(r['reason']==2 for r in rows),
        close_count=sum(r['reason']==4 for r in rows),
        hold_median_minutes=float(np.median([r['hold_minutes'] for r in rows])) if rows else None)


def replay(ready: dict, quotes: dict, signals: np.ndarray, config: dict) -> tuple:
    """機能: 1口座を同時上限と決済後10分休止を守って連続再生する。

    引数: ready/quotes/config(dict)、signals(ndarray)。返り値: 約定一覧と候補処理(tuple)。
    全力の初回だけを建て、追加・両建て・保有期限・日次損失停止は設けない。
    """
    rows = []
    gates = dict(candidates=len(signals), accepted=0, scheduled=0, holding=0, cooldown=0, cutoff=0, expired=0)
    previous_exit, next_entry = -1, -np.inf
    for signal in signals:
        i, side = int(signal[0]), int(signal[1])
        if i <= previous_exit:
            gates['holding'] += 1
        elif quotes['time_s'][i] >= ready['limit']-300.:
            gates['cutoff'] += 1
        elif quotes['time_s'][i] < next_entry:
            gates['cooldown'] += 1
        else:
            # 判定行では新規を予約し、次行へ進んだ時点で約定期限を確認する。
            # 次行時刻を入口指標に用いず、期限超過は未約定取消として数える。
            gates['scheduled'] += 1
            fill_i = i + 1
            if quotes['time_s'][fill_i] >= ready['limit']-300.:
                gates['expired'] += 1
                continue
            row = one(ready, quotes, i, side, config)
            rows.append(row)
            gates['accepted'] += 1
            previous_exit, next_entry = row['exit_i'], row['exit_time'] + 600.
    assert sum(gates[k] for k in ('accepted','holding','cooldown','cutoff','expired')) == gates['candidates']
    assert gates['scheduled'] == gates['accepted'] + gates['expired']
    return rows, gates


def synthetic() -> dict:
    """機能: 損切り先着、利益追跡、値飛び、売り対称性を合成価格で検査する。

    引数: なし。返り値: 合格結果(dict)。
    """
    cfg = configurations()[0]
    checks = []
    for side in (1, -1):
        for name, gains, expected in (
            ('損切り後に順行しても待たない', [0,0,-101,-102,200,300], (2,3,1)),
            ('開始後は利益に追従', [0,0,120,500,480,475], (4,5,2)),
            ('未開始の反落は初期損切り', [0,0,105,50,-105,-110], (4,5,1)),
            ('保護線越えの値飛び', [0,0,120,80,70,60], (3,4,2))):
            price = 100000. + side*np.asarray(gains, float)
            result = trace(np.arange(len(price),dtype=float),price,price,0,side,cfg['stop'],cfg['arm'],cfg['trail'],cfg['floor'],9999.)
            assert (int(result[0]),int(result[1]),int(result[5])) == expected
            checks.append(dict(名前=name,方向=side,合格=True))
    return dict(全合格=True,件数=len(checks),検査=checks)


def main() -> None:
    """機能: 結果前に12条件を固定して全50口座と旧42入口を再生する。

    引数: なし。返り値: なし(None)。現在API取得・実注文は行わない。
    """
    target = HERE / '結果.json'
    assert not target.exists(), '過去の計算を上書きしません'
    OUT.mkdir(parents=True,exist_ok=True)
    config = configurations()
    fixed = dict(固定時刻=datetime.now(timezone.utc).isoformat(),主案=config[0],全条件=config,
        入口='凍結済みR3_DEPTHの原板行と方向。新しい入口の探索なし。',
        枚数=dict(NK225micro=20,TOPIXmini=10),幅基準='次行新規約定価格。連続値の監視条件で判定し、約定は板の離散価格。',
        監視='含み利益は長玉bid/短玉ask。新規・返済とも条件判定の次の有効原板行の気配。',
        トレール='最高含み値幅から固定割合幅を差し引き、最初の0.1%利益線より下げない。最低約定利益の保証ではない。',
        その他='元入口の決済後10分休止と新規締切を維持。保有60分期限と日次停止は今回設けず、場内返済。',
        区間='Day15:34/Night05:49以後の最初の有効行で返済判断し次行約定。新規は15:30/05:45未満。',
        比較='旧全入口の個別追跡は重複し得るため実ポートフォリオではない。連続再生を主成績とする。',
        手数料='NKmicro20枚は片道220円、TOPIXmini10枚は片道418円。両側課金。',
        限界='ラージ売買気配の小商品代理。発注遅延・板の食い込みなし。全25場既知で新規未見検証ではない。',
        SHA={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),INPUTS,QUOTES,SIGNALS,OLD)},現在API取得=0,実注文=0)
    save(HERE/'実行前固定.json',fixed)
    save(HERE/'合成検査.json',synthetic())
    inputs,quotes,signals,old = [pickle.loads(p.read_bytes()) for p in (INPUTS,QUOTES,SIGNALS,OLD)]
    methods = []
    for c in config:
        accounts,rows,isolated = [],[],[]
        for key in sorted(inputs):
            ready,q = inputs[key],quotes[key]
            for name in ('seq','time_s'):
                np.testing.assert_array_equal(ready[name],q[name])
            trades,gates = replay(ready,q,signals[key]['DEPTH'],c)
            rows.extend(trades)
            accounts.append(dict(session=key[0],symbol=key[1],**summarize(trades),gates=gates))
            previous = old[(*key,'quote')]['trades']
            for trade in previous:
                i = int(np.searchsorted(ready['seq'],int(trade[18])))
                assert int(ready['seq'][i]) == int(trade[18])
                isolated.append(one(ready,q,i,int(trade[2]),c))
        method = dict(config=c,accounts=accounts,rows=rows,isolated=isolated,
            summary={s:summarize([r for r in rows if r['symbol']==s]) for s in ('TOPIX','NK225')},
            isolated_summary={s:summarize([r for r in isolated if r['symbol']==s]) for s in ('TOPIX','NK225')})
        methods.append(method)
        print(c['id'],json.dumps(method['summary'],ensure_ascii=False))
    result = dict(methods=methods,口座数=len(inputs),セッション数=len(inputs)//2,
        原板有効行数=sum(len(r['seq']) for r in inputs.values()),固定SHA=hashlib.sha256((HERE/'実行前固定.json').read_bytes()).hexdigest())
    save(target,result)
    for name in ('結果.json','実行前固定.json','合成検査.json'):
        (OUT/name).write_bytes((HERE/name).read_bytes())
    print('全12条件を完了しました')


if __name__ == '__main__':
    main()
