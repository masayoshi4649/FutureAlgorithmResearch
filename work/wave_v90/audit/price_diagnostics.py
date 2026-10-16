"""凍結後に限り、指値の価格悪化代理とERの実尺度を損失原因として分解する。"""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import pickle

import numpy as np

import common


def load(path):
    """
    機能: 凍結後の台帳又は価格入力を読み取る。
    引数: path(Path)。
    返り値: object。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def clock(value):
    """
    機能: 原本最終約定時計代理を日本時間の読める文字列へ変換する。
    引数: value(float)。
    返り値: str。
    """
    return datetime.fromtimestamp(float(value), timezone(timedelta(hours=9))).isoformat()


def sample(key, record, ledger, entry, trade):
    """
    機能: 一親の基準古さ・予約・指値と当時気配差・実損益を具体的に示す。
    引数: key(tuple)、record/ledger(dict)、entry/trade(ndarray)。
    返り値: dict。固定済み出口を保つ価格差診断であり新手法のバックテストではない。
    """
    row, decision, side, quantity, limit_price = int(entry[0]), int(entry[1]), int(entry[4]), int(entry[5]), entry[6]
    executable = record['ask'][row] if side == 1 else record['bid'][row]
    gap = side * (limit_price - executable)
    anchors = ledger['events'][(ledger['events'][:, 3] == 10) & (ledger['events'][:, 10] == entry[13])]
    assert len(anchors) == 1
    anchor_row = int(anchors[0, 0])
    unit = 1000. if key[1] == 'TOPIX' else 10.
    return dict(session=key[0], symbol=key[1], parent=int(entry[2]), side='買い' if side == 1 else '売り', quantity=quantity,
                anchor_time=clock(record['time_s'][anchor_row]), anchor_price=float(anchors[0, 7]),
                decision_time=clock(record['time_s'][decision]), fill_time=clock(record['time_s'][row]),
                decision_CurrentPrice=float(record['price'][decision]), fill_CurrentPrice=float(record['price'][row]),
                original_limit_price=float(limit_price), then_bid=float(record['bid'][row]), then_ask=float(record['ask'][row]),
                executable_quote=float(executable), adverse_gap_points=float(gap), adverse_gap_ticks=float(gap / record['tick']),
                adverse_gap_money=float(gap * quantity * unit),
                anchor_age_at_decision=float(record['time_s'][decision] - record['time_s'][anchor_row]),
                pending_seconds=float(record['time_s'][row] - record['time_s'][decision]),
                exit_time=clock(record['time_s'][int(trade[3])]), exit_reason=int(trade[13]),
                held_seconds=float(record['time_s'][int(trade[3])] - record['time_s'][row]),
                gross=float(trade[10]), fees=float(trade[8] + trade[9]), net=float(trade[11]),
                same_path_entry_quote_only_net=float(trade[11] + gap * quantity * unit))


def main():
    """
    機能: 全27条件の指値価格差を集計し、二市場ERの観測分布と主案の具体親を診断する。
    引数: なし。
    返り値: None。固定先行コードと原本は変更しない。
    """
    fixed = load(common.WORK / '事前固定.json')
    prices = load(common.ROOT / 'work/wave_v83/prepared/inputs.pkl')
    grids = load(common.ROOT / 'work/wave_v77/inputs/grids_delay1.pkl')
    results, examples = {}, []
    paths = [Path(__file__), common.WORK / '事前固定.json', common.ROOT / 'work/wave_v83/prepared/inputs.pkl',
             common.ROOT / 'work/wave_v77/inputs/grids_delay1.pkl']
    for config in fixed['条件']:
        ledger_path = common.WORK / 'ledgers' / (config['id'] + '.pkl')
        ledgers = load(ledger_path)
        records = {symbol: [] for symbol in common.SYMBOLS}
        for key, ledger in ledgers.items():
            trades = {int(value[0]): value for value in ledger['trades'] if value[1] == 1}
            for entry in ledger['orders'][(ledger['orders'][:, 3] == 1) & (ledger['orders'][:, 7] == 1)]:
                detail = sample(key, prices[key], ledger, entry, trades[int(entry[2])])
                records[key[1]].append(detail)
                if config['id'] == fixed['主']:
                    examples.append(detail)
        results[config['id']] = {}
        for symbol, entries in records.items():
            gaps = np.array([entry['adverse_gap_ticks'] for entry in entries])
            losses = [entry for entry in entries if entry['net'] < 0]
            results[config['id']][symbol] = dict(
                parents=len(entries), net=sum(entry['net'] for entry in entries),
                positive_entry_gap_parents=int((gaps > 1e-8).sum()), gap_over_stop_width_parents=int((gaps > config['stop_widths'] * config['width_ticks']).sum()),
                gap_quantiles_ticks={str(q): float(np.quantile(gaps, q)) if len(gaps) else None for q in (0, .5, .9, .95, 1)},
                gap_money_total=sum(entry['adverse_gap_money'] for entry in entries),
                gap_money_losing_parents=sum(entry['adverse_gap_money'] for entry in losses),
                original_loss=sum(-entry['net'] for entry in losses),
                same_path_entry_quote_only_net=sum(entry['same_path_entry_quote_only_net'] for entry in entries),
                stop_reason6_parents=sum(entry['exit_reason'] == 6 for entry in entries),
                held_at_most_5seconds=sum(entry['held_seconds'] <= 5 for entry in entries),
                anchor_age_median=float(np.median([entry['anchor_age_at_decision'] for entry in entries])) if entries else None,
                anchor_age_max=max((entry['anchor_age_at_decision'] for entry in entries), default=None))
        paths.append(ledger_path)
    distributions = {}
    for symbol in common.SYMBOLS:
        values = np.concatenate([grid['markets'][symbol]['windows'][300]['efficiency'] for grid in grids.values()])
        finite = values[np.isfinite(values)]
        distributions[symbol] = dict(finite=len(finite), quantiles={str(q): float(np.quantile(finite, q)) for q in (0, .5, .9, .95, .99, 1)},
                                    above={str(x): int((finite >= x).sum()) for x in (.1, .2, .3, .4, .5)})
    examples_by_symbol = {symbol: sorted([entry for entry in examples if entry['symbol'] == symbol],
                                         key=lambda entry: entry['adverse_gap_money'], reverse=True)[:5] for symbol in common.SYMBOLS}
    common.save('全27条件の旧指値価格と当時気配差及びER実尺度の独立診断.json',
                dict(全合格=True, 全期間既知=True, 主=fixed['主'], 条件別=results, ER300分布=distributions,
                     主の指値気配差上位5=examples_by_symbol,
                     解釈='買い指値は指定値以下、売り指値は指定値以上の当時気配を満たしているが、全量を元limitに約定させ価格改善を与えない悲観代理である。古い基準を状態許可まで保持すると、現在気配とlimitの乖離が大きくなり、成立後すぐ逆行損切りとなる。',
                     限界='same_path_entry_quote_only_netは既存親の出口判断・出口価格を固定した新規価格差だけの診断。実際のIFDは約定価格を変更すると利確/損切り発動も変わるため、新手法の損益とは呼ばない。大幅損失を実取引で必ず起きる金額と解釈しない。',
                     SHA256=common.fingerprint(paths), 現在API取得=0, 実注文=0, 旧変更=0, 固定先行コード変更=0))


if __name__ == '__main__':
    main()
