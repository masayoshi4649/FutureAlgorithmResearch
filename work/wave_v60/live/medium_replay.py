"""凍結した中期候補を現在の保存スナップショットへ適用し、未決済を清算せず会計する。"""

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
MEDIUM = HERE.parent / 'medium'
sys.path.insert(0, str(MEDIUM))
import engine
import features
import fees
import run as frozen_run
import signals


def partial_account(ready: dict, quotes: dict, config: dict, quote_mode: bool) -> dict:
    """機能: 未完了の一場を同じ固定コードで再生し、実現と全残玉の含みを分ける。

    引数: ready/quotes/config(dict)、quote_mode(bool) は気配主評価か中値参考か。
    返り値: 未清算の価格評価を含む口座辞書(dict)。場末と仮定した決済は追加しない。
    """
    if len(ready['seq']) == 0:
        return {'session': ready['session'], 'symbol': ready['symbol'], 'price_mode': 'quote' if quote_mode else 'mid',
                '状態': '場内の有効観測がなく準備待ち', 'cycles': 0, 'position': 0,
                'realized_gross_pnl': 0., 'fees_incurred': 0., 'unrealized_end': 0., 'economic_net': 0.,
                'net': 0., 'orders': [], 'trades': [], '準備可能足数': 0, '候補数': 0}
    setting = next(value for value in features.SETTINGS if value['id'] == config['setting_id'])
    frame = features.build(ready, quotes, setting)
    candidate = signals.candidates(frame, float(quotes['mid'][0]), ready['tick'], config['fraction'])[config['family']]
    result = engine.execute(ready, quotes, candidate, int(config['exit_id'][1]), config['minutes'], quote_mode, finish=False)
    orders, trades = result['orders'], result['trades']
    contract = fees.instrument(ready['symbol'])
    curve, positions = engine.equity_curve(ready, quotes, orders, contract['value'], quote_mode)
    position = int(positions[-1])
    realized_gross = float(trades[:, 6].sum())
    fees_incurred = float(orders[:, 9].sum())
    realized_after_fees = realized_gross - fees_incurred
    completed_net = float(trades[:, 8].sum())
    completed_fees = float(trades[:, 7].sum())
    open_entry_fees = fees_incurred - completed_fees
    open_positions = []
    if position:
        open_order = orders[orders[:, 4] == 1][-1]
        liquidation = float(quotes['bid'][-1] if position > 0 else quotes['ask'][-1]) if quote_mode else float(quotes['mid'][-1])
        unrealized = position * (liquidation - open_order[7]) * contract['value']
        open_positions.append({'方向': '買い' if position > 0 else '売り', '枚数': abs(position),
                               '建値': float(open_order[7]), '返済可能評価価格': liquidation,
                               '含み粗損益': unrealized, '建時発生手数料': open_entry_fees,
                               '将来返済手数料未計上': True})
    else:
        unrealized = 0.
    economic_net = realized_after_fees + unrealized
    np.testing.assert_allclose(economic_net, curve[-1], atol=1e-5)
    np.testing.assert_allclose(completed_net - open_entry_fees + unrealized, economic_net, atol=1e-5)
    result.update(closed_trade_net=completed_net, realized_gross_pnl=realized_gross,
                  fees_incurred=fees_incurred, completed_trade_fees=completed_fees, open_entry_fees=open_entry_fees,
                  realized_after_incurred_fees=realized_after_fees, unrealized_end=unrealized,
                  economic_net=economic_net, net=economic_net, position=position, open_positions=open_positions,
                  判定='稼働途中の原本末尾で停止。未決済を仮想清算しない。',
                  準備可能足数=int(frame['can_trade'].sum()), 候補数=len(candidate),
                  最後の保存時計=float(ready['time_s'][-1]),
                  未実行の新規判断数=int(result['candidate_audit']['scheduled'] - result['candidate_audit']['cancelled_at_fill'] - (orders[:, 4] == 1).sum()))
    return result


def main() -> None:
    """機能: 取得前固定の一候補を二銘柄へ適用し、全残玉を含む途中会計を保存する。

    引数: なし。
    返り値: なし(None)。元の売買コードと選定は変更しない。ネットワークは使用しない。
    """
    frozen_run.verify_freeze()
    selection = json.loads((HERE / '確認候補固定.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((MEDIUM / '売買結果.json').read_bytes()).hexdigest() == selection['source_sha256']['medium']
    selected = selection['selected']['medium']
    config = next(value for value in signals.methods() if value['id'] == selected['id'])
    inputs = pickle.loads((HERE / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((HERE / 'quotes.pkl').read_bytes())
    manifest = json.loads((HERE / '現在原本の照合.json').read_text(encoding='utf-8'))
    accounts = [partial_account(inputs[key], quotes[key], config, quote_mode)
                for key in sorted(inputs) for quote_mode in (True, False)]
    result = {'選定候補': selected, 'config': config, '取得前の選定不変': True,
              '現在原本': manifest, 'accounts': accounts, '注文列': engine.ORDER_COLUMNS, '返済列': engine.TRADE_COLUMNS,
              '途中会計': 'economic_net=実現粗損益−発生済手数料＋残玉の返済可能価格含み。未執行の返済手数料はまだ課さない。',
              '赤字参考候補': not selected['profitable_both'],
              '限界': 'ラージ気配はmini/micro実気配の代理。単一の途中場だけで安定性を判定しない。'}
    frozen_run.save(HERE / '現在中期の途中損益.json', result)
    print(json.dumps({'完了': True, '候補': config['id'], '口座数': len(accounts)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
