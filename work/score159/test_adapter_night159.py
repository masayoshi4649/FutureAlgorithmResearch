"""夜間Source保存値の接続を人工データだけで確認する。売買再生は行わない。"""

from copy import deepcopy
import unittest
from adapter_night159 import adapt_saved, features_night, execution_ok


def source(phase: str, side: int = 1) -> dict:
    """部分返済を含む1親を人工Source保存形式で組み立てる。

    引数: phase(str)、side(int)。返り値: dictは未来売買処理を必要としない固定会計。
    """
    support = {"Known": True, "M": .5, "T": .6, "Own5": side, "Own15": side * 3,
               "Own120": side * 4, "components": {"PeerKnown": False, "OFIKnown": True}}
    initial = {"Phase": phase, "Parent": "core/1", "Owner": "core", "Side": side,
               "Quantity": 2, "Time": 100., "Index": 1, "Support": support}
    new = {"id": "n", "owner": "core", "campaign": 1, "action": "new", "side": side,
           "quantity": 2, "source_index": 1, "time": 100.}
    events = [{"Phase": phase, "Signal": new, "FillIndex": 2, "FillTime": 101., "Price": 1000., "Gross": 0.}]
    for n, price in [(1, 1000. + side * 30), (2, 1000. - side * 10)]:
        close = {"id": f"c{n}", "owner": "core", "campaign": 1, "action": "close", "side": -side,
                 "quantity": 1, "source_index": 2 * n + 1, "time": 100. + 2 * n,
                 "targets": [{"id": "n-玉", "quantity": 1}]}
        events.append({"Phase": phase, "Signal": close, "FillIndex": 2 * n + 2,
                       "FillTime": 101. + 2 * n, "Price": price, "Gross": side * (price - 1000.) * 100})
    lot = {"ID": "n-玉", "Owner": "core", "Campaign": 1, "Side": side, "Quantity": 2, "Remaining": 0,
           "Entry": 1000., "At": 101., "Gross": 2000., "Best": 50., "Worst": -20.}
    return {"Phase": phase, "Method": "P05" if phase == "前半" else "D07",
            "Initials": [initial], "Events": events, "Lots": {"n-玉": lot}}


class AdapterNightTest(unittest.TestCase):
    """担当の名前空間・初回玉・部分返済・未知支持を確認する。"""

    def test_execution_receipt(self) -> None:
        """不足・不成功の実行証跡を成功へ変換しない。

        引数: self(AdapterNightTest)。返り値: None。
        """
        self.assertTrue(execution_ok({"exit_code": 0, "sources_unchanged": True, "raw_files_checked": 162}))
        self.assertTrue(execution_ok({"終了コード": 0, "参照改変数": 0}))
        for receipt in [{}, {"exit_code": 1, "sources_unchanged": True, "raw_files_checked": 162},
                        {"exit_code": 0, "sources_unchanged": False, "raw_files_checked": 162},
                        {"exit_code": 0, "sources_unchanged": True}, {"exit_code": "0", "sources_unchanged": True, "raw_files_checked": 162}]:
            self.assertFalse(execution_ok(receipt))

    def test_phase_and_side(self) -> None:
        """同IDの前後時間帯を分離し、買売両方の部分返済を等量評価する。

        引数: self(AdapterNightTest)。返り値: None。
        """
        saved = {"scene": {"kind": "Night", "session": "2026-09-21_Night"},
                 "sources": [source("前半"), source("後半", -1)]}
        rows, pending = adapt_saved(saved)
        self.assertEqual([r["parent"] for r in rows], ["前半/core/1", "後半/core/1"])
        self.assertEqual([r["initial_pt"] for r in rows], [10., 10.])
        self.assertEqual([r["features"]["post"] for r in rows], [0., 1.])
        self.assertEqual([r["features"]["change"] for r in rows], [0., 0.])
        self.assertEqual(pending, [])

    def test_unknown_and_unfilled(self) -> None:
        """自己未知を支持0へ変換せず、途中未約定を母集団から黙って捨てない。

        引数: self(AdapterNightTest)。返り値: None。
        """
        item = source("前半")
        item["Initials"][0]["Support"]["Known"] = False
        saved = {"scene": {"kind": "Night", "session": "2026-10-26_Night"}, "sources": [item]}
        rows, _ = adapt_saved(saved)
        self.assertIsNone(rows[0]["score"])
        self.assertEqual(rows[0]["qualification"], "既知途中場の完了版確認")
        item["Events"], item["Lots"] = [], {}
        with self.assertRaises(AssertionError):
            adapt_saved(saved)
        saved["scene"]["partial"] = True
        rows, partial = adapt_saved(saved)
        self.assertEqual(rows, [])
        self.assertEqual(partial[0]["status"], "初回未約定")

    def test_addition_not_initial(self) -> None:
        """同じ親の追加玉の損益と極値を初回玉へ混ぜない。

        引数: self(AdapterNightTest)。返り値: None。
        """
        item = source("前半")
        add = {"id": "add", "owner": "core", "campaign": 1, "action": "new", "side": 1,
               "quantity": 1, "source_index": 2, "time": 101.}
        close = {"id": "add_close", "owner": "core", "campaign": 1, "action": "close", "side": -1,
                 "quantity": 1, "source_index": 7, "time": 106., "targets": [{"id": "add-玉", "quantity": 1}]}
        item["Events"].insert(1, {"Phase": "前半", "Signal": add, "FillIndex": 3, "FillTime": 102., "Price": 1020., "Gross": 0.})
        item["Events"].append({"Phase": "前半", "Signal": close, "FillIndex": 8, "FillTime": 107., "Price": 1040., "Gross": 2000.})
        item["Lots"]["add-玉"] = {"ID": "add-玉", "Owner": "core", "Campaign": 1, "Side": 1, "Quantity": 1,
            "Remaining": 0, "Entry": 1020., "At": 102., "Gross": 2000., "Best": 500., "Worst": -200.}
        rows, partial = adapt_saved({"scene": {"kind": "Night", "session": "2026-09-21_Night"}, "sources": [item]})
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["initial_pt"], rows[0]["mfe"], rows[0]["mae"]), (10., 50., -20.))
        self.assertEqual(rows[0]["parent_net"], 4000.)
        self.assertEqual(partial, [])

    def test_reject_accounting_or_immediate_spread_loss(self) -> None:
        """対象玉への配賦不一致と新規直後spread欠落を検出する。

        引数: self(AdapterNightTest)。返り値: None。
        """
        base = {"scene": {"kind": "Night", "session": "2026-09-21_Night"}, "sources": [source("前半")]}
        damaged = deepcopy(base)
        damaged["sources"][0]["Lots"]["n-玉"]["Worst"] = 0.
        with self.assertRaises(AssertionError):
            adapt_saved(damaged)
        damaged = deepcopy(base)
        damaged["sources"][0]["Events"][1]["Gross"] += 100
        with self.assertRaises(AssertionError):
            adapt_saved(damaged)
        damaged = deepcopy(base)
        damaged["sources"][0]["Events"][0]["FillIndex"] = 1
        with self.assertRaises(AssertionError):
            adapt_saved(damaged)


if __name__ == "__main__":
    unittest.main()
