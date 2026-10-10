"""全974条件のHTMLを、保存セッション明細の独立合算と照合する。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from bs4 import BeautifulSoup

import adaptive_design as design

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'アルゴリズム調査/00033_復元方式の自動選択と改善8条件の反証'
TITLE = '復元方式の自動選択と改善8条件の反証'
sys.path.insert(0, str(HERE.parent/'wave_v36'))
source = importlib.util.spec_from_file_location('v36_report_numeric', HERE.parent/'wave_v36/report_contract_audit.py')
numeric = importlib.util.module_from_spec(source); source.loader.exec_module(numeric)


def main() -> None:
    """機能: 全金額・枚数表と全選択操作を検査する。

    引数: なし。返り値: なし (None)。報告生成器を呼ばず明細から再集計する。
    """
    fixed = numeric.read(HERE/'探索条件の固定.json')
    specs = design.catalog()+design.supplementary()
    expected = {s['id'] for s in specs}
    path = OUT/'全条件損益.html'
    soup = BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')
    methods = soup.select('section.method')
    assert len(methods) == len(expected) == 974 and {m['id'] for m in methods} == expected
    assert [m['id'] for m in methods if not m.has_attr('hidden')] == [design.PRIMARY_ID]
    select = soup.select_one('#method-filter')
    options = select.select('option')
    assert len(options) == 974 and {o['value'] for o in options} == expected
    assert [o['value'] for o in options if o.has_attr('selected')] == [design.PRIMARY_ID]
    money_tables=soup.select("table[data-id][data-symbol]")
    tables_by_key={(t["data-id"],t["data-symbol"]):t for t in money_tables}
    assert len(money_tables)==len(tables_by_key)==1948
    count = 0
    for spec in specs:
        folder = 'supplementary' if spec['role'] == 'supplementary' else ''
        rows = numeric.read(HERE/folder/'sessions'/(spec['id']+'.json.gz'))
        numeric.sessions_checked(rows, spec['id'], fixed['全セッション'])
        for symbol in ('TOPIX', 'NK225'):
            table=tables_by_key[(spec['id'],symbol)]
            count += numeric.check_money(table, numeric.money_expected(rows, fixed['全セッション'], symbol))
    assert count==33116
    scripts = [s.get_text() for s in soup.select('script') if s.get_text().strip()]
    assert len(scripts) == 1
    before = 'const ids='+json.dumps(sorted(expected))+';global.location={hash:""};const methods=ids.map(id=>({id,hidden:true}));const select={value:'+json.dumps(design.PRIMARY_ID)+',options:ids.map(value=>({value})),addEventListener(type,fn){this.fn=fn}};global.document={getElementById(id){if(id!=="method-filter")throw Error(id);return select},querySelectorAll(q){if(q!==".method")throw Error(q);return methods}};'
    after = '''for(const id of ids){select.value=id;select.fn({type:'change'});const visible=methods.filter(e=>!e.hidden);if(visible.length!==1||visible[0].id!==id)throw Error('表示不一致')}process.stdout.write(JSON.stringify({合格:true,操作数:ids.length}));'''
    result = subprocess.run(['node','-'], input=before+scripts[0]+after, text=True, encoding='utf-8', capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    ui = json.loads(result.stdout)
    assert ui['合格'] and ui['操作数'] == 974
    # ----------------------------------------
    # 比較表からの各候補リンクが、主案ではなく該当章を初期表示する。
    hash_targets=['H019__'+p+'__R1__V000' for p in design.SELECTED]
    for identifier in hash_targets:
        prefix=before.replace('global.location={hash:""}', 'global.location={hash:'+json.dumps('#'+identifier)+'}')
        suffix='const v=methods.filter(e=>!e.hidden);if(v.length!==1||v[0].id!=='+json.dumps(identifier)+')throw Error("リンク先不一致");'
        selected=subprocess.run(['node','-'],input=prefix+scripts[0]+suffix,text=True,encoding='utf-8',capture_output=True,timeout=30)
        assert selected.returncode==0,selected.stderr
    main = BeautifulSoup((OUT/(TITLE+'.html')).read_text(encoding='utf-8'), 'html.parser')
    assert '独立監査中の暫定' not in main.get_text()
    # ----------------------------------------
    # 比較表の全24行も、主章に固定した6方式の期間集計から検算する。
    identifiers=('H019__A0__R1__V000',design.PRIMARY_ID,'H019__B06_RB01_F50_N1__R1__V000',
        'H019__'+design.CLOCK_POLICY+'__R1__V000','H019__'+design.REVERSE_POLICY+'__R1__V000',
        design.PRIMARY_ID.replace('__R1__','__R0__'))
    labels=('元の数量を維持','主案：長めの逆行で使い分け','常に回復待ち','常に120秒待ち','逆の使い分け','主案・実R退出なし')
    attributed=dict(zip(identifiers,labels))
    compared = 0
    for period in ('all_symbols','symbols'):
        tables=main.select('table#main-'+period)
        assert len(tables)==1
        table=tables[0]
        printed = table.select('tbody tr')
        assert len(printed) == 12
        for line, (symbol, identifier) in zip(printed, [(s,p) for s in ('TOPIX','NK225') for p in identifiers]):
            rows = numeric.read(HERE/'sessions'/(identifier+'.json.gz'))
            names = fixed['全セッション'] if period == 'all_symbols' else fixed['後半7セッション']
            item = numeric.aggregate([r for r in rows if r['symbol']==symbol and r['session'] in names])
            cells = [c.get_text(strip=True) for c in line.select('td')]
            assert len(cells) == 9 and cells[0] == symbol and cells[1]==attributed[identifier]
            values = (item['gross_profit_yen'], -item['gross_loss_yen'], item['net_yen'],
                item['drawdown_yen'], item['money_ratio'], item['average_unit_payoff'])
            for text, value, digits in zip(cells[2:8], values, (0,0,0,0,2,2)):
                numeric.numeric(text, value, digits)
            assert cells[8] == f'{int(item["profit_units"])}/{int(item["loss_units"])}/{int(item["zero_units"])}'
            compared += 1
    assert compared==24
    # ----------------------------------------
    # 合否3項目と前回8候補の名称・旗・数値を、正式判定と独立期間集計から確認する。
    verdict=numeric.read(HERE/'独立判定.json')
    flags=main.select('[data-verdict]')
    expected_flags=('基礎候補','十四感度頑健性','分岐の利益付加価値')
    assert len(flags)==3 and {p['data-verdict'] for p in flags}==set(expected_flags)
    for flag in flags:assert flag.get_text(strip=True)==('通過' if verdict[flag['data-verdict']] else '未通過')
    eight=main.select('table#main-eight')
    assert len(eight)==1
    lines=eight[0].select('tbody tr');assert len(lines)==8
    for line,policy in zip(lines,design.SELECTED):
        identifier='H019__'+policy+'__R1__V000'
        cells=[c.get_text(strip=True) for c in line.select('td')]
        assert len(cells)==6 and cells[0]==policy
        assert cells[1]==('通過' if verdict['既選抜八条件'][policy]['基礎候補'] else '未通過')
        links=line.select('a');assert len(links)==1 and links[0]['href']=='全条件損益.html#'+identifier
        rows=numeric.read(HERE/'sessions'/(identifier+'.json.gz'))
        expected=[]
        for symbol in ('TOPIX','NK225'):
            values=numeric.aggregate([r for r in rows if r['symbol']==symbol])
            expected.extend((values['net_yen'],values['drawdown_yen']))
        for cell,value in zip(cells[2:],expected):numeric.numeric(cell,value,0)
    numeric.save(HERE/'report_contract_audit.json', dict(全合格=True, 全金額枚数行数=count, 比較行数=compared,
        表示操作=ui, 候補直接リンク数=len(hash_targets),合否表示数=3,候補表行数=8,全比較ラベル一致=True,
        HTML_SHA256={p.name:numeric.digest(p) for p in (path, OUT/(TITLE+'.html'))}))
    print(f'全{count}金額枚数行・比較{compared}行・974選択を照合。', flush=True)


if __name__ == '__main__':
    main()
