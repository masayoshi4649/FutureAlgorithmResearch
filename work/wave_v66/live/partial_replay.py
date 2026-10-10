"""固定12主案を取得済み板の順だけで再生し、未返済の含み損益を残す。"""

import argparse
import json
from pathlib import Path
import pickle

import numpy as np

import prepare_live


HERE = Path(__file__).resolve().parent
WORK = HERE.parent


def state(ready: dict, quotes: dict, index: int, qty: int, value: float, fee: int,
          gross: float, incurred: int, side: int, anchor: float, entry_i: int,
          pending_entry: dict | None, pending_exit: dict | None) -> dict:
    """機能: 原板の途中時点で実現・発生費用・全残玉含みを会計する。

    引数: ready/quotes(dict)、index/qty/fee/incurred/side/entry_i(int)、
          value/gross/anchor(float)、pending_entry/pending_exit(dict|None)。
    返り値: 途中資産と未返済・未約定の状態(dict)。未来返済費用は課さない。
    """
    liquidation = float(quotes['bid'][index] if side > 0 else quotes['ask'][index]) if side else None
    unrealized = side * qty * (liquidation - anchor) * value if side else 0.
    opened = [dict(side=side, quantity=qty, entry_i=entry_i, entry_seq=int(ready['seq'][entry_i]),
                   entry_price=anchor, entry_fee=fee, liquidation_price=liquidation,
                   unrealized=unrealized, future_exit_fee_incurred=False)] if side else []
    return dict(valid_rows=index + 1, seq=int(ready['seq'][index]) if index >= 0 else None,
                time_s=float(ready['time_s'][index]) if index >= 0 else None,
                gross_realized=gross, fees=incurred, realized_after_incurred_fees=gross - incurred,
                unrealized=unrealized, net=gross - incurred + unrealized,
                long_qty=qty if side > 0 else 0, short_qty=qty if side < 0 else 0,
                open_entry_fees=fee if side else 0, open_positions=opened,
                pending_entry=pending_entry, pending_exit=pending_exit)


