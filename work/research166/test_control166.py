"""金融再生をせず、登録受領と全場への移行ゲートを人工検査する。"""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import control166 as c


class 制御人工(unittest.TestCase):
    """小さい一時ディレクトリに登録受領と保存結果を作る。"""

    def setUp(self):
        """金融原資料を使わない仮の検査源を準備する。

        引数: self(制御人工)。返り値: None。
        """
        self.temp=tempfile.TemporaryDirectory(prefix="移植166人工_")
        self.root=Path(self.temp.name)
        self.here=self.root/"work/research166";self.here.mkdir(parents=True)
        self.patches=[patch.object(c,"ROOT",self.root),patch.object(c,"HERE",self.here),
            patch.object(c,"RECEIPT",self.here/"登録受領166.json"),patch.object(c,"BASELINE",self.here/"研究正本166.json")]
        for p in self.patches:p.start()
        self.source=self.here/"源.go";self.source.write_text("// 人工源",encoding="utf-8")
        r=c.record(self.source)
        c.save(c.BASELINE,dict(definitions=[r],cases_by_session=[dict(source=r)]))
        self.receipt=dict(id=c.IDENT,registered=True,returncode=0,sources=[r],implementation=r,
            plan=r,preflight=r,frozen=r,manifest=r,baseline=c.record(c.BASELINE))
        c.save(c.RECEIPT,self.receipt)

    def tearDown(self):
        """差替え定数を戻し、一時人工資料だけを片付ける。

        引数: self(制御人工)。返り値: None。
        """
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def test_成功受領と源指紋(self):
        """正常な受領だけを受理する。

        引数: self(制御人工)。返り値: None。
        """
        self.assertEqual(c.verify_receipt()["id"],c.IDENT)

    def test_受領失敗を拒否(self):
        """ファイル存在だけで実行を認めない。

        引数: self(制御人工)。返り値: None。
        """
        for field,value in [("registered",False),("returncode",1),("id","別試行")]:
            d=copy.deepcopy(self.receipt);d[field]=value
            with patch.object(c,"read",side_effect=lambda path:d if path==c.RECEIPT else {}):
                with self.assertRaises(AssertionError):c.verify_receipt()

    def test_源変更を拒否(self):
        """登録後の別実装を初回許可で実行しない。

        引数: self(制御人工)。返り値: None。
        """
        self.source.write_text("// 変更源",encoding="utf-8")
        with self.assertRaises(AssertionError):c.verify_receipt()

    def test_全場は先行検査なしで拒否(self):
        """全場を最初の同値確認より先に許可しない。

        引数: self(制御人工)。返り値: None。
        """
        with self.assertRaises(FileNotFoundError):c.allow("full")
        self.assertFalse((self.here/"実行許可166_full.json").exists())

    def smoke(self, mismatch=False):
        """3 手法の人工同値結果を保存する。

        引数: mismatch(bool)。返り値: None。
        """
        records=[]
        for kind,ids in [("Day",["NK225_D164_15"]),("Night",["NK225_P164_06","NK225_U165_03"])]:
            path=self.here/(kind+".json")
            cases=[dict(Session="2026-09-24_"+kind,Method=i,Cap=100,Pending=0,Held=0,
                Gross=0,ExpectedGross=0,Error="",Differences=["人工不一致"] if mismatch else []) for i in ids]
            c.save(path,dict(Error="<nil>",Results=cases));records.append(c.record(path))
        c.save(self.here/"初回実行_smoke_cap100.json",dict(completed=True,returncode=0,results=records))

    def test_先行3手法一致後だけ全場許可(self):
        """正本同値の 3 手法が揃っていることを確認する。

        引数: self(制御人工)。返り値: None。
        """
        self.smoke();c.allow("full")
        self.assertTrue(c.read(self.here/"実行許可166_full.json")["smoke"]["passed"])

    def test_先行不一致で全場拒否(self):
        """終了コードだけでなくケースの差も確認する。

        引数: self(制御人工)。返り値: None。
        """
        self.smoke(True)
        with self.assertRaises(AssertionError):c.allow("full")


if __name__=="__main__":unittest.main(verbosity=2)
