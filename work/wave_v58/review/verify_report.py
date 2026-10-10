"""原因分析の主要表・リンク・広狭画面を実Chromeで確認する。"""

from pathlib import Path
import hashlib
import importlib.util
import json
from urllib.parse import unquote

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
TASK=HERE.parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00055_補充監視が赤字になった原因'
SOURCE=OUT/'赤字の原因と理論の検証.html'
SPEC=importlib.util.spec_from_file_location('cause_browser',ROOT/'work/wave_v52/review/verify_report.py')
BROWSER=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROWSER)
BROWSER.OUT=OUT
BROWSER.VISUAL=HERE/'visual'


def number(cell: object) -> float:
    """機能: 表示上の符号と単位を除いて数値化する。

    引数: cell(HTML要素)。返り値: 表示された数値(float)。
    """
    value=cell.get_text(strip=True).replace(',','').replace('−','-').replace('%','').replace('倍','')
    return float(value)


def main() -> None:
    """機能: 主要表を元集計と照合し、実ブラウザー2画面と証跡を保存する。

    引数: なし。返り値: なし(None)。全売買とCSVの再計算はしない。
    """
    original=SOURCE.read_bytes();source=original.decode('utf8').replace('\r\n','\n');digest=hashlib.sha256(original).hexdigest()
    soup=BeautifulSoup(source,'html.parser');assert not soup.select('script')
    links=[]
    for tag in soup.select('a[href]'):
        link=tag['href']
        if link.startswith(('http','#')):continue
        assert (OUT/unquote(link.split('#')[0])).exists(),link
        links.append(link)
    assert 'README.md' in links and '../index.html' in links
    assert len([x for x in links if x.endswith('.csv')])==2
    assert SOURCE.name in (OUT/'README.md').read_text(encoding='utf8')
    assert f'{OUT.name}/{SOURCE.name}' in (OUT.parent/'index.html').read_text(encoding='utf8')
    entry=json.loads((TASK/'entry/入口固定時点の診断.json').read_text(encoding='utf8'))
    exit=json.loads((TASK/'exit/出口対照結果.json').read_text(encoding='utf8'))
    episode=json.loads((HERE/'表示回復と出来高の独立照合.json').read_text(encoding='utf8'))
    tables=soup.select('table');numbers=0
    for row in tables[0].select('tbody tr'):
        c=row.select('td');family=c[0].get_text();symbol='TOPIX' if c[1].get_text().startswith('TOPIX') else 'NK225'
        actual=next(m for m in entry['手法別'] if m['手法ID'].startswith(family+'_'))['銘柄別'][symbol]['元売買の中値会計']
        for col,key,scale,tolerance in ((2,'同値除外勝率',100,.0051),(3,'一枚平均勝ち負け比',1,.0051),(4,'損益分岐勝率',100,.0051),(5,'収支円',1,0)):
            assert abs(number(c[col])-actual[key]*scale)<=tolerance,(family,symbol,key)
            numbers+=1
    assert len(tables[0].select('tbody tr'))==6
    for row in tables[1].select('tbody tr'):
        c=row.select('td');symbol='TOPIX' if c[0].get_text().startswith('TOPIX') else 'NK225'
        assert 'ラージ' in c[0].get_text()
        a=episode['銘柄別'][symbol]
        assert number(c[1])==a['表示回復完了数'] and number(c[2])==a['周期中出来高ゼロ数']
        assert abs(number(c[3])-a['周期中出来高既知でゼロの割合']*100)<=.0051;numbers+=3
    for row in tables[2].select('tbody tr'):
        c=row.select('td');family=c[0].get_text();symbol='TOPIX' if c[1].get_text().startswith('TOPIX') else 'NK225'
        a=next(m for m in entry['手法別'] if m['手法ID'].startswith(family+'_'))['銘柄別'][symbol]['固定時点別']
        for j,seconds in enumerate(('60','300','900','1800')):
            assert abs(number(c[j+2].select_one('strong'))-a[seconds]['呼値']['entry加重平均'])<=.00051
            percentage=float(c[j+2].select_one('small').get_text().replace('有効','').replace('%','').strip())
            assert abs(percentage-a[seconds]['有効率']*100)<=.051;numbers+=2
    summary=next(t for t in tables if 'TOPIX利益円' in t.select_one('thead').get_text())
    assert len(summary.select('tbody tr'))==12
    for row in summary.select('tbody tr'):
        c=row.select('td');m=next(m for m in exit['methods'] if m['id']==c[0].get_text())
        for j,symbol in enumerate(('TOPIX','NK225')):
            for k,field in enumerate(('profit','loss','net')):
                assert number(c[2+j*3+k])==m['summary'][symbol][field];numbers+=1
    BROWSER.PROBE=r'''<script>
try{
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義');
 document.body.dataset.check=JSON.stringify({全合格:true,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.body).backgroundColor});
}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''
    screens=[BROWSER.render(source,'広幅',1500,1600),BROWSER.render(source,'狭幅',520,1600)]
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==digest
    result=dict(全合格=True,主要表数値照合数=numbers,ローカルリンク数=len(links),CSVリンク数=2,
                READMEとindexの往復案内=True,JavaScriptなし=True,HTML_SHA256=digest,目視確認=False,画面=screens)
    (HERE/'HTML表示の独立検査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
