"""Goの無取引Events:nullを空配列と同じ意味で集計する互換実行器。"""
from __future__ import annotations

import argparse
import copy

import control165 as original

PATH = original.HERE / "control_empty165.py"
FIX = original.HERE / "空取引の集計互換165.json"
original_row = original.row_from_case
original_save = original.save


def row_from_case(scene: dict, case: dict) -> dict:
    """無取引のnullイベントだけを読取時に空列と解釈する。

    引数: scene(dict)、case(dict)。返り値: dict。原会計ファイル・金額・数量は変更しない。
    """
    if case["actual"]["Events"] is not None:
        return original_row(scene, case)
    ledger = case["actual"]
    assert not ledger["Lots"] and not ledger["Active"] and not ledger["Pending"]
    assert ledger["Realized"] == 0
    safe = dict(case, actual=dict(ledger, Events=[]))
    return original_row(scene, safe)


def save(path, value) -> None:
    """凍結記録へ集計互換の実装と人工検査を追加する。

    引数: path(Path)、value(dict)。返り値: None。順位・選択式は変更しない。
    """
    if path == original.FREEZE:
        value["aggregation_adapter"] = original.record(PATH)
        value["aggregation_check"] = original.record(FIX)
        value["content_sha256"] = original.canonical({k:v for k,v in value.items() if k != "content_sha256"})
    original_save(path, value)


def artificial() -> None:
    """空列とnullの集計同値、非空の不変、壊れたnullの拒否を確かめる。

    引数: なし。返り値: None。金融再生は0。
    """
    sample = original.read(original.BASELINE)["cases"][0]
    assert row_from_case(sample["scene"],sample["case"]) == original_row(sample["scene"],sample["case"])
    empty = copy.deepcopy(sample["case"])
    ledger = empty["actual"]
    ledger.update(Events=[], Lots={}, Active={}, Pending=None, Realized=0)
    ledger["Risk"] = dict(Minimum=0,MaxDD=0,MaxLong=0,MaxShort=0,HeldSeconds=0,GrossSeconds=0)
    expected = original_row(sample["scene"],empty)
    ledger["Events"] = None
    got = row_from_case(sample["scene"],empty)
    assert got == expected and got["new_orders"] == 0 and got["net"] == 0
    ledger["Realized"] = 1
    try:
        row_from_case(sample["scene"],empty)
    except AssertionError:
        pass
    else:
        raise AssertionError("非ゼロの空会計を拒否できない")
    original_save(FIX, dict(passed=True,new_financial_replays=0,financial_results_changed=False,
        tests=3, reason="前20結果の無取引Ledger.Events:nullを旧集計が反復できずfreeze停止。nullを空列と同義に扱うだけ。",
        original=original.record(original.HERE/"control165.py"),adapter=original.record(PATH),
        numerical_rules_changed=False,ranking_changed=False,confirmation_started=False))


def main() -> None:
    """固定管理器へ空取引互換だけを適用して段階を進める。

    引数: CLI command(str)。返り値: None。
    """
    p=argparse.ArgumentParser()
    p.add_argument("command",choices=("test","freeze","allow_confirmation","complete"))
    args=p.parse_args()
    if args.command == "test":
        artificial()
        print("空取引互換の人工3項目PASS。金融再生0。")
        return
    proof=original.read(FIX)
    assert proof["passed"] and not proof["financial_results_changed"]
    original.verify(proof["original"])
    original.verify(proof["adapter"])
    original.row_from_case=row_from_case
    original.save=save
    if args.command=="freeze": original.freeze()
    elif args.command=="allow_confirmation": original.allow("confirmation")
    else: original.complete()


if __name__ == "__main__":
    main()
