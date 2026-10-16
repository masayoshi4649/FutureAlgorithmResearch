"""固定した同幅6手法の損失を、価格経路・反転の反復・気配差・料金へ分ける。"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib
import json
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0, str(WORK))
sys.dont_write_bytecode = True
import research


def jst(timestamp):
    """
    機能: 保存された代理時計を日本時間の表示へ変換する。
    引数: timestamp (float)。
    返り値: str。実際の受信時刻を補完しない。
    """
    return datetime.fromtimestamp(float(timestamp), timezone(timedelta(hours=9))).isoformat(timespec='seconds')


def cash_partition(values):
    """
    機能: 決済脚の純損益を利益・損失の絶対額・収支へ分ける。
    引数: values (list[float] 又は ndarray)。
    返り値: dict の会計と脚数。
    """
    values = np.asarray(values, dtype=float)
    return dict(脚数=len(values), 利益=float(values[values > 0].sum()), 損失=float(-values[values < 0].sum()),
                収支=float(values.sum()), 黒字脚=int((values > 0).sum()), 赤字脚=int((values < 0).sum()))


def detail(key, record, trade, orders):
    """
    機能: 決済脚の原本参照と、事後の順行・逆行・含み益の戻しを記述する。
    引数: key (tuple[str,str])、record (dict)、trade/ orders (ndarray)。
    返り値: dict。将来経路は説明にのみ使い、取引判断へ戻さない。
    """
    start, end = int(trade[1]), int(trade[2])
    side, qty = int(trade[3]), int(trade[4])
    point = research.CONTRACTS[key[1]]['pointvalue']
    tick = record['tick']
    rows = orders[orders[:, 2] == trade[0]]
    new = rows[rows[:, 6] == 1][0]
    close = rows[rows[:, 6] == 0][-1]
    positions = np.arange(start, end + 1)
    positions = positions[record['quote_valid'][positions]]
    quote = record['bid'][positions] if side == 1 else record['ask'][positions]
    liquidation = side * qty * point * (quote - trade[5]) - trade[7] - trade[8]
    best = float(liquidation.max())
    worst = float(liquidation.min())
    mids = (record['bid'] + record['ask']) / 2.
    middle = side * qty * point * (mids[end] - mids[start])
    current = side * qty * point * (record['price'][end] - record['price'][start])
    valid_prices = record['price'][start:end + 1][record['price_valid'][start:end + 1]]
    favorable = side * (valid_prices - trade[5]) / tick
    path_time = record['time_s'][start:end + 1]
    return dict(session=key[0], symbol=key[1], ticket_id=int(trade[0]), cycle_id=int(trade[13]),
                direction='買い' if side == 1 else '売り', quantity=qty,
                entry_reason=int(trade[11]), exit_reason=int(trade[12]),
                entry_decision=jst(new[9]), entry_fill=jst(new[11]), exit_decision=jst(close[9]), exit_fill=jst(close[11]),
                entry_i=start, exit_i=end, entry_seq=int(record['seq'][start]), exit_seq=int(record['seq'][end]),
                entry_decision_seq=int(record['seq'][int(new[1])]), exit_decision_seq=int(record['seq'][int(close[1])]),
                entry=float(trade[5]), exit=float(trade[6]),
                entry_CurrentPrice=float(record['price'][start]), exit_CurrentPrice=float(record['price'][end]),
                entry_bid=float(record['bid'][start]), entry_ask=float(record['ask'][start]),
                exit_bid=float(record['bid'][end]), exit_ask=float(record['ask'][end]),
                entry_spread_ticks=float((record['ask'][start] - record['bid'][start]) / tick),
                exit_spread_ticks=float((record['ask'][end] - record['bid'][end]) / tick),
                net=float(trade[10]), gross=float(trade[9]), fees=float(trade[7] + trade[8]),
                midpoint_gross=float(middle), spread_drag=float(middle - trade[9]),
                CurrentPrice_endpoint_gross=float(current),
                CurrentPrice_endpoint_minus_fill_gross=float(current - trade[9]),
                gross_ticks=float(trade[9] / (qty * point * tick)),
                planned_stop_and_fees=float(qty * point * tick * 8 + trade[7] + trade[8]),
                best_observed_liquidation_net=best, worst_observed_liquidation_net=worst,
                observed_profit_giveback=best - float(trade[10]),
                CurrentPrice_MFE_ticks=float(favorable.max(initial=0.)),
                CurrentPrice_MAE_ticks=float(-favorable.min(initial=0.)),
                proxy_hold_seconds=float(path_time[-1] - path_time[0]),
                max_proxy_clock_gap=float(np.diff(path_time).max(initial=0.)))


def summarize_symbol(ledger, inputs, symbol):
    """
    機能: 反転入口・返済理由・連続赤字・予定幅超過を一商品でまとめる。
    引数: ledger/inputs (dict)、symbol (str)。
    返り値: dict の損失構造。閾値の変更や代表の差替えは行わない。
    """
    cases = []
    runs = []
    linked = []
    for key, saved in ledger.items():
        if key[1] != symbol:
            continue
        record = inputs[key]
        active = []
        previous = None
        for trade in saved['trades']:
            case = detail(key, record, trade, saved['orders'])
            cases.append(case)
            if trade[11] in (21, 22):
                assert previous is not None and previous['direction'] != case['direction']
                assert previous['exit_i'] <= case['entry_i']
                linked.append(dict(前脚収支=previous['net'], 今脚収支=case['net'],
                                   入口理由=case['entry_reason'], 同じ観測=previous['exit_i'] == case['entry_i']))
            if case['net'] < 0:
                active.append(case)
            elif active:
                runs.append(active)
                active = []
            previous = case
        if active:
            runs.append(active)
    all_net = [r['net'] for r in cases]
    loss_cases = [r for r in cases if r['net'] < 0]
    overruns = [r for r in cases if -r['net'] > r['planned_stop_and_fees'] + 1e-6]
    reversed_gains = [r for r in cases if r['best_observed_liquidation_net'] > 0 and r['net'] < 0]
    holding = np.array([r['proxy_hold_seconds'] for r in cases])
    largest_run = min(runs, key=lambda group: sum(r['net'] for r in group), default=[])
    return dict(
        全脚=cash_partition(all_net),
        新規理由={str(reason): cash_partition([r['net'] for r in cases if r['entry_reason'] == reason]) for reason in (20, 21, 22)},
        返済理由={str(reason): cash_partition([r['net'] for r in cases if r['exit_reason'] == reason]) for reason in (1, 2, 3, 6)},
        反転新規=dict(合計=len(linked), 直前赤字の直後=sum(r['前脚収支'] < 0 for r in linked),
                      直前黒字の直後=sum(r['前脚収支'] > 0 for r in linked), 同じ観測=sum(r['同じ観測'] for r in linked),
                      今脚だけの会計=cash_partition([r['今脚収支'] for r in linked])),
        連続赤字=dict(最大連敗数=max((len(g) for g in runs), default=0),
                      最大赤字区間収支=sum(r['net'] for r in largest_run),
                      最大赤字区間脚数=len(largest_run),
                      そのうち即反転入口=sum(r['entry_reason'] == 21 for r in largest_run),
                      最大赤字区間=largest_run),
        損切り幅を超えた損失=dict(対象脚数=len(overruns), 全赤字脚数=len(loss_cases),
                                会計=cash_partition([r['net'] for r in overruns]),
                                大きい3例=sorted(overruns, key=lambda r: r['net'])[:3]),
        一時的な黒字から赤字返済=dict(脚数=len(reversed_gains),
                                    会計=cash_partition([r['net'] for r in reversed_gains]),
                                    大きい3例=sorted(reversed_gains, key=lambda r: r['net'])[:3]),
        原本時計の保有時間=dict(中央値=float(np.median(holding)) if len(holding) else None,
                               九十五百分位=float(np.percentile(holding, 95)) if len(holding) else None,
                               最大=float(holding.max()) if len(holding) else None,
                               同じ時計で新規返済した脚数=int((holding == 0).sum())),
        赤字上位3脚=sorted(cases, key=lambda r: r['net'])[:3],
        CurrentPrice端点進行損益=sum(r['CurrentPrice_endpoint_gross'] for r in cases),
        CurrentPrice端点と約定の差=sum(r['CurrentPrice_endpoint_minus_fill_gross'] for r in cases))


# ----------------------------------------
def main():
    """
    機能: 完了済み固定6条件の通常・論理対照を診断し、日本語成果を保存する。
    引数: なし。
    返り値: None。未完了なら停止し、部分的な成績で手法を選び直さない。
    """
    fixed = research.read(research.FIXED)
    research.validate_fixed(fixed)
    selection = research.read(WORK / '前半選定.json')
    conditions = selection['common_width']
    assert len(conditions) == 6 and all(r['config']['width_ticks'] == 8 and r['config']['variant'] == 1 for r in conditions)
    for model, folder in [('main', 'final/delay0'), ('ideal_fee', 'ideal_fee')]:
        for row in conditions:
            assert (WORK / folder / 'results' / (row['id'] + '.json')).exists()
            assert (WORK / folder / 'ledgers' / (row['id'] + '.pkl')).exists()
    inputs = research.data.load_data(verify=False)
    models = {}
    sources = {}
    for model, folder in [('main', 'final/delay0'), ('ideal_fee', 'ideal_fee')]:
        model_inputs = inputs if model == 'main' else {
            key: dict(r, bid=r['price'], ask=r['price'], quote_valid=r['price_valid']) for key, r in inputs.items()}
        methods = []
        for row in conditions:
            key = row['id']
            path = WORK / folder / 'results' / (key + '.json')
            result = research.read(path)
            sources[str(path.relative_to(WORK))] = hashlib.sha256(path.read_bytes()).hexdigest()
            with (WORK / folder / 'ledgers' / (key + '.pkl')).open('rb') as stream:
                ledger = pickle.load(stream)
            symbols = {}
            for symbol in research.SYMBOLS:
                analysis = summarize_symbol(ledger, model_inputs, symbol)
                assert abs(analysis['全脚']['収支'] - result['periods']['対象'][symbol]['net']) < 1e-5
                symbols[symbol] = dict(periods={p: result['periods'][p][symbol] for p in ('前16', '後14', '対象')},
                                       analysis=analysis)
            methods.append(dict(id=key, config=row['config'], symbols=symbols))
            print(f'{model} {key} 診断完了', flush=True)
        models[model] = methods
    comparison = []
    fields = ['profit', 'loss', 'net', 'gross', 'fees', 'midpoint_gross', 'spread_drag', 'trades',
              'cycle_profit_share', 'winning_sessions', 'losing_sessions', 'no_trade_sessions']
    for model, methods in models.items():
        lookup = {r['id']: r for r in methods}
        for pair in selection['pairs']:
            for period in ('前16', '後14', '対象'):
                for symbol in research.SYMBOLS:
                    first = lookup[pair['left_id']]['symbols'][symbol]['periods'][period]
                    second = lookup[pair['right_id']]['symbols'][symbol]['periods'][period]
                    comparison.append(dict(model=model, pair=pair, period=period, symbol=symbol,
                        基準={k: first[k] for k in fields}, 比較={k: second[k] for k in fields},
                        差額_比較から基準を引く={k: second[k] - first[k] for k in fields
                                               if first[k] is not None and second[k] is not None}))
    output = dict(
        対象='幅8呼値・出口1幅の6手法。比較条件は事前指定で、後半の損益から選んだ条件ではない。',
        観測制約='時刻はCurrentPriceTime由来の代理時計。保存順は保持するが、同じ時計での新規返済を実時間0秒とは呼ばない。ラージ気配を小型商品の全量約定へ代用する仮定がある。',
        将来値の用途='保有中の最良清算損益・最大順行逆行・最大連敗の抽出は事後説明専用。入口・途中・出口・代表選定へ戻さない。',
        損切り幅='同幅比較ではTOPIX4ポイント、日経80ポイント。10枚・20枚では価格損失40,000円・16,000円と往復料が目安で、実約定損失の保証上限ではない。',
        理由対応={'新規20': '通常の待機基準から新規', '新規21': '返済後すぐに反対新規', '新規22': '反対方向の追加1幅を確認した新規',
                  '返済1': '初期損切り幅', '返済2': '固定利確', '返済3': '極値からの追尾返済', '返済6': '場末全返済'},
        分解='midpoint_gross−spread_drag−fees＝netは同じ約定経路の会計恒等式。CurrentPrice端点との分解は最終約定値と売買気配の非同期を含み、方向予測の純粋な効力とは断定しない。',
        モデル差='現在値必約定＋実手数料は注文状態も再生した別の経路。通常との差を単純な費用差又は利益上界とは呼ばない。',
        即反転の集計='反転新規の会計は反転後に建てた脚だけ。前脚も足して重複計上することはしない。連敗は同じセッション内で数え、非赤字決済で区切る。',
        models=models, comparisons=comparison, source_SHA256=sources,
        選定SHA256=research.data.digest(WORK / '前半選定.json'), コードSHA256=research.data.digest(Path(__file__)))
    research.save_json(HERE / '同幅6手法の損失構造.json', output)
    summary = []
    for model, methods in models.items():
        for row in methods:
            values = []
            for symbol in research.SYMBOLS:
                a = row['symbols'][symbol]['periods']['対象']
                d = row['symbols'][symbol]['analysis']
                values.append(f'{symbol} 収支{a["net"]:,.0f}円、手数料前{a["gross"]:,.0f}円、'
                              f'{a["trades"]}脚、最大{d["連続赤字"]["最大連敗数"]}連敗')
            summary.append(f'{model} {row["id"]}: ' + '／'.join(values))
    research.save_json(HERE / '診断の短い要旨.json', dict(数値概要=summary,
        解釈上の注意=['前半選定・事前指定の同幅比較を変更しない。', '実手数料と気配差を区別する。',
                      '同じ幅でも出口後の建て直し方により取引の時刻・回数・価格経路が変わる。',
                      '現在値必約定でも手数料前が赤字なら、手数料だけでは説明できない。']))
    print(json.dumps(dict(完了=True, 固定条件=len(conditions), 比較レコード数=len(comparison)), ensure_ascii=False))


if __name__ == '__main__':
    main()
