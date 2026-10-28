"""保存xlsxの全表・式・キャッシュ値を元会計から独立に検算する。"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import posixpath
import statistics
import xml.etree.ElementTree as ET
from zipfile import ZipFile


WORK = Path(__file__).resolve().parents[1]
QA = WORK / "report/xlsx_checks"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def sha(path: Path) -> str:
    """ファイル全内容の指紋を返す。

    引数: path(Path)。返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    """UTF-8の確定会計・作者期待値を読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    """Excelアプリを使わず、正式Tableと全15手法405行を照合する。

    引数: なし。返り値: None。金融・式の再採点・売買条件変更は行わない。
    """
    audit = read(WORK / "audit/audit165.json")
    assert audit["passed"] and audit["totals"]["cases"] == 405
    expected = read(QA / "作者期待値165.json")
    source = WORK / "report_data165.json"
    report = read(source)
    workbook = Path(expected["workbook"])
    assert sha(source) == expected["source_sha256"]
    assert sha(workbook) == expected["workbook_sha256"]
    cells, values, tables, formula_count = {}, {}, {}, 0
    table_files, worksheet_tables = {}, {}
    with ZipFile(workbook) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(item.itertext()) for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        relationships = {item.attrib["Id"]: item.attrib["Target"] for item in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        root = ET.fromstring(archive.read("xl/workbook.xml"))
        for filename in archive.namelist():
            if filename.startswith("xl/tables/") and filename.endswith(".xml"):
                xml = ET.fromstring(archive.read(filename))
                assert xml.attrib["name"] not in tables
                tables[xml.attrib["name"]] = xml
                table_files[filename] = xml.attrib["name"]
        for sheet in root.find("s:sheets", NS):
            name = sheet.attrib["name"]
            target = relationships[sheet.attrib[f"{{{NS['r']}}}id"]]
            filename = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            xml = ET.fromstring(archive.read(filename))
            cells[name] = {item.attrib["r"]: item for item in xml.findall(".//s:sheetData/s:row/s:c", NS)}
            values[name] = {}
            for address, cell in cells[name].items():
                assert cell.attrib.get("t") != "e", (name, address, "保存式エラー")
                value = cell.find("s:v", NS)
                text = value.text if value is not None and value.text is not None else ""
                if cell.attrib.get("t") == "s":
                    text = shared[int(text)]
                elif cell.attrib.get("t") == "inlineStr":
                    text = "".join(cell.find("s:is", NS).itertext())
                values[name][address] = text
                formula_count += cell.find("s:f", NS) is not None
            table_parts = xml.find("s:tableParts", NS)
            assert table_parts is not None
            relpath = posixpath.join(posixpath.dirname(filename), "_rels", posixpath.basename(filename) + ".rels")
            rels = {item.attrib["Id"]: item.attrib["Target"] for item in ET.fromstring(archive.read(relpath))}
            linked = []
            for part in table_parts:
                target = rels[part.attrib[f"{{{NS['r']}}}id"]]
                resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(filename), target))
                linked.append(table_files[resolved])
            worksheet_tables[name] = linked
    assert len(cells) == 16 and set(cells) == set(expected["sheets"])
    assert len(tables) == 18 and len(worksheet_tables["比較"]) == 3
    assert all(len(value) == 1 for key, value in worksheet_tables.items() if key != "比較")
    checked, formulas_checked = 0, 0

    def equal(sheet: str, address: str, wanted) -> None:
        """保存済みの数値又は文字を期待値へ照合する。

        引数: sheet/address(str)、wanted(float又はstr)。返り値: None。
        """
        nonlocal checked
        actual = values[sheet].get(address, "")
        if isinstance(wanted, (int, float)):
            assert actual != "" and abs(float(actual) - wanted) < 1e-5, (sheet, address, actual, wanted)
        else:
            assert actual == wanted, (sheet, address, actual, wanted)
        checked += 1

    def formula(sheet: str, address: str, wanted: str | None = None) -> None:
        """式が保存され、必要な場合は参照範囲まで正しいことを確認する。

        引数: sheet/address(str)、wanted(str又はNone)。返り値: None。
        """
        nonlocal formulas_checked
        node = cells[sheet][address].find("s:f", NS)
        assert node is not None and node.text
        if wanted is not None:
            assert node.text.lstrip("=") == wanted.lstrip("="), (sheet, address, node.text, wanted)
        formulas_checked += 1

    for sheet, address, wanted in expected["checks"] + expected["texts"]:
        equal(sheet, address, wanted)
    for table in expected["tables"]:
        actual = tables[table["name"]]
        assert actual.attrib["ref"] == table["reference"]
        assert actual.find("s:autoFilter", NS) is not None
        assert table["name"] in worksheet_tables[table["sheet"]]
        assert len(actual.find("s:tableColumns", NS)) == (14 if table["sheet"] == "比較" else 13)

    # ----------------------------------------
    # 作者期待値を使わず、独立会計の各行から保存セルと式をもう一度求める。
    for method in report["methods"]:
        name = "日経_" + method["id"].replace("NK225_", "")
        running = 0.
        rows = method["rows"]
        assert len(rows) == 27
        for index, row in enumerate(rows):
            n = index + 6
            running += row["net"]
            period = "前20夜" if row["split"] in ("train", "validation") else "後7夜"
            wanted = [row["session"], period, row["profit"], row["loss"], row["net"], running,
                row["minimum_equity"], row["maximum_dd"], row["new_orders"], int(row["new_orders"] == 0),
                row["closed_micro"], row["net"] / (row["closed_micro"] * 10) if row["closed_micro"] else "n.a.", row["held_seconds"] / 60]
            for col, value in zip("ABCDEFGHIJKLM", wanted):
                equal(name, f"{col}{n}", value)
            formula(name, f"E{n}", f"C{n}-D{n}")
            formula(name, f"F{n}", f"F{n-1}+E{n}" if index else f"E{n}")
            formula(name, f"J{n}", f"IF(I{n}=0,1,0)")
            formula(name, f"L{n}", f'IF(K{n}=0,"n.a.",E{n}/(K{n}*10))')
        for column in "CDEFGHIJKLM":
            formula(name, column + "33")
        assert len(worksheet_tables[name]) == 1
        assert tables[worksheet_tables[name][0]].attrib["ref"] == "A5:M32"

    # ----------------------------------------
    # 期間ごとの比較値も場別行から再計算し、後7夜を前20へ混ぜない。
    for header, scope in ((5, "全場"), (24, "前20夜"), (43, "後7夜")):
        for index, method in enumerate(report["methods"]):
            rows = [row for row in method["rows"] if scope == "全場" or
                (row["split"] in ("train", "validation")) == (scope == "前20夜")]
            assert len(rows) == {"全場": 27, "前20夜": 20, "後7夜": 7}[scope]
            profit, loss = sum(row["profit"] for row in rows), sum(row["loss"] for row in rows)
            nets = [row["net"] for row in rows]
            closed = sum(row["closed_micro"] for row in rows)
            negatives = [-value for value in nets if value < 0]
            n = header + index + 1
            equal("比較", f"A{n}", method["id"])
            wanted = [profit, loss, sum(nets), len(negatives), sum(row["new_orders"] == 0 for row in rows),
                statistics.mean(negatives) if negatives else 0., max(negatives, default=0.),
                min(row["minimum_equity"] for row in rows), max(row["maximum_dd"] for row in rows),
                loss / (profit + loss) if profit + loss else "n.a.",
                sum(nets) / (closed * 10) if closed else "n.a.", sum(sorted(nets)[:-3])]
            for col, value in zip("CDEFGHIJKLMN", wanted):
                equal("比較", f"{col}{n}", value)
                formula("比較", f"{col}{n}")
    result = dict(passed=True, created_at=datetime.now().astimezone().isoformat(),
        source_sha256=sha(source), workbook_sha256=sha(workbook), audit_sha256=sha(WORK / "audit/audit165.json"),
        sheets=16, tables=18, checked_cells=checked, formula_cells=formula_count,
        formulas_checked=formulas_checked, formula_errors=0, independent_account_rows=405,
        all_table_relationships_verified=True, financial_replays=0, native_excel_executed=False,
        note="作者期待値に加えて、元会計の全405行と3期間の再集計を別のZIP/XML読取で照合。")
    for path in (QA / "保存Excelの独立検算165.json", WORK / "report/検算165.json"):
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