def simulate(ready: dict, quotes: dict, signals: np.ndarray, config: dict, known_count: int) -> dict:
    """機能: 一場の原板を前向きに再生し、未返済玉と既知境界を維持する。

    引数: ready/quotes/config(dict)、signals(ndarray)、known_count(int)。
    返り値: 決済・新規一覧、既知境界、末尾資産と追加区間損益(dict)。
    新規・返済は判断の次行。セッション途中の末尾では仮想清算しない。
    """
    times = ready['time_s']
    n = len(times)
    assert 0 <= known_count <= n
    topix = ready['symbol'] == 'TOPIX'
    qty, value, fee = (10, 1000., 418) if topix else (20, 10., 220)
    cfg = config['exit_config']
    beginning = state(ready, quotes, -1, qty, value, fee, 0., 0, 0, 0., -1, None, None)
    boundary = beginning if not known_count else None
    end = beginning
    side, entry_i, pending_new, pending_close = 0, -1, None, None
    anchor, best, line = 0., -np.inf, 0.
    active, armed_i = False, -1
    next_entry, cursor, gross, incurred = -np.inf, 0, 0., 0
    rows, orders = [], []
    group, entry_decision = 0, -1
    gates = dict(candidates=len(signals), accepted=0, scheduled=0, holding=0,
                 cooldown=0, cutoff=0, expired=0, pending=0)
    for i in range(n):
        held_at_start = side != 0 or pending_new is not None
        if pending_close is not None:
            assert side and pending_close['i'] == i - 1
            exit_price = float(quotes['bid'][i] if side > 0 else quotes['ask'][i])
            profit = side * qty * (exit_price - anchor) * value
            gross, incurred = gross + profit, incurred + fee
            row = dict(session=ready['session'], symbol=ready['symbol'], side=side, qty=qty, value=value,
                decision_i=entry_decision, entry_i=entry_i, exit_decision_i=pending_close['i'], exit_i=i,
                decision_seq=int(ready['seq'][entry_decision]), entry_seq=int(ready['seq'][entry_i]),
                exit_decision_seq=int(ready['seq'][pending_close['i']]), exit_seq=int(ready['seq'][i]),
                entry_time=float(times[entry_i]), exit_time=float(times[i]), entry_price=anchor,
                exit_price=exit_price, gross=profit, entry_fee=fee, exit_fee=fee, fees=2 * fee,
                net=profit - 2 * fee, reason=pending_close['reason'], protected=active,
                armed_i=armed_i, stop_gain=line, peak_gain=max(0., best), group_id=group,
                hold_minutes=float((times[i] - times[entry_i]) / 60.),
                protected_target_shortfall=bool(active and side * (exit_price-anchor) < anchor * cfg['floor'] - 1.e-9))
            rows.append(row)
            orders.append(dict(action='返済', side=-side, qty=qty, price=exit_price, fee=fee,
                               decision_i=pending_close['i'], fill_i=i, group_id=group, gross=profit))
            side, pending_close, next_entry = 0, None, float(times[i]) + 600.
        if pending_new is not None:
            assert not side and pending_new['i'] == i - 1
            if times[i] >= ready['limit'] - 300.:
                gates['expired'] += 1
            else:
                side, entry_decision, entry_i = pending_new['side'], pending_new['i'], i
                anchor = float(quotes['ask'][i] if side > 0 else quotes['bid'][i])
                best, line, active, armed_i = -np.inf, -anchor * cfg['stop'], False, -1
                incurred, group = incurred + fee, group + 1
                gates['accepted'] += 1
                orders.append(dict(action='新規', side=side, qty=qty, price=anchor, fee=fee,
                                   decision_i=entry_decision, fill_i=i, group_id=group, gross=0.))
            pending_new = None
        # ----------------------------------------
        # 保護線は原板の現在気配だけで更新し、次行に返済を予約する。
        if side:
            liquidation = float(quotes['bid'][i] if side > 0 else quotes['ask'][i])
            gain = side * (liquidation - anchor)
            best = max(best, gain)
            if not active and best >= anchor * cfg['arm'] - 1.e-9:
                active, armed_i = True, i
            if active:
                line = max(line, anchor * cfg['floor'], best - anchor * cfg['trail'])
            reason = (4 if times[i] >= ready['limit'] - 60.
                      else (2 if active else 1) if gain <= line + 1.e-9 else 0)
            if reason:
                pending_close = dict(i=i, seq=int(ready['seq'][i]), reason=reason)
        while cursor < len(signals) and int(signals[cursor, 0]) == i:
            direction = int(signals[cursor, 1])
            if held_at_start or side or pending_new is not None:
                gates['holding'] += 1
            elif times[i] >= ready['limit'] - 300.:
                gates['cutoff'] += 1
            elif times[i] < next_entry:
                gates['cooldown'] += 1
            else:
                pending_new = dict(i=i, seq=int(ready['seq'][i]), side=direction)
                gates['scheduled'] += 1
            cursor += 1
        end = state(ready, quotes, i, qty, value, fee, gross, incurred, side, anchor, entry_i,
                    dict(pending_new) if pending_new is not None else None,
                    dict(pending_close) if pending_close is not None else None)
        if i + 1 == known_count:
            boundary = end
    gates['pending'] = int(pending_new is not None)
    assert cursor == len(signals) and boundary is not None
    assert sum(gates[key] for key in ('accepted', 'holding', 'cooldown', 'cutoff', 'expired', 'pending')) == len(signals)
    assert gates['scheduled'] == gates['accepted'] + gates['expired'] + gates['pending']
    added = {key: end[key] - boundary[key] for key in
             ('gross_realized', 'fees', 'realized_after_incurred_fees', 'unrealized', 'net')}
    added.update(valid_rows=n - known_count, long_qty_start=boundary['long_qty'], long_qty_end=end['long_qty'],
                 short_qty_start=boundary['short_qty'], short_qty_end=end['short_qty'])
    np.testing.assert_allclose(added['net'], added['gross_realized'] - added['fees'] + added['unrealized'], atol=1.e-7)
    won, lost = [row for row in rows if row['net'] > 0], [row for row in rows if row['net'] < 0]
    np.testing.assert_allclose(end['net'], sum(row['net'] for row in rows) + end['unrealized'] - end['open_entry_fees'], atol=1.e-7)
    return dict(session=ready['session'], symbol=ready['symbol'], config=config,
                rows=rows, orders=orders, gates=gates, trades=len(rows), wins=len(won), losses=len(lost),
                flats=sum(row['net'] == 0 for row in rows), win_rate=len(won) / len(rows) if rows else None,
                profit=sum(row['net'] for row in won), loss=-sum(row['net'] for row in lost),
                closed_trade_net=sum(row['net'] for row in rows), win_qty=sum(row['qty'] for row in won),
                loss_qty=sum(row['qty'] for row in lost), gross=end['gross_realized'], fees=end['fees'],
                unrealized=end['unrealized'], net=end['net'], long_qty=end['long_qty'], short_qty=end['short_qty'],
                セッション期首=beginning, 既知境界=boundary, 現在末尾=end, 追加区間=added,
                未決済の扱い='原本末尾で仮想清算しない。未返済玉の全含みを返済可能側で評価。返済費用は未課金。')


