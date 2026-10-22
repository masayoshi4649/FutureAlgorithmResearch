"""固定した多系統の信号と注文管理を、既知13セッションで比較する。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import pickle
import time
from zoneinfo import ZoneInfo

import numpy as np

import engine
import learned_flow
import managers
import signals


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SYMBOLS = ['TOPIX', 'NK225']
MULT = {'TOPIX': 1000., 'NK225': 10.}
INPUTS, DIRECTIONS = {}, {}


def save(name: str, value: object) -> None:
    """機能: 結果を有限のJSONとして保存する。

    引数: name (str)、value (object)。返り値: なし (None)。
    """
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def ratio(a: float, b: float) -> float | None:
    """機能: 分母ゼロを欠損として比率を返す。

    引数: a/b (float)。返り値: 比率またはNone (float|None)。
    """
    return a / b if b > 1e-8 else None


def summarize(result: dict, cfg: dict, symbol: str, session: str, identifier: str) -> dict:
    """機能: 全玉返済・次行注文を確認し、金額と枚数を集計する。

    引数: result/cfg (dict)、symbol/session/identifier (str)。返り値: 区間集計 (dict)。
    """
    trades, cycles, orders, st = (result[k] for k in ['trades', 'cycles', 'orders', 'stats'])
    values = trades[:, 10] * MULT[symbol]
    wins, losses = values > 1e-6, values < -1e-6
    cv = cycles[:, 3] * MULT[symbol]
    assert st[9] == 0 and st[2] <= cfg['audit_cap'] and st[3] <= cfg['audit_cap']
    assert st[6] < 1e-6
    np.testing.assert_allclose([values.sum(), cv.sum()], st[0] * MULT[symbol], atol=.01, rtol=0)
    np.testing.assert_allclose(trades[:, 10], trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]), atol=1e-7, rtol=0)
    assert np.all(orders[:, 0] > orders[:, 1])
    assert np.all(trades[:, 6] < trades[:, 7])
    streak, longest = 0, 0
    for value in cv:
        streak = streak + 1 if value < 0 else 0
        longest = max(longest, streak)
    return dict(id=identifier, symbol=symbol, session=session,
                gross_profit_yen=float(values[wins].sum()), gross_loss_yen=float(-values[losses].sum()), net_yen=float(values.sum()),
                profit_units=int(trades[wins, 3].sum()), loss_units=int(trades[losses, 3].sum()), zero_units=int(trades[~(wins | losses), 3].sum()),
                cycles=len(cycles), cycle_wins=int((cv > 0).sum()), cycle_losses=int((cv < 0).sum()),
                cycle_profit_yen=float(cv[cv > 0].sum()), cycle_loss_yen=float(-cv[cv < 0].sum()),
                net_r=float(np.sum(cycles[:, 3] / cycles[:, 4])) if len(cycles) else 0.,
                drawdown_yen=float(st[1] * MULT[symbol]), min_equity_yen=float(st[7] * MULT[symbol]), max_equity_yen=float(st[8] * MULT[symbol]),
                max_long=int(st[2]), max_short=int(st[3]), closed_units=int(trades[:, 3].sum()),
                reversals=int(st[10]), longest_losing_streak=longest,
                maximum_trade_profit=max(0., float(cv.max())) if len(cv) else 0., maximum_trade_loss=min(0., float(cv.min())) if len(cv) else 0.)


def aggregate(rows: list[dict]) -> dict:
    """機能: 銘柄内で成績を合算し、最大勝ち除外と時価下落を計算する。

    引数: rows (list[dict])。返り値: 期間集計 (dict)。
    """
    fields = ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units',
              'cycles', 'cycle_wins', 'cycle_losses', 'cycle_profit_yen', 'cycle_loss_yen', 'net_r', 'closed_units']
    output = {f: sum(r[f] for r in rows) for f in fields}
    cash = high = dd = 0.
    for r in sorted(rows, key=lambda r: r['session']):
        dd = max(dd, r['drawdown_yen'], high - (cash + r['min_equity_yen']))
        high = max(high, cash + r['max_equity_yen'])
        cash += r['net_yen']
    best = max(rows, key=lambda r: r['net_yen']) if rows else None
    trimmed = [r for r in rows if r is not best]
    output.update(money_ratio=ratio(output['gross_profit_yen'], output['gross_loss_yen']),
                  cycle_ratio=ratio(output['cycle_profit_yen'], output['cycle_loss_yen']),
                  win_sessions=sum(r['net_yen'] > 0 for r in rows), active_sessions=sum(r['cycles'] > 0 for r in rows),
                  worst_session=min((r['net_yen'] for r in rows), default=0), drawdown_yen=dd,
                  best_removed_net=sum(r['net_yen'] for r in trimmed),
                  best_removed_pf=ratio(sum(r['cycle_profit_yen'] for r in trimmed), sum(r['cycle_loss_yen'] for r in trimmed)),
                  best_trade_removed_net=output['net_yen'] - max((r['maximum_trade_profit'] for r in rows), default=0),
                  max_long=max((r['max_long'] for r in rows), default=0), max_short=max((r['max_short'] for r in rows), default=0),
                  longest_losing_streak=max((r['longest_losing_streak'] for r in rows), default=0), session_count=len(rows))
    output['average_unit_payoff'] = ratio(output['gross_profit_yen'] / output['profit_units'], output['gross_loss_yen'] / output['loss_units']) if output['profit_units'] and output['loss_units'] else None
    return output


def eligibility(symbols: dict, n: int) -> bool:
    """機能: 両銘柄の黒字・活動・勝ち依存を固定条件で判定する。

    引数: symbols (dict)、n (int)。返り値: 合格可否 (bool)。
    """
    return all(a['net_yen'] > 0 and (a['cycle_ratio'] or 0) >= 1.10 and a['cycles'] >= max(6, n)
               and a['active_sessions'] >= math.ceil(n * .6) and a['win_sessions'] >= math.ceil(n * .5)
               and a['best_removed_net'] > 0 and a['best_trade_removed_net'] > 0 for a in symbols.values())


def score(symbols: dict, n: int) -> tuple:
    """機能: 銘柄間円額を合算せず、弱い銘柄側の安定性で順位付けする。

    引数: symbols (dict)、n (int)。返り値: 比較値の組 (tuple)。
    """
    active = all(a['cycles'] >= max(6, n) and a['active_sessions'] >= math.ceil(n * .6) for a in symbols.values())
    values = list(symbols.values())
    capped = lambda value: min(5., value) if value is not None else 0.
    return (eligibility(symbols, n), active, min(capped(a['best_removed_pf']) for a in values),
            min(a['win_sessions'] / max(1, n) for a in values),
            min(a['net_yen'] / max(1, a['drawdown_yen']) for a in values))


def worker_init() -> None:
    """機能: 各並列処理で固定入力・方向を１回だけ読み込む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, DIRECTIONS
    INPUTS = pickle.loads((OUT / 'inputs.pkl').read_bytes())
    DIRECTIONS = pickle.loads((OUT / 'directions.pkl').read_bytes())


