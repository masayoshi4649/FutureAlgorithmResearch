"""交互作用の担当分離・未来ラベル不使用を人工確認する。"""

import unittest
import numpy as np
from analyze159r2 import expand_rows, configure, core


class InteractionTest(unittest.TestCase):
    """追加交互作用だけを検査する。"""

    def test_interaction_unknown(self) -> None:
        """非該当担当は0、該当担当の未知はNoneとして区別する。

        引数: self(InteractionTest)。返り値: None。
        """
        rows = [{"owner": "core", "features": {"M": None, "T": None, "change": None}},
                {"owner": "episode", "features": {"M": .8, "T": .5, "change": .1}},
                {"owner": "addon", "features": {"M": .6, "T": .7, "change": -.2}}]
        expanded = expand_rows(rows)
        self.assertIsNone(expanded[0]["features"]["core_M"])
        self.assertEqual(expanded[0]["features"]["addon_M"], 0.)
        self.assertEqual(expanded[1]["features"]["core_T"], 0.)
        self.assertEqual(expanded[2]["features"]["addon_change"], -.2)
        self.assertNotIn("core_M", rows[0]["features"])

    def test_future_labels(self) -> None:
        """P4/P5の学習が検査ラベルへ依存しないことを検査する。

        引数: self(InteractionTest)。返り値: None。
        """
        configure()
        rows = []
        for i in range(18):
            owner = ["core", "addon", "episode"][i % 3]
            rows.append({"owner": owner, "features": {"core": float(owner == "core"), "addon": float(owner == "addon"),
                "M": i / 20, "T": (i % 4) / 4, "change": (i - 9) / 100, "agreement": float(i % 2),
                "own_known": 1., "peer_known": float(i % 2), "ofi_known": 1.},
                "win": int(i % 2), "initial_pt": i * 10 - 85})
        train, test = expand_rows(rows[:15]), expand_rows(rows[15:])
        for model in ["P4", "P5"]:
            p, e, state = core.fit_predict(train, test, model)
            for row in test:
                row["win"], row["initial_pt"] = 1 - row["win"], 1e9
            p2, e2, state2 = core.fit_predict(train, test, model)
            np.testing.assert_equal(p, p2)
            np.testing.assert_equal(e, e2)
            self.assertEqual(state, state2)


if __name__ == "__main__":
    unittest.main()
