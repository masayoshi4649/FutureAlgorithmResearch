"""市場資料を使わず、方向対称・間引き・選択境界・学習の人工例を確認する。"""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from engine161 import collect_events, summarize, eligibility, select_final, load_scene, require_registration, digest
from rules161 import candidates, manual_signal, model_matrix, fit_preprocess, transform, fit_logit, fit_tree, predict


def synthetic(length=8):
    """人工の観測・約定・先着ラベルを作る。

    引数: length(int)。返り値: dict。実原板や金融結果は読まない。
    """
    times = np.arange(length, dtype=float) * 30
    indices = np.arange(length, dtype=np.int64) * 10
    labels = dict(entry_index=indices+1, entry_time=times,
                  entry_price=np.column_stack((np.full(length, 1000), np.full(length, 990))),
                  primary_status=np.ones((length, 2), dtype=np.int8),
                  last_status=np.ones((length, 2), dtype=np.int8),
                  primary_resolution_index=np.column_stack((indices+2, indices+2)),
                  primary_resolution_time=np.column_stack((times+1, times+1)))
    return dict(scene=dict(session="人工_Day", split="train", start=0, kind="Day"),
                feature=dict(time=times, decision_index=indices, physical_line=indices+1,
                             phase=np.full(length, "Day")), label=labels)


