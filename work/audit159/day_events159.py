"""既知の日中部分の全保存約定を比較し、旧26場との合算資格を確認する。"""
from __future__ import annotations

from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work/audit159"


def load(path: Path) -> dict:
    """保存JSONを読み取る。

    引数: path(Path)。返り値: dictは保存値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def ref(path: Path) -> dict:
    """出典の位置と内容指紋を返す。

    引数: path(Path)。返り値: dictは検算根拠。
    """
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def strip_phase(value: str) -> str:
    """日中の名前空間だけを外す。

    引数: value(str)。返り値: str。手法固有IDや親番号を推測で置き換えない。
    """
    return value.removeprefix("日中/")


def normalized_events(ledger: dict, limit: int) -> list:
    """所有IDを同じ初回原行の独立新規へ対応づけて全配賦を比較可能にする。

    引数: ledger(dict)、limit(int)は旧採用原行数。返り値: listは数量・約定・返済対象の全経路。
    """
    result, holds, counts = [], {}, defaultdict(int)
    for event in ledger["Events"] or []:
        if event["FillIndex"] >= limit:
            continue
        order = event["Order"]
        parent = strip_phase(order["Parent"])
        targets = []
        if order.get("Targets"):
            for target in order["Targets"]:
                targets.append({"entry": holds[target["ID"]], "quantity": target["Quantity"]})
            targets.sort(key=lambda v: v["entry"])
        else:
            key = (parent, order["DecisionIndex"], order["Side"])
            counts[key] += 1
            holds[event["HoldID"]] = (*key, counts[key])
        result.append({"parent": parent, "owner": strip_phase(order["Owner"]), "action": "close" if targets else "new", "side": order["Side"], "quantity": order["Quantity"],
                       "decision_index": order["DecisionIndex"], "decision_time": order["DecisionTime"], "decision_bid": order["DecisionBid"], "decision_ask": order["DecisionAsk"],
                       "fill_index": event["FillIndex"], "fill_time": event["FillTime"], "price": event["Price"], "bid": event["Bid"], "ask": event["Ask"], "gross": event["Gross"], "targets": targets})
    return result


def compare_rows(old: list, new: list) -> dict:
    """同順列の全要素を確認し、差があれば最初の具体値を残す。

    引数: old/new(list)。返り値: dictは比較結果。
    """
    different = []
    for index in range(max(len(old), len(new))):
        left, right = old[index] if index < len(old) else None, new[index] if index < len(new) else None
        if left != right and len(different) < 5:
            different.append({"index": index, "old": left, "new": right})
    return {"passed": not different, "old_events": len(old), "new_events": len(new), "first_differences": different}


def economic_path(events: list) -> list:
    """同じ原行・親・方向の売買現金と数量を集約する。

    引数: events(list)。返り値: listは経済経路。返済配賦の一致とは区別する。
    """
    groups = defaultdict(lambda: {"quantity": 0, "cash": 0.0})
    for event in events:
        key = (event["fill_index"], event["parent"], event["side"], event["action"])
        groups[key]["quantity"] += event["quantity"]
        groups[key]["cash"] -= event["side"] * event["quantity"] * event["price"] * 10
    return [{"key": key, **value} for key, value in sorted(groups.items())]


def main() -> None:
    """全再生正常終了後に既知部分の保存約定だけを照合する。

    引数: なし。返り値: None。新金融・現在API・原資料変更はない。
    """
    done = load(ROOT / "work/research159/金融実行159.json")
    assert done["exit_code"] == 0, "全金融再生完了前"
    old_path = ROOT / "work/allocation_157/round2/results_go/2026-10-27_Day_S01.json"
    new_path = ROOT / "work/night159/results_go/2026-10-27_Day.json"
    old, new = load(old_path), load(new_path)
    inputs = load(WORK / "日中既知部分の入力照合159.json")
    for v in inputs["markets"].values():
        assert v["new_rows"] >= v["old_rows"]
        assert all(d["old"] is None for d in v["first_differences"]), "既知入力の途中に差"
        assert all(c["equal"] for c in v["candles"]), "既知確定足に差"
    limit = inputs["markets"]["NK225"]["old_rows"]
    old_cases = {c["config"]["id"]: c for c in old["cases"]}
    new_cases = {c["config"]["id"]: c for c in new["cases"]}
    pairs = {}
    for old_id, new_id, name in (("C00", "N00", "S01"), ("J02", "N02", "J02")):
        left, right = normalized_events(old_cases[old_id]["actual"], limit), normalized_events(new_cases[new_id]["actual"], limit)
        pair = compare_rows(left, right)
        old_economic, new_economic = economic_path(left), economic_path(right)
        pair["same_quantity_and_cash_at_each_fill_index"] = old_economic == new_economic
        pair["economic_groups"] = len(old_economic)
        pair["economic_equality_scope"] = "同じ原行の数量・売買現金が一致すれば全正常板BBO時価は一致する。玉別配賦・途中の確定と含みの内訳の一致を意味しない。"
        pair.update(old_id=old_id, new_id=new_id, old_net=sum(e["gross"] for e in left), new_net=sum(e["gross"] for e in right), old_events=left, new_events=right)
        pairs[name] = pair
    report = {"passed": all(p["passed"] for p in pairs.values()), "scope": "旧10月27日15:20未満データに存在する原行の全約定・配賦。末尾追加原行は別範囲。",
              "common_input_rows": limit, "input_common_prefix_equal": True, "input_full_cutoff_equal": inputs["passed"], "pairs": pairs, "new_financial_replays": 0,
              "sources": [ref(old_path), ref(new_path), ref(WORK / "日中既知部分の入力照合159.json")], "created_at": dt.datetime.now().astimezone().isoformat()}
    out = WORK / "日中既知部分の約定照合159.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "pairs": {k:{"passed":v["passed"], "old_event_count":len(v["old_events"]), "new_event_count":len(v["new_events"]), "old_net":v["old_net"], "new_net":v["new_net"]} for k,v in pairs.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
