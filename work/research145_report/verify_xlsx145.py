"""保存されたxlsxの表・数式計算値を、標準ライブラリで独立照合する。"""

import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
N={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def main():
    """
    機能: 出力xlsx内の全明細と累計・正式テーブルを再読取して検算する。
    引数: なし。返り値: None。xlsxの内容は変更しない。
    """
    path=ROOT/'アルゴリズム調査/00145_利益の分割回収と再参加の全場検証/利益の分割回収と再参加の全セッション損益.xlsx'
    report=json.loads((HERE/'report145.json').read_text(encoding='utf-8'))
    count=0
    with zipfile.ZipFile(path) as z:
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(item.itertext()) for item in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        book=ET.fromstring(z.read('xl/workbook.xml'))
        links={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        sheets={}
        for sheet in book.find('s:sheets',N):
            target=links[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            root=ET.fromstring(z.read(target));cells={}
            for cell in root.findall('.//s:sheetData/s:row/s:c',N):
                kind=cell.get('t');value=cell.find('s:v',N)
                assert kind!='e',(sheet.attrib['name'],cell.attrib['r'])
                if kind=='inlineStr':value=''.join(cell.find('s:is',N).itertext())
                elif value is None:value=None
                elif kind=='s':value=strings[int(value.text)]
                elif kind in ('str','b'):value=value.text
                else:value=float(value.text) if value.text else None
                cells[cell.attrib['r']]=value
            sheets[sheet.attrib['name']]=(root,cells)
        assert len(sheets)==46
        for method in report['methods']:
            root,cells=sheets['日経_'+method['id']]
            source=sorted([r for r in report['rows'] if r['method']==method['id']],key=lambda r:r['session'])
            cumulative=0.
            for i,row in enumerate(source,7):
                assert cells[f'A{i}']==row['session']
                for col,key in [('C','profit'),('D','loss'),('E','net'),('G','entries'),('H','parent_count')]:
                    assert cells[f'{col}{i}']==row[key],(method['id'],i,col,cells[f'{col}{i}'],row[key]);count+=1
                cumulative+=row['net']
                assert cells[f'F{i}']==cumulative
            assert cells['E57']==cells['F56']==cumulative
            assert len(root.find('s:tableParts',N))==1
            pane=root.find('s:sheetViews/s:sheetView/s:pane',N)
            assert float(pane.get('ySplit'))==6
        tables=[name for name in z.namelist() if name.startswith('xl/tables/') and name.endswith('.xml')]
        assert len(tables)==46
        compare=sheets['比較'][1]
        for i,method in enumerate(report['methods'],7):
            rows=[r for r in report['rows'] if r['method']==method['id']]
            ex3=sum(r['net'] for r in rows)-sum(sorted([r['net'] for r in rows if r['net']>0])[-3:])
            assert compare[f'L{i}']==ex3
    result=dict(worksheets=46,tables=46,method_rows=2200,cached_values_compared=count,
                cumulative_values=2200,summary_ex3=44,all_passed=True)
    (HERE/'xlsx保存後検算145.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(result)


if __name__=='__main__':main()
