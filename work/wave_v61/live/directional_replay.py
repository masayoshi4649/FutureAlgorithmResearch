"""取得済み原本だけで固定方向性手法を再生し、既知境界を同時刻内の原本順で分ける。"""

import argparse
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
BRANCH = HERE.parent / 'directional'
sys.path.insert(0, str(BRANCH))
import engine
import features
import fees
import run as frozen_run
import signals


def state_at(ready: dict, quotes: dict, orders: np.ndarray, count: int, quote_mode: bool) -> dict:
    """機能: 指定した有効行数までの注文から、現金・実現・費用・全残玉評価を再構成する。

    引数: ready/quotes(dict)、orders(ndarray)、count(int)、quote_mode(bool)。
    返り値: 途中状態(dict)。同一約定時計でもseqの境界を守り、未来返済の利益を混ぜない。
    """
    assert 0 <= count <= len(ready['seq'])
    if count == 0:
        return dict(valid_rows=0, seq=None, time_s=None, gross_realized=0., fees=0., cash=0.,
                    realized_after_incurred_fees=0., unrealized=0., net=0., long_qty=0, short_qty=0,
                    open_entry_fees=0., open_positions=[])
    last = count - 1
    value = fees.instrument(ready['symbol'])['value']
    selected = orders[orders[:, 3] <= ready['seq'][last]]
    gross = float(selected[:, 8].sum())
    incurred = float(selected[:, 9].sum())
    cash = float((-selected[:, 5] * selected[:, 6] * selected[:, 7] * value - selected[:, 9]).sum())
    opened = []
    for order in selected:
        if int(order[4]) == 2:
            opened.clear()
        else:
            opened.append(order)
    total_unrealized, long_qty, short_qty, open_fee, lots = 0., 0, 0, 0., []
    for order in opened:
        side, qty = int(order[5]), int(order[6])
        liquidation = float(quotes['bid'][last] if side > 0 else quotes['ask'][last]) if quote_mode else float(quotes['mid'][last])
        pnl = side * qty * (liquidation - order[7]) * value
        total_unrealized += pnl
        long_qty += qty if side > 0 else 0
        short_qty += qty if side < 0 else 0
        open_fee += order[9]
        lots.append(dict(group_id=int(order[12]), lot_id=int(order[15]), side=side, quantity=qty,
                         entry_price=float(order[7]), entry_fee=float(order[9]), liquidation_price=liquidation,
                         unrealized=pnl, future_exit_fee_incurred=False))
    position = long_qty - short_qty
    liquidation = float(quotes['bid'][last] if position >= 0 else quotes['ask'][last]) if quote_mode else float(quotes['mid'][last])
    net = gross - incurred + total_unrealized
    np.testing.assert_allclose(cash + position * liquidation * value, net, atol=1e-5)
    return dict(valid_rows=count, seq=int(ready['seq'][last]), time_s=float(ready['time_s'][last]),
                gross_realized=gross, fees=incurred, cash=cash, realized_after_incurred_fees=gross - incurred,
                unrealized=total_unrealized, net=net, long_qty=long_qty, short_qty=short_qty,
                open_entry_fees=open_fee, open_positions=lots)


def partial_account(ready: dict, quotes: dict, config: dict, quote_mode: bool, known_count: int) -> dict:
    """機能: 一場を未終了のまま再生し、既知前半と今回追加区間の資産変化を分ける。

    引数: ready/quotes/config(dict)、quote_mode(bool)、known_count(int)は既知有効原本行数。
    返り値: 現在全体と追加区間の部分会計(dict)。ネット取得・場末の架空清算をしない。
    """
    assert 0 <= known_count <= len(ready['seq'])
    if len(ready['seq']):
        frame = features.build(ready, quotes, features.SETTINGS[0])
        candidates = signals.candidates(frame, float(quotes['mid'][0]), ready['tick'], config['fraction'])[config['family']]
        result = engine.execute(ready, quotes, candidates, config, quote_mode, finish=False)
        orders = result['orders']
        curve, _ = engine.equity_curve(ready, quotes, orders, fees.instrument(ready['symbol'])['value'], quote_mode)
        boundary = state_at(ready, quotes, orders, known_count, quote_mode)
        end = state_at(ready, quotes, orders, len(ready['seq']), quote_mode)
        if known_count:
            np.testing.assert_allclose(boundary['net'], curve[known_count - 1], atol=1e-5)
        np.testing.assert_allclose(end['net'], curve[-1], atol=1e-5)
        result['準備可能足数'], result['候補数'] = int(frame['can_trade'].sum()), len(candidates)
    else:
        orders = np.empty((0, len(engine.ORDER_COLUMNS)))
        result = dict(session=ready['session'], symbol=ready['symbol'], price_mode='quote' if quote_mode else 'mid',
                      orders=orders, trades=np.empty((0, len(engine.TRADE_COLUMNS))), net=0., cycles=0,
                      準備可能足数=0, 候補数=0, 状態='有効原本行がなく準備待ち')
        boundary = end = state_at(ready, quotes, orders, 0, quote_mode)
    beginning = state_at(ready, quotes, orders, 0, quote_mode)
    added = {name: end[name] - boundary[name]
             for name in ('gross_realized', 'fees', 'cash', 'realized_after_incurred_fees', 'unrealized', 'net')}
    added.update(valid_rows=len(ready['seq']) - known_count,
                 long_qty_start=boundary['long_qty'], long_qty_end=end['long_qty'],
                 short_qty_start=boundary['short_qty'], short_qty_end=end['short_qty'])
    np.testing.assert_allclose(added['net'], added['gross_realized'] - added['fees'] + added['unrealized'], atol=1e-5)
    result.update(closed_trade_net=result['net'], net=end['net'], economic_net=end['net'],
                  realized_gross_pnl=end['gross_realized'], fees_incurred=end['fees'], unrealized_end=end['unrealized'],
                  long_qty=end['long_qty'], short_qty=end['short_qty'],
                  セッション期首=beginning, 既知境界=boundary, 現在末尾=end, 追加区間=added,
                  既知有効行数=known_count, 追加区間純変化=added['net'],
                  未決済の扱い='実清算しない。返済可能側の含みを全て評価。未執行の返済費用はまだ課さない。')
    return result


