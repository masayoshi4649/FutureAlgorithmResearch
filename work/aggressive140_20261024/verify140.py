"""生成xlsxを読み取り専用で開き、保存された数式値と元会計を照合する。"""

from __future__ import annotations

import hashlib
import json
import math
import posixpath
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile


WORK = Path(__file__).resolve().parent
ROOT = WORK.parent.parent
SOURCE = WORK / "report_data140.json"
BOOK = ROOT / "outputs/00140_aggressive_20261024/参加機会の改善と全セッション損益.xlsx"
PUBLIC = ROOT / "アルゴリズム調査/00140_参加機会の拡大と商品別戦略の再検証/参加機会の改善と全セッション損益.xlsx"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
KNOWN_END = "2026-10-22_Day"
DETAIL_LAYOUT = [("NK225", method, f"日経_{method}") for method in ["B5", "S36", "R02", "C36"]] + [
    ("TOPIX", method, f"TOPIX_{method}") for method in ["B5", "C33", "R09", "S33"]]


def number_equal(actual: object, expected: float, label: str) -> None:
    """数値一致を検証する。

    引数: actual(object) は保存値、expected(float) は期待値、label(str) は対象名。
    返り値: None。不一致・非有限ならAssertionErrorを発生する。
    """
    assert isinstance(actual, (float, int)) and math.isfinite(actual), (label, actual)
    assert abs(actual - expected) <= 0.001, (label, actual, expected)


def read_sheet(archive: ZipFile, name: str, shared: list[str]) -> tuple[dict, ET.Element]:
    """XMLからセル値と数式を読み取る。

    引数: archive(ZipFile) はxlsx、name(str) は内部パス、shared(list[str]) は文字列表。
    返り値: tuple[dict, ET.Element]。セル辞書とシートXML。
    """
    xml = ET.fromstring(archive.read(name))
    cells = {}
    for cell in xml.findall(".//s:sheetData/s:row/s:c", NS):
        kind = cell.get("t")
        value = cell.find("s:v", NS)
        formula = cell.find("s:f", NS)
        text = value.text if value is not None else None
        assert kind != "e", (name, cell.get("r"), text)
        if kind == "s":
            parsed = shared[int(text)]
        elif kind == "inlineStr":
            parsed = "".join(node.text or "" for node in cell.findall(".//s:t", NS))
        elif kind in {"str", "b"}:
            parsed = text
        elif kind == "d":
            parsed_date = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
            parsed = (parsed_date - datetime(1899, 12, 30)).total_seconds() / 86400
        elif text is None:
            parsed = None
        else:
            parsed = float(text)
        cells[cell.attrib["r"]] = (parsed, formula.text if formula is not None else None)
    return cells, xml


