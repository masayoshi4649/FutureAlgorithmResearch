"""実際のtest結果を開かずに診断器を人工データで検査する。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

from diagnose161 import authorize, sha, verify_event, summarize, raw_example, markdown, quantiles

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"features"))
from test_features161 import market, scene
from features161 import build_features
from labels161 import make_labels
from later_hit161 import aggregate


def event_for(features: dict, labels: dict, row: int, side: int) -> dict:
    """人工NPZから候補の保存事象と同じ構造を作る。

    引数: features/labels(dict)、row/side(int)。返り値: dict。
    """
    column = 0 if side == 1 else 1
    return {"session": "人工Night", "phase": "preUS", "candidate": "人工", "side": side, "row": row,
            "decision_index": int(features["decision_index"][row]), "physical_line": int(features["physical_line"][row]),
            "decision_time": float(features["time"][row]), "entry_index": int(labels["entry_index"][row]),
            "entry_time": float(labels["entry_time"][row]), "entry_price": float(labels["entry_price"][row, column]),
            "status": int(labels["primary_status"][row, column]), "resolution_index": int(labels["primary_resolution_index"][row, column]),
            "resolution_time": float(labels["primary_resolution_time"][row, column])}


class DiagnosisTests(unittest.TestCase):
    """未来ラベルを読み込む許可と、時系列の極値定義を確認する。"""

    def test_gate_before_results_exist(self):
        """完了許可がない時は結果ファイルを開く前に拒否する。

        引数: self(DiagnosisTests)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as temporary:
            p = Path(temporary)
            permission = p/"許可.json"
            permission.write_text('{"root_completed":false}', encoding="utf-8")
            with self.assertRaises(ValueError):
                authorize(permission,p/"不存在結果.json",p/"不存在選択.json")
            result, freeze = p/"locked.json", p/"freeze.json"
            result.write_text('{}',encoding="utf-8")
            freeze.write_text('{}',encoding="utf-8")
            permission.write_text(json.dumps({"root_completed":True,"locked_test_sha256":sha(result),"freeze_sha256":sha(freeze)}),encoding="utf-8")
            authorize(permission,result,freeze)
            result.write_text('{"変更":true}',encoding="utf-8")
            with self.assertRaises(ValueError):
                authorize(permission,result,freeze)

    def test_before_resolution_excludes_jump_and_keeps_spread(self):
        """障壁到達行の飛びを先着前極値へ混ぜず、建値の気配差を残す。

        引数: self(DiagnosisTests)。返り値: None。
        """
        times = np.array([0.,1.,2.,3.,70.,71.])
        own = market(times,np.array([1000.,1000.,1020.,1010.,1130.,900.]))
        f = build_features(own,market(times-.5,np.full(len(times),2000.)),scene())
        labels = make_labels(own,own["observations"],scene())
        e = verify_event(event_for(f,labels,0,1),f,labels)
        self.assertTrue(e["primary_path_gap_gt60"])
        x = raw_example(e,own,f)
        self.assertEqual(x["before_resolution"]["maximum_favorable_pt"],10)
        self.assertEqual(x["before_resolution"]["maximum_adverse_pt"],10)
        self.assertEqual(x["through_resolution"]["maximum_favorable_pt"],120)
        self.assertEqual(x["through_resolution"]["maximum_adverse_pt"],10)
        self.assertEqual(x["points"][2]["index"],4)
        self.assertEqual(x["context"][-1]["index"],0)
        summary = summarize([e])
        self.assertEqual(summary["success"],1)
        self.assertEqual(summary["quality"]["primary_path_gap_gt60"]["count"],1)
        self.assertEqual(summary["timing_by_outcome"]["success"]["entry_to_resolution_s"]["median"],69)
        self.assertEqual(quantiles([0,1,2,3,4,None])["q25"],1)

    def test_sell_direction_and_denominator(self):
        """売りの返済askを用い、未到達・未約定を成功分母に残す。

        引数: self(DiagnosisTests)。返り値: None。
        """
        times = np.arange(5.)
        own = market(times,np.array([1000.,1000.,980.,1050.,800.]))
        f = build_features(own,market(times-.5,np.full(5,2000.)),scene())
        labels = make_labels(own,own["observations"],scene())
        e = verify_event(event_for(f,labels,0,-1),f,labels)
        x = raw_example(e,own,f)
        self.assertEqual(e["status"],-1)
        self.assertEqual(x["through_resolution"]["maximum_adverse_pt"],60)
        self.assertEqual(x["before_resolution"]["maximum_favorable_pt"],10)
        fake_unresolved = {**e,"status":0}
        fake_noentry = {**e,"status":-2,"entry_index":-1}
        summary = summarize([e,fake_unresolved,fake_noentry])
        self.assertEqual(summary["events"],3)
        self.assertEqual(summary["entered"],2)
        self.assertEqual(summary["unresolved"],1)
        self.assertEqual(summary["no_entry"],1)
        output = markdown({"selected":{"preUS":"人工"},"phase":[{"phase":"preUS",**summary}],"examples":[x]})
        self.assertIn("3|0|1|1|1",output)

    def test_later_hit_is_not_first_success(self):
        """後から100円へ回復しても50円先着の結果と分母を変更しない。

        引数: self(DiagnosisTests)。返り値: None。
        """
        result = aggregate([{"status":-1,"down":10,"up":20},{"status":-1,"down":15,"up":-1},
                            {"status":1,"down":30,"up":10},{"status":0,"down":-1,"up":-1},
                            {"status":-2,"down":-1,"up":-1}])
        self.assertEqual(result["all_signals"],5)
        self.assertEqual(result["success_first"],1)
        self.assertEqual(result["adverse_first"],2)
        self.assertEqual(result["later_favorable_after_adverse"],1)
        self.assertEqual(result["conditional_rate"],.5)
        self.assertEqual(result["ever_favorable"],2)


if __name__ == "__main__":
    unittest.main()
