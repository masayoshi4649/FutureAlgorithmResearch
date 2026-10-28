"""第二巡の保存親対応と消えた利益追加の会計差を人工記録で検査する。"""

import copy
import unittest

from analyze153r2 import compare_additions


def entry(index: int, price: float) -> dict:
    """比較に必要な人工新規の原判断参照を作る。

    引数: index(int)は判断添字、price(float)は約定価格。
    返り値: dictは保存新規Event。戦略再生はしない。
    """
    order = {"ID": index, "ParentID": 1, "Action": "new", "Reason": "人工追加", "Side": 1, "Quantity": 1,
             "DecisionIndex": index, "DecisionTime": 1800000000+index, "DecisionLine": index+1,
             "DecisionBid": price-1, "DecisionAsk": price, "Feature": {"Known": True, "MA": price, "Previous": price-1, "Slope": .5},
             "EntrySlope": .5, "PeakSlope": .5, "PeakGain": 0}
    return {"Order": order, "FillIndex": index+1, "FillLine": index+2, "FillTime": 1800000001+index,
            "Price": price, "FillBid": price-1, "FillAsk": price, "Gross": 0}


class DifferenceTest(unittest.TestCase):
    """同じ親の追加を失った場合も、その基準利益を消さずに残す。"""

    def test_lost_profitable_addition(self) -> None:
        """利益だった追加の欠落と初回玉出口の差を混同しない。

        引数: self(DifferenceTest)。返り値: None。
        """
        before = {"Session": "人工_Day", "Symbol": "NK225", "Config": {"id": "R03"}, "Gross": 400,
                  "Events": [entry(1, 100), entry(3, 110)],
                  "Lots": [{"ID": 1, "Quantity": 0, "Initial": 1, "Realized": -100},
                           {"ID": 2, "Quantity": 0, "Initial": 1, "Realized": 500}]}
        after = copy.deepcopy(before)
        after["Config"]["id"], after["Gross"] = "R04", -200
        after["Events"], after["Lots"] = after["Events"][:1], after["Lots"][:1]
        after["Lots"][0]["Realized"] = -200
        row = compare_additions(before, after)
        self.assertEqual(row["net_difference"], -600)
        self.assertEqual(row["matched_first_lot_difference"], -100)
        self.assertEqual(row["matched_add_lot_difference"], -500)
        self.assertEqual((row["omitted_winning_additions"], row["omitted_winning_reference_net"]), (1, 500))


if __name__ == "__main__":
    unittest.main()
