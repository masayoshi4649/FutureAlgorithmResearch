"""登録前のschemaと候補順位を、実成績を使わず検査する。"""
import copy
from pathlib import Path
import unittest

from register162 import build_plan, record, schema_check
from freeze162 import rank_candidates, verify_proof


class ControlTests(unittest.TestCase):
    """管理器への小さい仮正本と固定順位の反例を検査する。"""

    def rows(self, key, values, minimum):
        """人工的な二場以上の集計を組み立てる。

        引数: key(str)、values(list[float])、minimum(float)。返り値: list[dict]。
        """
        return [dict(id=key, session=str(i), realized=v, minimum_equity=minimum) for i,v in enumerate(values)]

    def test_schema_sessions_required(self):
        """入力場一覧の欠落を、巨大正本へ触れず拒否する。

        引数: なし。返り値: None。
        """
        plan = build_plan(record(Path(__file__)), [])
        schema_check(plan)
        bad = copy.deepcopy(plan)
        del bad["spec"]["data"]["sessions"]
        with self.assertRaises(KeyError):
            schema_check(bad)

    def test_losing_count_over_total(self):
        """大勝ちの合計より赤字場数を優先する。

        引数: なし。返り値: None。
        """
        rows = self.rows("H01", [1,1,1,1], -100)+self.rows("H02", [-1,100,100,100], -1)
        self.assertEqual(rank_candidates(rows,["H01","H02"])[0]["id"], "H01")

    def test_q25_before_equity(self):
        """同じ赤字場数では下位25%収支を優先する。

        引数: なし。返り値: None。
        """
        rows = self.rows("H01", [10,10,10,10], -100)+self.rows("H02", [1,1,100,100], 0)
        self.assertEqual(rank_candidates(rows,["H01","H02"])[0]["id"], "H01")

    def test_equity_before_total_and_id(self):
        """同じ下位収支では途中リスク、次に合計、最後にIDを使う。

        引数: なし。返り値: None。
        """
        rows = self.rows("H01", [1,1,1,100], -100)+self.rows("H02", [1,1,1,2], -50)
        self.assertEqual(rank_candidates(rows,["H01","H02"])[0]["id"], "H02")
        rows += self.rows("H03", [1,1,1,3], -50)+self.rows("H04", [1,1,1,3], -50)
        self.assertEqual([r["id"] for r in rank_candidates(rows,["H01","H02","H03","H04"])], ["H03","H04","H02","H01"])

    def test_duplicate_and_failed_completion(self):
        """同一場の二重計上と失敗完了証跡を拒否する。

        引数: なし。返り値: None。
        """
        row = self.rows("H01", [1], -10)
        with self.assertRaises(AssertionError):
            rank_candidates(row+row,["H01"])
        for code in (True, 1, None):
            with self.assertRaises(AssertionError):
                verify_proof(dict(completed=True,returncode=code), "train_validation",40)


if __name__ == "__main__":
    unittest.main()
