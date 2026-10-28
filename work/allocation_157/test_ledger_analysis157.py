"""保存台帳の再会計だけを人工データで検査する。相場の金融再生ではない。"""

from copy import deepcopy
from ledger_analysis157 import reconcile


def marker(at: float, index: int, realized: float, unrealized: float, quantity: int) -> dict:
    """人工検査用の極値断面を作る。

    引数: at/indexは時刻と原行、realized/unrealizedは円、quantityは買残数。
    返り値: dictはMark157互換。
    """
    return {"Time": at, "Index": index, "Bid": 100 if quantity else 103, "Ask": 101 if quantity else 104,
            "Realized": realized, "Unrealized": unrealized, "Equity": realized + unrealized,
            "Long": quantity, "Short": 0, "Lots": {"玉1": quantity} if quantity else {}}


def main() -> None:
    """部分返済を含む一親と無取引、欠陥配賦の拒否を検査する。

    引数: なし。返り値: None。不一致は停止する。
    """
    order = {"Parent": "core/0", "Owner": "core", "Campaign": 0, "Kind": "initial", "Reason": "人工",
             "Side": 1, "Quantity": 2, "DecisionIndex": 0, "DecisionTime": 0, "Targets": [], "Support": {}}
    new = {"Order": order, "FillIndex": 1, "FillTime": 1, "Price": 101, "Bid": 100, "Ask": 101,
           "Gross": 0, "HoldID": "玉1", "Pieces": []}
    close_order = dict(order, Side=-1, Quantity=1, DecisionIndex=1, DecisionTime=1,
                       Targets=[{"ID": "玉1", "Quantity": 1}])
    close = {"Order": close_order, "FillIndex": 2, "FillTime": 2, "Price": 103, "Bid": 103, "Ask": 104,
             "Gross": 20, "HoldID": "", "Pieces": [{"ID": "玉1", "Kind": "initial", "Quantity": 1,
                                                      "Entry": 101, "Exit": 103, "Gross": 20}]}
    later = deepcopy(close)
    later["Order"].update(DecisionIndex=2, DecisionTime=2)
    later.update(FillIndex=3, FillTime=3)
    zero, low, peak = marker(0, -1, 0, 0, 0), marker(1, 1, 0, -20, 2), marker(3, 3, 40, 0, 0)
    ledger = {"Events": [new, close, later], "Realized": 40,
              "Lots": {"玉1": {"Remaining": 0, "Quantity": 2, "Entry": 101, "Gross": 40}},
              "Parents": {"core/0": {"Realized": 40, "Unrealized": 0}}, "Last": peak,
              "Risk": {"HeldSeconds": 2, "GrossSeconds": 3, "NetAbsSeconds": 3,
                       "NetSignedSeconds": 3, "HedgedSeconds": 0, "MaxLong": 2, "MaxShort": 0,
                       "MaxGross": 2, "MinimumAt": low, "PeakAt": peak, "DDFrom": zero, "DDTo": low,
                       "MaxDD": 20}}
    actual = reconcile(ledger, 0, 4)
    assert actual["profit"] == actual["net"] == 40 and actual["entries"] == 1
    assert actual["quantities"]["gross_seconds"] == 3
    empty = {"Events": [], "Realized": 0, "Lots": {}, "Parents": {}, "Last": zero,
             "Risk": {key: 0 for key in ("HeldSeconds", "GrossSeconds", "NetAbsSeconds", "NetSignedSeconds",
                                          "HedgedSeconds", "MaxLong", "MaxShort", "MaxGross", "MaxDD")}}
    empty["Risk"].update(MinimumAt=zero, PeakAt=zero, DDFrom=zero, DDTo=zero)
    assert reconcile(empty, 0, 4)["entries"] == 0
    broken = deepcopy(ledger)
    broken["Events"][1]["Gross"] = 21
    try:
        reconcile(broken, 0, 4)
    except AssertionError:
        pass
    else:
        raise AssertionError("誤Grossを見逃した")
    print("157保存台帳の人工3検査PASS、金融再生0")


if __name__ == "__main__":
    main()
