"""売買再生を行わず、第2巡の独立支持検算器を人工列で確認する。"""

from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"audit"))
from raw_result157 import support_arrays
from raw_support1572 import window1572,support_at1572


class RawSupport1572(unittest.TestCase):
    """不正板、窓端、補助欠測と未来相手を検査する。"""

    def test_last_normal_before_bound_and_speed(self):
        """窓端以後の近い正常値を使わず、実経過で短期だけ換算する。

        引数: self(RawSupport1572)。返り値: None。
        """
        raw=np.array([[0,100,99,101,10,10],[5,110,109,111,10,10],[14,111,111,111,10,10],[16,999,998,1000,10,10],[20,120,119,121,10,10]],dtype=float)
        w=window1572(support_arrays(raw),4,5,True)
        self.assertTrue(w["Known"]);self.assertEqual(w["EndpointAt"],5);self.assertEqual(w["Elapsed"],15)
        self.assertAlmostEqual(w["Value"],10000*(120/110-1)/3)
        raw[3,2:4]*=100
        self.assertEqual(window1572(support_arrays(raw),4,5,True),w)

    def test_endpoint_boundary_and_long_ratio(self):
        """許容15秒境界と120秒非換算を確認する。

        引数: self(RawSupport1572)。返り値: None。
        """
        raw=np.array([[0,100,99,101,10,10],[20,120,119,121,10,10]],dtype=float)
        self.assertAlmostEqual(window1572(support_arrays(raw),1,5,True)["Value"],500)
        raw[1,0]=20.001
        self.assertFalse(window1572(support_arrays(raw),1,5,True)["Known"])
        raw[1,0]=135
        self.assertAlmostEqual(window1572(support_arrays(raw),1,120,False)["Value"],2000)

    def test_missing_auxiliary_does_not_reweight(self):
        """補助が両方不明でも自己価格だけで0.8を超えないことを確認する。

        引数: self(RawSupport1572)。返り値: None。
        """
        for side in (-1,1):
            own=np.array([[i,60005+side*i*10,60000+side*i*10,60010+side*i*10,10,10] for i in range(401)],dtype=float)
            own[-1,4:]=0
            peer=own[:2]
            s=support_at1572(support_arrays(own),support_arrays(peer),400,side)
            self.assertTrue(s["Known"]);self.assertFalse(s["components"]["PeerKnown"]);self.assertFalse(s["components"]["OFIKnown"])
            self.assertAlmostEqual(s["M"],.8);self.assertAlmostEqual(s["T"],.8)

    def test_intermediate_bad_and_same_second_peer(self):
        """途中異常だけでは全窓を失効させず、相手の同秒行は使わない。

        引数: self(RawSupport1572)。返り値: None。
        """
        own=np.array([[i,60005+i*10,60000+i*10,60010+i*10,10,10] for i in range(401)],dtype=float)
        own[200,3]=own[200,2]
        peer=np.array([[i,4000.5+i,4000+i,4001+i,10,10] for i in range(402)],dtype=float)
        peer[400:,2:4]*=1e5
        s=support_at1572(support_arrays(own),support_arrays(peer),400,1)
        self.assertTrue(s["Known"]);self.assertEqual(s["PeerAt"],399)
        self.assertAlmostEqual(s["Peer120"],10000*(4399.5/4279.5-1))
        own[-1,3]=own[-1,2]
        self.assertFalse(support_at1572(support_arrays(own),support_arrays(peer),400,1)["Known"])


if __name__=="__main__":
    unittest.main(verbosity=2)
