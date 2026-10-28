"""第二巡の板条件と段階許可を、人工資料だけで独立に確認する。"""

import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0, str(WORK / "search"))
import rules161r2
import engine161r2

spec = importlib.util.spec_from_file_location("許可監査161r2", WORK / "allow161r2.py")
allow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(allow)


def scalar(row, family, side, cuts):
    """一観測の条件をベクトル実装から独立に評価する。

    引数: row(dict)、family(str)、side(int)、cuts(dict)。返り値: bool。
    """
    spread = row["spread"]
    if not 0 < spread <= 20:
        return False
    flow = side * row["ofi15"] >= cuts["ofi15"]
    depth = side * row["depth_imb"] >= cuts["depth_imb"]
    same = "bid_refill15" if side > 0 else "ask_refill15"
    other = "ask_refill15" if side > 0 else "bid_refill15"
    refill = row[same] >= cuts[same] and row[same] > row[other]
    reverse_flow = side * row["ofi15"] <= -cuts["ofi15"]
    r15, r5 = side * row["ret15_pt"], side * row["ret5_pt"]
    if family == "BF":
        return flow
    if family == "BD":
        return depth
    if family == "BR":
        return refill
    if family == "BA":
        return flow and r15 >= 0 and r5 >= 0
    if family == "BP":
        return refill and r15 >= -10 and r5 >= 0
    if family == "BC":
        return flow and depth
    if family == "BS":
        return reverse_flow and r15 >= -10 and r5 >= 10
    if family == "BU":
        return (reverse_flow or refill) and r15 >= -10 and r5 >= 10
    raise AssertionError(family)


