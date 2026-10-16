"""利益を小さく守っても赤字が増えた原因を、保存した実注文と支持判断から診断する。"""

from collections import Counter
import gzip
import json
from pathlib import Path
import pickle

import numpy as np

import base


HERE = Path(__file__).resolve().parent
IDS = ('C_OWN_B2', 'C_OWN_T2', 'C_N30_B4', 'C_N30_T2', 'R_OWN_T2', 'U_P10_T2')


def loaded(item: dict) -> dict:
    """
    機能: 正式金融で一度生成した台帳を診断だけのために読む。
    引数: item(dict)は新台帳の位置と指紋。
    返り値: dictは注文と支持判断。金融を再生せず、原本も読まない。
    """
    import hashlib
    saved = (base.ROOT/item['path']).read_bytes()
    assert hashlib.sha256(saved).hexdigest() == item['SHA256']
    return pickle.loads(gzip.decompress(saved))


def parent_rows(session: str, symbol: str, ledger: dict) -> list[dict]:
    """
    機能: 初期の実リスク、利益追尾の発動、損失内訳と返済の悪化を親ごとに整理する。
    引数: session/symbol(str)、ledger(dict)は場・商品と新B/T台帳。
    返り値: list[dict]は事後診断。未来の勝敗で入口を選ぶ条件には使わない。
    """
    tick, multiplier = (.5, 1000.) if symbol == 'TOPIX' else (10., 10.)
    orders, judgments = ledger['orders'], ledger['judgments']
    columns = {name: i for i, name in enumerate(ledger['judgment_columns'])}
    diagnostics = {row['parent_id']: row for row in ledger['raw_entry_diagnostics']}
    rows = []
    for trade in ledger['trades']:
        ident, side, quantity = int(trade[0]), int(trade[4]), int(trade[5])
        entry, exit_price, net = float(trade[6]), float(trade[7]), float(trade[11])
        group = orders[orders[:, 2] == ident]
        opening, closing = group[group[:, 7] == 1], group[group[:, 7] == 0]
        assert len(opening) == len(closing) == 1
        sampled = judgments[judgments[:, columns['parent_id']] == ident]
        assert len(sampled)
        first = sampled[0]
        assert int(first[columns['row']]) == int(trade[2])
        support, stop = float(first[columns['support_price']]), float(first[columns['stop_after']])
        known = diagnostics[ident]
        assert int(known['fill_row']) == int(trade[2])
        activated = sampled[:, columns['profit_active']] == 1
        peak = float(sampled[-1, columns['peak']])
        first_clearance = float(first[columns['liquidation_quote']])
        reason, decision = int(closing[0, 8]), int(closing[0, 1])
        decision_sample = sampled[sampled[:, columns['row']] == decision]
        decision_quote = float(decision_sample[-1, columns['liquidation_quote']]) if len(decision_sample) else None
        decision_net = side*(decision_quote-entry)*quantity*multiplier-float(trade[8]+trade[9]) if decision_quote is not None else None
        expected_risk = float(first[columns['initial_risk_yen']])
        rows.append(dict(session=session, symbol=symbol, parent=ident, side=side, quantity=quantity,
            entry_price=entry, support_price=support, initial_stop=stop,
            initial_risk_yen=expected_risk, actual_net=net, gross=float(trade[10]), fees=float(trade[8]+trade[9]),
            entry_support_distance_ticks=side*(entry-support)/tick,
            entry_stop_distance_ticks=side*(entry-stop)/tick,
            initial_clearance_to_stop_ticks=side*(first_clearance-stop)/tick,
            fill_already_broke_stop=side*(first_clearance-stop) <= 1e-8,
            entry_decision_time=float(opening[0, 10]), entry_fill_time=float(opening[0, 11]),
            exit_decision_time=float(closing[0, 10]), exit_fill_time=float(closing[0, 11]),
            proxy_hold_seconds=float(closing[0, 11]-opening[0, 11]),
            profit_trail_activated=bool(activated.any()), best_clearance_profit_ticks=side*(peak-entry)/tick,
            exit_reason=reason, exit_decision_quote=decision_quote, exit_decision_net=decision_net,
            exit_fill_change_ticks=side*(exit_price-decision_quote)/tick if decision_quote is not None else None,
            fees_only_loss=(net < 0 and float(trade[10]) >= 0),
            net_loss_before_activation=bool(net < 0 and not activated.any()),
            net_loss_after_activation=bool(net < 0 and activated.any()),
            decision_profitable_but_fill_negative=(net < 0 and decision_net is not None and decision_net >= 0)))
    return rows


