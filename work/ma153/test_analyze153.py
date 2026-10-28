"""保存会計の独立照合を人工値で検証する。金融戦略は実行しない。"""

import copy
import unittest

from analyze153 import account_case


def fixture() -> tuple[dict, dict]:
    """一つの新規玉を利益と損失に分けて返済した人工記録を作る。

    引数: なし。
    返り値: tuple[dict,dict]は時計資料と保存会計。
    """
    start = 1800000000.0
    scene = {"start": start, "end": start+25200, "kind": "Day", "partial": False, "us_open": 0,
             "qualification": {"NK225": {"book": {"first": {"last": 100, "time": "開始"}, "last": {"last": 105, "time": "末尾"}}}}}
    feature = {"Known": True, "MA": 100, "Previous": 99.99, "Slope": .3}
    events = []
    for index, at, action, side, qty, price, bid, ask, gross, closed, reason in (
        (2, start+100, "new", 1, 2, 100, 99, 100, 0, [], "傾き入口"),
        (4, start+200, "close", -1, 1, 110, 110, 111, 1000, [{"LotID": 1, "Quantity": 1, "EntryPrice": 100, "ExitPrice": 110, "Gross": 1000}], "比例枚数へ縮小"),
        (6, start+300, "close", -1, 1, 95, 95, 96, -500, [{"LotID": 1, "Quantity": 1, "EntryPrice": 100, "ExitPrice": 95, "Gross": -500}], "傾き反転"),
    ):
        order = {"ID": index//2, "ParentID": 1, "Action": action, "Reason": reason, "Side": side, "Quantity": qty,
                 "DecisionIndex": index-1, "DecisionLine": index, "DecisionTime": at-1,
                 "DecisionBid": bid, "DecisionAsk": ask, "Feature": feature,
                 "EntrySlope": .3, "PeakSlope": .4, "PeakGain": 10}
        events.append({"Order": order, "FillIndex": index, "FillLine": index+1, "FillTime": at, "Price": price,
                       "FillBid": bid, "FillAsk": ask, "Gross": gross, "Closed": closed})
    snapshots = []
    for index, at, bid, ask, side, qty, realized, unrealized in ((2, start+100, 99, 100, 1, 2, 0, -200),
                                                              (4, start+200, 110, 111, 1, 1, 1000, 1000),
                                                              (6, start+300, 95, 96, 0, 0, 500, 0),
                                                              (7, start+25140, 104, 105, 0, 0, 500, 0)):
        snapshots.append({"Time": at, "Index": index, "Bid": bid, "Ask": ask, "Side": side, "Quantity": qty,
                          "Realized": realized, "Unrealized": unrealized, "Equity": realized+unrealized})
    case = {"Session": "人工_Day", "Kind": "Day", "Symbol": "NK225", "Partial": False, "PointValue": 100,
            "Events": events, "Gross": 500, "Profit": 1000, "Loss": 500, "Unrealized": 0,
            "OpeningMid": 99.5, "ClosingMid": 104.5, "FirstKnownAt": start+90,
            "last_normal_quote": {"Time": start+25140, "Index": 7, "Line": 8, "Bid": 104, "Ask": 105},
            "HeldSeconds": 200, "EligibleSeconds": 25200, "KnownSeconds": 25000,
            "MaxQuantity": 2, "MaxReserved": 2, "FirstEntry": start+100, "LastEntry": start+100,
            "FlatAt": start+25140, "ObservationEnd": start+25140, "Pending": None,
            "MaximumDrawdown": 1500, "MinimumEquity": -200, "MinimumUnrealized": -200,
            "MaximumDrawdownAt": snapshots[2], "MaximumDrawdownFrom": snapshots[1],
            "MinimumEquityAt": snapshots[0], "MinimumUnrealizedAt": snapshots[0], "Snapshots": snapshots,
            "Lots": [{"ID": 1, "ParentID": 1, "Side": 1, "Initial": 2, "Quantity": 0, "Price": 100, "At": start+100, "Realized": 500}],
            "Parents": [{"ID": 1, "Realized": 500, "EntrySlope": .3, "PeakGain": 10, "PeakGainTime": start+200,
                         "WorstGain": -5, "WorstGainTime": start+300, "LastSlope": -.1, "LastSlopeTime": start+299,
                         "PeakSlope": .4, "Strengthened": False, "Anchor": 100, "ExitReason": "傾き反転"}]}
    return scene, case


class AccountTest(unittest.TestCase):
    """配賦会計と完結親会計の違い、および改変検出を確かめる。"""

    def test_partial_close_accounting(self) -> None:
        """分割返済の正負が親では相殺されることを確認する。

        引数: self(AccountTest)。返り値: None。
        """
        scene, case = fixture()
        row, internal = account_case(scene, case, "人工")
        self.assertEqual((row["profit"], row["loss"], row["net"]), (1000, 500, 500))
        self.assertEqual((row["parent_profit"], row["parent_loss"]), (500, 0))
        self.assertEqual((row["entries"], row["reductions"], row["held_seconds"]), (1, 1, 200))
        self.assertEqual(row["held_rate"], 200/25200)
        self.assertEqual(row["direction"], "上昇")
        self.assertEqual(internal["lots"], 1)

    def test_tampered_price_is_rejected(self) -> None:
        """保存利益だけでなく実約定側の価格改変も検出する。

        引数: self(AccountTest)。返り値: None。
        """
        scene, case = fixture()
        case = copy.deepcopy(case)
        case["Events"][1]["Price"] += 1
        with self.assertRaises(AssertionError):
            account_case(scene, case, "人工改変")

    def test_tampered_target_is_rejected(self) -> None:
        """同じ総収支に見せてもFIFO返済対象の改変は通さない。

        引数: self(AccountTest)。返り値: None。
        """
        scene, case = fixture()
        case = copy.deepcopy(case)
        case["Events"][1]["Closed"][0]["LotID"] = 2
        with self.assertRaises(AssertionError):
            account_case(scene, case, "人工改変")

    def test_partial_unrealized_is_separate(self) -> None:
        """途中場の未決済含みを確定利益へ混ぜず、正式分母も保つ。

        引数: self(AccountTest)。返り値: None。
        """
        scene, case = fixture()
        scene["partial"], scene["cutoff"] = True, scene["end"]
        case["Partial"], case["FlatAt"] = True, 0
        case["Events"] = case["Events"][:2]
        case["Gross"], case["Profit"], case["Loss"], case["Unrealized"] = 1000, 1000, 0, 400
        case["HeldSeconds"], case["EligibleSeconds"] = 25040, 25140
        case["Lots"][0]["Quantity"], case["Lots"][0]["Realized"] = 1, 1000
        case["open_parent"] = case["Parents"].pop()
        case["open_parent"]["Realized"] = 1000
        case["Snapshots"] = case["Snapshots"][:2]+[case["Snapshots"][-1]]
        final = case["Snapshots"][-1]
        final.update(Side=1, Quantity=1, Realized=1000, Unrealized=400, Equity=1400)
        case["MaximumDrawdown"], case["MaximumDrawdownAt"] = 600, final
        row, _ = account_case(scene, case, "人工途中")
        self.assertEqual((row["profit"], row["net"], row["unrealized"], row["equity"]), (1000, 1000, 400, 1400))
        self.assertEqual((row["parent_profit"], row["open_parent_realized"], row["remaining_qty"]), (0, 1000, 1))
        self.assertEqual(row["held_rate"], 25040/25200)


if __name__ == "__main__":
    unittest.main()
