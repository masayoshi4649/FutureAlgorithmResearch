"""書き出されたXLSXの正式テーブル、式キャッシュ、元会計との一致を読み取り検査する。"""

import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TARGET = ROOT / "アルゴリズム調査/00148_米国開始前の勢い入口と利益追跡/米国開始前の変更と全夜間損益.xlsx"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def equal(actual, expected, label):
    """元会計と出力キャッシュの値を照合する。

    引数: actual/expected(float)は検査値、label(str)は対象。
    返り値: None。不一致は例外で停止する。
    """
    assert isinstance(actual, (float, int)) and math.isfinite(actual), (label, actual)
    assert abs(actual - expected) < 0.001, (label, actual, expected)


def main():
    """ZIP内の表定義と全セッション会計を照合する。

    引数: なし。
    返り値: None。検査結果JSONだけを専用作業領域へ保存する。
    """
    report = json.loads((HERE / "report.json").read_text(encoding="utf-8"))
    verified = 0
    with zipfile.ZipFile(TARGET) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relmap = {node.attrib["Id"]: node.attrib["Target"] for node in rels}
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(node.itertext()) for node in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        sheets = {}
        for node in workbook.find("s:sheets", NS):
            rid = node.attrib[f"{{{NS['r']}}}id"]
            target = relmap[rid].lstrip("/")
            member = target if target.startswith("xl/") else "xl/" + target
            xml = ET.fromstring(archive.read(member))
            cells = {}
            for cell in xml.findall(".//s:sheetData/s:row/s:c", NS):
                value = cell.find("s:v", NS)
                if cell.attrib.get("t") == "e":
                    raise AssertionError((node.attrib["name"], cell.attrib["r"], value.text if value is not None else "式エラー"))
                if value is not None:
                    text = value.text or ""
                    if cell.attrib.get("t") == "s":
                        decoded = strings[int(text)]
                    elif cell.attrib.get("t") == "str":
                        decoded = text
                    else:
                        decoded = float(text) if text else None
                else:
                    inline = cell.find("s:is", NS)
                    decoded = "".join(inline.itertext()) if inline is not None else None
                cells[cell.attrib["r"]] = {"value": decoded, "formula": cell.find("s:f", NS) is not None}
            sheets[node.attrib["name"]] = cells
        assert len(sheets) == len(report["methods"]) + 2
        expected_names = {"比較", "当夜途中"} | {"日経_" + method["id"] for method in report["methods"]}
        assert set(sheets) == expected_names
        tables = [ET.fromstring(archive.read(name)) for name in archive.namelist() if name.startswith("xl/tables/") and name.endswith(".xml")]
        assert len(tables) == len(report["methods"]) + 2
        for table in tables:
            assert table.find("s:autoFilter", NS) is not None
            assert table.find("s:tableColumns", NS) is not None
            name = table.attrib["name"]
            expected_ref = "A6:K31" if name.startswith("Method148_") else f"A6:N{len(report['methods']) + 6}" if name == "Comparison148" else f"A6:H{len(report['partial']) + 6}"
            assert table.attrib["ref"] == expected_ref, (name, table.attrib["ref"])
        for method in report["methods"]:
            cells = sheets["日経_" + method["id"]]
            cumulative = 0.
            for index, row in enumerate(sorted(method["rows"], key=lambda r: r["session"]), start=7):
                assert cells[f"A{index}"]["value"] == row["session"]
                cumulative += row["net"]
                for col, expected in (("C", row["profit"]), ("D", row["loss"]), ("E", row["net"]), ("F", cumulative), ("G", row["entries"]), ("H", row["quantity"]), ("I", row["pre_net"]), ("J", row["post_net"])):
                    equal(cells[f"{col}{index}"]["value"], expected, (method["id"], index, col))
                    verified += 1
                assert cells[f"E{index}"]["formula"] and cells[f"F{index}"]["formula"]
            for col, key in (("C", "profit"), ("D", "loss"), ("E", "net"), ("G", "entries"), ("H", "quantity"), ("I", "pre_net"), ("J", "post_net")):
                equal(cells[f"{col}32"]["value"], sum(row[key] for row in method["rows"]), (method["id"], col, "総計"))
                verified += 1
                assert cells[f"{col}32"]["formula"]
        partial = {row["id"]: row for row in report["partial"]}
        for index in range(7, len(report["partial"]) + 7):
            method_id = sheets["当夜途中"][f"A{index}"]["value"]
            equal(sheets["当夜途中"][f"D{index}"]["value"], partial[method_id]["equity"], (method_id, "途中合計"))
            assert sheets["当夜途中"][f"D{index}"]["formula"]
            verified += 1
        result = {"xlsx": str(TARGET), "sheets": list(sheets), "tables": len(tables), "all_tables_have_filters": True, "rows_per_method": 25, "source_account_cells_verified": verified, "formula_cached_results_verified": True, "unexpected_formula_error": False}
    (HERE / "xlsx_checks/XLSX保存後の照合.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"sheets": len(sheets), "tables": len(tables), "verified": verified}, ensure_ascii=False))


if __name__ == "__main__":
    main()
