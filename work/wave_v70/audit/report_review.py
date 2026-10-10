"""公開 HTML の固定 JSON と説明を監査済み台帳・期間集計へ照合する。"""

from __future__ import annotations

import json
from pathlib import Path
import re

import numpy as np

from audit_all import read, digest, ROOT, WORK, HERE
from combine import aggregate
from independent_account import near, save


OUT = ROOT / "アルゴリズム調査/00067_両建て保険と途中管理"
MAIN = OUT / "両建て保険と途中管理の説明と損益.html"
ALL = OUT / "全条件の途中管理比較.html"


def payload(path: Path) -> tuple[str, dict]:
    """機能: 公開 HTML の唯一の固定データを読み、外部実行せず JSON 化する。

    引数: path(Path)。返り値: 原本文字列と JSON 辞書(tuple[str,dict])。
    """
    text = path.read_text(encoding="utf-8")
    parts = re.findall(r'<script id="report-data" type="application/json">(.*?)</script>', text, re.S)
    assert len(parts) == 1
    return text, json.loads(parts[0])


def match(method: dict, packet: dict) -> None:
    """機能: 公開された個別・期間・固定条件を監査済み結果へ完全照合する。

    引数: method/packet(dict)。返り値: なし(None)。
    """
    for field in ("config", "rows", "periods", "ledger_SHA256"):
        assert method[field] == packet[field], (method["id"], field)
    assert len(method["rows"]) == 56
    for symbol in ("TOPIX", "NK225"):
        rows = [r for r in method["rows"] if r["symbol"] == symbol]
        assert len(rows) == 28
        near(sum(r["net"] for r in rows), method["periods"]["全28"][symbol]["net"], "公開全場合計")


