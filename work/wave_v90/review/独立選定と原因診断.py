"""注文台帳から選定・差額・状態別の成績と最大損失原因を独立に復元する。"""

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
TOLERANCE = 1e-4


def read(path):
    """
    機能: 完了済み保存成果又は価格素材を読取専用で読む。
    引数: path(Path)。
    返り値: object はJSON又はpickleの内容。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    """
    機能: 保存資料を分割して指紋化する。
    引数: path(Path)。
    返り値: str はSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def clean(value):
    """
    機能: NumPy数値等を有限な日本語JSONへ変換する。
    引数: value(object)。
    返り値: object は標準JSON型。
    """
    if isinstance(value, dict):
        return {str(key): clean(child) for key, child in value.items()}
    if isinstance(value, (tuple, list, np.ndarray)):
        return [clean(child) for child in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def stamp(value):
    """
    機能: 保存代理時計を日本時間の秒表示へ変換する。
    引数: value(float)。
    返り値: str は日本時間ISO形式。
    """
    return datetime.fromtimestamp(float(value), ZoneInfo('Asia/Tokyo')).isoformat(timespec='seconds')


def parents_from_orders(key, ledger):
    """
    機能: エンジンと正式会計を呼ばず、新規・返済注文だけから全親を再構築する。
    引数: key(tuple[str,str])、ledger(dict)。
    返り値: list[dict] は源別親の数量・約定・手数料・純損益。
    """
    value, fee_unit = (1000., 41.8) if key[1] == 'TOPIX' else (10., 11.)
    opened, ended = {}, []
    for row in ledger['orders']:
        parent_id, source, quantity = int(row[2]), int(row[3]), int(row[5])
        parent_key = source, parent_id
        fee = math.floor(quantity * fee_unit + 1e-8)
        assert fee == row[9]
        assert row[0] > row[1]
        if row[7] == 1:
            assert parent_key not in opened
            opened[parent_key] = row
        else:
            entry = opened.pop(parent_key)
            assert quantity == entry[5] and row[4] == -entry[4]
            side = int(entry[4])
            gross = side * quantity * (row[6] - entry[6]) * value
            ended.append(dict(parent_id=parent_id, source=source, source_name=('J2', 'O06')[source],
                decision_row=int(entry[1]), entry_row=int(entry[0]), exit_decision_row=int(row[1]),
                exit_row=int(row[0]), side=side, quantity=quantity,
                entry_price=float(entry[6]), exit_price=float(row[6]),
                entry_fee=float(entry[9]), exit_fee=float(row[9]), gross=float(gross),
                fees=float(entry[9] + row[9]), net=float(gross-entry[9]-row[9]),
                entry_reason=int(entry[8]), exit_reason=int(row[8]), cycle=int(entry[13]),
                decision_time=float(entry[10]), entry_time=float(entry[11]),
                exit_decision_time=float(row[10]), exit_time=float(row[11])))
    assert not opened
    expected = {int(row[0]): row for row in ledger['trades']}
    assert len(ended) == len(expected)
    for parent in ended:
        reference = expected[parent['parent_id']]
        assert abs(parent['net'] - reference[11]) < TOLERANCE
        assert abs(parent['gross'] - reference[10]) < TOLERANCE
        assert parent['source'] == reference[1] and parent['quantity'] == reference[5]
    return ended


def totals(parents):
    """
    機能: 源や同日の利益玉と損失玉を相殺せず親の金額を集計する。
    引数: parents(list[dict])。
    返り値: dict は利益・損失・収支・親数・平均勝負額・枚数。
    """
    winning = [parent for parent in parents if parent['net'] > 0]
    losing = [parent for parent in parents if parent['net'] < 0]
    profit = sum(parent['net'] for parent in winning)
    loss = -sum(parent['net'] for parent in losing)
    average_win = profit / len(winning) if winning else None
    average_loss = loss / len(losing) if losing else None
    return dict(profit=profit, loss=loss, net=profit-loss,
                gross=sum(parent['gross'] for parent in parents), fees=sum(parent['fees'] for parent in parents),
                campaigns=len(parents), winning_campaigns=len(winning), losing_campaigns=len(losing),
                flat_campaigns=len(parents)-len(winning)-len(losing),
                winning_lots=sum(parent['quantity'] for parent in winning),
                losing_lots=sum(parent['quantity'] for parent in losing),
                lots=sum(parent['quantity'] for parent in parents),
                profit_share=profit/(profit+loss) if profit+loss else None,
                average_win=average_win, average_loss=average_loss,
                payoff=average_win/average_loss if winning and losing else None)


def aggregate(accounts, symbol, sessions):
    """
    機能: 指定期間の親集計、活動場、最大利益日と最大利益親除外を独立計算する。
    引数: accounts(dict[tuple,list])、symbol(str)、sessions(list[str])。
    返り値: dict は商品を混ぜない期間統計。
    """
    selected = {session: accounts[(session, symbol)] for session in sessions}
    flat = [parent for parents in selected.values() for parent in parents]
    answer = totals(flat)
    sessions_net = {session: sum(parent['net'] for parent in parents) for session, parents in selected.items()}
    active = sum(bool(parents) for parents in selected.values())
    positive = sum(value > 0 for value in sessions_net.values())
    answer.update(active_sessions=active, positive_sessions=positive,
                  losing_sessions=sum(value < 0 for value in sessions_net.values()),
                  no_trade_sessions=len(sessions)-active, session_count=len(sessions),
                  positive_session_rate=positive/active if active else None,
                  all_sessions_profitable=all(value > 0 for value in sessions_net.values()),
                  worst_session=min(sessions_net.values(), default=0), sessions_net=sessions_net)
    days = {}
    for session, net in sessions_net.items():
        days[session[:10]] = days.get(session[:10], 0) + net
    best_day = max(days, key=days.get) if days else None
    answer['best_day'] = best_day
    answer['without_best_day'] = totals([parent for session, parents in selected.items()
                                       if session[:10] != best_day for parent in parents])
    largest = max(flat, key=lambda parent: parent['net'], default=None)
    answer['without_best_parent'] = totals([parent for parent in flat if parent is not largest])
    answer['largest_parent_profit'] = largest['net'] if largest else None
    answer['sources'] = {name: totals([parent for parent in flat if parent['source'] == source])
                         for source, name in enumerate(('J2', 'O06'))}
    return answer


def choose(periods):
    """
    機能: 凍結した前16場の段階別足切りと同点解消を独立に実行する。
    引数: periods(dict[ID,dict])。
    返り値: dict は選定ID、足切り段階と全採点。
    """
    all_ids = sorted(periods)
    active = [ident for ident in all_ids if all(periods[ident]['前16'][symbol]['campaigns'] >= 20
                    and periods[ident]['前16'][symbol]['active_sessions'] >= 8 for symbol in SYMBOLS)]
    positive = [ident for ident in active if all(periods[ident]['前16'][symbol]['net'] > 0 for symbol in SYMBOLS)]
    good = [ident for ident in positive if all(periods[ident]['前16'][symbol]['payoff'] is not None
                    and periods[ident]['前16'][symbol]['payoff'] > 1 for symbol in SYMBOLS)]
    pool = good or positive or active or all_ids
    scores = {}
    for ident in pool:
        rows = [periods[ident]['前16'][symbol] for symbol in SYMBOLS]
        shares = [row['profit_share'] if row['profit_share'] is not None else -1 for row in rows]
        rates = [row['positive_session_rate'] if row['positive_session_rate'] is not None else -1 for row in rows]
        scores[ident] = (-min(shares), -min(rates), -sum(shares), ident)
    return dict(id=min(pool, key=scores.get), level=0 if good else 1 if positive else 2 if active else 3,
                eligible_ids=pool, scores=scores)


def entry_identity(parent):
    """
    機能: 将来の出口を使わず同じ新規だけを親対応する。
    引数: parent(dict)。
    返り値: tuple は源・判断・実新規・方向・数量・価格。
    """
    return tuple(parent[field] for field in ('source', 'decision_row', 'entry_row', 'side', 'quantity', 'entry_price'))


def difference(actual, baseline):
    """
    機能: 消えた親・同じ入口の出口変更・新しい約定経路を分けて差額を復元する。
    引数: actual/baseline(list[dict])。
    返り値: dict は損失回避・利益喪失・出口差・新規利益損失と収支差。
    """
    left = {entry_identity(parent): parent for parent in actual}
    right = {entry_identity(parent): parent for parent in baseline}
    assert len(left) == len(actual) and len(right) == len(baseline)
    both = left.keys() & right.keys()
    removed = [parent for key, parent in right.items() if key not in left]
    added = [parent for key, parent in left.items() if key not in right]
    saved = -sum(parent['net'] for parent in removed if parent['net'] < 0)
    missed = sum(parent['net'] for parent in removed if parent['net'] > 0)
    exit_delta = sum(left[key]['net']-right[key]['net'] for key in both)
    new_profit = sum(parent['net'] for parent in added if parent['net'] > 0)
    new_loss = -sum(parent['net'] for parent in added if parent['net'] < 0)
    delta = sum(parent['net'] for parent in actual)-sum(parent['net'] for parent in baseline)
    assert abs(saved-missed+exit_delta+new_profit-new_loss-delta) < TOLERANCE
    return dict(saved_loss=saved, missed_profit=missed, changed_exit=exit_delta,
                new_profit=new_profit, new_loss=new_loss, delta=delta,
                matched=len(both), absent=len(removed), novel=len(added))


def state(session, entry, config):
    """
    機能: 正式strategyを呼ばず、二市場のER・範囲・共同方向から現在状態を復元する。
    引数: session/entry/config(dict)。
    返り値: dict は格子別の生状態・確認状態と市場原資料。
    """
    grid = session['grid']
    markets = [session['markets'][symbol] for symbol in SYMBOLS]
    valid = np.ones(len(grid), bool)
    high = valid.copy()
    low = valid.copy()
    inside = valid.copy()
    for market in markets:
        current, window, bounds = market['current'], market['windows'][300], market['ranges'][180]
        valid &= current['valid'] & window['source_valid'] & np.isfinite(window['efficiency'])
        valid &= np.isfinite(window['total_variation']) & (window['total_variation'] > 0)
        high &= window['efficiency'] >= config['high_er']
        low &= window['efficiency'] <= config['low_er']
        inside &= bounds['source_valid'] & bounds['position_valid'] & (bounds['width'] > 0)
        inside &= np.isfinite(bounds['width']) & np.isfinite(current['mid'])
        inside &= (current['mid'] >= bounds['low']) & (current['mid'] <= bounds['high'])
    common = entry['common']
    raw = np.zeros(len(grid), np.int8)
    for side in (-1, 1):
        allowed = entry['entries']['J2']['long_allowed' if side == 1 else 'short_allowed']
        raw[valid & high & (common == side) & allowed] = side
    raw[valid & low & inside & (common == 0)] = 2
    mode = np.zeros(len(grid), np.int8)
    sources = [market['current']['index'] for market in markets]
    for wanted in (-1, 1, 2):
        first = None
        previous = None
        for index in range(len(grid)):
            if not valid[index] or raw[index] != wanted:
                first = None
            else:
                if first is None or (previous is not None and grid[index]-grid[previous] > 5.00000001):
                    first = index
                if config['confirm_seconds'] == 0 or (grid[index]-grid[first] >= config['confirm_seconds']
                        and all(source[index] > source[first] for source in sources)):
                    mode[index] = wanted
            previous = index
    return dict(grid=grid, mode=mode, raw=raw, valid=valid, common=common, markets=session['markets'])


def timeline(record, grid_state):
    """
    機能: 格子が最初の自市場原板で公開される順を独立復元する。
    引数: record/grid_state(dict)。
    返り値: dict は全原板行で見えていた最新格子・状態。
    """
    times, grid = record['time_s'], grid_state['grid']
    mapped = np.full(len(times), -1, np.int32)
    for index, row in enumerate(np.searchsorted(times, grid, side='left')):
        if row < len(times) and times[row]-grid[index] <= 10:
            mapped[row] = index
    latest = np.maximum.accumulate(mapped)
    good = latest >= 0
    good[good] &= times[good]-grid[latest[good]] <= 10.00000001
    mode = np.zeros(len(times), np.int8)
    mode[good] = grid_state['mode'][latest[good]]
    return dict(latest=latest, fresh=good, mode=mode)


def snapshot_at(row, record, current, grid_state):
    """
    機能: 特定判断行で当時見えていた二市場ER・方向・範囲・最良気配を示す。
    引数: row(int)、record/current/grid_state(dict)。
    返り値: dict は将来情報を含まない当時の説明用資料。
    """
    index = int(current['latest'][row])
    answer = dict(row=int(row), seq=int(record['seq'][row]), time=stamp(record['time_s'][row]),
                  current_price=float(record['price'][row]), bid=float(record['bid'][row]), ask=float(record['ask'][row]),
                  mode=int(current['mode'][row]), fresh=bool(current['fresh'][row]), grid_index=index)
    if index >= 0:
        answer.update(grid_time=stamp(grid_state['grid'][index]), raw_mode=int(grid_state['raw'][index]),
                      common=int(grid_state['common'][index]), markets={})
        for symbol in SYMBOLS:
            market = grid_state['markets'][symbol]
            now, window, bounds = market['current'], market['windows'][300], market['ranges'][180]
            answer['markets'][symbol] = dict(
                source_row=int(now['index'][index]), source_valid=bool(now['valid'][index]),
                actual_age=float(now['actual_age'][index]), mid=float(now['mid'][index]),
                ER300=float(window['efficiency'][index]), ret_bp300=float(window['ret_bp'][index]),
                ret_bp30=float(market['windows'][30]['ret_bp'][index]),
                total_variation300=float(window['total_variation'][index]),
                range_low180=float(bounds['low'][index]), range_high180=float(bounds['high'][index]),
                range_position180=float(bounds['position'][index]))
    return answer


def first_row(mask, start, stop):
    """
    機能: 指定範囲における条件初成立行を見つける。
    引数: mask(ndarray[bool])、start/stop(int、左含む右含まない)。
    返り値: int | None は最初の行。
    """
    available = np.flatnonzero(mask[start:stop])
    return int(start+available[0]) if len(available) else None


def diagnosis(key, parent, ledger, record, current, grid_state):
    """
    機能: 大損失親の入口から反対状態、損切り、予約、約定の順を具体化する。
    引数: key(tuple)、parent/ledger/record/current/grid_state(dict)。
    返り値: dict は当時状態・実値動き・各判断時計・失効と気配悪化。
    将来極値や最終netは原因診断にだけ使い、取引判断へ戻さない。
    """
    start, stop, side = parent['entry_row'], parent['exit_row'], parent['side']
    opposite = first_row(current['mode'] == -side, start+1, stop+1)
    unknown = first_row(current['mode'] == 0, start+1, stop+1)
    p = record['price']
    stop_width = 8 * record['tick']
    crossed = first_row(side * (p-parent['entry_price']) <= -stop_width, start+1, stop+1) \
        if parent['source'] == 1 else None
    quote = record['bid'] if side == 1 else record['ask']
    decision_quote = quote[parent['exit_decision_row']]
    quote_worsening = side * (parent['exit_price']-decision_quote)
    relevant_events = ledger['events'][(ledger['events'][:, 1] == parent['parent_id'])
                                      & (ledger['events'][:, 2] == parent['source'])]
    progress = side * (quote[start:stop+1]-parent['entry_price'])
    peak_row = start+int(np.argmax(progress))
    trough_row = start+int(np.argmin(progress))
    answer = dict(session=key[0], symbol=key[1], parent=parent,
                  new_decision=snapshot_at(parent['decision_row'], record, current, grid_state),
                  entry=snapshot_at(start, record, current, grid_state),
                  exit_decision=snapshot_at(parent['exit_decision_row'], record, current, grid_state),
                  exit=snapshot_at(stop, record, current, grid_state),
                  first_opposite_mode=snapshot_at(opposite, record, current, grid_state) if opposite is not None else None,
                  first_unknown_mode=snapshot_at(unknown, record, current, grid_state) if unknown is not None else None,
                  first_range_stop=snapshot_at(crossed, record, current, grid_state) if crossed is not None else None,
                  liquidation_favourable_price=max(float(progress.max()), 0.),
                  liquidation_adverse_price=max(float(-progress.min()), 0.),
                  favourable_peak_time=stamp(record['time_s'][peak_row]),
                  adverse_peak_time=stamp(record['time_s'][trough_row]),
                  exit_quote_change_after_decision=float(quote_worsening),
                  exit_quote_change_money=float(quote_worsening*parent['quantity']*(1000 if key[1]=='TOPIX' else 10)),
                  events=[])
    for event in relevant_events:
        row = int(event[0])
        answer['events'].append(dict(row=row, time=stamp(record['time_s'][row]), code=int(event[3]),
            decision_row=int(event[6]), decision_time=stamp(event[9]), mode=int(event[8]),
            limit_price=float(event[7]), detail=float(event[11])))
    if parent['source'] == 0:
        answer['初期仮説と限界'] = '二市場の共通進行へ入ったが、確認済み状態は過去窓の形状であり、その後の継続を保証しない。元の幅広い追尾又は30分期限までの逆行が損失を確定する。'
    else:
        answer['初期仮説と限界'] = '低ERと過去範囲内を往復の候補としたが、買い指値は売り気配の下落、売り指値は買い気配の上昇で約定するため、反発未確認の逆選択が残る。'
    return answer


def main():
    """
    機能: 全27の完了後に独立会計と原因診断を追加review内へ保存する。
    引数: なし。
    返り値: None。凍結コードと過去資料は変更しない。
    """
    fixed = read(WORK/'事前固定.json')
    ids = [config['id'] for config in fixed['条件']]
    assert len(ids) == 27
    assert all((WORK/'results'/f'{ident}.json').exists() for ident in ids)
    for relative, expected in fixed['SHA256'].items():
        assert digest(ROOT/relative) == expected, relative
    periods, accounts, ledgers, results = {}, {}, {}, {}
    for ident in ids:
        results[ident] = read(WORK/'results'/f'{ident}.json')
        ledger_path = WORK/'ledgers'/f'{ident}.pkl'
        assert digest(ledger_path) == results[ident]['ledger_SHA256']
        ledgers[ident] = read(ledger_path)
        accounts[ident] = {key: parents_from_orders(key, ledger) for key, ledger in ledgers[ident].items()}
        periods[ident] = {name: {symbol: aggregate(accounts[ident], symbol, sessions) for symbol in SYMBOLS}
                         for name, sessions in [('全30', fixed['全30']), ('前16', fixed['前16']), ('後14', fixed['後14'])]}
        for name, by_symbol in periods[ident].items():
            for symbol, independent in by_symbol.items():
                official = results[ident]['periods'][name][symbol]
                for field in ('profit', 'loss', 'net', 'gross', 'fees', 'campaigns', 'winning_campaigns',
                              'losing_campaigns', 'winning_lots', 'losing_lots', 'lots', 'profit_share',
                              'average_win', 'average_loss', 'payoff', 'active_sessions', 'positive_sessions',
                              'losing_sessions', 'no_trade_sessions', 'positive_session_rate', 'worst_session'):
                    if independent[field] is None:
                        assert official[field] is None
                    else:
                        assert abs(independent[field]-official[field]) < TOLERANCE, (ident, name, symbol, field)
                assert independent['best_day'] == official['best_day']
                for field in ('profit', 'loss', 'net', 'campaigns'):
                    assert abs(independent['without_best_day'][field]-official['without_best_day'][field]) < TOLERANCE
    chosen = choose(periods)

    # ----------------------------------------
    noninterference = []
    compared = [index for index in range(17) if index not in (2, 16)]
    for key, ledger in ledgers['M82'].items():
        for source, single in ((0, 'J8'), (1, 'O2')):
            actual = ledger['orders'][ledger['orders'][:, 3] == source]
            expected = ledgers[single][key]['orders']
            assert np.array_equal(actual[:, compared], expected[:, compared])
            assert ledger['source_curve_column_SHA256'][source] == ledgers[single][key]['source_curve_column_SHA256'][source]
            noninterference.append(dict(session=key[0], symbol=key[1], source=source, orders=len(actual)))
    differences = {}
    for config in fixed['条件']:
        if config['selection'] != 'gated_fixed' or config['trend_budget'] != 8 or config['range_budget'] != 2:
            continue
        ident = config['id']
        per_key = {key: difference(accounts[ident][key], accounts['M82'][key]) for key in accounts['M82']}
        differences[ident] = {name: {symbol: {field: sum(item[field] for key, item in per_key.items()
                                     if key[0] in sessions and key[1] == symbol)
                                     for field in next(iter(per_key.values()))}
                              for symbol in SYMBOLS}
                             for name, sessions in [('全30', fixed['全30']), ('前16', fixed['前16']), ('後14', fixed['後14'])]}
    comparison_path = WORK/'analysis/比較結果.json'
    if comparison_path.exists():
        comparison = read(comparison_path)
        assert chosen['id'] == comparison['selected'] and chosen['level'] == comparison['selection_proof']['level']
        assert set(chosen['eligible_ids']) == set(comparison['selection_proof']['eligible_ids'])
        for ident, names in differences.items():
            for name, by_symbol in names.items():
                for symbol, fields in by_symbol.items():
                    for field, value in fields.items():
                        assert abs(value-comparison['differences'][ident][name][symbol][field]) < TOLERANCE
    else:
        comparison = None

    # ----------------------------------------
    prices = read(ROOT/'work/wave_v83/prepared/inputs.pkl')
    grids = read(ROOT/'work/wave_v77/inputs/grids_delay1.pkl')
    entries = read(ROOT/'work/wave_v77/prepared/signals_delay1.pkl')
    configs = {config['id']: config for config in fixed['条件']}
    cache = {}
    def diagnostic_inputs(ident, key):
        """
        機能: 同じ市場パラメータの独立状態を再利用し、当該原板での公開順へ接続する。
        引数: ident(str)、key(tuple[str,str])。
        返り値: tuple[dict,dict] は格子状態と原板状態。
        """
        config = configs[ident]
        signature = config['high_er'], config['low_er'], config['confirm_seconds'], key[0]
        if signature not in cache:
            cache[signature] = state(grids[key[0]], entries[key[0]], config)
        grid_state = cache[signature]
        return grid_state, timeline(prices[key], grid_state)

    mode_performance = {}
    for ident in ('J10', 'O10'):
        mode_performance[ident] = {}
        for symbol in SYMBOLS:
            buckets = {'追従順方向': [], '追従逆方向': [], '往復': [], '不明': []}
            per_case = []
            for key, parents in accounts[ident].items():
                if key[1] != symbol:
                    continue
                grid_state, current = diagnostic_inputs(ident, key)
                for parent in parents:
                    mode = int(current['mode'][parent['decision_row']])
                    name = '往復' if mode == 2 else '不明' if mode == 0 else \
                        '追従順方向' if mode == parent['side'] else '追従逆方向'
                    buckets[name].append(parent)
                    per_case.append(dict(session=key[0], parent_id=parent['parent_id'], mode=mode,
                                         class_name=name, net=parent['net']))
            mode_performance[ident][symbol] = dict(groups={name: totals(parents) for name, parents in buckets.items()},
                                                   全親数=sum(len(parents) for parents in buckets.values()))

    # ----------------------------------------
    worst = {}
    for ident in dict.fromkeys((fixed['主'], chosen['id'])):
        worst[ident] = {}
        for symbol in SYMBOLS:
            keys = sorted((key for key in accounts[ident] if key[1] == symbol),
                          key=lambda key: (sum(parent['net'] for parent in accounts[ident][key]), key[0]))[:3]
            cases = []
            for key in keys:
                parents = accounts[ident][key]
                parent = min(parents, key=lambda parent: parent['net'], default=None)
                if parent is None:
                    cases.append(dict(session=key[0], symbol=symbol, net=0., no_trade=True))
                    continue
                grid_state, current = diagnostic_inputs(ident, key)
                case = diagnosis(key, parent, ledgers[ident][key], prices[key], current, grid_state)
                case['session_totals'] = totals(parents)
                case['source_totals'] = {name: totals([item for item in parents if item['source'] == source])
                                         for source, name in enumerate(('J2', 'O06'))}
                cases.append(case)
            worst[ident][symbol] = cases

    both80 = [ident for ident in ids if all(periods[ident]['全30'][symbol]['profit_share'] is not None
              and periods[ident]['全30'][symbol]['profit_share'] >= .8
              and periods[ident]['全30'][symbol]['net'] > 0
              and periods[ident]['全30'][symbol]['campaigns'] >= 20
              and periods[ident]['全30'][symbol]['active_sessions'] >= 8 for symbol in SYMBOLS)]
    raw_both80 = [ident for ident in ids if all(periods[ident]['全30'][symbol]['profit_share'] is not None
                  and periods[ident]['全30'][symbol]['profit_share'] >= .8 for symbol in SYMBOLS)]
    every_session = [ident for ident in ids if all(periods[ident]['全30'][symbol]['all_sessions_profitable']
                                                 for symbol in SYMBOLS)]
    if comparison is not None:
        assert both80 == comparison['both80']
        assert every_session == comparison['all_sessions_positive']
    proof = dict(全合格=True, 全条件数=len(ids), 独立選定=chosen,
                 正式比較との一致=comparison is not None, 主=fixed['主'], 全期間既知=True,
                 会計口座数=sum(len(value) for value in accounts.values()),
                 独立復元親数=sum(len(parents) for value in accounts.values() for parents in value.values()),
                 同量非干渉=dict(全合格=True, 源口座数=len(noninterference), 各口座=noninterference),
                 差額分解=differences, 単独入口時mode別成績=mode_performance,
                 最悪3セッションと最大損失親=worst,
                 独立期間会計=periods, 両商品金額80=both80, 活動足切り前の両80=raw_both80,
                 全30両商品全黒字=every_session,
                 判定条件='金額G/Lは源別親netの正負。無取引は勝ちではない。最大利益日はその商品の日中と夜間を合計して選び、その日全体を除外する。最大利益親の単独除外も別に表示。',
                 注意=['将来の純損益・極値・mode変化は事後診断だけに使用する。',
                       '排他全枠Dと固定8/2枠G82の違いには投入数量と初期損失幅が含まれる。',
                       '前16/後14は全て既知データであり、新しい未見検証ではない。',
                       '同量非干渉の全行曲線一致は保存された源別曲線指紋の比較。全行時価の独立再構築は別担当の全会計監査に委ねる。'],
                 凍結SHA検証=True, 現在API取得=0, 実注文=0, 凍結対象変更=0,
                 SHA256={str(path.relative_to(ROOT)): digest(path) for path in
                    [Path(__file__), WORK/'事前固定.json', *[WORK/'results'/f'{ident}.json' for ident in ids]]})
    if comparison_path.exists():
        proof['SHA256'][str(comparison_path.relative_to(ROOT))] = digest(comparison_path)
    target = HERE/'独立会計選定と状態別成績及び最悪親原因.json'
    target.write_text(json.dumps(clean(proof), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(独立前16=chosen['id'], 主=fixed['主'], 会計口座=proof['会計口座数'],
                         独立親=proof['独立復元親数'], 両80=both80, 全日黒字=every_session,
                         正式比較との一致=comparison is not None), ensure_ascii=False))


if __name__ == '__main__':
    main()
