"""登録前に数量換算と親内相殺の会計恒等式を人工例だけで確認する。"""

from pathlib import Path
import json
import unittest


def values(cash: float, long_qty: int, short_qty: int, bid: float, ask: float, multiplier: float = 10.0) -> dict:
    """売買現金と実保有から中値・全玉清算時価を計算する。

    引数: cash(float)は価格数量単位の売買現金、long_qty/short_qty(int)は保有数量。
      bid/ask/multiplier(float)は気配価格と1pt価値。
    返り値: dictは円単位の中値時価、BBO清算時価、差引数量。
    """
    return {
        "mid": (cash + (long_qty - short_qty) * (bid + ask) / 2) * multiplier,
        "bbo": (cash + long_qty * bid - short_qty * ask) * multiplier,
        "net": long_qty - short_qty,
    }


class AccountingIdentity157(unittest.TestCase):
    """実市場を再生せず、評価基準と数量換算の境界を反証する。"""

    def test_single_parent_mid_equal_bbo_overlap(self):
        """同現金列・同純数量の親内相殺は中値同値と重複BBO差を満たす。

        引数: self(AccountingIdentity157)。返り値: なし。
        """
        for long_qty, short_qty, cash in ((10, 3, -730), (3, 10, 667), (4, 4, -8)):
            for bid, ask in ((90, 91), (100, 105)):
                hedge = values(cash, long_qty, short_qty, bid, ask)
                net = values(cash, max(0, long_qty - short_qty), max(0, short_qty - long_qty), bid, ask)
                self.assertEqual(hedge["mid"], net["mid"])
                self.assertEqual(hedge["bbo"] - net["bbo"], -min(long_qty, short_qty) * (ask - bid) * 10)

    def test_parent_net_is_not_account_net(self):
        """別親の反対玉が残るため、口座全体の重複数量を差式へ流用しない。

        引数: self(AccountingIdentity157)。返り値: なし。
        """
        bid, ask = 90.0, 91.0
        hedge = values(-360, 12, 8, bid, ask)
        parent_net = values(-360, 7, 3, bid, ask)
        account_net = values(-360, 4, 0, bid, ask)
        self.assertEqual(hedge["mid"], parent_net["mid"])
        self.assertEqual(hedge["bbo"] - parent_net["bbo"], -5 * 10)
        self.assertNotEqual(hedge["bbo"] - parent_net["bbo"], -8 * 10)
        self.assertEqual(hedge["bbo"] - account_net["bbo"], -8 * 10)

    def test_identical_terminal_cashflows_equal(self):
        """カバー返済と再追加を同じ買3とし、同じ全売却まで行えば最終一致。

        引数: self(AccountingIdentity157)。返り値: なし。
        """
        hedge_final = (-10 * 100 + 3 * 90 - 3 * 91 + 10 * 90) * 10
        net_final = (-10 * 100 + 3 * 90 - 3 * 91 + 10 * 90) * 10
        self.assertEqual(hedge_final, net_final)
        self.assertEqual(hedge_final, -1030)

    def test_minimal_flat_is_not_identical_cashflows(self):
        """終端の相殺往復を省けば、両方flatでも気配差分の最終損益差が残る。

        引数: self(AccountingIdentity157)。返り値: なし。
        """
        hedge_final = (-730 + 10 * 90 - 3 * 91) * 10
        net_final = (-730 + 7 * 90) * 10
        self.assertEqual(hedge_final - net_final, -30)

    def test_mini_micro_exact_conversion_preserves_partial_closes(self):
        """初回・部分返済・残玉を全て10倍すれば、micro換算でも金額一致。

        引数: self(AccountingIdentity157)。返り値: なし。
        """
        entry = 64000
        mini_realized = (64100 - entry) * 2 * 100
        micro_realized = (64100 - entry) * 20 * 10
        mini_unrealized = (63950 - entry) * 3 * 100
        micro_unrealized = (63950 - entry) * 30 * 10
        self.assertEqual(mini_realized, micro_realized)
        self.assertEqual(mini_unrealized, micro_unrealized)
        self.assertNotEqual(mini_unrealized, (63950 - entry) * 1 * 10)

    def test_realized_profit_is_not_instant_total_equity_gain(self):
        """利益側返済は既存含みの現金化であり、同気配評価の時価を増やさない。

        引数: self(AccountingIdentity157)。返り値: なし。
        """
        before = values(-10 * 100 + 3 * 110, 10, 3, 90, 91)
        after = values(-10 * 100 + 3 * 110 - 3 * 91, 10, 0, 90, 91)
        self.assertEqual(before["bbo"], after["bbo"])
        self.assertEqual((110 - 91) * 3 * 10, 570)
        self.assertLess(after["bbo"], 0)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AccountingIdentity157)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    Path(__file__).with_suffix(".json").write_text(json.dumps({
        "passed": result.wasSuccessful(),
        "tests": result.testsRun,
        "financial_replay": False,
        "scope": "人工会計恒等式のみ。戦略実装の正しさや実市場収益性を証明しない。",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
