"""即追尾比較のカバー損益を中値変化と新規・返済の半気配差へ分ける。"""
from collections import Counter
import json
from pathlib import Path

from diagnose162 import WORK, HERE, completion_gate, read, fingerprint


def main() -> None:
    """全53場の保存BBOだけでH01/H13の全カバー返済を恒等分解する。

    引数: なし。返り値: None。手法を再実行せず、入口・退出の変更も行わない。
    """
    _, records, sources = completion_gate(WORK)
    totals = {ident: Counter() for ident in ("H01", "H13")}
    rows = []
    for record in records:
        saved = read(Path(record["path"]))
        for case in saved["cases"]:
            if case["id"] not in totals:
                continue
            refs = {r["index"]: r for r in case["reference"]}
            new = {e["order"]["id"]: e for e in case["events"] if e["order"]["action"] == "new"}
            account = Counter()
            for event in case["events"]:
                order = event["order"]
                if order["action"] != "close" or order["role"] != "cover":
                    continue
                opened = new[order["target"]]
                a = refs[opened["fill_index"]]
                b = refs[event["quote_index"] if event.get("proxy") else event["fill_index"]]
                point_value = order["quantity"] * 100
                mid = opened["order"]["side"] * (b["bid"] + b["ask"] - a["bid"] - a["ask"]) * .5 * point_value
                spread = ((a["ask"] - a["bid"]) + (b["ask"] - b["bid"])) * .5 * point_value
                assert mid - spread == event["gross"]
                account["mid_net"] += mid
                account["spread_cost"] += spread
                account["actual_net"] += event["gross"]
                account["close_count"] += 1
            assert account["actual_net"] == case["summary"]["roles"]["cover"]["net"]
            rows.append({"session": saved["session"], "split": saved["split"], "id": case["id"], **account})
            totals[case["id"]].update(account)
    result = {"sessions": 53, "totals": {k: dict(v) for k, v in totals.items()}, "rows": rows,
              "identity": "実収支 = 約定行中値の方向損益 - 入口と出口の半気配差",
              "scope": "保存約定価格の分解。気配差をなくした時の戦略経路の再検証ではない。",
              "sources": sources, "implementation": fingerprint(Path(__file__))}
    destination = HERE / "即追尾気配差分解162.json"
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"file": fingerprint(destination), "totals": result["totals"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
