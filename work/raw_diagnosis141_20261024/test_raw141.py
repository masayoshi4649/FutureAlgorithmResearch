"""原板特徴の因果性と数量差の意味を合成板で確認する。売買再生はしない。"""

from copy import deepcopy
import json
from pathlib import Path
import unittest

import numpy as np

import raw141


def sample() -> dict:
    """時計不変、数量補充、価格移動、時計欠測を含む小さな板を作る。

    引数: なし。
    返り値: dictは5行の合成入力。実データの代用品として損益には使わない。
    """
    start, _ = raw141.bounds("2026-10-23_Day")
    bid = np.array([100.0, 100.0, 101.0, 101.0, 101.0])
    ask = bid + 1.0
    buy_price = bid[:, None] - np.arange(10)[None, :]
    sell_price = ask[:, None] + np.arange(10)[None, :]
    buy_qty = np.full((5, 10), 3.0)
    sell_qty = np.full((5, 10), 4.0)
    buy_qty[:, 0] = [10, 15, 12, 12, 14]
    sell_qty[:, 0] = [20, 15, 18, 18, 17]
    return {"time_s": np.array([start, start, start + 1, np.nan, start + 2]),
            "volume_time_s": np.array([start, start, start + 1, start + 1, start + 2]),
            "last": np.array([100.0, 100.0, 101.0, 101.0, 101.0]), "volume": np.array([10., 10., 12., 1., 2.]),
            "buy_price": buy_price, "sell_price": sell_price, "buy_qty": buy_qty, "sell_qty": sell_qty}


class RawFeatureChecks(unittest.TestCase):
    """数値定義と未来行不使用の確認。"""

    def test_quantity_and_ofi(self) -> None:
        """同じ最良価格の数量差とOFIの符号を確認する。

        引数: self(RawFeatureChecks)はテスト実体。
        返り値: None。
        """
        data = sample()
        raw141.features(data, "NK225", "2026-10-23_Day")
        self.assertEqual(data["same_price_buy_increase"][1], 5)
        self.assertEqual(data["same_price_sell_decrease"][1], 5)
        self.assertEqual(data["ofi"][1], 10)
        self.assertAlmostEqual(data["ofi_normalized"][1], 1 / 6)
        self.assertEqual(data["ofi"][2], 27)
        self.assertTrue(data["price_clock_same"][1])
        self.assertTrue(data["book_changed"][1])
        self.assertTrue(data["book_valid"][3])
        self.assertFalse(data["price_clock_valid"][3])
        self.assertFalse(data["in_session"][3])
        self.assertTrue(data["volume_reset"][3])
        self.assertTrue(np.isnan(data["volume_delta"][3]))

    def test_prefix_invariance(self) -> None:
        """後続原行を追加しても既存時点の特徴が変わらないことを確認する。

        引数: self(RawFeatureChecks)はテスト実体。
        返り値: None。
        """
        source = sample()
        complete = deepcopy(source)
        raw141.features(complete, "NK225", "2026-10-23_Day")
        for length in range(1, len(source["time_s"])):
            prefix = {key: values[:length].copy() for key, values in source.items()}
            raw141.features(prefix, "NK225", "2026-10-23_Day")
            for key, values in prefix.items():
                np.testing.assert_allclose(values, complete[key][:length], rtol=0, atol=0, equal_nan=True, err_msg=key)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RawFeatureChecks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    proof = {"passed": result.wasSuccessful(), "tests": result.testsRun, "financial_replays": 0,
             "checks": ["同価格数量差とOFIの符号", "価格時計欠測と板資格の分離", "出来高リセットをゼロ補正しない", "全特徴の原行prefix不変性"]}
    (Path(__file__).parent / "非金融特徴の合成確認141.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
