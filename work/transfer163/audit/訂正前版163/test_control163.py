"""前40場の選択規則とGo成果の結合を人工資料だけで確認する。"""
import copy
from pathlib import Path
import unittest

from register163 import build_plan, record, schema_check, CONFIG_IDS, CANDIDATE_IDS
from freeze163 import rank_candidates, verify_proof, scene_summaries


class ControlTests(unittest.TestCase):
    """schema、順位、未完済拒否を反例で確認する。"""

    def rows(self, key, values, minimum):
        """人工的な場収支を作る。

        引数: key(str)、values(list[float])、minimum(float)。返り値: list[dict]。
        """
        return [dict(id=key,session=str(i),realized=v,minimum_equity=minimum) for i,v in enumerate(values)]

    def test_schema(self):
        """入力場一覧の欠落を小さい仮正本だけで拒否する。

        引数: なし。返り値: None。
        """
        plan = build_plan(record(Path(__file__)), [])
        schema_check(plan)
        del plan["spec"]["data"]["sessions"]
        with self.assertRaises(KeyError):
            schema_check(plan)

    def test_losing_count(self):
        """合計大勝ちより赤字場数を優先する。

        引数: なし。返り値: None。
        """
        rows = self.rows("D40",[1,1,1,1],-100)+self.rows("D80",[-1,100,100,100],-1)
        self.assertEqual(rank_candidates(rows,["D40","D80"])[0]["id"],"D40")

    def test_remaining_priority(self):
        """25%点・場内最低・合計・IDの順を検査する。

        引数: なし。返り値: None。
        """
        rows = self.rows("D40",[10,10,10,10],-100)+self.rows("D80",[1,1,100,100],0)
        self.assertEqual(rank_candidates(rows,["D40","D80"])[0]["id"],"D40")
        rows = self.rows("D40",[1,1,1,100],-100)+self.rows("D80",[1,1,1,2],-50)
        rows += self.rows("E40",[1,1,1,3],-50)+self.rows("E80",[1,1,1,3],-50)
        self.assertEqual([r["id"] for r in rank_candidates(rows,["D40","D80","E40","E80"])],["E40","E80","D80","D40"])

    def test_day_night_independent(self):
        """昼夜を混ぜた最大額で選択しないことを確認する。

        引数: なし。返り値: None。
        """
        rows=[]
        for kind,winner in (("Day","D40"),("Night","E80")):
            for key in CANDIDATE_IDS:
                rows += [dict(r,kind=kind) for r in self.rows(key,[1 if key==winner else -1]*20,-10)]
        got={kind:rank_candidates([r for r in rows if r["kind"]==kind],sorted(CANDIDATE_IDS))[0]["id"] for kind in ("Day","Night")}
        self.assertEqual(got,{"Day":"D40","Night":"E80"})

    def test_go_schema_and_open_positions(self):
        """Go台帳の大小キーと10案結合、未完済拒否を確認する。

        引数: なし。返り値: None。
        """
        scene=dict(session="人工_Day",kind="Day")
        result=dict(scene=scene,cases=[dict(config=dict(id=key),actual=dict(Active=[],Pending=[],Lots={},Realized=12,Risk=dict(Minimum=-3))) for key in sorted(CONFIG_IDS)])
        rows=scene_summaries(result,scene)
        self.assertEqual(len(rows),10)
        self.assertEqual(rows[0]["realized"],12)
        bad=copy.deepcopy(result)
        bad["cases"][0]["actual"]["Lots"]["残玉"]={"Remaining":1}
        with self.assertRaises(AssertionError):
            scene_summaries(bad,scene)

    def test_duplicates_and_failed_proof(self):
        """重複場と不成功証跡を拒否する。

        引数: なし。返り値: None。
        """
        rows=self.rows("D40",[1],-10)
        with self.assertRaises(AssertionError):
            rank_candidates(rows+rows,["D40"])
        for code in (True,1,None):
            with self.assertRaises(AssertionError):
                verify_proof(dict(completed=True,returncode=code),"train_validation",40)


if __name__=="__main__":
    unittest.main()
