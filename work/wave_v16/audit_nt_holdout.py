"""固定されたNT4条件だけの最終夜と、保存済み各脚による週の全行会計を監査する。"""

from __future__ import annotations

import json
import pickle

import numpy as np
import pandas as pd

import reference
import selection
import audit_alternatives as audit

OUT = reference.OUT
pair = audit.pair
legacy = reference.import_v14('details')


def reconstruct(tapes: list[dict], session: str, legs: list[dict]) -> dict:
    """機能: 保存脚の現金移動と両価格から全原本行の時価・数量・下落を再構成する。

    引数: tapes (list[dict])、session (str)、legs (list[dict])。返り値: 全行曲線と極値の辞書。
    売買信号を再実行せず、セッション内の原本順序と２銘柄同時刻順だけを再現する。
    """
    clean = []
    for tape in tapes:
        valid = np.isfinite(tape['time_s']) & np.isfinite(tape['last']) & (tape['last'] > 0)
        clean.append({key: tape[key][valid] for key in ['time_s', 'seq', 'last']})
    start, limit = pair.bounds(session)
    last_clock = np.floor(min(t['time_s'][-1] for t in clean) / 60) * 60
    clocks = np.arange(start, min(last_clock, limit) + 1, 60.)
    times = np.concatenate([t['time_s'] for t in clean] + [clocks])
    kinds = np.concatenate([np.full(len(t['seq']), j, dtype=int) for j, t in enumerate(clean)]
                           + [np.full(len(clocks), 2, dtype=int)])
    rows = np.concatenate([np.arange(len(t['seq'])) for t in clean] + [np.arange(len(clocks))])
    order = np.argsort(times, kind='stable')
    times, kinds, rows = times[order], kinds[order], rows[order]
    size = len(times)
    cash, realized, gross = np.zeros(size), np.zeros(size), np.zeros(size)
    positions, prices, maps = [], [], []
    for j, tape in enumerate(clean):
        indices = np.flatnonzero(kinds == j)
        mapping = np.full(len(tape['seq']), -1, dtype=int)
        mapping[rows[indices]] = indices
        maps.append(mapping)
        values = np.full(size, np.nan)
        values[indices] = tape['last'][rows[indices]]
        prices.append(pd.Series(values).ffill().fillna(0).to_numpy())
        positions.append(np.zeros(size))
    for leg in legs:
        j = reference.SYMBOLS.index(leg['symbol'])
        tape = clean[j]
        assert leg['quantity'] > 0 and leg['entry_time'] > leg['entry_order']
        assert leg['complete'] and leg['exit_time'] > leg['exit_order']
        assert leg['quantity'] == int(leg['quantity'])
        assert leg['multiplier'] == (1000 if j == 0 else 10000)
        locs = {}
        for name in ['entry', 'exit']:
            i = int(np.searchsorted(tape['seq'], leg[name + '_seq']))
            assert tape['seq'][i] == leg[name + '_seq']
            np.testing.assert_allclose([tape['time_s'][i], tape['last'][i]],
                                       [leg[name + '_time'], leg[name + '_price']])
            locs[name] = maps[j][i]
        factor = leg['side'] * leg['quantity'] * leg['multiplier']
        a, b = locs['entry'], locs['exit']
        cash[a] -= factor * leg['entry_price']
        positions[j][a] += factor
        gross[a] += leg['quantity']
        cash[b] += factor * leg['exit_price']
        positions[j][b] -= factor
        gross[b] -= leg['quantity']
        pnl = factor * (leg['exit_price'] - leg['entry_price'])
        realized[b] += pnl
        np.testing.assert_allclose(pnl, leg['net_yen'], atol=1e-5)
    equity = np.cumsum(cash)
    for position, price in zip(positions, prices):
        equity += np.cumsum(position) * price
        assert abs(position.sum()) < 1e-5
    realized, gross = np.cumsum(realized), np.cumsum(gross)
    assert gross[-1] == 0 and gross.max() <= 20
    np.testing.assert_allclose(equity[-1], realized[-1], atol=1e-5)
    dd = np.maximum.accumulate(np.r_[0., equity])[1:] - equity
    return dict(time=times, equity=equity, realized=realized, gross=gross, drawdown=dd,
                kinds=kinds, rows=rows, minimum=float(min(0., equity.min())),
                maximum=float(max(0., equity.max())), max_drawdown=float(dd.max()),
                origin_inverse=np.argsort(order), offsets=np.array([0, len(clean[0]['seq']),
                                                                    len(clean[0]['seq']) + len(clean[1]['seq'])]))


def inspect_cycles(cycles: list[dict], legs: list[dict]) -> None:
    """機能: 各ペア損益を数量と価格から計算し、２種類の相対・端数分解を確認する。

    引数: cycles/legs (list[dict])。返り値: None。不一致時は例外。
    """
    for c in cycles:
        part = [leg for leg in legs if leg['cycle_id'] == c['cycle_id']]
        assert len(part) == 2 and c['complete']
        n = next(x for x in part if x['symbol'] == 'NK225')
        t = next(x for x in part if x['symbol'] == 'TOPIX')
        a = n['quantity'] * n['multiplier'] * n['entry_price']
        b = t['quantity'] * t['multiplier'] * t['entry_price']
        rn = (n['exit_price'] - n['entry_price']) / n['entry_price']
        rt = (t['exit_price'] - t['entry_price']) / t['entry_price']
        side, beta = n['side'], c['target_beta']
        relative = side * (a + b) * (rn - rt) / 2
        common = side * (a - b) * (rn + rt) / 2
        beta_relative = side * a * (rn - beta * rt)
        beta_residual = side * (beta * a - b) * rt
        np.testing.assert_allclose([relative, common, beta_relative, beta_residual],
                                   [c['relative_yen'], c['common_residual_yen'],
                                    c['beta_relative_yen'], c['beta_rounding_yen']], atol=1e-5)
        np.testing.assert_allclose([sum(x['net_yen'] for x in part), relative + common,
                                   beta_relative + beta_residual], c['net_yen'], atol=1e-5)