def main() -> None:
    """機能: 三代表・222一覧・同幅対照・診断黒字重複・未採用説明を検算する。

    引数: なし。返り値: なし(None)。
    """
    main_text, D = payload(MAIN)
    all_text, A = payload(ALL)
    fixed = read(WORK / "事前固定.json")
    selected = read(WORK / "前半選定.json")
    original = read(HERE / "全条件の独立監査.json")
    diagnostic = read(HERE / "追加診断対照の独立監査.json")
    ready = read(ROOT / "work/wave_v69/prepared/inputs.pkl")
    assert original["合格"] and diagnostic["合格"]
    assert D["sessions"] == A["sessions"] == fixed["全セッション"] and len(D["sessions"]) == 28
    assert [m["id"] for m in D["methods"]] == [r["id"] for r in selected["代表"]] == A["selectedIds"]
    assert len(D["methods"]) == 3 and len(A["methods"]) == 222
    assert len({m["id"] for m in A["methods"]}) == 222
    config_ids = {c["id"] for c in fixed["条件"]}
    diagnostic_ids = {c["id"] for c in read(WORK / "追加対照の事前固定.json")["条件"]}
    assert {m["id"] for m in A["methods"]} == config_ids | diagnostic_ids
    assert sum(m["config"].get("control", False) for m in A["methods"]) == 30
    for method in A["methods"]:
        folder = WORK / "controls/results" if method["config"].get("control") else WORK / "results"
        match(method, read(folder / (method["id"] + ".json")))
    selection_by_id = {r["id"]: r for r in selected["代表"]}
    for method in D["methods"]:
        match(method, read(WORK / "results" / (method["id"] + ".json")))
        assert method["eligible"] == selection_by_id[method["id"]]["eligible"] is False
        baseline = selection_by_id[method["id"]]["baseline"]
        assert method["baseline"] == read(WORK / "results" / (baseline + ".json"))
        ledger = read(WORK / "ledgers" / (method["id"] + ".pkl"))
        for key, stored in ledger.items():
            orders = method["orders"]["|".join(key)]
            expected = [list(order) + [float(ready[key]["time_s"][int(order[0])])] for order in stored["orders"]]
            assert orders == expected
        for symbol in ("TOPIX", "NK225"):
            weeks = method["weeks"][symbol]
            assert len(weeks) == 3
            for field in ("profit", "loss", "net", "fees", "campaign_profit", "campaign_loss", "campaigns", "winning_lots", "losing_lots"):
                near(sum(week[field] for week in weeks), method["periods"]["全28"][symbol][field], "週合計/" + field)
    for method in D["methods"][:2]:
        assert method["control"]["config"]["id"] == "T2L0_D32"
        match(dict(method["control"], id="T2L0_D32"), read(WORK / "controls/results/T2L0_D32.json"))
        assert method["baseline"]["config"]["stop"] == 16
        assert method["config"]["stop"] == method["control"]["config"]["stop"] == 32
        assert method["config"]["hold_seconds"] == method["control"]["config"]["hold_seconds"]
        assert method["config"]["basket_stop"] == method["control"]["config"]["basket_stop"]

    # ----------------------------------------
    # 追加診断の二つの黒字設定は売買経路が同一で、独立成功を二つと数えない。
    blacks = [m for m in A["methods"] if m["id"] in diagnostic_ids and all(m["periods"]["全28"][s]["net"] > 0 for s in ("TOPIX", "NK225"))]
    assert sorted(m["id"] for m in blacks) == ["T3L1_D32", "T3L1_D32A16W8"]
    ledgers = [read(WORK / "controls/ledgers" / (m["id"] + ".pkl")) for m in blacks]
    for key in ready:
        columns = [0, 1, 2, 3, 4, 5, 7, 8]
        np.testing.assert_array_equal(ledgers[0][key]["orders"][:, columns], ledgers[1][key]["orders"][:, columns])
        np.testing.assert_array_equal(ledgers[0][key]["trades"], ledgers[1][key]["trades"])
        assert ledgers[0][key]["curve_hash"] == ledgers[1][key]["curve_hash"]
    top, nk = blacks[0]["periods"]["全28"]["TOPIX"], blacks[0]["periods"]["全28"]["NK225"]
    assert top["net"] == 234068 and nk["net"] == 1840 and nk["campaigns"] == 14
    assert blacks[0]["periods"]["前16"]["NK225"]["net"] == -78640
    assert round(top["campaign_payoff"], 2) == .85 and round(nk["campaign_payoff"], 2) == .76
    assert not any(all(m["periods"]["全28"][s]["net"] > 0 for s in ("TOPIX", "NK225")) for m in A["methods"] if m["id"] in config_ids)
    notes = "\n".join(D["notes"] + D["sourceNotes"])
    required = ["途中で実玉が0枚になっても", "途中の0枚を成功で組終了とはしない", "旧E01/R01", "再現した結果ではない",
        "選定に使用していない", "同じ売買", "選定外", "採用条件を満たさない", "32呼値", "D32", "部分", "全料金"]
    for text in required:
        assert text in notes, ("重要説明", text)
    assert "以下の3手法は比較代表" in main_text and "採用条件は未達" in main_text
    assert "途中の0枚だけでは勝ちに数えません" in main_text and "管理終了までを一組" in main_text
    assert "診断・選定外" in all_text
    reduction = []
    ratchet = D["methods"][2]
    for symbol in ("TOPIX", "NK225"):
        a, b = ratchet["periods"]["全28"][symbol], ratchet["baseline"]["periods"]["全28"][symbol]
        reduction.append(100 * (1 - a["campaign_loss"] / b["campaign_loss"]))
    assert 35.5 < min(reduction) < 36.5 and 37.5 < max(reduction) < 38.5
    published = read(WORK / "公開会計.json")
    assert published["主HTML_SHA256"] == digest(MAIN) and published["全条件HTML_SHA256"] == digest(ALL)
    save(HERE / "公開説明と会計の最終監査.json", dict(合格=True, 主要条件=192, 追加診断=30,
        三代表=[m["id"] for m in D["methods"]], 未採用明記=True, 途中0枚は組終了ではない明記=True,
        旧E01全体再現ではない明記=True, 同幅D32対応=True, 全222会計と全28場一致=True,
        三代表全注文と約定時計一致=True, 三週合計一致=True, 黒字診断二設定は全56口座同一売買経路=True,
        黒字診断の差="返済理由ラベルが異なる行はあるが、判断・約定行、売買、枚数、価格、全行評価と決済は同じ",
        追加診断は選定外明記=True, 損失合計削減率=reduction,
        主HTML_SHA256=digest(MAIN), 全条件HTML_SHA256=digest(ALL)))
    print("公開3代表/222一覧・会計・同幅対照・同一黒字診断・未採用説明: 合格", flush=True)


if __name__ == "__main__":
    main()