def evaluate(task: tuple[str, dict]) -> list[dict]:
    """機能: 一つの方向と管理を全26区間で再生する。

    引数: task (tuple[str,dict])。返り値: 各区間の指標 (list[dict])。
    """
    signal_id, manager = task
    identifier = signal_id + '_' + manager['id']
    rows, ledger = [], {}
    for key, ready in INPUTS.items():
        session, symbol = key
        cfg = managers.make_config(manager, symbol, ready)
        result = engine.run(ready, DIRECTIONS[signal_id][key], cfg, detail=False)
        rows.append(summarize(result, cfg, symbol, session, identifier))
        ledger[session + '_' + symbol + '_trades'] = result['trades']
        ledger[session + '_' + symbol + '_cycles'] = result['cycles']
    np.savez_compressed(OUT / 'trades' / (identifier + '.npz'), **ledger)
    return rows


def select(all_rows: list[dict], catalog: list[dict]) -> dict:
    """機能: 固定基準の全既知ランキングと過去だけで選ぶ逐次検証を作成する。

    引数: all_rows (list[dict])、catalog (list[dict])。返り値: 選択結果 (dict)。
    """
    sessions = sorted({r['session'] for r in all_rows})
    grouped = {c['id']: [] for c in catalog}
    for row in all_rows:
        grouped[row['id']].append(row)
    ranking = []
    for item in catalog:
        by_symbol = {s: aggregate([r for r in grouped[item['id']] if r['symbol'] == s]) for s in SYMBOLS}
        ranking.append(dict(item, symbols=by_symbol, qualified=eligibility(by_symbol, len(sessions)), score=list(score(by_symbol, len(sessions)))))
    ranking.sort(key=lambda r: (tuple(r['score']), r['id']), reverse=True)
    folds, walk_rows = [], []
    for i in range(6, len(sessions)):
        previous = set(sessions[:i])
        choices = []
        for item in catalog:
            symbol_rows = {s: aggregate([r for r in grouped[item['id']] if r['symbol'] == s and r['session'] in previous]) for s in SYMBOLS}
            choices.append((score(symbol_rows, i), item['id'], eligibility(symbol_rows, i)))
        best_score, best_id, qualified = max(choices)
        test = [r for r in grouped[best_id] if r['session'] == sessions[i]]
        walk_rows.extend(test)
        folds.append(dict(学習末尾=sessions[i - 1], 評価セッション=sessions[i], 選択ID=best_id, 過去側資格合格=qualified, 結果=test))
    save('全条件の期間集計.json', ranking)
    save('逐次選択の結果.json', dict(全期間既読による事後再現=True, fold数=len(folds), folds=folds,
         symbols={s: aggregate([r for r in walk_rows if r['symbol'] == s]) for s in SYMBOLS}))
    chosen, families = [], set()
    for row in ranking:
        if row['family'] not in families:
            chosen.append(row['id'])
            families.add(row['family'])
        if len(chosen) == 5:
            break
    return dict(primary=ranking[0]['id'], qualified_count=sum(r['qualified'] for r in ranking), finalists=chosen,
                selected_by='最大勝ち除外後の組PFの両銘柄で弱い側→黒字セッション率→収支/時価最大下落。円額を銘柄間合算しない。',
                never_claim_unseen=True, sessions=sessions)


