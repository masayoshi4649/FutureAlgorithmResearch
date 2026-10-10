"""新規足・返済足の高安を利益診断へ混入させないことを確認する。"""

import unittest

import pandas as pd

from audit_baseline import audit_trade


class BaselineAuditTests(unittest.TestCase):
    """機能: 元方式診断の時刻境界と買売対称性を検査する。

    引数: unittest が生成する試験インスタンス。
    返り値: 試験結果は unittest に報告する。
    """

    def setUp(self) -> None:
        """機能: 高安と確定終値の差が大きい人工足を用意する。

        引数: なし。
        返り値: なし (None)。
        """
        times = pd.date_range("2026-09-23 09:00", periods=3, freq="min", tz="Asia/Tokyo")
        self.candles = pd.DataFrame(dict(close=[110, 120, 999], high=[500, 140, 1000], low=[90, 100, 1]), index=times)
        self.trade = dict(symbol="NK225", session="2026-09-23_Day", side=1, entry_time=times[0],
                          exit_time=times[2], entry_price=100, exit_price=115, atr=10,
                          closed=True, net_points=-5, reason="境界検査")

    def test_close_only_and_reference_boundaries(self) -> None:
        """機能: 返済足の終値・高値、新規足高値を主指標に使わない。

        引数: なし。
        返り値: なし (None)。
        """
        result = audit_trade(self.trade, self.candles, 1)
        self.assertEqual(result["最大含み益費用前円"], 20000)
        self.assertEqual(result["最大含み益観測時刻"], "2026-09-23T09:02:00+09:00")
        self.assertEqual(result["最終利益費用後円"], -5000)
        self.assertEqual(result["利益返却円"], 5000)
        self.assertEqual(result["足高安参考最大益費用前円"], 40000)
        self.assertEqual(result["新規足高安を含む参考最大益費用前円"], 400000)
        self.assertEqual(result["初期損切価格"], 70)

    def test_short_and_stop_rounding(self) -> None:
        """機能: 売りは低値側で含み益を評価し、初期逆指値を上へ丸める。

        引数: なし。
        返り値: なし (None)。
        """
        self.trade.update(side=-1, entry_price=130, exit_price=115, net_points=-5)
        result = audit_trade(self.trade, self.candles, 1)
        self.assertEqual(result["最大含み益費用前円"], 20000)
        self.assertEqual(result["初期損切価格"], 160)
        self.assertEqual(result["足高安参考最大益費用前円"], 30000)

    def test_same_bar_exit_has_no_close_observation(self) -> None:
        """機能: 同足で返済した場合に足終値を保有中の価格と扱わない。

        引数: なし。
        返り値: なし (None)。
        """
        self.trade.update(exit_time=self.trade["entry_time"], exit_price=90, net_points=-30)
        result = audit_trade(self.trade, self.candles, 1)
        self.assertEqual(result["最大含み益費用前円"], 0)
        self.assertEqual(result["利益返却円"], 10000)
        self.assertIsNone(result["残存率費用後"])


if __name__ == "__main__":
    unittest.main()
