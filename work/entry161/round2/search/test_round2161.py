"""第二巡の分位、分解対照、上下対称、既知後半表示を市場ラベルなしで検査する。"""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from rules161r2 import candidates, load_thresholds, signal
import engine161r2


def features():
    """一行の人工板特徴を作る。

    引数: なし。返り値: dict[str,ndarray]。
    """
    return {key: np.array([value], dtype=float) for key, value in dict(spread=10, ofi15=.1, depth_imb=.2,
        bid_refill15=.2, ask_refill15=.05, ret15_pt=0, ret5_pt=10).items()}


def thresholds():
    """上下対称の正閾値を作る。

    引数: なし。返り値: dict。
    """
    return {phase: {key: dict(quantiles={"0.5": .05, "0.75": .10, "0.9": .15})
                    for key in ("ofi15", "depth_imb", "bid_refill15", "ask_refill15")}
            for phase in ("Day", "preUS", "postUS")}


class RoundTwo161(unittest.TestCase):
    """第二巡独自の境界と成果の分離を確認する。"""

    def test_candidate_count(self):
        """8構造×3分位のIDが一意である。

        引数: self(RoundTwo161)。返り値: None。
        """
        rows = candidates()
        self.assertEqual(len(rows), 24)
        self.assertEqual(len({row["id"] for row in rows}), 24)

    def test_no_unnecessary_and_in_decomposition(self):
        """OFI単独は補充欠測、補充単独はOFI欠測でも成立できる。

        引数: self(RoundTwo161)。返り値: None。
        """
        rules = {row["id"]: row for row in candidates()}
        f = features()
        f["bid_refill15"][:] = np.nan
        f["ask_refill15"][:] = np.nan
        f["depth_imb"][:] = np.nan
        self.assertTrue(signal(f, rules["BF01"], 1, "Day", thresholds())[0])
        f = features()
        f["ofi15"][:] = np.nan
        self.assertTrue(signal(f, rules["BR01"], 1, "Day", thresholds())[0])

    def test_absorption_uses_alternative_routes(self):
        """吸収の二経路で逆OFIと補充を同時必須にしない。

        引数: self(RoundTwo161)。返り値: None。
        """
        rules = {row["id"]: row for row in candidates()}
        f = features()
        f["ofi15"][:] = -.1
        f["bid_refill15"][:] = .01
        self.assertTrue(signal(f, rules["BU01"], 1, "Day", thresholds())[0])
        f = features()
        self.assertTrue(signal(f, rules["BU01"], 1, "Day", thresholds())[0])
        self.assertFalse(signal(f, rules["BS01"], 1, "Day", thresholds())[0])

    def test_zero_flow_is_not_signal(self):
        """分位下限が正なので数量変化ゼロを支持へ変えない。

        引数: self(RoundTwo161)。返り値: None。
        """
        f = features()
        for key in ("ofi15", "depth_imb", "bid_refill15", "ask_refill15"):
            f[key][:] = 0
        t = thresholds()
        for columns in t.values():
            for record in columns.values():
                record["quantiles"] = {"0.5": 1e-12, "0.75": 1e-12, "0.9": 1e-12}
        for rule in candidates():
            self.assertFalse(signal(f, rule, 1, "Day", t)[0])
            self.assertFalse(signal(f, rule, -1, "Day", t)[0])

    def test_threshold_equality_and_nested_strength(self):
        """分位接触は成立し、強度を上げた包含関係を守る。

        引数: self(RoundTwo161)。返り値: None。
        """
        f = features()
        rules = {row["id"]: row for row in candidates()}
        self.assertTrue(signal(f, rules["BF02"], 1, "Day", thresholds())[0])
        self.assertFalse(signal(f, rules["BF03"], 1, "Day", thresholds())[0])

    def test_mirror_and_refill_threshold_swap(self):
        """価格方向と買売の補充分位を反転すると入口方向だけが変わる。

        引数: self(RoundTwo161)。返り値: None。
        """
        rng = np.random.default_rng(1612)
        f = {key: rng.normal(0, .2, 1000) for key in ("ofi15", "depth_imb")}
        f.update(spread=np.full(1000, 10.), ret15_pt=rng.normal(0, 20, 1000), ret5_pt=rng.normal(0, 20, 1000),
                 bid_refill15=rng.random(1000)*.2, ask_refill15=rng.random(1000)*.2)
        mirror = copy.deepcopy(f)
        for key in ("ofi15", "depth_imb", "ret15_pt", "ret5_pt"):
            mirror[key] = -f[key]
        mirror["bid_refill15"], mirror["ask_refill15"] = f["ask_refill15"], f["bid_refill15"]
        original = thresholds()
        original["Day"]["bid_refill15"]["quantiles"]["0.5"] = .04
        reversed_threshold = copy.deepcopy(original)
        reversed_threshold["Day"]["bid_refill15"], reversed_threshold["Day"]["ask_refill15"] = original["Day"]["ask_refill15"], original["Day"]["bid_refill15"]
        for rule in candidates():
            np.testing.assert_array_equal(signal(f, rule, 1, "Day", original), signal(mirror, rule, -1, "Day", reversed_threshold))

    def test_known_confirmation_metadata(self):
        """互換ファイル名でも既知後半であることを必ず記録する。

        引数: self(RoundTwo161)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "selection_frozen161.json"
            value = dict(selected={}, models={}, test_opened=False, content_sha256="旧値")
            engine161r2.write_development(path, value)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(saved["confirmation_is_known_development"])
            self.assertIn("既知資料", saved["metadata"])
            check = {key: item for key, item in saved.items() if key != "content_sha256"}
            self.assertEqual(saved["content_sha256"], engine161r2.base.canonical_digest(check))

    def test_train_only_threshold_evidence(self):
        """許可されたtrain特徴だけで分位が固定されている。

        引数: self(RoundTwo161)。返り値: None。
        """
        t = load_thresholds()
        self.assertEqual(set(t), {"Day", "preUS", "postUS"})
        saved = json.loads((Path(__file__).parent / "thresholds161r2.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved["input_features"]), 30)
        self.assertTrue(all(row["split"] == "train" and "/features/train/" in row["features"].replace("\\", "/") for row in saved["input_features"]))

    def test_runtime_dependency_connection_without_source_change(self):
        """同じ採点器へ24条件を接続し、第一巡源を変更しない。

        引数: self(RoundTwo161)。返り値: None。
        """
        base = engine161r2.base
        path = Path(base.__file__)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        keys = ("candidates", "train_models", "evaluate_candidate", "write_json")
        original = {key: getattr(base, key) for key in keys}
        try:
            engine161r2.configure()
            self.assertEqual(len(base.candidates()), 24)
            self.assertEqual(base.train_models([], None, []), {})
            self.assertIs(base.evaluate_candidate, engine161r2.evaluate_candidate)
        finally:
            for key, value in original.items():
                setattr(base, key, value)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
