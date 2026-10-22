"""レポート生成処理を呼ばず、元会計とHTMLの全金額・追加表示・出典を独立照合する。"""

import argparse
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEST = ROOT / "アルゴリズム調査/00132_現行アルゴリズムの追加セッション検証"
PAGE = DEST / "現行アルゴリズムの全セッション損益.html"
OLD = ROOT / "work/regime131_20261020/公開候補の43場統合.json"
NEW = HERE / "results/追加セッションの会計.json"
SYMBOLS = ("TOPIX", "NK225")
ADDED = ("2026-10-20_Night", "2026-10-21_Day")


class Tables(HTMLParser):
    """生成された表の文字・属性を集める。生成器の整形関数は利用しない。"""

    def __init__(self):
        """
        機能: HTMLから独立抽出する表・リンク・アンカーを初期化する。
        引数: なし。
        返り値: None。
        """
        super().__init__(convert_charrefs=True)
        self.tables, self.links, self.ids = [], [], {}
        self.table, self.row, self.cell = None, None, None

    def handle_starttag(self, tag, attrs):
        """
        機能: 表・行・セルの開始と全リンクを記録する。
        引数: tag(str)、attrs(list[tuple])はHTMLの要素と属性。
        返り値: None。
        """
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids[attrs["id"]] = self.ids.get(attrs["id"], 0) + 1
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag == "table":
            assert self.table is None, "表の入れ子を想定しない"
            self.table = {"attrs": attrs, "rows": []}
            self.tables.append(self.table)
        elif tag == "tr" and self.table is not None:
            self.row = {"attrs": attrs, "cells": []}
            self.table["rows"].append(self.row)
        elif tag in ("td", "th") and self.row is not None:
            self.cell = {"attrs": attrs, "text": ""}
            self.row["cells"].append(self.cell)

    def handle_data(self, data):
        """
        機能: バッジ等の子要素を含めてセルの可視文字を蓄積する。
        引数: data(str)はHTML文字列。
        返り値: None。
        """
        if self.cell is not None:
            self.cell["text"] += data

    def handle_endtag(self, tag):
        """
        機能: セル・行・表の終了で現在の収集先を解放する。
        引数: tag(str)は終了要素。
        返り値: None。
        """
        if tag in ("td", "th"):
            self.cell = None
        elif tag == "tr":
            self.row = None
        elif tag == "table":
            self.table = None


