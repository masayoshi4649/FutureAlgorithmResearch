"""凍結条件・モデル接続・同値省略を人工一場で検査する。実資料は読まない。"""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from configs162 import configurations
from replay162 import run_market, require_registration, require_stage, sha
from signals162 import EXPECTED, make_signals
from source161_rules import DIRECTIONAL, UNDIRECTED, model_matrix


def artificial() -> tuple[dict,dict,dict,dict]:
    """同秒の重複・板変化・反転を含む人工一場を作る。

    引数: なし。返り値: tuple[dict,dict,dict,dict]は場/原板/当時特徴/選択。
    """
    times = np.repeat(np.arange(240.),3)
    cycle = times % 80
    mid = np.where(cycle < 20,1000-cycle*5,np.where(cycle < 40,900+(cycle-20)*5,np.where(cycle < 60,1000+(cycle-40)*7,1140-(cycle-60)*7)))
    # 同時計の2行目以降にも別価格の正常板を混ぜ、次行約定を検査する。
    mid[1::9] += 10
    observations = np.arange(0,len(times),3)
    market = {"time":times,"bid":mid-5,"ask":mid+5,"last":mid,"valid":np.ones(len(times),dtype=bool),"line":np.arange(len(times))+1,"observations":observations}
    names = np.array(["ret5_pt","ret15_pt","ret60_pt","ofi5","spread"])
    values = np.zeros((len(observations),len(names)))
    direction = np.where(np.arange(len(observations)) % 40 < 3,1,np.where(np.arange(len(observations)) % 40 > 20,-1,0))
    values[:,0] = direction*20
    values[:,1] = direction*10
    values[:,2] = direction*-60
    values[:,3] = direction*.2
    values[:,4] = 10
    features = {"features":values,"feature_names":names,"time":times[observations],"decision_index":observations,"physical_line":observations+1,"phase":np.zeros(len(observations),dtype=np.int8)}
    scene = {"session":"人工Day","kind":"Day","split":"train","start":0,"end":250,"us_open":0}
    return scene,market,features,{"selected":EXPECTED,"models":{}}


class ReplayTests(unittest.TestCase):
    """実約定のある人工経路で仕様接続を比較する。"""

    def test_all_26_and_fast_path_equal_without_labels(self):
        """26条件を逐次版と省略版で比較し、全通知・玉・時価が一致することを確認する。

        引数: self(ReplayTests)。返り値: None。
        """
        scene,market,feature,frozen = artificial()
        definitions = configurations()
        self.assertEqual(len(definitions),26)
        self.assertEqual(definitions[2]["id"],"H01")
        self.assertEqual(definitions[-1]["id"],"H24")
        fast = run_market(scene,market,feature,frozen,definitions,True)
        slow = run_market(scene,market,feature,frozen,definitions,False)
        self.assertGreater(sum(c["summary"]["cover_entries"] for c in fast["cases"]),0)
        self.assertGreater(sum(c["skipped_unchanged_rows"] for c in fast["cases"]),0)
        for a,b in zip(fast["cases"],slow["cases"]):
            references = {r["index"]:r for r in a["reference"]}
            for event in a["events"]:
                if event.get("proxy"):
                    self.assertIn(event["quote_index"],references)
                    price = references[event["quote_index"]]["ask" if event["order"]["side"] == 1 else "bid"]
                    self.assertEqual(event["price"],price)
            a.pop("skipped_unchanged_rows")
            b.pop("skipped_unchanged_rows")
            self.assertEqual(a,b)
        self.assertFalse(fast["label_input_used"])
        # JSON化でデータ型や非有限値の混入を検査する。
        json.dumps(fast,ensure_ascii=False,allow_nan=False)

    def test_source_r02_is_condition_not_old_event_list(self):
        """全観測のR02条件を返し、将来の先着や旧採用イベントに依存しない。

        引数: self(ReplayTests)。返り値: None。
        """
        _,_,feature,frozen = artificial()
        buy,sell = make_signals(feature,frozen)
        self.assertEqual(len(buy),240)
        self.assertGreater(int(buy.sum()),10)
        self.assertGreater(int(sell.sum()),10)
        self.assertFalse((buy & sell).any())
        changed = {k:(v.copy() if isinstance(v,np.ndarray) else v) for k,v in feature.items()}
        changed["features"][120:] *= -1
        after = make_signals(changed,frozen)
        np.testing.assert_array_equal(buy[:120],after[0][:120])
        np.testing.assert_array_equal(sell[:120],after[1][:120])

    def test_registration_requires_both_success_fields(self):
        """片方だけ成功した受領を金融実行許可へしない。

        引数: self(ReplayTests)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/"receipt.json"
            for value in ({"registered":True,"returncode":1},{"registered":False,"returncode":0},{"registered":True,"returncode":False}):
                p.write_text(json.dumps(value),encoding="utf-8")
                with self.assertRaises(ValueError):
                    require_registration(p)
            p.write_text('{"registered":true,"returncode":0}',encoding="utf-8")
            require_registration(p)

    def test_night_models_and_phase_are_separate(self):
        """同じ特徴でも前後の固定モデルを取り違えず、各phaseの条件だけを返す。

        引数: self(ReplayTests)。返り値: None。
        """
        names = list(dict.fromkeys(DIRECTIONAL+UNDIRECTED+("pos60","bid_refill15","ask_refill15")))
        values = np.ones((2,len(names)))
        values[:,names.index("spread")] = 10
        feature = {"features":values,"feature_names":np.asarray(names),"time":np.asarray([100.,200.]),"phase":np.asarray([1,2])}
        columns = model_matrix({n:values[:,i] for i,n in enumerate(names)},1).shape[1]
        prep = {"median":[0.]*columns,"mean":[0.]*columns,"std":[1.]*columns}
        models = {}
        for phase,sign in (("preUS",1),("postUS",-1)):
            c = [-1.,sign*3]+[0.]*(columns*2-1)
            models[phase] = {"preprocess":prep,"GL":{"kind":"GL","coefficient":c}}
        buy,sell = make_signals(feature,{"selected":EXPECTED,"models":models})
        np.testing.assert_array_equal(buy,[True,False])
        np.testing.assert_array_equal(sell,[False,True])

    def test_locked_stage_requires_selection_and_hashes(self):
        """後13場を前40場の許可で開かず、凍結選択と指紋の一致を要求する。

        引数: self(ReplayTests)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest,configs,spec,freeze = [root/n for n in ("manifest.json","configs.json","spec.json","freeze.json")]
            for p in (manifest,configs,spec):
                p.write_text('{}',encoding="utf-8")
            hashes = {"manifest_sha256":sha(manifest),"configs_sha256":sha(configs),"spec_sha256":sha(spec)}
            receipt = {"allowed_stages":["train_validation"],**hashes}
            require_stage(receipt,"train_validation",manifest,configs,spec,None)
            with self.assertRaises(ValueError):
                require_stage(receipt,"locked_test",manifest,configs,spec,None)
            chosen = {"selected":["H01","H13","H24"],"test_opened":False,**hashes}
            freeze.write_text(json.dumps(chosen),encoding="utf-8")
            receipt.update(allowed_stages=["locked_test"],freeze_sha256=sha(freeze))
            require_stage(receipt,"locked_test",manifest,configs,spec,freeze)
            chosen["selected"] = ["H01","H02","H03","H04"]
            freeze.write_text(json.dumps(chosen),encoding="utf-8")
            receipt["freeze_sha256"] = sha(freeze)
            with self.assertRaises(ValueError):
                require_stage(receipt,"locked_test",manifest,configs,spec,freeze)


if __name__ == "__main__":
    unittest.main()
