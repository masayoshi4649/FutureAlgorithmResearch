"""入口見送り比較を、売買台帳から独立に検算する。"""

from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
IDS = ('F50_NONE__E11', 'F50_NONE__E10', 'C01__E10', 'A0__E10')
SOURCES = (
    ROOT / 'work/wave_v47/exit_integration',
    ROOT / 'work/wave_v47/integration_followup/new',
    ROOT / 'work/wave_v48/update_20260930',
    ROOT / 'work/wave_v48/update_20261001',
)


def read(path: Path) -> object:
    """機能: 通常又は圧縮JSONを読み取る。

    引数: path (Path) は読取資料。返り値: 保存内容 (object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def sha(path: Path) -> str:
    """機能: 資料の内容指紋を返す。

    引数: path (Path) は読取資料。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name: str, content: object) -> None:
    """機能: 独立監査専用の場所へJSONを保存する。

    引数: name (str)、content (object)。返り値: なし (None)。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def same(left: float, right: float, label: str) -> None:
    """機能: 金額又は数量の一致を確認する。

    引数: left/right (float)、label (str)。返り値: なし (None)。
    """
    assert abs(left - right) < 1e-6, (label, left, right)


def account(ledger: dict, row: dict, ready: dict | None = None) -> dict:
    """機能: 金額・枚数・建玉を売買脚と注文の二式から確認する。

    引数: ledger/row (dict)、ready (dict|None) は任意の生価格入力。
    返り値: 検算結果 (dict)。集計関数又はエンジン内部統計は計算に使わない。
    """
    symbol = ledger['symbol']
    initial, cap, multiplier = (5, 10, 1000.) if symbol == 'TOPIX' else (10, 20, 10.)
    config = ledger['config']
    assert config['initial_qty'] == initial and config['audit_cap'] == cap
    assert config['point_value'] == multiplier
    inactive = ('add_mode', 'add_qty', 'hedge_ratio', 'cover_add', 'reverse_mode',
                'neutral_min', 'signal_exit', 'max_same_losses')
    assert all(config[field] == 0 for field in inactive)
    totals = dict(gross_profit_yen=0., gross_loss_yen=0., net_yen=0.,
                  profit_units=0, loss_units=0, zero_units=0)
    opened, closed = Counter(), Counter()
    campaigns = Counter()
    for trade in ledger['trades']:
        campaign, _, side, quantity, entry, exit_price, entry_row, exit_row, _, _, saved = trade
        assert side in (-1, 1) and quantity > 0 and quantity == int(quantity)
        assert 0 <= entry_row <= exit_row
        points = side * quantity * (exit_price - entry)
        same(points, saved, '脚価格と数量')
        value = points * multiplier
        totals['gross_profit_yen'] += max(value, 0.)
        totals['gross_loss_yen'] += max(-value, 0.)
        totals['net_yen'] += value
        totals['profit_units' if value > 0 else 'loss_units' if value < 0 else 'zero_units'] += quantity
        opened[(entry_row, side, entry)] += quantity
        closed[(exit_row, -side, exit_price)] += quantity
        campaigns[campaign] += value
    for field, value in totals.items():
        same(value, row[field], field)
    assert sum(value > 0 for value in campaigns.values()) == row['cycle_wins']
    assert sum(value < 0 for value in campaigns.values()) == row['cycle_losses']
    assert len(campaigns) == row['cycles']
    same(sum(totals[name] for name in ('profit_units', 'loss_units', 'zero_units')), row['closed_units'], '返済枚数')
    # ----------------------------------------
    # 注文を新規と返済へ分けて、返済脚の枚数と全保有を独立照合する。
    order_opened, order_closed = Counter(), Counter()
    holdings, largest = {-1: 0., 1: 0.}, {-1: 0., 1: 0.}
    last_row = -1
    cash = 0.
    for order in ledger['orders']:
        execution, source, _, side, quantity, price, reason, kind = order
        assert 0 <= source < execution and last_row <= execution
        last_row = execution
        assert quantity > 0 and quantity == int(quantity) and side in (-1, 1)
        cash -= side * quantity * price * multiplier
        if kind == 1:
            order_opened[(execution, side, price)] += quantity
            holdings[side] += quantity
            if reason == 20:
                assert quantity == initial
        else:
            assert kind == 0
            order_closed[(execution, side, price)] += quantity
            holdings[-side] -= quantity
        for direction in (-1, 1):
            assert 0 <= holdings[direction] <= initial <= cap
            largest[direction] = max(largest[direction], holdings[direction])
    assert order_opened == opened and order_closed == closed
    assert holdings == {-1: 0., 1: 0.}
    same(cash, totals['net_yen'], '注文現金と返済損益')
    same(largest[1], row['max_long'], '買い保有上限')
    same(largest[-1], row['max_short'], '売り保有上限')
    result = dict(session=row['session'], symbol=symbol, id=row['id'], **totals,
                  cycles=len(campaigns), 注文数=len(ledger['orders']), 全注文が判断より後=True,
                  金額枚数一致=True, 最終建玉ゼロ=True, 入口変更が出口に波及する設定なし=True)
    if ready is not None:
        n = len(ready['last'])
        cash_change, position_change = np.zeros(n), np.zeros(n)
        for order in ledger['orders']:
            execution, _, _, side, quantity, price, _, _ = order
            index = int(execution)
            assert ready['start'] <= ready['time_s'][index] < ready.get('session_close', ready['limit'] + 600.)
            cash_change[index] -= side * quantity * price
            position_change[index] += side * quantity
        equity = (np.cumsum(cash_change) + np.cumsum(position_change) * ready['last']) * multiplier
        same(equity[-1], totals['net_yen'], '期末時価')
        same(float(np.max(np.maximum.accumulate(equity) - equity)), row['drawdown_yen'], '最大下落')
        same(float(np.min(equity)), row['min_equity_yen'], '最悪時価')
        same(float(np.max(equity)), row['max_equity_yen'], '最高時価')
        result.update(全行時価を別式検算=True, セッション内返済=True)
    return result


def baseline() -> dict:
    """機能: 旧四方式の全16場を再生せず別式で検算する。

    引数: なし。返り値: 検算証跡と資料指紋 (dict)。
    """
    results, fingerprints = [], {}
    for identifier in IDS:
        rows, ledgers = [], []
        for folder in SOURCES:
            for name, target in (('sessions', rows), ('ledgers', ledgers)):
                path = folder / name / (identifier + '.json.gz')
                target.extend(read(path))
                fingerprints[path.relative_to(ROOT).as_posix()] = sha(path)
        keyed = {(row['session'], row['symbol']): row for row in rows}
        assert len(rows) == len(ledgers) == len(keyed) == 32
        for ledger in ledgers:
            results.append(account(ledger, keyed[ledger['session'], ledger['symbol']]))
    assert len(results) == 128
    output = dict(全合格=True, 口座数=len(results), 会計結果=results, 資料SHA256=fingerprints)
    save('旧4方式16場の会計検算.json', output)
    return output


if __name__ == '__main__':
    result = baseline()
    print(json.dumps(dict(全合格=result['全合格'], 口座数=result['口座数']), ensure_ascii=False))
