"""生成xlsxを読み取り専用で開き、保存された数式値と元会計を照合する。"""

from __future__ import annotations

import hashlib
import json
import math
import posixpath
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile


WORK = Path(__file__).resolve().parent
ROOT = WORK.parent.parent
SOURCE = WORK / "report_data142.json"
BOOK = ROOT / "outputs/00142_conditional_20261024/状況で切り替える手法の全セッション損益.xlsx"
PUBLIC = ROOT / "アルゴリズム調査/00142_状況判断と売買を分離した条件切替/状況で切り替える手法の全セッション損益.xlsx"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
KNOWN_END = "2026-10-22_Day"


def number_equal(actual: object, expected: float, label: str, tolerance: float = 0.001) -> None:
    """数値一致を検証する。

    引数: actual(object) は保存値、expected(float) は期待値、label(str) は対象名、tolerance(float) は許容誤差。
    返り値: None。不一致・非有限ならAssertionErrorを発生する。
    """
    assert isinstance(actual, (float, int)) and math.isfinite(actual), (label, actual)
    assert abs(actual - expected) <= tolerance, (label, actual, expected)


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
    detail_layout = [(row["symbol"], row["method"], ("日経" if row["symbol"] == "NK225" else "TOPIX") + "_" + row["method"]) for row in data["selected"]]
    selected_info = {(row["symbol"], row["method"]): row for row in data["selected"]}
    full_rows = [dict(row, group="全場") for row in data.get("comparison_summary", [])] + data.get("comparisons", [])
    summary_end = len(data["summary"]) + 6
    full_heading = summary_end + 5
    day_night_end = len(detail_layout) * 6 + 6
    loss_events = data.get("loss_events", [])
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
        expected_sheets = ["比較", "昼夜比較"] + (["具体損失時間"] if loss_events else []) + [row[2] for row in detail_layout]
        assert list(sheets) == expected_sheets, ("シート名又は順序が違います", list(sheets), expected_sheets)

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
            if sheet_name == "比較":
                expected_ranges = {f"A6:S{summary_end}"} | ({f"A{full_heading}:U{full_heading + len(full_rows)}"} if full_rows else set())
            elif sheet_name == "昼夜比較":
                expected_ranges = {f"A6:R{day_night_end}"}
            elif sheet_name == "具体損失時間":
                expected_ranges = {f"A6:H{len(loss_events) + 6}"}
            else:
                expected_ranges = {"A6:Q56"}
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
        assert len(table_checks) == len(expected_sheets) + bool(full_rows), "ネイティブ表数が設計と一致しません"

        # ----------------------------------------
        # 全明細の保存値とExcel式を元会計から独立に再計算する。
        for symbol, expected_method, sheet_name in detail_layout:
            cells, xml = sheets[sheet_name]
            cumulatives = {}
            actual_rows = sorted(int(address[1:]) for address in cells if address.startswith("A") and address[1:].isdigit() and int(address[1:]) >= 7)
            assert actual_rows == list(range(7, 57)), (sheet_name, "50場が揃っていません")
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
                number_equal(cells[f"B{row_number}"][0], serial, f"{key}/開始日時", 1e-8)
                assert cells[f"C{row_number}"][0] == expected_kind, key
                assert cells[f"M{row_number}"][0] == ("対照47場" if source["session"] <= KNOWN_END else "診断3場"), key
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
                duration = 420.0 if expected_kind == "デイ" else 780.0
                number_equal(cells[f"P{row_number}"][0], source["held_minutes"] / duration, f"{key}/保有率算式", 1e-9)
                number_equal(cells[f"P{row_number}"][0], source["holding_ratio"], f"{key}/保有率", 1e-9)
                number_equal(cells[f"Q{row_number}"][0], source["avg_held_quantity"], f"{key}/平均保有枚数", 1e-9)
                assert cells[f"P{row_number}"][1] == f'O{row_number}/IF(C{row_number}="デイ",420,780)', (key, "保有率式欠落")
                formula_count += 1
        assert checked == set(source_map), "未照合の会計が残っています"

        # ----------------------------------------
        # 比較欄のキャッシュを元の銘柄・手法・対象区間の集計と照合する。
        cells, _ = sheets["比較"]
        assert cells["A4"][0] == data["selection_note"], "比較案と約定模型の説明が一致しません"
        summary_map = {(row["symbol"], row["method"], row["scope"]): row for row in data["summary"]}
        summary_checked = set()
        names = {"日経mini": "NK225", "TOPIXmini": "TOPIX"}
        scopes = {"全50場": "all", "対照47場": "known", "診断3場": "new"}
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
            for column, field in (("R", "mean_holding_ratio"), ("S", "time_weighted_holding_ratio")):
                value, formula = cells[f"{column}{row_number}"]
                number_equal(value, source[field], f"{key}/{field}", 1e-9)
                expected_sheet = ("日経" if key[0] == "NK225" else "TOPIX") + "_" + key[1]
                assert formula is not None and f"'{expected_sheet}'!" in formula, (key, "保有率の参照不一致")
                formula_count += 1
        assert summary_checked == set(summary_map), "未照合の集計が残っています"

        # ----------------------------------------
        # 昼夜48区分の保存式値と、昼夜合計が従来集計へ戻ることを確認する。
        day_night_cells, _ = sheets["昼夜比較"]
        part_map = {(row["symbol"], row["method"], row["scope"], row["group"]): row for row in data["parts"]
                    if row["symbol"] in {"NK225", "TOPIX"} and row["group"] in {"Day", "Night"}}
        day_night_checked = {}
        for row_number in range(7, day_night_end + 1):
            symbol = names[day_night_cells[f"A{row_number}"][0]]
            method = day_night_cells[f"B{row_number}"][0]
            group = {"デイ": "Day", "ナイト": "Night"}[day_night_cells[f"C{row_number}"][0]]
            scope = scopes[day_night_cells[f"D{row_number}"][0]]
            key = (symbol, method, scope, group)
            assert key not in day_night_checked, (key, "昼夜集計の重複")
            part = part_map[key]
            info = selected_info[(symbol, method)]
            baseline = info["day_method" if group == "Day" else "night_method"]
            if baseline == "B5":
                underlying = "T06" if group == "Day" else ("U06" if symbol == "NK225" else "T04")
                baseline = f"B5（{underlying}）"
            elif baseline == "M1":
                underlying = ("G02" if group == "Day" else "G10") if symbol == "NK225" else ("G06" if group == "Day" else "H02")
                baseline = f"M1（{underlying}）"
            assert day_night_cells[f"E{row_number}"][0] == baseline, (key, "実行手法不一致")
            assert day_night_cells[f"F{row_number}"][0] == info["label"], (key, "運用説明の不一致")
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
            value, formula = day_night_cells[f"R{row_number}"]
            number_equal(value, part["mean_holding_ratio"], f"昼夜{key}/保有率", 1e-9)
            assert formula is not None and f"'{expected_sheet}'!" in formula, (key, "昼夜保有率の参照不一致")
            formula_count += 1
        assert set(day_night_checked) == set(part_map) and len(day_night_checked) == len(detail_layout) * 6, "昼夜区分が揃いません"
        for key, stat in summary_map.items():
            daytime = day_night_checked[key + ("Day",)]
            nighttime = day_night_checked[key + ("Night",)]
            for index, field in enumerate(["sessions", "profit", "loss", "net", "entries", "wins", "losses", "flat"]):
                number_equal(daytime[index] + nighttime[index], stat[field], f"{key}/昼夜合計{field}")
        # ----------------------------------------
        # 選定外も含む全条件表を、保存集計のキー・全列と照合する。
        full_map = {(row["symbol"], row["method"], row["scope"], row["group"]): row for row in full_rows}
        assert len(full_map) == len(full_rows), "全条件に重複キーがあります"
        full_checked = set()
        group_names = {"全場": "全場", "デイ": "Day", "ナイト": "Night", "上昇": "上昇", "下落": "下落"}
        for row_number in range(full_heading + 1, full_heading + len(full_rows) + 1):
            key = (names[cells[f"A{row_number}"][0]], cells[f"B{row_number}"][0], scopes[cells[f"C{row_number}"][0]], group_names[cells[f"T{row_number}"][0]])
            assert key not in full_checked, (key, "全条件表重複")
            full_checked.add(key)
            source = full_map[key]
            fields = {"D": "profit", "E": "loss", "F": "net", "G": "wins", "H": "losses", "I": "ex_top3", "J": "entries", "K": "worst", "L": "avg_loss", "M": "first_minutes", "N": "held_minutes", "O": "max_per_side", "Q": "flat", "R": "mean_holding_ratio", "S": "time_weighted_holding_ratio", "U": "sessions"}
            for column, field in fields.items():
                actual = cells.get(f"{column}{row_number}", (None, None))[0]
                if source[field] is None:
                    assert actual is None, (key, field, actual)
                else:
                    number_equal(actual, source[field], f"全条件{key}/{field}", 1e-9 if column in {"R", "S"} else .001)
            assert cells[f"P{row_number}"][0] == source["name"], (key, "手法名不一致")
            assert cells[f"F{row_number}"][1] == f"D{row_number}-E{row_number}", (key, "収支式欠落")
            formula_count += 1
        assert full_checked == set(full_map), "全条件に未照合の集計があります"

        # ----------------------------------------
        # 具体的な診断時計は原価格時計として保存し、全場収支の差額だけを計算する。
        loss_checked = 0
        if loss_events:
            event_cells, _ = sheets["具体損失時間"]
            assert event_cells["A3"][0] == data["loss_event_basis"], "損益差の比較単位が一致しません"
            for index, event in enumerate(loss_events):
                row_number = index + 7
                assert event_cells[f"A{row_number}"][0] == event["session"], (index, "診断場不一致")
                assert names[event_cells[f"B{row_number}"][0]] == event["symbol"], (index, "診断商品不一致")
                if isinstance(event["time"], (int, float)):
                    stamp = datetime.fromtimestamp(event["time"], timezone.utc)
                else:
                    stamp = datetime.fromisoformat(event["time"].replace("Z", "+00:00"))
                    assert stamp.tzinfo is not None, "診断時計にタイムゾーンがありません"
                    stamp = stamp.astimezone(timezone.utc)
                serial = ((stamp + timedelta(hours=9)).replace(tzinfo=None) - datetime(1899, 12, 30)).total_seconds() / 86400
                # 保存エンジンの日時丸めは最大1ミリ秒。2ミリ秒以内で照合する。
                number_equal(event_cells[f"C{row_number}"][0], serial, f"診断{index}/原価格時計", 0.002 / 86400)
                seq = event_cells.get(f"D{row_number}", (None, None))[0]
                if event["seq"] is None:
                    assert seq is None, (index, "未採番のseqを推定しています")
                else:
                    number_equal(seq, event["seq"], f"診断{index}/原seq")
                number_equal(event_cells[f"E{row_number}"][0], event["old_net"], f"診断{index}/旧収支")
                number_equal(event_cells[f"F{row_number}"][0], event["new_net"], f"診断{index}/改善後収支")
                number_equal(event_cells[f"G{row_number}"][0], event["new_net"] - event["old_net"], f"診断{index}/差額")
                assert event_cells[f"G{row_number}"][1] == f"F{row_number}-E{row_number}", (index, "差額式欠落")
                assert event_cells[f"H{row_number}"][0] == event["change"], (index, "問題説明不一致")
                formula_count += 1
                loss_checked += 1
    result = {"出力": str(PUBLIC), "保存会計数": len(checked), "保存集計数": len(summary_checked), "照合数式数": formula_count,
              "昼夜集計数": len(day_night_checked), "全条件保存集計数": len(full_checked), "損失診断数": loss_checked,
              "シート名": list(sheets), "ネイティブ表数": len(table_checks), "表とフィルタ": table_checks,
              "Excelエラー値": 0, "原本と指定先が同一": True, "SHA256": hashlib.sha256(BOOK.read_bytes()).hexdigest(),
              "確認範囲": "xlsx内のXMLと保存済み式計算値を読み取り専用で照合。Excelアプリの起動はしていない。"}
    (WORK / "xlsx保存後照合142.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
