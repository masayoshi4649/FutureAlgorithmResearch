"""公開する二つのHTMLを実ブラウザで表示し、全選択と保存会計を照合する。"""

import hashlib
import importlib.util
import json
from pathlib import Path

import report

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('browser_review', report.ROOT/'work/wave_v52/review/verify_report.py')
BROWSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROWSER)
BROWSER.OUT = report.OUT
BROWSER.VISUAL = HERE/'review/visual'
BROWSER.VISUAL.mkdir(parents=True, exist_ok=True)

COMMON = r'''
const A=window.reportTest;
if(!A)throw Error('表示APIがありません');
let values=0,views=0,charts=0,markers=0;
const read=cell=>Number(cell.textContent.replaceAll(',','').replaceAll('円','').replaceAll('＋','+').replaceAll('−','-').trim());
const indicator=r=>({win:r.campaign_win_rate??(r.campaigns?r.campaign_wins/r.campaigns:null),payoff:r.campaign_payoff??(r.campaign_wins&&r.campaign_losses?(r.campaign_profit/r.campaign_wins)/(r.campaign_loss/r.campaign_losses):null),dd:r.drawdown??r.max_drawdown??0});
const ratio=(r,p=false)=>r===null||r===undefined||!Number.isFinite(Number(r))?'—':p?`${(r*100).toFixed(1)}%`:Number(r).toFixed(2);
/**
 * 機能: 組単位の会計と表示数値を全列照合する。
 * @param {HTMLTableRowElement} row - 表示行。
 * @param {object} data - 保存会計。
 * @returns {void} 返り値なし。
 */
function primary(row,data){
 if(!row||!data)throw Error('比較対象の不足');
 for(const [c,k]of[[1,'campaign_profit'],[2,'campaign_loss'],[3,'net'],[4,'campaigns']]){if(read(row.cells[c])!==data[k])throw Error('組金額・数:'+k);values++;}
 const q=indicator(data);
 if(row.cells[5].textContent!==ratio(q.win,true)||row.cells[6].textContent!==ratio(q.payoff))throw Error('組比率');
 if(read(row.cells[7])!==q.dd||row.cells[8].textContent!==`${data.max_long}／${data.max_short}`)throw Error('時価・上限');
}
/**
 * 機能: 部分決済、枚数、役割、料金の全列を照合する。
 * @param {HTMLTableRowElement} row - 表示行。
 * @param {object} data - 保存会計。
 * @returns {void} 返り値なし。
 */
function detail(row,data){
 for(const [c,k]of[[1,'profit'],[2,'loss'],[3,'winning_lots'],[4,'losing_lots'],[5,'core_net'],[6,'cover_net'],[7,'fees']]){if(read(row.cells[c])!==data[k])throw Error('明細:'+k);values++;}
}
/**
 * 機能: 全画面の暗色表示と横溢れを確認する。
 * @returns {object} 表示の検査結果。
 */
function finish(){
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,切替数:views,表示数値照合:values,売買図数:charts,売買点数:markers,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.body).backgroundColor};
}
'''

MAIN = r'''
if(A.D.methods.length!==3||A.D.sessions.length!==28)throw Error('主HTML件数');
for(let index=0;index<A.D.methods.length;index++){
 const m=A.D.methods[index],s=A.STATE.get(index),sec=document.getElementById(`method-${index}`);
 if(m.eligible)throw Error('採用未達の代表');
 for(const symbol of ['TOPIX','NK225']){
  s.symbol=symbol;
  for(const period of ['前16','後12','全28']){
   s.period=period;A.updateMethod(index);
   const actual=sec.querySelector('.comparison tbody').rows,part=sec.querySelector('.comparison-detail tbody').rows;
   const expected=[m.baseline.periods[period][symbol],...(m.control?[m.control.periods[period][symbol]]:[]),m.periods[period][symbol]];
   if(actual.length!==expected.length)throw Error('比較行数');
   expected.forEach((r,i)=>{primary(actual[i],r);detail(part[i],r);});views++;
  }
  const rows=A.D.sessions.map(key=>m.rows.find(r=>r.session===key&&r.symbol===symbol));
  rows.push(m.periods['全28'][symbol]);
  const ses=sec.querySelector('.session-table tbody').rows,det=sec.querySelector('.session-detail tbody').rows;
  if(ses.length!==29||det.length!==29)throw Error('場会計行数');
  rows.forEach((r,i)=>{primary(ses[i],r);detail(det[i],r);});
  const week=[...m.weeks[symbol],m.periods['全28'][symbol]],ws=sec.querySelector('.week-table tbody').rows;
  if(ws.length!==4)throw Error('週行数');week.forEach((r,i)=>primary(ws[i],r));
  for(const session of A.D.sessions){
   s.session=session;A.drawChart(index);
   const orders=m.orders[session+'|'+symbol],svg=sec.querySelector('.chart svg');
   if(!svg||/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('売買図');
   if(svg.querySelectorAll('circle,path').length!==orders.length)throw Error('売買点数');
   if(svg.querySelectorAll('circle').length!==orders.filter(o=>o[7]===1).length)throw Error('新規点');
   if(svg.querySelectorAll('title').length!==A.D.bars[session+'|'+symbol].length+orders.length)throw Error('売買図説明');
   const hs=sec.querySelector('.history tbody')?.rows??[];
   if(hs.length!==orders.length)throw Error('注文履歴数');
   orders.forEach((o,i)=>{
    if(read(hs[i].cells[2])!==o[4]||read(hs[i].cells[3])!==o[5]||read(hs[i].cells[6])!==o[2])throw Error('注文数値');
    if(hs[i].cells[7].textContent!==`${o[1]}→${o[0]}`||o[1]>=o[0])throw Error('判断と約定順');
   });
   markers+=orders.length;charts++;
  }
 }
 s.symbol='TOPIX';s.period='全28';s.session='2026-10-08_Day';A.updateMethod(index);
}
if(!document.querySelector('.source-note').textContent.includes('採用条件は未達'))throw Error('採用表示');
return finish();
'''

