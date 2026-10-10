"""保存済み週の固定格子を現在スナップショットまで接続し、残玉を清算せず記録する。"""

from datetime import datetime
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
GRID = HERE.parent / 'grid'
sys.path.insert(0, str(GRID))
import backtest
import engine
import features


def append_current(stream: dict, ready: dict, quote: dict) -> dict:
    """機能: 同週の直後一場だけを原本順に接続する。新しい空白価格は作らない。

    引数: stream/ready/quote(dict)。返り値: 現在場を追加した週の再生入力(dict)。
    """
    assert features.week_start(ready['session']) == stream['week']
    assert ready['session'] not in stream['sessions']
    np.testing.assert_array_equal(ready['seq'], quote['seq'])
    np.testing.assert_array_equal(ready['time_s'], quote['time_s'])
    if len(ready['time_s']):
        assert ready['time_s'][0] >= stream['time_s'][-1]
    offset, sid = len(stream['mid']), len(stream['sessions'])
    out = dict(stream)
    for key in ('time_s', 'seq'):
        out[key] = np.r_[stream[key], ready[key]]
    for key in ('mid', 'bid', 'ask'):
        out[key] = np.r_[stream[key], quote[key]]
    out['session_index'] = np.r_[stream['session_index'], np.full(len(ready['seq']), sid, np.int64)]
    events = features.direction_events(ready, quote) if len(ready['seq']) else np.empty((0, 4))
    events[:, 0] += offset
    out['events'] = np.concatenate([stream['events'], events])
    out['offsets'] = np.r_[stream['offsets'], offset]
    out['sessions'] = stream['sessions'] + [ready['session']]
    out['starts'] = np.r_[stream['starts'], ready['start']]
    out['limits'] = np.r_[stream['limits'], ready['limit']]
    day = datetime.strptime(ready['session'][:10], '%Y-%m-%d')
    out['final_reason'] = 1 if day.weekday() == 4 and ready['session'].endswith('_Night') else 0
    return out


def partial_account(stream: dict, config: dict) -> dict:
    """機能: 固定格子を週初から再生し、現在場と週累計の現金・費用・残玉を照合する。

    引数: stream/config(dict)。返り値: 未決済を含む途中会計(dict)。将来の返済費用は課さない。
    """
    symbol = stream['symbol']
    cap, value, fee_tenths = (10, 1000., 418) if symbol == 'TOPIX' else (20, 10., 110)
    arguments = {name: stream[name] for name in ('mid', 'bid', 'ask', 'limits', 'events', 'final_reason')}
    raw = engine.replay(times=stream['time_s'], seqs=stream['seq'], sessions=stream['session_index'],
        **arguments, **config['config'], cap=cap, value=value, tick=stream['tick'], fee_tenths=fee_tenths, finish=False)
    orders, trades, curve, mid_curve, risks, resets, pos, pending, book, cancelled = raw
    sid, first = len(stream['sessions']) - 1, int(stream['offsets'][-1])
    current_orders, current_trades = orders[orders[:, 6] == sid], trades[trades[:, 12] == sid]
    before_curve, before_mid = float(curve[first - 1]), float(mid_curve[first - 1])
    before_unrealized = float(risks[first - 1, 2:4].sum())
    unrealized = float(risks[-1, 2:4].sum())
    gross = float(current_trades[:, 15].sum())
    fee = float(current_orders[:, 13].sum())
    net = gross - fee + unrealized - before_unrealized
    np.testing.assert_allclose(net, curve[-1] - before_curve, atol=1e-5)
    np.testing.assert_allclose(book[2] - book[3] - book[1] + unrealized, curve[-1], atol=1e-5)
    open_positions = []
    for slot, p in enumerate(pos):
        if p[1] <= 0:
            continue
        liquidation = engine.liquidation_price(int(p[0]), len(curve) - 1, stream['mid'], stream['bid'], stream['ask'], config['config']['mode'])
        open_positions.append(dict(段番号=slot, 方向='買い' if p[0] > 0 else '売り', 枚数=int(p[1]),
            役割='カバー' if p[9] else '格子', 建値=float(p[2]), 建時発生費用=float(p[3]),
            新規セッション=stream['sessions'][int(p[6])], 新規原本行=int(stream['seq'][int(p[4])]),
            返済可能評価価格=float(liquidation), 含み粗損益=float(p[0] * p[1] * (liquidation - p[2]) * value),
            将来返済手数料未計上=True))
    np.testing.assert_allclose(sum(p['含み粗損益'] for p in open_positions), unrealized, atol=1e-5)
    local_curve = np.r_[before_curve, curve[first:]]
    week_curve = np.r_[0., curve]
    return dict(session=stream['sessions'][-1], symbol=symbol, week=stream['week'],
        id=config['id'], price_mode=config['price_mode'], config=config['config'],
        状態='現在場の観測末尾。未決済玉は清算しない' if first < len(curve) else '現在場の有効原本なし。前場末評価を保持',
        realized_gross_pnl=gross, fees_incurred=fee, realized_after_incurred_fees=gross-fee,
        unrealized_start=before_unrealized, unrealized_end=unrealized, mtm_change=unrealized-before_unrealized,
        economic_net=net, net=net, closed_trade_net=float(current_trades[:, 18].sum()),
        week_realized_gross_pnl=float(book[2]-book[3]), week_fees_incurred=float(book[1]),
        week_economic_net=float(curve[-1]), week_before_current_net=before_curve,
        drawdown=float(np.max(np.maximum.accumulate(local_curve)-local_curve)),
        week_drawdown=float(np.max(np.maximum.accumulate(week_curve)-week_curve)),
        current_mid_equity_change=float(mid_curve[-1]-before_mid),
        long_qty=int(risks[-1, 0]), short_qty=int(risks[-1, 1]), gross_qty=int(risks[-1, :2].sum()),
        open_positions=open_positions, pending=pending[pending[:, 0] != 0].tolist(),
        orders=current_orders.tolist(), trades=current_trades.tolist(),
        week_orders=orders.tolist(), week_trades=trades.tolist(), sessions=stream['sessions'],
        判断材料公開数=int((stream['events'][:, 0] >= first).sum()),
        有効方向材料公開数=int(((stream['events'][:, 0] >= first) & (stream['events'][:, 3] == 1)).sum()),
        最後の保存時計=float(stream['time_s'][-1]), 観測有効行数=len(curve)-first,
        調査端仮想清算=False, 最終行未約定予約数=int((pending[:, 0] != 0).sum()))


