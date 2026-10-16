"""注文手法を共通の費用会計で比較し、前半だけで代表を固定する。"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
import hashlib
import importlib
import json
import pickle
import sys
import time

import numpy as np

sys.dont_write_bytecode = True
import data


HERE = Path(__file__).resolve().parent
FIXED = HERE / 'results/事前固定.json'
SYMBOLS = ('TOPIX', 'NK225')
CONTRACTS = {'TOPIX': dict(cap=10, pointvalue=1000., fee=41.8),
             'NK225': dict(cap=20, pointvalue=10., fee=11.)}
ORDER_COLUMNS = ['fill_i', 'decision_i', 'ticket_id', 'order_side', 'qty', 'price', 'new_flag', 'reason', 'fee',
                 'decision_time', 'arrival_time', 'fill_time', 'slot', 'limit_price', 'cycle_id', 'islimit']
TRADE_COLUMNS = ['ticket_id', 'entry_i', 'exit_i', 'held_side', 'qty', 'entry', 'exit', 'entryfee', 'exitfee',
                 'gross', 'net', 'entryreason', 'exitreason', 'cycle_id']
CYCLE_COLUMNS = ['cycle_id', 'first_entry_i', 'last_exit_i', 'legs', 'gross', 'fees', 'net', 'closed_qty']
STAT_COLUMNS = ['maxlong', 'maxshort', 'maxreservedlong', 'maxreservedshort', 'residualheldlong',
                'residualheldshort', 'pendingentryqty', 'pendingexitqty', 'IOCcancel', 'entrycount',
                'tradecount', 'peakgrosslots', 'basketstops', 'ties']
EVENT_COLUMNS = ['row_i', 'ticket_id', 'slot', 'code', 'side', 'qty', 'decision_time', 'arrival_time',
                 'price_limit', 'is_limit', 'reason', 'cycle']
MONEY_FIELDS = ('profit', 'loss', 'net', 'gross', 'fees', 'midpoint_gross', 'spread_drag', 'decision_to_fill_cost',
                'cycle_profit', 'cycle_loss', 'cycle_net', 'hold_seconds', 'cycle_hold_seconds',
                'order_wait_seconds')
COUNT_FIELDS = ('trades', 'wins', 'losses', 'flats', 'winning_lots', 'losing_lots', 'flat_lots', 'cycles',
                'cycle_wins', 'cycle_losses', 'cycle_flats', 'orders', 'entry_orders', 'exit_orders',
                'cancellations', 'basket_stops', 'ties')
MAX_FIELDS = ('max_trade_loss', 'max_cycle_loss', 'max_long', 'max_short', 'max_reserved_long',
              'max_reserved_short', 'max_gross_lots', 'max_gross', 'max_net', 'max_order_wait_seconds')


def read(path):
    """
    機能: 今回又は既存の保存仕様を読む。
    引数: path (Path)。
    返り値: dict 又は list。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, value):
    """
    機能: 今回の作業領域へ日本語JSONを保存する。
    引数: path (Path)、value (object)。
    返り値: None。非有限数値があると停止する。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def metrics(a):
    """
    機能: 決済脚と全玉が終了した親組の比率を別々に加える。
    引数: a (dict) は加算済み会計。
    返り値: dict の比率付き会計。無取引を勝ちとして扱わない。
    """
    for prefix, count in (('', 'trades'), ('cycle_', 'cycles')):
        p, loss = a[prefix + 'profit'], a[prefix + 'loss']
        wins, losses = a[prefix + 'wins'], a[prefix + 'losses']
        a[prefix + 'profit_share'] = p / (p + loss) if p + loss else None
        a[prefix + 'profit_loss_ratio'] = p / loss if loss else None
        a[prefix + 'win_rate'] = wins / a[count] if a[count] else None
        a[prefix + 'average_win'] = p / wins if wins else None
        a[prefix + 'average_loss'] = loss / losses if losses else None
        a[prefix + 'payoff'] = (p / wins) / (loss / losses) if wins and losses and loss else None
        a[prefix + 'average_net'] = a[prefix + 'net'] / a[count] if a[count] else None
    a['average_hold_seconds'] = a['hold_seconds'] / a['trades'] if a['trades'] else None
    a['cycle_average_hold_seconds'] = a['cycle_hold_seconds'] / a['cycles'] if a['cycles'] else None
    a['average_order_wait_seconds'] = a['order_wait_seconds'] / a['orders'] if a['orders'] else None
    return a


def account(key, record, output, run):
    """
    機能: 約定台帳から脚・親組・全玉清算時価を独立に照合して一場を会計する。
    引数: key (tuple[str,str])、record (dict)、output (tuple)、run (dict)。
    返り値: tuple[dict,np.ndarray] の場会計と親組台帳。
    """
    orders, trades, curve, stats = output[:4]
    orders = np.asarray(orders, np.float64).reshape(-1, len(ORDER_COLUMNS))
    trades = np.asarray(trades, np.float64).reshape(-1, len(TRADE_COLUMNS))
    curve = np.asarray(curve, np.float64)
    stats = np.asarray(stats)
    spec = CONTRACTS[key[1]]; cap, value, fee = spec['cap'], spec['pointvalue'], spec['fee']
    times, bid, ask = record['time_s'], record['bid'], record['ask']
    assert curve.shape == times.shape and np.isfinite(curve).all(), (key, '全原板の清算時価が不足')
    assert len(stats) == len(STAT_COLUMNS) and np.all(stats[4:8] == 0), (key, '未返済又は未取消', stats)
    assert np.max(stats[:4], initial=0) <= cap, (key, '片方向上限超過', stats)
    assert np.isfinite(orders).all() and np.isfinite(trades).all()
    fill_indices = orders[:, 0].astype(np.int64); decision_indices = orders[:, 1].astype(np.int64)
    max_net = 0.
    if len(orders):
        causal_order = fill_indices >= decision_indices if run['delay'] == 0 else fill_indices > decision_indices
        assert (causal_order & (decision_indices >= 0) & (fill_indices < len(times))).all()
        np.testing.assert_array_equal(orders[:, 11], times[fill_indices])
        observed = orders[:, 9] == times[decision_indices]
        timed = ~observed
        if timed.any():
            assert (orders[timed, 7] == 6).all() and (orders[timed, 6] == 0).all()
            assert (orders[timed, 9] == record['limit'] - 60.).all()
            assert (times[decision_indices[timed]] < orders[timed, 9]).all()
            assert (orders[timed, 9] <= times[decision_indices[timed] + 1]).all()
        assert (orders[:, 10] >= orders[:, 9] + run['delay'] - 1e-8).all()
        assert (orders[:, 11] >= orders[:, 10] - 1e-8).all()
        assert np.isin(orders[:, 3], (-1., 1.)).all() and np.isin(orders[:, 6], (0., 1.)).all()
        np.testing.assert_allclose(orders[:, 8], np.floor(orders[:, 4] * fee + 1e-8), atol=1e-8, rtol=0)
        long_delta = np.where((orders[:, 6] == 1) & (orders[:, 3] == 1), orders[:, 4],
                              np.where((orders[:, 6] == 0) & (orders[:, 3] == -1), -orders[:, 4], 0.))
        short_delta = np.where((orders[:, 6] == 1) & (orders[:, 3] == -1), orders[:, 4],
                               np.where((orders[:, 6] == 0) & (orders[:, 3] == 1), -orders[:, 4], 0.))
        for balance in (np.cumsum(long_delta), np.cumsum(short_delta)):
            assert balance.min(initial=0) >= 0 and balance.max(initial=0) <= cap and balance[-1] == 0
        max_net = float(np.abs(np.cumsum(long_delta - short_delta)).max(initial=0))
    gross = float(trades[:, 9].sum()); fees = float(orders[:, 8].sum()); net = trades[:, 10]
    np.testing.assert_allclose(trades[:, 9], trades[:, 3] * trades[:, 4] * (trades[:, 6] - trades[:, 5]) * value, atol=1e-6, rtol=0)
    np.testing.assert_allclose(trades[:, 10], trades[:, 9] - trades[:, 7] - trades[:, 8], atol=1e-6, rtol=0)
    assert abs(fees - float(trades[:, 7:9].sum())) < 1e-6, (key, '注文料と決済脚の料金配分')
    total = float(net.sum())
    assert abs(total - (gross - fees)) < 1e-5 and abs(total - curve[-1]) < 1e-4, (key, '最終時価と会計')
    cycle_rows = []
    for cycle_id in np.unique(trades[:, 13].astype(np.int64)):
        ts = trades[trades[:, 13] == cycle_id]
        os = orders[orders[:, 14] == cycle_id]
        assert len(os) > 0
        first = int(ts[:, 1].min()); last = int(ts[:, 2].max())
        cfee = float(os[:, 8].sum()); cgross = float(ts[:, 9].sum()); cnet = float(ts[:, 10].sum())
        assert abs(cgross - cfee - cnet) < 1e-5, (key, cycle_id, '親組の全費用')
        cycle_rows.append([cycle_id, first, last, len(ts), cgross, cfee, cnet, float(ts[:, 4].sum())])
    cycles = np.asarray(cycle_rows, np.float64).reshape(-1, len(CYCLE_COLUMNS))
    cycle_net = cycles[:, 6]
    assert abs(float(cycle_net.sum()) - total) < 1e-5
    hold = float(np.sum(times[trades[:, 2].astype(np.int64)] - times[trades[:, 1].astype(np.int64)]))
    cycle_hold = float(np.sum(times[cycles[:, 2].astype(np.int64)] - times[cycles[:, 1].astype(np.int64)]))
    mids = (bid + ask) / 2.
    mid_gross = float(np.sum(trades[:, 3] * trades[:, 4] * value *
                            (mids[trades[:, 2].astype(np.int64)] - mids[trades[:, 1].astype(np.int64)])))
    spread = float(np.sum(orders[:, 3] * (orders[:, 5] - mids[fill_indices]) * orders[:, 4] * value))
    assert abs(mid_gross - gross - spread) < 1e-5, (key, '中値経路と全約定の気配差')
    decision_quotes = np.where(orders[:, 3] > 0, ask[decision_indices], bid[decision_indices])
    delayed_cost = float(np.sum(orders[:, 3] * (orders[:, 5] - decision_quotes) * orders[:, 4] * value))
    peak = np.maximum.accumulate(np.r_[0., curve])[1:]
    waits = orders[:, 11] - orders[:, 9]
    result = dict(session=key[0], symbol=key[1], profit=float(net[net > 0].sum()), loss=float(-net[net < 0].sum()),
        net=total, gross=gross, fees=fees, midpoint_gross=mid_gross,
        trades=len(trades), wins=int(np.sum(net > 0)), losses=int(np.sum(net < 0)), flats=int(np.sum(net == 0)),
        winning_lots=int(trades[net > 0, 4].sum()), losing_lots=int(trades[net < 0, 4].sum()), flat_lots=int(trades[net == 0, 4].sum()),
        cycle_profit=float(cycle_net[cycle_net > 0].sum()), cycle_loss=float(-cycle_net[cycle_net < 0].sum()), cycle_net=total,
        cycles=len(cycles), cycle_wins=int(np.sum(cycle_net > 0)), cycle_losses=int(np.sum(cycle_net < 0)), cycle_flats=int(np.sum(cycle_net == 0)),
        hold_seconds=hold, cycle_hold_seconds=cycle_hold, spread_drag=spread, decision_to_fill_cost=delayed_cost,
        drawdown=float(np.max(peak - curve)), curve_min=min(0., float(curve.min())), curve_max=max(0., float(curve.max())),
        max_trade_loss=max(0., -float(net.min(initial=0))), max_cycle_loss=max(0., -float(cycle_net.min(initial=0))),
        max_long=int(stats[0]), max_short=int(stats[1]), max_reserved_long=int(stats[2]), max_reserved_short=int(stats[3]),
        max_gross_lots=int(stats[11]), max_gross=int(stats[11]), max_net=int(max_net),
        cancellations=int(stats[8]), basket_stops=int(stats[12]), ties=int(stats[13]),
        orders=len(orders), entry_orders=int(np.sum(orders[:, 6] == 1)), exit_orders=int(np.sum(orders[:, 6] == 0)),
        order_wait_seconds=float(waits.sum()), max_order_wait_seconds=float(waits.max(initial=0)),
        reasons={str(int(reason)): int(np.sum(orders[:, 7] == reason)) for reason in np.unique(orders[:, 7])})
    return metrics(result), cycles


def aggregate(rows, symbol, sessions):
    """
    機能: 一商品の期間会計と場内・場間を通じた最大資産減少を集計する。
    引数: rows (list[dict])、symbol (str)、sessions (list[str])。
    返り値: dict。銘柄間の円額は合算しない。
    """
    rs = sorted([r for r in rows if r['symbol'] == symbol and r['session'] in sessions], key=lambda r: sessions.index(r['session']))
    a = {field: sum(r[field] for r in rs) for field in (*MONEY_FIELDS, *COUNT_FIELDS)}
    for field in MAX_FIELDS:
        a[field] = max((r[field] for r in rs), default=0.)
    a.update(sessions=len(rs), active_sessions=sum(r['trades'] > 0 for r in rs),
             winning_sessions=sum(r['net'] > 0 for r in rs), losing_sessions=sum(r['net'] < 0 for r in rs),
             no_trade_sessions=sum(r['trades'] == 0 for r in rs),
             traded_flat_sessions=sum(r['trades'] > 0 and r['net'] == 0 for r in rs),
             best_session=max((r['net'] for r in rs), default=0.), worst_session=min((r['net'] for r in rs), default=0.))
    a['losing_session_share'] = a['losing_sessions'] / a['active_sessions'] if a['active_sessions'] else None
    a['without_best_session'] = a['net'] - a['best_session']
    balance = peak = dd = 0.
    for r in rs:
        dd = max(dd, r['drawdown'], peak - balance - r['curve_min'])
        peak = max(peak, balance + r['curve_max'])
        balance += r['net']
    a['drawdown'] = dd
    a['reasons'] = {key: sum(r['reasons'].get(key, 0) for r in rs) for key in sorted({k for r in rs for k in r['reasons']})}
    return metrics(a)


# ----------------------------------------
def specification():
    """
    機能: 新損益前に会計・選抜・感度のルールを固定する。
    引数: なし。
    返り値: dict の固定仕様。
    """
    return dict(
        会計='profit/loss/tradesは決済脚、cycle_profit/cycle_loss/cyclesは新規から全玉終了までの親組。net=cycle_netを全場で照合。',
        料金='TOPIXmini41.8円/NK225micro11円×各注文枚数を1円未満切捨て。新規・返済に課金。',
        時価='curveは全原板行の両側即時返済気配・返済料控除後清算時価。原本曲線の指紋と正確なDDを保存する。',
        定時返済='場末理由6は既知のlimit−60秒に予約できる。decision_iはその時刻より前の最終観測行、decision_timeは定時。通常の価格条件発注はdecision_time=time_s[decision_i]。',
        主執行='ユーザーの訂正に従い、主検証は遅延0・判断当該行の売買気配で即時約定。0秒でも次の観測へ待つ旧仕様とは区別する。親約定後の子条件は次の観測から監視し、同値でも初回評価する。次サイクル・追加も次行以降とし、同一観測で無限に再入場しない。',
        費用分解='spread_dragは全注文の約定中値に対する売買差。slip感度では追加不利約定分も含む。decision_to_fill_costは判断時の同側気配からの変化であり、前者に重ねて差し引かない。',
        対象='既知30場を前16で選定し後14で確認。後14も未知データと呼ばない。',
        最低数='両商品で親組20以上、取引したセッション8以上。満たさない家族は採用不可の参考代表。',
        主3基準={
            '利益割合':'両商品の低い親組金額利益割合が最大。次に低い親組平均純益の上限呼値換算が最大、悪い側の負場率が最小。',
            '場の安定':'両商品の高い負場率が最小。次に低い親組金額利益割合が最大、低い親組平均純益の上限呼値換算が最大。負場率の分母は取引した場だけ。',
            '親組効率':'両商品の低い親組平均純益÷(方向別上限×呼値×円倍率)が最大。次に低い親組金額利益割合が最大、悪い側の負場率が最小。'},
        家族代表='12家族ごとに主の利益割合基準で1条件を前16だけから固定。',
        同点='最後まで同点ならIDの昇順。重複代表を別の独立成功と数えず、次順位への差替えをしない。',
        黒字条件='代表選抜は順位付け。両商品で親組20・活動8を満たし双方net>0の場合だけ前半共通黒字候補。将来採用の保証ではない。',
        非活動='無取引を勝ちに数えない。十分な活動条件が存在しない集合では参考代表として示す。',
        最終='主3と家族12の一意unionだけ全30を再生し、後半で選び直さない。',
        感度='家族0の固定代表を種0〜19で比較。再選抜しない。0/1/5秒の遅延順位付けは行わない。判断後5秒以内の最悪約定は後続の別診断とし、5秒後の一点での約定と混同しない。',
        乱数='各口座へ同じ指定seedを渡す。seed0は基準。良かった種だけを採らず分布を示す。',
        注文イベント='code1新規送信、2返済送信、3IOC失効、4新規約定、5返済約定。原板の同一行内でも記録の追加順を保持する。',
        contracts=CONTRACTS, orders=ORDER_COLUMNS, trades=TRADE_COLUMNS, cycles=CYCLE_COLUMNS, stats=STAT_COLUMNS, events=EVENT_COLUMNS)


def freeze():
    """
    機能: 根担当が確定したcatalogとエンジンを会計選抜仕様に結び付ける。
    引数: なし。
    返り値: dict の固定記録。既存固定は上書きしない。
    """
    catalog_module = importlib.import_module('catalog')
    catalog = catalog_module.catalog()
    assert len(catalog) == 288 and len({c['id'] for c in catalog}) == 288
    assert {c['family'] for c in catalog} == set(range(12))
    assert {c['width_ticks'] for c in catalog} == {1, 2, 4, 8, 16, 32}
    assert {c['variant'] for c in catalog} == set(range(4))
    source = read(data.PREPARED / '価格入力の仕様.json')
    value = dict(catalog=catalog, 全30=source['全30'], 前16=source['前16'], 後14=source['後14'],
                 specification=specification(), catalog_specification=catalog_module.specification(),
                 code_SHA256={name: data.digest(HERE / name) for name in ('data.py', 'engine.py', 'catalog.py', 'research.py')},
                 input_SHA256=read(data.PREPARED / '価格入力の照合.json')['出力SHA256'])
    target = FIXED
    if target.exists():
        assert read(target) == value, '固定済み仕様と異なります。変更を無言で上書きしません'
    else:
        save_json(target, value)
    return value


def run_condition(config, inputs, sessions, fixed, base, delay=0., seed=0, slip_ticks=0.):
    """
    機能: 固定1条件を指定セッションで逐次実行し、場会計と全注文台帳を保存する。
    引数: config/inputs/fixed (dict)、sessions (list[str])、base (Path)、delay/slip_ticks (float)、seed (int)。
    返り値: dict の条件会計。既存結果は実行情報・指紋が同じ時だけ再利用する。
    """
    run = dict(delay=float(delay), seed=int(seed), slip_ticks=float(slip_ticks), sessions=sessions,
               input_SHA256=fixed['input_SHA256'], code_SHA256=fixed['code_SHA256'])
    target = base / 'results' / (config['id'] + '.json')
    ledger_path = base / 'ledgers' / (config['id'] + '.pkl')
    if target.exists():
        result = read(target)
        assert result['config'] == config and result['run'] == run and ledger_path.exists()
        return result
    engine = importlib.import_module('engine')
    rows = []; ledgers = {}; started = time.monotonic()
    for session in sessions:
        for symbol in SYMBOLS:
            key = (session, symbol); r = inputs[key]; terms = CONTRACTS[symbol]
            out = engine.run(data.as_tuple(r), config['family'], config['width_ticks'], config['variant'],
                             terms['cap'], terms['pointvalue'], terms['fee'], delay, seed, slip_ticks)
            a, cycles = account(key, r, out, run)
            rows.append(a)
            ledgers[key] = dict(orders=out[0], trades=out[1], cycles=cycles, stats=out[3],
                                curve_hash=hashlib.sha256(np.asarray(out[2]).tobytes()).hexdigest())
            if 'final' in base.parts:
                assert len(out) == 5 and out[4].shape[1] == len(EVENT_COLUMNS)
                ledgers[key]['events'] = out[4]
    periods = {name: {s: aggregate(rows, s, selected) for s in SYMBOLS} for name, selected in
               [('前16', [s for s in sessions if s in fixed['前16']]), ('後14', [s for s in sessions if s in fixed['後14']]), ('対象', sessions)]}
    result = dict(config=config, run=run, rows=rows, periods=periods, elapsed_seconds=time.monotonic() - started)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ledger_path.with_suffix('.pkl.tmp')
    with temporary.open('wb') as stream:
        pickle.dump(ledgers, stream, protocol=5)
    temporary.replace(ledger_path)
    save_json(target, result)
    return result


def score(result, kind):
    """
    機能: 前半の両商品に共通する無次元評価値を作る。
    引数: result (dict)、kind (str)。
    返り値: tuple の大きいほど良い順位。銘柄円額の合算は行わない。
    """
    accounts = result['periods']['前16']
    sufficient = all(accounts[s]['cycles'] >= 20 and accounts[s]['active_sessions'] >= 8 for s in SYMBOLS)
    shares = [accounts[s]['cycle_profit_share'] if accounts[s]['cycle_profit_share'] is not None else -1. for s in SYMBOLS]
    negative = [accounts[s]['losing_session_share'] if accounts[s]['losing_session_share'] is not None else 1. for s in SYMBOLS]
    efficiency = [accounts[s]['cycle_average_net'] / (CONTRACTS[s]['cap'] * CONTRACTS[s]['pointvalue'] * (.5 if s == 'TOPIX' else 10.))
                  if accounts[s]['cycle_average_net'] is not None else -1e100 for s in SYMBOLS]
    share, bad, effic = min(shares), max(negative), min(efficiency)
    if kind == '場の安定':
        return sufficient, -bad, share, effic
    if kind == '親組効率':
        return sufficient, effic, share, -bad
    return sufficient, share, effic, -bad


def choose(results, kind):
    """
    機能: 固定ルールで同点ID順も含めて代表を一つ選ぶ。
    引数: results (list[dict])、kind (str)。
    返り値: dict の代表と活動数の資格判定。
    """
    assert results
    ordered = sorted(results, key=lambda r: r['config']['id'])
    selected = sorted(ordered, key=lambda r: score(r, kind), reverse=True)[0]
    adequate = bool(score(selected, kind)[0])
    accounts = selected['periods']['前16']
    return dict(id=selected['config']['id'], family=selected['config']['family'], criterion=kind,
                sufficient=adequate, common_positive=adequate and all(accounts[s]['net'] > 0 for s in SYMBOLS),
                score=list(score(selected, kind)), config=selected['config'], 前16=accounts,
                status='前半共通黒字候補' if adequate and all(accounts[s]['net'] > 0 for s in SYMBOLS) else
                       '活動条件を満たす比較代表・両商品黒字は未達' if adequate else '活動不足の参考代表・採用不可')


def select(fixed):
    """
    機能: 前半288条件だけから主3と家族12を固定する。
    引数: fixed (dict)。
    返り値: dict の選抜記録。後半や感度結果を読まない。
    """
    results = [read(HERE / 'train/results' / (c['id'] + '.json')) for c in fixed['catalog']]
    assert all(r['run']['sessions'] == fixed['前16'] and r['run']['delay'] == 0 and r['run']['seed'] == 0 and r['run']['slip_ticks'] == 0 for r in results)
    primary = [choose(results, kind) for kind in ('利益割合', '場の安定', '親組効率')]
    families = [dict(choose([r for r in results if r['config']['family'] == family], '利益割合'), family=family) for family in range(12)]
    selected = sorted({r['id'] for r in primary + families})
    value = dict(primary=primary, families=families, selected=selected,
                 primary_unique=len({r['id'] for r in primary}), selected_unique=len(selected),
                 rule=fixed['specification'], 前16=fixed['前16'], 後14を参照した選び直し=False,
                 元結果SHA256={r['config']['id']: data.digest(HERE / 'train/results' / (r['config']['id'] + '.json')) for r in results})
    target = HERE / '前半選定.json'
    if target.exists():
        assert read(target) == value, '前半固定代表が変化しています'
    else:
        save_json(target, value)
    return value


def batch(configs, inputs, sessions, fixed, base, workers, delay=0., seed=0, slip_ticks=0.):
    """
    機能: Numbaの計算を共有入力に対する少数スレッドで並行実行する。
    引数: configs (list[dict])、inputs/fixed (dict)、sessions (list[str])、base (Path)、workers (int)、delay/slip_ticks (float)、seed (int)。
    返り値: None。各条件の損益は表示せず完了数だけ出力する。
    """
    # 初回コンパイルの競合を避け、最初の条件のみ先に完了させる。
    if not configs:
        return
    run_condition(configs[0], inputs, sessions, fixed, base, delay, seed, slip_ticks)
    print(f'{base.relative_to(HERE)} 1/{len(configs)} 完了', flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(run_condition, c, inputs, sessions, fixed, base, delay, seed, slip_ticks): c for c in configs[1:]}
        for i, future in enumerate(as_completed(pending), start=2):
            future.result()
            print(f'{base.relative_to(HERE)} {i}/{len(configs)} 完了', flush=True)


def summarize_seeds(config):
    """
    機能: 固定した無作為手法の全20種を省略せず分布へまとめる。
    引数: config (dict) は家族0の前半固定代表。
    返り値: dict。最良seedを新たな代表に選ばない。
    """
    results = [read(HERE / f'sensitivity/seed{seed:02d}/results' / (config['id'] + '.json')) for seed in range(20)]
    rows = [dict(seed=r['run']['seed'], metrics=r['periods']['対象']) for r in results]
    by_symbol = {}
    for symbol in SYMBOLS:
        nets = np.array([r['metrics'][symbol]['net'] for r in rows])
        by_symbol[symbol] = dict(seeds=20, mean_net=float(nets.mean()), median_net=float(np.median(nets)),
                                 worst_net=float(nets.min()), best_net=float(nets.max()),
                                 profitable_seeds=int(np.sum(nets > 0)), profitable_share=float(np.mean(nets > 0)))
    value = dict(config=config, rows=rows, symbols=by_symbol,
                 both_profitable_seeds=sum(all(r['metrics'][s]['net'] > 0 for s in SYMBOLS) for r in rows),
                 both_profitable_share=sum(all(r['metrics'][s]['net'] > 0 for s in SYMBOLS) for r in rows) / 20.,
                 selection='家族0の前半固定代表だけを種0〜19で比較。最良の種による採用・条件の選び直しは行わない。',
                 独立性='同じ30場に乱数だけを変えた感度であり、20個の独立した相場を観測した証拠ではない。')
    save_json(HERE / 'sensitivity/無作為20種の比較.json', value)
    return value


# ----------------------------------------
def main():
    """
    機能: 固定、前半実行・選抜、固定代表の全30場、感度を段階別に実行する。
    引数: CLIの--phase、--workers、--freeze、--select-only等。
    返り値: None。全条件の後半探索を行わない。
    """
    parser = argparse.ArgumentParser(description='注文条件だけの固定比較と会計')
    parser.add_argument('--phase', choices=('train', 'final', 'sensitivity'))
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--select-only', action='store_true')
    args = parser.parse_args()
    if args.freeze:
        freeze()
        if not args.phase:
            print('会計・選抜・入力とコードを事前固定しました')
            return
    fixed = read(FIXED)
    for name, expected in fixed['code_SHA256'].items():
        assert data.digest(HERE / name) == expected, (name, 'コードが事前固定から変化')
    if args.select_only:
        select(fixed)
        return
    assert args.phase is not None, '--phase を指定してください'
    assert 1 <= args.workers <= 16
    assert data.digest(data.PREPARED / 'inputs.pkl') == fixed['input_SHA256']
    inputs = data.load_data(verify=False)
    if args.phase == 'train':
        batch(fixed['catalog'], inputs, fixed['前16'], fixed, HERE / 'train', args.workers)
        select(fixed)
    else:
        selection = read(HERE / '前半選定.json')
        configs = [c for c in fixed['catalog'] if c['id'] in selection['selected']]
        if args.phase == 'final':
            batch(configs, inputs, fixed['全30'], fixed, HERE / 'final/delay0', args.workers)
        else:
            coin = next(r['config'] for r in selection['families'] if r['family'] == 0)
            for seed in range(20):
                batch([coin], inputs, fixed['全30'], fixed, HERE / f'sensitivity/seed{seed:02d}', args.workers, seed=seed)
            summarize_seeds(coin)


if __name__ == '__main__':
    main()
