"""実原板を使わず、独立人工列で特徴の因果境界を検査する。"""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import hashlib

import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "features/features161.py"
spec = importlib.util.spec_from_file_location("features_under_audit161", SOURCE)
features = importlib.util.module_from_spec(spec)
spec.loader.exec_module(features)


def market(times, bids=None, asks=None, quantities=None):
    """独立人工の市場配列を作る。

    引数: times(list)、bids/asks/quantities(list又はNone)。
    返り値: dict は特徴器の入力配列。
    """
    t = np.asarray(times, dtype=float)
    b = 10000 + 2*t if bids is None else np.asarray(bids, dtype=float)
    a = b+10 if asks is None else np.asarray(asks, dtype=float)
    q = np.full(len(t), 20.0) if quantities is None else np.asarray(quantities, dtype=float)
    valid = np.isfinite(b) & np.isfinite(a) & (0 < b) & (b < a)
    obs, reps = [], []
    for i in range(len(t)):
        if i == 0 or t[i] != t[i-1]:
            reps.append(i)
            found = False
        if valid[i] and not found:
            reps[-1] = i
            obs.append(i)
            found = True
    return dict(time=t, last=(b+a)/2, bid=b, ask=a, bq=q, aq=np.full(len(t), 10.0),
                line=np.arange(1, len(t)+1), valid=valid, mid=(b+a)/2,
                observations=np.asarray(obs), representatives=np.asarray(reps),
                imb5=np.zeros(len(t)), imb10=np.zeros(len(t)), depth_imb=np.zeros(len(t)))


def table(own, peer=None):
    """固定場境界で人工特徴を返す。

    引数: own(dict)、peer(dict又はNone)。返り値: dict は特徴器の出力。
    """
    return features.build_features(own, own if peer is None else peer,
                                   dict(start=0, end=1000, kind="Day", us_open=0))


def column(result, name):
    """名前から特徴列を選ぶ。

    引数: result(dict)、name(str)。返り値: ndarray。
    """
    return result["features"][:, list(result["feature_names"]).index(name)]


class IndependentFeatures(unittest.TestCase):
    """実測値を参照しない因果・時計・数量の人工検査。"""

    def test_future_same_second_does_not_change_current(self):
        """機能: 現在と同秒の後続行を先取りしない。引数: self。返り値: None。"""
        times = list(range(301)) + [300, 300, 301, 302]
        original = market(times)
        changed = market(times)
        changed["bid"][301:] += 700
        changed["ask"][301:] += 700
        changed["mid"][301:] += 700
        changed["bq"][301:] *= 100
        a, b = table(original), table(changed)
        np.testing.assert_allclose(a["features"][:301], b["features"][:301], equal_nan=True)

    def test_prefix_only_matches_full(self):
        """機能: 原行prefixだけでも現在特徴が一致。引数: self。返り値: None。"""
        full, short = table(market(range(501))), table(market(range(301)))
        np.testing.assert_allclose(full["features"][:301], short["features"], equal_nan=True)

    def test_peer_strict_previous_and_first_same_clock(self):
        """機能: 相手同時計と過去同時計後続を使わない。引数: self。返り値: None。"""
        own = market(range(301))
        times = list(range(300)) + [299, 300, 301]
        a = market(times)
        b = market(times)
        for key in ["bid", "ask", "mid"]:
            b[key][300:] += 5000
        before, after = table(own, a), table(own, b)
        for name in ["peer_ret5_bp", "peer_ret15_bp", "peer_ret60_bp", "peer_age_s"]:
            np.testing.assert_allclose(column(before, name), column(after, name), equal_nan=True)
        self.assertEqual(column(after, "peer_age_s")[-1], 1)

    def test_asof_tolerance_inclusive(self):
        """機能: asofの15秒境界は含み未来側を使わない。引数: self。返り値: None。"""
        m = market([0, 30])
        idx, known = features.endpoints(m, np.array([15, 15.001, 29.99, 30]))
        self.assertEqual(idx.tolist(), [0, 0, 0, 1])
        self.assertEqual(known.tolist(), [True, False, False, True])

    def test_expected_linear_returns_and_twap(self):
        """機能: 単調列の差分と過去保持TWAPを手計算照合。引数: self。返り値: None。"""
        r = table(market(range(301)))
        self.assertEqual(column(r, "ret5_pt")[-1], 10)
        self.assertEqual(column(r, "vel5_pt_s")[-1], 2)
        self.assertEqual(column(r, "er60")[-1], 1)
        self.assertEqual(column(r, "twap60")[-1], 10544)
        self.assertEqual(column(r, "twap60_coverage")[-1], 1)
        self.assertNotIn("vwap", list(r["feature_names"]))

    def test_refill_is_display_change(self):
        """機能: 同価格数量増分だけを表示回復代理にする。引数: self。返り値: None。"""
        m = market([0, 1, 2], [100, 100, 110], [110, 110, 120], [20, 30, 50])
        f = features.flows(m)
        self.assertAlmostEqual(f["ofi"][1], 1/7)
        self.assertAlmostEqual(f["bid_refill"][1], .2)
        self.assertEqual(f["bid_refill"][2], 0)

    def test_invalid_quantity_and_invalid_bbo_break_flow(self):
        """機能: 不正板/数量からOFIを作らない。引数: self。返り値: None。"""
        m = market([0, 1, 2, 3], [100, 100, 100, 100], [110, 90, 110, 110], [20]*4)
        self.assertEqual(features.flows(m)["valid"].tolist(), [False, False, False, True])
        m["bq"][2] = np.nan
        self.assertFalse(features.flows(m)["valid"].any())

    def test_bad_peer_latest_representative_is_unknown(self):
        """機能: 相手最新の不正代表を古い正常板へ無言で戻さない。引数: self。返り値: None。"""
        own = market(range(301)); peer = market(range(300))
        peer["valid"][-1] = False
        peer["bid"][-1] = 0
        peer["mid"][-1] = 0
        peer["observations"] = peer["observations"][:-1]
        r = table(own, peer)
        self.assertEqual(column(r, "peer_current_known")[-1], 0)
        self.assertTrue(np.isnan(column(r, "peer_ret60_bp")[-1]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
