"""全サイクル返済後の連敗・実現損失で新規を止める、因果的な管理層。"""

from __future__ import annotations

import numpy as np
from numba import njit

import reference


GUARDS = [dict(code='G1', label='２連敗で当該セッション終了', streak=2, loss=None),
          dict(code='G2', label='３連敗で当該セッション終了', streak=3, loss=None),
          dict(code='G3', label='実現損失２ATR換算で終了', streak=None, loss=2.),
          dict(code='G4', label='実現損失４ATR換算で終了', streak=None, loss=4.),
          dict(code='G5', label='２連敗または実現損失２ATR換算で終了', streak=2, loss=2.)]


def eligible_base(config: dict) -> bool:
    """機能: 損益を使わず、事前に列挙した入口・利益保護方式を追加検証対象にする。

    引数: config (dict)。返り値: bool。純粋時間返済や別思想へ暗黙に拡張しない。
    """
    name = config['id']
    return any(tag in name for tag in ('_E1_X5_', '_E3_X2_', '_A0_', '_A1_', '_A4_', '_A5_'))


def variants(config: dict) -> list[dict]:
    """機能: 事前に決めた５種類の停止条件を付けた設定を返す。

    引数: config (dict)。返り値: list[dict]。旧設定は変更しない。
    """
    if not eligible_base(config):
        return []
    return [dict(config, id=config['id']+'_'+g['code'], base_id=config['id'], guard=g,
                 philosophy='サイクル損失で新規を停止', label=config['label']+'／'+g['label']) for g in GUARDS]


def filter_raw(raw: np.ndarray, config: dict) -> tuple[np.ndarray, dict]:
    """機能: 全玉返済が確定した順に損益を読み、停止後の新規だけを除く。

    引数: raw (ndarray): 22列原売買、config (dict): guardとmax_legsを含む。
    返り値: (残す原売買ndarray, 停止記録dict)。含み損を見て未来の再開時点を選ばない。
    """
    guard = config.get('guard')
    if not guard or not len(raw):
        return raw.copy(), dict(stopped=False, row=None, reason=None)
    cap = config['max_legs']
    streak, accumulated = 0, 0.
    baskets = sorted(np.unique(raw[:, 0]), key=lambda n: float(raw[raw[:, 0] == n, 5].min()))
    for basket in baskets:
        part = raw[raw[:, 0] == basket]
        if not np.all(part[:, 14] == 1):
            continue
        result = float(part[:, 15].sum())
        accumulated += float((part[:, 15]/part[:, 7]).sum())/cap
        streak = streak+1 if result < -1e-8 else 0
        hit_streak = guard['streak'] is not None and streak >= guard['streak']
        hit_loss = guard['loss'] is not None and accumulated <= -guard['loss']+1e-10
        if hit_streak or hit_loss:
            boundary = int(part[:, 6].max())
            kept = raw[raw[:, 5] <= boundary].copy()
            if np.any(kept[:, 6] > boundary) or np.any(kept[:, 14] != 1):
                raise ValueError('全玉返済後の停止点に、別サイクルの建玉が重なっています')
            return kept, dict(stopped=True, row=boundary, cycle=int(basket),
                    reason='連敗と実現損失' if hit_streak and hit_loss else '連敗' if hit_streak else '実現損失',
                    consecutive_losses=streak, realized_atr_cap=accumulated)
    return raw.copy(), dict(stopped=False, row=None, reason=None)


@njit(cache=True)
def account_arrays(raw: np.ndarray, prices: np.ndarray) -> tuple:
    """機能: 各脚の現金移動と枚数から、全原本行の含み損込み評価を再構成する。

    引数: raw (ndarray)、prices (ndarray)。返り値: 評価/ATR評価/総枚数/確定/下落配列と最大下落のtuple。
    """
    n = len(prices)
    cash = np.zeros(n); position = np.zeros(n); cash_atr = np.zeros(n); position_atr = np.zeros(n)
    gross = np.zeros(n); realized = np.zeros(n)
    for row in raw:
        a, b, d, entry, exit_price, atr = int(row[5]), int(row[6]), row[2], row[8], row[9], row[7]
        cash[a] -= d*entry; position[a] += d
        cash_atr[a] -= d*entry/atr; position_atr[a] += d/atr; gross[a] += 1
        if row[14] == 1:
            cash[b] += d*exit_price; position[b] -= d
            cash_atr[b] += d*exit_price/atr; position_atr[b] -= d/atr; gross[b] -= 1
            realized[b] += row[15]
    equity = np.zeros(n); eq_atr = np.zeros(n); drawdown = np.zeros(n)
    c, p, ca, pa, g, r, high, high_atr, maxdd, maxdda, last_price = 0.,0.,0.,0.,0.,0.,0.,0.,0.,0.,0.
    for i in range(n):
        c += cash[i]; p += position[i]; ca += cash_atr[i]; pa += position_atr[i]
        g += gross[i]; r += realized[i]
        if np.isfinite(prices[i]):
            last_price = prices[i]
        equity[i] = c+p*last_price
        eq_atr[i] = ca+pa*last_price
        high = max(high, equity[i]); high_atr = max(high_atr, eq_atr[i])
        maxdd = max(maxdd, high-equity[i]); maxdda = max(maxdda, high_atr-eq_atr[i])
        drawdown[i] = maxdd; gross[i] = g; realized[i] = r
    return equity, eq_atr, gross, realized, drawdown, maxdd, maxdda


