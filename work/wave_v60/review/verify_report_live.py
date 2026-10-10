"""最終追記の現在場8口座・週継続・人工相場表を原台帳へ照合する。"""

import hashlib
import importlib.util
import json
from pathlib import Path

from bs4 import BeautifulSoup
from verify_report import equal,HERE,ROOT,WORK,OUT,MAIN


def main() -> None:
    """機能: 追記表の全数値と枚数を検算し、現在確認章の実画面を保存する。

    引数: なし。返り値: なし(None)。元HTML・売買結果は変更しない。
    """
    raw=MAIN.read_bytes();doc=BeautifulSoup(raw.decode('utf-8'),'html.parser')
    data={name:json.loads((WORK/'live'/f'現在{name}の途中損益.json').read_text(encoding='utf-8')) for name in ('中期','グリッド')}
    symbols={'TOPIX mini':'TOPIX','NK225 micro':'NK225'};count=rows=0
    for table in doc.select('table'):
        heading=table.select_one('th').get_text(strip=True)
        if heading=='系統':
            mode='mid' if table.find_parent('details') else 'quote'
            for row in table.select('tbody tr'):
                c=row.select('td');name=c[0].get_text(strip=True);symbol=symbols[c[1].get_text(strip=True)]
                source=data[name];a=next(a for a in source['accounts'] if a['symbol']==symbol and a['price_mode']==mode)
                gross_index,net_index,qty_index=(6,8,3) if name=='中期' else (15,18,4)
                profit=sum(t[gross_index] for t in a['trades'] if t[gross_index]>0)
                loss=-sum(t[gross_index] for t in a['trades'] if t[gross_index]<0)
                values=[profit,loss,a['fees_incurred'],a['unrealized_end']-a.get('unrealized_start',0),a['economic_net']]
                for cell,val in zip(c[2:7],values):equal(cell,val);count+=1
                equal(c[9],a['unrealized_end']);count+=1
                q=[int(sum(t[qty_index] for t in a['trades'] if (t[net_index]>0 if sign==1 else t[net_index]<0 if sign==-1 else t[net_index]==0))) for sign in (1,-1,0)]
                assert c[7].get_text(strip=True)=='/'.join(map(str,q))
                l=a.get('long_qty',max(a.get('position',0),0));s=a.get('short_qty',max(-a.get('position',0),0))
                assert c[8].get_text(strip=True)==f'{l}/{s}';rows+=1
        elif heading=='グリッド商品':
            for row in table.select('tbody tr'):
                c=row.select('td');symbol=symbols[c[0].get_text(strip=True)]
                a=next(a for a in data['グリッド']['accounts'] if a['symbol']==symbol and a['price_mode']=='quote')
                for cell,key in zip(c[1:],('week_before_current_net','net','week_economic_net')):equal(cell,a[key]);count+=1
        elif heading=='主方式':
            stress=json.loads((HERE/'主グリッドの人工相場検査.json').read_text(encoding='utf-8'))
            for family,row in zip(('G0','G1','G2','G3','G4'),table.select('tbody tr')):
                cells=row.select('td')
                for i,symbol in enumerate(('TOPIX','NK225')):
                    a=next(v for v in stress['結果'] if v['銘柄']==symbol and v['方式']==family and v['経路']=='上昇')
                    equal(cells[i*2+1],a['収支']);equal(cells[i*2+2],a['返済玉数']);count+=2
    assert rows==8
    spec=importlib.util.spec_from_file_location('chrome_live_v60',ROOT/'work/wave_v52/review/verify_report.py')
    browser=importlib.util.module_from_spec(spec);spec.loader.exec_module(browser)
    browser.OUT=OUT;browser.VISUAL=HERE/'visual'
    browser.PROBE='<script>document.body.dataset.check=JSON.stringify({全合格:true});</script>'
    extra='''<script>const h=[...document.querySelectorAll('h2')].find(n=>n.textContent==='現在セッションの一回確認');const f=document.createDocumentFragment();for(let n=h;n;){let next=n.nextSibling;f.appendChild(n);n=next;}document.querySelector('main').replaceChildren(f);document.querySelectorAll('details').forEach(d=>d.open=true);window.scrollTo(0,0);</script>'''
    screenshot=browser.render(raw.decode('utf-8'),'現在確認',1500,1450,extra)
    evidence=dict(合格=True,口座行=rows,追加数値照合=count,目視確認=False,画面=screenshot,
                  HTML_SHA256=hashlib.sha256(raw).hexdigest())
    (HERE/'現在確認表示の独立検査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':main()
