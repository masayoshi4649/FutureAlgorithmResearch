"""研究151の保存xlsxを原会計と照合し、未測定空欄・数式・正式テーブルを確認する。"""

import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def detail_values(row: dict) -> dict:
    """元会計を表示単位へ対応させる。

    引数: row(dict)は独立会計。
    返り値: dictは列と値。未測定はNone。
    """
    result = {"B": row["profit"], "C": row["loss"], "F": row["target_net"], "G": row["post"]["net"] if row["post"] else None,
              "L": row["max_unrealized_loss"], "M": row["equity_drawdown"], "N": row["max_long"], "O": row["max_short"],
              "P": row["entries"], "Q": row["target_entries"], "R": row["entry_quantity"],
              "W": row["cap_rejected_notices"], "X": row["rejected_notices"], "Y": row["reentry_entries"], "Z": row["positive_decision_negative_fill"]}
    for col, name, key in (("H", "trail", "profit"), ("I", "trail", "loss"), ("J", "boundary", "profit"), ("K", "boundary", "loss")):
        result[col] = row[name][key] if row[name] else None
    for col, key in (("S", "held_seconds"), ("T", "hedged_seconds"), ("U", "long_cap_seconds"), ("V", "short_cap_seconds")):
        result[col] = row[key] / 60 if row[key] is not None else None
    return result


def main() -> None:
    """保存値・数式・空欄・正式テーブルと出力同一性を確認する。

    引数: なし。
    返り値: None。検算証跡だけを保存し、xlsxを編集しない。
    """
    filename = "損切りなし両建ての全夜間損益.xlsx"
    path = ROOT / "アルゴリズム調査/00151_損切りなし両建てと利益玉トレーリング" / filename
    copy = ROOT / "outputs/00151_no_stop_hedge" / filename
    assert path.read_bytes() == copy.read_bytes()
    raw = (HERE / "report151.json").read_bytes()
    report = json.loads(raw)
    author = json.loads((HERE / "xlsx_checks/Excel計算との照合.json").read_text("utf-8"))
    assert hashlib.sha256(raw).hexdigest() == author["report_sha256"]
    numeric = blanks = formula_count = 0
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {row.attrib["Id"]: row.attrib["Target"] for row in rels}
        sheets = {}
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(x.itertext()) for x in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        for sheet in workbook.find("m:sheets", NS):
            destination = targets[sheet.attrib[f'{{{NS["r"]}}}id']]
            destination = destination.lstrip("/") if destination.startswith("/") else "xl/" + destination
            xml = ET.fromstring(archive.read(destination))
            cells = {cell.attrib["r"]: cell for cell in xml.findall(".//m:sheetData/m:row/m:c", NS)}
            assert not [cell for cell in cells.values() if cell.attrib.get("t") == "e"]
            parts = xml.find("m:tableParts", NS)
            assert parts is not None and len(parts) == 1
            sheets[sheet.attrib["name"]] = cells
            formula_count += sum(cell.find("m:f", NS) is not None for cell in cells.values())
        assert set(sheets) == {"比較", "当夜途中"} | {"日経_" + m["id"] for m in report["methods"]}
        table_paths = [name for name in archive.namelist() if name.startswith("xl/tables/") and name.endswith(".xml")]
        assert len(table_paths) == len(sheets)
        table_names = set()
        for name in table_paths:
            table = ET.fromstring(archive.read(name))
            assert table.find("m:autoFilter", NS) is not None
            table_names.add(table.attrib["displayName"])
        assert len(table_names) == len(table_paths)

        def check(sheet: str, cell: str, expected: float | None) -> None:
            """数値又は未測定空欄を直接検査する。

            引数: sheet,cell(str)は位置、expected(float|None)は元会計。
            返り値: None。空欄を0へ置き換えていた場合も停止する。
            """
            nonlocal numeric, blanks
            item = sheets[sheet].get(cell)
            if expected is None:
                if item is not None:
                    assert item.find("m:f", NS) is None, (sheet, cell, "未測定に式")
                    value = item.find("m:v", NS)
                    if value is not None and value.text:
                        assert item.attrib.get("t") == "s" and strings[int(value.text)] == "", (sheet, cell, "未測定を値で補完")
                blanks += 1
                return
            assert item is not None, (sheet, cell, "セルなし")
            value = item.find("m:v", NS)
            assert value is not None and value.text is not None, (sheet, cell, "値なし")
            actual = float(value.text)
            assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=0.0001), (sheet, cell, actual, expected)
            numeric += 1

        for method_index, method in enumerate(report["methods"]):
            sheet = "日経_" + method["id"]
            rows = sorted(method["rows"], key=lambda r: r["session"])
            assert len(rows) == 25
            cumulative = 0
            for n, row in enumerate(rows, 7):
                cumulative += row["net"]
                values = dict(detail_values(row), D=row["net"], E=cumulative)
                for col, value in values.items():
                    check(sheet, f"{col}{n}", value)
                assert sheets[sheet][f"D{n}"].find("m:f", NS) is not None
                assert sheets[sheet][f"E{n}"].find("m:f", NS) is not None
            for col in detail_values(rows[0]):
                values = [detail_values(row)[col] for row in rows]
                value = None if all(v is None for v in values) else max(values) if col in ("L", "M", "N", "O") else sum(values)
                check(sheet, f"{col}32", value)
            check(sheet, "D32", cumulative)
            check(sheet, "E32", cumulative)

            n = method_index + 7
            for col, key in (("C", "profit"), ("D", "loss"), ("E", "net"), ("F", "pf"), ("G", "wins"), ("H", "losses"), ("I", "maxloss"), ("J", "avgloss"), ("K", "medianloss"), ("L", "ex3"), ("R", "entries")):
                check("比較", f"{col}{n}", method["summary"][key])
            values = {"M": None, "N": None, "O": None, "P": None, "Q": None, "S": None, "T": None}
            if not method["saved_control"]:
                values.update(M=method["target_summary"]["net"], N=method["summary"]["trail"]["profit"], O=method["summary"]["boundary"]["loss"],
                              P=method["summary"]["max_unrealized_loss"], Q=method["summary"]["equity_drawdown"],
                              S=method["summary"]["cap_rejected_notices"], T=method["summary"]["reentry_entries"])
            for col, value in values.items():
                check("比較", f"{col}{n}", value)
        for n, row in enumerate(sorted(report["partial"], key=lambda r: r["id"]), 7):
            values = {"C": row["net"], "D": row["unrealized"], "E": row["equity"], "F": row["profit"], "G": row["loss"],
                      "H": row["open_lot_realized"], "I": row["entries"],
                      "J": sum(lot["remaining"] for lot in row["lot_details"] if lot["side"] > 0),
                      "K": sum(lot["remaining"] for lot in row["lot_details"] if lot["side"] < 0),
                      "L": row["max_unrealized_loss"], "M": row["equity_drawdown"]}
            for col, value in values.items():
                check("当夜途中", f"{col}{n}", value)
        assert len(list((HERE / "xlsx_checks").glob("*.png"))) == len(sheets)
    result = {"all_checks_passed": True, "numeric_cells_checked": numeric, "unmeasured_blank_cells_checked": blanks,
              "formula_cells": formula_count, "formula_errors": 0, "sheets": len(sheets), "formal_tables": len(table_paths),
              "public_copy_identical": True, "report_sha256": hashlib.sha256(raw).hexdigest(),
              "xlsx_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (HERE / "xlsx_checks/保存xlsxの独立検算.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
