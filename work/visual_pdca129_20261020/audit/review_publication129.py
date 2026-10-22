"""公開文書の主張・表示会計・リンクを保存資料で独立照合する。"""

import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import unquote

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
REPORT = ROOT / "アルゴリズム調査/00129_チャートと板からの失敗機構再検証"


def read_json(path):
    """
    機能: 保存JSONを読む。
    引数: path(Path)は保存先。
    返り値: dict又はlistは復号済み資料。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: 読んだファイルの内容指紋を求める。
    引数: path(Path)は対象ファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """
    機能: 数値・無取引・主張と限界を検査し、独立レビューの証跡を保存する。
    引数: なし。
    返り値: None。金融再生・公開資料変更はせず証跡だけを新規保存する。
    """
    documents = [
        REPORT / "README.md",
        REPORT / "反復の理由と到達点.md",
        REPORT / "チャートで検証した改修と全セッション損益.html",
        REPORT / "日中の持続確認で改善した部分と残る負け.md",
        REPORT / "夜間再試験の失敗と勝ちの観察.md",
    ]
    texts = {p.name: p.read_text(encoding="utf-8-sig") for p in documents}
    html = texts[documents[2].name]
    saved = json.loads(re.search(
        r'<script(?=[^>]*\bid="saved-data")[^>]*>(.*?)</script>', html, re.S
    ).group(1))
    final_path = WORK / "最終全場比較_確定.json"
    final = read_json(final_path)
    checks = []
    for key in ("rows", "summary"):
        assert saved[key] == final[key], key
    assert saved["names"] == {r["method"]: r["name"] for r in final["rows"]}
    checks.append(dict(項目="公開埋込資料と保存確定資料", 合格=True,
                       商品場=len(saved["rows"]), 比較群=len(saved["summary"])))

    # ----------------------------------------
    # 表示会計を保存場から再集計する。売買判断は再実行しない。
    for summary in saved["summary"]:
        rows = [r for r in saved["rows"]
                if (r["method"], r["symbol"]) == (summary["method"], summary["symbol"])]
        values = [r["net"] for r in rows]
        positive = sorted((v for v in values if v > 0), reverse=True)
        expected = {
            "sessions": len(rows), "profit": sum(r["profit"] for r in rows),
            "loss": sum(r["loss"] for r in rows), "net": sum(values),
            "black": sum(v > 0 for v in values), "red": sum(v < 0 for v in values),
            "flat": sum(r["entries"] == 0 for r in rows),
            "worst": min(values), "without_top3": sum(values)-sum(positive[:3]),
        }
        for key, value in expected.items():
            assert abs(summary[key]-value) < 1e-7, (summary["method"], summary["symbol"], key)
        assert all(abs(r["profit"]-r["loss"]-r["net"]) < 1e-7 for r in rows)
        assert not any(r["net"] == 0 and r["entries"] > 0 for r in rows)
        assert sum(x["net"] for x in summary["regimes"].values()) == summary["net"]
    checks.append(dict(項目="全72群の場会計・無取引・方向区分・上位除外", 合格=True,
                       備考="無取引と損益ゼロの実取引を混同する事例はない"))

    lookup = {(r["method"], r["symbol"]): r for r in saved["summary"]}
    expected_groups = {
        ("D17", "TOPIX"): (485133, 14, 6, 2, -91672),
        ("DV07", "TOPIX"): (522633, 14, 6, 2, -79172),
        ("D17", "NK225"): (248300, 15, 6, 1, -30520),
        ("DV05", "NK225"): (260800, 15, 6, 1, -25100),
        ("DV07", "NK225"): (242800, 15, 6, 1, -29100),
        ("NV25", "NK225"): (62040, 9, 4, 8, -8220),
        ("NV25", "TOPIX"): (156222, 7, 8, 6, -27918),
    }
    for key, expected in expected_groups.items():
        row = lookup[key]
        assert tuple(row[k] for k in ("net", "black", "red", "flat", "worst")) == expected
    checks.append(dict(項目="主要説明7群の数値", 合格=True))

    # ----------------------------------------
    # 文書と画像のローカルリンクを確認する。外部通信は行わない。
    links = []
    for document in documents:
        text = texts[document.name]
        if document.suffix == ".html":
            targets = re.findall(r'(?:href|src)="([^"]+)"', text)
        else:
            targets = re.findall(r"\]\(([^)]+)\)", text)
        for target in targets:
            if target.startswith(("http:", "https:", "#", "data:")):
                continue
            target_path = target.split("#", 1)[0].split("?", 1)[0]
            path = (document.parent / unquote(target_path)).resolve()
            assert path.exists(), (document.name, target)
            links.append(dict(文書=document.name, リンク=target))
    checks.append(dict(項目="ローカルリンク", 合格=True, 件数=len(links)))

    # ----------------------------------------
    # 成果と未達を分離できているか、今回の数値に基づいて判定する。
    assertions = {
        "既知開発資料と明記": all("既知" in texts[p.name] for p in documents[:3]),
        "READMEの夜間未完成": "夜間は未完成" in texts["README.md"],
        "HTMLの夜間採用を否定": "両銘柄共通の安定性をまだ確認できていない" in html,
        "HTMLで無取引を黒字に数えない": "無取引は黒字に数えない" in html,
        "欠測由来成績を採用しない": "欠測を利益条件にしていた成績を採用しない"
                                  in texts["反復の理由と到達点.md"],
        "日中赤字場数不変と明記": "6→6" in texts["README.md"],
        "日中の銘柄別選択が事後と明記": "既知資料で比較した結果" in texts["README.md"],
    }
    assert all(assertions.values()), assertions
    checks.append(dict(項目="採用保留と評価上の限界", 合格=True, 条件=assertions))
    notes = []
    if "<th>同値場収支</th>" not in html and "<th>同値収支</th>" not in html:
        notes.append(dict(対象="全条件比較表", 指摘="同値区分が未表示",
                          具体例="NV25日経は上昇18240+下落51020+同値-7220=総額62040",
                          推奨="同値列、または同値分が別にあることを表示"))
    if "NV04〜09は途中欠測の扱いに問題" in html:
        notes.append(dict(対象="欠測説明", 指摘="問題対象が広すぎる",
                          具体例="60差の過剰資格はNV04/05/07/08。境界高低NV06/09は全区間資格を維持",
                          推奨="NV04/05/07/08をNV10/11/12/13へ対応させて記載"))
    day_old = lookup[("D17", "NK225")]
    day_common = lookup[("DV07", "NK225")]
    notes.append(dict(
        対象="日中共通DV07の限定", 種別="結論誤りではなく強調の提案",
        収支差=day_common["net"]-day_old["net"],
        平均赤字旧=day_old["mean_red"], 平均赤字新=day_common["mean_red"],
        対応済み="全面改善ではない" in html,
        推奨="最悪場の小幅改善と全損失分布の改善を同一視せず、日経はDV05を別候補と明記する"))

    # ----------------------------------------
    # 新入口知見の親数と増減を、保存取引配列から独立に確認する。
    law_path = ROOT / "アルゴリズム調査/共通/知見台帳/入口.md"
    law = law_path.read_text(encoding="utf-8-sig").split(
        '<a id="00129_発注待機と準備破棄は別の手法"></a>', 1
    )[1]
    current_path = WORK / "night/強逆流準備破棄の全親差分と新準備.json"
    prior_path = WORK / "night/強逆流待機の全親差分と解除取消し.json"
    current, prior = read_json(current_path), read_json(prior_path)
    assert len(current["rows"]) == 69
    assert len(current["comparisons"]) == 8
    assert len(current["cancellations"]) == 9
    pairs = [p for x in current["comparisons"] for p in x["pairs"]]
    assert len(pairs) == 8 and all(p["new"] is None and p["old"] for p in pairs)
    old_diagnostics = {
        (r["method"], r["symbol"], r["session"], r["entry_row"]): r for r in prior["rows"]
    }
    for row in current["rows"]:
        old_key = ({"NV24": "NV22", "NV25": "NV23"}[row["method"]],
                   row["symbol"], row["session"], row["entry_row"])
        old = old_diagnostics[old_key]
        for field in ("arm_row", "boundary", "width", "progress_row", "return_row",
                      "return_extreme", "decision_row", "entry_row", "exit_row",
                      "side", "entry", "exit", "quantity", "gross", "fee", "net"):
            assert row[field] == old[field], (old_key, field)
    shared, removed, added = 0, [], []
    for path in sorted((WORK / "round7/measurement").glob("*.npz")):
        previous = WORK / "round6/measurement" / path.name
        with np.load(path) as new_file, np.load(previous) as old_file:
            for new_id, old_id in (("NV24", "NV22"), ("NV25", "NV23")):
                old_trades = old_file[old_id+"__trades"]
                new_trades = new_file[new_id+"__trades"]
                old_map = {(int(t[0]), int(t[2])): t for t in old_trades}
                new_map = {(int(t[0]), int(t[2])): t for t in new_trades}
                for key in old_map.keys() & new_map.keys():
                    np.testing.assert_array_equal(old_map[key], new_map[key])
                    shared += 1
                removed.extend(dict(手法=new_id, 商品=path.name.split("_")[0],
                                    親=list(key), 損益=old_map[key][8].item())
                               for key in old_map.keys()-new_map.keys())
                added.extend((path.name, new_id, key) for key in new_map.keys()-old_map.keys())
    assert shared == 69 and len(removed) == 8 and len(added) == 0
    expected_delta = {("NV24", "TOPIX"): 18336, ("NV24", "NK225"): -3340,
                      ("NV25", "TOPIX"): -7082, ("NV25", "NK225"): 21440}
    for key, value in expected_delta.items():
        assert -sum(r["損益"] for r in removed if (r["手法"], r["商品"]) == key) == value
    assert lookup[("NV25", "NK225")]["without_top3"] == 140
    assert "既知" in texts["README.md"] and "将来の優位性へ一般化しない" in law
    if "両120秒変化が各0.25初期ATR" in law:
        notes.append(dict(対象="入口の準備破棄知見", 指摘="120秒比の尺度は初期固定ATRではない",
                          推奨="各市場の当該観測行で公開済みATRと明記する"))
    for target in re.findall(r"\]\(([^)]+)\)", law):
        assert (law_path.parent / unquote(target.split("#", 1)[0])).resolve().exists(), target
    checks.append(dict(項目="追加入口知見の数値と分母", 合格=True,
                       比較口座84=84, 準備破棄=9, 除去親=removed,
                       全取引配列が同一の残存親=shared, 新親=len(added),
                       準備行を含む診断欄の一致=69, 未発注のままの破棄=1))
    proposals = [
        dict(
            観測量="新規時アンカー逆行の継続区間で、約定活動を伴うか否か",
            対象="日中DV05/DV07で撤退した全親と、D17で後に回復した勝ち",
            定義="逆行開始を当時固定し、正常原行の正の出来高増合計と価格変化回数を、出来高不変の気配更新回数と別に記録。方向推定は直接約定主体と呼ばない",
            目的="同じ価格時計60/120秒でも実活動を伴う再評価と静止価格内の更新が混在するかを区別する",
            対照="既存00110/00114の入口代理票とは保有中の分母・終点が異なる。新金融の前に全候補と欠測数、救う負けと失う勝ちを保存し、条件が分離しなければ採用しない"),
        dict(
            観測量="夜間の固定突破線への再接触時の、同じ絶対価格での表示供給維持と次の価格への進行",
            対象="NV25の残る全親、特に9/23日経と10/1TOPIXの失敗および似た入口の勝ち",
            定義="上位何段目かではなく同一絶対価格の表示数量を追い、価格を変えず数量が減少・回復した累計を出来高増と別記録。参照線は接触前の固定値を使う",
            目的="戻り形状だけでは分からない供給応答が失敗前に異なるかを検証する",
            対照="00114の一呼値先着率を流用しない。次正常原行の発注側気配から固定初期幅の逆行・利益保護起動までを全候補で採点し、打切も分母に残す。約定消費・取消・真の補充は今回の資料だけでは識別できない"),
    ]
    proof = dict(
        passed=True, レビュー範囲="保存会計と公開断定の敵対的照合。実描画の再検査ではない",
        主要結論="日中の限定改善・夜間共通採用保留は妥当。額の最大化、無取引の勝ち扱い、欠測の偶然採用による完成宣言なし",
        確認=checks, 表示文言の指摘=notes, 次の観測案=proposals,
        sources={str(p.relative_to(ROOT)): sha(p) for p in documents+
                 [final_path, law_path, current_path, prior_path, Path(__file__)]},
        financial_replays=0, api_calls=0, public_edits=0,
    )
    destination = HERE / f"公開結論と次仮説の敵対的レビュー_{time.time_ns()}.json"
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, path=str(destination), checks=len(checks),
                          links=len(links), notes=len(notes)), ensure_ascii=False))


if __name__ == "__main__":
    main()
