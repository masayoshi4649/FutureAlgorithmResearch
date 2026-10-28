"""第二巡夜間診断を人工Source通知と保存約定だけで検査する。"""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

import diagnose_night164r2 as d


def fixture(add_after=False):
    """部分利確前の40円と、残玉資格後の5円を分離した人工例を作る。

    引数: add_after(bool)。返り値: (dict,list[dict],dict)。
    """
    quotes=[dict(index=i,physical_line=i+1,time=float(i),jst=d.base.timestamp(i),bid=b,ask=b+10,last=b+5,normal=True) for i,b in enumerate((990,990,1040,1005,990,1000,980))]
    parent="前半/core/1"
    def signal(sid,action,i,q,targets=None):
        return dict(id=sid,owner="core",campaign=1,action=action,side=1 if action=="new" else -1,quantity=q,time=float(i),source_index=i,targets=targets)
    signals=[signal("n","new",0,2),signal("pc","close",2,1,[dict(id="n-玉",quantity=1)])]
    if add_after:signals.append(signal("add","new",2,1))
    signals.append(signal("fc","close",5,2 if add_after else 1,[dict(id="n-玉",quantity=1)]+([dict(id="add-玉",quantity=1)] if add_after else [])))
    maps=d.source_maps([dict(Phase="前半",Signals=signals)])
    def order(oid,sid,i,q,kind,reason,targets):
        return dict(ID=oid,SourceID="前半/"+sid,Parent=parent,Owner="前半/core",Campaign=1,Kind=kind,Reason=reason,Side=-1 if targets else 1,Quantity=q,DecisionIndex=i,DecisionTime=float(i),DecisionBid=quotes[i]["bid"],DecisionAsk=quotes[i]["ask"],Targets=targets)
    def event(o,i,price,pieces,hold=""):
        return dict(Order=o,FillIndex=i,FillTime=float(i),Price=price,Bid=quotes[i]["bid"],Ask=quotes[i]["ask"],Gross=sum(p["Gross"] for p in pieces),Pieces=pieces,HoldID=hold)
    initial=order("entry","n",0,20,"initial","initial",[])
    part=order("partial","pc",2,10,"source_close","source_partial/1",[dict(ID="h1",Quantity=10)])
    pieces=[dict(ID="h1",Kind="initial",Quantity=10,Entry=1000.,Exit=980.,Gross=-2000.,Best=40.,Worst=-20.)]
    events=[event(initial,1,1000.,[],"h1"),event(part,3,1005.,[dict(ID="h1",Kind="initial",Quantity=10,Entry=1000.,Exit=1005.,Gross=500.,Best=40.,Worst=-10.)])]
    lots={"h1":dict(ID="h1",Parent=parent,Owner="前半/core",Campaign=1,Side=1,Kind="initial",SourceID="前半/n",Quantity=20,Remaining=0,Entry=1000.,At=1.,EntryIndex=1,Gross=-1500.,Best=40.,Worst=-20.,BestAt=2.,WorstAt=6.)}
    states={"h1":dict(ResidualEligible=True,Activated=False)}
    if add_after:
        events.append(event(order("addentry","add",2,10,"source_add","source_add",[]),3,1015.,[],"h2"))
        pieces.append(dict(ID="h2",Kind="source_add",Quantity=10,Entry=1015.,Exit=980.,Gross=-3500.,Best=0.,Worst=-35.))
        lots["h2"]=dict(ID="h2",Parent=parent,Owner="前半/core",Campaign=1,Side=1,Kind="source_add",SourceID="前半/add",Quantity=10,Remaining=0,Entry=1015.,At=3.,EntryIndex=3,Gross=-3500.,Best=0.,Worst=-35.,BestAt=3.,WorstAt=6.)
        states["h2"]=dict(ResidualEligible=False,Activated=False)
    events.append(event(order("full","fc",5,sum(x["Quantity"] for x in pieces),"source_close","source_end/1",[dict(ID=x["ID"],Quantity=x["Quantity"]) for x in pieces]),6,980.,pieces))
    case=dict(config=dict(id="NK225_P164_05",scope="PreUS",residual_floor=True),actual=dict(Active=[],Pending=[],Lots=lots,Events=events,Realized=sum(x["Gross"] for x in lots.values())),lot_states=states,trigger_trace=[],counts={})
    return case,quotes,maps


