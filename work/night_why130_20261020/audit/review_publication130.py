"""公開結論・保存会計・分母・全選択・ローカル参照を独立に検査する。"""

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import unquote, urlparse

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PUBLIC = ROOT/"アルゴリズム調査/00130_夜間損失のなぜ三段階と再改善"


def read(path):
    """
    機能: 保存JSONを読み込む。
    引数: path(Path)は対象。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: 最終公開資料の内容指紋を取得する。
    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Extract(HTMLParser):
    """保存JSON、比較表セル、リンクだけを描画せず抽出する。"""

    def __init__(self):
        """
        機能: 抽出状態を初期化する。
        引数: なし。
        返り値: None。
        """
        super().__init__()
        self.payload = ""
        self.collect = False
        self.links = []
        self.table = False
        self.cell = None
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        """
        機能: 対象要素への進入と参照を記録する。
        引数: tag(str)、attrs(list[tuple])はHTML要素。
        返り値: None。
        """
        attrs = dict(attrs)
        if tag == "script" and attrs.get("id") == "saved-data":
            self.collect = True
        for key in ("href", "src"):
            if key in attrs:
                self.links.append(attrs[key])
        if tag == "table" and attrs.get("id") == "all-comparison":
            self.table = True
        if self.table and tag == "tr":
            self.row = []
        if self.table and tag in ("td", "th"):
            self.cell = ""

    def handle_data(self, value):
        """
        機能: 対象の文字データを保存する。
        引数: value(str)は文字列。
        返り値: None。
        """
        if self.collect:
            self.payload += value
        if self.cell is not None:
            self.cell += value

    def handle_endtag(self, tag):
        """
        機能: 対象要素の終了時に抽出結果を確定する。
        引数: tag(str)は終了要素。
        返り値: None。
        """
        if tag == "script":
            self.collect = False
        if self.table and tag in ("td", "th"):
            self.row.append(self.cell.strip())
            self.cell = None
        if self.table and tag == "tr":
            self.rows.append(self.row)
        if tag == "table":
            self.table = False


def metrics(rows):
    """
    機能: 保存された場会計だけから独立統計を計算する。
    引数: rows(list[dict])は対象の商品場。
    返り値: dictは利益損失・黒赤休・大勝ち除外等。
    """
    net = np.array([r["net"] for r in rows], float)
    positive, negative = net[net > 0], net[net < 0]
    return dict(sessions=len(rows), profit=sum(r["profit"] for r in rows),
        loss=sum(r["loss"] for r in rows), fees=sum(r["fees"] for r in rows),
        net=float(net.sum()), black=len(positive), red=len(negative),
        flat=sum(r["entries"] == 0 for r in rows),
        breakeven=sum(r["entries"] > 0 and r["net"] == 0 for r in rows),
        active=sum(r["entries"] > 0 for r in rows),
        median=float(np.median(net)) if len(net) else 0.,
        worst=float(net.min()) if len(net) else 0.,
        mean_black=float(positive.mean()) if len(positive) else 0.,
        mean_red=float(-negative.mean()) if len(negative) else 0.,
        without_top3=float(net.sum()-np.sort(positive)[-3:].sum()),
        entries=sum(r["entries"] for r in rows))


def number(text):
    """
    機能: 表示円額を整数へ戻す。
    引数: text(str)は符号付き円額。
    返り値: intは金額。
    """
    return int(text.replace(",", "").replace("円", "").replace("＋", "+").replace("−", "-"))


def main():
    """
    機能: 公開762商品場と統計・表示元・全選択・文章中の主要表を独立検査する。
    引数: なし。
    返り値: None。金融再生せずレビュー証拠だけを保存する。
    """
    final_path = WORK/"最終全場比較_確定.json"
    data = read(final_path)
    conclusion = read(WORK/"結論.json")
    html_path = PUBLIC/"夜間のなぜ三段階と改善後の損益.html"
    documents = list(PUBLIC.glob("*.md"))+[html_path, final_path, WORK/"結論.json"]
    snapshot = {p.relative_to(ROOT).as_posix(): sha(p) for p in documents}
    keys = [(r["method"], r["symbol"], r["session"]) for r in data["rows"]]
    assert len(keys) == len(set(keys)) == 762
    assert len({r["method"] for r in data["rows"]}) == 18
    assert len({r["session"] for r in data["rows"]}) == 43
    assert data["financial_replays"] == 0  # 最終資料は保存会計の再集計のみ。

    # ----------------------------------------
    # 旧258商品場と新504商品場の出典を、その保存会計へ一行ずつ照合する。
    origins = {}
    for ref in data["evidence"]:
        assert sha(ROOT/ref["path"]) == ref["sha256"], ref
        for row in read(ROOT/ref["path"])["rows"]:
            key = row["method"], row["symbol"], row["session"]
            origins[key] = row
    assert sum(read(ROOT/ref["path"])["financial_replays"] for ref in data["evidence"][1:]) == 504
    numeric = ("profit", "loss", "net", "gross", "fees", "entries", "quantity",
               "parent_wins", "parent_losses", "max_quantity")
    for row in data["rows"]:
        key = row["method"], row["symbol"], row["session"]
        original = origins[key]
        for field in numeric:
            assert row[field] == original[field], (key, field)
        assert row["profit"] >= 0 and row["loss"] >= 0
        assert row["profit"]-row["loss"] == row["net"] == row["gross"]-row["fees"]
        assert row["entries"] or row["net"] == 0
    assert sum(r["method"].startswith("W") for r in data["rows"]) == 504
    summaries = {(s["method"], s["symbol"]): s for s in data["summary"]}
    compared_groups = 0
    for key, summary in summaries.items():
        rows = [r for r in data["rows"] if (r["method"], r["symbol"]) == key]
        expected = metrics(rows)
        for field, value in expected.items():
            assert np.isclose(summary[field], value, atol=1e-8, rtol=0), (key, field)
        assert summary["sessions"] == (22 if summary["kind"] == "Day" else 21)
        assert summary["black"]+summary["red"]+summary["flat"]+summary["breakeven"] == summary["sessions"]
        compared_groups += 1
        for groupfield, rowfield in (("regimes", "regime"), ("halves", "half_within_kind")):
            for group, given in summary[groupfield].items():
                calculated = metrics([r for r in rows if r[rowfield] == group])
                for field, value in calculated.items():
                    assert np.isclose(given[field], value, atol=1e-8, rtol=0), (key, group, field)
                compared_groups += 1
            assert sum(v["sessions"] for v in summary[groupfield].values()) == summary["sessions"]
            assert sum(v["net"] for v in summary[groupfield].values()) == summary["net"]

    parsed = Extract()
    parsed.feed(html_path.read_text(encoding="utf-8-sig"))
    embedded = json.loads(parsed.payload)
    assert embedded["rows"] == data["rows"] and embedded["summary"] == data["summary"]
    assert len(parsed.rows)-1 == len(summaries)
    for row in parsed.rows[1:]:
        s = summaries[row[0], row[1]]
        assert number(row[2]) == s["net"]
        assert list(map(int, row[3].split("/"))) == [s[k] for k in ("black", "red", "flat", "breakeven")]
        assert number(row[4]) == s["worst"] and number(row[5]) == s["without_top3"]
        for index, regime in enumerate(("上昇", "下落", "同値")):
            assert number(row[6+index]) == s["regimes"].get(regime, {}).get("net", 0.)
        assert number(row[9]) == s["halves"]["後半"]["net"]

    # ----------------------------------------
    # 選択による欠落や重複がなく、昼夜を混ぜても43場・両商品が揃うことを確認する。
    methods = {kind: sorted({r["method"] for r in data["rows"] if r["kind"] == kind})
               for kind in ("Day", "Night")}
    selections = 0
    for day in ["別"]+methods["Day"]:
        for night in methods["Night"]:
            selected = []
            for row in data["rows"]:
                method = night if row["kind"] == "Night" else (
                    ("DV07" if row["symbol"] == "TOPIX" else "DV05") if day == "別" else day)
                if row["method"] == method:
                    selected.append(row)
            assert len(selected) == 86
            scenes = sorted({r["session"] for r in selected})
            assert len(scenes) == 43
            for symbol in ("TOPIX", "NK225"):
                values = [r for r in selected if r["symbol"] == symbol]
                assert len(values) == 43 and len({r["session"] for r in values}) == 43
                dm = ("DV07" if symbol == "TOPIX" else "DV05") if day == "別" else day
                assert sum(r["net"] for r in values) == summaries[dm, symbol]["net"]+summaries[night, symbol]["net"]
            selections += 1
    assert selections == 60

    table_rows = 0
    local_links, missing = [], []
    for path in documents:
        if path.suffix not in (".md", ".html"):
            continue
        text = path.read_text(encoding="utf-8-sig")
        links = parsed.links if path.suffix == ".html" else re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text)
        for target in links:
            parsed_url = urlparse(target.strip("<>"))
            if parsed_url.scheme or not parsed_url.path:
                continue
            resolved = (path.parent/unquote(parsed_url.path)).resolve()
            local_links.append(dict(source=path.relative_to(ROOT).as_posix(), target=target,
                                    exists=resolved.exists()))
            if not resolved.exists():
                missing.append(local_links[-1])
        if path.suffix == ".md":
            for line in text.splitlines():
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) != 5:
                    continue
                match = re.fullmatch(r"([A-Z][A-Z0-9]*)・(TOPIX|NK225)", cells[0])
                if not match or not cells[1].endswith("円") or len(cells[2].split("／")) != 3:
                    continue
                s = summaries[match.group(1), match.group(2)]
                assert number(cells[1]) == s["net"], (str(path), cells, s["net"])
                assert list(map(int, cells[2].split("／"))) == [s["black"], s["red"], s["flat"]]
                assert number(cells[3]) == s["worst"] and number(cells[4]) == s["without_top3"]
                table_rows += 1
    assert not missing, missing

    # ----------------------------------------
    # 冒頭の採用範囲と反例を保存数値へ対応させ、無取引を無敗の根拠にしない。
    assert conclusion["night"] == "W07"
    assert "未完成" in conclusion["headline"] and "TOPIX" in conclusion["headline"]
    assert "17" in conclusion["finding"] and "全夜間の安定性を示す結果ではない" in conclusion["finding"]
    assert summaries["W12", "NK225"]["entries"] == summaries["W12", "NK225"]["black"] == 4
    assert summaries["W12", "NK225"]["flat"] == 17
    assert summaries["W07", "TOPIX"]["worst"] == -33754
    assert summaries["W07", "TOPIX"]["without_top3"] == 97894
    assert summaries["W07", "NK225"]["without_top3"] == -36640
    assert summaries["W07", "TOPIX"]["profit"]-summaries["W11", "TOPIX"]["profit"] == 268320
    assert summaries["W07", "TOPIX"]["loss"]-summaries["W11", "TOPIX"]["loss"] == 74172
    assert summaries["W12", "NK225"]["net"]-summaries["W08", "NK225"]["net"] == 10220-4780
    assert all(summaries["W07", "TOPIX"][field][key]["net"] > 0
               for field, keys_ in (("regimes", ("上昇", "下落")), ("halves", ("前半", "後半")))
               for key in keys_)
    specification = (PUBLIC/"改修条件の対応.md").read_text(encoding="utf-8-sig")
    assert "それぞれ観測時点で公開済みのATR" in specification
    assert "固定したRを使わず" in specification and "判断時刻より厳密に過去" in specification
    after = {p.relative_to(ROOT).as_posix(): sha(p) for p in documents}
    assert snapshot == after, "監査中に公開資料が変更された"
    result = dict(passed=True, accounts=762, new_accounts=504, reused_accounts=258,
        methods=18, summaries=len(summaries), statistical_groups=compared_groups,
        selected_combinations=selections, markdown_table_rows=table_rows,
        local_links_checked=len(local_links), links=local_links, sources=after,
        evidence=data["evidence"], financial_replays=0, API=0,
        manual_conclusion="TOPIX W07は既知資料内の損失縮小候補。W12日経4勝を全21夜間の安定性へ一般化していない。日中は保存引用。時計・実約定・主導側代理の限界を区別している。",
        resolved_clarification="NV25の逆流分母を観測時点の自己/相手ATR、準備固定Rとは別、相手は厳密過去行とする説明が修正済み。最新公開SHAで確認。",
        excluded_scope="ブラウザ描画はrootの実表示QA。外部論文の再査読・新相場再生はしない。")
    target = HERE/f"最終公開結論と762商品場の敵対的レビュー_{time.time_ns()}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in ("sources", "links", "evidence")},
                     ensure_ascii=False))
    print(target)


if __name__ == "__main__":
    main()
