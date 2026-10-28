"""価格尺度の記述器を人工経路で確認する。"""
import unittest
import numpy as np
from measure162 import window


class MeasureTests(unittest.TestCase):
    """入口の方向対称性と欠測の扱いを確認する。"""

    def market(self, times, mids):
        """人工正常板を作る。

        引数: times/mids(list)。返り値: dict。
        """
        m = np.asarray(mids, dtype=float)
        return dict(time=np.asarray(times, dtype=float), mid=m, bid=m-5, ask=m+5,
                    valid=np.ones(len(m), dtype=bool))

    def test_reversal_and_mirror(self):
        """進行30から20の戻しと上下鏡像を確認する。

        引数: なし。返り値: なし。
        """
        a = self.market([0, 1, 2, 3, 5], [1000, 980, 970, 980, 990])
        b = self.market([0, 1, 2, 3, 5], [1000, 1020, 1030, 1020, 1010])
        wa, wb = window(a, 0, 1, 5, np.arange(5)), window(b, 0, -1, 5, np.arange(5))
        self.assertEqual(wa, wb)
        self.assertEqual(wa["cover_direction_excursion_pt"], 30)
        self.assertEqual(wa["peak_giveback_pt"], 20)
        self.assertEqual(wa["giveback_clock_s"], 3)

    def test_no_new_clock(self):
        """同秒の値動きを1秒後の新時計観測と混同しない。

        引数: なし。返り値: なし。
        """
        a = self.market([0, 0, 3], [1000, 990, 980])
        result = window(a, 0, 1, 1, np.arange(3))
        self.assertEqual(result["quality"], "新価格時計なし")
        self.assertNotIn("change_pt", result)

    def test_gap_and_end(self):
        """空白と場末の不足をゼロ変動へ置き換えない。

        引数: なし。返り値: なし。
        """
        a = self.market([0, 20, 30], [1000, 980, 990])
        result = window(a, 0, 1, 30, np.arange(3))
        self.assertEqual(result["max_clock_gap_s"], 20)
        self.assertEqual(window(a, 0, 1, 60, np.arange(3))["quality"], "場末不足")


if __name__ == "__main__":
    unittest.main()