def save(path, value):
    """人工JSONを一時領域に保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(root):
    """両巡の人工登録と入力を生成する。

    引数: root(Path)。返り値: tuple[Path,Path] は前巡と第二巡の領域。
    """
    base = root / "work/entry161"
    current = base / "round2"
    for folder, receipt in ((base, "登録受領161.json"), (current, "登録受領161r2.json")):
        paths = [folder / name for name in ("search/spec161.json", "source.py", "plan.json", "bundle.zip")]
        for path in paths:
            save(path, {})
        refs = [dict(path=p.relative_to(root).as_posix(), sha256=allow.sha(p)) for p in paths]
        save(folder / receipt, dict(registered=True, returncode=0, sources=refs[:2], plan=refs[2], implementation=refs[3]))
    save(base / "inputs161.json", {})
    return base, current


class IndependentRoundTwo(unittest.TestCase):
    """既存ラベルを読まずに条件、欠測、段階許可の境界を検査する。"""

    def test_all_rules_match_independent_scalar(self):
        """全24条件を3区分、両側、欠測を含む人工500行で照合する。

        引数: self(IndependentRoundTwo)。返り値: None。
        """
        rng = np.random.default_rng(210161)
        f = {k: rng.normal(0, .2, 500) for k in ("ofi15", "depth_imb")}
        f.update({k: rng.uniform(0, .3, 500) for k in ("bid_refill15", "ask_refill15")})
        f.update({k: rng.integers(-30, 31, 500).astype(float) for k in ("ret5_pt", "ret15_pt")})
        f["spread"] = rng.choice([0., 10., 20., 30., np.nan], 500)
        for values in f.values():
            values[rng.choice(500, 20, replace=False)] = np.nan
        thresholds = rules161r2.load_thresholds()
        for phase in thresholds:
            for candidate in rules161r2.candidates():
                q = candidate["quantile"]
                cuts = {k: v["quantiles"][q] for k, v in thresholds[phase].items()}
                for side in (1, -1):
                    expected = [scalar({k: v[i] for k, v in f.items()}, candidate["family"], side, cuts) for i in range(500)]
                    actual = rules161r2.signal(f, candidate, side, phase, thresholds)
                    np.testing.assert_array_equal(actual, expected)

    def test_refill_tie_and_zero_are_not_direction(self):
        """補充両側同量や無変化を方向優勢と扱わない。

        引数: self(IndependentRoundTwo)。返り値: None。
        """
        f = {k: np.array([0., 1.]) for k in ("ofi15", "depth_imb", "bid_refill15", "ask_refill15")}
        f.update(spread=np.array([10., 10.]), ret5_pt=np.zeros(2), ret15_pt=np.zeros(2))
        t = rules161r2.load_thresholds()
        for rule in rules161r2.candidates():
            for side in (1, -1):
                actual = rules161r2.signal(f, rule, side, "Day", t)
                self.assertFalse(actual[0])
                if rule["family"] in ("BR", "BP"):
                    self.assertFalse(actual[1])

    def test_strict_rules_never_add_signal(self):
        """閾値強度の上昇で同じ構造の成立行が増えない。

        引数: self(IndependentRoundTwo)。返り値: None。
        """
        rng = np.random.default_rng(12)
        f = {k: rng.normal(0, .1, 1000) for k in ("ofi15", "depth_imb")}
        f.update({k: rng.random(1000) for k in ("bid_refill15", "ask_refill15")})
        f.update(spread=np.full(1000, 10.), ret5_pt=rng.normal(0, 20, 1000), ret15_pt=rng.normal(0, 20, 1000))
        t = rules161r2.load_thresholds()
        for phase in t:
            for side in (1, -1):
                for offset in range(0, 24, 3):
                    masks = [rules161r2.signal(f, c, side, phase, t) for c in rules161r2.candidates()[offset:offset+3]]
                    self.assertFalse(np.any(masks[1] & ~masks[0]))
                    self.assertFalse(np.any(masks[2] & ~masks[1]))

    def test_wrapper_never_trains_another_model(self):
        """新巡では保存特徴やラベルを読む学習器を追加しない。

        引数: self(IndependentRoundTwo)。返り値: None。
        """
        class Unreadable:
            def __iter__(self):
                raise AssertionError("人工引数を読まない")
        self.assertEqual(engine161r2.empty_models(Unreadable(), Unreadable(), Unreadable()), {})

    def test_train_permission_needs_both_unchanged_sources(self):
        """どちらかの巡の登録源が変われば評価許可を拒否する。

        引数: self(IndependentRoundTwo)。返り値: None。
        """
        for changed in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); base, current = fixture(root)
                save((current if changed else base) / "source.py", {"changed": True})
                with patch.object(allow, "ROOT", root), patch.object(allow, "BASE", base), patch.object(allow, "HERE", current), patch("sys.argv", ["allow", "train_validation"]):
                    with self.assertRaises(AssertionError):
                        allow.main()
                self.assertFalse((current / "train_validation_許可161r2.json").exists())

    def test_failed_receipt_cannot_authorize(self):
        """登録失敗を許可に転用しない。

        引数: self(IndependentRoundTwo)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); base, current = fixture(root)
            receipt = current / "登録受領161r2.json"
            value = json.loads(receipt.read_text()); value["registered"] = False
            save(receipt, value)
            with patch.object(allow, "ROOT", root), patch.object(allow, "BASE", base), patch.object(allow, "HERE", current), patch("sys.argv", ["allow", "train_validation"]):
                with self.assertRaises(AssertionError):
                    allow.main()

    def test_test_permission_needs_freeze_and_is_single_use(self):
        """後半許可には選択凍結が必要で、既存結果があれば再評価を拒否する。

        引数: self(IndependentRoundTwo)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); base, current = fixture(root)
            with patch.object(allow, "ROOT", root), patch.object(allow, "BASE", base), patch.object(allow, "HERE", current), patch("sys.argv", ["allow", "locked_test"]):
                with self.assertRaises(FileNotFoundError):
                    allow.main()
                freeze = current / "results/selection_frozen161.json"
                save(freeze, dict(spec_sha256=allow.sha(current / "search/spec161.json"), manifest_sha256=allow.sha(base / "inputs161.json")))
                allow.main()
                permit = json.loads((current / "locked_test_許可161r2.json").read_text(encoding="utf-8"))
                self.assertTrue(permit["known_test"])
                self.assertEqual(permit["freeze_sha256"], allow.sha(freeze))
                save(current / "results/locked_test161.json", {})
                with self.assertRaises(AssertionError):
                    allow.main()


if __name__ == "__main__":
    unittest.main(verbosity=2)