def load(path):
    """
    機能: 保存済みのJSONを読み込む。
    引数: path(Path)は参照資料。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def reference(path):
    """
    機能: 検査した資料とその内容指紋を対応付ける。
    引数: path(Path)はプロジェクト内の資料。
    返り値: dictは相対pathとSHA256。
    """
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def parse_money(cell):
    """
    機能: HTMLに表示されている符号付き円額を独立して解釈する。
    引数: cell(dict)はHTMLParserが取得した一セル。
    返り値: intは表示額。色と数値の符号が違う場合は拒否する。
    """
    value = cell["text"].strip().replace("−", "-").replace(",", "")
    assert re.fullmatch(r"[+-]?\d+", value), value
    number = int(value)
    expected_class = "positive" if number > 0 else "negative" if number < 0 else "zero"
    assert expected_class in cell["attrs"].get("class", "").split(), cell
    return number


def integer(value):
    """
    機能: 元会計の整数円を丸め誤差の隠蔽なしに確定する。
    引数: value(float又はint)は元会計金額。
    返り値: intは整数円。1円未満の差がある会計は拒否する。
    """
    assert math.isfinite(value) and math.isclose(value, round(value), rel_tol=0., abs_tol=1e-6)
    return int(round(value))


def verify_link(base, href, ids=None):
    """
    機能: 相対リンクの参照ファイル又はページ内アンカーの実在を確認する。
    引数: base(Path)は参照元、href(str)は参照先、ids(dict|None)は同ページID集合。
    返り値: strは確認した参照先。
    """
    parsed = urlsplit(href)
    assert not parsed.scheme and not parsed.netloc and not parsed.query, href
    if parsed.path:
        target = (base.parent / unquote(parsed.path)).resolve()
        assert target.is_relative_to(ROOT) and target.is_file(), href
    else:
        assert parsed.fragment and ids is not None and ids.get(unquote(parsed.fragment)) == 1, href
    return href


def audit():
    """
    機能: 元90会計と全270場別セル・累計6セルを独立照合し、リンクと説明を点検する。
    引数: なし。固定した原会計と公開HTMLを読む。
    返り値: dictは監査数・元指紋・計数結果。金融再生はしない。
    """
    old, new = load(OLD), load(NEW)
    plan = load(HERE / "試行計画_v2.json")
    assert reference(OLD)["sha256"] == plan["sources"][reference(OLD)["path"]]
    assert old["passed"] and new["passed"]
    assert len(old["rows"]) == 86 and len(new["rows"]) == 4
    rows = old["rows"] + new["rows"]
    by_key = {(row["session"], row["symbol"]): row for row in rows}
    expected_sessions = sorted({row["session"] for row in rows})
    assert len(by_key) == 90 and len(expected_sessions) == 45
    assert {row["session"] for row in new["rows"]} == set(ADDED)
    combined = load(DEST / "セッション損益.json")
    assert combined["rows"] == sorted(rows, key=lambda row: (row["session"], SYMBOLS.index(row["symbol"])))
    assert combined["sources"] == [reference(OLD), reference(NEW)]
    page = PAGE.read_text(encoding="utf-8")
    parsed = Tables()
    parsed.feed(page)
    parsed.close()
    assert len(parsed.tables) == 2
    assert all(count == 1 for count in parsed.ids.values())
    assert "color-scheme:dark" in page and 'lang="ja"' in page
    assert "片方向上限10枚" in page and "同20枚" in page
    assert "TOPIXミニ41.8円" in page and "日経マイクロ11円" in page and "注文ごとに円未満切捨て" in page
    assert "アプリの実約定記録ではありません" in page
    session_table = next(table for table in parsed.tables if table["attrs"].get("id") == "sessions")
    session_rows = [row for row in session_table["rows"] if row["cells"] and re.match(r"\d{4}-\d{2}-\d{2}", row["cells"][0]["text"])]
    assert len(session_rows) == 45
    observed, added, count = [], [], 0
    for row in session_rows:
        label = row["cells"][0]["text"].strip()
        match = re.match(r"(\d{4}-\d{2}-\d{2}) (デイ|ナイト)", label)
        assert match and len(row["cells"]) == 7, row
        session = match[1] + ("_Day" if match[2] == "デイ" else "_Night")
        expected = []
        for symbol in SYMBOLS:
            source = by_key[session, symbol]
            expected.extend([integer(source["profit"]), -integer(source["loss"]), integer(source["net"])])
            assert integer(source["profit"])-integer(source["loss"]) == integer(source["gross"])-integer(source["fees"]) == integer(source["net"])
        values = [parse_money(cell) for cell in row["cells"][1:]]
        assert values == expected, (session, values, expected)
        assert ("追加" in label) == (session in ADDED)
        if "added" in row["attrs"].get("class", "").split():
            added.append(session)
        if session == ADDED[0]:
            assert row["attrs"].get("id") == "added-sessions"
        observed.append(session)
        count += len(values)
    assert observed == expected_sessions and added == list(ADDED)
    # ----------------------------------------
    # 表示器のtotalsを使わず、親取引集計済みの原会計90件から加算する。
    summary_rows = parsed.tables[0]["rows"][1:]
    assert len(summary_rows) == 2
    summaries = {}
    for symbol, row in zip(SYMBOLS, summary_rows, strict=True):
        assert len(row["cells"]) == 4
        source = [record for record in rows if record["symbol"] == symbol]
        assert len(source) == 45
        summary = {field: sum(integer(record[field]) for record in source) for field in ("profit", "loss", "net", "gross", "fees")}
        assert summary["profit"]-summary["loss"] == summary["gross"]-summary["fees"] == summary["net"]
        actual = [parse_money(cell) for cell in row["cells"][1:]]
        assert actual == [summary["profit"], -summary["loss"], summary["net"]]
        assert all(combined["summary"][symbol][field] == value for field, value in summary.items())
        summaries[symbol] = summary
    links = [verify_link(PAGE, href, parsed.ids) for href in parsed.links]
    readme_path = DEST / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    readme_links = [verify_link(readme_path, href) for href in re.findall(r"\[[^\]]+\]\(([^)]+)\)", readme)]
    for token in ("主担当はTOPIXミニ5枚・日経マイクロ10枚", "最大5枚・10枚", "DV07", "DV05", "NV01", "NV25", "T06", "T04", "U06"):
        assert token in readme, token
    assert PAGE.name in (ROOT / "README.md").read_text(encoding="utf-8-sig")
    assert PAGE.name in (ROOT / "アルゴリズム調査/index.html").read_text(encoding="utf-8-sig")
    return dict(passed=True, session_rows=len(observed), account_rows=len(by_key), session_amount_cells=count,
                total_amount_cells=6, added_rows=added, summary=summaries, html_links=links, readme_links=readme_links,
                sources=[reference(path) for path in (OLD, NEW, PAGE, DEST / "セッション損益.json", readme_path)],
                financial_replays=0, data_changes=0, browser_render_checked=False,
                note="HTML文字と属性を独立解析。ブラウザ画像の見え方を検証したものではない。")


def main():
    """
    機能: 独立表示監査を実行し、既存ファイルを上書きせず監査資料を保存する。
    引数: --outputで本作業内の監査出力先を指定できる。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="全セッション損益の独立表示照合")
    parser.add_argument("--output", type=Path, default=HERE / "report_display_audit.json")
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to(HERE) and not output.exists(), str(output)
    result = audit()
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ("passed", "session_rows", "account_rows", "session_amount_cells", "total_amount_cells", "added_rows", "summary")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