def prepare() -> None:
    """機能: 取得前に接続コードと固定売買器のSHAを保存する。

    引数: なし。
    返り値: なし(None)。外部アクセス・実データ売買を行わない。
    """
    frozen_run.verify_freeze()
    assert json.loads((HERE / '方向性途中会計の合成監査.json').read_text(encoding='utf-8'))['合格']
    record = {'コードSHA256': frozen_run.digest(Path(__file__)),
              '売買器固定SHA256': frozen_run.digest(BRANCH / '実行前固定.json'),
              '合成監査SHA256': frozen_run.digest(HERE / '方向性途中会計の合成監査.json'),
              '取得前固定': True, 'ネットワーク取得': False}
    target = HERE / '方向性接続実装固定.json'
    if target.exists():
        assert record == json.loads(target.read_text(encoding='utf-8'))
    else:
        frozen_run.save(target, record)
    print('方向性接続コードを取得前に固定しました。取得と親GOを待ちます。')


def main() -> None:
    """機能: 取得済み入力と取得前選定を照合し、固定候補の途中会計だけを保存する。

    引数: なし。
    返り値: なし(None)。選定・売買器・費用を変更せず、追加API取得もしない。
    """
    frozen_run.verify_freeze()
    frozen = json.loads((HERE / '方向性接続実装固定.json').read_text(encoding='utf-8'))
    assert frozen_run.digest(Path(__file__)) == frozen['コードSHA256']
    assert frozen_run.digest(BRANCH / '実行前固定.json') == frozen['売買器固定SHA256']
    selection = json.loads((HERE / '候補固定.json').read_text(encoding='utf-8'))
    before_fetch = json.loads((HERE / '取得直前照合.json').read_text(encoding='utf-8'))
    assert frozen_run.digest(HERE / '候補固定.json') == before_fetch['候補SHA']
    assert frozen_run.digest(BRANCH / '集計結果.json') == selection['sources']['directional']
    selected = selection['selected']['directional']
    target = HERE / '現在方向性の途中損益.json'
    if target.exists():
        raise RuntimeError('現在確認結果は既に存在します。再計算しません')
    config = next(value for value in signals.methods() if value['id'] == selected['id'])
    inputs = pickle.loads((HERE / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((HERE / 'quotes.pkl').read_bytes())
    boundary = json.loads((HERE / '既知前半と追加区間.json').read_text(encoding='utf-8'))
    counts = {(item['セッション'], item['銘柄']): int(item['既知有効行数']) for item in boundary['照合']}
    assert set(inputs) == set(quotes) == set(counts) and len(inputs) == 2
    records = [partial_account(inputs[key], quotes[key], config, mode, counts[key])
               for key in sorted(inputs) for mode in (True, False)]
    frozen_run.save(target, {'選定候補': selected, 'config': config, 'accounts': records,
                            '注文列': engine.ORDER_COLUMNS, '返済列': engine.TRADE_COLUMNS,
                            '位置づけ': '取得前固定の仮想手法の一回参考確認。採用推奨ではない。既知前半は未知の成績に含めない。',
                            '境界': boundary, '会計': '現在net=実現粗利益−全発生費用＋全残玉含み。追加net=現在net−既知境界net。',
                            '時計': '原本に受信時計はなく約定時計と原本順を使用。同時計の境界も有効行数n−1で分割。',
                            '候補SHA256': frozen_run.digest(HERE / '候補固定.json'),
                            '入力SHA256': {name: frozen_run.digest(HERE / name) for name in ('inputs.pkl', 'quotes.pkl')},
                            '売買コード不変': True, 'API取得': False})
    print(json.dumps({'完了': True, '候補': selected['id'], '口座数': len(records)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.prepare == args.run:
        raise SystemExit('--prepare 又は --run の一方を指定してください')
    prepare() if args.prepare else main()
