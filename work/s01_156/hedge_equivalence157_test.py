"""両建てと純建玉の中値・清算気配・最終キャッシュフローを人工検算する。"""
from pathlib import Path
import json
import unittest


def values(cash: float, long: int, short: int, bid: float, ask: float) -> dict:
    """同じ売買残高から中値と全玉清算時価を計算する。

    引数: cash/bid/ask(float)、long/short(int)は人工口座の残高と気配。
    返り値: dictは中値・BBO評価と純建玉。ポイント価値は1で固定。
    """
    return {"mid":cash+(long-short)*(bid+ask)/2,"bbo":cash+long*bid-short*ask,"net":long-short}


class HedgeEquivalence157(unittest.TestCase):
    """同値を主張できる範囲と、重複清算で残る差を区別する。"""

    def test_mid_equal_and_bbo_overlap_difference(self):
        """同じ純建玉と売買残高なら中値は一致し、BBOは重複分だけ差がある。

        引数: self(HedgeEquivalence157)。返り値: なし。
        """
        for long,short,cash in ((10,3,-730),(3,10,667),(4,4,-8)):
            for bid,ask in ((90,91),(100,105)):
                hedge=values(cash,long,short,bid,ask)
                net=values(cash,max(0,long-short),max(0,short-long),bid,ask)
                self.assertEqual(hedge["mid"],net["mid"])
                self.assertEqual(hedge["bbo"]-net["bbo"],-min(long,short)*(ask-bid))

    def test_user_example_exact_values(self):
        """買10と売3の例を実現分類に依存しない残高で確認する。

        引数: self(HedgeEquivalence157)。返り値: なし。
        """
        hedge=values(-1000+270,10,3,90,91)
        net=values(-1000+270,7,0,90,91)
        self.assertEqual(hedge,{"mid":-96.5,"bbo":-103,"net":7})
        self.assertEqual(net,{"mid":-96.5,"bbo":-100,"net":7})

    def test_identical_full_cashflows_then_flat_equal(self):
        """カバー返済と買い再追加を同じ買3とし、その後全10売で同額になる。

        引数: self(HedgeEquivalence157)。返り値: なし。
        """
        hedge_cash=-1000+3*90-3*91+10*90
        net_cash=-1000+3*90-3*91+10*90
        self.assertEqual(hedge_cash,net_cash)
        self.assertEqual(hedge_cash,-103)

    def test_minimal_terminal_flat_is_not_identical_cashflow(self):
        """両建てを両側清算し純建玉を片側清算すると追加気配差が残る。

        引数: self(HedgeEquivalence157)。返り値: なし。
        """
        hedge_final=-730+10*90-3*91
        net_final=-730+7*90
        self.assertEqual(hedge_final,-103)
        self.assertEqual(net_final,-100)
        self.assertEqual(hedge_final-net_final,-3)


if __name__=="__main__":
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(HedgeEquivalence157)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    Path(__file__).with_name("両建て対照の人工検査157.json").write_text(json.dumps({"financial_replay":False,"tests":result.testsRun,"passed":result.wasSuccessful(),"mid_equality":True,"bbo_difference":"重複枚数×スプレッドだけ両建てが低い","terminal_equality":"清算を含む全売買キャッシュフローが同じ場合に限定"},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
