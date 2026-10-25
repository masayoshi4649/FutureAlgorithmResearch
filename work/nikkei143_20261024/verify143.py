"""143の完成xlsxをZIP/XMLで読み、正式表・全場会計・式の保存結果を独立確認する。"""

from pathlib import Path
import hashlib
import json
import math
import posixpath
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'p': 'http://schemas.openxmlformats.org/package/2006/relationships'}
RID = '{'+NS['r']+'}id'


def read(path):
    """
    機能: JSONの原資料を読む。
    引数: path(Path)は資料の位置。
    返り値: dict/listは原内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def equal(actual, expected, label):
    """
    機能: 欠測・文字・数値を区別して期待値と比較する。
    引数: actual/expected(str|float|None)、label(str)は値と確認名。
    返り値: None。不一致なら例外。
    """
    if expected is None:
        assert actual in (None, ''), (label, actual, expected)
    elif isinstance(expected, (float, int)):
        assert isinstance(actual, (float, int)) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-6), (label, actual, expected)
    else:
        assert actual == expected, (label, actual, expected)


def relation_path(owner, target):
    """
    機能: xlsx内の関連先を所有部品から解決する。
    引数: owner/target(str)はZIP内の部品名と関連先。
    返り値: strは正規化したZIP内の位置。
    """
    return target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(owner), target))


def excel_start(session):
    """
    機能: 日本時間の場開始をExcelの日時数値へ変換する。
    引数: session(str)は日付_Day/Night。
    返り値: floatは時差を持たない日本時間のシリアル値。
    """
    hour = '08:45' if session.endswith('_Day') else '17:00'
    value = datetime.fromisoformat(session[:10]+'T'+hour+':00')
    return (value-datetime(1899, 12, 30)).total_seconds()/86400.


def main():
    """
    機能: 出力と公開版を照合し、全明細・計算キャッシュ・正式表を検証する。
    引数: なし。
    返り値: None。既存xlsxを編集せず検査JSONだけを作成する。
    """
    source = read(HERE/'report_data143.json')
    evidence = read(HERE/'F1始終値方向と深夜除外保有率143.json')
    generated = read(HERE/'xlsx照合143.json')
    output, public = Path(generated['出力']), Path(generated['公開先'])
    raw = output.read_bytes()
    assert raw == public.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == generated['SHA256']
    assert hashlib.sha256((HERE/'report_data143.json').read_bytes()).hexdigest() == generated['入力SHA256']
    labels = {row['session']: row for row in evidence['sessions']}
    expected_names = ['比較', '昼夜・方向比較']+[f'日経_{item["method"]}' for item in source['selected']]+['始終値根拠']
    cells, tables, formulas, formula_errors = {}, [], [], []
    with zipfile.ZipFile(output) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(value.itertext()) for value in shared.findall('s:si', NS)]
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets = {item.attrib['Id']: relation_path('xl/workbook.xml', item.attrib['Target']) for item in rels}
        sheets = workbook.findall('s:sheets/s:sheet', NS)
        assert [item.attrib['name'] for item in sheets] == expected_names
        for sheet in sheets:
            name = sheet.attrib['name']
            target = targets[sheet.attrib[RID]]
            xml = ET.fromstring(archive.read(target))
            current = {}
            for cell in xml.findall('.//s:sheetData/s:row/s:c', NS):
                address, kind = cell.attrib['r'], cell.attrib.get('t')
                value = cell.find('s:v', NS)
                text = value.text if value is not None else None
                if kind == 's':
                    content = strings[int(text)]
                elif kind == 'inlineStr':
                    content = ''.join(cell.find('s:is', NS).itertext())
                elif kind in ('str', 'e'):
                    content = text
                elif kind == 'd':
                    value_date = datetime.fromisoformat(text.replace('Z', '+00:00')).replace(tzinfo=None)
                    content = (value_date-datetime(1899, 12, 30)).total_seconds()/86400.
                else:
                    content = float(text) if text is not None else None
                current[address] = content
                formula = cell.find('s:f', NS)
                if formula is not None:
                    formulas.append({'sheet': name, 'cell': address, 'formula': formula.text})
                    assert content is not None, (name, address, '式の保存値がありません')
                if kind == 'e':
                    formula_errors.append({'sheet': name, 'cell': address, 'error': content})
            cells[name] = current
            relation = posixpath.join(posixpath.dirname(target), '_rels', posixpath.basename(target)+'.rels')
            sheet_targets = {}
            if relation in archive.namelist():
                for item in ET.fromstring(archive.read(relation)):
                    sheet_targets[item.attrib['Id']] = relation_path(target, item.attrib['Target'])
            for table in xml.findall('s:tableParts/s:tablePart', NS):
                detail = ET.fromstring(archive.read(sheet_targets[table.attrib[RID]]))
                auto = detail.find('s:autoFilter', NS)
                assert auto is not None and auto.attrib['ref'] == detail.attrib['ref']
                columns = detail.findall('s:tableColumns/s:tableColumn', NS)
                assert len(columns) == len({item.attrib['name'] for item in columns})
                tables.append({'sheet': name, 'name': detail.attrib['name'], 'ref': detail.attrib['ref'], 'columns': len(columns)})
    assert not formula_errors, formula_errors
    for name in expected_names:
        assert any(table['sheet'] == name for table in tables), (name, '正式なExcelテーブルがありません')
    assert len({table['name'] for table in tables}) == len(tables)
    checks = 0
    for selected in source['selected']:
        method = selected['method']
        name = f'日経_{method}'
        rows = sorted([r for r in source['rows'] if r['method'] == method], key=lambda r: r['session'])
        assert len(rows) == 50
        assert any(t['sheet'] == name and t['ref'] == 'A6:T56' and t['columns'] == 20 for t in tables)
        total = 0.
        for index, row in enumerate(rows, 7):
            total += row['net']
            ratio = row.get('holding_ratio_excluding_03_06', row.get('holding_ratio'))
            quantity = row.get('avg_held_quantity_excluding_03_06', row.get('average_quantity'))
            split = ('比較47場' if row['session'] <= '2026-10-22_Day' else '診断3場') if source.get('include_period_split') else '既知開発50場'
            expected = [method, excel_start(row['session']), 'デイ' if row['session'].endswith('_Day') else 'ナイト', labels[row['session']]['direction'],
                row['profit'], row['loss'], row['net'], total, row['fees'], row['gross'], row['entries'], row['quantity'], row['max_per_side'],
                row['first_minutes'], row['held_minutes'], row['held_minutes_excluding_03_06'], 420. if row['session'].endswith('_Day') else 600., ratio, quantity, split]
            for number, value in enumerate(expected):
                address = chr(65+number)+str(index)
                equal(cells[name].get(address), value, name+'!'+address)
                checks += 1
            for column in ('G', 'H', 'R'):
                assert any(f['sheet'] == name and f['cell'] == column+str(index) for f in formulas)
    for check in generated['検算セル']:
        equal(cells[check['sheet']].get(check['cell']), check['expected'], check['sheet']+'!'+check['cell'])
        checks += 1
    assert any(t['sheet'] == '始終値根拠' and t['ref'] == 'A6:O56' for t in tables)
    for index, row in enumerate(sorted(evidence['sessions'], key=lambda r: r['session']), 7):
        for column, expected in [('A', row['session']), ('B', row['first_price']), ('D', row['final_price']), ('F', row['change']),
                                 ('G', row['direction']), ('J', row['first_evidence']['seq0']), ('K', row['final_evidence']['seq0']), ('M', row['book_sha256'])]:
            equal(cells['始終値根拠'].get(column+str(index)), expected, '始終値根拠!'+column+str(index))
            checks += 1
    report = dict(合格=True, シート=expected_names, 正式テーブル=tables, 数式数=len(formulas), 数式エラー数=0,
                  検算数=checks, 全会計行数=len(source['selected'])*50, 始終値根拠=50,
                  出力=str(output), 公開先=str(public), SHA256=generated['SHA256'])
    (HERE/'xlsx保存後照合143.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
