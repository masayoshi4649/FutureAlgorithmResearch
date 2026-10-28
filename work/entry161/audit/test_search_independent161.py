"""独立人工だけで先着・NPZ接続・選択遮断を検査する。"""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "features"), str(HERE.parent / "search")]
from test_features_independent161 import market, table
from labels161 import make_labels
from extract161 import save_npz, permit_extraction
import engine161 as search


class IndependentSearch(unittest.TestCase):
    """実資料を読まずに因果ラベルと探索境界を検査する。"""

    def test_initial_spread_exact50_is_failure_both_sides(self):
        """機能: 約定瞬間の50円気配差を逆行先着へ含める。引数: self。返り値: None。"""
        m = market([0, 1, 2], [1000, 1000, 1100], [1010, 1050, 1110])
        label = make_labels(m, np.array([0]))
        np.testing.assert_array_equal(label["primary_status"][0], [-1, -1])
        np.testing.assert_array_equal(label["primary_resolution_index"][0], [1, 1])

    def test_same_second_first_passage_uses_raw_order(self):
        """機能: 同秒内の逆転でも最初の到達原行を優先。引数: self。返り値: None。"""
        for bids, expect in [([1000, 1000, 1110, 960], 1), ([1000, 1000, 960, 1110], -1)]:
            m = market([0, 1, 1, 1], bids)
            label = make_labels(m, np.array([0]))
            self.assertEqual(label["primary_status"][0, 0], expect)
            self.assertEqual(label["primary_resolution_index"][0, 0], 2)

    def test_entry_must_be_next_normal_raw_row(self):
        """機能: 不正板を飛ばし判断より後の正常行で建値を固定。引数: self。返り値: None。"""
        m = market([0, 0, 0, 1], [1000, 0, 1000, 1110], [1010, 0, 1010, 1120])
        label = make_labels(m, np.array([0]))
        self.assertEqual(label["entry_index"][0], 2)
        self.assertEqual(label["entry_price"][0, 0], 1010)
        self.assertEqual(label["primary_status"][0, 0], 1)

    def test_no_entry_and_unresolved_are_distinct(self):
        """機能: 次正常なしと場末未到達を区別。引数: self。返り値: None。"""
        m = market([0, 1, 2], [1000, 1000, 1000])
        label = make_labels(m, np.array([0, 2]))
        np.testing.assert_array_equal(label["primary_status"], [[0, 0], [-2, -2]])
        self.assertEqual(label["entry_index"][1], -1)

    def test_bad_path_gap_and_phase_are_diagnostics_only(self):
        """機能: 不正板・時計空白・枠越えでも結果を隠さず品質列へ残す。引数: self。返り値: None。"""
        m = market([0, 2, 3, 30], [1000, 1000, 0, 1110], [1010, 1010, 0, 1120])
        label = make_labels(m, np.array([0]), dict(kind="Night", us_open=1))
        self.assertEqual(label["primary_status"][0, 0], 1)
        self.assertTrue(label["entry_cross_phase"][0])
        self.assertEqual(label["primary_path_bad_bbo"][0, 0], 1)
        self.assertEqual(label["primary_path_gap_count"][0, 0], 1)
        self.assertTrue(label["path_gap"][0, 0])
        self.assertEqual(label["entry_price_clock_gap_s"][0], 2)

    def test_artificial_extractor_npz_connects_to_search(self):
        """機能: 生成器の実schema・数値phaseを探索器へ接続。引数: self。返り値: None。"""
        m = market(range(401))
        f = table(m)
        label = make_labels(m, m["observations"])
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            save_npz(base/"features/train/人工_Day.npz", f, {})
            save_npz(base/"labels/train/人工_Day.npz", label, {})
            data = search.load_scene(dict(session="人工_Day", split="train", kind="Day", start=0), base, {"train"}, [])
            self.assertEqual(set(data["feature"]["phase"]), {"Day"})
            long_signal = np.zeros(len(m["observations"]), dtype=bool)
            long_signal[[120, 240, 360]] = True
            events = search.collect_events(data, long_signal, np.zeros_like(long_signal), "人工", "Day")
            self.assertEqual([e["row"] for e in events], [120, 240, 360])
            self.assertEqual(events[0]["status"], 1)

    def test_mismatched_decision_time_is_rejected(self):
        """機能: 添字同一でも時刻不一致のファイルを拒否。引数: self。返り値: None。"""
        m = market(range(401)); f = table(m); label = make_labels(m, m["observations"])
        label["decision_time"][100] += .5
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            save_npz(base/"features/train/人工_Day.npz", f, {})
            save_npz(base/"labels/train/人工_Day.npz", label, {})
            with self.assertRaises(ValueError):
                search.load_scene(dict(session="人工_Day", split="train"), base, {"train"}, [])

    def test_test_split_is_blocked_before_npz_access(self):
        """機能: 後半確認資料を選択段階から開かない。引数: self。返り値: None。"""
        with self.assertRaises(ValueError):
            search.load_scene(dict(session="人工_Day", split="test"), Path("存在しない"), {"train", "validation"}, [])

    def test_no_eligible_candidate_is_not_rescued(self):
        """機能: 分母不適格なら選択なしを維持。引数: self。返り値: None。"""
        record = dict(train_exclusions=["件数不足"], validation_exclusions=[],
                      validation=dict(wilson95=[.9, 1], session_cluster95=[1, 1], success_probability=1, events=1))
        self.assertEqual(search.select_final({"Day": {"候補": record}}), {})

    def test_registration_failure_not_success(self):
        """機能: 指紋と許可段階があっても登録失敗は拒否。引数: self。返り値: None。"""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); spec = base/"spec.json"; manifest = base/"manifest.json"; receipt = base/"receipt.json"
            spec.write_text('{"implementation":[]}', encoding="utf-8")
            manifest.write_text('{}', encoding="utf-8")
            record = dict(registered=False, returncode=1, allowed_stages=["train_validation"],
                          spec_sha256=search.digest(spec), manifest_sha256=search.digest(manifest))
            receipt.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaises(ValueError):
                search.require_registration(receipt, "train_validation", spec, manifest)

    def test_test_extraction_needs_frozen_content(self):
        """機能: test特徴/ラベルは凍結前・凍結後変更を拒否。引数: self。返り値: None。"""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); spec = base/"spec.json"; manifest = base/"manifest.json"; receipt = base/"receipt.json"; freeze = base/"freeze.json"
            spec.write_text('{}', encoding="utf-8"); manifest.write_text('{}', encoding="utf-8")
            record = dict(registered=True, returncode=0, allowed_stages=["locked_test"], spec_sha256=search.digest(spec), manifest_sha256=search.digest(manifest))
            receipt.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaises(ValueError):
                permit_extraction(receipt, "test", manifest, spec, None)
            frozen = dict(test_opened=False, selected={"Day": "M01"}, models={}, spec_sha256=record["spec_sha256"], manifest_sha256=record["manifest_sha256"])
            frozen["content_sha256"] = search.canonical_digest(frozen)
            freeze.write_text(json.dumps(frozen), encoding="utf-8")
            record["freeze_sha256"] = search.digest(freeze)
            receipt.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(permit_extraction(receipt, "test", manifest, spec, freeze)["allowed_stage"], "locked_test")
            frozen["selected"]["Day"] = "M02"
            freeze.write_text(json.dumps(frozen), encoding="utf-8")
            with self.assertRaises(ValueError):
                permit_extraction(receipt, "test", manifest, spec, freeze)


if __name__ == "__main__":
    unittest.main(verbosity=2)
