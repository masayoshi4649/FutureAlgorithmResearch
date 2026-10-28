"""事後監査器を実資料なしの人工価格・架空集計で検査する。"""

import unittest
import numpy as np

from audit_results161 import first_hit, summarize, exclusions, check_event_order, signals, model_probability


class AuditorTests(unittest.TestCase):
    """検算器自身の分母と経路の人工反例。"""

    def test_same_second_and_initial_spread(self):
        """機能: 同秒先着と初期気配差を検算。引数: self。返り値: None。"""
        raw=np.array([[0,1000,1000,1010,1,1,1],[1,1000,1000,1010,1,1,2],[1,1100,1110,1120,1,1,3],[1,950,950,960,1,1,4]],float)
        result=first_hit(raw,1,1)
        self.assertEqual((result["status"],result["hit"]),(1,2))
        raw[1,3]=1050
        self.assertEqual(first_hit(raw,1,1)["status"],-1)

    def test_invalid_rows_not_used_as_barriers(self):
        """機能: 異常気配の到達を採らず品質へ残す。引数: self。返り値: None。"""
        raw=np.array([[0,1000,1000,1010,1,1,1],[1,1000,2000,1000,1,1,2],[30,1120,1110,1120,1,1,3]],float)
        result=first_hit(raw,0,1)
        self.assertEqual(result["hit"],2)
        self.assertEqual(result["path_bad_bbo"],1)
        self.assertEqual(result["path_gap"],1)

    def test_all_signals_remain_denominator(self):
        """機能: 未到達/未約定を除外した率と主率を分離。引数: self。返り値: None。"""
        events=[dict(session="a",side=1,status=s,opposite_status=-1,last_status=1) for s in [1,-1,0,-2]]
        stats=summarize(events,["a","b"])
        self.assertEqual(stats["success_probability"],.25)
        self.assertEqual(stats["resolved_probability"],.5)
        self.assertEqual(stats["active_sessions"],1)
        self.assertEqual(len(exclusions(stats,"train")),4)

    def test_overlap_and_phase_rejected(self):
        """機能: 未決重複と時刻区分違いを拒否。引数: self。返り値: None。"""
        scene={"a":dict(kind="Night",us_open=100,split="train")}
        a=dict(session="a",side=1,decision_index=1,decision_time=1,resolution_index=100,phase="preUS",split="train")
        b={**a,"decision_index":50,"decision_time":70}
        with self.assertRaises(AssertionError):
            check_event_order([a,b],scene,"preUS")
        with self.assertRaises(AssertionError):
            check_event_order([{**a,"decision_time":101}],scene,"preUS")


if __name__=="__main__":
    unittest.main(verbosity=2)