def synthetic() -> dict:
    """機能: 未返済会計・末尾予約・次行約定・売り対称性を合成価格で検査する。

    引数: なし。返り値: 検査結果(dict)。現在APIにも旧現在原本にも接続しない。
    """
    checks = []
    config = prepare_live.candidates()[0]
    for direction in (1, -1):
        for name, gains in (('未返済利益', [0., 0., 50., 80.]),
                            ('未返済損切り予約', [0., 0., -101.]),
                            ('利益追跡の次行返済', [0., 0., 120., 500., 480., 475.])):
            price = 100000. + direction * np.asarray(gains)
            ready = dict(session='合成', symbol='NK225', seq=np.arange(len(price), dtype=np.int64),
                         time_s=np.arange(len(price), dtype=float), start=0., limit=999999., tick=10.)
            quote = dict(bid=price.copy(), ask=price.copy(), mid=price.copy(), seq=ready['seq'], time_s=ready['time_s'])
            signals = np.asarray([[0., direction, 0.]])
            result = simulate(ready, quote, signals, config, 2)
            end, boundary = result['現在末尾'], result['既知境界']
            assert boundary['fees'] == 220 and boundary['net'] == -220 and boundary['open_entry_fees'] == 220
            if name == '未返済利益':
                assert end['fees'] == 220 and end['unrealized'] == 16000 and end['net'] == 15780
                assert not result['rows'] and end['pending_exit'] is None
            elif name == '未返済損切り予約':
                assert end['fees'] == 220 and end['unrealized'] == -20200 and end['pending_exit']['i'] == 2
                assert not result['rows']
            else:
                assert end['fees'] == 440 and end['net'] == 94560 and end['unrealized'] == 0
                assert result['rows'][0]['exit_decision_i'] == 4 and result['rows'][0]['exit_i'] == 5
            checks.append(dict(名前=name, 方向=direction, 合格=True))
    # ----------------------------------------
    # 末尾の新規判断は次行がないため未約定のまま残す。
    empty_ready = dict(session='合成', symbol='TOPIX', seq=np.array([0], dtype=np.int64),
                       time_s=np.array([0.]), start=0., limit=999999., tick=.5)
    empty_quote = dict(bid=np.array([99999.]), ask=np.array([100001.]), mid=np.array([100000.]))
    result = simulate(empty_ready, empty_quote, np.asarray([[0., 1., 0.]]), config, 0)
    assert result['fees'] == 0 and result['net'] == 0 and result['現在末尾']['pending_entry']['i'] == 0
    checks.append(dict(名前='次行のない新規判断を未約定に保持', 合格=True))
    return dict(全合格=True, 件数=len(checks), 検査=checks, ネットワーク取得=0, 実注文=0)


def run() -> None:
    """機能: 取得前固定12候補を一回取得原本だけで再生し、部分損益を保存する。

    引数: なし。返り値: なし(None)。再取得・条件変更・原本末尾の強制清算はしない。
    """
    prepare_live.verify_seal()
    before = json.loads((HERE / '取得直前照合.json').read_text(encoding='utf-8'))
    assert before['候補SHA'] == prepare_live.digest(HERE / '候補固定.json')
    target = HERE / '現在急傾斜の途中損益.json'
    assert not target.exists(), '現在確認結果の再計算を拒否します'
    inputs = pickle.loads((HERE / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((HERE / 'quotes.pkl').read_bytes())
    bounds = json.loads((HERE / '既知前半と追加区間.json').read_text(encoding='utf-8'))
    counts = {(item['セッション'], item['銘柄']): item['既知有効行数'] for item in bounds['照合']}
    assert set(inputs) == set(quotes) == set(counts) and len(inputs) == 2
    modules = {'minute': prepare_live.load_module('封印済み分足', WORK / 'steep_signals.py'),
               'raw': prepare_live.load_module('封印済み短期', WORK / 'round2/raw_signals.py')}
    methods = []
    for config in prepare_live.candidates():
        module = modules[config['source']]
        definition = next(value for value in module.definitions() if value['id'] == config['entry'])
        accounts = []
        for key in sorted(inputs):
            ready, quote = inputs[key], quotes[key]
            signals = module.candidates(module.build(ready, quote), definition) if len(ready['seq']) else np.empty((0, 3))
            accounts.append(simulate(ready, quote, signals, config, counts[key]))
        methods.append(dict(config=config, accounts=accounts))
    prepare_live.save(target.name, dict(methods=methods, 条件数=len(methods), 境界=bounds,
        会計='現在純損益=実現粗利益−発生手数料＋全残玉含み。追加純損益=現在−既知境界。',
        未決済='未返済玉を勝敗に含めない。未執行返済の費用は課金しない。残玉と予約を表示する。',
        位置づけ='取得前固定主案の一回参考確認。現在結果で再調整せず、採用推奨を意味しない。',
        入力SHA={name: prepare_live.digest(HERE / name) for name in ('inputs.pkl', 'quotes.pkl')},
        候補SHA=prepare_live.digest(HERE / '候補固定.json'), ネットワーク追加取得=0, 実注文=0))
    print(json.dumps(dict(完了=True, 条件数=len(methods), 未返済玉を保持=True), ensure_ascii=False))


def main() -> None:
    """機能: ネット無しの合成検査と取得後の部分再生を明示的に選ぶ。

    引数: コマンド引数stage(str)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser(description='急傾斜手法の部分損益を原板順で会計する。')
    parser.add_argument('stage', choices=('synthetic', 'run'))
    args = parser.parse_args()
    if args.stage == 'synthetic':
        result = synthetic()
        prepare_live.save('途中会計の合成監査.json', result)
        print(json.dumps(result, ensure_ascii=False))
    else:
        run()


if __name__ == '__main__':
    main()
