"""夜間診断器を人工約定だけで検査する。実結果は読まない。"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import diagnose_night164 as d


def fixture():
    """正利益後に次板損失となる人工一玉を作る。

    引数: なし。返り値: (dict,list[dict])。
    """
    quotes=[dict(index=i,physical_line=i+1,time=float(i),jst=d.timestamp(i),bid=bid,ask=bid+10,last=bid+5,normal=True) for i,bid in enumerate((990,990,1020,1000,980))]
    new=dict(ID="n1",Parent="p1",Owner="PreUS",Kind="初回",Reason="初回",Side=1,Quantity=10,DecisionIndex=0,DecisionTime=0.,DecisionBid=990.,DecisionAsk=1000.,Targets=[])
    close=dict(ID="c1",Parent="p1",Owner="PreUS",Kind="初回",Reason="利益床",Side=-1,Quantity=10,DecisionIndex=3,DecisionTime=3.,DecisionBid=1000.,DecisionAsk=1010.,Targets=[dict(ID="h1",Quantity=10)])
    piece=dict(ID="h1",Kind="初回",Quantity=10,Entry=1000.,Exit=980.,Gross=-2000.,Best=20.,Worst=-20.)
    entries=[dict(Order=new,FillIndex=1,FillTime=1.,Price=1000.,Bid=990.,Ask=1000.,Gross=0.,Pieces=[],HoldID="h1"),dict(Order=close,FillIndex=4,FillTime=4.,Price=980.,Bid=980.,Ask=990.,Gross=-2000.,Pieces=[piece],HoldID="")]
    lot=dict(ID="h1",Parent="p1",Owner="PreUS",Kind="初回",SourceID="",Campaign=1,Side=1,Quantity=10,Remaining=0,Entry=1000.,At=1.,Gross=-2000.,Best=20.,Worst=-20.,BestAt=2.,WorstAt=4.,EntryIndex=1,Activated=False,Floor=0.)
    trace=[dict(Kind="新規",OrderID="n1",Index=0,Time=0.,Features=dict(Known5=True,Known15=True,Known300=True,Path15=True)),dict(Kind="保護起動",OrderID="h1",Index=2,Time=2.)]
    case=dict(config=dict(id="NK225_P164_02",scope="PreUS"),actual=dict(Active=[],Pending=[],Lots={"h1":lot},Events=entries,Realized=-2000.),trigger_trace=trace,guards={"h1":dict(R=40,Active=True,Floor=0.)})
    return case,quotes


class DiagnoseTest(unittest.TestCase):
    """保存値と原行の説明用再会計を人工検査する。"""

    def test_positive_floor_gap_and_residual(self):
        """利益瞬間、床判断、次板赤字と少量残玉を分離する。

        引数: self(DiagnoseTest)。返り値: None。
        """
        case,quotes=fixture()
        state=d.prepare_case(case,"人工Night","人工")
        d.trace_raw([state],iter(quotes))
        lot=state["lots"]["h1"]
        self.assertEqual(lot["first_positive"]["index"],2)
        self.assertEqual(lot["reaction_seconds"],1)
        value=d.summarize([lot])
        self.assertEqual(value["positive_then_loss_lots"],1)
        self.assertEqual(value["floor_gap_negative_pieces"],1)
        self.assertEqual(value["small_residual_positive_then_negative_pieces"],1)
        self.assertEqual(value["mid_move_yen"]-value["bbo_cost_yen"],-2000)
        self.assertEqual(lot["exits"][0]["decision_raw"]["physical_line"],4)

    def test_sell_mirror(self):
        """売りの返済Askと同じ経済損益を確認する。

        引数: self(DiagnoseTest)。返り値: None。
        """
        case,quotes=fixture()
        for q in quotes:q["bid"],q["ask"],q["last"]=2000-q["ask"],2000-q["bid"],2000-q["last"]
        lot=case["actual"]["Lots"]["h1"];lot["Side"]=-1
        for ev in case["actual"]["Events"]:
            ev["Bid"],ev["Ask"]=2000-ev["Ask"],2000-ev["Bid"];ev["Price"]=2000-ev["Price"]
            order=ev["Order"];order["Side"]*=-1;order["DecisionBid"],order["DecisionAsk"]=2000-order["DecisionAsk"],2000-order["DecisionBid"]
            for piece in ev["Pieces"]:piece["Exit"]=2000-piece["Exit"]
        state=d.prepare_case(case,"人工Night","人工");d.trace_raw([state],iter(quotes));value=d.summarize(list(state["lots"].values()))
        self.assertEqual(value["net"],-2000)
        self.assertEqual(value["positive_then_loss_lots"],1)

    def test_completion_rejected_before_result(self):
        """完了falseで結果ファイルへ進まない。

        引数: self(DiagnoseTest)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"未完了.json";path.write_text('{"completed":false}',encoding="utf-8")
            with self.assertRaises(AssertionError):d.completed_inputs(path)

    def test_quality_missing_is_not_low(self):
        """旧基準の特徴未計測と端点未知・内部異常を区別する。

        引数: self(DiagnoseTest)。返り値: None。
        """
        self.assertEqual(d.quality(None),"基準_新層特徴未記録")
        self.assertEqual(d.quality({}),"必要端点未知")
        self.assertEqual(d.quality(dict(Known5=True,Known15=True,Path15=True,Known300=True,Invalid300=1)),"既知_内部異常又は空白あり")

    def test_raw_indices_and_physical_lines(self):
        """同時計後続と異常BBOを採番に残し、時計欠測を除く。

        引数: self(DiagnoseTest)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"人工.jsonl"
            books=[]
            for at,bid,ask in ((100,990,1000),(100,980,990),(101,1000,990),(99,990,1000),(102,990,1000)):
                books.append(dict(CurrentPriceTime=d.timestamp(at),CurrentPrice=995,Buy1=dict(Price=bid),Sell1=dict(Price=ask)))
            books.insert(1,dict(CurrentPriceTime=None,CurrentPrice=995))
            raw=("\n".join(json.dumps(x) for x in books)+"\n").encode();path.write_bytes(raw)
            scene=dict(start=100,end=200,cutoff=200,books={"NK225":str(path)},fingerprints=[dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())])
            quotes=list(d.raw_quotes(scene))
            self.assertEqual([q["physical_line"] for q in quotes],[1,3,4,6])
            self.assertEqual([q["index"] for q in quotes],[0,1,2,3])
            self.assertFalse(quotes[2]["normal"])


if __name__=="__main__":unittest.main()
