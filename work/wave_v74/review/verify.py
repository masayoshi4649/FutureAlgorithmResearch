"""基準価格と連敗休止の比較表・全場・売買図を実ブラウザで独立照合する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import argparse
from pathlib import Path
import sys

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT/'アルゴリズム調査/00070_始値と前終値の方向制限と連敗休止'
SOURCE = OUT/'基準価格と連敗休止の説明と全セッション損益.html'
VISUAL = HERE/'visual'

PROBE = r'''<script>
/**
 * 機能: 全章の銘柄・期間・保存場を操作し、保存台帳と表示を照合する。
 * @returns {object} 検査件数と表示品質。
 */
function independentVerify(){
 const {D,STATE}=window.reportTest;
 let tables=0,accounts=0,markers=0,numbers=0,pauses=0;
 const number=td=>Number(td.textContent.replace(/[,\s円＋+]/g,'').replace('−','-'));
 const near=(a,b,label)=>{if(!Number.isFinite(a)||Math.abs(a-b)>1e-6)throw Error(label+':'+a+'/'+b);};
 const percent=v=>v===null?'—':(v*100).toFixed(1)+'%';
 const sum=(rs,k)=>rs.reduce((n,r)=>n+r[k],0);
 const verifyRow=(tr,a)=>{
  for(const [j,k] of [[1,'profit'],[2,'loss'],[3,'net'],[5,'trades'],[8,'fees'],[9,'pause_count']]){near(number(tr.cells[j]),a[k],k);numbers++;}
  near(a.profit-a.loss,a.net,'利益−損失');
  const loss=a.profit+a.loss?a.loss/(a.profit+a.loss):null,wr=a.trades?a.wins/a.trades:null;
  if(a.money_loss_share!==loss||tr.cells[4].textContent!==percent(loss)||tr.cells[6].textContent!==percent(wr))throw Error('金額比率/勝率');
  const payoff=a.wins&&a.losses?(a.profit/a.wins)/(a.loss/a.losses):null;
  if(tr.cells[7].textContent!==(payoff===null?'—':payoff.toFixed(2)))throw Error('平均勝ち負け比');
 };
 const verifyTable=(box,values)=>{
  const trs=box.querySelector('tbody').rows;
  if(trs.length!==values.length)throw Error('表行数');
  values.forEach((v,j)=>verifyRow(trs[j],v));tables++;
 };
 if(D.methods.length!==3||D.sessions.length!==29)throw Error('代表と保存場数');
 if(D.extensionSummary){
  if(document.getElementById('extension-overview').hidden)throw Error('追加検証の概要が非表示');
  verifyTable(document.querySelector('.extension-table'),D.extensionSummary.methods.flatMap(m=>['TOPIX','NK225'].map(s=>m.periods.全29[s])));
 }
 for(const [i,m] of D.methods.entries()){
  const section=document.getElementById(`method-${i}`);
  for(const symbol of ['TOPIX','NK225']){
   section.querySelector(`[data-symbol="${symbol}"]`).click();
   if(STATE.get(i).symbol!==symbol)throw Error('銘柄操作');
   for(const period of ['前16','後13','全29']){
    const select=section.querySelector('.period-select');select.value=period;select.dispatchEvent(new Event('change'));
    if(STATE.get(i).period!==period)throw Error('期間操作');
    verifyTable(section.querySelector('.comparison'),[m.baseline.periods[period][symbol],m.periods[period][symbol]]);
    verifyTable(section.querySelector('.pause-comparison'),m.pauseComparison.map(p=>p.periods[period][symbol]));
    verifyTable(section.querySelector('.control-comparison'),[m.pauseComparison[0].periods[period][symbol],...m.controls.map(p=>p.periods[period][symbol])]);
   }
   const rows=D.sessions.map(s=>m.rows.find(r=>r.session===s&&r.symbol===symbol)),total=m.periods.全29[symbol];
   verifyTable(section.querySelector('.session-table'),[...rows,total]);
   verifyTable(section.querySelector('.week-table'),[...m.weeks[symbol],total]);
   for(const field of ['profit','loss','net','fees','trades','winning_lots','losing_lots']){
    near(sum(rows,field),total[field],'場集計:'+field);near(sum(m.weeks[symbol],field),total[field],'週集計:'+field);
   }
   for(const [j,session] of D.sessions.entries()){
    if(j%2===0)section.querySelector(`.session-link[data-session="${session}"]`).click();
    else{const select=section.querySelector('.session-select');select.value=session;select.dispatchEvent(new Event('change'));}
    if(STATE.get(i).session!==session||section.querySelector('.session-select').value!==session)throw Error('保存場操作');
    const key=session+'|'+symbol,orders=m.orders[key],zones=m.pauses[key],bars=D.bars[key],svg=section.querySelector('.chart svg');
    if(!svg||!bars.length||/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('売買図');
    const ms=svg.querySelectorAll('.order-marker'),zs=svg.querySelectorAll('.pause-zone');
    if(ms.length!==orders.length||ms.length!==rows[j].trades*2||zs.length!==zones.length)throw Error('売買点/休止帯数');
    const left=Math.min(...bars.map(b=>b[0]),...orders.map(o=>o[9])),right=Math.max(...bars.map(b=>b[0]+300),...orders.map(o=>o[9]));
    const prices=bars.flatMap(b=>[b[2],b[3]]).concat(orders.map(o=>o[5])),lo=Math.min(...prices),hi=Math.max(...prices),pad=Math.max((hi-lo)*.08,symbol==='TOPIX'?.5:10);
    const x=t=>80+(t-left)/(right-left)*900,y=p=>20+(hi+pad-p)/(hi-lo+2*pad)*295;
    orders.forEach((o,k)=>{
     const shape=ms[k].querySelector(o[7]===1?'circle':'path');if(!shape)throw Error('新規/返済形状');
     if(o[7]===1){near(Number(shape.getAttribute('cx')),x(o[9]),'新規横座標');near(Number(shape.getAttribute('cy')),y(o[5]),'新規縦座標');}
     else{const xy=shape.getAttribute('d').match(/[-+]?\d*\.?\d+(?:e[-+]?\d+)?/gi).map(Number);near(xy[0],x(o[9]),'返済横座標');near(xy[1]+5,y(o[5]),'返済縦座標');}
    });
    if(orders.length){
     const history=section.querySelector('.history tbody').rows;if(history.length!==orders.length)throw Error('履歴数');
     orders.forEach((o,k)=>{near(number(history[k].cells[2]),o[4],'履歴枚数');near(number(history[k].cells[3]),o[5],'履歴価格');if(history[k].cells[5].textContent!==`${o[1]}→${o[0]}`)throw Error('判断行と約定行');});
    }else if(!section.querySelector('.history').textContent.includes('売買なし'))throw Error('無取引表示');
    markers+=ms.length;pauses+=zs.length;accounts++;
   }
  }
 }
 for(const symbol of ['TOPIX','NK225']){
  const select=document.getElementById('reference-symbol');select.value=symbol;select.dispatchEvent(new Event('change'));
  const rows=document.querySelector('#reference-table tbody').rows;if(rows.length!==29)throw Error('基準表');
  D.sessions.forEach((s,j)=>{const r=D.references[s+'|'+symbol];near(number(rows[j].cells[1]),r.ref_open.value,'始値');if(r.ref_prev.value===null){if(rows[j].cells[3].textContent!=='欠測')throw Error('前値欠測');}else near(number(rows[j].cells[3]),r.ref_prev.value,'前保存場価格');});
 }
 for(let i=0;i<3;i++){document.querySelector(`#method-${i} [data-symbol="TOPIX"]`).click();const s=document.querySelector(`#method-${i} .session-select`);s.value=D.sessions.at(-1);s.dispatchEvent(new Event('change'));}
 if(getComputedStyle(document.documentElement).colorScheme!=='dark')throw Error('暗色');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,照合表数:tables,保存場表示数:accounts,金額照合数:numbers,売買点数:markers,休止帯数:pauses,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''


def main() -> None:
    """機能: 全章を独立検査し、広幅・狭幅・図・全場表を保存する。

    引数: --extra(bool)。返り値: なし(None)。公開原本は書き換えない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--extra',action='store_true')
    args=parser.parse_args()
    source_path=OUT/'新規方向だけを制限する方式の損益.html' if args.extra else SOURCE
    prefix='追加_' if args.extra else ''
    VISUAL.mkdir(parents=True,exist_ok=True)
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('隔離表示',ROOT/'work/wave_v52/review/verify_report.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.OUT,helper.VISUAL,helper.PROBE = OUT,VISUAL,PROBE
    source = source_path.read_text(encoding='utf8')
    soup = BeautifulSoup(source,'html.parser')
    assert not soup.select('script[src],iframe,link[rel=stylesheet],img[src^=http]')
    results = [helper.render(source,prefix+'全体',1450,1500),helper.render(source,prefix+'狭幅',520,1350),
        helper.render(source,prefix+'全場表',1450,1600,'<script>const e=document.querySelector("#method-0");document.querySelector("main").replaceChildren(e.querySelector("h2"),e.querySelector(".session-table"));window.scrollTo(0,0);</script>'),
        helper.render(source,prefix+'売買図',1450,1100,'<script>const e=document.querySelector("#method-0");document.querySelector("main").replaceChildren(e.querySelector("h2"),e.querySelector(".legend"),e.querySelector(".chart-box"),e.querySelector(".history"));window.scrollTo(0,0);</script>')]
    proof = dict(全合格=True,目視確認=False,HTML_SHA256=hashlib.sha256(source_path.read_bytes()).hexdigest(),結果=results)
    (HERE/(prefix+'HTML表示の独立検査.json')).write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__ == '__main__':
    main()
