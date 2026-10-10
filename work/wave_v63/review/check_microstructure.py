"""短期板売買の会計・未来切断・影取引の既完了条件を独立に検査する。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'microstructure/core.py'
os.environ['NUMBA_CACHE_DIR'] = str(HERE / '.numba')
spec = importlib.util.spec_from_file_location('短期板監査対象', SOURCE)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


def shadow_reference(times: np.ndarray, bid: np.ndarray, ask: np.ndarray, signal: np.ndarray,
                     qty: int, value: float, fee: int, protect: bool) -> list[tuple]:
    """機能: 校正門を持たない影取引の終了行・純益を別の状態表現で再生する。

    引数: 時刻・気配・信号(ndarray)、qty/fee(int)、value(float)、protect(bool)。
    返り値: 終了行と費用後収支の一覧(list[tuple])。結果が出た行より前へ返さない。
    """
    position = None
    scheduled = None
    last_exit = -1e20
    outcomes = []
    for i, now in enumerate(times):
        if scheduled is not None:
            kind, direction = scheduled
            if kind == '建':
                if now < 400:
                    price = ask[i] if direction > 0 else bid[i]
                    position = dict(side=direction, price=price, time=now, best=0.)
            else:
                assert now < 1000
                price = bid[i] if position['side'] > 0 else ask[i]
                profit = position['side'] * (price - position['price']) * qty * value - 2 * fee
                outcomes.append((i, profit))
                position = None
                last_exit = now
            scheduled = None
        if position is not None:
            profit_points = position['side'] * ((bid[i] if position['side'] > 0 else ask[i]) - position['price'])
            position['best'] = max(position['best'], profit_points)
            protected = protect and position['best'] >= 2 and profit_points <= 2 * fee / (qty * value) + .5
            if profit_points >= 4 or profit_points <= -2 or now - position['time'] >= 25 or now >= 640 or protected:
                scheduled = ('返', position['side'])
        elif signal[i] and now < 400 and now - last_exit >= 10:
            scheduled = ('建', int(signal[i]))
    return outcomes


def run(times: np.ndarray, bid: np.ndarray, ask: np.ndarray, signal: np.ndarray,
        value: float, qty: int, unit: float, protect: int, calibration: int) -> tuple:
    """機能: 固定した人工設定を監査対象へ渡す。

    引数: 各ndarray、value/unit(float)、qty/protect/calibration(int)。返り値: 再生結果(tuple)。
    """
    return core.replay.py_func(times, bid, ask, signal, 1., 0., 700., value, qty, unit,
        4, 2, 25., 10., protect, calibration, 3, 4)


def audit_cash(orders: np.ndarray, trades: np.ndarray, equity: np.ndarray,
               bid: np.ndarray, ask: np.ndarray, value: float, qty: int, fee: int) -> None:
    """機能: 原本各行の現金と返済可能価格から全資産を再構成する。

    引数: 台帳・資産・気配(ndarray)、value(float)、qty/fee(int)。返り値: なし(None)。
    """
    cash = np.zeros(len(bid))
    positions = np.zeros(len(bid))
    if len(orders):
        d, i = orders[:, 0].astype(int), orders[:, 1].astype(int)
        assert np.all(i == d + 1)
        np.testing.assert_array_equal(orders[:, 5], np.where(orders[:, 3] > 0, ask[i], bid[i]))
        np.testing.assert_array_equal(orders[:, 6], np.full(len(orders), fee))
        np.add.at(cash, i, -orders[:, 3] * orders[:, 4] * orders[:, 5] * value - fee)
        np.add.at(positions, i, orders[:, 3] * orders[:, 4])
    positions = np.cumsum(positions)
    curve = np.cumsum(cash) + positions * np.where(positions > 0, bid, ask) * value
    np.testing.assert_allclose(curve, equity, rtol=0, atol=1e-6)
    assert positions[-1] == 0 and np.max(np.abs(positions)) <= qty
    assert abs(curve[-1] - trades[:, 11].sum()) < 1e-6


def main() -> None:
    """機能: 校正・保護・鏡像と締切の人工検査を保存する。

    引数: なし。返り値: なし(None)。実データ利益は参照しない。
    """
    times = np.arange(780, dtype=float)
    paths = [1000 + np.arange(780) * .4, 1000 + 7 * np.sin(np.arange(780) / 8),
             1000 + 4 * np.sin(np.arange(780) / 3), np.full(780, 1000.)]
    count = prefix_count = future_count = entries = completed = 0
    for symbol, value, qty, unit in [('TOPIX', 1000., 5, 41.8), ('NK225', 10., 10, 11.)]:
        fee = int(qty * unit + 1e-9)
        for path in paths:
            for side in (1, -1):
                mid = path if side > 0 else 2000 - path
                bid, ask = mid - .5, mid + .5
                signal = np.zeros(len(times), dtype=np.int8)
                signal[::3] = side
                for protect in (0, 1):
                    shadow = shadow_reference(times, bid, ask, signal, qty, value, fee, protect)
                    for calibration in (0, 1):
                        result = run(times, bid, ask, signal, value, qty, unit, protect, calibration)
                        orders, trades, curve, counters = result
                        audit_cash(orders, trades, curve, bid, ask, value, qty, fee)
                        assert counters[1] == len(shadow)
                        assert counters[2] == sum(pnl > 0 for _, pnl in shadow[-4:])
                        for trade in trades:
                            if calibration:
                                past = [pnl for i, pnl in shadow if i <= trade[0]]
                                assert len(past) >= 4 and sum(pnl > 0 for pnl in past[-4:]) >= 3
                            entries += 1
                        for cut in (2, 91, 233, 399):
                            partial = run(times[:cut], bid[:cut], ask[:cut], signal[:cut], value, qty, unit, protect, calibration)
                            np.testing.assert_array_equal(partial[0], orders[orders[:, 1] < cut])
                            np.testing.assert_array_equal(partial[1], trades[trades[:, 3] < cut])
                            np.testing.assert_allclose(partial[2], curve[:cut], rtol=0, atol=1e-8)
                            prefix_count += 1
                            changed_bid, changed_ask = bid.copy(), ask.copy()
                            changed_bid[cut:] += 100
                            changed_ask[cut:] += 100
                            changed = run(times, changed_bid, changed_ask, signal, value, qty, unit, protect, calibration)
                            np.testing.assert_array_equal(changed[0][changed[0][:, 1] < cut], orders[orders[:, 1] < cut])
                            np.testing.assert_allclose(changed[2][:cut], curve[:cut], rtol=0, atol=1e-8)
                            future_count += 1
                        count += 1
                        completed += len(trades)
    # ----------------------------------------
    # 判断後に新規締切へ達した場合の取消、返済が場外へ飛ぶ場合の失敗を検査する。
    signal = np.array([1, 0, 0], dtype=np.int8)
    late = run(np.array([399., 400., 401.]), np.full(3, 999.), np.full(3, 1000.), signal, 1000., 5, 41.8, 0, 0)
    assert len(late[0]) == 0 and late[3][0] == 0
    failed = False
    try:
        run(np.array([0., 1., 30., 1000.]), np.full(4, 999.), np.full(4, 1000.),
            np.array([1, 0, 0, 0], dtype=np.int8), 1000., 5, 41.8, 0, 0)
    except AssertionError:
        failed = True
    assert failed and completed > 100
    record = dict(合格=True, 人工経路=count, 実決済組=completed, prefix比較=prefix_count, 未来改変比較=future_count,
        影取引を別状態表現で照合=True, 校正使用結果は判断行までに完了=True,
        新規の約定時締切再確認=True, 返済が保存場外へ飛ぶと停止=True,
        全原本行の注文現金と含み一致=True, core_SHA256=hashlib.sha256(SOURCE.read_bytes()).hexdigest())
    (HERE / '短期板の独立合成監査.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False))


if __name__ == '__main__':
    main()
