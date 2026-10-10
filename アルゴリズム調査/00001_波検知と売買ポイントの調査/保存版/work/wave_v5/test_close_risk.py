"""終値評価の費用時点、同分返済、両脚相殺を検査する。"""

import unittest

import pandas as pd

from close_risk import mark_to_close


class CloseRiskTests(unittest.TestCase):
    """機能: 時価評価と実現純損益の一致を合成系列で検査する。

    引数: unittestのメソッド名 (str)。返り値: テストケース (CloseRiskTests)。
    """

    def setUp(self) -> None:
        """機能: 上下変動のある３本の終値を用意する。

        引数: self (CloseRiskTests)。返り値: なし (None)。
        """
        self.index = pd.date_range("2026-09-23 09:00", periods=3, freq="min", tz="Asia/Tokyo")
        self.one = pd.DataFrame(dict(close=[90.0, 120.0, 110.0]), index=self.index)

    def test_cost_paid_on_entry_and_profit_can_draw_down(self) -> None:
        """機能: 最終利益でも新規費用と含み損が終値DDへ現れることを確認する。

        引数: self (CloseRiskTests)。返り値: なし (None)。
        """
        trade = dict(side=1, entry_time=self.index[0], exit_time=self.index[2], entry_price=100.0, exit_price=110.0, net_points=8.0, closed=True)
        risk, curve = mark_to_close(self.one, [trade], 1.0)
        self.assertEqual(curve.equity_points.tolist(), [-12.0, 18.0, 8.0])
        self.assertEqual(risk["max_drawdown_points"], 12.0)
        self.assertEqual(risk["worst_aggregate_unrealized_loss_points"], 10.0)
        self.assertEqual(risk["realized_loss_points"], 0.0)

    def test_two_legs_are_summed_at_same_minute(self) -> None:
        """機能: 買売両脚を同時に合算しつつ、単脚の含み損を区別する。

        引数: self (CloseRiskTests)。返り値: なし (None)。
        """
        long = dict(side=1, entry_time=self.index[0], exit_time=self.index[2], entry_price=100.0, exit_price=110.0, net_points=8.0, closed=True)
        short = dict(side=-1, entry_time=self.index[0], exit_time=self.index[1], entry_price=100.0, exit_price=120.0, net_points=-22.0, closed=True)
        risk, curve = mark_to_close(self.one, [long, short], 1.0)
        self.assertEqual(curve.equity_points.tolist(), [-4.0, -4.0, -14.0])
        self.assertEqual(risk["max_drawdown_points"], 14.0)
        self.assertEqual(risk["worst_aggregate_unrealized_loss_points"], 0.0)
        self.assertEqual(risk["worst_single_leg_unrealized_loss_points"], 10.0)

    def test_same_minute_closed_trade_is_not_still_open(self) -> None:
        """機能: 新規と返済が同じ分なら、その分末に終値で未決済評価しない。

        引数: self (CloseRiskTests)。返り値: なし (None)。
        """
        trade = dict(side=1, entry_time=self.index[0], exit_time=self.index[0], entry_price=100.0, exit_price=105.0, net_points=3.0, closed=True)
        risk, curve = mark_to_close(self.one, [trade], 1.0)
        self.assertEqual(curve.equity_points.tolist(), [3.0, 3.0, 3.0])
        self.assertEqual(risk["worst_aggregate_unrealized_loss_points"], 0.0)


if __name__ == "__main__":
    unittest.main()
