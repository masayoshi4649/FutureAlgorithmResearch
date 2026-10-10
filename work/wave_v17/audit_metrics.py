"""全返済の価格と数量から会計・枚数・時間順選択を独立に照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
MULTIPLIERS = {'NK225': 1000., 'TOPIX': 10000.}
SESSIONS = [f'2026-09-{day:02d}_{part}' for day in range(21, 26) for part in ['Day', 'Night']]
CHECKS = 0


def ratio(numerator: float, denominator: float) -> float | None:
    """機能: 正の分母がある場合だけ比率を計算する。

    引数: numerator/denominator (float)。返り値: 比率または欠損 (float|None)。
    """
    return float(numerator / denominator) if denominator > 1e-8 else None


def compare(actual: object, expected: object, label: str) -> None:
    """機能: 独立計算値と保存値を比較し、不一致なら停止する。

    引数: actual/expected (object)、label (str)。返り値: なし (None)。
    """
    global CHECKS
    if actual is None or expected is None:
        assert actual is expected, (label, actual, expected)
    elif isinstance(actual, str) or isinstance(expected, str):
        assert actual == expected, (label, actual, expected)
    else:
        assert np.isclose(actual, expected, rtol=1e-10, atol=1e-5), (label, actual, expected)
    CHECKS += 1


def profit_fields(profits: np.ndarray, quantities: np.ndarray) -> dict:
    """機能: 金額の利益損失と利益玉・損失玉の数量を別々に集計する。

    引数: profits/quantities (ndarray)。返り値: 指標辞書 (dict)。
    """
    winner, loser = profits > 1e-6, profits < -1e-6
    p, l = float(sum(profits[winner])), -float(sum(profits[loser]))
    w, d, z = (int(sum(quantities[mask])) for mask in [winner, loser, ~(winner | loser)])
    return dict(gross_profit_yen=p, gross_loss_yen=l, net_yen=p-l,
                profit_units=w, loss_units=d, zero_units=z, unit_balance=w-d,
                money_ratio=ratio(p, l), unit_ratio=ratio(w, d),
                avg_profit_per_unit=ratio(p, w), avg_loss_per_unit=ratio(l, d),
                unit_payoff=ratio(p / w, l / d) if w and d else None,
                closed_units=w+d+z)


def session_metrics(block: dict, ready: dict, config: dict) -> tuple[dict, dict]:
    """機能: 返済表の原価格・数量だけから全行の保有と時価を再構成する。

    引数: block/ready/config (dict)。返り値: 全区間指標と検査件数 (tuple[dict, dict])。
    """
    trades, cycles = block['trades'], block['cycles']
    count, multiplier = len(ready['last']), MULTIPLIERS[ready['symbol']]
    assert trades.shape[1] == 11 and cycles.shape[1] == 10
    assert np.isin(trades[:, 2], [-1, 1]).all()
    assert np.all(trades[:, 3] > 0) and np.equal(trades[:, 3], np.floor(trades[:, 3])).all()
    prices_pnl = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4])
    np.testing.assert_allclose(prices_pnl, trades[:, 10], rtol=1e-12, atol=1e-8)
    out = profit_fields(prices_pnl * multiplier, trades[:, 3])
    entering, exiting = trades[:, 6].astype(int), trades[:, 7].astype(int)
    assert np.all(entering < exiting) and np.all(exiting < count)
    signed_quantity = trades[:, 2] * trades[:, 3]
    cash_change = np.bincount(entering, weights=-signed_quantity*trades[:, 4], minlength=count)
    cash_change += np.bincount(exiting, weights=signed_quantity*trades[:, 5], minlength=count)
    positive = trades[:, 2] > 0
    inventories = []
    for mask in [positive, ~positive]:
        quantity_change = np.bincount(entering[mask], weights=trades[mask, 3], minlength=count)
        quantity_change -= np.bincount(exiting[mask], weights=trades[mask, 3], minlength=count)
        inventory = np.cumsum(quantity_change)
        assert inventory.min(initial=0) >= 0 and inventory.max(initial=0) <= 100
        assert inventory[-1] == 0
        inventories.append(inventory)
    long, short = inventories
    gross, net = long+short, long-short
    equity = (np.cumsum(cash_change) + net*ready['last']) * multiplier
    peaks = np.maximum.accumulate(np.maximum(equity, 0.))
    compare(equity[-1], out['net_yen'], '最後の全玉返済後時価')
    # ----------------------------------------
    # 元脚を部分返済ごとに分けても、元建値と元新規行は保持される必要がある。
    for leg in np.unique(trades[:, 1]):
        rows = trades[trades[:, 1] == leg]
        for column in [0, 2, 4, 6]:
            assert len(np.unique(rows[:, column])) == 1, ('元脚属性の変化', leg, column)
        assert np.all(np.diff(rows[:, 7]) >= 0)
    out.update(max_long=int(max(long, default=0)), max_short=int(max(short, default=0)),
               max_gross=int(max(gross, default=0)), max_net=int(max(abs(net), default=0)),
               drawdown_yen=float(max(peaks-equity, default=0)),
               min_equity_yen=float(min(0., min(equity, default=0))),
               max_equity_yen=float(max(0., max(equity, default=0))),
               order_count=len(trades)+len(np.unique(trades[:, 1])),
               reversals=len(np.unique(trades[trades[:, 9] == 5, 7])))
    # ----------------------------------------
    # 建玉一式の損益は、その組へ属する全返済脚を合算する。
    campaign_profit, campaign_risk = [], []
    assert np.array_equal(cycles[:, 0], np.arange(len(cycles)))
    for cycle in cycles:
        related = trades[:, 0] == cycle[0]
        gain = float(sum(prices_pnl[related]))
        compare(gain, cycle[3], '組損益')
        first, last = min(entering[related]), max(exiting[related])
        compare(first, cycle[1], '組の最初の新規行')
        compare(last, cycle[2], '組の最後の返済行')
        risk = config['initial_qty'] * config['stop_atr'] * cycle[5]
        compare(risk, cycle[4], '初期の組損失予算')
        compare(gross[first:last+1].max(initial=0), cycle[6], '組最大総保有数')
        compare(abs(net[first:last+1]).max(initial=0), cycle[7], '組最大純保有数')
        assert risk > 0
        campaign_profit.append(gain*multiplier)
        campaign_risk.append(gain/risk)
    gains = np.array(campaign_profit, dtype=float)
    compare(sum(gains), out['net_yen'], '組合計と全返済脚の一致')
    out.update(cycle_profit_yen=float(sum(gains[gains > 1e-6])),
               cycle_loss_yen=-float(sum(gains[gains < -1e-6])),
               cycle_wins=int(sum(gains > 1e-6)), cycle_losses=int(sum(gains < -1e-6)),
               cycles=len(cycles), net_r=float(sum(campaign_risk)))
    cover = trades[:, 8] == 1
    cover_pnl = prices_pnl[cover]*multiplier
    out.update(cover_profit_yen=float(sum(cover_pnl[cover_pnl > 1e-6])),
               cover_loss_yen=-float(sum(cover_pnl[cover_pnl < -1e-6])),
               method_id=config['id'], session=ready['session'], symbol=ready['symbol'])
    return out, dict(返済行数=len(trades), 元脚数=len(np.unique(trades[:, 1])), 組数=len(cycles),
                     全行時価再構成数=count, 返済累計枚数=out['closed_units'])


def aggregate(rows: list[dict]) -> dict:
    """機能: 独立計算したセッション結果を合算し、期間をつないだ最大下落を再計算する。

    引数: rows (list[dict])。返り値: 期間指標 (dict)。
    """
    additive = ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units',
                'unit_balance', 'cycle_profit_yen', 'cycle_loss_yen', 'cycle_wins', 'cycle_losses',
                'cycles', 'net_r', 'closed_units', 'order_count', 'reversals', 'cover_profit_yen', 'cover_loss_yen']
    result = {key: sum(row[key] for row in rows) for key in additive}
    p, l, w, d = (result[key] for key in ['gross_profit_yen', 'gross_loss_yen', 'profit_units', 'loss_units'])
    result.update(method_id=rows[0]['method_id'], symbol=rows[0]['symbol'], session_count=len(rows),
                  positive_sessions=sum(row['net_yen'] > 0 for row in rows),
                  active_sessions=sum(row['cycles'] > 0 for row in rows),
                  money_ratio=ratio(p, l), unit_ratio=ratio(w, d),
                  avg_profit_per_unit=ratio(p, w), avg_loss_per_unit=ratio(l, d),
                  unit_payoff=ratio(p/w, l/d) if w and d else None)
    p, l, w, d = (result[key] for key in ['cycle_profit_yen', 'cycle_loss_yen', 'cycle_wins', 'cycle_losses'])
    result.update(cycle_pf=ratio(p, l), cycle_payoff=ratio(p/w, l/d) if w and d else None)
    # ----------------------------------------
    # 各区間の最安時価と、それ以前の区間の最高時価との差をすべて列挙する。
    offsets = np.r_[0., np.cumsum([row['net_yen'] for row in rows])[:-1]]
    troughs = [offset+row['min_equity_yen'] for offset, row in zip(offsets, rows)]
    highs = [offset+row['max_equity_yen'] for offset, row in zip(offsets, rows)]
    cross_losses = [max([0.] + highs[:i]) - low for i, low in enumerate(troughs)]
    result['drawdown_yen'] = max([0.] + cross_losses + [row['drawdown_yen'] for row in rows])
    for key in ['max_long', 'max_short', 'max_gross', 'max_net']:
        result[key] = max(row[key] for row in rows)
    return result


def rank_candidates(grouped: dict, symbol: str, count: int) -> tuple[str, bool]:
    """機能: 初期期間だけの組損益から、資格・除外耐性・同順位規則を独立に評価する。

    引数: grouped (dict)、symbol (str)、count (int)。返り値: 選択IDと資格 (tuple[str,bool])。
    """
    options = []
    for (method, target), rows in grouped.items():
        if target != symbol:
            continue
        sample = rows[:count]
        totals = aggregate(sample)
        pf, payoff = totals['cycle_pf'] or 0., totals['cycle_payoff'] or 0.
        acceptable = (totals['cycles'] >= 6 and totals['cycle_wins'] >= 2 and totals['cycle_losses'] >= 2
                      and pf > 1 and payoff > 1 and totals['active_sessions'] >= min(3, count)
                      and totals['positive_sessions'] > count/2
                      and totals['net_r'] > max(row['net_r'] for row in sample))
        tolerances = []
        for omitted in sample:
            p = totals['cycle_profit_yen']-omitted['cycle_profit_yen']
            l = totals['cycle_loss_yen']-omitted['cycle_loss_yen']
            wins = totals['cycle_wins']-omitted['cycle_wins']
            losses = totals['cycle_losses']-omitted['cycle_losses']
            ratio_amount = ratio(p, l) or 0.
            ratio_average = (ratio(p/wins, l/losses) or 0.) if wins and losses else 0.
            tolerances.append(min(5., ratio_amount, ratio_average))
        options.append((not acceptable, -min(tolerances), -pf, -payoff, method, acceptable))
    chosen = min(options)
    return chosen[4], chosen[5]


def digest(path: Path) -> str:
    """機能: 監査対象のハッシュを計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1048576):
            result.update(chunk)
    return result.hexdigest()


