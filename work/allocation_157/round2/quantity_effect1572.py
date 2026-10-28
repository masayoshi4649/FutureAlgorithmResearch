"""固定10microとの金額差を、保存初回量と親損益だけで恒等分解する。"""

from collections import defaultdict
from pathlib import Path
import hashlib
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyze157 import read, save
from ledger_analysis157 import equal

HERE = Path(__file__).resolve().parent
REPORT_SHA = "24b17a9f41290400a2d4bf08d3f3db20054f5aa5347cb59367523f562bb93597"


def decompose(candidate: str, sessions: list[str]) -> dict:
    """親ごとの初回数量比と、旧出口の確定収支を使って差額を分解する。

    引数: candidate(str)はJ比較ID、sessions(list[str])は完了場。返り値: dict。
    一律縮小は整数発注を再現しない算術対照で、追加売買の再生は行わない。
    """
    rows, totals = [], defaultdict(lambda: {"base_net": 0., "candidate_net": 0., "base_qty": 0, "candidate_qty": 0})
    for session in sessions:
        base = read(HERE/"audit/cases"/session/"K01.json")["actual"]["parents"]
        current = read(HERE/"audit/cases"/session/f"{candidate}.json")["actual"]["parents"]
        by_id = {p["id"]: p for p in current}
        assert set(by_id) == {p["id"] for p in base}
        for p in base:
            c = by_id[p["id"]]
            assert p["completed"] and c["completed"]
            q0, q1 = p["initial_quantity"], c["initial_quantity"]
            ratio = q1/q0
            row = {"session": session, "parent": p["id"], "owner": p["owner"],
                   "base_quantity": q0, "candidate_quantity": q1, "initial_ratio": ratio,
                   "base_net": p["realized"], "candidate_net": c["realized"],
                   "scaled_base": p["realized"]*ratio,
                   "quantity_path_residual": c["realized"]-p["realized"]*ratio}
            rows.append(row)
            total = totals[p["owner"]]
            total["base_net"] += p["realized"]
            total["candidate_net"] += c["realized"]
            total["base_qty"] += q0
            total["candidate_qty"] += q1
    base_net = sum(r["base_net"] for r in rows)
    candidate_net = sum(r["candidate_net"] for r in rows)
    global_ratio = sum(r["candidate_quantity"] for r in rows)/sum(r["base_quantity"] for r in rows)
    uniform = (global_ratio-1)*base_net
    owner_effect, within_owner, residual = 0., 0., 0.
    for owner, total in totals.items():
        ratio = total["candidate_qty"]/total["base_qty"]
        part = [r for r in rows if r["owner"] == owner]
        total["mean_initial_ratio"] = ratio
        total["owner_reallocation"] = (ratio-global_ratio)*total["base_net"]
        total["within_owner_reallocation"] = sum((r["initial_ratio"]-ratio)*r["base_net"] for r in part)
        total["quantity_path_residual"] = sum(r["quantity_path_residual"] for r in part)
        owner_effect += total["owner_reallocation"]
        within_owner += total["within_owner_reallocation"]
        residual += total["quantity_path_residual"]
    equal(uniform+owner_effect+within_owner+residual, candidate_net-base_net, "数量差の恒等分解")
    return {"candidate": candidate, "control": "K01", "parents": len(rows),
            "base_net": base_net, "candidate_net": candidate_net, "net_delta": candidate_net-base_net,
            "uniform_initial_ratio": global_ratio, "uniform_size_effect": uniform,
            "owner_reallocation_effect": owner_effect, "within_owner_reallocation_effect": within_owner,
            "quantity_path_residual": residual, "owners": dict(totals), "rows": rows}


def main() -> None:
    """固定済み第二巡を読み、J02/J15の差額を算術だけで整理する。

    引数: なし。返り値: None。結果を使った再発注・閾値再選択は行わない。
    """
    path = HERE/"report1572.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == REPORT_SHA
    report = read(path)
    sessions = [r["session"] for r in next(m for m in report["methods"] if m["id"] == "K01")["rows"]]
    results = [decompose(candidate, sessions) for candidate in ("J02", "J15")]
    save(HERE/"増枚と配分の算術分解1572.json", {
        "definition": "K01の同親PLへ実初回数量比を掛けた算術対照。整数端数・後続数量・上限等による差は残差。新戦略の再生ではない。",
        "report_sha256": REPORT_SHA, "results": results,
    })
    lines = ["# 固定10microとの差は、増枚と配分を分ける", "",
             "K01は初回10micro固定。J02/J15との差額を同じ155親に対応させ、元の親損益を数量比だけで拡大する算術対照を置いた。", "",
             "| 比較 | 収支差 | 全親を平均初回枚数まで一律増量 | 担当間の配分差 | 同担当内の親配分差 | 後続量等の残差 |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for r in results:
        lines.append("| "+r["candidate"]+"−K01 | "+" | ".join(f'{r[k]:+,.0f}円' for k in ("net_delta", "uniform_size_effect", "owner_reallocation_effect", "within_owner_reallocation_effect", "quantity_path_residual"))+" |")
    lines += ["", "各行の4要因の和は収支差へ一致する。これは保存結果の恒等分解で、一律増量の新しい約定模型ではない。整数端数を含む後続量・相殺・上限の経路差を残差へまとめ、支持の予測効果とは呼ばない。", "",
              "同担当内の配分が今回の既知結果へ有利でも、支持と元S01同親損益の順位相関は別検査で弱い。金額の増加だけを『強い支持の予測力が検証された』とは解釈しない。", "",
              "根拠：[155親の数量と損益](増枚と配分の算術分解1572.json)、[支持識別の診断](支持と元S01損益の関係1572.md)。"]
    (HERE/"増枚と配分の算術分解1572.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    for result in results:
        print({k: v for k, v in result.items() if k not in ("rows", "owners")})


if __name__ == "__main__":
    main()
