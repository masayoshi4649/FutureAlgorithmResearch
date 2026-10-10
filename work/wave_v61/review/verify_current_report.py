"""現在一回確認の表示表・全境界CSV・案内リンクを独立確認する。"""

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

import verify_report as common

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
LIVE=WORK/'live'
OUT=common.OUT


def main() -> None:
    """機能: 既知境界・現在残玉・追加区間の表示を元結果に照合し画面を保存する。

    引数: なし。返り値: なし(None)。既存HTML・原本を書き換えない。
    """
    source=common.MAIN.read_text(encoding='utf-8')
    doc=BeautifulSoup(source,'html.parser')
    accounts={}
    for filename in ('現在方向性の途中損益.json','現在在庫の途中損益.json'):
        result=json.loads((LIVE/filename).read_text(encoding='utf-8'))
        for a in result['accounts']:accounts[(result['選定候補']['id'],a['symbol'],a['price_mode'])]=a
    numbers=0;rows=0
    table=next(t for t in doc.select('table') if t.select_one('th').get_text(strip=True)=='固定条件')
    for row in table.select('tbody tr'):
        cells=row.select('td');condition=cells[0].get_text(strip=True);symbol=common.SYMBOLS[cells[1].get_text(strip=True)]
        a=accounts[(condition,symbol,'quote')];end=a['現在末尾']
        expected=[a['既知境界']['net'],end['gross_realized'],end['fees'],end['unrealized'],end['net'],a['追加区間']['net']]
        for cell,value in zip(cells[2:8],expected):common.equal(cell,value);numbers+=1
        assert cells[8].get_text(strip=True)==f'買{end["long_qty"]} / 売{end["short_qty"]}'
        rows+=1
    assert rows==4
    seen=set()
    with (OUT/'現在確認の途中会計.csv').open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            key=(row['条件ID'],row['銘柄'],row['価格仮定']);a=accounts[key];phase=row['区間'];state=a[phase]
            assert a['session']==row['セッション']
            assert (*key,phase) not in seen;seen.add((*key,phase))
            for label,field in [('実現粗損益円','gross_realized'),('発生手数料円','fees'),
                                ('含み損益または変化円','unrealized'),('費用含み込み純収支または変化円','net')]:
                assert abs(float(row[label])-state[field])<1e-6;numbers+=1
            qty=a['現在末尾'] if phase=='追加区間' else state
            assert int(row['末尾買枚数'])==qty['long_qty'] and int(row['末尾売枚数'])==qty['short_qty']
    assert len(seen)==24
    links=0
    for path in (OUT/'README.md',):
        for label,url in re.findall(r'\[([^\]]+)\]\(([^)]+)\)',path.read_text(encoding='utf-8')):
            if url.startswith(('http:','https:')):continue
            assert (path.parent/unquote(url.split('#')[0])).exists(),url;links+=1
    index=BeautifulSoup((OUT.parent/'index.html').read_text(encoding='utf-8'),'html.parser')
    listed=[a['href'] for a in index.select('a[href]') if OUT.name in unquote(a['href'])]
    assert listed
    for url in listed:assert (OUT.parent/unquote(url.split('#')[0])).exists(),url;links+=1
    rootread=(OUT.parent/'README.md').read_text(encoding='utf-8');assert OUT.name in rootread
    spec=importlib.util.spec_from_file_location('現在描画',common.ROOT/'work/wave_v52/review/verify_report.py')
    browser=importlib.util.module_from_spec(spec);spec.loader.exec_module(browser)
    browser.OUT=OUT;browser.VISUAL=HERE/'visual'
    browser.PROBE='''<script>document.body.dataset.check=JSON.stringify({全合格:document.documentElement.scrollWidth<=innerWidth+2,幅:innerWidth,文書幅:document.documentElement.scrollWidth});</script>'''
    scroll='''<script>const target=Array.from(document.querySelectorAll('h2')).find(e=>e.textContent==='現在セッションの一回確認');for(let p=target.previousElementSibling;p;p=p.previousElementSibling)p.style.display='none';window.scrollTo(0,0);</script>'''
    screens=[browser.render(source,'現在確認',1500,1600,scroll),browser.render(source,'現在確認狭幅',520,1600,scroll)]
    evidence=dict(合格=True,目視確認=False,主評価表行=rows,全境界CSV行=len(seen),数値照合=numbers,
                  読む順序と一覧リンク=links,画面=screens,主HTML_SHA256=hashlib.sha256(common.MAIN.read_bytes()).hexdigest())
    (HERE/'現在確認表示の独立検査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