def main() -> None:
    """機能: 保存された3600セル・360週合計・14選択を独立に監査して結果を保存する。

    引数: なし。返り値: なし (None)。本体コードの関数呼出・通信は行わない。
    """
    started = time.time()
    inputs = {}
    for stage in ['development', 'holdout']:
        with (ROOT / 'work/wave_v16' / f'入力_{stage}.pkl').open('rb') as stream:
            inputs.update(pickle.load(stream))
    with (OUT / '全返済と組.pkl').open('rb') as stream:
        blocks = pickle.load(stream)
    saved = json.loads((OUT / 'セッション集計.json').read_text(encoding='utf-8'))
    weekly = json.loads((OUT / '週合計.json').read_text(encoding='utf-8'))
    configs = {row['id']: row for row in json.loads((OUT / '全条件一覧.json').read_text(encoding='utf-8'))}
    assert len(configs) == 180 and len(saved) == len(blocks) == 3600 and len(weekly) == 360
    indexed = {(row['method_id'], row['session'], row['symbol']): row for row in saved}
    calculated, totals = {}, dict(返済行数=0, 元脚数=0, 組数=0, 全行時価再構成数=0, 返済累計枚数=0)
    for number, (key, block) in enumerate(blocks.items()):
        method, session, symbol = key
        metrics, counts = session_metrics(block, inputs[(session, symbol)], configs[method])
        row = indexed[key]
        for field, value in metrics.items():
            compare(value, row[field], f'{key}:{field}')
        assert row['cash_error'] < 1e-5
        assert row['closed_units'] == row['profit_units'] + row['loss_units'] + row['zero_units']
        assert row['unit_balance'] == row['profit_units'] - row['loss_units']
        calculated[key] = metrics
        for field, value in counts.items():
            totals[field] += value
        if (number+1) % 400 == 0:
            print(f'{number+1}/3600 セルの独立再構成が完了、{time.time()-started:.1f}秒', flush=True)
    grouped = {(method, symbol): [calculated[(method, session, symbol)] for session in SESSIONS]
               for method in configs for symbol in MULTIPLIERS}
    for row in weekly:
        independent = aggregate(grouped[(row['method_id'], row['symbol'])])
        assert set(independent) == set(row)
        for field, value in independent.items():
            compare(value, row[field], f"週:{row['method_id']}:{row['symbol']}:{field}")
    choices = json.loads((OUT / '時間順比較.json').read_text(encoding='utf-8'))
    assert len(choices) == 14
    chosen_records = []
    for choice in choices:
        symbol, count = choice['symbol'], choice['train_sessions']
        selected, eligible = rank_candidates(grouped, symbol, count)
        compare(selected, choice['chosen'], '時間順選択ID')
        compare(eligible, choice['eligible'], '時間順資格')
        compare(SESSIONS[count], choice['next_session'], '時間順次セッション')
        expected = indexed[(selected, SESSIONS[count], symbol)]
        assert expected == choice['result']
        config = configs[selected]
        baseline = f'{config["signal"]}_{"順" if config["sign"] == 1 else "逆"}_A00'
        assert indexed[(baseline, SESSIONS[count], symbol)] == choice['baseline']
        chosen_records.append(dict(銘柄=symbol, 選択までの区間数=count, 選択ID=selected, 資格合格=eligible, 次区間のみ評価=True))
    targets = ['全返済と組.pkl', 'セッション集計.json', '週合計.json', '時間順比較.json', '全条件一覧.json']
    output = dict(合格=True, 条件数=180, セッションセル数=3600, 週合計セル数=360, 独立数値照合数=CHECKS,
                  集計件数=totals, 時間順選択一致数=len(chosen_records), 時間順選択=chosen_records,
                  現在API取得数=0, 本体関数呼出数=0, 既知データだけの再現性監査=True,
                  独立再構成='全返済の方向×数量×価格差から損益を求め、元脚の新規行と各部分返済行で数量・現金を差分展開。全原本行の時価、最大同時枚数、最大下落、全玉返済を別実装で再構成。',
                  枚数の定義='利益枚数・損失枚数・ゼロ枚数は返済した累計数量。最大買い・最大売り・最大総保有・最大純保有は同時点の在庫数量であり、累計返済枚数とは別。',
                  累計枚数の関係='closed_units=profit_units+loss_units+zero_units、unit_balance=profit_units-loss_units。',
                  役割の注意='カバーから主玉へ昇格した玉は返済時の役割に分類される。元脚の元建値・方向・新規行は保存される。',
                  入力SHA256={name: digest(OUT / name) for name in targets}, 経過秒=time.time()-started)
    (OUT / '集計の独立監査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({key: value for key, value in output.items() if key not in ['時間順選択', '入力SHA256']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