def main() -> None:
    """機能: 取得前の固定候補を確認し、接続可能な現在場だけを固定規則で再生する。

    引数: なし。返り値: なし(None)。ネットワーク・実注文・元の条件変更は行わない。
    """
    configs = backtest.methods()
    backtest.freeze(configs)
    selection = json.loads((HERE / '確認候補固定.json').read_text(encoding='utf8'))
    assert backtest.digest(GRID / '売買結果.json') == selection['source_sha256']['grid']
    selected = selection['selected']['grid']
    config = next(m for m in configs if m['id'] == selected['id'])
    assert config['price_mode'] == 'quote' and config['config']['carry'] == 1
    manifest = json.loads((HERE / '現在原本の照合.json').read_text(encoding='utf8'))
    output = dict(選定候補=selected, 取得前の選定不変=True, 現在原本=manifest,
        赤字参考候補=not selected['profitable_both'], accounts=[], 注文列=engine.ORDER_COLUMNS, 返済列=engine.TRADE_COLUMNS,
        途中会計='当場net=当場返済粗損益−当場発生手数料＋現在残玉含み−前場末含み。週累計は週初からの実現−全費用＋現在残玉含み。',
        実装='売買と特徴は保存検証前に凍結したコード。取得後に追加した接続・会計wrapperのSHAを現在損益計算前に固定。',
        限界='quote主評価とmid参考は独立再生。ラージ気配はmini/micro実気配を保証しない。単一の途中場で安定性を判定しない。')
    path = HERE / '現在グリッドの途中損益.json'
    if not manifest['週内継続の連結が可能']:
        output.update(状態='継続検証不成立', 理由=manifest['週内継続の注記'])
        backtest.save(path, output)
        print('週内継続は不成立のため、新しい空白経路を作らず停止しました')
        return
    inputs = pickle.loads((HERE / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((HERE / 'quotes.pkl').read_bytes())
    fixed = dict(wrapper_sha256=backtest.digest(Path(__file__)),
        inputs_sha256={n: backtest.digest(HERE / n) for n in ('inputs.pkl', 'quotes.pkl')},
        selection_sha256=backtest.digest(HERE / '確認候補固定.json'), 現在損益計算前=True, API再取得=0)
    fixed_path = HERE / '現在グリッド接続実装固定.json'
    assert not path.exists(), '現在グリッドを既に再生済みです。結果を見て再実行しません'
    if fixed_path.exists():
        assert json.loads(fixed_path.read_text(encoding='utf8')) == fixed
    else:
        backtest.save(fixed_path, fixed)
    streams = features.load_streams(flatten_study_end=False)
    for key in sorted(inputs):
        ready, quote = inputs[key], quotes[key]
        assert key[0] == manifest['セッション'] and key[0] == manifest['直後に必要なセッション']
        stream = streams[(ready['symbol'], features.week_start(ready['session']))]
        assert stream['sessions'][-1] == manifest['週内継続の直近保存場']
        appended = append_current(stream, ready, quote)
        for mode in ('quote', 'mid'):
            actual = next(m for m in configs if m['condition_id'] == config['condition_id'] and m['price_mode'] == mode)
            output['accounts'].append(partial_account(appended, actual))
    backtest.freeze(configs)
    output['接続実装固定'] = fixed
    backtest.save(path, output)
    print(json.dumps(dict(完了=True, 候補=selected['id'], 口座数=len(output['accounts']),
                         収支=[(a['symbol'], a['price_mode'], a['net']) for a in output['accounts']]), ensure_ascii=False))


if __name__ == '__main__':
    main()