ALL = r'''
if(A.D.methods.length!==222||A.D.sessions.length!==28)throw Error('全件数');
const allRows=document.querySelector('#summary tbody').rows;
if(allRows.length!==222)throw Error('一覧の条件数');
A.D.methods.forEach((m,i)=>{
 for(const [c,s,k]of[[3,'TOPIX','net'],[5,'TOPIX','campaigns'],[6,'NK225','net'],[8,'NK225','campaigns']]){if(read(allRows[i].cells[c])!==m.periods['全28'][s][k])throw Error('一覧会計');values++;}
 if(allRows[i].cells[4].textContent!==ratio(indicator(m.periods['全28'].TOPIX).payoff)||allRows[i].cells[7].textContent!==ratio(indicator(m.periods['全28'].NK225).payoff))throw Error('一覧比率');
 if(Boolean(m.config.control)!==allRows[i].cells[0].textContent.includes('診断・選定外'))throw Error('対照タグ');
 for(const symbol of ['TOPIX','NK225']){
  A.STATE.id=m.id;A.STATE.symbol=symbol;A.renderCondition();
  const pr=document.querySelector('#period-table tbody').rows;
  ['前16','後12','全28'].forEach((p,j)=>primary(pr[j],m.periods[p][symbol]));
  const ses=document.querySelector('#session-table tbody').rows,det=document.querySelector('#detail-table tbody').rows;
  if(ses.length!==29||det.length!==29)throw Error('全一覧場会計');
  const rows=A.D.sessions.map(key=>m.rows.find(r=>r.session===key&&r.symbol===symbol));rows.push(m.periods['全28'][symbol]);
  rows.forEach((r,j)=>{primary(ses[j],r);detail(det[j],r);});views++;
 }
});
for(const source of new Set(A.D.methods.map(m=>m.config.source))){
 A.STATE.source=source;A.STATE.group='';A.renderList();
 if(document.querySelectorAll('#summary tbody tr').length!==37)throw Error('入口絞り込み');
}
A.STATE.source='';
for(const group of new Set(A.D.methods.map(m=>m.config.group))){
 A.STATE.group=group;A.renderList();
 if(document.querySelectorAll('#summary tbody tr').length!==A.D.methods.filter(m=>m.config.group===group).length)throw Error('管理絞り込み');
}
A.STATE.source='';A.STATE.group='';A.STATE.id='T2L0_H03';A.STATE.symbol='TOPIX';A.renderList();A.selectMethod('T2L0_H03');
if(decodeURIComponent(location.hash.slice(1))!=='T2L0_H03')throw Error('URL選択');
return finish();
'''


def probe(script: str) -> str:
    """機能: ブラウザ検査を例外込みの結果JSONへまとめる。

    引数: script(str)。返り値: 検査用スクリプト(str)。
    """
    return '<script>function independentVerify(){'+COMMON+script+'}\ntry{document.body.dataset.check=JSON.stringify(independentVerify());}catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e),stack:e.stack});}</script>'


def main() -> None:
    """機能: 全表示切替と広狭幅を照合し、目視用画像を保存する。

    引数: なし。返り値: なし(None)。
    """
    checks = []
    for filename, script, label in ((report.MAIN, MAIN, '主HTML'),(report.ALL, ALL, '全一覧')):
        source = (report.OUT/filename).read_text(encoding='utf8')
        BROWSER.PROBE = probe(script)
        for width in (1360,500):
            checks.append(BROWSER.render(source,label+str(width),width,980))
    BROWSER.PROBE = '<script>document.body.dataset.check=JSON.stringify({全合格:true});</script>'
    extra = '''<script>
    const A=window.reportTest;A.STATE.get(0).session='2026-10-08_Day';A.drawChart(0);
    const box=document.querySelector('#method-0 .chart-box').outerHTML;
    document.querySelector('main').innerHTML='<h1>段階両建ての売買図</h1><p>水色：元玉、黄色：保険玉。丸：新規、菱形：返済。</p>'+box;
    window.scrollTo(0,0);
    </script>'''
    checks.append(BROWSER.render((report.OUT/report.MAIN).read_text(encoding='utf8'),'保険の売買図',1360,880,extra))
    proof = dict(全合格=True,全条件表示=True,目視確認=False,検査=checks,
                 主HTML_SHA256=hashlib.sha256((report.OUT/report.MAIN).read_bytes()).hexdigest(),
                 全条件HTML_SHA256=hashlib.sha256((report.OUT/report.ALL).read_bytes()).hexdigest())
    (HERE/'HTML表示の独立検査.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
