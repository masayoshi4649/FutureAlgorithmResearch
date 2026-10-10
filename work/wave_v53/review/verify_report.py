"""作業00050を実Chromeで表示し、全選択と保存数値を独立照合する。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00050_一般的な分析と板確認と損益管理'
SOURCE=OUT/'一般的な分析と損益管理の検証.html'
SPEC=importlib.util.spec_from_file_location('old_browser_renderer',HERE.parent.parent/'wave_v52/review/verify_report.py')
BROWSER=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROWSER)
BROWSER.OUT=OUT
BROWSER.VISUAL=HERE/'visual'

PROBE=r'''<script>
/**
 * 機能: 全手法・商品・場の表示金額と注文点を保存データに照合する。
 * @returns {object} 検査件数と画面品質。
 */
function verifyAll(){
 let views=0,accounts=0,numbers=0,markers=0;
 const number=cell=>Number(cell.textContent.replaceAll(',','').trim());
 for(const method of RESULT.methods){
  el('method').value=method.id;
  for(const symbol of ['TOPIX','NK225']){
   el('symbol').value=symbol;render();
   const group=method.accounts.filter(a=>a.symbol===symbol).sort((a,b)=>a.session.localeCompare(b.session));
   const rows=el('sessions').querySelector('tbody').rows;
   if(rows.length!==23||group.length!==23)throw Error('場数');
   for(let i=0;i<rows.length;i++){
    const a=group[i],r=rows[i];
    if(r.cells[0].textContent!==a.session)throw Error('場名');
    for(const [column,field]of [[1,'profit'],[2,'loss'],[3,'net']]){
     if(number(r.cells[column])!==a[field])throw Error('場金額:'+field);numbers++;
    }
    if(r.cells[4].textContent!==`${fmt(a.win_qty)} / ${fmt(a.loss_qty)} / ${fmt(a.flat_qty)}`)throw Error('枚数');
    if(number(r.cells[5])!==a.win_qty-a.loss_qty)throw Error('枚数差');
    const pf=a.loss?a.profit/a.loss:null;
    const payoff=a.win_qty&&a.loss_qty&&a.loss?(a.profit/a.win_qty)/(a.loss/a.loss_qty):null;
    if(r.cells[6].textContent!==fmt(pf,2)||r.cells[7].textContent!==fmt(payoff,2))throw Error('PF平均勝負');
    if(r.cells[8].textContent!==`${fmt(a.wins)} / ${fmt(a.cycles)}`)throw Error('組数');
   }
   const pr=el('periods').querySelector('tbody').rows;
   const expected=[...Object.values(method.periods[symbol]),...Object.values(method.weeks[symbol])];
   if(pr.length!==expected.length)throw Error('期間数');
   for(let i=0;i<expected.length;i++)for(const [column,field]of [[1,'profit'],[2,'loss'],[3,'net']]){
    if(number(pr[i].cells[column])!==expected[i][field])throw Error('期間金額');numbers++;
   }
   if(el('all-methods').querySelector('tbody').rows.length!==50)throw Error('全手法数');
   if(el('auto-comparison').querySelector('tbody').rows.length!==2)throw Error('統合数');
   views++;
   for(const a of group){
    el('session').value=a.session;renderSession();
    const ir=el('intervals').querySelector('tbody').rows;
    if(ir.length!==a.intervals.length)throw Error('区間数');
    for(let i=0;i<ir.length;i++)for(const [column,field]of [[1,'利益円'],[2,'損失円'],[3,'確定収支円'],[4,'開始含み円'],[5,'終了含み円'],[6,'時価収支円']]){
     if(number(ir[i].cells[column])!==a.intervals[i][field])throw Error('区間金額:'+field);numbers++;
    }
    const svg=el('chart').querySelector('svg');
    if(!svg||svg.querySelectorAll('path title,circle title').length!==a.orders.length)throw Error('マーカー数');
    if(svg.querySelectorAll('circle').length!==a.orders.filter(o=>o[4]===2).length)throw Error('返済点数');
    if(/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('グラフ未定義');
    const orders=el('orders').querySelector('tbody').rows;
    if(orders.length!==a.orders.length)throw Error('注文行数');
    for(let i=0;i<orders.length;i++){
     const o=a.orders[i],r=orders[i];
     if(number(r.cells[2])!==o[6]||number(r.cells[3])!==o[7]||number(r.cells[6])!==o[11]||number(r.cells[7])!==o[10]+1||number(r.cells[8])!==o[3])throw Error('注文表示値');
     if(o[4]===2&&number(r.cells[4])!==o[8])throw Error('返済額');
    }
    markers+=a.orders.length;accounts++;
   }
  }
 }
 el('sort').value='net';renderComparison();
 const values=[...el('all-methods').querySelector('tbody').rows].map(r=>number(r.cells[1]));
 if(values.some((v,i)=>i&&v>values[i-1]))throw Error('収支順');
 el('sort').value='fixed';el('method').value='AUTO_D';el('symbol').value='TOPIX';el('session').value=RESULT.sessions.at(-1);render();
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,手法商品表示数:views,セッション表示数:accounts,金額照合数:numbers,売買点数:markers,
         文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(verifyAll());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''

SMALL=r'''<script>
try{
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 document.body.dataset.check=JSON.stringify({全合格:true,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth});
}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''


def main() -> None:
    """機能: 全100表示・2300場の照合と広狭画面の画像を保存する。

    引数: --links/--links-only指定時はローカルリンクも確認。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--links',action='store_true')
    parser.add_argument('--links-only',action='store_true')
    args=parser.parse_args()
    source_bytes=SOURCE.read_bytes()
    source=source_bytes.decode('utf8').replace('\r\n','\n')
    source_hash=hashlib.sha256(source_bytes).hexdigest()
    links=None
    if args.links or args.links_only:
        links=0
        soup=BeautifulSoup(source,'html.parser')
        for tag in soup.select('a[href],img[src]'):
            link=tag.get('href',tag.get('src'))
            if link.startswith(('http','#')):
                continue
            target=OUT/unquote(link.split('#')[0].split('?')[0])
            assert target.exists(),target
            links+=1
    output=HERE/'HTML表示の独立検査.json'
    if args.links_only:
        result=json.loads(output.read_text(encoding='utf8'))
        assert result['HTML_SHA256']==source_hash, '表示検査後にHTMLが変更されています'
        result['静的リンク数']=links
    else:
        BROWSER.PROBE=PROBE
        allcheck=BROWSER.render(source,'全体',1500,1500)
        BROWSER.PROBE=SMALL
        small=BROWSER.render(source,'狭幅',520,1350)
        detail=BROWSER.render(source,'損益',1500,1450,'<script>document.querySelector("main").replaceChildren(document.querySelector("#detail"));window.scrollTo(0,0);</script>')
        chart=BROWSER.render(source,'売買図と区間',1500,1400,'<script>document.querySelector("main").replaceChildren(document.querySelector("#execution"));document.querySelectorAll("details").forEach(x=>x.open=true);window.scrollTo(0,0);</script>')
        result=dict(全合格=True,静的リンク数=links,目視確認=False,結果=[allcheck,small,detail,chart])
    result['HTML_SHA256']=source_hash
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
