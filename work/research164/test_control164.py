"""実市場を読まず段階管理と固定順位の境界を検査する。"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("制御164", Path(__file__).with_name("control164.py"))
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class 管理検査(unittest.TestCase):
    """金融0の人工構造だけを渡す検査集合。"""

    def test_固定順は合計額だけで候補を選ばない(self):
        """黒字・参加・赤字場数を収支額より先に評価する。

        引数: self(管理検査)。返り値: None。
        """
        def row(name,net,idle,loss):
            """人工の順位比較行を作る。

            引数: name(str)、net/int、idle/int、loss/int。返り値: dict。
            """
            return dict(id=name,net=net,no_entries=idle,negative_sessions=loss,mean_negative_absolute=10,worst_equity_absolute=10)
        rows=[row("大勝ち",1000,0,3),row("安定",100,0,1),row("無取引増",2000,1,0),row("赤字",-10,0,0)]
        self.assertEqual([x["id"] for x in control.rank(rows)],["安定","大勝ち","無取引増","赤字"])

    def test_指紋は内容と順序(self):
        """辞書キー順を除外し、値の変更を必ず区別する。

        引数: self(管理検査)。返り値: None。
        """
        self.assertEqual(control.canonical({"a":1,"b":2}),control.canonical({"b":2,"a":1}))
        self.assertNotEqual(control.canonical({"a":1}),control.canonical({"a":2}))

    def test_証跡上書き拒否(self):
        """登録・凍結の新規保存関数が再利用を拒否する。

        引数: self(管理検査)。返り値: None。
        """
        with tempfile.TemporaryDirectory(prefix="人工164_") as folder:
            path=Path(folder)/"記録.json"
            control.save(path,{"金融":0})
            self.assertEqual(control.read(path),{"金融":0})
            with self.assertRaises(FileExistsError):
                control.save(path,{"金融":1})

    def test_IDと時間区分の一致(self):
        """20手法を別定義にし、対象区分のすり替えを拒否する。

        引数: self(管理検査)。返り値: None。
        """
        with tempfile.TemporaryDirectory(prefix="人工定義164_") as folder:
            path=Path(folder)/"条件.json"
            rows=[dict(id=f"NK225_{letter}164_{i:02d}",scope=scope,rule_hash="a"*64) for scope,(letter,count) in control.SCOPES.items() for i in range(count)]
            original=control.CONFIGS
            try:
                control.CONFIGS=path
                path.write_text(json.dumps(rows),encoding="utf-8")
                self.assertEqual(len(control.configs()),20)
                rows[-1]["scope"]="PreUS"
                path.write_text(json.dumps(rows),encoding="utf-8")
                with self.assertRaises(AssertionError): control.configs()
            finally:
                control.CONFIGS=original


if __name__ == "__main__":
    unittest.main()
