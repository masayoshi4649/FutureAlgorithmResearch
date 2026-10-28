"""保存済みxlsxのXMLを読み、正式Table・式・表示値を別の読取器で確認する。"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import xml.etree.ElementTree as ET
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def sha(path: Path) -> str:
    """保存ファイルの内容指紋を返す。

    引数: path(Path)。返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """元会計に対応した全検算セルと正式Excel構造を確認する。

    引数: なし。返り値: None。Excelアプリの実起動は行わない。
    """
    expected = json.loads((HERE/"xlsx_checks/Excel照合162.json").read_text(encoding="utf-8"))
    book = Path(expected["output"])
    source = HERE.parent/"report_data162.json"
    assert sha(book) == expected["workbook_sha256"]
    assert sha(source) == expected["source_sha256"]
    checked = 0
    formulas = 0
    sheet_data = {}
    with ZipFile(book) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {r.attrib["Id"]: r.attrib["Target"] for r in relationships}
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(si.itertext()) for si in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        for sheet in workbook.find("s:sheets", NS):
            link = sheet.attrib[f"{{{NS['r']}}}id"]
            target = targets[link]
            filename = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/"+target)
            parsed = ET.fromstring(archive.read(filename))
            cells = {cell.attrib["r"]: cell for cell in parsed.findall(".//s:sheetData/s:row/s:c", NS)}
            assert parsed.find("s:tableParts", NS) is not None, sheet.attrib["name"]
            for cell in cells.values():
                assert cell.attrib.get("t") != "e", (sheet.attrib["name"], cell.attrib["r"])
                formulas += cell.find("s:f", NS) is not None
            sheet_data[sheet.attrib["name"]] = cells
        assert len(sheet_data) == expected["sheets"] == 27
        for name, address, value in expected["check_cells"]:
            cell = sheet_data[name][address]
            stored = cell.find("s:v", NS)
            assert stored is not None and stored.text is not None, (name, address)
            actual = strings[int(stored.text)] if cell.attrib.get("t") == "s" else stored.text
            assert abs(float(actual)-value) < 1e-5, (name, address, actual, value)
            checked += 1
        tables = {}
        for filename in archive.namelist():
            if filename.startswith("xl/tables/") and filename.endswith(".xml"):
                item = ET.fromstring(archive.read(filename))
                tables[item.attrib["name"]] = item
        assert len(tables) == len(expected["tables"]) == 27
        for item in expected["tables"]:
            actual = tables[item["name"]]
            assert actual.attrib["ref"] == item["reference"]
            assert actual.find("s:autoFilter", NS) is not None
            assert len(actual.find("s:tableColumns", NS)) == (13 if item["sheet"] == "比較" else 12)
        for name, cells in sheet_data.items():
            if name == "比較":
                continue
            for row in range(6, 59):
                for column in ("E", "F"):
                    assert cells[f"{column}{row}"].find("s:f", NS) is not None
            assert cells["E59"].find("s:f", NS) is not None
    result = {"passed": True, "created_at": datetime.now().astimezone().isoformat(),
              "source_sha256": sha(source), "workbook_sha256": sha(book),
              "sheets": len(sheet_data), "tables": len(tables), "checked_cells": checked,
              "formula_cells": formulas, "formula_errors": 0, "native_excel_executed": False}
    (HERE/"xlsx_checks/保存Excelの独立検算162.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
