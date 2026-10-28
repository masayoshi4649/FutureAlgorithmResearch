"""保存採否のJSONキー誤記や支持値の見落としを防ぐ人工検査。"""

import copy
import importlib.util
from pathlib import Path
import unittest
import numpy as np
from raw_result157 import support_arrays, support_at

spec=importlib.util.spec_from_file_location("saved_audit157",Path(__file__).with_name("結果の全原板監査157.py"))
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class SavedSupport157(unittest.TestCase):
    """既知/未知を含む保存採否が実際に照合されることを検査する。"""

    def fixture(self) -> tuple:
        """人工原板と既知の採否一件を用意する。

        引数: self(SavedSupport157)。返り値: tupleはcase/自己配列/相手配列。
        """
        raw=np.array([[t,60005+t,60000+t,60010+t,10,10] for t in range(401)],dtype=float)
        own=support_arrays(raw);peer=support_arrays(raw)
        saved=support_at(own,peer,400,1)
        return {"config":{"id":"人工"},"parents":{"p":{"Side":1}},"decisions":[{"Index":400,"Parent":"p","Support":saved}]},own,peer

    def test_actual_lowercase_key_is_counted(self):
        """実JSONの小文字キーを必須とし、既知支持一件を数える。

        引数: self(SavedSupport157)。返り値: None。
        """
        case,own,peer=self.fixture()
        self.assertEqual(audit.check_support(case,own,peer,{}),{"known":1,"unknown":0})
        case["Decisions"]=case.pop("decisions")
        with self.assertRaises(AssertionError):audit.check_support(case,own,peer,{})

    def test_changed_known_and_partial_unknown_values_fail(self):
        """既知/未知や途中まで算出した値の改変を見逃さない。

        引数: self(SavedSupport157)。返り値: None。
        """
        case,own,peer=self.fixture();case["decisions"][0]["Support"]["T"]+=0.01
        with self.assertRaises(AssertionError):audit.check_support(case,own,peer,{})
        case,own,peer=self.fixture();case["decisions"][0]["Support"]["Known"]=False
        with self.assertRaises(AssertionError):audit.check_support(case,own,peer,{})
        case,own,peer=self.fixture()
        value={k:0 for k in ("OwnAt","PeerAt","Own5","Own15","Own120","Own300","Peer120","OFI30","M","T","Opp")}
        value.update(support_at(own,peer,100,1))
        case["decisions"][0].update(Index=100,Support=value)
        self.assertEqual(audit.check_support(case,own,peer,{}),{"known":0,"unknown":1})
        value["Own5"]+=0.01
        with self.assertRaises(AssertionError):audit.check_support(case,own,peer,{})


if __name__=="__main__":
    unittest.main(verbosity=2)
