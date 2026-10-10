"""E01の発注判断を固定し、直後15秒の最悪観測価格で約定金額を再計算する。"""

from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPORT = ROOT / 'アルゴリズム調査/00046_E01の15秒最悪約定比較'
JST = timezone(timedelta(hours=9))
INPUTS = ['work/wave_v47/inputs.pkl', 'work/wave_v48/update_20260930/new_inputs.pkl',
          'work/wave_v48/update_20261001/new_inputs.pkl']
LEDGERS = ['work/wave_v49/early/ledgers/E01.json.gz']
UPDATES = json.loads((ROOT / 'work/wave_v50/追加結果一覧.json').read_text(encoding='utf-8'))
INPUTS += ['work/wave_v50/' + name + '/new_inputs.pkl' for name in UPDATES]
LEDGERS += ['work/wave_v50/' + name + '/ledgers/E01.json.gz' for name in UPDATES]


def read(path: Path) -> object:
    """機能: JSONまたは圧縮JSONを読み込む。

    引数: path(Path)。返り値: 保存値(object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def iso(value: float) -> str:
    """機能: 市場時計を日本時間表示へ変換する。

    引数: value(float、UNIX秒)。返り値: 日時(str)。
    """
    return datetime.fromtimestamp(value, JST).isoformat()


def account(ledger: dict, ready: dict) -> dict:
    """機能: 一口座の買いを15秒窓の最高値、売りを最安値へ置換する。

    引数: ledger/ready(dict)。返り値: 約定比較・決済損益・監査情報(dict)。
    発注判断・方向・枚数を固定し、将来価格を戦略入力へ戻さない。
    """
    times = ready['time_s']
    prices = ready['last']
    close = ready.get('session_close', ready['limit'] + 600)
    factor = ledger['config']['point_value']
    assert np.all(np.diff(times) >= 0) and np.all(np.isfinite(prices))
    orders, mapping = [], {}
    for number, row in enumerate(ledger['orders']):
        fill, source, campaign, side, qty, ideal, reason, opening = row
        fill, source, side, qty, opening = int(fill), int(source), int(side), int(qty), bool(opening)
        assert source < fill and side in (-1, 1)
        decision = source if int(reason) in (8, 9, 30, 32) else fill
        at = float(times[decision])
        right = min(int(np.searchsorted(times, at + 15, side='right')),
                    int(np.searchsorted(times, close, side='left')))
        assert right > decision
        window = prices[decision:right]
        relative = int(np.argmax(window) if side > 0 else np.argmin(window))
        selected = decision + relative
        worst = float(prices[selected])
        assert at <= times[selected] <= at + 15 and times[selected] < close
        key = (fill, side, opening)
        assert key not in mapping
        loss = side * (worst - ideal) * qty * factor
        # ----------------------------------------
        # 取引時刻が秒単位でも、判断より前の同秒行は最悪値の候補に含めない。
        item = dict(order=number, fill_row=fill, source_row=source, decision_row=decision, campaign=int(campaign),
                    decision_time=at, decision_jst=iso(at), side=side, quantity=qty,
                    is_entry=opening, reason=int(reason), ideal_price=ideal, worst_price=worst,
                    adverse_yen=loss, worst_row=selected, worst_time=float(times[selected]),
                    worst_jst=iso(float(times[selected])), window_rows=right-decision,
                    requested_end=at+15, observed_end=float(times[right-1]),
                    dataset_covers_15s=bool(times[-1] >= at+15),
                    session_covers_15s=bool(close > at+15),
                    last_observation_gap=float(at+15-times[right-1]))
        orders.append(item)
        mapping[key] = item
    # ----------------------------------------
    # 注文の現金収支と、入口・出口を対応させた決済利益を独立に一致させる。
    trades = []
    for row in ledger['trades']:
        campaign, leg, direction, quantity, entry, exit_price, entry_row, exit_row, _, reason, points = row
        entry_order = mapping[int(entry_row), int(direction), True]
        exit_order = mapping[int(exit_row), -int(direction), False]
        assert entry == entry_order['ideal_price'] and exit_price == exit_order['ideal_price']
        ideal_pnl = direction * quantity * (exit_price-entry) * factor
        worst_pnl = direction * quantity * (exit_order['worst_price']-entry_order['worst_price']) * factor
        assert abs(points * factor-ideal_pnl) < 1e-7
        trades.append(dict(campaign=int(campaign), direction=int(direction), quantity=int(quantity),
                           entry_order=entry_order['order'], exit_order=exit_order['order'],
                           ideal_pnl=ideal_pnl, worst_pnl=worst_pnl,
                           worst_entry_after_exit_decision=entry_order['worst_row'] > exit_order['decision_row'],
                           worst_entry_after_exit_fill=entry_order['worst_row'] > exit_order['worst_row']))
    aggregates = {}
    for mode in ('ideal', 'worst'):
        pnl = [t[mode+'_pnl'] for t in trades]
        profits, losses = sum(max(0, p) for p in pnl), sum(max(0, -p) for p in pnl)
        net = profits-losses
        cash = sum(-o['side']*o['quantity']*o[mode+'_price']*factor for o in orders)
        assert abs(net-cash) < 1e-6
        aggregates[mode] = dict(profit=profits, loss=losses, net=net,
                               win_units=sum(t['quantity'] for t in trades if t[mode+'_pnl'] > 0),
                               loss_units=sum(t['quantity'] for t in trades if t[mode+'_pnl'] < 0),
                               flat_units=sum(t['quantity'] for t in trades if t[mode+'_pnl'] == 0))
    assert sum(o['side']*o['quantity'] for o in orders) == 0
    entry_loss = sum(o['adverse_yen'] for o in orders if o['is_entry'])
    exit_loss = sum(o['adverse_yen'] for o in orders if not o['is_entry'])
    assert abs(aggregates['ideal']['net']-aggregates['worst']['net']-entry_loss-exit_loss) < 1e-6
    audit = dict(order_count=len(orders), entry_count=sum(o['is_entry'] for o in orders),
                 improved_orders=sum(o['adverse_yen'] < 0 for o in orders),
                 dataset_short_windows=sum(not o['dataset_covers_15s'] for o in orders),
                 session_short_windows=sum(not o['session_covers_15s'] for o in orders),
                 windows_overlapping_next_order=sum(b['decision_time'] <= a['requested_end'] for a,b in zip(orders,orders[1:])),
                 reversed_worst_fill_order=sum(b['worst_row'] < a['worst_row'] for a,b in zip(orders,orders[1:])),
                 entry_after_exit_decision=sum(t['worst_entry_after_exit_decision'] for t in trades),
                 entry_after_exit_fill=sum(t['worst_entry_after_exit_fill'] for t in trades),
                 max_final_observation_gap=max((o['last_observation_gap'] for o in orders), default=0))
    return dict(session=ledger['session'], symbol=ledger['symbol'], **aggregates,
                adverse_yen=entry_loss+exit_loss, entry_adverse_yen=entry_loss,
                exit_adverse_yen=exit_loss, orders=orders, trades=trades, audit=audit)


def total(rows: list[dict]) -> dict:
    """機能: セッション損益と枚数を合算する。

    引数: rows(list[dict])。返り値: 合計と黒字場数(dict)。
    """
    result = {}
    for mode in ('ideal', 'worst'):
        values = {k:sum(r[mode][k] for r in rows) for k in ('profit','loss','net','win_units','loss_units','flat_units')}
        values['win_sessions'] = sum(r[mode]['net'] > 0 for r in rows)
        values['profit_factor'] = values['profit']/values['loss'] if values['loss'] else None
        values['unit_payoff'] = ((values['profit']/values['win_units'])/(values['loss']/values['loss_units'])
                                 if values['win_units'] and values['loss_units'] else None)
        result[mode] = values
    result.update({k:sum(r[k] for r in rows) for k in ('adverse_yen','entry_adverse_yen','exit_adverse_yen')})
    result['net_retained_percent'] = 100*result['worst']['net']/result['ideal']['net'] if result['ideal']['net'] else None
    result['order_count'] = sum(r['audit']['order_count'] for r in rows)
    return result


def main() -> None:
    """機能: 全19セッションを固定条件で計算し、00046へ結果を保存する。

    引数: なし。返り値: なし(None)。通信・過去結果の上書きは行わない。
    """
    REPORT.mkdir(parents=True, exist_ok=True)
    fingerprints = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in INPUTS+LEDGERS}
    inputs = {}
    for name in INPUTS:
        with (ROOT/name).open('rb') as handle:
            values = pickle.load(handle)
        assert not set(values).intersection(inputs)
        inputs.update(values)
    ledgers = [row for name in LEDGERS for row in read(ROOT/name)]
    assert len(ledgers) == len(inputs) == 38
    reference = read(ROOT/'アルゴリズム調査/00044_新候補2手法と基準の説明と損益/報告データ.json')
    old = next(m for m in reference['候補'] if m['spec']['id'] == 'E01')
    rows = [account(ledger, inputs[ledger['session'],ledger['symbol']]) for ledger in ledgers]
    rows.sort(key=lambda r:(r['session'],r['symbol']))
    for row in rows:
        previous = next(r for r in old['sessions'] if (r['session'],r['symbol']) == (row['session'],row['symbol']))
        for new, original in [('profit','gross_profit_yen'),('loss','gross_loss_yen'),('net','net_yen')]:
            assert abs(row['ideal'][new]-previous[original]) < 1e-6
    totals = {symbol:total([r for r in rows if r['symbol']==symbol]) for symbol in ('TOPIX','NK225')}
    result = dict(method='E01', window_seconds=15, session_count=19,
                  scope='00044の全19セッション。TOPIXミニ初回5枚・上限10枚、NK225マイクロ初回10枚・上限20枚。',
                  decision='条件付き新規・返済は条件成立の観測行。半減・時間終了・損失予算による成行返済は決定を記録したsource行。待機注文の作成時刻ではない。',
                  price_model='判断行から15秒後までの保存板CurrentPrice。買いは最大、売りは最小。右端を含み判断前の同秒行は除く。',
                  limitation='売買判断と枚数を固定した約定価格の感度検証。悪化した建値から出口条件を再計算する再運転ではない。市場時計による窓で実受信遅延そのものは未測定。',
                  live_api_calls=0, sources=fingerprints, totals=totals, sessions=rows,
                  audit={key:sum(row['audit'][key] for row in rows) for key in rows[0]['audit'] if key!='max_final_observation_gap'})
    result['audit']['max_final_observation_gap']=max(row['audit']['max_final_observation_gap'] for row in rows)
    result['audit']['ideal_equals_00044']=True
    (REPORT/'計算結果.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'totals':totals,'audit':result['audit']},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
