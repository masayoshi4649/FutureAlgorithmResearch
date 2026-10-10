"""主12条件の全表示と全336条件の会計をブラウザで検算する。"""

import importlib.util
import json
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup

import study


HERE=Path(__file__).resolve().parent
OUT=study.OUT


def number(text: str) -> float:
    """機能: 表示金額を数値へ変換する。

    引数: text(str)。返り値: 数値(float)。
    """
    return float(text.replace(',',''))


def main() -> None:
    """機能: 12条件×2商品×25場と現況を照合し暗色表示を確認する。

    引数: なし。返り値: なし(None)。ブラウザの外部通信は遮断する。
    """
    source=(OUT/'急傾斜の説明とセッション損益.html').read_text(encoding='utf-8')
    soup=BeautifulSoup(source,'html.parser')
    assert all((OUT/unquote(a['href'])).exists() for a in soup.select('a[href]'))
    all_source=(OUT/'全336条件.html').read_text(encoding='utf-8')
    all_soup=BeautifulSoup(all_source,'html.parser')
    methods=json.loads((OUT/'全336条件の会計.json').read_text(encoding='utf-8'))['methods']
    rows=all_soup.select('tbody tr')
    assert len(rows)==len(methods)==336
    for row,m in zip(rows,methods):
        cells=row.find_all('td')
        assert cells[0].text==m['id']
        for column,symbol,key in ((3,'TOPIX','net'),(4,'TOPIX','fees'),(6,'NK225','net'),(7,'NK225','fees')):
            assert number(cells[column].text)==m['summary'][symbol][key]
        for symbol in ('TOPIX','NK225'):
            accounts=[a for a in m['accounts'] if a['symbol']==symbol]
            assert len(accounts)==25
            assert sum(a['net'] for a in accounts)==m['summary'][symbol]['net']
    # ----------------------------------------
    # 実際のDOMを全選択へ切り替え、表示金額を独立に読み取る。
    spec=importlib.util.spec_from_file_location('既存描画器',HERE.parent/'wave_v52/review/verify_report.py')
    renderer=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT=OUT;renderer.VISUAL=HERE/'visual'
    renderer.PROBE=r'''<script>
/**
 * 機能: 全主条件と商品を選び、DOMの金額・枚数・割合を保存会計へ照合する。
 * @returns {object} 表示照合の件数。
 */
function verifyReport(){
 let views=0,amounts=0,sessions=0;
 const num=t=>Number(t.replaceAll(',',''));
 const compare=(cells,column,expected)=>{if(num(cells[column].textContent)!==expected)throw Error('表示金額:'+column);amounts++;};
 const fixed=v=>(v*100).toFixed(2)+'%';
 for(const m of data.methods){
  document.getElementById('method').value=m.id;
  for(const symbol of ['NK225','TOPIX']){
   document.getElementById('symbol').value=symbol;render();
   const rule=`損切り${fixed(m.exit.stop)}、順行${fixed(m.exit.arm)}で追跡開始、追跡幅${fixed(m.exit.trail)}、最初の利益条件線${fixed(m.exit.floor)}。`;
   if(document.getElementById('rule').textContent!==rule)throw Error('注文割合');
   const totals=document.querySelectorAll('#totals tbody tr');
   for(let i=0;i<2;i++){
    const s=['NK225','TOPIX'][i],a=m.summary[s],cells=totals[i].cells;
    for(const [column,key] of [[3,'profit'],[4,'loss'],[5,'net'],[6,'fees']])compare(cells,column,a[key]);
    if(cells[1].textContent!==`${a.wins}/${a.losses}`||cells[7].textContent!==`${a.win_qty}/${a.loss_qty}`)throw Error('合計枚数');
    const scores=document.querySelectorAll('#scores tbody tr')[i].cells,b=m.mid_score[s],q=m.score[s];
    compare(scores,1,q.n);
    for(const [column,value] of [[2,b.labels['0.10'].target_rate],[3,b.labels['0.10'].first_rate],[4,q.labels['0.10'].target_rate],[5,q.labels['0.10'].first_rate]]){
     if(scores[column].textContent!== (value===null?'—':(value*100).toFixed(1)+'%'))throw Error('方向率');
    }
   }
   const expected=m.accounts.filter(a=>a.symbol===symbol),actual=document.querySelectorAll('#sessions tbody tr');
   if(actual.length!==25||expected.length!==25)throw Error('全場数');
   for(let i=0;i<25;i++){
    const a=expected[i],cells=actual[i].cells;
    if(cells[0].textContent!==a.session)throw Error('場名');
    for(const [column,key] of [[1,'profit'],[2,'loss'],[3,'net'],[4,'fees']])compare(cells,column,a[key]);
    if(cells[5].textContent!==`${a.wins}/${a.losses}`||cells[6].textContent!==`${a.win_qty}/${a.loss_qty}`||num(cells[7].textContent)!==a.win_qty-a.loss_qty)throw Error('枚数');
    sessions++;
   }
   const weeks=document.querySelectorAll('#weeks tbody tr');
   for(let i=0;i<3;i++)for(const [column,key] of [[1,'profit'],[2,'loss'],[3,'net']])compare(weeks[i].cells,column,m.weeks[symbol][i][key]);
   const fresh=data.live.filter(a=>a.id===m.id),current=document.querySelectorAll('#current tbody tr');
   if(fresh.length!==2||current.length!==2)throw Error('現況商品数');
   for(let i=0;i<2;i++){
    const a=fresh[i],cells=current[i].cells;
    for(const [column,key]of[[2,'gross'],[3,'fees'],[4,'unrealized'],[5,'net']])compare(cells,column,a[key]);
    if(cells[6].textContent!==`${a.long_qty}/${a.short_qty}`)throw Error('未返済枚数');
   }
   views++;
  }
 }
 document.getElementById('method').value='RAW_ACCEL_S060_V050_広幅_順';document.getElementById('symbol').value='NK225';render();
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面全体横溢れ');
 if(document.querySelectorAll('svg circle').length!==6)throw Error('売買マーカー');
 if(/NaN|Infinity|undefined/.test(document.body.innerText))throw Error('未定義');
 if(getComputedStyle(document.body).backgroundColor!=='rgb(12, 20, 32)')throw Error('背景');
 return {全合格:true,表示条件商品数:views,場表示数:sessions,数値照合数:amounts,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth};
}
try{document.body.dataset.check=JSON.stringify(verifyReport());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''
    chart_source=source.replace('</head>','<style>main>p,main>h1,main>section,main>details{display:none}main>section:nth-of-type(3){display:block}</style></head>')
    views=[renderer.render(source,'広幅',1500,1380),renderer.render(source,'狭幅',520,1250),renderer.render(chart_source,'急加速売買図',1500,1180)]
    study.save(OUT/'表示検査.json',dict(全合格=True,全条件照合=336,画面=views))
    study.save(HERE/'表示検査.json',dict(全合格=True,全条件照合=336,画面=views))
    print('全336会計と主12条件の全表示・暗色グラフを確認しました')


if __name__=='__main__':
    main()
