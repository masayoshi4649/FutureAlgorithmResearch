"""一時ディレクトリだけで段階許可の成功・遮断を検査する。"""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parent.parent / "allow161.py"
spec = importlib.util.spec_from_file_location("allow_under_audit161", SOURCE)
allow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(allow)


def save(path, value):
    """人工JSONを一時領域へ保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(root):
    """原資料や台帳を使わず人工登録受領を作る。

    引数: root(Path)。返り値: Path は人工作業域。
    """
    here = root / "work/entry161"
    files = [here / name for name in ["inputs161.json", "search/spec161.json", "plan.json", "bundle.json"]]
    for path in files:
        save(path, {})
    refs = [dict(path=str(p.relative_to(root)), sha256=allow.sha(p)) for p in files]
    save(here/"登録受領161.json", dict(registered=True, returncode=0, sources=refs[:2], plan=refs[2], implementation=refs[3]))
    return here


class AllowTests(unittest.TestCase):
    """実資料を読まずに登録後の段階固定を検査する。"""

    def test_train_permission_only_after_unchanged_registration(self):
        """機能: 原登録指紋を保った時だけtrain許可を生成。引数: self。返り値: None。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); here = fixture(root)
            with patch.object(allow, "ROOT", root), patch.object(allow, "HERE", here), patch("sys.argv", ["allow161", "train_validation"]):
                allow.main()
            saved = json.loads((here/"train_validation_許可161.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["allowed_stages"], ["train_validation"])

    def test_changed_registered_source_is_blocked(self):
        """機能: 登録済み入力の変更を段階許可前に拒否。引数: self。返り値: None。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); here = fixture(root)
            save(here/"inputs161.json", {"changed": True})
            with patch.object(allow, "ROOT", root), patch.object(allow, "HERE", here), patch("sys.argv", ["allow161", "train_validation"]):
                with self.assertRaises(AssertionError):
                    allow.main()
            self.assertFalse((here/"train_validation_許可161.json").exists())

    def test_test_needs_frozen_selection_and_no_prior_result(self):
        """機能: 凍結前又は確認結果既存の場合にtest許可を拒否。引数: self。返り値: None。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); here = fixture(root)
            with patch.object(allow, "ROOT", root), patch.object(allow, "HERE", here), patch("sys.argv", ["allow161", "locked_test"]):
                with self.assertRaises(FileNotFoundError):
                    allow.main()
                save(here/"results/selection_frozen161.json", dict(test_opened=False,
                    manifest_sha256=allow.sha(here/"inputs161.json"), spec_sha256=allow.sha(here/"search/spec161.json")))
                save(here/"results/locked_test161.json", {})
                with self.assertRaises(AssertionError):
                    allow.main()
            self.assertFalse((here/"locked_test_許可161.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
