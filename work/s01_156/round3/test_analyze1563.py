"""局所停止の損失判定と消えた再参加の会計を人工値で検査する。"""
import copy
import unittest
import numpy as np
from analyze1563 import local_stop_evidence,compare_reentry_lots


class Accounting1563(unittest.TestCase):
    """金融入力を使わず、方向と会計粒度の取り違えを検査する。"""

    def test_local_stop_is_symmetric_and_next_quote_loss_is_kept(self):
        """買売鏡像の局所停止でも次板による追加損失を残す。

        引数: self(Accounting1563)。返り値: なし。
        """
        for side in (1,-1):
            raw=np.array([[100,1000-side*25,970 if side>0 else 1020,980 if side>0 else 1030]],dtype=float)
            lot={"id":"玉","price":1000,"side":side,"is_reentry1562":True,"ever_positive":False}
            case={"config":{"local_stop":20},"events":[{"signal":{"action":"close","reason_code":15631},"decision_index":0,"fill":{"Price":1000-side*40,"Closed":[{"id":"玉","quantity":2}]}}]}
            detail={"lots":[lot],"row":{}}
            actual=local_stop_evidence(case,detail,raw)
            self.assertEqual(actual["net"],-8000)
            self.assertEqual(actual["decision_net"],-6000)
            self.assertEqual(actual["fill_minus_decision"],-2000)
            self.assertEqual(actual["never_positive_allocations"],1)
            changed=copy.deepcopy(detail)
            changed["lots"][0]["is_reentry1562"]=False
            with self.assertRaises(AssertionError):
                local_stop_evidence(case,changed,raw)

    def test_lost_future_wins_and_avoided_losses_are_separate(self):
        """停止後の消失玉と、同じ入口の退出改善を分離する。

        引数: self(Accounting1563)。返り値: なし。
        """
        def lot(index,net):
            """人工の再参加1枚を作る。

            引数: index(int)、net(int)。返り値: dict。
            """
            return {"owner":"core","side":1,"decision_index":index,"net":net,"quantity":1,"entry_time":index,"is_reentry1562":True}
        baseline={"row":{"session":"人工","id":"R01"},"lots":[lot(1,-8000),lot(2,5000),lot(3,-4000)]}
        candidate={"row":{"session":"人工","id":"L01"},"lots":[lot(1,-1000),lot(4,2000)]}
        actual=compare_reentry_lots(baseline,candidate)
        self.assertEqual(actual["lost_win"],5000)
        self.assertEqual(actual["avoided_loss"],4000)
        self.assertEqual(actual["same_entry_delta"],7000)
        self.assertEqual(actual["added_net"],2000)
        self.assertEqual(actual["delta"],8000)


if __name__=="__main__":
    unittest.main()
