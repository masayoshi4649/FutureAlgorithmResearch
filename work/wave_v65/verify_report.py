"""全25場・週・12条件のHTML表示金額を独立集計と照合する。"""

import importlib.util
import json
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup

import replay


HERE=Path(__file__).resolve().parent
OUT=replay.OUT


def number(text: str) -> float:
    """機能: 表示された数値を読み取る。

    引数: text(str)。返り値: 数値(float)。
    """
    return float(text.replace(',',''))


def main() -> None:
    """機能: 静的会計表と暗色画面を広幅・狭幅で検査する。

    引数: なし。返り値: なし(None)。ブラウザの外部通信は遮断する。
    """
    packet=json.loads((HERE/'結果.json').read_text(encoding='utf-8'))
    main_method=packet['methods'][0]
    source=(OUT/'候補3の全力新規とトレール損益.html').read_text(encoding='utf-8')
    soup=BeautifulSoup(source,'html.parser')
    checked=0
    for symbol in ('TOPIX','NK225'):
        actual=soup.select(f'table[data-accounts="{symbol}"] tbody tr')
        expected=[a for a in main_method['accounts'] if a['symbol']==symbol]
        assert len(actual)==len(expected)==25
        for row,a in zip(actual,expected):
            cells=row.find_all('td')
            assert cells[0].text==a['session']
            for i,key in ((1,'profit'),(2,'loss'),(3,'net'),(4,'fees')):
                assert number(cells[i].text)==a[key]
                checked+=1
            assert cells[5].text==f'{a["wins"]} / {a["losses"]}'
            assert cells[6].text==f'{a["win_qty"]} / {a["loss_qty"]}'
            assert a['profit']-a['loss']==a['net']
        rows=[r for r in main_method['rows'] if r['symbol']==symbol]
        assert sum(a['net'] for a in expected)==sum(r['net'] for r in rows)==main_method['summary'][symbol]['net']
    variants=soup.select('#variants tbody tr')
    assert len(variants)==12
    for row,m in zip(variants,packet['methods']):
        cells=row.find_all('td')
        assert number(cells[4].text)==m['summary']['NK225']['net']
        assert number(cells[7].text)==m['summary']['TOPIX']['net']
        checked+=2
    assert len(soup.select('#ledger tbody tr'))==23
    assert len(soup.select('svg'))==2
    assert all((OUT/unquote(a['href'])).exists() for a in soup.select('a[href]'))
    # ----------------------------------------
    # 保存資料をheadless Chromeで表示し、幅とダークテーマとSVGを確認する。
    spec=importlib.util.spec_from_file_location('過去描画器',HERE.parent/'wave_v52/review/verify_report.py')
    renderer=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT=OUT
    renderer.VISUAL=HERE/'visual'
    renderer.PROBE='''<script>
/**
 * 機能: 画面幅、暗色背景、表と売買図の表示を確認する。
 * @returns {object} 画面検査の結果。
 */
function verifyView(){
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面全体の横溢れ');
 if(document.querySelectorAll('table[data-accounts] tbody tr').length!==50)throw Error('全場行数');
 if(document.querySelectorAll('#variants tbody tr').length!==12)throw Error('条件数');
 if(document.querySelectorAll('svg circle').length!==4)throw Error('売買マーカー数');
 if(/NaN|undefined|Infinity/.test(document.body.innerText))throw Error('未定義表示');
 const color=getComputedStyle(document.body).backgroundColor;
 if(color!=='rgb(12, 20, 32)')throw Error('暗色背景');
 return {全合格:true,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:color};
}
try{document.body.dataset.check=JSON.stringify(verifyView());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''
    chart_source=source.replace('</head>','<style>main>p,main>h1,main>section,main>details{display:none}main>section:nth-of-type(4){display:block}</style></head>')
    views=[renderer.render(source,'広幅',1500,1350),renderer.render(source,'狭幅',520,1250),
        renderer.render(chart_source,'売買図',1500,1050)]
    proof=dict(全合格=True,表示金額照合数=checked,セッション数=25,全条件数=12,画面=views)
    replay.save(HERE/'表示検査.json',proof)
    replay.save(OUT/'表示検査.json',proof)
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    main()
