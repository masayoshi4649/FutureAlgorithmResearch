"""全原板監査器の人工会計を検査する。市場の売買再生は実行しない。"""

import copy
import unittest
import numpy as np
from raw157 import raw_risk, reserved_cap, support_arrays, support_at


def fixture() -> tuple[np.ndarray, dict]:
    """含み益の山と次板返済を持つ人工口座を作る。

    引数: なし。返り値: 原板ndarrayと保存台帳dict。
    """
    raw=np.array([[1000,105,100,110,10,10],[1010,105,100,110,10,10],[1020,145,140,150,10,10],[1030,125,120,130,10,10],[1040,125,120,130,10,10]],dtype=float)
    opening={"ID":"new","Parent":"core/0","Side":1,"Quantity":2,"DecisionIndex":0,"DecisionTime":1000,"DecisionBid":100,"DecisionAsk":110,"Targets":None}
    closing={"ID":"close","Parent":"core/0","Side":-1,"Quantity":2,"DecisionIndex":2,"DecisionTime":1020,"DecisionBid":140,"DecisionAsk":150,"Targets":[{"ID":"new-玉","Quantity":2}]}
    ledger={"Events":[{"Order":opening,"FillIndex":1,"FillTime":1010,"Bid":100,"Ask":110,"Price":110,"HoldID":"new-玉","Gross":0},{"Order":closing,"FillIndex":3,"FillTime":1030,"Bid":120,"Ask":130,"Price":120,"Gross":200}],"Pending":None,"Realized":200,"Last":{"Equity":200},"Risk":{"Minimum":-200,"MaxDD":400}}
    return raw,ledger


class RawAudit157(unittest.TestCase):
    """独立原板会計と支持式の欠陥を人工例で先に検出する。"""

    def test_full_path_peak_and_next_quote(self):
        """保存断面以外の山も含め、次正常約定と全時価経路を確認する。

        引数: self(RawAudit157)。返り値: None。
        """
        raw,ledger=fixture();risk=raw_risk(raw,ledger,1000)
        self.assertEqual(risk["dd_from"]["index"],2)
        self.assertEqual(risk["dd_to"]["index"],3)
        self.assertEqual(risk["min_equity"],-200)
        self.assertEqual(reserved_cap(ledger)["max_long_reserved"],2)

    def test_same_row_fill_rejected(self):
        """判断原行の約定を受理しない。

        引数: self(RawAudit157)。返り値: None。
        """
        raw,ledger=fixture();ledger["Events"][0]["FillIndex"]=0
        with self.assertRaises(AssertionError):raw_risk(raw,ledger,1000)

    def test_pending_new_counts_to_cap(self):
        """未約定新規も上限へ含め、最終Pendingの欠落を防ぐ。

        引数: self(RawAudit157)。返り値: None。
        """
        _,ledger=fixture();pending=copy.deepcopy(ledger["Events"][0]["Order"])
        pending.update(ID="pending",DecisionIndex=4,Quantity=101)
        ledger["Pending"]=[pending]
        with self.assertRaises(AssertionError):reserved_cap(ledger)
        pending["Quantity"]=100
        self.assertEqual(reserved_cap(ledger)["final_pending"],1)

    def test_support_uses_window_endpoint_and_prior_peer(self):
        """窓端を包含し、相手の同秒後続行を使わない。

        引数: self(RawAudit157)。返り値: None。
        """
        own=np.array([[t,60005+10*t,60000+10*t,60010+10*t,10,10] for t in range(401)],dtype=float)
        peer=np.array([[t,4005+.1*t,4000+.1*t,4010+.1*t,10,10] for t in range(402)],dtype=float)
        peer[-2:,2:4]*=10
        value=support_at(support_arrays(own),support_arrays(peer),400,1)
        self.assertTrue(value["Known"]);self.assertEqual(value["PeerAt"],399)
        self.assertAlmostEqual(value["Own5"],10000*(64005/63955-1),places=8)
        own[399,3]=own[399,2]
        self.assertFalse(support_at(support_arrays(own),support_arrays(peer),400,1)["Known"])


if __name__=="__main__":
    unittest.main(verbosity=2)
