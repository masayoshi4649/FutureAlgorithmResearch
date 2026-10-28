"""第二巡の再利用対照照合を、金融データなしで検査する。"""
import copy
import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from test_analyze156 import fixture
from analyze1562 import control_equal,reentry_diagnostics,verify_reentry_evidence
from analyze156 import analyze_case,normal_indices


class Controls1562(unittest.TestCase):
    """元の全売買は一致し、追加診断表示だけを許す。"""

    def test_added_diagnostic_does_not_change_trade(self):
        """新たな診断キーがあっても旧根拠と約定の一致を検査できる。

        引数: self(Controls1562)。
        返り値: なし。
        """
        old,_,_=fixture()
        new=copy.deepcopy(old)
        new["events"][0]["signal"]["evidence"]["new_reentry_diagnostic"]={"enabled":False}
        control_equal(new,old)

    def test_changed_old_evidence_or_lot_is_rejected(self):
        """原行・旧判断根拠・所有・極値・未約定の変更を見逃さない。

        引数: self(Controls1562)。
        返り値: なし。
        """
        for kind in ("index","evidence","lot","peak","pending"):
            old,_,_=fixture()
            new=copy.deepcopy(old)
            if kind=="index":new["events"][0]["fill_index"]+=1
            if kind=="evidence":new["events"][0]["signal"]["evidence"]["observation"]["Last"]+=10
            if kind=="lot":new["events"][1]["fill"]["Closed"][0]["id"]="別玉"
            if kind=="peak":new["parents"]["core/1"]["Peak"]+=100
            if kind=="pending":new["final_pending"]=[new["signals"][-1]]
            with self.assertRaises(AssertionError):
                control_equal(new,old)

    def test_reentry_lot_does_not_become_parent_account(self):
        """再参加玉と元玉を分け、旧源停止幅を診断だけへ付記する。

        引数: self(Controls1562)。
        返り値: なし。人工保存配賦以外の金融入力は使用しない。
        """
        case,scene,raw=fixture()
        row,detail=analyze_case(case,scene,raw,normal_indices(raw))
        event=next(e for e in case["events"] if e["signal"]["action"]=="new")
        event["signal"]["reason_code"]=15630
        case["snapshots"]=[{"Index":event["signal"]["source_index"],"Diagnostics":[{"owner":event["signal"]["owner"],"core_exit_shadow":{"stop_price":900,"anchor":1000}}]}]
        before=dict(row)
        reentry_diagnostics(case,detail,raw)
        item=next(l for l in detail["lots"] if l["is_reentry1562"])
        self.assertEqual(item["entry_to_old_source_stop_points"],item["side"]*(item["price"]-900))
        self.assertEqual(detail["reentry1562"]["entries"],1)
        self.assertEqual(detail["reentry1562"]["quantity"],item["quantity"])
        for key in ("net","profit","loss","positive_then_loss_count"):
            self.assertEqual(before[key],row[key])

    def test_reentry_extreme_is_from_new_raw_only(self):
        """完済後の新極値を全正常板から検算し、旧値や当行初期化を拒否する。

        引数: self(Controls1562)。
        返り値: なし。3原行の人工例だけを使う。
        """
        raw=np.array([[100,995,990,1000],[101,985,980,990],[102,1005,1000,1010]],dtype=float)
        valid=np.arange(3)
        signal={"owner":"core","action":"new","reason_code":15630,"campaign":1,"ticket":-1,"source_index":2,"quantity":1,"side":1}
        prepared={"Owner":"core","Action":"準備","Campaign":1,"Side":1,"Quantity":1,"Time":100,"Index":0}
        ordered={**prepared,"Action":"発注","Time":102,"Index":2,"Ticket":-1,"Extreme":980,"Mark":1000}
        case={"signals":[signal],"events":[{"fill_index":0,"signal":{"owner":"core","action":"close","reason_code":15601}}],"reentry1562":{"Width":20,"Audit":[prepared,ordered],"Arms":{},"Targets":{"-1":{"Requested":1,"Owner":"core","Campaign":1}}}}
        detail={"lots":[{"owner":"core","entry_index":0,"quantity":1,"closes":[{"index":0,"quantity":1}]}]}
        self.assertEqual(verify_reentry_evidence(case,detail,raw,valid)["raw_extremes_matched"],1)
        for kind in ("古い極値","完済当行","元返済"):
            changed=copy.deepcopy(case)
            if kind=="古い極値":changed["reentry1562"]["Audit"][1]["Extreme"]=900
            if kind=="完済当行":changed["reentry1562"]["Audit"][0].update(Index=1,Time=101)
            if kind=="元返済":changed["events"][0]["signal"]["reason_code"]=30
            with self.assertRaises(AssertionError):
                verify_reentry_evidence(changed,detail,raw,valid)


if __name__=="__main__":
    unittest.main()
