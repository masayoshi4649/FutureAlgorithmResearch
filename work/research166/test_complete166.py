"""完了ゲートの会計条件を人工例だけで検査する。"""
import copy
import unittest
import complete166 as c


class 完了人工(unittest.TestCase):
    """売買入力や実台帳へ接続しない小会計。"""

    def case(self):
        """買い新規と反対方向の返済という人工例を返す。

        引数: self(完了人工)。返り値: dict。
        """
        return dict(Cap=10,Method="NK225_D164_15",Session="人工_Day",Held=0,Pending=0,Error="",Differences=[],
            Gross=1000.,ExpectedGross=0.,Events=[
                dict(DecisionIndex=0,FillIndex=1,Time=100.,Price=1000.,Gross=0.,Action="new",Side=1,Quantity=1),
                dict(DecisionIndex=1,FillIndex=2,Time=100.,Price=1010.,Gross=1000.,Action="close",Side=-1,Quantity=1)])

    def test_整数と同秒後行の会計(self):
        """同秒でも原行順なら許し、売り返済で買い所有を減らす。

        引数: self(完了人工)。返り値: None。
        """
        r=c.case_check(self.case(),10)
        self.assertEqual(r["maximum_long"],1);self.assertEqual(r["net"],1000)

    def test_上限と非整数拒否(self):
        """最終 flat の表示だけを信じず、途中数量を照合する。

        引数: self(完了人工)。返り値: None。
        """
        for bad in [11,0,1.5,True]:
            x=self.case();x["Events"][0]["Quantity"]=bad
            with self.assertRaises(AssertionError):c.case_check(x,10)

    def test_同原行約定と残玉を拒否(self):
        """原因より先の約定と、未完の台帳を完了扱いしない。

        引数: self(完了人工)。返り値: None。
        """
        x=self.case();x["Events"][0]["FillIndex"]=0
        with self.assertRaises(AssertionError):c.case_check(x,10)
        x=self.case();x["Events"].pop();x["Gross"]=0
        with self.assertRaises(AssertionError):c.case_check(x,10)

    def test_約定収支不一致と正本不一致を拒否(self):
        """表の合計だけ一致しても約定明細の差を拒否する。

        引数: self(完了人工)。返り値: None。
        """
        x=self.case();x["Gross"]=500
        with self.assertRaises(AssertionError):c.case_check(x,10)
        x=self.case();x["Cap"]=100
        with self.assertRaises(AssertionError):c.case_check(x,100)

    def test_成功証跡の矛盾と欠落を拒否(self):
        """成功フラグだけが真の終了失敗も拒否する。

        引数: self(完了人工)。返り値: None。
        """
        for bad in [{},{"passed":False},{"passed":True,"returncode":1},{"returncode":True}]:
            with self.assertRaises(AssertionError):c.successful(bad)
        c.successful({"passed":True,"returncode":0})


if __name__=="__main__":unittest.main(verbosity=2)