def result_from_raw(prepared: dict, raw: np.ndarray, config: dict, detail: bool = False) -> dict:
    """機能: 停止後を除いた売買から、含み損・全行下落・明細を作る。

    引数: prepared/config (dict)、raw (ndarray)、detail (bool)。返り値: v13互換結果 (dict)。
    """
    values = account_arrays(raw, prepared['last'])
    equity, atr_equity, gross, realized, dd, maxdd, maxdda = values
    multiplier = reference.engine.MULTIPLIERS[prepared['symbol']]
    closed = raw[raw[:, 14] == 1]
    profit = float(closed[closed[:, 15] > 0, 15].sum()) if len(closed) else 0.
    loss = float(closed[closed[:, 15] < 0, 15].sum()) if len(closed) else 0.
    summary = dict(net_yen=float(equity[-1]*multiplier), closed_net_yen=float(realized[-1]*multiplier),
        profit_yen=profit*multiplier, loss_yen=loss*multiplier,
        open_yen=float((equity[-1]-realized[-1])*multiplier), net_atr=float(atr_equity[-1]),
        closed_net_atr=float((closed[:, 15]/closed[:, 7]).sum()) if len(closed) else 0.,
        max_drawdown_yen=float(maxdd*multiplier), max_drawdown_atr=float(maxdda),
        closed_count=len(closed), win_count=int((closed[:, 15] > 0).sum()), loss_count=int((closed[:, 15] < 0).sum()),
        open_count=int(gross[-1]), gross_peak=int(gross.max()), entry_count=len(raw), fee_yen=0., spread_cost_yen=0.)
    summary['cap_net_yen'] = summary['net_yen']/config['max_legs']
    summary['cap_net_atr'] = summary['net_atr']/config['max_legs']
    summary['win_rate'] = summary['win_count']/len(closed) if len(closed) else None
    trades, curve = [], []
    if detail:
        for row in raw:
            trade = dict(zip(reference.engine.RAW_COLUMNS, row.tolist()))
            trade.update(銘柄=prepared['symbol'], セッション=prepared['session'],
                         条件設定時刻=float(prepared['time_s'][int(row[4])]),
                         新規時刻=float(prepared['time_s'][int(row[5])]),
                         返済評価時刻=float(prepared['time_s'][int(row[6])]),
                         収支円=float(row[15]*multiplier), 返済理由=reference.engine.REASONS.get(int(row[13]), '追加方式の返済'))
            trades.append(trade)
        minute = np.floor(prepared['time_s']/60)
        indices = np.unique(np.r_[0, np.where(np.diff(minute) != 0)[0]+1, len(minute)-1])
        curve = np.column_stack([prepared['time_s'][indices], prepared['seq'][indices], equity[indices]*multiplier,
            atr_equity[indices], gross[indices], realized[indices]*multiplier, dd[indices]*multiplier]).tolist()
    return dict(summary=summary, raw=raw, trades=trades, equity=curve)


def simulate(prepared: dict, config: dict, detail: bool = False) -> dict:
    """機能: 凍結済み基本方式を再生してから、返済済み損失だけで新規停止を適用する。

    引数: prepared/config (dict)、detail (bool)。返り値: raw/summary/trades/equity/guard監査 (dict)。
    """
    base = reference.engine.simulate(prepared, config['family'], config)
    raw, audit = filter_raw(base['raw'], config)
    result = result_from_raw(prepared, raw, config, detail)
    result['guard'] = audit
    return result
