"""公開する持続確認・数量追加の数値、分母、相対出典を保存結果へ再照合する。"""

import hashlib
import json
from pathlib import Path
import re

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
PUBLIC = ROOT/"アルゴリズム調査/00129_チャートと板からの失敗機構再検証"
LEDGER = ROOT/"アルゴリズム調査/共通/知見台帳"
READS = []
CHECKS = []


def read(path: Path):
    """
    機能: 保存JSONを読み、照合に用いた版を記録する。
    引数: path(Path)は資料の位置。
    返り値: objectは保存内容。
    """
    raw = path.read_bytes()
    READS.append(dict(path=path.relative_to(ROOT).as_posix(),
                      sha256=hashlib.sha256(raw).hexdigest()))
    return json.loads(raw)


def check(name: str, actual, expected) -> None:
    """
    機能: 公開数値の計算結果を期待記載と照合する。
    引数: name(str)、actual/expected(object)は照合内容。
    返り値: None。
    """
    assert actual == expected, (name, actual, expected)
    CHECKS.append(dict(name=name, actual=actual, expected=expected))


def main() -> None:
    """
    機能: 日中と数量の公開説明を保存結果へ照合し、証拠を保存する。
    引数: なし。
    返り値: None。金融核、注文生成、APIは実行しない。
    """
    day = read(TASK/"day_round2/全場比較.json")
    changes = read(TASK/"day_diagnosis/日中第二巡の影別増減と残存損失.json")
    night = read(TASK/"round5/全条件の会計.json")
    sized = read(TASK/"night_quantity_diagnosis/数量変更の独立会計と追加単価診断.json")
    path_class = read(TASK/"night_quantity_diagnosis/夜間の順行後追加に残る単価幅.json")
    day_audit = read(TASK/"audit/day_round2_全注文と全行会計の独立照合.json")
    check("日中保存独立会計", [day_audit["passed"], day_audit["accounts"]], [True, 176])
    expected = {
        ("D17", "TOPIX"): [485133, 14, 6, 2, -91672, 208637],
        ("DV07", "TOPIX"): [522633, 14, 6, 2, -79172, 246137],
        ("D17", "NK225"): [248300, 15, 6, 1, -30520, 82700],
        ("DV05", "NK225"): [260800, 15, 6, 1, -25100, 95200],
        ("DV07", "NK225"): [242800, 15, 6, 1, -29100, 77200],
    }
    for (method, symbol), claim in expected.items():
        rows = [r for r in day["rows"] if r["method"] == method and r["symbol"] == symbol]
        values = sorted(r["net"] for r in rows)
        check(method+symbol+"対象22場", len(rows), 22)
        actual = [sum(values), sum(v > 0 for v in values), sum(v < 0 for v in values),
                  sum(v == 0 for v in values), min(values), sum(values[:-3])]
        check(method+symbol+"公開表", actual, claim)
        check(method+symbol+"ゼロは無取引", all(r["entries"] == 0 for r in rows if r["net"] == 0), True)
    for regime, count, median, after_three in (("上昇", 12, 83., -149436.), ("下落", 10, 55457., 165242.)):
        values = sorted(r["net"] for r in day["rows"] if r["method"] == "DV07"
                        and r["symbol"] == "TOPIX" and r["regime"] == regime)
        check("TOPIX120秒_"+regime, [len(values), float(np.median(values)), sum(values[:-3])],
              [count, median, after_three])
    # ----------------------------------------
    # 全親差分から、負けの縮小と元勝ちの除去、部分返済後の変化を分離する。
    day_parents = {}
    for method, symbol in (("DV07", "TOPIX"), ("DV05", "NK225")):
        parents = [(r["session"], p) for r in changes["rows"] if r["method"] == method
                   and r["symbol"] == symbol for p in r["parents"]]
        changed = [(scene, p) for scene, p in parents if p["difference"] != 0]
        day_parents[method, symbol] = parents
        if symbol == "TOPIX":
            check("TOPIXの44親中3親だけ変更", [len(parents), len(changed)], [44, 3])
            check("TOPIX変更は負け3親で37500円", [sum(p["old_net"] < 0 for _, p in changed),
                  sum(p["difference"] for _, p in changed)], [3, 37500.])
            check("TOPIX旧勝ちの返済注文も同一", all(p["old"]["exits"] == p["initial"][0]["exits"]
                  for _, p in parents if p["old_net"] > 0), True)
            check("TOPIX救済日の一致", sorted(scene for scene, _ in changed),
                  ["2026-10-02_Day", "2026-10-06_Day", "2026-10-16_Day"])
        else:
            losing = [p for _, p in changed if p["old_net"] < 0]
            removed = [p for _, p in changed if p["old_net"] > 0 and p["new_net"] < 0]
            partial = [p for _, p in changed if p["old_net"] > 0 and p["new_net"] > 0]
            check("日経の50親中9親だけ変更", [len(parents), len(changed)], [50, 9])
            check("日経変更の分解", [len(losing), sum(p["difference"] for p in losing),
                len(removed), sum(p["difference"] for p in removed), len(partial),
                sum(p["difference"] for p in partial)], [5, 21000., 1, -12500., 3, 4000.])
            check("改善3親は元部分返済あり", all(len(p["old"]["exits"]) > 1 for p in partial), True)
    top = next(p for scene, p in day_parents["DV07", "TOPIX"]
               if scene == "2026-10-16_Day" and p["shadow_parent"] == 0)
    check("TOPIX10月16日の具体約定", [top["old"]["entry_time"], top["old"]["entry_price"],
        top["old"]["exit_time"], top["old_net"], top["initial"][0]["exit_time"],
        top["initial"][0]["exits"][-1]["price"], top["new_net"]],
        ["09:52:20", 4077., "10:37:07", -42918., "10:32:00", 4071., -30418.])
    nk = next(p for scene, p in day_parents["DV05", "NK225"]
              if scene == "2026-10-08_Day" and p["shadow_parent"] == 4)
    check("日経10月8日の具体約定", [nk["old"]["entry_time"], nk["old"]["entry_price"],
        nk["old_net"], nk["initial"][0]["exit_time"], nk["initial"][0]["exits"][-1]["price"], nk["new_net"]],
        ["13:32:49", 69600., 8280., "13:39:45", 69560., -4220.])
    check("日経10月8日旧益は部分利確込み", len(nk["old"]["exits"]), 3)
    # ----------------------------------------
    # 数量の全場・追加親分母・黒字喪失場・予算破りを保存会計へ照合。
    claims = {
        ("NV18", "TOPIX"): [113866., 3], ("NV19", "TOPIX"): [161465., 5],
        ("NV18", "NK225"): [3784., 12], ("NV19", "NK225"): [1892., 11],
        ("NV20", "TOPIX"): [72368., 5], ("NV21", "TOPIX"): [109133., 7],
        ("NV20", "NK225"): [232., 11], ("NV21", "NK225"): [-11504., 13],
    }
    for (method, symbol), claim in claims.items():
        rows = [r for r in night["rows"] if r["method"] == method and r["symbol"] == symbol]
        check(method+symbol+"対象21場", len(rows), 21)
        check(method+symbol+"数量公開表", [sum(r["net"] for r in rows), sum(r["net"] < 0 for r in rows)], claim)
    for method, symbol, negative, count, after_three in (
        ("NV19", "TOPIX", 12, 19, -33154.), ("NV19", "NK225", 15, 20, -18696.),
        ("NV21", "TOPIX", 13, 20, -30988.), ("NV21", "NK225", 20, 24, -28940.)):
        own = [p for p in sized["parents"] if p["method"] == method and p["symbol"] == symbol and p["additions"]]
        values = sorted(p["addition_net"] for p in own)
        check(method+symbol+"追加親分母と負寄与", [len(own), sum(v < 0 for v in values)], [count, negative])
        check(method+symbol+"上位3親を除く追加寄与", sum(values[:-3]), after_three)
    original_parents = {(r["method"], r["symbol"], r["session"], r["parent"]) for r in path_class["rows"]}
    check("事前単価分類の219親", len(original_parents), 219)
    for method, symbol, negative, count in (
        ("N36", "TOPIX", 13, 26), ("N36", "NK225", 20, 30),
        ("NV02", "TOPIX", 17, 27), ("NV02", "NK225", 25, 33)):
        touched = [r for r in path_class["rows"] if r["method"] == method and r["symbol"] == symbol
                   and r["threshold_R"] == 1. and r["touched"]]
        check(method+symbol+"1R接触後の残幅", [len(touched), sum(r["additional_unit_negative"] for r in touched)],
              [count, negative])
        check(method+symbol+"旧勝ちだけが1R接触", all(r["old_winner"] for r in touched), True)
    for method, gross, extra_fee in (("NV19", 0., 1892.), ("NV21", -9800., 1936.)):
        own = [p for p in sized["parents"] if p["method"] == method and p["symbol"] == "NK225"]
        gross_sum = sum(a["leg_gross"] for p in own for a in p["additions"])
        net_sum = sum(p["addition_net"] for p in own)
        check(method+"日経追加粗損益と費用", [gross_sum, gross_sum-net_sum], [gross, extra_fee])
    check("数量監査の口座親検査数", [sized["account_count"], len(sized["parents"]), sized["checks"]], [168, 438, 7357])
    check("追加219親と対照219親", [sum(p["method"] in ("NV19", "NV21") for p in sized["parents"]),
          sum(p["method"] in ("NV18", "NV20") for p in sized["parents"])], [219, 219])
    check("数量全行の最大誤差0", max(r["max_curve_error"] for r in sized["audits"]), 0.)
    check("黒字から赤字の6口座", len(sized["positive_to_negative"]), 6)
    check("6口座の追加親は全て黒字", all(p["net"] > 0 for r in sized["positive_to_negative"]
          for p in r["parents"] if p["additions"]), True)
    budget_broken = [p for p in sized["parents"] if p["additions"] and p["net"] < 0]
    check("追加後赤字はTOPIX10月1日2方式", sorted((p["method"], p["symbol"], p["session"]) for p in budget_broken),
          [("NV19", "TOPIX", "2026-10-01_Night"), ("NV21", "TOPIX", "2026-10-01_Night")])
    for parent in budget_broken:
        check(parent["method"]+"実予算破り", parent["budget_to_actual"],
              dict(last_budget=168., added_fill_change=500., all_exit_change=-2000., actual_net=-1332.))
    # ----------------------------------------
    # 公開2文書と知見2項目の出典が、存在する相対位置へ接続するか確認。
    documents = [(PUBLIC/"日中の持続確認で改善した部分と残る負け.md", None),
                 (PUBLIC/"数量追加で黒字場が減った理由.md", None),
                 (LEDGER/"継続.md", "00129_持続確認は損失の深さを改善したが頻度は同じ"),
                 (LEDGER/"売買の工夫.md", "00129_利益床内追加でも場の安定性は悪化し得る")]
    document_refs, links = [], []
    wording_notes = []
    for path, anchor in documents:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        if anchor:
            text = text.split(f'<a id="{anchor}"></a>', 1)[1].split("<a id=", 1)[0]
        document_refs.append(dict(path=path.relative_to(ROOT).as_posix(), anchor=anchor,
                                  sha256=hashlib.sha256(raw).hexdigest()))
        for link in re.findall(r"\]\(([^)]+)\)", text):
            target = (path.parent/link.split("#", 1)[0]).resolve()
            check("出典存在:"+path.name+":"+link, target.exists(), True)
            links.append(dict(document=path.name, target=link))
        if "元の初期玉は全438親で減量対照と完全一致" in text:
            wording_notes.append("売買の工夫：438親は4条件全体であり、比較は追加219親と対応対照219親。親数の表現を親担当へ修正依頼済み。")
    proof = dict(passed=True, checks=len(CHECKS), details=CHECKS, inputs=READS,
                 documents=document_refs, links=links, wording_notes=wording_notes,
                 financial_replays=0, API=0, scope="公開値の再集計。新しい有効性の証拠ではない。",
                 source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target = HERE/"日中持続確認と数量追加の公開前照合.json"
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(passed=True, checks=len(CHECKS), links=len(links), wording_notes=wording_notes), ensure_ascii=False))


if __name__ == "__main__":
    main()
