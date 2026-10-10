"""未来行での約定・場内返済・会計の研究用検査。"""

import unittest
import numpy as np
from replay import execute


SPEC = dict(stop_atr=1., activation_atr=2., trail_atr=1., hold_seconds=0,
            exit_neutral=False, failure_seconds=0, failure_atr=0,
            cooldown_seconds=0)


def fixture(prices: list, times: list | None = None) -> dict:
    """機能: 検査専用の原本配列を作る。

    引数: prices(list)、times(list|None)。返り値: 再生入力(dict)。
    """
    n = len(prices)
    return dict(session='合成_Day', symbol='TOPIX', last=np.array(prices, float),
                time_s=np.array(times if times else range(n), float), seq=np.arange(n),
                atr=np.full(n, 2.), limit=1000.)


class ReplayTest(unittest.TestCase):
    """約定タイミングと会計を独立した例で確認する。"""

    def test_next_valid_row_and_stop(self):
        """機能: 判断後の価格で建て、損切りも判断後の価格で返す。

        引数: self(ReplayTest)。返り値: なし(None)。
        """
        result = execute(fixture([100, 103, 101, 99, 120]), np.array([[0, 1]]), SPEC)
        self.assertEqual(result['net'], -20000)
        self.assertEqual(result['orders'][0][7], 103)
        self.assertEqual(result['orders'][1][7], 99)
        self.assertEqual(result['orders'][1][2:4], [2, 3])

    def test_trail_and_reflection(self):
        """機能: 利益追跡と上下対称の損益を確認する。

        引数: self(ReplayTest)。返り値: なし(None)。
        """
        p = np.array([100, 100, 106, 105, 103, 104], float)
        long = execute(fixture(p), np.array([[0, 1]]), SPEC)
        short = execute(fixture(200 - p), np.array([[0, -1]]), SPEC)
        self.assertEqual(long['net'], 20000)
        self.assertEqual(long['net'], short['net'])
        self.assertEqual(long['trades'][0][7], 2)

    def test_session_flat(self):
        """機能: 場末判断の後続行で返済し、保有を残さない。

        引数: self(ReplayTest)。返り値: なし(None)。
        """
        ready = fixture([100, 100, 101, 102], [0, 1, 1000, 1001])
        result = execute(ready, np.array([[0, 1]]), SPEC)
        self.assertEqual(result['net'], 10000)
        self.assertEqual(result['trades'][0][7], 8)

    def test_future_truncation(self):
        """機能: 将来を切断しても既に決まった約定が変わらない。

        引数: self(ReplayTest)。返り値: なし(None)。
        """
        prices = [100, 100, 106, 105, 103, 104, 105, 104, 102, 101]
        decisions = np.array([[0, 1], [6, -1]])
        full = execute(fixture(prices), decisions, SPEC, finish=False)
        for end in range(2, len(prices)):
            cut = execute(fixture(prices[:end]), decisions[decisions[:, 0] < end], SPEC, finish=False)
            known = [row for row in full['orders'] if row[3] < end]
            self.assertEqual(cut['orders'], known)

    def test_unfinished_session_fails(self):
        """機能: 未返済を黙って確定損益と見なさない。

        引数: self(ReplayTest)。返り値: なし(None)。
        """
        with self.assertRaises(ValueError):
            execute(fixture([100, 100]), np.array([[0, 1]]), SPEC)


if __name__ == '__main__':
    unittest.main()
