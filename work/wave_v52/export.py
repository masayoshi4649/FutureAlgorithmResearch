"""研究用台帳を、各場・各週・30分・原本行参照の記録へ整形する。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
import numpy as np


JST = timezone(timedelta(hours=9))


def stamp(value: float) -> str:
    """機能: Unix秒を日本時間へ変換する。

    引数: value(float)。返り値: 日本時間(str)。
    """
    return datetime.fromtimestamp(value, JST).isoformat()


def save_csv(path: Path, rows: list[dict]) -> None:
    """機能: 日本語の列名を持つ記録を保存する。

    引数: path(Path)、rows(list[dict])。返り値: なし(None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text('', encoding='utf-8-sig')
        return
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def intervals(ready: dict, result: dict) -> list[dict]:
    """機能: 原本順の時価曲線を30分区間へ分け、決済額と含み増減を照合する。

    引数: ready(dict)、result(dict)。返り値: 区間会計(list[dict])。
    境界直前の観測だけを使い、未来の補間価格は使わない。
    """
    times, curve = ready['time_s'], result['curve']
    trades = np.asarray(result['trades'], float).reshape(-1, 16)
    start, end = float(ready['start']), float(times[-1]) + .001
    step = 1800.
    inner = np.arange((np.floor(start / step) + 1) * step, end, step)
    edges = np.r_[start, inner, end]
    previous = realized = 0.
    rows = []
    for left, right in zip(edges[:-1], edges[1:]):
        idx = np.searchsorted(times, right, side='left') - 1
        equity = float(curve[idx]) if idx >= 0 else 0.
        selected = trades[(trades[:, 1] >= left) & (trades[:, 1] < right)]
        profit = float(np.maximum(selected[:, 6], 0).sum())
        loss = float(-np.minimum(selected[:, 6], 0).sum())
        old_unrealized = previous - realized
        realized += profit - loss
        new_unrealized = equity - realized
        rows.append(dict(開始=stamp(left), 終了未満=stamp(right), 利益円=profit, 損失円=loss,
                         確定収支円=profit - loss, 開始含み円=old_unrealized,
                         終了含み円=new_unrealized, 時価収支円=equity - previous,
                         利益返済枚数=int(selected[selected[:, 6] > 0, 3].sum()),
                         損失返済枚数=int(selected[selected[:, 6] < 0, 3].sum()),
                         同値返済枚数=int(selected[selected[:, 6] == 0, 3].sum()),
                         評価原本行=int(ready['seq'][idx]) if idx >= 0 else None))
        previous = equity
    np.testing.assert_allclose(sum(r['時価収支円'] for r in rows), result['net'], atol=1e-6)
    np.testing.assert_allclose(sum(r['確定収支円'] for r in rows), result['net'], atol=1e-6)
    return rows


def summarize(accounts: list[dict]) -> dict:
    """機能: 同銘柄の勝ち金額・負け金額と決済枚数を集計する。

    引数: accounts(list[dict])。返り値: 期間成績(dict)。
    """
    columns = ('profit', 'loss', 'net', 'win_qty', 'loss_qty', 'flat_qty', 'cycles', 'wins', 'losses')
    out = {c: sum(a[c] for a in accounts) for c in columns}
    out.update(sessions=len(accounts), positive_sessions=sum(a['net'] > 0 for a in accounts),
               negative_sessions=sum(a['net'] < 0 for a in accounts), active_sessions=sum(a['cycles'] > 0 for a in accounts))
    out['pf'] = out['profit'] / out['loss'] if out['loss'] else None
    out['win_rate'] = out['wins'] / out['cycles'] if out['cycles'] else None
    out['win_per_lot'] = out['profit'] / out['win_qty'] if out['win_qty'] else None
    out['loss_per_lot'] = out['loss'] / out['loss_qty'] if out['loss_qty'] else None
    out['payoff'] = out['win_per_lot'] / out['loss_per_lot'] if out['loss_per_lot'] and out['win_per_lot'] is not None else None
    out['without_best'] = out['net'] - max([a['net'] for a in accounts], default=0)
    out['worst_session'] = min([a['net'] for a in accounts], default=0)
    peak = balance = dd = 0.
    for a in sorted(accounts, key=lambda x: x['session']):
        if 'curve' in a:
            curve = balance + a['curve']
            peaks = np.maximum.accumulate(np.r_[peak, curve])[1:]
            dd = max(dd, float(np.max(peaks - curve, initial=0)))
            peak = max(peak, float(np.max(curve, initial=peak)))
        balance += a['net']
    out['drawdown'] = dd
    return out
