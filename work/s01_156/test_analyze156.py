"""金融データを使わない00156の独立会計検査。"""
import copy
import unittest

import numpy as np

from analyze156 import analyze_case, normal_indices, parent_extrema, summarize


def fixture(partial=False):
    """部分利確後に損失となる人工一親を作る。

    引数: partial(bool)。
    返り値: case/scene/raw。
    """
    raw=np.asarray([[100+i,b+5,b,b+10] for i,b in enumerate([1000,1000,1040,1030,990,980])],dtype=float)
    lotid="初回-玉"
    def signal(ident,index,action,q):
        side=1 if action=="new" else -1
        out={"id":ident,"owner":"core","campaign":1,"action":action,"side":side,"quantity":q,"source_index":index,"time":raw[index,0],"reason_code":0,"evidence":{"observation":{"Index":index,"Time":raw[index,0],"Last":raw[index,1],"Bid":raw[index,2],"Ask":raw[index,3]}}}
        if action=="close":out["targets"]=[{"id":lotid,"quantity":q}]
        return out
    ss=[signal("初回",0,"new",2),signal("一部",2,"close",1),signal("残玉",4,"close",1)]
    ev=[]
    for i,(s,fi,price,gross) in enumerate(zip(ss,[1,3,5],[1010,1030,980],[0,2000,-3000])):
        fill={"HoldID":lotid if i==0 else s["id"]+"-玉","Quantity":s["quantity"],"Price":price,"Time":raw[fi,0],"Fee":0,"Closed":s.get("targets")}
        item={"signal":s,"fill":fill,"decision_index":s["source_index"],"fill_index":fi,"gross":gross}
        if i:item["pieces"]=[{"Gross":gross,"BestGain":30,"WorstGain":-10 if i==1 else -30,"PositiveThenLoss":i==2,"Protected":False,"Floor":0,"ProtectionAt":0}]
        ev.append(item)
    if partial:raw=raw[:5];ev=ev[:2]
    lot={"Quantity":2,"Remaining":1 if partial else 0,"Price":1010,"Gross":2000 if partial else -1000,"BestPoints":30,"WorstPoints":-20 if partial else -30,"BestTime":102,"WorstTime":104 if partial else 105}
    parent={"Realized":2000 if partial else -1000,"Unrealized":-2000 if partial else 0,"Equity":0 if partial else -1000,"Remaining":1 if partial else 0,"Peak":6000,"Minimum":-2000,"PeakAt":102,"MinimumAt":101,"PositiveThenLoss":not partial}
    case={"config":{"id":"S01"},"signals":ss,"events":ev,"entries":{lotid:lot},"parents":{"core/1":parent},"Gross":2000 if partial else -1000,"Unrealized":-2000 if partial else 0,"last_quote":{"Time":raw[-1,0],"Last":raw[-1,1],"Bid":raw[-1,2],"Ask":raw[-1,3]},"final_pending":[ss[-1]] if partial else []}
    scene={"session":"人工_Day","partial":partial}
    return case,scene,raw


class Accounting156(unittest.TestCase):
    """人工だけを使う独立会計試験。"""

    def test_closed_parent_and_piece_are_separate(self):
        """返済配賦利益2000/損失3000と完結親損失1000を混同しない。

        引数: self。
        返り値: なし。
        """
        case,scene,raw=fixture()
        row,details=analyze_case(case,scene,raw,normal_indices(raw))
        self.assertEqual((row["profit"],row["loss"],row["net"]),(0,1000,-1000))
        self.assertEqual((row["allocation_profit"],row["allocation_loss"]),(2000,3000))
        self.assertEqual(row["positive_then_loss_count"],1)
        self.assertEqual(row["positive_then_loss_piece_count"],1)
        self.assertEqual(details["parents"][0]["peak"],6000)

    def test_partial_has_no_invented_close(self):
        """途中親の実現と未返済含みを完結親利益へ混ぜない。

        引数: self。
        返り値: なし。
        """
        case,scene,raw=fixture(True)
        row,_=analyze_case(case,scene,raw,normal_indices(raw))
        self.assertEqual((row["profit"],row["loss"],row["open_parent_realized"]),(0,0,2000))
        self.assertEqual((row["net"],row["unrealized"],row["equity"]),(2000,-2000,0))
        self.assertEqual(row["remaining_qty"],1)

    def test_changed_execution_is_rejected(self):
        """約定時刻・金額・所有IDのすり替えを拒否する。

        引数: self。
        返り値: なし。
        """
        for field in ("same_row","price","owner"):
            case,scene,raw=fixture()
            if field=="same_row":case["events"][0]["fill_index"]=0
            if field=="price":case["events"][0]["fill"]["Price"]+=10
            if field=="owner":case["events"][1]["fill"]["Closed"]=[{"id":"他人玉","quantity":1}]
            with self.assertRaises((AssertionError,KeyError)):
                analyze_case(case,scene,raw,normal_indices(raw))

    def test_top_three_removes_only_positive(self):
        """上位3黒字除外で赤字を取り除かない。

        引数: self。
        返り値: なし。
        """
        case,scene,raw=fixture()
        row,_=analyze_case(case,scene,raw,normal_indices(raw))
        rows=[dict(row,net=v) for v in (1000,500,-200,-300)]
        summary=summarize(rows)
        self.assertEqual(summary["ex3"],-500)
        self.assertEqual(summary["avgloss"],250)

    def test_short_mirror_has_same_account(self):
        """売買鏡像の全量/部分返済/親時価が一致する。

        引数: self(Accounting156)。
        返り値: なし。
        """
        case,scene,raw=fixture()
        original,_=analyze_case(case,scene,raw,normal_indices(raw))
        mirror=raw.copy()
        mirror[:,1]=2000-raw[:,1]
        mirror[:,2]=2000-raw[:,3]
        mirror[:,3]=2000-raw[:,2]
        for signal in case["signals"]:
            signal["side"]=-signal["side"]
            idx=signal["source_index"]
            for key,col in (("Last",1),("Bid",2),("Ask",3)):
                signal["evidence"]["observation"][key]=mirror[idx,col]
        for event in case["events"]:
            event["fill"]["Price"]=2000-event["fill"]["Price"]
        case["entries"]["初回-玉"]["Price"]=990
        for key,col in (("Last",1),("Bid",2),("Ask",3)):
            case["last_quote"][key]=mirror[-1,col]
        reflected,_=analyze_case(case,scene,mirror,normal_indices(mirror))
        for key in ("profit","loss","net","max_parent_loss","positive_then_loss_count","allocation_profit","allocation_loss"):
            self.assertEqual(original[key],reflected[key])


if __name__=="__main__":
    unittest.main()