def main() -> None:
    """全会計と出力整合性を検証し、結果JSONを保存する。

    引数: なし。
    返り値: None。不整合時は処理を停止する。xlsxへの書き込みはしない。
    """
    data = json.loads(SOURCE.read_text(encoding="utf-8-sig"))
    assert BOOK.read_bytes() == PUBLIC.read_bytes(), "指定公開先の同一性が失われています"
    source_map = {(row["symbol"], row["method"], row["session"]): row for row in data["rows"]}
    checked = set()
    formula_count = 0
    with ZipFile(BOOK) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            string_xml = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.findall(".//s:t", NS)) for item in string_xml]
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {row.attrib["Id"]: row.attrib["Target"] for row in relations}
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = {}
        sheet_paths = {}
        for sheet in workbook.findall("s:sheets/s:sheet", NS):
            target = targets[sheet.attrib[f"{{{REL_NS}}}id"]]
            internal = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            sheets[sheet.attrib["name"]] = read_sheet(archive, internal, shared)
            sheet_paths[sheet.attrib["name"]] = internal
        expected_sheets = {"比較", "昼夜比較"} | {row[2] for row in DETAIL_LAYOUT} | ({"ペア_P03"} if data.get("pair_rows") else set())
        assert set(sheets) == expected_sheets, set(sheets)
        assert list(sheets) == ["比較", "昼夜比較"] + [row[2] for row in DETAIL_LAYOUT] + ["ペア_P03"], "シートの順序が違います"

        # ----------------------------------------
        # 見た目の罫線だけでなく、ネイティブ表とフィルタ定義の保存を確認する。
        table_checks = []
        table_names = set()
        for sheet_name, (_, sheet_xml) in sheets.items():
            sheet_path = sheet_paths[sheet_name]
            relation_path = posixpath.join(posixpath.dirname(sheet_path), "_rels", posixpath.basename(sheet_path) + ".rels")
            sheet_relations = ET.fromstring(archive.read(relation_path))
            table_targets = {row.attrib["Id"]: row.attrib["Target"] for row in sheet_relations}
            parts = sheet_xml.findall("s:tableParts/s:tablePart", NS)
            expected_ranges = {"A7:J10", "A13:T63"} if sheet_name == "ペア_P03" else ({"A6:Q30"} if sheet_name == "比較" else ({"A6:Q54"} if sheet_name == "昼夜比較" else {"A6:O56"}))
            actual_ranges = set()
            for part in parts:
                target = table_targets[part.attrib[f"{{{REL_NS}}}id"]]
                internal = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(sheet_path), target))
                table = ET.fromstring(archive.read(internal))
                name = table.attrib["name"]
                assert name not in table_names, (sheet_name, name, "表名重複")
                table_names.add(name)
                ref = table.attrib["ref"]
                actual_ranges.add(ref)
                auto_filter = table.find("s:autoFilter", NS)
                assert auto_filter is not None and auto_filter.attrib["ref"] == ref, (sheet_name, ref, "autoFilter未保存")
                columns = table.find("s:tableColumns", NS)
                assert columns is not None and int(columns.attrib["count"]) == len(columns), (sheet_name, "列数不一致")
                table_checks.append({"シート": sheet_name, "表": name, "範囲": ref, "autoFilter": True})
            assert actual_ranges == expected_ranges, (sheet_name, actual_ranges, expected_ranges)
        assert len(table_checks) == 12, "ネイティブ表数が12ではありません"

        # ----------------------------------------
        # 全明細の保存値とExcel式を元会計から独立に再計算する。
        for symbol, expected_method, sheet_name in DETAIL_LAYOUT:
            cells, xml = sheets[sheet_name]
            cumulatives = {}
            actual_rows = sorted(int(address[1:]) for address in cells if address.startswith("A") and address[1:].isdigit() and int(address[1:]) >= 7)
            assert actual_rows, sheet_name
            assert xml.find("s:tableParts", NS) is not None, f"{sheet_name}に絞り込み表がありません"
            assert xml.find("s:sheetViews/s:sheetView/s:pane", NS) is not None, f"{sheet_name}に固定表示がありません"
            for row_number in actual_rows:
                method = cells[f"A{row_number}"][0]
                assert method == expected_method, (sheet_name, method)
                candidates = sorted(key for key in source_map if key[0] == symbol and key[1] == method)
                consumed = sum(key in checked for key in candidates)
                key = candidates[consumed]
                source = source_map[key]
                checked.add(key)
                expected_kind = "デイ" if source["session"].endswith("_Day") else "ナイト"
                start = datetime.fromisoformat(source["session"][:10] + ("T08:45:00" if expected_kind == "デイ" else "T17:00:00"))
                serial = (start - datetime(1899, 12, 30)).total_seconds() / 86400
                number_equal(cells[f"B{row_number}"][0], serial, f"{key}/開始日時")
                assert cells[f"C{row_number}"][0] == expected_kind, key
                assert cells[f"M{row_number}"][0] == ("既知47場" if source["session"] <= KNOWN_END else "追加3場"), key
                cumulatives[method] = cumulatives.get(method, 0.0) + source["net"]
                for column, field in [("D", "profit"), ("E", "loss"), ("F", "net"), ("H", "fees"), ("I", "gross"), ("J", "entries"), ("K", "quantity"), ("L", "max_per_side")]:
                    number_equal(cells[f"{column}{row_number}"][0], source[field], f"{key}/{field}")
                number_equal(cells[f"G{row_number}"][0], cumulatives[method], f"{key}/累計")
                assert cells[f"F{row_number}"][1] == f"D{row_number}-E{row_number}", f"{key}/収支式"
                assert "SUMIFS" in cells[f"G{row_number}"][1], f"{key}/累計式"
                formula_count += 2
                for column, field in [("N", "first_minutes"), ("O", "held_minutes")]:
                    actual = cells.get(f"{column}{row_number}", (None, None))[0]
                    if source[field] is None:
                        assert actual is None, (key, field, actual)
                    else:
                        number_equal(actual, source[field], f"{key}/{field}")
        assert checked == set(source_map), "未照合の会計が残っています"

        # ----------------------------------------
        # 比較欄のキャッシュを元の銘柄・手法・対象区間の集計と照合する。
        cells, _ = sheets["比較"]
        summary_map = {(row["symbol"], row["method"], row["scope"]): row for row in data["summary"]}
        summary_checked = set()
        names = {"日経mini": "NK225", "TOPIXmini": "TOPIX"}
        scopes = {"全50場": "all", "既知47場": "known", "追加3場": "new"}
        for row_number in range(7, len(data["summary"]) + 7):
            key = (names[cells[f"A{row_number}"][0]], cells[f"B{row_number}"][0], scopes[cells[f"C{row_number}"][0]])
            summary_checked.add(key)
            source = summary_map[key]
            fields = ["profit", "loss", "net", "wins", "losses", "ex_top3", "entries", "worst", "avg_loss", "first_minutes", "held_minutes", "max_per_side"]
            for column, field in zip("DEFGHIJKLMNO", fields):
                actual, formula = cells.get(f"{column}{row_number}", (None, None))
                assert formula is not None, f"{key}/{field}/数式欠落"
                if column not in {"F"}:
                    expected_sheet = ("日経" if key[0] == "NK225" else "TOPIX") + "_" + key[1]
                    assert f"'{expected_sheet}'!" in formula, f"{key}/{field}/他手法参照"
                formula_count += 1
                if source[field] is None:
                    assert actual in {None, ""}, (key, field, actual)
                else:
                    number_equal(actual, source[field], f"{key}/{field}")
            relevant = [row for row in data["rows"] if row["symbol"] == key[0] and row["method"] == key[1]
                        and (key[2] == "all" or (row["session"] <= KNOWN_END if key[2] == "known" else row["session"] > KNOWN_END))]
            number_equal(cells[f"Q{row_number}"][0], sum(row["entries"] == 0 for row in relevant), f"{key}/無取引場数")
            assert cells[f"Q{row_number}"][1] is not None, f"{key}/無取引場数の数式欠落"
            formula_count += 1
        assert summary_checked == set(summary_map), "未照合の集計が残っています"

        # ----------------------------------------
        # 昼夜48区分の保存式値と、昼夜合計が従来集計へ戻ることを確認する。
        day_night_cells, _ = sheets["昼夜比較"]
        part_map = {(row["symbol"], row["method"], row["scope"], row["group"]): row for row in data["parts"]
                    if row["symbol"] in {"NK225", "TOPIX"} and row["group"] in {"Day", "Night"}}
        day_night_checked = {}
        for row_number in range(7, 55):
            symbol = names[day_night_cells[f"A{row_number}"][0]]
            method = day_night_cells[f"B{row_number}"][0]
            group = {"デイ": "Day", "ナイト": "Night"}[day_night_cells[f"C{row_number}"][0]]
            scope = scopes[day_night_cells[f"D{row_number}"][0]]
            key = (symbol, method, scope, group)
            assert key not in day_night_checked, (key, "昼夜集計の重複")
            part = part_map[key]
            baseline = "T06" if group == "Day" else ("U06" if symbol == "NK225" else "T04")
            assert day_night_cells[f"E{row_number}"][0] == baseline, (key, "基準手法不一致")
            assert day_night_cells[f"F{row_number}"][0], (key, "追加方式の説明欠落")
            fields = ["sessions", "profit", "loss", "net", "entries", "wins", "losses", "flat", "avg_loss", "worst", "ex_top3"]
            numbers = []
            for column, field in zip("GHIJKLMNOPQ", fields):
                actual, formula = day_night_cells[f"{column}{row_number}"]
                expected = max(0.0, -part[field]) if field == "worst" else part[field]
                number_equal(actual, expected, f"昼夜{key}/{field}")
                assert formula is not None, (key, field, "式欠落")
                if column != "J":
                    expected_sheet = ("日経" if symbol == "NK225" else "TOPIX") + "_" + method
                    assert f"'{expected_sheet}'!" in formula, (key, field, "他手法参照")
                numbers.append(actual)
                formula_count += 1
            day_night_checked[key] = numbers
        assert set(day_night_checked) == set(part_map) and len(day_night_checked) == 48, "昼夜48区分が揃いません"
        for key, stat in summary_map.items():
            daytime = day_night_checked[key + ("Day",)]
            nighttime = day_night_checked[key + ("Night",)]
            for index, field in enumerate(["sessions", "profit", "loss", "net", "entries", "wins", "losses", "flat"]):
                number_equal(daytime[index] + nighttime[index], stat[field], f"{key}/昼夜合計{field}")
        # ----------------------------------------
        # ペアの二脚内訳と独立した対象別集計を照合する。
        pair_checked = 0
        if data.get("pair_rows"):
            pair_cells, pair_xml = sheets["ペア_P03"]
            assert pair_xml.find("s:tableParts", NS) is not None, "ペアに絞り込み表がありません"
            assert pair_xml.find("s:sheetViews/s:sheetView/s:pane", NS) is not None, "ペアに固定表示がありません"
            pair_cumulative = {}
            pair_rows = sorted(data["pair_rows"], key=lambda row: (row["method"], row["session"]))
            for row_number, source in enumerate(pair_rows, start=14):
                key = (source["method"], source["session"])
                assert pair_cells[f"A{row_number}"][0] == source["method"], key
                expected_kind = "デイ" if source["session"].endswith("_Day") else "ナイト"
                start = datetime.fromisoformat(source["session"][:10] + ("T08:45:00" if expected_kind == "デイ" else "T17:00:00"))
                number_equal(pair_cells[f"B{row_number}"][0], (start - datetime(1899, 12, 30)).total_seconds() / 86400, f"{key}/日時")
                assert pair_cells[f"C{row_number}"][0] == expected_kind, key
                assert pair_cells[f"M{row_number}"][0] == ("既知47場" if source["session"] <= KNOWN_END else "追加3場"), key
                for column, field in [("D", "profit"), ("E", "loss"), ("F", "net"), ("H", "fees"), ("I", "gross"), ("J", "entries"), ("K", "quantity"), ("L", "max_per_side"), ("P", "nk_net"), ("Q", "topix_net"), ("R", "pair_count"), ("S", "mismatch"), ("T", "single_leg_seconds")]:
                    number_equal(pair_cells[f"{column}{row_number}"][0], source[field], f"ペア{key}/{field}")
                pair_cumulative[source["method"]] = pair_cumulative.get(source["method"], 0.0) + source["net"]
                number_equal(pair_cells[f"G{row_number}"][0], pair_cumulative[source["method"]], f"ペア{key}/累計")
                assert pair_cells[f"F{row_number}"][1] == f"D{row_number}-E{row_number}", f"ペア{key}/収支式"
                assert "SUMIFS" in pair_cells[f"G{row_number}"][1], f"ペア{key}/累計式"
                for column, field in [("N", "first_minutes"), ("O", "held_minutes")]:
                    actual = pair_cells.get(f"{column}{row_number}", (None, None))[0]
                    if source[field] is None:
                        assert actual is None, (key, field, actual)
                    else:
                        number_equal(actual, source[field], f"ペア{key}/{field}")
                pair_checked += 1
                formula_count += 2
            for row_number, scope in enumerate(["all", "known", "new"], start=8):
                source = next(row for row in data["pair_summary"] if row["scope"] == scope)
                for column, field in zip("BCDEFGHIJ", ["profit", "loss", "net", "wins", "losses", "flat", "entries", "fees", "ex_top3"]):
                    value, formula = pair_cells[f"{column}{row_number}"]
                    number_equal(value, source[field], f"ペア集計{scope}/{field}")
                    assert formula is not None, f"ペア集計{scope}/{field}数式"
                    formula_count += 1

        # ----------------------------------------
        # 旧10シートの数値と式は、許可された昼夜説明セル以外を変更しない。
        backup = WORK / "xlsx昼夜比較追加前140.xlsx"
        preserved_cells = 0
        with ZipFile(backup) as previous:
            old_shared = []
            if "xl/sharedStrings.xml" in previous.namelist():
                old_shared = ["".join(node.text or "" for node in item.findall(".//s:t", NS))
                              for item in ET.fromstring(previous.read("xl/sharedStrings.xml"))]
            old_targets = {row.attrib["Id"]: row.attrib["Target"] for row in ET.fromstring(previous.read("xl/_rels/workbook.xml.rels"))}
            old_book = ET.fromstring(previous.read("xl/workbook.xml"))
            for old_sheet in old_book.findall("s:sheets/s:sheet", NS):
                sheet_name = old_sheet.attrib["name"]
                target = old_targets[old_sheet.attrib[f"{{{REL_NS}}}id"]]
                internal = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
                old_cells, _ = read_sheet(previous, internal, old_shared)
                current_cells = sheets[sheet_name][0]
                allowed = {"A4", "A5"} if sheet_name in {row[2] for row in DETAIL_LAYOUT} else set()
                for address in set(old_cells) | set(current_cells):
                    if address in allowed:
                        continue
                    old_value = old_cells.get(address, (None, None))
                    current_value = current_cells.get(address, (None, None))
                    assert old_value == current_value, (sheet_name, address, "依頼範囲外の変更", old_value, current_value)
                    preserved_cells += 1
    result = {"出力": str(PUBLIC), "保存会計数": len(checked), "保存集計数": len(summary_checked), "照合数式数": formula_count,
              "ペア保存会計数": pair_checked,
              "昼夜集計数": len(day_night_checked), "旧シート維持セル数": preserved_cells,
              "シート名": list(sheets), "ネイティブ表数": len(table_checks), "表とフィルタ": table_checks,
              "Excelエラー値": 0, "原本と指定先が同一": True, "SHA256": hashlib.sha256(BOOK.read_bytes()).hexdigest(),
              "確認範囲": "xlsx内のXMLと保存済み式計算値を読み取り専用で照合。Excelアプリの起動はしていない。"}
    (WORK / "xlsx保存後照合140.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
