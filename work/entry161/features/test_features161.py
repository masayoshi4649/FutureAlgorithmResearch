"""人工板だけで因果特徴・原行採番・先着木を検査する。実金融資料は使わない。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from features161 import read_market, build_features, flows, endpoints
from labels161 import make_labels
from extract161 import permit, permit_extraction, save_npz


def market(times: np.ndarray, prices: np.ndarray) -> dict:
    """人工価格列から既知の正常板列を作る。

    引数: times/prices(ndarray)。返り値: dictは人工市場。
    """
    count = len(times)
    return {"time": times.astype(float), "last": prices.astype(float), "mid": prices.astype(float), "bid": prices-5., "ask": prices+5.,
            "bq": np.full(count, 10.), "aq": np.full(count, 10.), "line": np.arange(count)+1,
            "valid": np.ones(count, dtype=bool), "observations": np.flatnonzero(np.r_[True, np.diff(times)>0]),
            "representatives": np.flatnonzero(np.r_[True, np.diff(times)>0]), "imb5": np.zeros(count), "imb10": np.zeros(count), "depth_imb": np.zeros(count)}


def scene() -> dict:
    """人工検査の場時計を返す。

    引数: なし。返り値: dict。
    """
    return {"kind": "Night", "start": 0, "end": 1000, "us_open": 500}


class FeatureTests(unittest.TestCase):
    """人工だけで公開情報の境界を確認する。"""

    def test_linear_values_and_window(self):
        """一定速度・実経過・現在を除く高安・TWAPを手計算と比較する。

        引数: self(FeatureTests)。返り値: None。
        """
        t = np.arange(401.)
        own, peer = market(t, 1000+2*t), market(t-.5, 1000+t)
        result = build_features(own, peer, scene())
        row = dict(zip(result["feature_names"], result["features"][300]))
        self.assertEqual(row["ret5_pt"], 10)
        self.assertEqual(row["vel5_pt_s"], 2)
        self.assertEqual(row["ret5_lag5_pt"], 10)
        self.assertEqual(row["accel5_prev5_pt_s"], 0)
        self.assertEqual(row["high60_prev"], 1598)
        self.assertEqual(row["low60_prev"], 1480)
        self.assertEqual(row["er60"], 1)
        self.assertEqual(row["twap60"], 1539)
        self.assertEqual(row["twap60_coverage"], 1)
        self.assertEqual(row["peer_age_s"], .5)

    def test_prefix_and_peer_same_clock(self):
        """未来追記とpeer同時計後続の書換えで過去特徴が変わらないことを確認する。

        引数: self(FeatureTests)。返り値: None。
        """
        t = np.arange(401.)
        own, peer = market(t, 1000+t), market(np.repeat(t, 2), np.repeat(2000+t, 2))
        before = build_features(own, peer, scene())
        changed = {k: v.copy() for k, v in peer.items()}
        for key in ("last", "mid", "bid", "ask"):
            changed[key][1::2] += 9000
        after = build_features(own, changed, scene())
        np.testing.assert_allclose(before["features"], after["features"], equal_nan=True)
        cut = 350
        shorter = {k: v[:cut].copy() for k, v in own.items()}
        peer_short = {k: v[v < cut] if k in ("observations", "representatives") else v[:cut*2] for k, v in peer.items()}
        peer_short["representatives"] = peer["representatives"][peer["representatives"] < cut*2]
        peer_short["observations"] = peer_short["representatives"]
        prefix = build_features(shorter, peer_short, scene())
        np.testing.assert_allclose(prefix["features"], before["features"][:cut], equal_nan=True)

    def test_endpoint_delay_and_invalid_observation(self):
        """過去端遅れ15秒の境界と窓内不正の分離を確認する。

        引数: self(FeatureTests)。返り値: None。
        """
        own = market(np.array([0., 20., 20.01, 25.]), np.array([1000., 1020., 1021., 1025.]))
        indices, known = endpoints(own, np.array([15., 15.01]))
        np.testing.assert_array_equal(indices, [0, 0])
        np.testing.assert_array_equal(known, [True, False])
        own["valid"][1] = False
        indices, known = endpoints(own, np.array([20.]))
        self.assertFalse(known[0])

    def test_flow_and_nonfinite_quantity(self):
        """OFIと数量回復代理を手計算し、非有限数量は未知へ分ける。

        引数: self(FeatureTests)。返り値: None。
        """
        own = market(np.arange(4.), np.full(4, 1000.))
        own["bq"][1:] = [20, np.inf, 30]
        f = flows(own)
        self.assertAlmostEqual(f["ofi"][1], .2)
        self.assertAlmostEqual(f["bid_refill"][1], 1/3)
        np.testing.assert_array_equal(f["valid"], [False, True, False, False])
        self.assertTrue(np.isfinite(f["ofi"]).all())

    def test_reader_first_normal_and_indices(self):
        """同時計で最初の正常板だけが観測となり不正行も採番へ残ることを確認する。

        引数: self(FeatureTests)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as temporary:
            p = Path(temporary)/"book.jsonl"
            rows = []
            for time, last, bid, ask in ((0,100,100,100),(0,100,99,101),(0,101,100,102),(2,102,101,103),(1,103,102,104),(3,0,102,104)):
                rows.append({"CurrentPriceTime": datetime.fromtimestamp(time, timezone.utc).isoformat(), "CurrentPrice": last, "Buy1": {"Price":bid,"Qty":10}, "Sell1":{"Price":ask,"Qty":10}})
            p.write_text("\n".join(json.dumps(r) for r in rows)+"\n", encoding="utf-8")
            s = {"start":0,"end":5,"cutoff":6,"books":{"NK225":str(p)},"fingerprints":[{"path":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}]}
            own, meta = read_market(s, "NK225")
            np.testing.assert_array_equal(own["observations"], [1,3])
            np.testing.assert_array_equal(own["representatives"], [1,3])
            self.assertEqual(meta["counts"]["backwards"], 1)
            self.assertEqual(meta["counts"]["last_missing"], 1)
            self.assertEqual(len(own["time"]), 4)

    def test_labels_against_direct_scan(self):
        """売買鏡像・同秒・板飛び・未約定を素朴な原行探索と比較する。

        引数: self(FeatureTests)。返り値: None。
        """
        rng = np.random.default_rng(161)
        own = market(np.repeat(np.arange(50.), 2), 1000+np.cumsum(rng.integers(-50, 51, 100)))
        own["valid"][[5,20,51]] = False
        observations = np.flatnonzero(own["valid"])
        labels = make_labels(own, observations)
        normal = np.flatnonzero(own["valid"])
        for n, decision in enumerate(observations):
            candidates = normal[normal > decision]
            if not len(candidates):
                np.testing.assert_array_equal(labels["primary_status"][n], [-2,-2])
                continue
            entry = int(candidates[0])
            self.assertEqual(labels["entry_index"][n], entry)
            for definition in ("primary", "last"):
                for column, side in enumerate((1,-1)):
                    base = own["last"][entry] if definition == "last" else own["ask" if side == 1 else "bid"][entry]
                    points = side*(own["last" if definition == "last" else "bid" if side == 1 else "ask"]-base)
                    valid = np.ones(len(points),dtype=bool) if definition == "last" else own["valid"]
                    up = next((i for i in range(entry,len(points)) if valid[i] and points[i]>=100), -1)
                    down = next((i for i in range(entry,len(points)) if valid[i] and points[i]<=-50), -1)
                    self.assertEqual(labels[definition+"_first_up_index"][n,column], up)
                    self.assertEqual(labels[definition+"_first_down_index"][n,column], down)

    def test_registration_and_no_overwrite(self):
        """失敗登録と既存ファイルへの上書きを拒否する。

        引数: self(FeatureTests)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as temporary:
            p = Path(temporary)/"receipt.json"
            p.write_text('{"registered":true,"returncode":1}',encoding="utf-8")
            with self.assertRaises(ValueError):
                permit(p)
            p.write_text('{"registered":true,"returncode":0}',encoding="utf-8")
            permit(p)
            npz = Path(temporary)/"features.npz"
            save_npz(npz,{"features":np.zeros((2,3))},{"stage":"features"})
            with self.assertRaises(FileExistsError):
                save_npz(npz,{"features":np.zeros((2,3))},{})

    def test_label_quality_is_future_only(self):
        """価格時計空白・不正板・米国境界を先着とは別の品質へ保存する。

        引数: self(FeatureTests)。返り値: None。
        """
        own = market(np.array([0.,1.,1.,70.,71.,140.]), np.array([1000.,1000.,1000.,1000.,1110.,1110.]))
        own["valid"][1] = False
        labels = make_labels(own, np.array([0,2,3,5]), {"kind":"Night","us_open":50})
        self.assertEqual(labels["entry_skipped_bad_bbo"][0], 1)
        self.assertFalse(labels["entry_cross_phase"][0])
        self.assertTrue(labels["entry_cross_phase"][1])
        self.assertTrue(labels["entry_gap_gt60"][1])
        self.assertTrue(labels["primary_path_cross_phase"][0,0])
        self.assertTrue(labels["path_gap"][0,0])
        self.assertTrue(labels["path_gap_gt60"][0,0])
        self.assertEqual(labels["path_bad_bbo"][0,0], 0)
        self.assertEqual(labels["path_bad_bbo"][-1,0], -1)
        self.assertEqual(labels["primary_status"][0,0], 1)

    def test_test_extraction_requires_matching_frozen_selection(self):
        """test特徴とラベルの共通ゲートが未凍結・変更済みモデルを拒否する。

        引数: self(FeatureTests)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest, spec, receipt, freeze = [directory/name for name in ("manifest.json","spec.json","receipt.json","selection_frozen161.json")]
            manifest.write_text('{"sessions":[]}',encoding="utf-8")
            spec.write_text('{"version":161}',encoding="utf-8")
            mh, sh = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (manifest,spec)]
            frozen = {"selected":{"Day":"M01"},"models":{},"test_opened":False,"manifest_sha256":mh,"spec_sha256":sh}
            frozen["content_sha256"] = hashlib.sha256(json.dumps(frozen,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
            freeze.write_text(json.dumps(frozen),encoding="utf-8")
            allowed = {"registered":True,"returncode":0,"allowed_stages":["train_validation"],"manifest_sha256":mh,"spec_sha256":sh}
            receipt.write_text(json.dumps(allowed),encoding="utf-8")
            permit_extraction(receipt,"train",manifest,spec,None)
            with self.assertRaises(ValueError):
                permit_extraction(receipt,"test",manifest,spec,freeze)
            allowed.update(allowed_stages=["locked_test"],freeze_sha256=hashlib.sha256(freeze.read_bytes()).hexdigest())
            receipt.write_text(json.dumps(allowed),encoding="utf-8")
            with self.assertRaises(ValueError):
                permit_extraction(receipt,"test",manifest,spec,None)
            proof = permit_extraction(receipt,"test",manifest,spec,freeze)
            self.assertEqual(proof["freeze_content_sha256"],frozen["content_sha256"])
            frozen["selected"]["Day"]="M02"
            freeze.write_text(json.dumps(frozen),encoding="utf-8")
            with self.assertRaises(ValueError):
                permit_extraction(receipt,"test",manifest,spec,freeze)


if __name__ == "__main__":
    unittest.main()
