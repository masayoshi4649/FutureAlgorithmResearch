"""保存Excel XMLを別読取器で検査し、作者期待値と独立会計JSONの両方へ照合する。"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
from zipfile import ZipFile

WORK=Path(__file__).resolve().parent.parent
QA=WORK/"report/xlsx_checks"
NS={"s":"http://schemas.openxmlformats.org/spreadsheetml/2006/main","r":"http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def sha(path):
    """ファイル全体のSHA256を返す。

    引数: path(Path)。返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """全表・式・金額・区分・時間割の元会計一致を保存する。

    引数: なし。返り値: None。Excelアプリ起動や金融再生なし。
    """
    expected=json.loads((QA/"作者期待値164.json").read_text("utf-8"))
    source=WORK/"report_data164_all.json"
    report=json.loads(source.read_text("utf-8")); book=Path(expected["workbook"])
    assert sha(source)==expected["source_sha256"] and sha(book)==expected["workbook_sha256"]
    cells_by_sheet={}; tables={}; values={}; formulas=0
    with ZipFile(book) as archive:
        shared=[]
        if "xl/sharedStrings.xml" in archive.namelist():
            shared=["".join(si.itertext()) for si in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        rels={r.attrib["Id"]:r.attrib["Target"] for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        workbook=ET.fromstring(archive.read("xl/workbook.xml"))
        for sheet in workbook.find("s:sheets",NS):
            target=rels[sheet.attrib[f"{{{NS['r']}}}id"]]
            name=sheet.attrib["name"]
            filename=target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/"+target)
            xml=ET.fromstring(archive.read(filename)); assert xml.find("s:tableParts",NS) is not None
            cells={c.attrib["r"]:c for c in xml.findall(".//s:sheetData/s:row/s:c",NS)}
            cells_by_sheet[name]=cells; values[name]={}
            for address,cell in cells.items():
                assert cell.attrib.get("t")!="e",(name,address)
                v=cell.find("s:v",NS); value=v.text if v is not None and v.text is not None else ""
                if cell.attrib.get("t")=="s": value=shared[int(value)]
                elif cell.attrib.get("t")=="inlineStr": value="".join(cell.find("s:is",NS).itertext())
                values[name][address]=value
                formulas+=cell.find("s:f",NS) is not None
        for filename in archive.namelist():
            if filename.startswith("xl/tables/") and filename.endswith(".xml"):
                t=ET.fromstring(archive.read(filename)); tables[t.attrib["name"]]=t
    assert len(cells_by_sheet)==len(expected["sheets"])==34
    assert set(cells_by_sheet)==set(expected["sheets"])
    count=0

    def equal(sheet,address,value):
        """保存セルを数値又は文字で照合する。

        引数: sheet/address(str)、value(float又はstr)。返り値: None。
        """
        nonlocal count
        actual=values[sheet].get(address,"")
        if isinstance(value,(int,float)):
            assert actual!="" and abs(float(actual)-value)<1e-5,(sheet,address,actual,value)
        else:
            assert actual==value,(sheet,address,actual,value)
        count+=1

    for sheet,address,value in expected["checks"]+expected["texts"]:
        equal(sheet,address,value)
    assert len(tables)==len(expected["tables"])==33+len(report["schedules"])
    for item in expected["tables"]:
        table=tables[item["name"]]
        assert table.attrib["ref"]==item["reference"] and table.find("s:autoFilter",NS) is not None
        assert len(table.find("s:tableColumns",NS))==(15 if item["sheet"]=="比較" else 11)
    # ----------------------------------------
    # 作者が生成した期待値を使わず、会計正本から全27行を再取得します。
    for i,method in enumerate(report["methods"]):
        name="日経_"+method["id"].replace("NK225_","")
        total=0
        for j,row in enumerate(method["rows"]):
            n=j+6;total+=row["net"]
            expected_row={"A":row["session"],"C":row["direction"],"D":row["profit"],"E":row["loss"],"F":row["net"],"G":total,"H":row["minimum_equity"],"I":row["maximum_dd"],"J":row["new_orders"],"K":int(row["new_orders"]==0)}
            for col,value in expected_row.items(): equal(name,f"{col}{n}",value)
            for col in ("F","G","K"):
                assert cells_by_sheet[name][f"{col}{n}"].find("s:f",NS) is not None
        s=method["summary"]["全場"]; n=i+6
        fields=[s["profit"],s["loss"],s["net"],s["average"],s["negative_sessions"],s["no_entries"],s["mean_loss"],s["maximum_loss"],s["minimum_equity"],method["summary"]["前40内"]["net"],method["summary"]["確認14内"]["net"],s["excluding_top3"]]
        equal("比較",f"A{n}",method["id"])
        for col,value in zip("DEFGHIJKLMNO",fields): equal("比較",f"{col}{n}",value)
        for col in "DEFGMN": assert cells_by_sheet["比較"][f"{col}{n}"].find("s:f",NS) is not None
        for col in "DEFGHIJK": assert cells_by_sheet[name][f"{col}33"].find("s:f",NS) is not None
    for i,schedule in enumerate(report["schedules"]):
        header=5+i*32
        equal("夜間の時間割",f"A{header-1}"," / ".join(schedule["aliases"]))
        for j,row in enumerate(schedule["rows"]):
            n=header+j+1
            for col,value in {"A":row["session"],"B":schedule["pre"],"C":schedule["post"],"D":row["profit"],"E":row["loss"],"F":row["net"],"G":row["cumulative"],"H":row["minimum_equity"],"I":row["maximum_dd"]}.items(): equal("夜間の時間割",f"{col}{n}",value)
    result=dict(passed=True,created_at=datetime.now().astimezone().isoformat(),source_sha256=sha(source),workbook_sha256=sha(book),
        sheets=len(cells_by_sheet),tables=len(tables),checked_cells=count,formula_cells=formulas,formula_errors=0,
        independent_account_rows=32*27,native_excel_executed=False,new_financial_replays=0)
    (QA/"保存Excelの独立検算164.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (WORK/"report/検算164.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
