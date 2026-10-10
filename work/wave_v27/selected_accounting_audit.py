"""選抜済み条件の全玉会計を、注文・元建玉から独立に再構成する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import socket
import time
import urllib.request

import numpy as np

import hierarchy_runner as runner
import hierarchy_signals as signals

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v23'
MULT = {'TOPIX': 1000., 'NK225': 10.}
CAP = {'TOPIX': 10, 'NK225': 20}


def reject_network(*args: object, **kwargs: object) -> None:
    """機能: 監査中の外部通信を明示的に拒否する。

    引数: args/kwargs (object) は任意の通信引数。返り値: なし (None)。必ず例外を送出する。
    """
    raise AssertionError('この監査では外部通信を許可しません')


def close(left: object, right: object, label: str) -> None:
    """機能: 金額・価格の浮動小数誤差だけを許容して比較する。

    引数: left/right (object) は比較値、label (str) は比較名。返り値: なし (None)。
    """
    np.testing.assert_allclose(left, right, atol=1e-6, rtol=0, err_msg=label)


def integer(value: float, label: str) -> int:
    """機能: 数量・行番号が厳密な整数であることを検査する。

    引数: value (float)、label (str)。返り値: 整数値 (int)。
    """
    assert np.isfinite(value) and value == round(value), label
    return int(value)


def reconstruct(ready: dict, result: dict, symbol: str, closed: bool = True) -> tuple[dict, dict]:
    """機能: 約定注文から現金・在庫を、元建玉と返済から実現損益を再構成する。

    引数: ready/result (dict)、symbol (str)、closed (bool) は全返済を要求するか。
    返り値: 独立集計と独立時系列 (tuple[dict,dict])。エンジンの損益欄は比較先にしか使わない。
    """
    prices, times = ready['last'], ready['time_s']
    n = len(prices)
    assert n > 1 and np.isfinite(prices).all() and (prices > 0).all()
    assert np.all(np.diff(times) >= 0)
    orders, trades, cycles = (result[k] for k in ('orders', 'trades', 'cycles'))
    assert orders.shape[1] == 8 and trades.shape[1] == 11 and cycles.shape[1] == 10
    cash_change, long_change, short_change, realized_change = (np.zeros(n) for _ in range(4))
    legs, pnl, quantities, campaign_pnl = [], [], [], {}
    campaigns, reasons = {}, {}
    long_qty = short_qty = 0
    close_index, last_fill = 0, -1
    # ----------------------------------------
    # 一枚でも元建玉の数量を超えて返済すれば失敗する。損失玉も同じ経路で計上する。
    for order in orders:
        row, source, campaign, side, qty, price, reason, opening = order
        row, source, campaign, side, qty, reason, opening = [integer(v, '注文の整数欄') for v in
                                                            (row, source, campaign, side, qty, reason, opening)]
        assert 0 <= source < row < n and row >= last_fill
        assert side in (-1, 1) and qty > 0 and opening in (0, 1)
        assert np.isfinite(price) and price > 0 and campaign >= 0
        assert times[row] >= ready['start'] and times[row] <= ready['limit'] + 300
        last_fill = row
        cash_change[row] -= side * qty * price
        campaigns.setdefault(campaign, []).append(row)
        reasons[campaign] = reason
        if opening:
            assert reason in (20, 21, 22, 23)
            legs.append({'side': side, 'qty': qty, 'remaining': qty, 'price': price,
                         'row': row, 'campaign': campaign})
            if side == 1:
                long_qty += qty
                long_change[row] += qty
            else:
                short_qty += qty
                short_change[row] += qty
        else:
            assert close_index < len(trades), '返済注文に対応する明細がない'
            trade = trades[close_index]
            close_index += 1
            leg_id = integer(trade[1], '元建玉番号')
            assert 0 <= leg_id < len(legs)
            leg = legs[leg_id]
            assert leg['remaining'] >= qty and leg['row'] < row
            close(trade[[0, 2, 3, 4, 5, 6, 7, 9]],
                  [campaign, -side, qty, leg['price'], price, leg['row'], row, reason], '注文と元建玉の照合')
            assert leg['side'] == -side and leg['campaign'] == campaign
            assert integer(trade[8], '主玉・カバー区分') in (0, 1)
            value = leg['side'] * qty * (price - leg['price'])
            close(trade[10], value, '返済損益を建値・枚数から再計算')
            pnl.append(value)
            quantities.append(qty)
            campaign_pnl[campaign] = campaign_pnl.get(campaign, 0.) + value
            realized_change[row] += value
            leg['remaining'] -= qty
            if leg['side'] == 1:
                long_qty -= qty
                long_change[row] -= qty
            else:
                short_qty -= qty
                short_change[row] -= qty
        assert 0 <= long_qty <= CAP[symbol] and 0 <= short_qty <= CAP[symbol], '注文途中の保有上限'
    assert close_index == len(trades), '注文が存在しない返済明細'
    if closed:
        assert long_qty == short_qty == 0 and all(x['remaining'] == 0 for x in legs)
    # ----------------------------------------
    # 時価曲線は約定金額と現在価格だけで計算し、エンジン内の実現損益を使わない。
    cash = np.cumsum(cash_change)
    longs, shorts = np.cumsum(long_change), np.cumsum(short_change)
    net = longs - shorts
    equity = cash + net * prices
    realized = np.cumsum(realized_change)
    high = np.maximum.accumulate(np.maximum(0., equity))
    drawdown = np.maximum.accumulate(high - equity)
    curve = result['curve']
    assert curve.shape == (n, 8), 'detail=True の曲線が必要'
    independent = np.column_stack([equity, realized, longs, shorts, drawdown, cash, net])
    close(curve[:, :7], independent, '全観測行の現金・保有・時価・最大下落')
    close(result['stats'][:6], [realized[-1], drawdown[-1], max(longs), max(shorts),
                               max(longs + shorts), max(abs(net))], '集計検算')
    close(result['stats'][7:10], [min(0., min(equity)), max(0., max(equity)), long_qty + short_qty], '残玉と最大最小時価')
    completed = []
    for cycle in cycles:
        campaign = integer(cycle[0], '組番号')
        rows = campaigns[campaign]
        first, last = min(rows), max(rows)
        assert all(x['remaining'] == 0 for x in legs if x['campaign'] == campaign)
        close(cycle[[1, 2, 3, 6, 7]], [first, last, campaign_pnl.get(campaign, 0.),
                    max((longs + shorts)[first:last + 1]), max(abs(net[first:last + 1]))], '組単位の損益と最大枚数')
        assert cycle[4] > 0 and cycle[5] > 0
        completed.append(campaign)
    assert len(set(completed)) == len(completed)
    if closed:
        assert set(completed) == set(campaigns), '全玉返済済みの組が集計から脱落'
        close(cash[-1], sum(pnl), '全返済後の現金と全損益')
    at_limit = np.flatnonzero(times >= ready['limit'])
    if closed and len(at_limit) > 1:
        after = int(at_limit[0]) + 1
        assert not (longs[after:] + shorts[after:]).any(), '場末判断の次観測以降に持越し'
    values, units = np.asarray(pnl) * MULT[symbol], np.asarray(quantities)
    wins, losses = values > 1e-6, values < -1e-6
    cv = np.asarray([campaign_pnl[x] for x in completed]) * MULT[symbol]
    summary = {'symbol': symbol, 'session': ready.get('session', '合成'),
               'gross_profit_yen': float(values[wins].sum()), 'gross_loss_yen': float(-values[losses].sum()),
               'net_yen': float(values.sum()), 'profit_units': int(units[wins].sum()),
               'loss_units': int(units[losses].sum()), 'zero_units': int(units[~(wins | losses)].sum()),
               'closed_units': int(units.sum()), 'max_long': int(max(longs)), 'max_short': int(max(shorts)),
               'drawdown_yen': float(drawdown[-1] * MULT[symbol]),
               'min_equity_yen': float(min(0., min(equity)) * MULT[symbol]),
               'max_equity_yen': float(max(0., max(equity)) * MULT[symbol]),
               'cycles': len(cycles), 'cycle_wins': int((cv > 0).sum()), 'cycle_losses': int((cv < 0).sum()),
               'cycle_profit_yen': float(cv[cv > 0].sum()), 'cycle_loss_yen': float(-cv[cv < 0].sum()),
               '新規注文数': len(legs), '返済明細数': len(trades), '検算した観測行数': n,
               '最終残玉': int(long_qty + short_qty), '買い返済枚数': int(sum(t[3] for t in trades if t[2] > 0)),
               '売り返済枚数': int(sum(t[3] for t in trades if t[2] < 0))}
    return summary, {'equity': equity, 'realized': realized, 'cash': cash, 'long': longs, 'short': shorts}


def clipped(ready: dict, count: int) -> dict:
    """機能: 元の場末時刻を変えず、観測列だけを途中で切る。

    引数: ready (dict)、count (int)。返り値: 入力の接頭辞 (dict)。
    """
    n = len(ready['last'])
    return {k: v[:count] if isinstance(v, np.ndarray) and v.ndim and len(v) == n else v
            for k, v in ready.items()}


def prefix_equal(left: dict, right: dict, count: int) -> None:
    """機能: 途中終了しても、それ以前の約定・返済・時価が変わらないことを確認する。

    引数: left/right (dict) はエンジン出力、count (int) は比較行数。返り値: なし (None)。
    """
    for key, row_column in [('orders', 0), ('trades', 7), ('cycles', 2)]:
        original = left[key][left[key][:, row_column] < count]
        altered = right[key][right[key][:, row_column] < count]
        close(original, altered, '未来変更前の' + key)
    close(left['curve'][:count], right['curve'][:count], '未来変更前の時価曲線')


def engine_causality(ready: dict, direction: np.ndarray, cfg: dict, baseline: dict) -> dict:
    """機能: 原本行の途中切断と将来価格・ATR・方向の改変を別々に検査する。

    引数: ready/cfg/baseline (dict)、direction (ndarray)。返り値: 検査回数 (dict)。
    """
    for fraction in (.37, .73):
        count = max(2, int(len(direction) * fraction))
        short = runner.engine.run(clipped(ready, count), direction[:count], cfg, detail=True)
        prefix_equal(baseline, short, count)
        altered = dict(ready)
        altered['last'] = ready['last'].copy()
        altered['last'][count:] += 3 * ready['atr'][count:]
        altered['atr'] = ready['atr'].copy()
        altered['atr'][count:] *= 1.7
        new_direction = direction.copy()
        new_direction[count:] *= -1
        answer = runner.engine.run(altered, new_direction, cfg, detail=True)
        prefix_equal(baseline, answer, count)
    return {'未来切断': 2, '未来価格ATR方向改変': 2}


def reflection(ready: dict, direction: np.ndarray, cfg: dict, baseline: dict, symbol: str) -> None:
    """機能: 呼値に整合する鏡映価格と逆方向信号で、注文器の売買対称性を調べる。

    引数: ready/cfg/baseline (dict)、direction (ndarray)、symbol (str)。返り値: なし (None)。
    信号計算自体の反射は別の全96条件監査で実施済み。ここでは建玉管理だけを検査する。
    """
    offset = 2 * np.ceil(float(max(ready['last'])) / ready['tick']) * ready['tick']
    reflected = dict(ready, last=offset - ready['last'])
    answer = runner.engine.run(reflected, -direction, cfg, detail=True)
    reconstruct(reflected, answer, symbol)
    left, right = baseline['trades'], answer['trades']
    close(left[:, [0, 1, 3, 6, 7, 8, 9, 10]], right[:, [0, 1, 3, 6, 7, 8, 9, 10]], '鏡映返済行と損益')
    close(left[:, 2], -right[:, 2], '鏡映建玉方向')
    close(left[:, 4:6], offset - right[:, 4:6], '鏡映新規と返済価格')
    left, right = baseline['orders'], answer['orders']
    close(left[:, [0, 1, 2, 4, 6, 7]], right[:, [0, 1, 2, 4, 6, 7]], '鏡映注文行と枚数')
    close(left[:, 3], -right[:, 3], '鏡映注文方向')
    close(left[:, 5], offset - right[:, 5], '鏡映約定価格')
    close(baseline['curve'][:, [0, 1, 4]], answer['curve'][:, [0, 1, 4]], '鏡映時価損益と下落')
    close(baseline['curve'][:, [2, 3]], answer['curve'][:, [3, 2]], '鏡映保有枚数')


def self_test() -> dict:
    """機能: 手計算可能な両建て・部分返済台帳と、その改ざんの検出を確認する。

    引数: なし。返り値: 合成検査の記録 (dict)。新候補の成績は参照しない。
    """
    ready = {'last': np.array([100., 100., 99., 101., 98., 102., 102., 102.]),
             'time_s': np.arange(8, dtype=float), 'start': 0., 'limit': 6., 'tick': 1.,
             'atr': np.ones(8), 'us_open': np.inf}
    orders = np.array([[1, 0, 0, 1, 2, 100, 20, 1], [2, 1, 0, -1, 1, 99, 21, 1],
                       [3, 2, 0, -1, 1, 101, 7, 0], [4, 3, 0, 1, 1, 98, 3, 0],
                       [5, 4, 0, -1, 1, 102, 2, 0]], dtype=float)
    trades = np.array([[0, 0, 1, 1, 100, 101, 1, 3, 0, 7, 1],
                       [0, 1, -1, 1, 99, 98, 2, 4, 1, 3, 1],
                       [0, 0, 1, 1, 100, 102, 1, 5, 0, 2, 2]], dtype=float)
    curve = np.array([[0, 0, 0, 0, 0, 0, 0, -1], [0, 0, 2, 0, 0, -200, 2, 0],
                      [-2, 0, 2, 1, 2, -101, 1, 0], [0, 1, 1, 1, 2, 0, 0, 0],
                      [0, 2, 1, 0, 2, -98, 1, 0], [4, 4, 0, 0, 2, 4, 0, 0],
                      [4, 4, 0, 0, 2, 4, 0, 0], [4, 4, 0, 0, 2, 4, 0, 0]], dtype=float)
    result = {'orders': orders, 'trades': trades, 'curve': curve,
              'cycles': np.array([[0, 1, 5, 4, 2, 1, 3, 2, 1, 2]], dtype=float),
              'stats': np.array([4, 2, 2, 1, 3, 2, 0, -2, 4, 0, 0], dtype=float)}
    summary, _ = reconstruct(ready, result, 'TOPIX')
    assert summary['net_yen'] == 4000 and summary['profit_units'] == 3 and summary['max_short'] == 1
    detected = []
    for name, key, row, col, value in [('損益の改ざん', 'trades', 0, 10, 5.),
                                     ('同じ行の先取り約定', 'orders', 0, 1, 1.),
                                     ('返済枚数の水増し', 'trades', 0, 3, 2.),
                                     ('現金曲線の改ざん', 'curve', 2, 5, -100.),
                                     ('注文のない建玉返済', 'trades', 0, 1, 1.)]:
        changed = {k: v.copy() for k, v in result.items()}
        changed[key][row, col] = value
        try:
            reconstruct(ready, changed, 'TOPIX')
        except (AssertionError, IndexError):
            detected.append(name)
        else:
            raise AssertionError('改ざんを検出できません: ' + name)
    # ----------------------------------------
    # 単純な上昇・下落の両方を実エンジンで動かし、監査器のエンジン接続も確認する。
    configured = next(x for x in runner.managers.manager_catalog() if x['id'] == 'G18')
    cfg = runner.managers.make_config(configured, 'TOPIX', ready)
    cfg.update(warmup_min=0., entry_cutoff_min=0., cooldown_min=0.)
    direction = np.ones(8, dtype=np.int8)
    actual = runner.engine.run(ready, direction, cfg, detail=True)
    reconstruct(ready, actual, 'TOPIX')
    reflection(ready, direction, cfg, actual, 'TOPIX')
    engine_causality(ready, direction, cfg, actual)
    return {'手計算両建て部分返済': True, '手計算収支円': 4000,
            '改ざん検出': detected, '合成エンジン反射と未来改変': True}


def audit(identifier: str, fixed: dict, inputs: dict, features: dict) -> dict:
    """機能: 指定された一候補だけを全26区間で独立監査する。

    引数: identifier (str)、fixed/inputs/features (dict)。返り値: 監査結果 (dict)。順位付けはしない。
    """
    signal_id, manager_id = identifier.split('__')
    spec = next(x for x in fixed['signals'] if x['id'] == signal_id)
    management = next(x for x in fixed['managers'] if x['id'] == manager_id)
    stored = next(x for x in runner.read(HERE / 'sessions' / f'{signal_id}.json.gz') if x['id'] == identifier)
    stored_summary = next(x for x in runner.read(HERE / 'summaries' / f'{signal_id}.json')['candidates'] if x['id'] == identifier)
    saved_directions = np.load(HERE / 'directions' / f'{signal_id}.npz')
    signals.clear_cache()
    full = signals.build(spec, inputs, features)
    direction_prefixes = 0
    for fraction in (.37, .73):
        cutoff = {}
        for session in {key[0] for key in inputs}:
            pair = [r for key, r in inputs.items() if key[0] == session]
            start, end = max(r['start'] for r in pair), min(r['time_s'][-1] for r in pair)
            cutoff[session] = start + fraction * (end - start)
        partial = {key: clipped(r, int(np.searchsorted(r['time_s'], cutoff[key[0]], side='right')))
                   for key, r in inputs.items()}
        signals.clear_cache()
        directions = signals.build(spec, partial, features)
        for key in inputs:
            np.testing.assert_array_equal(full[key][:len(directions[key])], directions[key])
            direction_prefixes += 1
    rows, hasher, series = [], hashlib.sha256(), {}
    for key, ready in inputs.items():
        session, symbol = key
        np.testing.assert_array_equal(full[key], saved_directions[f'{session}|{symbol}'])
        cfg = runner.managers.make_config(management, symbol, ready)
        result = runner.engine.run(ready, full[key], cfg, detail=True)
        hasher.update(str(key).encode())
        hasher.update(result['trades'].tobytes())
        row, values = reconstruct(ready, result, symbol)
        row['session'] = session
        expected = next(x for x in stored['rows'] if x['session'] == session and x['symbol'] == symbol)
        for name in set(row) & set(expected):
            if isinstance(row[name], (float, int)):
                close(row[name], expected[name], '保存済みセッション表の' + name)
        row['因果性検査'] = engine_causality(ready, full[key], cfg, result)
        reflection(ready, full[key], cfg, result, symbol)
        row['買売反射一致'] = True
        rows.append(row)
        series[key] = values['equity']
        print(f'{identifier} {session} {symbol} 会計・未来改変・反射一致', flush=True)
    assert hasher.hexdigest() == stored_summary['ledger_hash'], '探索保存時の返済台帳との不一致'
    aggregate = {}
    for symbol in MULT:
        selected = [r for r in rows if r['symbol'] == symbol]
        fields = ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units',
                  'zero_units', 'closed_units', 'cycles', 'cycle_wins', 'cycle_losses',
                  'cycle_profit_yen', 'cycle_loss_yen']
        totals = {f: sum(r[f] for r in selected) for f in fields}
        offset, high, dd = 0., 0., 0.
        for key in sorted(k for k in inputs if k[1] == symbol):
            equity = series[key] * MULT[symbol] + offset
            peaks = np.maximum.accumulate(np.maximum(high, equity))
            dd = max(dd, float(max(peaks - equity)))
            high = float(peaks[-1])
            offset = float(equity[-1])
        totals['drawdown_yen'] = dd
        totals['money_ratio'] = totals['gross_profit_yen'] / totals['gross_loss_yen'] if totals['gross_loss_yen'] else None
        totals['average_unit_payoff'] = ((totals['gross_profit_yen'] / totals['profit_units']) /
                                        (totals['gross_loss_yen'] / totals['loss_units'])) if totals['profit_units'] and totals['loss_units'] else None
        for name, value in totals.items():
            if value is not None:
                close(value, stored_summary['symbols'][symbol][name], '保存済み期間表の' + name)
        aggregate[symbol] = totals
    return {'id': identifier, '台帳SHA256一致': hasher.hexdigest(), '方向再生成一致': len(inputs),
            '方向の未来切断一致': direction_prefixes, 'sessions': rows, 'symbols': aggregate}


def main() -> None:
    """機能: 合成試験、または親から指定された候補の会計監査を実行して保存する。

    引数: --ids (list[str]) は明示指定候補、--self-test (bool) は合成だけ。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--ids', nargs='+', default=[])
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    assert args.self_test or args.ids, '未選抜候補は自動選択しません。--ids を明示してください'
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    urllib.request.OpenerDirector.open = reject_network
    began = time.perf_counter()
    synthetic = self_test()
    if args.self_test:
        runner.save(HERE / 'selected_accounting_self_test.json', synthetic)
        print(json.dumps(synthetic, ensure_ascii=False), flush=True)
        return
    fixed = runner.read(HERE / '探索条件の固定.json')
    before = {relative: runner.digest(HERE.parent / relative) for relative in fixed['SHA256']}
    assert before == fixed['SHA256']
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    features = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    assert len(inputs) == 26 and len({k[0] for k in inputs}) == 13
    candle_paths = [HERE.parents[1] / 'candle_1min' / symbol / (session + '.csv')
                    for session, symbol in inputs]
    candle_before = {p.relative_to(HERE.parents[1]).as_posix(): runner.digest(p) for p in candle_paths}
    results = [audit(identifier, fixed, inputs, features) for identifier in args.ids]
    after = {relative: runner.digest(HERE.parent / relative) for relative in before}
    assert before == after, '凍結された入力またはコードの変更'
    assert candle_before == {p.relative_to(HERE.parents[1]).as_posix(): runner.digest(p) for p in candle_paths}, '１分足原本の変更'
    record = {'API取得回数': 0, '通信拒否': True, '選抜条件の追加変更': False,
              '会計定義': '約定注文から現金と買売在庫、元建玉から全返済損益を再構成。利益玉だけの除外なし。',
              '先読み検査': '全26区間を37％/73％で切断。信号は再生成、注文器は未来切断と未来価格ATR方向変更。',
              '方向検査': '選択された注文管理について全26区間の鏡映価格・逆方向信号を照合。',
              '限界': '会計実装と因果性の検査であり、将来利益を証明しない。費用０・指定約定の主前提を維持。',
              '合成試験': synthetic, '候補': results, '固定ファイル不変': True,
              '確定１分足原本26ファイルSHA256': candle_before,
              '監査コードSHA256': runner.digest(Path(__file__)), '実行秒': time.perf_counter() - began}
    runner.save(HERE / 'selected_accounting_audit.json', record)
    text = ['# 選抜候補の独立会計監査', '', '約定注文から現金・保有を、元建玉と全返済から損益を再計算しました。',
            '選抜基準は変更していません。費用０・指定価格約定を維持し、現在データ取得は０回です。', '',
            '| 手法 | 銘柄 | 利益円 | 損失円 | 収支円 | 利益枚数 | 損失枚数 |',
            '|---|---|---:|---:|---:|---:|---:|']
    for item in results:
        for symbol, row in item['symbols'].items():
            text.append(f"| {item['id']} | {symbol} | {row['gross_profit_yen']:,.0f} | {row['gross_loss_yen']:,.0f} | {row['net_yen']:,.0f} | {row['profit_units']} | {row['loss_units']} |")
    text += ['', '全観測行の時価・含み損を含む最大下落、買売それぞれの上限、場末の全返済、前行以前の発注、保存表・台帳を照合しました。',
             '各候補26区間すべてで、未来切断２点・未来価格等の改変２点・買売反射を確認しました。',
             '信号自体の未来足OHLC／出来高改変と左右反射は、同じ凍結信号に対する hierarchy_signal_audit.json の全96条件監査が補完します。',
             'これらは実装検査です。既知期間で選抜した手法の将来利益を保証するものではありません。']
    (HERE / 'selected_accounting_audit.md').write_text('\n'.join(text) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
