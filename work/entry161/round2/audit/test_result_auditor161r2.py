"""事後監査の板算式を人工板だけで検査する。"""

import copy
import unittest

import numpy as np

from audit_results161r2 import distance_depth, displayed_flow


def raw():
    """手計算できる四行の最良板を作る。

    引数: なし。返り値: ndarray。
    """
    return np.array([[0, 105, 100, 110, 10, 10, 1], [5, 105, 100, 110, 20, 10, 2],
                     [10, 115, 110, 120, 20, 30, 3], [15, 115, 110, 120, 10, 40, 4]], dtype=float)


class BoardAuditor(unittest.TestCase):
    """同値段補充、気配更新、時刻打切りを独立した手計算と比較する。"""

    def test_manual_flow(self):
        """買補充、気配上昇、売補充を三つの隣接変化として平均する。

        引数: self(BoardAuditor)。返り値: None。
        """
        result = displayed_flow(raw(), 3)
        self.assertEqual(result["ofi15_count"], 3)
        self.assertAlmostEqual(result["ofi15"], (.2 + .375 - .2) / 3)
        self.assertAlmostEqual(result["bid_refill15"], 1 / 9)
        self.assertAlmostEqual(result["ask_refill15"], 1 / 21)
        self.assertAlmostEqual(result["ofi15_coverage"], 3 / 4)

    def test_same_clock_later_row_is_excluded(self):
        """同時計でも判断の後の物理行を平均へ入れない。

        引数: self(BoardAuditor)。返り値: None。
        """
        before = raw()
        future = np.vstack([before, [15, 150, 140, 160, 500, 1, 5]])
        self.assertEqual(displayed_flow(before, 3), displayed_flow(future, 3))

    def test_gap_and_invalid_pair_are_not_quantity_changes(self):
        """異常板や15秒超離れた板の差を数量変化へ作らない。

        引数: self(BoardAuditor)。返り値: None。
        """
        values = raw(); values[1, 3] = 90
        result = displayed_flow(values, 3)
        self.assertEqual(result["ofi15_count"], 1)
        self.assertTrue(np.isnan(result["ofi15"]))
        values = raw(); values[3, 0] = 50
        result = displayed_flow(values, 3)
        self.assertEqual(result["ofi15_count"], 0)
        self.assertTrue(np.isnan(result["bid_refill15"]))

    def test_depth_distance_and_invalid_price_order(self):
        """10段距離重みの比と価格順不正による欠測を手計算する。

        引数: self(BoardAuditor)。返り値: None。
        """
        board = {}
        for i in range(1, 11):
            board["Buy" + str(i)] = dict(Price=1000 - (i - 1) * 10, Qty=10)
            board["Sell" + str(i)] = dict(Price=1010 + (i - 1) * 10, Qty=20)
        result = distance_depth(board)
        self.assertAlmostEqual(result["depth_imb"], -1/3)
        self.assertAlmostEqual(result["weighted_bid"], sum(10/i for i in range(1, 11)))
        broken = copy.deepcopy(board); broken["Buy2"]["Price"] = 1020
        self.assertTrue(np.isnan(distance_depth(broken)["depth_imb"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
