"""出口実装と独立した人工相場で、先読み・約定順序・保護更新を検査する。"""

from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from exit_engine import ExitRule, KINDS, _bar_exit, simulate


def fixture(bars: list[list[float]], signs: list[int] | None = None, side: int = 1) -> tuple:
    """機能: 指定足列と既知方向で、固定新規の人工再生入力を用意する。

    引数: bars (list[list[float]]) は始高安終、signs (list[int] | None) は既知方向、side (int) は売買。
    返り値: 入力・方向・入口設定・固定新規 (tuple)。
    """
    size = len(bars)
    times = pd.date_range("2026-09-23 09:30", periods=size, freq="min", tz="Asia/Tokyo")
    data = dict(symbol="NK225", session="人工日中", tick=1.0, times=times, values=np.array(bars, dtype=float),
                positions=np.arange(size), minutes=np.arange(size), limit_min=size-1, limit=times[-1],
                atr=np.full(size, 10.0), ref=np.full(size, 100.0), z=pd.DataFrame(index=times-pd.Timedelta(minutes=2)))
    direction = np.array(signs if signs is not None else [side] * size)
    schedule = direction, np.full(size, 10)
    cfg = SimpleNamespace(key="人工入口", entry="trail", reverse=False, rearm="cooldown", cooldown=45, warmup=0, confirm=1, offset=1)
    anchor = dict(symbol="NK225", session="人工日中", entry_time=times[0], signal_time=times[0], entry_price=100.0, atr=10.0, side=side)
    return data, schedule, cfg, anchor


