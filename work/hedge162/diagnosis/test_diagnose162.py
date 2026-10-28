"""保存約定の対応と会計分解を人工系列だけで検査する。"""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from configs162 import configurations
from replay162 import run_market
from test_replay162 import artificial
from diagnose162 import parent_records, compare, case_row, choose_examples, detail_example, markdown, summary_rows


class DiagnosisTests(unittest.TestCase):
    """親IDの偶然の一致に依存せず、全損益を保存明細へ対応する。"""

    @classmethod
    def setUpClass(cls):
        """実資料を読まず、既存の人工一場の保存形式を作る。

        引数: cls(type)。返り値: None。
        """
        scene, market, feature, frozen = artificial()
        cls.saved = run_market(scene, market, feature, frozen, configurations())
        cls.cases = {c["id"]: c for c in cls.saved["cases"]}

    def test_all_cases_full_parent_identity_and_delta(self):
        """26条件の全玉会計と、N00差の四要因が一致することを確認する。

        引数: self(DiagnosisTests)。返り値: None。
        """
        for case in self.cases.values():
            parents = parent_records(case)
            self.assertEqual(sum(p["net"] for p in parents.values()), case["summary"]["realized"])
            result = compare(case, self.cases["N00"])
            total = sum(result[k] for k in ("cover_net", "common_main_delta", "lost_main_effect", "new_main_effect"))
            self.assertEqual(result["net_delta"], total)
        changed = copy.deepcopy(self.cases["N00"])
        vanished = next(iter(parent_records(changed).values()))
        changed["events"] = [e for e in changed["events"] if e["order"]["parent"] != vanished["parent"]]
        changed["summary"]["realized"] -= vanished["net"]
        result = compare(changed, self.cases["N00"])
        self.assertEqual(result["lost_parents"], 1)
        self.assertEqual(result["lost_main_effect"], -vanished["main_net"])

    def test_different_parent_and_lot_ids_do_not_change_match(self):
        """全所有IDを替えても同判断の主親が同じ対応を保つことを確認する。

        引数: self(DiagnosisTests)。返り値: None。
        """
        changed = copy.deepcopy(self.cases["N00"])
        for p in changed["parents"]:
            p["id"] = "改" + p["id"]
        for lot in changed["lots"]:
            lot["id"], lot["parent"] = "改" + lot["id"], "改" + lot["parent"]
        for event in changed["events"]:
            order = event["order"]
            order["id"], order["parent"] = "改" + order["id"], "改" + order["parent"]
            if order["target"]:
                order["target"] = "改" + order["target"]
        result = compare(changed, self.cases["N00"])
        self.assertEqual(result["net_delta"], 0)
        self.assertEqual(result["lost_parents"] + result["new_parents"], 0)

    def test_proxy_reference_and_artificial_report(self):
        """終端代理の気配参照を保ち、短い報告を欠落なく作る。

        引数: self(DiagnosisTests)。返り値: None。
        """
        case = self.cases["H01"]
        row = case_row(self.saved, case, self.cases["N00"], self.cases["S00"])
        row["example"] = "worse"
        example = detail_example(self.saved, case, self.cases["N00"], row)
        report = {"methods": [{"id": "H01", "examples": [example],
                    "periods": {p: summary_rows([row]) for p in ("train_validation", "locked_test", "all")}}]}
        text = markdown(report)
        self.assertIn("N00", text)
        self.assertIn("人工Day", text)
        scene, market, feature, frozen = artificial()
        scene["end"] = 6
        market = {k: v[:18] if k != "observations" else v[:6] for k, v in market.items()}
        feature = {k: v if k == "feature_names" else v[:6] for k, v in feature.items()}
        shortened = run_market(scene, market, feature, frozen, [configurations()[1]])["cases"][0]
        proxies = [e for p in parent_records(shortened).values() for e in p["events"] if e["proxy"]]
        self.assertGreater(len(proxies), 0)
        self.assertTrue(all(e["fill_index"] is None and e["quote"]["index"] >= 0 for e in proxies))

    def test_example_selection_has_losses_and_one_improvement(self):
        """説明例が悪化3場と改善1場へ固定され、同額は日付順になる。

        引数: self(DiagnosisTests)。返り値: None。
        """
        rows = [{"session": str(i), "comparison": {"net_delta": x}}
                for i, x in enumerate((20, -1, -10, -2, 10, -5, 0))]
        selected = choose_examples(rows)
        self.assertEqual([r["comparison"]["net_delta"] for r in selected], [-10, -5, -2, 20])


if __name__ == "__main__":
    unittest.main()
