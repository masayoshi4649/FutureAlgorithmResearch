"""原資料を使わず、訂正確認の段階・正本一致・内容指紋を人工確認する。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import control166r2 as c


class 訂正人工(unittest.TestCase):
    """1 ケースだけの人工ファイルで実行判定を確認する。"""

    def setUp(self):
        """仮の出力先と正常な日中ケースを用意する。

        引数: self(訂正人工)。返り値: None。
        """
        self.temp=tempfile.TemporaryDirectory(prefix="訂正166人工_");self.root=Path(self.temp.name)
        self.patches=[patch.object(c,"ROOT",self.root),patch.object(c,"HERE",self.root),patch.object(c.original,"ROOT",self.root)]
        for p in self.patches:p.start()
        self.case=dict(Session="2026-10-26_Day",Method="NK225_D164_15",Cap=100,
            Error="",Differences=[],Held=0,Pending=0,Gross=10.,ExpectedGross=10.)

    def tearDown(self):
        """一時人工資料と差替え定数だけを戻す。

        引数: self(訂正人工)。返り値: None。
        """
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def fixture(self,returncode=0):
        """現在の人工ケースを完了証跡へ結び付ける。

        引数: returncode(int)。返り値: Path。
        """
        result=self.root/"人工結果.json"
        c.save(result,dict(Error="<nil>",Results=[self.case]))
        c.save(c.stage_proof("day_smoke"),dict(completed=returncode==0,returncode=returncode,
            sources_unchanged=True,stage="day_smoke",cap=100,results=[c.record(result)]))
        return result

    def test_一件一致のみ受理(self):
        """指定の日中と手法が正本同値なら受理する。

        引数: self(訂正人工)。返り値: None。
        """
        self.fixture();self.assertTrue(c.verify_stage("day_smoke")["completed"])

    def test_同損益でも判断差を拒否(self):
        """今回の不具合と同じ、収支だけ一致する差を見逃さない。

        引数: self(訂正人工)。返り値: None。
        """
        self.case["Differences"]=["判断が一原行違う"];self.fixture()
        with self.assertRaises(AssertionError):c.verify_stage("day_smoke")

    def test_別手法と未完を拒否(self):
        """夜手法を日中検査に置き換えない。

        引数: self(訂正人工)。返り値: None。
        """
        self.case["Method"]="NK225_P164_06";self.fixture()
        with self.assertRaises(AssertionError):c.verify_stage("day_smoke")

    def test_保存後の改変を拒否(self):
        """成功した結果の内容指紋を後で変えない。

        引数: self(訂正人工)。返り値: None。
        """
        result=self.fixture();result.write_text("{}",encoding="utf-8")
        with self.assertRaises(AssertionError):c.verify_stage("day_smoke")

    def test_非ゼロ終了を拒否(self):
        """実行器の失敗を残玉表示だけで成功扱いしない。

        引数: self(訂正人工)。返り値: None。
        """
        self.fixture(1)
        with self.assertRaises(AssertionError):c.verify_stage("day_smoke")


if __name__=="__main__":unittest.main(verbosity=2)
