"""共通台帳の重複判定を、経済結果を使わず境界で確かめる。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

import duplicate_check as target


def fixture() -> dict:
    """
    機能: 8部品を全て明示した人工の実行仕様を作る。
    引数: なし。
    返り値: dictは相互に独立な変更検査用spec。正式条件又は成績ではない。
    """
    return dict(entry={"信号": "人工", "窓秒": 30, "方向": ["買い", "売り"]},
        management={"外部filter": True, "停止予算倍": 1},
        exit={"初期支持呼値": 4, "R発動倍": 2, "R追尾倍": 1},
        allocation={"商品": "TOPIXmini", "実数量": 10},
        costs={"一枚片道税込円": 41.8, "丸め": "一注文一円未満切捨て"},
        execution={"方式": "次の正常quote", "買い": "ask", "売り": "bid", "force秒": 60},
        data={"場": ["人工Day"], "内容SHA256": "a" * 64, "入力版": "人工v1"},
        implementation={"sourceSHA256": "b" * 64, "順序版": 1})


# ----------------------------------------
class Boundaries(unittest.TestCase):
    """名前・順序・数量・不完全仕様の各境界を検査する。"""

    def compare(self, old: dict, new: dict) -> dict:
        """
        機能: 二つの完全仕様の比較を簡潔に呼び出す。
        引数: old/new(dict)は人工spec。
        返り値: dictはanalyzeの判定。
        """
        return target.analyze({"id": "新名称", "spec": new}, [{"id": "旧名称", "status": "完了", "spec": old}])

    def test_name_and_results_are_ignored(self):
        """
        機能: ID・名前・説明・損益の変更が条件指紋に入らないことを確認する。
        引数: なし。
        返り値: None。異なる条件を同一扱いした場合は検査失敗。
        """
        spec = fixture()
        result = target.analyze({"id": "別ID", "name": "別名", "説明": "別説明", "結果": float("nan"), "spec": spec},
            [{"id": "旧ID", "name": "旧名", "結果": -999, "status": "検証済み", "spec": deepcopy(spec)}])
        self.assertTrue(result["再利用可能"])
        self.assertTrue(result["proposal_complete"])
        self.assertEqual(result["matches"][0]["id"], "旧ID")
        self.assertEqual(result["matches"][0]["kind"], "完全同一")
        self.assertEqual(result["比較"][0]["判定"], "完全同一")
        json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_nested_identifiers_and_file_names_are_kept(self):
        """
        機能: spec内のモデルIDと入力ファイル名を条件又はデータ差として保持する。
        引数: なし。
        返り値: None。
        """
        old = fixture(); old["entry"]["model"] = {"id": "人工モデル1"}
        new = deepcopy(old); new["entry"]["model"]["id"] = "人工モデル2"
        comparison = self.compare(old, new)["matches"][0]
        self.assertEqual(comparison["kind"], "条件差")
        self.assertIn("入口.model.id", comparison["部品差"][0]["位置"])
        old = fixture(); old["data"]["files"] = [{"name": "入力1", "内容SHA256": "a"*64}]
        new = deepcopy(old); new["data"]["files"][0]["name"] = "入力2"
        self.assertEqual(self.compare(old, new)["matches"][0]["kind"], "新データ")
        tagged = deepcopy(old); tagged["name"] = "specの未分類項目"
        self.assertFalse(self.compare(old, tagged)["proposal_complete"])

    def test_dictionary_order_is_ignored(self):
        """
        機能: 辞書の順序だけの変更で再試行しない。
        引数: なし。
        返り値: None。
        """
        old = fixture()
        new = {key: dict(reversed(list(part.items()))) for key, part in reversed(list(old.items()))}
        self.assertTrue(self.compare(old, new)["再利用可能"])

    def test_list_order_is_kept(self):
        """
        機能: 規則や配分の配列順変更を残す。
        引数: なし。
        返り値: None。
        """
        old = fixture(); new = deepcopy(old)
        new["entry"]["方向"].reverse()
        self.assertEqual(self.compare(old, new)["比較"][0]["判定"], "条件差")

    def test_quantity_cost_time_and_rule(self):
        """
        機能: 数量・費用・約定時刻・途中ルールの各差を条件差とする。
        引数: なし。
        返り値: None。
        """
        for part, key, value in (("allocation", "実数量", 1), ("costs", "一枚片道税込円", 11),
                ("execution", "force秒", 30), ("management", "停止予算倍", 2), ("exit", "R追尾倍", 2)):
            with self.subTest(部品=part):
                old = fixture(); new = deepcopy(old); new[part][key] = value
                comparison = self.compare(old, new)["比較"][0]
                self.assertEqual(comparison["判定"], "条件差")
                self.assertEqual(comparison["変更部品"], [target.LABELS[part]])
                self.assertIn(key, comparison["部品差"][0]["位置"])

    def test_data_only(self):
        """
        機能: ルール同一でデータだけ変わった場合を区別する。
        引数: なし。
        返り値: None。
        """
        old = fixture(); new = deepcopy(old); new["data"]["内容SHA256"] = "c" * 64
        self.assertEqual(self.compare(old, new)["比較"][0]["判定"], "新データ")

    def test_implementation_only_and_both(self):
        """
        機能: 実装変更だけとデータも変わった場合を別分類する。
        引数: なし。
        返り値: None。
        """
        old = fixture(); new = deepcopy(old); new["implementation"]["sourceSHA256"] = "d" * 64
        self.assertEqual(self.compare(old, new)["比較"][0]["判定"], "実装差")
        new["data"]["場"].append("人工Night")
        self.assertEqual(self.compare(old, new)["比較"][0]["判定"], "データ及び実装差")

    def test_boolean_is_not_numeric(self):
        """
        機能: boolと1、整数と1.0が同じ指紋へ潰れないことを確認する。
        引数: なし。
        返り値: None。
        """
        old = fixture(); new = deepcopy(old); new["management"]["外部filter"] = 1
        self.assertEqual(self.compare(old, new)["比較"][0]["判定"], "条件差")
        new = deepcopy(old); new["allocation"]["実数量"] = 10.0
        self.assertFalse(self.compare(old, new)["再利用可能"])

    def test_missing_and_unknown_are_incomplete(self):
        """
        機能: 欠落・null・unknown・空を不完全扱いにする。
        引数: なし。
        返り値: None。
        """
        for value in (None, "unknown", "未登録", {}, [], {"source": "unknown"}, {"source": None}):
            with self.subTest(不完全=value):
                spec = fixture(); spec["data"] = value
                result = self.compare(fixture(), spec)
                self.assertFalse(result["提案完全"])
                self.assertFalse(result["再利用可能"])
        spec = fixture(); del spec["implementation"]
        self.assertFalse(self.compare(fixture(), spec)["提案完全"])

    def test_incomplete_history_is_not_nonduplicate_proof(self):
        """
        機能: 過去の欠落仕様を重複なしの証明に使わない。
        引数: なし。
        返り値: None。
        """
        old = fixture(); del old["data"]
        result = self.compare(old, fixture())
        self.assertEqual(result["比較可能件数"], 0)
        self.assertEqual(len(result["不完全な過去試行"]), 1)
        self.assertEqual(len(result["incomplete_history"]), 1)
        self.assertFalse(result["matches"])
        self.assertFalse(result["重複なしの証明"])
        self.assertIn("未照合", result["判定"])

    def test_complete_match_with_incomplete_other(self):
        """
        機能: 不完全記録が併存しても実在する完全一致だけを再利用する。
        引数: なし。
        返り値: None。
        """
        result = target.analyze({"spec": fixture()}, [{"spec": fixture(), "status": "完了"}, {"id": "欠落"}])
        self.assertTrue(result["再利用可能"])
        self.assertEqual(result["比較可能件数"], 1)
        self.assertEqual(len(result["不完全な過去試行"]), 1)

    def test_nan_infinity_and_non_json(self):
        """
        機能: NaN・無限大・非JSON型・不正キーを拒否する。
        引数: なし。
        返り値: None。
        """
        for value in (float("nan"), float("inf"), float("-inf"), (1, 2), {1, 2}, {1: "値"}):
            with self.subTest(値=repr(value)):
                spec = fixture(); spec["data"]["不正"] = value
                self.assertFalse(target.analyze({"spec": spec}, [])["提案完全"])
                with self.assertRaises(ValueError):
                    target.canonical(spec)

    def test_direct_spec_and_unknown_top_field(self):
        """
        機能: 直接8部品を受け付け、spec外側と内側の情報を区別する。
        引数: なし。
        返り値: None。
        """
        result = target.analyze(fixture(), [fixture()])
        self.assertTrue(result["proposal_complete"])
        self.assertEqual(result["matches"][0]["kind"], "完全同一")
        self.assertFalse(result["reusable"])
        spec = fixture(); spec["未分類ルール"] = {"値": 2}
        self.assertFalse(target.analyze({"spec": spec}, [])["提案完全"])
        self.assertFalse(target.analyze({"spec": fixture()}, [])["重複なしの証明"])

    def test_addition_and_deletion_details(self):
        """
        機能: 部品内のキー追加・削除を日本語位置付きで記録する。
        引数: なし。
        返り値: None。
        """
        old = fixture(); new = deepcopy(old)
        del new["exit"]["初期支持呼値"]; new["exit"]["新規則"] = 3
        differences = self.compare(old, new)["比較"][0]["部品差"]
        self.assertEqual({item["変更"] for item in differences}, {"新規項目", "項目削除"})

    def test_big_integer_and_sha_stability(self):
        """
        機能: 2の53乗より大きな整数と正規UTF-8の指紋を保つ。
        引数: なし。
        返り値: None。
        """
        spec = fixture(); spec["data"]["原seq"] = 2**53 + 1
        result = target.analyze({"spec": spec}, [{"spec": deepcopy(spec), "status": "完了"}])
        self.assertTrue(result["再利用可能"])
        expected = hashlib.sha256(target.canonical(spec).encode("utf-8")).hexdigest()
        self.assertEqual(result["提案指紋"]["全体"], expected)
        changed = deepcopy(spec); changed["data"]["原seq"] += 1
        self.assertEqual(self.compare(spec, changed)["比較"][0]["判定"], "新データ")

    def test_type_guard(self):
        """
        機能: trials配列の契約違反を黙って重複なしにしない。
        引数: なし。
        返り値: None。
        """
        with self.assertRaises(TypeError):
            target.analyze({"spec": fixture()}, {})

    def test_identical_unexecuted_or_failed_result_is_not_reusable(self):
        """
        機能: 完全同一の計画でも未実行・入力失敗・status欠落では結果再利用を許可しない。
        引数: なし。
        返り値: None。
        """
        for status in ("未実行", "入力失敗", "計画", "実行中", "成功", "不明", None, False):
            with self.subTest(状態=status):
                old = {"id": "同一計画", "spec": fixture()}
                if status is not None:
                    old["status"] = status
                result = target.analyze({"spec": fixture()}, [old])
                self.assertEqual(result["matches"][0]["kind"], "完全同一")
                self.assertFalse(result["reusable"])
                self.assertFalse(result["matches"][0]["reusable"])
                self.assertTrue(result["matches"][0]["警告"])
                self.assertTrue(result["実績なしの完全同一"])

    def test_only_completed_or_verified_status_can_reuse(self):
        """
        機能: 明示statusが検証済み又は完了の完全一致だけを結果再利用とする。
        引数: なし。
        返り値: None。
        """
        for status in ("検証済み", "完了"):
            with self.subTest(状態=status):
                result = target.analyze({"spec": fixture()}, [{"spec": fixture(), "status": status}])
                self.assertTrue(result["reusable"])
                self.assertTrue(result["matches"][0]["reusable"])
        result = target.analyze({"spec": fixture()}, [
            {"id": "未実行", "spec": fixture(), "status": "未実行"},
            {"id": "完了済", "spec": fixture(), "status": "完了"},
            {"id": "欠落", "status": "完了"}])
        self.assertTrue(result["reusable"])
        self.assertEqual(len(result["再利用できる完全同一"]), 1)
        self.assertEqual(len(result["実績なしの完全同一"]), 1)


# ----------------------------------------
if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Boundaries)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    here = Path(__file__).resolve().parent
    proof = {"全合格": result.wasSuccessful(), "人工専用": True, "検査件数": result.testsRun,
        "SHA256": {name: hashlib.sha256((here/name).read_bytes()).hexdigest()
            for name in ("duplicate_check.py", "test_duplicate_check.py")},
        "金融再生": 0, "原本読取": 0, "API取得": 0,
        "範囲": "ID変更・辞書順・配列順・数量・費用・時刻・ルール・データ・実装・型・欠落・NaN等の境界"}
    (here/"重複判定の純Python人工検査.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