class Artificial161(unittest.TestCase):
    """実市場を見ずに00161の因果順・分母・凍結制約を検査する。"""

    def test_busy_edge_is_not_recreated(self):
        """未決中の成立を解決後へ持ち越さない。

        引数: self(Artificial161)。返り値: None。
        """
        d = synthetic()
        d["label"]["primary_resolution_index"][0, 0] = 35
        signal = np.array([True, False, True, True, True, False, True, False])
        rows = collect_events(d, signal, np.zeros(8, bool), "人工", "Day")
        self.assertEqual([r["row"] for r in rows], [0, 6])

    def test_cooldown_and_exact_resolution_row(self):
        """60秒間隔と決着原行より後の再参加を確認する。

        引数: self(Artificial161)。返り値: None。
        """
        d = synthetic(7)
        d["label"]["primary_resolution_index"][0, 0] = 20
        signal = np.array([True, False, True, False, True, False, True])
        rows = collect_events(d, signal, np.zeros(7, bool), "人工", "Day")
        self.assertEqual([r["row"] for r in rows], [0, 4, 6])

    def test_unresolved_stays_in_denominator_and_busy(self):
        """未決・未約定を成功にせず場末まで再参加しない。

        引数: self(Artificial161)。返り値: None。
        """
        for status in (0, -2):
            d = synthetic()
            d["label"]["primary_status"][0, 0] = status
            d["label"]["primary_resolution_index"][0, 0] = -1
            signal = np.array([True, False, True, False, True, False, True, False])
            rows = collect_events(d, signal, np.zeros(8, bool), "人工", "Day")
            self.assertEqual(len(rows), 1)
            summary = summarize(rows, ["人工_Day"])
            self.assertEqual(summary["success_probability"], 0)
            self.assertIsNone(summary["resolved_probability"])

    def test_buy_sell_mirror(self):
        """価格と板の上下反転で手動入口の方向だけが反転する。

        引数: self(Artificial161)。返り値: None。
        """
        rng = np.random.default_rng(161)
        n = 500
        f = {name: rng.normal(0, 30, n) for name in ("ret5_pt", "ret15_pt", "ret60_pt", "ret120_pt", "ret300_pt", "ret5_lag5_pt", "vel5_pt_s", "vel15_pt_s", "accel5_15_pt_s", "ofi5", "ofi15", "depth_imb", "imb1", "microprice_offset_pt", "peer_ret15_bp", "peer_ret60_bp")}
        f.update(mid=np.full(n, 65000.), spread=np.full(n, 10.), er60=rng.random(n),
                 pos60=rng.random(n), bid_refill15=rng.random(n), ask_refill15=rng.random(n),
                 high60_prev=np.full(n, 65020.), low60_prev=np.full(n, 64980.),
                 range60_pt=np.full(n, 80.), range60_previous_pt=np.full(n, 40.), peer_age_s=np.full(n, 1.))
        mirrored = {name: values.copy() for name, values in f.items()}
        for name in ("ret5_pt", "ret15_pt", "ret60_pt", "ret120_pt", "ret300_pt", "ret5_lag5_pt", "vel5_pt_s", "vel15_pt_s", "accel5_15_pt_s", "ofi5", "ofi15", "depth_imb", "imb1", "microprice_offset_pt", "peer_ret15_bp", "peer_ret60_bp"):
            mirrored[name] = -f[name]
        mirrored["mid"] = 130000 - f["mid"]
        mirrored["high60_prev"] = 130000 - f["low60_prev"]
        mirrored["low60_prev"] = 130000 - f["high60_prev"]
        mirrored["pos60"] = 1 - f["pos60"]
        mirrored["bid_refill15"], mirrored["ask_refill15"] = f["ask_refill15"], f["bid_refill15"]
        for candidate in candidates():
            if candidate["kind"] == "manual":
                np.testing.assert_array_equal(manual_signal(f, candidate, 1), manual_signal(mirrored, candidate, -1))
        np.testing.assert_allclose(model_matrix(f, 1), model_matrix(mirrored, -1))

    def test_all_manual_missing_no_signal(self):
        """必須価格が全欠測なら手動条件は成立しない。

        引数: self(Artificial161)。返り値: None。
        """
        keys = ("spread", "ret5_pt", "ret15_pt", "ret60_pt", "ret120_pt", "ret5_lag5_pt", "er60", "vel5_pt_s", "vel15_pt_s", "ofi5", "ofi15", "pos60", "depth_imb", "bid_refill15", "ask_refill15", "peer_ret60_bp", "mid", "peer_age_s", "high60_prev", "low60_prev", "range60_pt", "range60_previous_pt")
        f = {key: np.array([np.nan]) for key in keys}
        for candidate in candidates():
            if candidate["kind"] == "manual":
                self.assertFalse(manual_signal(f, candidate, 1).any())

    def test_known_candidate_count(self):
        """24手動と10学習候補が一意である。

        引数: self(Artificial161)。返り値: None。
        """
        rows = candidates()
        self.assertEqual(len(rows), 34)
        self.assertEqual(len({row["id"] for row in rows}), 34)
        self.assertEqual(sum(row["kind"] == "manual" for row in rows), 24)

    def test_model_training_and_frozen_transform(self):
        """学習の動作と変換固定を人工データで検査する。

        引数: self(Artificial161)。返り値: None。
        """
        x = np.linspace(-2, 2, 200).reshape(-1, 1)
        y = (x[:, 0] > 0).astype(float)
        pre = fit_preprocess(x)
        before = json.dumps(pre)
        z = transform(x, pre)
        for model in (fit_logit(z, y, np.ones(200)), fit_tree(z, y, np.ones(200))):
            score = predict(z, model)
            self.assertGreater(score[-1], score[0])
        transform(np.array([[1000000.], [np.nan]]), pre)
        self.assertEqual(json.dumps(pre), before)

    def test_test_access_is_denied_before_file_read(self):
        """選択段階にtestパスを渡してもファイルを開かない。

        引数: self(Artificial161)。返り値: None。
        """
        access = []
        with self.assertRaises(ValueError):
            load_scene(dict(session="存在しない", split="test"), Path("存在しない"), {"train", "validation"}, access)
        self.assertEqual(access, [])

    def test_numeric_phase_npz_connection(self):
        """抽出側と同じ分割フォルダと数字phaseを接続する。

        引数: self(Artificial161)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("features", "labels"):
                (root / name / "train").mkdir(parents=True)
            np.savez(root / "features/train/人工.npz", features=np.array([[10.], [20.], [30.]]),
                     feature_names=np.array(["mid"]), time=np.array([10., 20., 30.]),
                     decision_index=np.array([1, 3, 5]), physical_line=np.array([2, 4, 6]), phase=np.array([0, 1, 2], dtype=np.int8))
            np.savez(root / "labels/train/人工.npz", decision_time=np.array([10., 20., 30.]), decision_index=np.array([1, 3, 5]))
            access = []
            data = load_scene(dict(session="人工", split="train"), root, {"train"}, access)
            self.assertEqual(list(data["feature"]["phase"]), ["Day", "preUS", "postUS"])
            self.assertEqual(len(access), 1)

    def test_minimums_and_selection_do_not_use_opposite(self):
        """分布不足を除き、反対側の勝ちを選択に使わない。

        引数: self(Artificial161)。返り値: None。
        """
        low = dict(events=10, active_sessions=2, long_events=9, short_events=1, max_session_share=.9)
        self.assertEqual(len(eligibility(low, "train")), 4)
        base = dict(wilson95=[.5, .8], session_cluster95=[.45, .9], success_probability=.7, events=30)
        reports = {"Day": {"A01": dict(train_exclusions=[], validation_exclusions=[], validation={**base, "opposite_success_probability": 1}), "B01": dict(train_exclusions=[], validation_exclusions=[], validation={**base, "opposite_success_probability": 0})}}
        self.assertEqual(select_final(reports), {"Day": "A01"})

    def test_failed_receipt_is_rejected(self):
        """許可項目が残った失敗受領でも金融ファイルを読まない。

        引数: self(Artificial161)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            spec, manifest, receipt = root / "spec.json", root / "manifest.json", root / "receipt.json"
            spec.write_text("{}", encoding="utf-8")
            manifest.write_text("{}", encoding="utf-8")
            data = dict(registered=True, returncode=1, allowed_stages=["train_validation"], spec_sha256=digest(spec), manifest_sha256=digest(manifest))
            receipt.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                require_registration(receipt, "train_validation", spec, manifest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