class ExitIndependentTests(unittest.TestCase):
    """機能: 調整対象コードの内部計算を期待値として流用せず、返済結果を確認する。

    引数: unittest が生成する試験インスタンス。
    返り値: 検査結果は unittest に報告する。
    """

    def test_initial_loss_fixed_for_every_kind(self) -> None:
        """機能: 全系統で初期損切りが2.5Aに固定されていることを確認する。

        引数: なし。返り値: なし (None)。
        """
        for side in (1, -1):
            for kind in KINDS:
                data, schedule, cfg, anchor = fixture([[100, 100, 100, 100], [100, 100, 100, 100]], side=side)
                trade = simulate(data, schedule, cfg, ExitRule(kind, width=.5), [anchor])[0]
                self.assertEqual(trade["initial_stop"], 75 if side == 1 else 125)

    def test_profit_lock_does_not_retroactively_hit_same_bar(self) -> None:
        """機能: 当足の高値で保護価格を上げても、その足の過去安値で返済しない。

        引数: なし。返り値: なし (None)。
        """
        data, schedule, cfg, anchor = fixture([[100, 100, 100, 100], [100, 130, 90, 129], [126, 127, 123, 125], [125, 125, 125, 125]])
        trade = simulate(data, schedule, cfg, ExitRule("profit_lock", trigger=1, retain=.8), [anchor])[0]
        self.assertEqual(trade["exit_time"], data["times"][2])
        self.assertEqual(trade["exit_price"], 124)
        self.assertEqual(trade["mfe_close_points"], 29)

    def test_entry_bar_high_does_not_activate_profit_lock(self) -> None:
        """機能: 新規成立前かもしれない同足高値を利益保護の起動に使わない。

        引数: なし。返り値: なし (None)。
        """
        data, schedule, cfg, anchor = fixture([[100, 200, 90, 100], [100, 105, 90, 100], [100, 100, 100, 100]])
        trade = simulate(data, schedule, cfg, ExitRule("profit_lock", trigger=1, retain=.8), [anchor])[0]
        self.assertEqual(trade["exit_time"], data["times"][2])
        self.assertEqual(trade["reason"], "セッション内の時刻返済")

    def test_stop_gap_is_adverse_for_both_sides(self) -> None:
        """機能: 保護価格を飛び越えた始値では不利な始値で返済する。

        引数: なし。返り値: なし (None)。
        """
        for side, stop, bar, expected in ((1, 75, [60, 70, 50, 65], 60), (-1, 125, [140, 150, 130, 145], 140)):
            result = _bar_exit(dict(side=side, stop=stop, target=None), np.array(bar))
            self.assertEqual(result[1], expected)

    def test_target_and_stop_order_ambiguity(self) -> None:
        """機能: 足内両条件接触は損切り優先、既知始値での利確成立は先に扱う。

        引数: なし。返り値: なし (None)。
        """
        active = dict(side=1, stop=75, target=120, ambiguous_exit=False)
        self.assertEqual(_bar_exit(active.copy(), np.array([100, 130, 70, 110]))[1], 75)
        self.assertEqual(_bar_exit(active.copy(), np.array([130, 135, 70, 110]))[1], 120)
        self.assertIsNone(_bar_exit(active.copy(), np.array([100, 130, 90, 110]), new_entry=True))
        self.assertEqual(_bar_exit(active.copy(), np.array([100, 130, 90, 125]), new_entry=True)[1], 120)
        self.assertEqual(_bar_exit(active.copy(), np.array([100, 130, 70, 125]), new_entry=True)[1], 75)

    def test_protection_delay_one_and_two_bars(self) -> None:
        """機能: 確定した保護更新が追加１足・２足後まで有効にならない。

        引数: なし。返り値: なし (None)。
        """
        bars = [[100, 100, 100, 100], [100, 130, 95, 129]] + [[126, 127, 123, 125]] * 4
        for delay in (0, 1, 2):
            data, schedule, cfg, anchor = fixture(bars)
            trade = simulate(data, schedule, cfg, ExitRule("profit_lock", trigger=1, retain=.8, delay=delay), [anchor])[0]
            self.assertEqual(trade["exit_time"], data["times"][2 + delay])
            self.assertEqual(trade["exit_price"], 124)

    def test_market_condition_uses_prior_peak_and_remains_pending(self) -> None:
        """機能: 当足高値で成行条件を先読みせず、確定した返済判断を遅延して実行する。

        引数: なし。返り値: なし (None)。
        """
        bars = [[100, 100, 100, 100], [100, 130, 95, 125], [126, 135, 123, 134], [133, 136, 130, 134], [135, 140, 133, 137], [137, 137, 137, 137]]
        for delay in (0, 1, 2):
            data, schedule, cfg, anchor = fixture(bars)
            trade = simulate(data, schedule, cfg, ExitRule("stagnation", trigger=1, window=1, delay=delay), [anchor])[0]
            self.assertEqual(trade["exit_time"], data["times"][2 + delay])
            self.assertEqual(trade["exit_price"], bars[2 + delay][0])
            self.assertEqual(trade["reason"], "有利極値の更新停滞による返済")

    def test_reversal_needs_profit_already_observed(self) -> None:
        """機能: 反転返済の利益条件は当足で新しく付けた高値を参照しない。

        引数: なし。返り値: なし (None)。
        """
        data, schedule, cfg, anchor = fixture([[100, 100, 100, 100], [100, 130, 95, 125], [126, 130, 120, 125], [125, 125, 125, 125]], signs=[1, -1, -1, -1])
        trade = simulate(data, schedule, cfg, ExitRule("reversal", trigger=1, window=1), [anchor])[0]
        self.assertEqual(trade["exit_time"], data["times"][2])
        self.assertEqual(trade["exit_price"], 126)

    def test_exit_bar_prices_not_in_mfe(self) -> None:
        """機能: 退出足の返済後の高値と終値を最大含み益へ加算しない。

        引数: なし。返り値: なし (None)。
        """
        data, schedule, cfg, anchor = fixture([[100, 100, 100, 100], [100, 120, 95, 110], [110, 999, 50, 900], [100, 100, 100, 100]])
        trade = simulate(data, schedule, cfg, ExitRule("baseline"), [anchor])[0]
        self.assertEqual(trade["mfe_close_points"], 10)
        self.assertEqual(trade["mfe_extreme_points"], 20)
        self.assertEqual(trade["exit_price"], 80)
        self.assertEqual(trade["giveback_points"], 30)


if __name__ == "__main__":
    unittest.main()