def main() -> None:
    """機能: 凍結記録から信号・売買・逐次選択を一括実行する。

    引数: なし。返り値: なし (None)。現在データは取得しない。
    """
    inputs = pickle.loads((OUT / 'inputs.pkl').read_bytes())
    features = pickle.loads((OUT / 'features_depth.pkl').read_bytes())
    specs = signals.catalog() + learned_flow.catalog()
    manager_specs = managers.manager_catalog()
    items = [dict(id=s['id'] + '_' + m['id'], signal_id=s['id'], manager_id=m['id'], family=s['family'],
                  name=s['name'] + '＋' + m['name'], signal=s, manager=m) for s in specs for m in manager_specs]
    save('探索前の固定記録.json', dict(時刻=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 全13セッション既読=True,
         信号数=len(specs), 管理数=len(manager_specs), 全条件数=len(items), 逐次選択='最初６区間で選択→次１区間評価、以後１区間ずつ過去を拡張',
         資格='両銘柄で黒字・組PF1.10以上・組数max(6,区間数)以上・活動60%以上・黒字区間50%以上・最大勝ち区間と最大勝ち取引を個別除外して黒字',
         順位='資格合格→活動条件→両銘柄の弱い側の最大勝ち除外後組PF（上限5）→黒字区間率→収支/時価最大下落',
         費用=0, 指定価格約定=True, 現在API取得回数=0,
         コードSHA256={name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() for name in ['research.py', 'signals.py', 'engine.py', 'managers.py', 'learned_flow.py']}))
    save('全条件一覧.json', items)
    print(f'固定完了: {len(specs)}信号×{len(manager_specs)}管理={len(items)}条件', flush=True)
    directions = {}
    for s in signals.catalog():
        directions[s['id']] = signals.build(s, inputs, features)
    _, learned = learned_flow.build_all(inputs, features)
    directions.update(learned)
    with (OUT / 'directions.pkl').open('wb') as stream:
        pickle.dump(directions, stream, pickle.HIGHEST_PROTOCOL)
    del features, inputs, directions
    (OUT / 'trades').mkdir(exist_ok=True)
    rows = []
    tasks = [(s['id'], m) for s in specs for m in manager_specs]
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=3, initializer=worker_init) as pool:
        for i, batch in enumerate(pool.map(evaluate, tasks, chunksize=1), 1):
            rows.extend(batch)
            if i % 40 == 0 or i == len(tasks):
                print(f'{i}/{len(tasks)}条件完了、{time.monotonic()-started:.0f}秒', flush=True)
    save('全条件セッション集計.json', rows)
    selection = select(rows, items)
    save('選択結果.json', selection)
    print(json.dumps(selection, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
