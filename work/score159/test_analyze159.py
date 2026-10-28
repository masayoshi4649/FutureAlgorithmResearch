"""支持校正の人工検査。金融原板・売買処理は呼び出さない。"""

import unittest
import numpy as np
from analyze159 import ranks, rho, describe, fit_predict, matrix


class CalibrationTest(unittest.TestCase):
    """順位・場抽出・学習前後分離を人工数値で検査する。"""

    def test_rank_ties(self) -> None:
        """同順位と定数相関の未算出を検査する。

        引数: self(CalibrationTest)。返り値: None。
        """
        np.testing.assert_equal(ranks(np.array([5., 2., 2.])), [3., 1.5, 1.5])
        self.assertAlmostEqual(rho(np.array([1., 2., 3.]), np.array([3., 2., 1.])), -1.)
        self.assertIsNone(rho(np.ones(3), np.arange(3)))

    def test_cluster_weighted_median(self) -> None:
        """同じ場の全親が重複抽出される手計算を検査する。

        引数: self(CalibrationTest)。返り値: None。
        """
        rows = []
        for day, value in [("a", 1.), ("a", 3.), ("b", 10.)]:
            rows.append({"session": day, "win": 1, "flat": 0, "initial_pt": value, "mfe": value,
                         "mae": -value, "parent_pt_initial": value, "parent_pt_all": value})
        got = describe(rows, ["a", "b"], np.array([[2, 0], [0, 2], [1, 1]]))
        np.testing.assert_allclose(got["initial_pt"]["cluster_median_95"], np.quantile([2., 10., 3.], [.025, .975]))

    def test_training_transform_and_future_label(self) -> None:
        """検査日の値とラベルが学習変換・係数へ混入しないことを検査する。

        引数: self(CalibrationTest)。返り値: None。
        """
        train = [{"features": {"core": 0., "addon": 0., "score": s, "own_known": 1., "peer_known": 1., "ofi_known": 1.},
                  "win": int(s > .4), "initial_pt": s * 100 - 40} for s in [0., .2, .4, .6, .8, 1.]]
        test = [{"features": dict(train[0]["features"], score=100.), "win": 0, "initial_pt": -1e9}]
        p, e, state = fit_predict(train, test, "P1")
        test[0]["win"], test[0]["initial_pt"] = 1, 1e9
        p2, e2, state2 = fit_predict(train, test, "P1")
        np.testing.assert_equal(p, p2)
        np.testing.assert_equal(e, e2)
        self.assertEqual(state, state2)
        self.assertAlmostEqual(state["transforms"]["score"]["center"], .5)
        test[0]["features"]["score"] = None
        _, z, _ = matrix(train, test, ["score"])
        self.assertEqual(z[0, 1], 0.)


if __name__ == "__main__":
    unittest.main()
