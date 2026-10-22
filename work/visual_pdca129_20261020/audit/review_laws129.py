"""共通知見の五項目を元会計・分類分母・相対リンクと独立照合する。"""

import hashlib
import json
from pathlib import Path
import re
import time

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
KNOWLEDGE = ROOT/"アルゴリズム調査/共通/知見台帳"


def read(path):
    """
    機能: 保存JSONを読む。
    引数: path(Path)は位置。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: 内容指紋を求める。
    引数: path(Path)は位置。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """
    機能: 五項目の重要数値を元資料から再集計し、本文リンクと指紋を保存する。
    引数: なし。
    返り値: None。文書・数値源を変更せず証拠だけ新規保存する。
    """
    sources = [
        WORK/"round1/全条件の会計.json", WORK/"round2/全条件の会計.json", WORK/"round3/全条件の会計.json",
        WORK/"audit/価格時計と気配及び呼値尺度の独立診断.json",
        WORK/"audit/価格源変更と一時間欠測の保存親独立診断.json",
        WORK/"audit/第三巡欠測修正の場差保存分解.json",
        WORK/"day_diagnosis/両市場0.25逆行の持続分類.json",
        WORK/"day_diagnosis/日中第一巡の影別増減と残存損失.json",
        WORK/"day_round1/全条件の会計.json",
    ]
    checked = []
    rows = read(sources[0])["rows"]
    expected = {
        ("NV01", "TOPIX"): (21, 17, 3, 1, 257018),
        ("NV02", "TOPIX"): (21, 15, 5, 1, 180764),
        ("NV01", "NK225"): (21, 8, 12, 1, -540),
        ("NV02", "NK225"): (21, 9, 11, 1, 580),
    }
    for key, value in expected.items():
        group = [x for x in rows if (x["method"], x["symbol"]) == key]
        actual = (len(group), sum(x["net"] > 0 for x in group), sum(x["net"] < 0 for x in group),
                  sum(x["entries"] == 0 for x in group), sum(x["net"] for x in group))
        assert actual == value, (key, actual)
        checked.append(dict(項目="第一巡の場分母と勝敗", 条件=key, 値=actual))
    old = read(sources[3])["summary"]
    for method, count in (("N27", 34), ("N36", 27)):
        row = next(x for x in old if x["method"] == method and x["symbol"] == "NK225")
        assert row["赤字"] == row["同時刻Lastでも赤字の実赤字親"] == count
        checked.append(dict(項目="同注文Lastでも負け", 条件=method, 親数=count))
    missing = read(sources[4])
    assert sum(x["unknown"]["親数"] for x in missing["context_groups"]) == 16
    assert sum(x["internal_missing"]["親数"] for x in missing["context_groups"]) == 16
    assert missing["oct1_nk_context"] == dict(sole_removed_net=21780., other_four_trades_identical=True,
                                           old_net=-24100., new_net=-45880.)
    checked.append(dict(項目="内部欠測16親と唯一の黒字除外", 合格=True))
    r2, r3 = read(sources[1])["rows"], read(sources[2])["rows"]
    for symbol, before, after in (("TOPIX", 187854, 187018), ("NK225", 10560, 7460)):
        assert sum(x["net"] for x in r2 if x["method"] == "NV07" and x["symbol"] == symbol) == before
        assert sum(x["net"] for x in r3 if x["method"] == "NV12" and x["symbol"] == symbol) == after
        checked.append(dict(項目="欠測資格修正収支", 条件=symbol, 旧=before, 新=after))
    delta = read(sources[5])
    nk = [x for x in delta["changes"] if x["symbol"] == "NK225"]
    assert sum(x["delta"] for x in nk if x["delta"] > 0) == 21780
    assert sum(x["delta"] for x in nk if x["delta"] < 0) == -24880
    assert len([x for x in nk if x["delta"] < 0]) == 4
    checked.append(dict(項目="修正で増えた勝ちと四場の損失", 合格=True))
    duration = read(sources[6])
    assert len(duration["rows"]) == 52
    for symbol, win, count, ever120 in (("TOPIX", True, 3, 0), ("TOPIX", False, 21, 3),
                                        ("NK225", True, 9, 1), ("NK225", False, 19, 1)):
        group = [x for x in duration["rows"] if x["symbol"] == symbol and x["old_winner"] == win]
        assert len(group) == count and sum(x["ever120"] for x in group) == ever120
        if symbol == "NK225" and win:
            assert max(x["first_episode_seconds"] for x in group) == 31.
        checked.append(dict(項目="持続分類の分母と120秒", 条件=(symbol, win), 親数=count, 成立=ever120))
    example = missing["early_trail_example"]["tracks"]
    assert example["old"]["mfe_before_new_exit"] == 3.5 and not example["old"]["protection_activated"]
    assert example["new"]["mfe_before_new_exit"] == 5 and example["new"]["protection_activated"]
    changes = missing["same_entry_exit_changes"]
    assert len(changes) == 3
    assert sum(x["delta"] for x in changes if x["old"]["symbol"] == "TOPIX") == 5000
    assert sum(x["delta"] for x in changes if x["old"]["symbol"] == "NK225") == 0
    selected = [x for x in missing["cases"] if x["symbol"] == "TOPIX" and x["session"] == "2026-10-16_Night"]
    pick = {(x["method"], x["parent"]): x for x in selected}
    assert pick["NV01", 1]["net"] == 72082
    assert pick["NV02", 1]["net"] == 4582 and pick["NV02", 2]["net"] == 17082
    assert 4582+17082-72082 == -50418
    checked.append(dict(項目="早期利益保護と後続取引の差", 合格=True))
    day = read(sources[7])
    dayrows = read(sources[8])["rows"]
    assert len(dayrows) == 176
    for symbol, expected in (("TOPIX", (485133, 549034, 11995, 51906, 11)),
                             ("NK225", (248300, 141360, -95800, -11140, 12))):
        summary = next(x for x in day["summaries"] if x["method"] == "DV02" and x["symbol"] == symbol)
        values = tuple(summary[x] for x in ("old_net", "new_net", "initial_change", "retry_net", "retry_count"))
        assert values == expected
        assert sum(x["net"] for x in dayrows if x["method"] == "DV02" and x["symbol"] == symbol) == expected[1]
        checked.append(dict(項目="日中初回変更と再参加", 条件=symbol, 値=values))
    top = [x for x in day["rows"] if x["method"] == "DV02" and x["symbol"] == "TOPIX"]
    assert min(x["old_net"] for x in top) == -91672
    assert min(x["new_net"] for x in top) == -95426
    for row in top:
        if row["session"] == "2026-10-16_Day":
            assert row["initial_change"] == 32500 and row["retry_net"] == -36254
        if row["session"] == "2026-10-01_Day":
            p = next(x for x in row["parents"] if x["shadow_parent"] == 0)
            assert p["old_net"] == 94084 and p["initial_net"] == -22918 and p["retry_net"] == 86584
            assert p["new_net"] == 63666 and p["difference"] == -30418
    checked.append(dict(項目="再参加の具体例と最悪場", 合格=True))
    links, documents = [], []
    total = 0
    for file in ("入口.md", "継続.md", "出口.md", "売買の工夫.md"):
        path = KNOWLEDGE/file
        text = path.read_text(encoding="utf-8-sig")
        sections = re.findall(r'(<a id="00129_[^"]+"></a>.*?)(?=\n<a id="|\Z)', text, flags=re.S)
        expected_count = 2 if file == "入口.md" else 1
        assert len(sections) == expected_count
        total += len(sections)
        for section in sections:
            assert "**出典：**" in section and "00129_チャートと板からの失敗機構再検証/README.md" in section
            for href in re.findall(r'\]\(([^)]+)\)', section):
                target = (path.parent/href.split("#", 1)[0]).resolve()
                assert target.exists(), (file, href)
                links.append(dict(文書=file, href=href, target=target.relative_to(ROOT).as_posix()))
        documents.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(path)))
    assert total == 5
    # 高安が一分終値に限られることを明示した補正を最終版の条件とする。
    entry = (KNOWLEDGE/"入口.md").read_text(encoding="utf-8-sig")
    relevant = entry[entry.index('<a id="00129_価格差と高安の欠測資格を分ける">'):]
    clarification = ("一分終値" in relevant or "1分終値" in relevant) and ("分中" in relevant or "分内" in relevant)
    result = dict(passed=clarification, checks=checked, documents=documents, links=links,
                  entries=total, numerical_claims_checked=len(checked), financial_replays=0,
                  source_refs=[dict(path=p.relative_to(ROOT).as_posix(), sha256=sha(p)) for p in sources],
                  auditor_sha256=sha(Path(__file__)),
                  wording="高安は61個の一分終値の高低に限定し、分中の実高安ではないことを確認" if clarification else
                          "数値とリンクは一致。高安を61個の一分終値の高低と明確化する修正待ち。")
    target = HERE/f"共通知見五項目の数値と出典の独立レビュー_{time.time_ns()}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), passed=result["passed"],
                         entries=total, numeric_checks=len(checked), links=len(links),
                         wording=result["wording"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
