"""価格形成の静的HTMLを実Chromeで開き、数字・リンク・暗色の可読性を確認する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
TASK=HERE.parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00053_価格が動く理由と板データの再点検'
SOURCE=OUT/'価格が動く理由と板データ.html'
SPEC=importlib.util.spec_from_file_location('static_report_browser',ROOT/'work/wave_v52/review/verify_report.py')
BROWSER=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROWSER)
BROWSER.OUT=OUT
BROWSER.VISUAL=HERE/'visual'


def main() -> None:
    """機能: 完成HTMLと診断数値を照合し、広狭画面と詳細表示を保存する。

    引数: なし。返り値: なし(None)。元HTMLを変更せず複製だけをブラウザーへ渡す。
    """
    original=SOURCE.read_bytes();source=original.decode('utf-8').replace('\r\n','\n')
    digest=hashlib.sha256(original).hexdigest()
    soup=BeautifulSoup(source,'html.parser')
    assert not soup.select('script')
    assert not any(token in source for token in ('__AUDIT__','__QUOTE_ROWS__','__ENTRY_ROWS__'))
    links=0
    for tag in soup.select('a[href],img[src]'):
        link=tag.get('href',tag.get('src'))
        if link.startswith(('http','#')):
            continue
        target=OUT/unquote(link.split('#')[0].split('?')[0])
        assert target.exists(),target
        links+=1
    book=json.loads((TASK/'diagnosis/板の観測可能性.json').read_text(encoding='utf-8'))
    trades=json.loads((TASK/'diagnosis/入口途中出口の診断.json').read_text(encoding='utf-8'))
    candidate=next(m for m in trades['手法別'] if m['手法ID']=='P03_W05')
    tables=soup.select('#details table.data')
    numbers=0
    for row in tables[0].select('tbody tr'):
        cells=[c.get_text(strip=True) for c in row.select('td')]
        item=book['気配と最終価格の比較'][cells[0]]
        assert int(cells[1].replace(',',''))==item['最終価格変化数']
        assert int(cells[2].replace(',',''))==item['最終価格変化で両最良気配不変数']
        assert cells[3]==f"{100*item['最終価格変化中の両最良気配不変割合']:.1f}%"
        numbers+=3
    entry_table=next(table for table in tables if '順行が先' in table.get_text())
    for row in entry_table.select('tbody tr'):
        cells=[c.get_text(strip=True) for c in row.select('td')]
        item=candidate['銘柄別'][cells[0]]['全体'];parts=item['1W先着内訳']
        assert [int(c.replace(',','')) for c in cells[1:]]==[item['組数'],parts['順行先着'],parts['逆行先着'],parts['双方未観測']]
        numbers+=4
    display=json.loads((TASK/'measurement/表示範囲補正とOFIの全数監査.json').read_text(encoding='utf-8'))
    display_table=next(table for table in tables if '最良買い板の消失量' in table.get_text())
    for row in display_table.select('tbody tr'):
        cells=[c.get_text(strip=True) for c in row.select('td')]
        item=display['銘柄別'][cells[0]]['全比較']
        assert [int(c.replace(',','')) for c in cells[1:]]==[item['bid_best_disappeared'],item['ask_best_disappeared']]
        numbers+=2
    audit=json.loads((HERE/'レポート追記.json').read_text(encoding='utf-8'))
    assert audit['status'] in soup.get_text()
    for sentence in audit['items']:
        assert sentence in soup.get_text(),sentence
    BROWSER.PROBE=r'''<script>
/**
 * 機能: 静的画面の幅、未置換値、背景を検査する。
 * @returns {object} 画面の検査結果。
 */
function inspect(){
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__AUDIT__|__QUOTE_ROWS__|__ENTRY_ROWS__/.test(document.body.innerText))throw Error('未置換値');
 return {全合格:true,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,
         背景:getComputedStyle(document.documentElement).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(inspect());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''
    screens=[BROWSER.render(source,'原理の全体',1500,1550),BROWSER.render(source,'狭幅',520,1550),
             BROWSER.render(source,'点検結果',1500,1550,'<script>document.querySelector("main").replaceChildren(document.querySelector("#details"));document.querySelectorAll("details").forEach(x=>x.open=true);window.scrollTo(0,0);</script>')]
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==digest,'検査中に原本HTMLが変更された'
    result=dict(全合格=True,静的リンク数=links,診断数値照合数=numbers,監査短文照合数=len(audit['items']),
                元HTMLのスクリプト数=0,目視確認=False,HTML_SHA256=digest,画面=screens)
    (HERE/'HTML表示の独立検査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
