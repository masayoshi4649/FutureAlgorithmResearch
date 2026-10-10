"""公開HTMLの全切替・表示金額・売買マーカーをブラウザで独立検査する。"""

import importlib.util
import json
from pathlib import Path

from bs4 import BeautifulSoup

import report

HERE = Path(__file__).resolve().parent
SOURCE = report.OUT / 'E01と改修の説明と全セッション損益.html'
PROBE = r'''<script>
/**
 * 全表示の金額とマーカーを保存会計へ照合する。
 * @returns {object} 検査結果。
 */
function verifyAll(){let views=0,charts=0,markers=0,numbers=0;
 const number=td=>Number(td.textContent.replaceAll(',','').replace('円',''));
 for(const model of ['specified','observed'])for(const v of D.条件)for(const symbol of ['TOPIX','NK225']){
  $('model').value=model;$('method').value=v.id;$('symbol').value=symbol;render();
  const result=D.結果[model][v.id],expected=result.rows.filter(r=>r.symbol===symbol),rows=$('sessions').querySelector('tbody').rows;
  if(rows.length!==29||expected.length!==28)throw Error('場数');
  for(let i=0;i<28;i++){const r=rows[i],a=expected[i];
   for(const [col,field,mult]of [[1,'profit',1],[2,'loss',-1],[3,'net',1],[4,'fees',1]]){
    if(number(r.cells[col])!==Math.round(a[field]*mult))throw Error(`金額 ${v.id} ${symbol} ${a.session} ${field}`);numbers++;
   }
   if(r.cells[5].textContent!==`${a.winning_lots} / ${a.losing_lots}`)throw Error('枚数');
  }
  for(const session of D.固定.全セッション){$('session').value=session;draw();const key=session+'|'+symbol,orders=result.orders[key],svg=$('price-chart').querySelector('svg');
   if(!svg||/NaN|undefined|Infinity/.test(svg.outerHTML))throw Error('無効図');
   if(svg.querySelectorAll('circle').length!==orders.filter(o=>o[7]===1).length)throw Error('新規点');
   if(svg.querySelectorAll('path').length!==orders.filter(o=>o[7]===0).length)throw Error('返済点');
   if($('orders').querySelector('tbody').rows.length!==orders.length)throw Error('注文表');
   markers+=orders.length;charts++;
  }
  views++;
 }
 $('model').value='observed';$('method').value='E01';$('symbol').value='TOPIX';$('session').value=D.固定.全セッション.at(-1);render();
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('文書の横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,表示切替:views,売買図:charts,売買点:markers,金額:numbers,背景:getComputedStyle(document.documentElement).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(verifyAll());}catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e),stack:e.stack});}
</script>'''


def main() -> None:
    """機能: 広い画面と狭い画面で全表示を検査し、図の画像も保存する。

    引数: なし。返り値: なし(None)。
    """
    path = report.ROOT / 'work/wave_v52/review/verify_report.py'
    spec = importlib.util.spec_from_file_location('e01_browser_helper', path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.OUT = report.OUT
    helper.VISUAL = HERE / 'visual'
    helper.PROBE = PROBE
    source = SOURCE.read_text(encoding='utf8')
    output = [helper.render(source, '全体', 1500, 1350), helper.render(source, '狭幅', 520, 1250),
        helper.render(source, '売買図', 1500, 900,
            '<script>const s=document.querySelector("#price-chart").closest("section");document.querySelector("main").replaceChildren(s);</script>')]
    links = []
    for file in (SOURCE, report.OUT / '全16改修条件.html'):
        soup = BeautifulSoup(file.read_text(encoding='utf8'), 'html.parser')
        for tag in soup.select('a[href]'):
            href = tag['href']
            if href.startswith(('http', '#')):
                continue
            target = (file.parent / href).resolve()
            assert target.exists(), target
            links.append(str(target))
    result = dict(全合格=True, 画面=output, リンク=len(links), 目視確認=False)
    (HERE / 'HTML表示の独立検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
