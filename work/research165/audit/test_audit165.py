"""保存会計監査の集計・原行順・無取引・半量を小さい人工値で検査する。"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

import audit_results165 as audit


def event(number: int, at: int, side: int, quantity: int, price: float, target=None) -> dict:
    """人工の新規又は返済イベントを作る。

    引数: number/at/side/quantity(int)、price(float)、target(str又はNone)。返り値: dict。
    """
    order = dict(ID=str(number), Parent="親", Owner="core", Campaign=1, Kind="initial", SourceID="通知" + str(number),
        Side=side, Quantity=quantity, DecisionIndex=at - 1, DecisionTime=at - 1,
        Targets=[dict(ID=target, Quantity=quantity)] if target else None)
    pieces = [dict(ID=target, Quantity=quantity, Entry=100., Exit=price,
        Gross=quantity * (price - 100) * 10, Best=20., Worst=-10.)] if target else None
    return dict(Order=order, FillIndex=at, FillTime=at, Price=price, Bid=price if target else price - 10,
        Ask=price + 10 if target else price, Gross=pieces[0]["Gross"] if target else 0.,
        Pieces=pieces, HoldID="玉" + str(number) if target is None else "")


class Audit165Tests(unittest.TestCase):
    """金融結果を読まない監査器の人工回帰検査。"""

    def test_parent_path_contains_zero_and_same_row_execution(self):
        """親の開始ゼロと実BBOで最高・最低時価を確認する。

        引数: self(Audit165Tests)。返り値: None。
        """
        raw = np.array([[0, 100, 90, 100, 1, 1], [1, 100, 90, 100, 1, 1],
            [2, 120, 120, 130, 1, 1], [3, 110, 110, 120, 1, 1]], dtype=float)
        events = [event(1, 1, 1, 2, 100.), event(2, 3, -1, 2, 110., "玉1")]
        result = audit.path_extrema(raw, np.arange(4), events, 0.)
        self.assertEqual(result["minimum"], -200.)
        self.assertEqual(result["peak"], 400.)

    def test_half_keeps_clock_price_and_ownership(self):
        """半量で時計・価格を変えた偽対照を拒否する。

        引数: self(Audit165Tests)。返り値: None。
        """
        risk = {key: 20. for key in ("Peak", "Minimum", "MaxDD", "MinimumRealized", "MinimumUnrealized",
            "MaxLong", "MaxShort", "MaxGross", "MaxNetAbs", "GrossSeconds", "NetAbsSeconds", "NetSignedSeconds")}
        risk.update(HeldSeconds=2., HedgedSeconds=0.)
        full = dict(Events=[event(1, 1, 1, 2, 100.), event(2, 3, -1, 2, 110., "玉1")], Risk=risk, Realized=200.)
        half = deepcopy(full)
        for e in half["Events"]:
            e["Order"]["Quantity"] //= 2
            e["Gross"] /= 2
            for value in (e["Order"]["Targets"] or []) + (e["Pieces"] or []):
                value["Quantity"] //= 2
                if "Gross" in value:
                    value["Gross"] /= 2
        for key in half["Risk"]:
            if key not in ("HeldSeconds", "HedgedSeconds"):
                half["Risk"][key] /= 2
        half["Realized"] /= 2
        self.assertTrue(audit.half_control(full, half, True)["passed"])
        half["Events"][1]["FillTime"] += 1
        with self.assertRaises(AssertionError):
            audit.half_control(full, half, True)

    def test_reserved_close_uses_actual_id(self):
        """同じ所有玉を二重に返済予約する場合は拒否する。

        引数: self(Audit165Tests)。返り値: None。
        """
        valid = dict(Events=[event(1, 1, 1, 2, 100.), event(2, 3, -1, 2, 110., "玉1")])
        self.assertEqual(audit.owner_reservations(valid)["duplicate_close_reservations"], 0)
        invalid = deepcopy(valid)
        duplicate = event(3, 3, -1, 1, 110., "玉1")
        invalid["Events"].append(duplicate)
        with self.assertRaises(AssertionError):
            audit.owner_reservations(invalid)

    def test_zero_profit_is_not_no_trade_or_loss(self):
        """収支ゼロ・無取引・赤字の分母を区別する。

        引数: self(Audit165Tests)。返り値: None。
        """
        rows = [dict(net=value, profit=max(value, 0), loss=max(-value, 0), new_orders=new,
            closed_micro=new, minimum_equity=min(value, 0), maximum_dd=max(-value, 0), held_seconds=new,
            parent_positive_then_loss=0, lot_positive_then_loss=0)
            for value, new in [(0., 0), (0., 1), (-20., 1), (50., 1)]]
        result = audit.summary(rows)
        self.assertEqual((result["no_entries"], result["negative_sessions"]), (1, 1))
        self.assertEqual(result["worst_quarter_loss"], 20.)
        self.assertEqual(result["excluding_top3"], -20.)

    def test_direction_scope_is_explicit(self):
        """全場下落と米国後上昇を別の事後分類として保存する。

        引数: self(Audit165Tests)。返り値: None。
        """
        raw = np.array([[0, 100, 90, 100, 1, 1], [1, 50, 40, 50, 1, 1], [2, 80, 70, 80, 1, 1]], dtype=float)
        self.assertEqual(audit.direction(raw, np.arange(3), "全場")["direction"], "下落")
        self.assertEqual(audit.direction(raw, np.array([1, 2]), "米国後")["direction"], "上昇")
        self.assertFalse(audit.direction(raw, np.arange(3), "全場")["decision_input"])

    def test_complete_gate_prevents_result_open(self):
        """全完了のない状態では結果フォルダを一切開かない。

        引数: self(Audit165Tests)。返り値: None。
        """
        with TemporaryDirectory() as folder, patch.object(audit, "WORK", Path(folder)):
            with self.assertRaises(FileNotFoundError):
                audit.main()

    def test_only_half_snapshot_map_is_reconstructed(self):
        """診断mapの誤りだけを約定から別写しへ復元し、原台帳を変更しない。

        引数: self(Audit165Tests)。返り値: None。
        """
        initial = dict(Index=-1, Lots=None)
        snapshot = dict(Index=2, Time=2., Lots={"玉1": 5}, Long=10, Short=0,
            Bid=110., Ask=120., Realized=0., Unrealized=1000., Equity=1000.)
        risk = {key: deepcopy(initial) for key in ("MinimumAt", "PeakAt", "DDFrom", "DDTo", "MinimumRealizedAt", "MinimumUnrealizedAt")}
        risk.update(PeakAt=deepcopy(snapshot), DDFrom=deepcopy(snapshot))
        ledger = dict(Events=[event(1, 1, 1, 10, 100.), event(2, 3, -1, 10, 110., "玉1")],
            Lots={"玉1": dict(Side=1, Entry=100.)}, Risk=risk)
        original = deepcopy(ledger)
        fixed, differences = audit.snapshot_accounting_view(ledger, "NK225_U165_12")
        self.assertEqual(ledger, original)
        self.assertEqual(len(differences), 2)
        self.assertEqual(fixed["Risk"]["PeakAt"]["Lots"], {"玉1": 10})
        with self.assertRaises(AssertionError):
            audit.snapshot_accounting_view(ledger, "NK225_U165_11")


if __name__ == "__main__":
    unittest.main()