def summary(rows: list[dict]) -> dict:
    """
    機能: 診断の件数・金額・実リスク幅を勝敗別にまとめる。
    引数: rows(list[dict])は一条件一商品の親診断。
    返り値: dictは実親に基づく内訳。不取引の空集団は勝ちに数えない。
    """
    result = {}
    for label, selected in (('全取引', rows), ('利益取引', [row for row in rows if row['actual_net'] > 0]),
                            ('損失取引', [row for row in rows if row['actual_net'] < 0])):
        result[label] = dict(count=len(selected), net=sum(row['actual_net'] for row in selected),
            gross=sum(row['gross'] for row in selected), fees=sum(row['fees'] for row in selected),
            **{field: sum(row[field] for row in selected) for field in ('fill_already_broke_stop',
                'profit_trail_activated', 'fees_only_loss', 'net_loss_before_activation',
                'net_loss_after_activation', 'decision_profitable_but_fill_negative')},
            exit_reasons=dict(Counter(str(row['exit_reason']) for row in selected)),
            quantiles={field: list(map(float, np.quantile([row[field] for row in selected], (0., .5, .9, 1.)))) if selected else []
                for field in ('entry_stop_distance_ticks', 'entry_support_distance_ticks', 'proxy_hold_seconds')})
    return result


def main() -> None:
    """
    機能: 固定した6代表条件の全親を診断し、次の仮説と区別する証跡を保存する。
    引数: なし。
    返り値: None。新しい条件の金融再生、原本、API、未知Dayの読取は0。
    """
    result = base.read(HERE/'金融全32の結果.json')
    assert result['全合格'] and result['条件数'] == 121
    target = HERE/'支持幅と再参加及び利益保険の損失診断.json'
    assert not target.exists()
    outcomes, parents = {}, {}
    for ident in IDS:
        item = result['results'][ident]
        assert base.digest(base.ROOT/item['path']) == item['SHA256']
        case = base.read(base.ROOT/item['path'])
        selected = {symbol: [] for symbol in ('TOPIX', 'NK225')}
        for key, saved in case['ledgers'].items():
            session, symbol = key.split('|')
            selected[symbol].extend(parent_rows(session, symbol, loaded(saved)))
        outcomes[ident], parents[ident] = {}, selected
        for symbol, rows in selected.items():
            total = case['periods']['全32'][symbol]
            assert len(rows) == total['campaigns']
            assert abs(sum(row['actual_net'] for row in rows)-total['net']) < 1e-5
            outcomes[ident][symbol] = summary(rows)
        print(ident+' 全親診断を保存準備', flush=True)
    saved = dict(全合格=True, conditions=list(IDS), summary=outcomes, parents=parents,
        formal_result_SHA256=base.digest(HERE/'金融全32の結果.json'), source_SHA256=base.digest(Path(__file__)),
        新金融再生=0, 原本読取=0, 現在API=0, 追加Day読取=0,
        定義='実supportから実fillまでの距離と停止幅を区別する。分位点は最小・中央値・90%点・最大。保有秒数は価格代理時計。',
        限界='事後の原因内訳であり、このラベルを当時の入口判断へ渡さない。出口時点より後の価格を最良値へ足さない。')
    target.write_text(json.dumps(saved, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
