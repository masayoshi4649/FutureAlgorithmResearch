"""元返済の価格・数量から縮小版の全行時価と枚数を独立再構成する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SOURCE = ROOT / 'work' / 'wave_v17'
METHODS = ['M3_逆_A03', 'M3_逆_A00', 'M2_逆_A00', 'M2_逆_A01']
SESSIONS = [f'2026-09-{day:02d}_{part}' for day in range(21, 26) for part in ['Day', 'Night']]
MULTIPLIERS = {'TOPIX': 1000., 'NK225': 10.}
OLD_MULTIPLIERS = {'TOPIX': 10000., 'NK225': 1000.}
CAPS = {'TOPIX': 10, 'NK225': 20}
TICKS = {'TOPIX': .25, 'NK225': 5.}
CHECKS = 0


def divide(a: float, b: float) -> float | None:
    """機能: 分母が正の場合に比率を求める。

    引数: a/b (float)。返り値: 比率または欠損 (float|None)。
    """
    return float(a / b) if b > 1e-9 else None


def compare(a: object, b: object, label: str) -> None:
    """機能: 独立値を比較して不一致なら停止する。

    引数: a/b (object)、label (str)。返り値: なし (None)。
    """
    global CHECKS
    if a is None or b is None:
        assert a is b, (label, a, b)
    else:
        assert np.isclose(a, b, rtol=1e-10, atol=1e-5), (label, a, b)
    CHECKS += 1


def fields(profit: np.ndarray, qty: np.ndarray) -> dict:
    """機能: 実価格差から利益・損失・累計返済枚数を求める。

    引数: profit/qty (ndarray)。返り値: 損益指標 (dict)。
    """
    positive, negative = profit > 1e-6, profit < -1e-6
    p, l = float(profit[positive].sum()), float(-profit[negative].sum())
    w, d, z = [int(qty[mask].sum()) for mask in [positive, negative, ~(positive | negative)]]
    return dict(gross_profit_yen=p, gross_loss_yen=l, net_yen=p-l,
                profit_units=w, loss_units=d, zero_units=z, unit_balance=w-d,
                closed_units=w+d+z, money_ratio=divide(p, l), unit_ratio=divide(w, d),
                avg_profit_per_unit=divide(p, w), avg_loss_per_unit=divide(l, d),
                unit_payoff=divide(p/w, l/d) if w and d else None)


def reconstruct(block: dict, ready: dict, factor: float, multiplier: float, cap: int) -> tuple[dict, np.ndarray]:
    """機能: 元返済行だけから縮小数量・現金・全観測時価を再構成する。

    引数: block/ready (dict)、factor/multiplier (float)、cap (int)。
    返り値: 指標と全行時価 (tuple[dict, ndarray])。
    """
    trades = block['trades']
    assert trades.shape[1] == 11
    qty = trades[:, 3] * factor
    assert np.allclose(qty, np.round(qty)) and np.all(qty >= 1)
    qty = np.round(qty).astype(np.int64)
    direction, entries, exits = trades[:, 2], trades[:, 6].astype(int), trades[:, 7].astype(int)
    assert np.all(entries < exits)
    assert np.all(trades[:, 8] == 0), '対象手法にカバーはない'
    assert not np.any(np.isin(trades[:, 9], [3, 4, 5, 6, 7])), '対象手法に部分返済・反転はない'
    assert len(np.unique(trades[:, 1])) == len(trades), '全返済のみである'
    target_tick = TICKS[ready['symbol']]
    for col in [4, 5]:
        units = trades[:, col] / target_tick
        assert np.allclose(units, np.round(units)), '既存約定価格は対象商品の呼値に載る'
    prices = ready['last']
    size = len(prices)
    points = direction * qty * (trades[:, 5] - trades[:, 4])
    out = fields(points * multiplier, qty)
    cash_change = np.bincount(entries, weights=-direction*qty*trades[:, 4], minlength=size)
    cash_change += np.bincount(exits, weights=direction*qty*trades[:, 5], minlength=size)
    inventories = []
    for sign in [1, -1]:
        mask = direction == sign
        change = np.bincount(entries[mask], weights=qty[mask], minlength=size)
        change -= np.bincount(exits[mask], weights=qty[mask], minlength=size)
        inventory = np.cumsum(change)
        assert np.all(inventory >= 0) and np.all(inventory <= cap)
        assert inventory[-1] == 0
        inventories.append(inventory)
    long, short = inventories
    assert np.all((long == 0) | (short == 0)), '対象手法に両建てはない'
    equity = (np.cumsum(cash_change) + (long-short)*prices) * multiplier
    compare(equity[-1], out['net_yen'], '最後の全玉返済後時価')
    peak = np.maximum.accumulate(np.r_[0., equity])[1:]
    cycle_gains = []
    for cycle in block['cycles']:
        gain = float(points[trades[:, 0] == cycle[0]].sum())
        compare(gain, cycle[3]*factor, '組損益の数量比例')
        cycle_gains.append(gain*multiplier)
    cg = np.asarray(cycle_gains)
    risk = block['cycles'][:, 4] * factor * multiplier
    np.testing.assert_allclose(risk, block['cycles'][:, 5] * 10 * factor * multiplier, rtol=1e-12)
    out.update(max_long=int(long.max(initial=0)), max_short=int(short.max(initial=0)),
               max_gross=int((long+short).max(initial=0)), max_net=int(abs(long-short).max(initial=0)),
               drawdown_yen=float((peak-equity).max(initial=0)),
               min_equity_yen=float(equity.min(initial=0)), max_equity_yen=float(equity.max(initial=0)),
               cycles=len(cg), cycle_wins=int((cg > 1e-6).sum()), cycle_losses=int((cg < -1e-6).sum()),
               cycle_profit_yen=float(cg[cg > 1e-6].sum()), cycle_loss_yen=float(-cg[cg < -1e-6].sum()),
               raw_rows=size, closed_rows=len(trades), target_tick=target_tick,
               price_tick_checks=len(trades)*2, risk_budget_yen=risk.tolist(),
               risk_budget_min=float(risk.min()), risk_budget_median=float(np.median(risk)), risk_budget_max=float(risk.max()))
    return out, equity


def aggregate(rows: list[dict], curves: list[np.ndarray]) -> dict:
    """機能: 全行時価を時系列につなぎ、週合算と週最大下落を算出する。

    引数: rows (list[dict])、curves (list[ndarray])。返り値: 週指標 (dict)。
    """
    keys = ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units',
            'unit_balance', 'closed_units', 'cycles', 'cycle_wins', 'cycle_losses', 'cycle_profit_yen',
            'cycle_loss_yen', 'raw_rows', 'closed_rows']
    out = {key: sum(row[key] for row in rows) for key in keys}
    p, l, w, d = [out[key] for key in ['gross_profit_yen', 'gross_loss_yen', 'profit_units', 'loss_units']]
    out.update(money_ratio=divide(p, l), unit_ratio=divide(w, d), avg_profit_per_unit=divide(p, w),
               avg_loss_per_unit=divide(l, d), unit_payoff=divide(p/w, l/d) if w and d else None,
               positive_sessions=sum(row['net_yen'] > 0 for row in rows), session_count=len(rows),
               best_session_removed_net=out['net_yen']-max(row['net_yen'] for row in rows))
    offset, running_peak, drawdown = 0., 0., 0.
    for curve, row in zip(curves, rows):
        values = curve + offset
        peaks = np.maximum.accumulate(np.r_[running_peak, values])[1:]
        drawdown = max(drawdown, float((peaks-values).max(initial=0)))
        running_peak = float(peaks[-1])
        offset += row['net_yen']
    out['drawdown_yen'] = drawdown
    budgets = np.concatenate([np.asarray(row['risk_budget_yen']) for row in rows])
    out.update(risk_budget_min=float(budgets.min()), risk_budget_median=float(np.median(budgets)),
               risk_budget_max=float(budgets.max()), price_tick_checks=sum(row['price_tick_checks'] for row in rows))
    for key in ['max_long', 'max_short', 'max_gross', 'max_net']:
        out[key] = max(row[key] for row in rows)
    return out


def digest(path: Path) -> str:
    """機能: 読取元ファイルの同一性をSHA256で記録する。

    引数: path (Path)。返り値: ハッシュ (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: 4手法・2銘柄・10セッションを二つの数量配分で独立再集計する。

    引数: なし。返り値: なし (None)。本体関数呼出や通信は行わない。
    """
    started = time.time()
    sources = [SOURCE / name for name in ['engine.py', 'catalog.py', '全返済と組.pkl', '週合計.json', 'セッション集計.json']]
    before = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    inputs = {}
    for stage in ['development', 'holdout']:
        path = ROOT / 'work' / 'wave_v16' / f'入力_{stage}.pkl'
        before[str(path.relative_to(ROOT))] = digest(path)
        with path.open('rb') as stream:
            inputs.update(pickle.load(stream))
    with (SOURCE / '全返済と組.pkl').open('rb') as stream:
        blocks = pickle.load(stream)
    source_week = {(r['method_id'], r['symbol']): r for r in json.loads((SOURCE / '週合計.json').read_text(encoding='utf-8'))}
    source_sessions = {(r['method_id'], r['session'], r['symbol']): r for r in json.loads((SOURCE / 'セッション集計.json').read_text(encoding='utf-8'))}
    quantity_keys = ['profit_units', 'loss_units', 'zero_units', 'unit_balance', 'closed_units', 'max_long', 'max_short', 'max_gross', 'max_net']
    amount_keys = ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'drawdown_yen', 'cycle_profit_yen', 'cycle_loss_yen']
    invariant_keys = ['cycles', 'cycle_wins', 'cycle_losses', 'money_ratio', 'unit_ratio', 'unit_payoff']
    outputs = {}
    for mode in ['各手法の最大枚数枠を利用', '元の全100枚上限を一律縮小']:
        weekly, sessions = [], []
        for method in METHODS:
            for symbol in ['TOPIX', 'NK225']:
                original_cap = 100 if method.endswith('A03') or mode == '元の全100枚上限を一律縮小' else 10
                quantity_factor = CAPS[symbol] / original_cap
                money_factor = quantity_factor * MULTIPLIERS[symbol] / OLD_MULTIPLIERS[symbol]
                rows, curves = [], []
                for session in SESSIONS:
                    key = (method, session, symbol)
                    row, equity = reconstruct(blocks[key], inputs[(session, symbol)], quantity_factor, MULTIPLIERS[symbol], CAPS[symbol])
                    row.update(method_id=method, session=session, symbol=symbol, quantity_factor=quantity_factor, money_factor=money_factor)
                    for field in quantity_keys:
                        compare(row[field], source_sessions[key][field]*quantity_factor, f'{key}:{field}')
                    for field in amount_keys + ['min_equity_yen', 'max_equity_yen']:
                        compare(row[field], source_sessions[key][field]*money_factor, f'{key}:{field}')
                    for field in invariant_keys:
                        compare(row[field], source_sessions[key][field], f'{key}:{field}')
                    rows.append(row)
                    curves.append(equity)
                    sessions.append(row)
                week = aggregate(rows, curves)
                week.update(method_id=method, symbol=symbol, quantity_factor=quantity_factor, money_factor=money_factor,
                            initial_qty=int(10*quantity_factor), add_qty=int(10*quantity_factor) if method.endswith('A03') else 0,
                            cap=CAPS[symbol])
                source = source_week[(method, symbol)]
                for field in quantity_keys:
                    compare(week[field], source[field]*quantity_factor, f'週:{method}:{symbol}:{field}')
                for field in amount_keys:
                    compare(week[field], source[field]*money_factor, f'週:{method}:{symbol}:{field}')
                for field in invariant_keys + ['positive_sessions', 'session_count']:
                    compare(week[field], source[field], f'週:{method}:{symbol}:{field}')
                weekly.append(week)
        outputs[mode] = dict(weekly=weekly, sessions=sessions)
    assert all(digest(ROOT / name) == value for name, value in before.items()), '原本変更なし'
    result = dict(合格=True, 数値照合数=CHECKS, 現在API取得数=0, 元本体関数呼出数=0,
                  整数数量=True, 全セッション内返済=True, 原本変更なし=True,
                  全新規返済価格が対象商品の呼値に一致=True, 対象商品の呼値=TICKS,
                  縮小等価性='対象4手法は全返済のみ。数量・損失予算・実現損益・簿価の同率変更で合算逆指値価格の倍率が相殺され、ATR・追跡・時間条件は不変。A03は追加上限も同率変更する。',
                  注意='ラージの原価格系列と呼値で得た約定を小型商品の倍率へ換算した参考値。ミニ・マイクロ固有の板、呼値、出来高による実約定の再生ではない。費用ゼロ。',
                  入力SHA256=before, 経過秒=time.time()-started, 配分=outputs)
    (OUT / 'audit_scale.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    brief = dict(合格=result['合格'], 数値照合数=CHECKS, 経過秒=result['経過秒'], 週合計=outputs['各手法の最大枚数枠を利用']['weekly'])
    print(json.dumps(brief, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