def main() -> None:
    """機能: 保留４条件だけ再生し、週10区間の保存脚から下落額を独立に照合する。

    引数: なし。返り値: None。全36条件の保留探索や旧９区間の再売買はしない。
    """
    selection.freeze_check()
    record = json.loads((OUT / '最終選択.json').read_text(encoding='utf-8'))
    methods = [x['method'] for x in record['照合対象'] if x['symbol'] == 'NT']
    assert len(methods) == 4
    mapping = {c['id']: c for c in reference.configs()}
    holdout = reference.load_inputs('holdout')
    development = reference.load_inputs('development')
    ready = pair.prepare_session(reference.HOLDOUT, tapes=[holdout[(reference.HOLDOUT, s)] for s in reference.SYMBOLS])
    with (OUT / 'NT_再生結果.pkl').open('rb') as stream:
        saved = pickle.load(stream)
    table = pd.read_csv(OUT / '代表_セッション集計.csv')
    report_trades = json.loads((OUT / '代表_全取引.json').read_text(encoding='utf-8'))
    bundles = json.loads((OUT / '週合計指標.json').read_text(encoding='utf-8'))
    comparisons, discrepancies, holdout_rows = [], [], []
    price_rows = holdout_legs = holdout_cycles = 0
    for method in methods:
        result = pair.run(ready, mapping[method], detail=True)
        independent = reconstruct(ready['tapes'], reference.HOLDOUT, result['legs'])
        native = result['full_curve']
        origins = native[:, 7].astype(int) + independent['offsets'][native[:, 6].astype(int)]
        locs = independent['origin_inverse'][origins]
        for actual, expected in [(independent['equity'][locs], native[:, 3]),
                                 (independent['realized'][locs], native[:, 1]),
                                 (independent['gross'][locs], native[:, 5]),
                                 (independent['drawdown'][locs], native[:, 4])]:
            np.testing.assert_allclose(actual, expected, atol=1e-5)
        inspect_cycles(result['cycles'], result['legs'])
        actual_trades = legacy.pair_trades(result['legs'], method)
        expected_trades = [x for x in report_trades if x['方式'] == method and x['セッション'] == reference.HOLDOUT]
        assert actual_trades == expected_trades
        holdout_legs += len(result['legs'])
        holdout_cycles += len(result['cycles'])
        holdout_rows.append(dict(方式=method, 原本時計行数=len(independent['equity']), 脚数=len(result['legs']),
                                 サイクル数=len(result['cycles']), 収支円=float(independent['equity'][-1]),
                                 最大下落円=independent['max_drawdown'], 全返済=True))
        equities = []
        for session in reference.SESSIONS:
            if session == reference.HOLDOUT:
                session_result, account = result, independent
            else:
                session_result = saved[(method, session, 'NT')]
                account = reconstruct([development[(session, s)] for s in reference.SYMBOLS], session, session_result['legs'])
            inspect_cycles(session_result['cycles'], session_result['legs'])
            equities.append(account['equity'])
            price_rows += len(account['equity'])
            row = table[(table['方式'] == method) & (table['銘柄'] == 'NT') & (table['セッション'] == session)].iloc[0]
            np.testing.assert_allclose([row.net_yen, row.closed_net_yen, row.open_yen, row.max_drawdown_yen],
                                       [account['equity'][-1], account['realized'][-1], 0., account['max_drawdown']], atol=1e-5)
            for field, value in [('最小評価損益円', account['minimum']), ('最大評価損益円', account['maximum'])]:
                if not np.isclose(row[field], value, atol=1e-5):
                    discrepancies.append(dict(方式=method, セッション=session, 項目=field,
                                               保存値=float(row[field]), 原本全行値=value))
        cumulative, previous = [], 0.
        for eq in equities:
            cumulative.append(previous + eq)
            previous += float(eq[-1])
        curve = np.concatenate(cumulative)
        week_dd = float(np.max(np.maximum.accumulate(np.r_[0., curve])[1:] - curve))
        bundle = next(x for x in bundles if x['method'] == method and x['symbol'] == 'NT')
        recorded = bundle['指標']['全10区間']['期間全体の最大下落円']
        matches = bool(np.isclose(week_dd, recorded, atol=1e-5))
        comparisons.append(dict(方式=method, 週収支円=float(curve[-1]), 原本全行週下落円=week_dd,
                                保存週下落円=recorded, 一致=matches))
    selection.freeze_check()
    summary = dict(成功=all(x['一致'] for x in comparisons), 固定４条件のみ=True, 保留全36探索=False,
                   原本通信回数=0, 旧９区間の再売買回数=0, 保留再生セル数=4,
                   保留原本時計行数=sum(x['原本時計行数'] for x in holdout_rows), 保留脚数=holdout_legs,
                   保留サイクル数=holdout_cycles, 保留=holdout_rows,
                   週全行会計セル数=40, 週原本時計行数=price_rows, 週下落照合=comparisons,
                   表示間引きによる区間極値の差=discrepancies,
                   会計確認='原本価格・数量・元本差分解・全返済・全行MTM・全行DDを確認。旧９は保存脚から会計し直した。')
    reference.save(OUT / 'NT最終保留_独立監査.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
