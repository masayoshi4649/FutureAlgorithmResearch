"""最終案内の対象件数と候補値を、各巡の保存会計から照合する。"""

import hashlib
import json
from pathlib import Path
import re

from check_public_day_quantity129 import read, check, CHECKS, READS, ROOT, TASK, PUBLIC


def main() -> None:
    """
    機能: 九巡の分母と最新候補、反復一覧の主要主張を保存会計へ照合する。
    引数: なし。
    返り値: None。金融再生や公開生成は行わず、照合JSONを保存する。
    """
    final = read(TASK/"最終全場比較_確定.json")
    expected_rounds = [("round1", 126, 3), ("round2", 252, 6), ("round3", 168, 4),
                       ("day_round1", 176, 4), ("day_round2", 176, 4),
                       ("round4", 168, 4), ("round5", 168, 4), ("round6", 84, 2), ("round7", 84, 2)]
    new_rows, new_ids = [], set()
    final_by_key = {(r["method"], r["symbol"], r["session"]): r for r in final["rows"]}
    for folder, accounts, methods in expected_rounds:
        saved = read(TASK/folder/"全条件の会計.json")
        ids = {r["method"] for r in saved["rows"]}
        check(folder+"口座と方法数", [len(saved["rows"]), saved["financial_replays"], len(ids)],
              [accounts, accounts, methods])
        check(folder+"方法の重複なし", bool(ids & new_ids), False)
        new_ids.update(ids)
        new_rows.extend(saved["rows"])
        for row in saved["rows"]:
            published = final_by_key[row["method"], row["symbol"], row["session"]]
            check(folder+"/"+row["method"]+"/"+row["symbol"]+"/"+row["session"]+"元会計一致",
                  [published[k] for k in ("profit", "loss", "net", "gross", "fees", "entries")],
                  [row[k] for k in ("profit", "loss", "net", "gross", "fees", "entries")])
    old_rows = [r for r in final["rows"] if r["method"] not in new_ids]
    check("新旧の対象件数", [len(new_rows), len(new_ids), len(old_rows),
          len(final["rows"]), len({r["method"] for r in final["rows"]})], [1402, 33, 128, 1530, 36])
    check("旧三基準", sorted({r["method"] for r in old_rows}), ["D17", "N27", "N36"])
    check("重複口座なし", len(final_by_key), len(final["rows"]))
    check("日中と夜間の商品場数", [sum(r["kind"] == "Day" for r in new_rows),
          sum(r["kind"] == "Night" for r in new_rows)], [352, 1050])
    for method in sorted({r["method"] for r in final["rows"]}):
        rows = [r for r in final["rows"] if r["method"] == method]
        day = rows[0]["kind"] == "Day"
        for symbol in ("TOPIX", "NK225"):
            check(method+"/"+symbol+"全対象場", len([r for r in rows if r["symbol"] == symbol]), 22 if day else 21)
    for method, symbol, claim in (
        ("NV23", "NK225", [40600., 9, 5, 7, -13220., -21300.]),
        ("NV25", "NK225", [62040., 9, 4, 8, -8220., 140.]),
        ("NV23", "TOPIX", [163304., 7, 8, 6, -27918., -104188.]),
        ("NV25", "TOPIX", [156222., 7, 8, 6, -27918., -104188.])):
        rows = [r for r in final["rows"] if r["method"] == method and r["symbol"] == symbol]
        values = sorted(r["net"] for r in rows)
        check(method+"/"+symbol+"候補説明", [sum(values), sum(v > 0 for v in values),
              sum(v < 0 for v in values), sum(v == 0 for v in values), min(values), sum(values[:-3])], claim)
    diagnosis = read(TASK/"night/再試験入口の全親と固定線診断.json")
    losses = [r for r in diagnosis["rows"] if r["net"] < 0]
    check("夜間4診断の範囲", sorted({r["method"] for r in diagnosis["rows"]}), ["NV15", "NV17"])
    check("夜間4の78親と33敗", [len(diagnosis["rows"]), len(losses)], [78, 33])
    check("夜間4の全33敗は起動幅未満", all(r["mfe"] < r["width"]*r["activation"] for r in losses), True)
    changes = read(TASK/"day_diagnosis/日中第二巡の影別増減と残存損失.json")
    counterexamples = [p for r in changes["rows"] if r["method"] == "DV07" and r["symbol"] == "NK225"
                       for p in r["parents"] if p["old_net"] > 0 and p["new_net"] < 0]
    check("120秒後にも回復を失う実例", len(counterexamples) > 0, True)
    # ----------------------------------------
    # 親が生成した案内のリンクと、分母補足の公開本文・生成源の一致を確認。
    document_refs, links = [], []
    phrase = "診断対象NV15・NV17の78親中33敗は利益保護起動前。"
    for name in ("README.md", "反復の理由と到達点.md"):
        path = PUBLIC/name
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        document_refs.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(raw).hexdigest()))
        for link in re.findall(r"\]\(([^)]+)\)", text):
            target = (path.parent/link.split("#", 1)[0]).resolve()
            check(name+"出典存在:"+link, target.exists(), True)
            links.append(dict(document=name, target=link))
        if name == "反復の理由と到達点.md":
            check("公開一覧の33敗分母補足", phrase in text, True)
    source = TASK/"finish_docs129.py"
    check("生成源の33敗分母補足", phrase in source.read_text(encoding="utf-8"), True)
    proof = dict(passed=True, checks=len(CHECKS), details=CHECKS, inputs=READS,
                 documents=document_refs, links=links, financial_replays=0, API=0,
                 source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 correction="33敗はNV14～17全体ではなく、診断対象NV15/NV17の78親中と公開本文・生成源へ明記。")
    path = TASK/"audit/最終案内と九巡分母の独立照合.json"
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(passed=True, checks=len(CHECKS), links=len(links)), ensure_ascii=False))


if __name__ == "__main__":
    main()
