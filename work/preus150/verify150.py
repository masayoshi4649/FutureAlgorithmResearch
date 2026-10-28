"""保存xlsxの各会計値、数式キャッシュ、正式テーブルを読取検算する。"""

import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}


def main() -> None:
    """公開xlsxを原会計と直接照合する。

    引数: なし。
    返り値: None。検算JSONを保存し、書換えは行わない。
    """
    filename='D07の積極性と全夜間損益.xlsx'
    path=ROOT/'アルゴリズム調査/00150_D07の米国前しきい値緩和と開始前リセット'/filename
    copy=ROOT/'outputs/00150_preus_activity'/filename
    assert path.read_bytes()==copy.read_bytes()
    report=json.loads((HERE/'report150.json').read_text('utf-8'))
    checked=0
    with zipfile.ZipFile(path) as z:
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        targets={r.attrib['Id']:r.attrib['Target'] for r in rels}
        sheets={}
        for sheet in wb.find('m:sheets',NS):
            target=targets[sheet.attrib[f'{{{NS["r"]}}}id']]
            target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            tree=ET.fromstring(z.read(target))
            cells={c.attrib['r']:c for c in tree.findall('.//m:sheetData/m:row/m:c',NS)}
            assert not [c for c in cells.values() if c.attrib.get('t')=='e']
            sheets[sheet.attrib['name']]=cells
        assert len(sheets)==len(report['methods'])+3
        tables=[n for n in z.namelist() if n.startswith('xl/tables/') and n.endswith('.xml')]
        assert len(tables)==len(sheets)
        names=[]
        for name in tables:
            table=ET.fromstring(z.read(name))
            names.append(table.attrib['displayName'])
            assert table.find('m:autoFilter',NS) is not None
        assert len(set(names))==len(names)

        # ----------------------------------------
        # 各会計セルを、Excel式とは別の原JSON計算で検算する。
        def check(sheet: str,cell: str,expected: float) -> None:
            """保存値を原会計と比較する。

            引数: sheet,cell (str): 所在。expected (float): 原会計値。
            返り値: None。不一致なら検算を停止する。
            """
            nonlocal checked
            c=sheets[sheet][cell]
            value=c.find('m:v',NS)
            assert value is not None,(sheet,cell,'値なし')
            actual=float(value.text)
            assert math.isclose(actual,expected,abs_tol=0.0001),(sheet,cell,actual,expected)
            checked+=1

        methods=list(report['methods'])
        a00=next(m for m in methods if m['id']=='A00');baseline=sum(r['pre']['net'] for r in a00['rows'])
        for method_index,method in enumerate(methods):
            sheet='日経_'+method['id']
            rows=sorted(method['rows'],key=lambda r:r['session'])
            cumulative=0
            for index,row in enumerate(rows,7):
                cumulative+=row['net']
                values={'B':row['pre']['profit'],'C':row['pre']['loss'],'D':row['pre']['net'],
                        'E':row['post']['profit'],'F':row['post']['loss'],'G':row['post']['net'],
                        'H':row['profit'],'I':row['loss'],'J':row['net'],'K':cumulative,
                        'L':row['entries'],'M':row['pre']['entries'],'N':row['post']['entries'],'O':row['max_per_side'],'P':row['pre_activity']['holding_ratio'],'Q':row['pre_activity']['average_quantity']}
                for col,value in values.items(): check(sheet,f'{col}{index}',value)
                delay=row['pre_activity']['first_entry_delay_minutes']
                if delay is not None: check(sheet,f'R{index}',delay)
                for col in ('D','G','H','I','J','K'):
                    assert sheets[sheet][f'{col}{index}'].find('m:f',NS) is not None
            for col,key in [('H','profit'),('I','loss'),('J','net'),('L','entries')]:
                check(sheet,f'{col}32',sum(r[key] for r in rows))
            check(sheet,'K32',cumulative)
            check(sheet,'P32',method['pre_activity']['mean_holding_ratio'])
            check(sheet,'Q32',method['pre_activity']['mean_quantity'])
            if method['pre_activity']['median_first_entry_minutes'] is not None:
                check(sheet,'R32',method['pre_activity']['median_first_entry_minutes'])
            summary=method['summary']; n=method_index+7
            values={'B':sum(r['pre']['net'] for r in rows),'C':sum(r['post']['net'] for r in rows),
                    'D':summary['net'],'E':summary['profit'],'F':summary['loss'],'H':summary['wins'],
                    'I':summary['losses'],'J':summary['maxloss'],'K':summary['ex3'],'L':method['pre']['entries'],
                    'M':method['pre_activity']['participating_nights'],'N':method['pre_activity']['mean_holding_ratio'],
                    'O':method['pre_activity']['mean_quantity'],'P':summary['entries'],'Q':method['pre']['net']-baseline}
            if summary['loss']: values['G']=summary['profit']/summary['loss']
            for col,value in values.items(): check('比較',f'{col}{n}',value)
        for index,row in enumerate(sorted(report['partial'],key=lambda r:r['id']),7):
            for col,key in [('B','net'),('C','unrealized'),('D','equity'),('E','entries'),('F','max_per_side')]:
                check('当夜途中',f'{col}{index}',row[key])
        # ----------------------------------------
        # 時計窓の観測値も固定した記述統計から照合し、金融損益とは別表に保つ。
        clocks=json.loads((HERE/'data/時刻前後の市場診断150.json').read_text('utf-8'))
        calendar=json.loads((HERE/'data/現物営業日21場の参考診断150.json').read_text('utf-8'))
        observations=[]
        for source in (clocks['groups']['デイ'],calendar['comparisons'],clocks['groups']['ナイト']):
            for metric in ('abs_change_mean','range_mid','spread_p90','jump_50_rate','jump_100_rate','jump_200_rate'):
                observations.append(source['開始後15分対次15分']['metrics'][metric])
        observations.append(clocks['groups']['ナイト']['直前15分対開始後15分']['metrics']['abs_change_mean'])
        observations.append(clocks['groups']['ナイト']['イベント対直後30分']['metrics']['abs_change_mean'])
        for index,item in enumerate(observations,7):
            values={'E':item['n'],'F':item['event_mean'],'G':item['control_mean'],
                    'H':item['event_mean']-item['control_mean'],
                    'I':item['mean_difference_ci95'][0],'J':item['mean_difference_ci95'][1]}
            for col,value in values.items(): check('時刻観測',f'{col}{index}',value)
            assert sheets['時刻観測'][f'H{index}'].find('m:f',NS) is not None
        assert len(list((HERE/'xlsx_checks').glob('*.png')))==len(sheets)
    result=dict(all_checks_passed=True,checked_numeric_cells=checked,sheets=len(sheets),
                tables=len(tables),formal_filter_tables=True,native_formula_cells_present=True,
                formula_errors=0,public_copy_identical=True,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),output=str(path))
    (HERE/'xlsx_checks/保存xlsxの独立検算.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='output'},ensure_ascii=False))


if __name__=='__main__':
    main()