class DiagnosisTests(unittest.TestCase):
    """将来のピーク流用と同原行の資格継承を禁止する。"""

    def test_residual_after_partial_only(self):
        """資格前ピーク40を残玉ピーク5へ混入させない。

        引数: self(DiagnosisTests)。返り値: None。
        """
        case,quotes,maps=fixture();state=d.prepare_case(case,"人工Night","人工",maps)
        d.trace_raw([state],iter(quotes));lot=state["lots"]["h1"]
        self.assertEqual(lot["Best"],40)
        self.assertEqual(lot["residual_best"],5)
        self.assertEqual(lot["residual_realized"],-2000)
        self.assertEqual(d.summary([lot])["residual_positive_then_loss_lots"],1)

    def test_same_row_future_add_not_qualified(self):
        """部分返済の後順で新規約定する玉へ資格を移さない。

        引数: self(DiagnosisTests)。返り値: None。
        """
        case,quotes,maps=fixture(True);state=d.prepare_case(case,"人工Night","人工",maps)
        d.trace_raw([state],iter(quotes))
        self.assertIsNone(state["lots"]["h2"]["residual_qualification"])
        self.assertEqual(d.summary(list(state["lots"].values()))["net"],-5000)

    def test_negative_actual_does_not_qualify(self):
        """元の判断が正益でも、次板Actual赤字なら資格なしにする。

        引数: self(DiagnosisTests)。返り値: None。
        """
        case,_,maps=fixture();ev=case["actual"]["Events"][1]
        ev.update(Price=990.,Bid=990.,Ask=1000.,Gross=-1000.)
        ev["Pieces"][0].update(Exit=990.,Gross=-1000.)
        case["actual"]["Lots"]["h1"]["Gross"]=-3000.;case["actual"]["Realized"]=-3000.
        case["lot_states"]["h1"]["ResidualEligible"]=False
        state=d.prepare_case(case,"人工Night","人工",maps)
        self.assertIsNone(state["lots"]["h1"]["residual_qualification"])

    def test_next_normal_and_missing_rows(self):
        """次正常原行より遅い保存約定を拒否する。

        引数: self(DiagnosisTests)。返り値: None。
        """
        case,quotes,maps=fixture();state=d.prepare_case(case,"人工Night","人工",maps)
        quotes.insert(1,dict(quotes[0],index=.5,physical_line=999))
        with self.assertRaises(AssertionError):d.trace_raw([state],iter(quotes))

    def test_completion_closed(self):
        """未完了なら結果の有無を見る前に止まる。

        引数: self(DiagnosisTests)。返り値: None。
        """
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"未完了.json";p.write_text('{"completed":false}',encoding="utf-8")
            with self.assertRaises(AssertionError):d.completed_inputs(p)

    def test_source_id_pair_delayed(self):
        """待機後の価格・時刻が変わっても同じSourceIDへ対応する。

        引数: self(DiagnosisTests)。返り値: None。
        """
        case,quotes,maps=fixture();state=d.prepare_case(case,"人工Night","人工",maps);d.trace_raw([state],iter(quotes))
        old=state["lots"]["h1"];new=copy.deepcopy(old);new.update(method="NK225_P164_07",At=2.,EntryIndex=2,Entry=1010.,delayed=True,Gross=-1000.)
        v=d.compare([old],[new]);self.assertEqual(v["delta"],500);self.assertTrue(v["rows"][0]["delayed"])


if __name__=="__main__":unittest.main()
