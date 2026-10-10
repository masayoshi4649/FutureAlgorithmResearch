"""入口確認と幅拡大のHTMLを、実ブラウザの全選択・表示会計で独立照合する。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査/00068_入口確認とトレーリング幅拡大'
MAIN_NAME = '入口確認と幅拡大の説明と損益.html'
ALL_NAME = '全432条件の比較.html'
REVIEW = HERE / 'review'
SPEC = importlib.util.spec_from_file_location('入口幅比較のブラウザ検査器', ROOT / 'work/wave_v52/review/verify_report.py')
BROWSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROWSER)
BROWSER.OUT = OUT
BROWSER.VISUAL = REVIEW / 'visual'


COMMON = r'''
const A=window.reportTest;
if(!A)throw Error('表示APIがありません');
let values=0,views=0,charts=0,markers=0,diagnostics=0,widthRows=0,references=0;
const PERIODS=['前16','後12','全28','追加1','全29'];
const read=cell=>Number(cell.textContent.replaceAll(',','').replaceAll('円','').replaceAll('＋','+').replaceAll('−','-').trim());
const indicator=r=>({win:r.campaign_win_rate??(r.campaigns?r.campaign_wins/r.campaigns:null),payoff:r.campaign_payoff??(r.campaign_wins&&r.campaign_losses?(r.campaign_profit/r.campaign_wins)/(r.campaign_loss/r.campaign_losses):null),dd:r.drawdown??r.max_drawdown??0});
const ratio=(r,p=false)=>r===null||r===undefined||!Number.isFinite(Number(r))?'—':p?`${(r*100).toFixed(1)}%`:Number(r).toFixed(2);

/**
 * 機能: 組単位の利益・損失・収支・勝率・最大下落・枚数を照合する。
 * @param {HTMLTableRowElement} row - 表示された行。
 * @param {object} data - 対応する固定集計値。
 * @returns {void} 返り値なし。
 */
function primary(row,data){
 if(!row||!data)throw Error('組会計比較対象の不足');
 for(const [c,k]of[[1,'campaign_profit'],[2,'campaign_loss'],[3,'net'],[4,'campaigns']]){
  if(read(row.cells[c])!==data[k])throw Error('組会計表示:'+k+'/'+read(row.cells[c])+'/'+data[k]);values++;
 }
 const q=indicator(data);
 if(row.cells[5].textContent!==ratio(q.win,true)||row.cells[6].textContent!==ratio(q.payoff))throw Error('組の平均比・勝率');
 if(read(row.cells[7])!==q.dd||row.cells[8].textContent!==`${data.max_long}／${data.max_short}`)throw Error('含み込み下落・上限');
 if(Math.abs(data.campaign_profit-data.campaign_loss-data.net)>1e-6)throw Error('組利益損失と収支の不一致');
}

/**
 * 機能: 部分決済の利益・損失・枚数・由来別収支・手数料を照合する。
 * @param {HTMLTableRowElement} row - 表示された行。
 * @param {object} data - 固定集計値。
 * @returns {void} 返り値なし。
 */
function detail(row,data){
 if(!row||!data)throw Error('明細比較対象の不足');
 for(const [c,k]of[[1,'profit'],[2,'loss'],[3,'winning_lots'],[4,'losing_lots'],[5,'core_net'],[6,'cover_net'],[7,'fees']]){
  if(read(row.cells[c])!==data[k])throw Error('明細会計表示:'+k);values++;
 }
 if(Math.abs(data.core_net+data.cover_net-data.net)>1e-6)throw Error('元と保険の収支合算');
}

/**
 * 機能: 主HTMLの入口先着率を、未到達を含む全件分母で照合する。
 * @param {HTMLElement} section - 手法の章。
 * @param {object} method - 保存された入口診断。
 * @param {string} period - 対象期間。
 * @param {string} symbol - 対象銘柄。
 * @returns {void} 返り値なし。
 */
function diagnostic(section,method,period,symbol){
 const expected=[method.baseEntryDiagnostic[period][symbol]['8'],method.baseEntryDiagnostic[period][symbol]['16'],
                 method.entryDiagnostic[period][symbol]['8'],method.entryDiagnostic[period][symbol]['16']];
 const rows=section.querySelector('.entry-diagnostic tbody')?.rows;
 if(!rows||rows.length!==4)throw Error('入口診断の4行不足');
 expected.forEach((data,i)=>{
  const row=rows[i],level=i%2===0?8:16;
  if(row.cells[1].textContent!==`±${level}呼値`||row.cells[2].textContent!==`${data.favorable}／${data.total}`)throw Error('入口先着幅・全件分母');
  if(row.cells[3].textContent!==ratio(data.favorable_rate_all,true)||read(row.cells[4])!==data.adverse||read(row.cells[5])!==data.unreached||row.cells[6].textContent!==ratio(data.favorable_rate_reached,true))throw Error('先着率・未到達');
  if(data.total!==data.favorable+data.adverse+data.unreached)throw Error('入口先着分類の合算');
  diagnostics++;values+=6;
 });
}

/**
 * 機能: 暗色背景、横溢れ、未定義値、G3同期限界の説明を確認する。
 * @returns {object} 表示検査の件数。
 */
function finish(){
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('文書の横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義の表示');
 const color=getComputedStyle(document.body).backgroundColor;
 const rgb=color.match(/\d+/g)?.map(Number)??[];
 if(rgb.length<3||rgb.slice(0,3).some(v=>v>80))throw Error('明るい背景');
 return {全合格:true,切替数:views,表示数値照合:values,入口診断行数:diagnostics,同入口幅比較行数:widthRows,参考例行数:references,売買図数:charts,
         売買点数:markers,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:color};
}
'''


MAIN = r'''
if(A.D.methods.length!==3||A.D.sessions.length!==29)throw Error('主HTML件数');
if(!A.D.sessions.includes('2026-10-09_Day'))throw Error('追加追試場');
if(!document.querySelector('#notes').textContent.includes('参考として主選定除外'))throw Error('G3主選定外説明');
if(document.querySelector('.source-note').textContent.includes('採用条件は未達'))throw Error('採用未達の固定説明');
if(document.getElementById('conclusion').textContent!==A.D.conclusion)throw Error('固定データと採用説明の不一致');
for(let index=0;index<A.D.methods.length;index++){
 const m=A.D.methods[index],s=A.STATE.get(index),sec=document.getElementById(`method-${index}`);
 const options=Array.from(sec.querySelector('.period-select').options,o=>o.value);
 if(JSON.stringify(options)!==JSON.stringify(PERIODS))throw Error('5期間の選択肢');
 for(const symbol of ['TOPIX','NK225']){
  s.symbol=symbol;
  for(const period of PERIODS){
   s.period=period;A.updateMethod(index);
   const actual=sec.querySelector('.comparison tbody').rows,part=sec.querySelector('.comparison-detail tbody').rows;
   const expected=[m.baseline.periods[period][symbol],m.control.periods[period][symbol],m.netControl.periods[period][symbol],m.periods[period][symbol]];
   if(actual.length!==4||part.length!==4)throw Error('基準・無保険・縮小・現在の4比較');
   expected.forEach((r,i)=>{primary(actual[i],r);detail(part[i],r);});
   const ws=sec.querySelector('.width-comparison tbody')?.rows;
   if(!ws||ws.length!==6||m.widthComparisons.length!==6)throw Error('同じGの6幅比較');
   m.widthComparisons.forEach((w,i)=>{
    if(w.config.source!==m.config.source||w.config.gate_level!==m.config.gate_level||w.config.method!=='H')throw Error('幅比較の入口又は管理不一致');
    if(ws[i].cells[0].textContent!==`${w.config.width_id}：${w.config.width_name}`)throw Error('幅名');
    primary(ws[i],w.periods[period][symbol]);widthRows++;
   });
   diagnostic(sec,m,period,symbol);views++;
  }
  const rows=A.D.sessions.map(key=>m.rows.find(r=>r.session===key&&r.symbol===symbol));
  rows.push(m.periods['全29'][symbol]);
  const ses=sec.querySelector('.session-table tbody').rows,det=sec.querySelector('.session-detail tbody').rows;
  if(ses.length!==30||det.length!==30)throw Error('29場と合計の会計行数');
  rows.forEach((r,i)=>{primary(ses[i],r);detail(det[i],r);});
  const week=[...m.weeks[symbol],m.periods['全29'][symbol]],ws=sec.querySelector('.week-table tbody').rows;
  if(ws.length!==4||m.weeks[symbol].length!==3)throw Error('3週と全29合計');
  week.forEach((r,i)=>primary(ws[i],r));
  for(const session of A.D.sessions){
   s.session=session;A.drawChart(index);
   const orders=m.orders[session+'|'+symbol],svg=sec.querySelector('.chart svg');
   if(!svg||/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('5分足と売買図');
   if(svg.querySelectorAll('circle,path').length!==orders.length)throw Error('売買マーカー数');
   if(svg.querySelectorAll('circle').length!==orders.filter(o=>o[7]===1).length)throw Error('新規丸の数');
   if(svg.querySelectorAll('title').length!==A.D.bars[session+'|'+symbol].length+orders.length)throw Error('ローソク足と売買の説明');
   const nodes=svg.querySelectorAll('circle,path'),hs=sec.querySelector('.history tbody')?.rows??[];
   if(hs.length!==orders.length)throw Error('注文履歴数');
   orders.forEach((o,i)=>{
    if(read(hs[i].cells[2])!==o[4]||read(hs[i].cells[3])!==o[5]||read(hs[i].cells[6])!==o[2])throw Error('注文の枚数・価格・組');
    if(hs[i].cells[7].textContent!==`${o[1]}→${o[0]}`||o[1]>=o[0])throw Error('発注判断と約定行順');
    if(nodes[i].getAttribute('fill')!==(o[8]===1?'#ffc973':'#67d7ff'))throw Error('役割別マーカー配色');
    const text=hs[i].cells[1].textContent;
    if((o[3]>0)!==text.includes('買い')||(o[7]===1)!==text.includes('新規'))throw Error('新規返済と買売');
   });
   markers+=orders.length;charts++;
  }
 }
 s.symbol='TOPIX';s.period='全29';s.session='2026-10-09_Day';A.updateMethod(index);
}
if(charts!==174||views!==30||diagnostics!==120)throw Error('全主選択の検査数');
const referenceRows=document.querySelector('#reference tbody')?.rows;
if(!A.D.reference||referenceRows?.length!==10)throw Error('少数黒字参考例の5期間2銘柄');
let refIndex=0;
for(const p of PERIODS)for(const symbol of ['TOPIX','NK225']){
 primary(referenceRows[refIndex++],A.D.reference.periods[p][symbol]);references++;
}
if(!document.getElementById('reference').textContent.includes(A.D.reference.id)||!document.getElementById('reference').textContent.includes(A.D.reference.description))throw Error('参考ID又は説明');
return finish();
'''


ALL = r'''
if(A.D.methods.length!==432||A.D.sessions.length!==29)throw Error('全条件件数');
if(!document.body.innerText.includes('G3')||!document.body.innerText.includes('主選定から除外'))throw Error('G3の参考扱い');
const allRows=document.querySelector('#summary tbody').rows;
if(allRows.length!==432)throw Error('一覧件数');
A.D.methods.forEach((m,i)=>{
 for(const [c,s,k]of[[3,'TOPIX','net'],[5,'TOPIX','campaigns'],[6,'NK225','net'],[8,'NK225','campaigns']]){
  if(read(allRows[i].cells[c])!==m.periods['全29'][s][k])throw Error('一覧の全29会計');values++;
 }
 if(allRows[i].cells[4].textContent!==ratio(indicator(m.periods['全29'].TOPIX).payoff)||allRows[i].cells[7].textContent!==ratio(indicator(m.periods['全29'].NK225).payoff))throw Error('一覧損益比');
 for(const symbol of ['TOPIX','NK225']){
  A.STATE.id=m.id;A.STATE.symbol=symbol;A.renderCondition();
  const pr=document.querySelector('#period-table tbody').rows;
  if(pr.length!==5)throw Error('一覧5期間');
  PERIODS.forEach((p,j)=>primary(pr[j],m.periods[p][symbol]));
  const ses=document.querySelector('#session-table tbody').rows,det=document.querySelector('#detail-table tbody').rows;
  if(ses.length!==30||det.length!==30)throw Error('全条件29場会計');
  const rows=A.D.sessions.map(key=>m.rows.find(r=>r.session===key&&r.symbol===symbol));
  rows.push(m.periods['全29'][symbol]);
  rows.forEach((r,j)=>{primary(ses[j],r);detail(det[j],r);});views++;
 }
});
for(const source of new Set(A.D.methods.map(m=>m.config.source))){
 A.STATE.source=source;A.STATE.group='';A.renderList();
 if(document.querySelectorAll('#summary tbody tr').length!==72)throw Error('入口別72条件の絞り込み');
}
A.STATE.source='';
for(const group of new Set(A.D.methods.map(m=>m.config.group))){
 A.STATE.group=group;A.renderList();
 if(document.querySelectorAll('#summary tbody tr').length!==A.D.methods.filter(m=>m.config.group===group).length)throw Error('管理系統の絞り込み');
}
const chosen=A.D.selectedIds[0]??A.D.methods[0].id;
A.STATE.source='';A.STATE.group='';A.STATE.id=chosen;A.STATE.symbol='TOPIX';A.renderList();A.selectMethod(chosen);
if(decodeURIComponent(location.hash.slice(1))!==chosen)throw Error('URLhashによる条件選択');
if(views!==864)throw Error('全432条件×2銘柄の切替');
return finish();
'''


def probe(script: str) -> str:
    """機能: 実ブラウザ検査の結果と例外をJSONへ収める。

    引数: script(str)。返り値: 検査を埋め込むscriptタグ(str)。
    """
    return '<script>function independentVerify(){'+COMMON+script+'}\ntry{document.body.dataset.check=JSON.stringify(independentVerify());}catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e),stack:e.stack});}</script>'


def links() -> dict:
    """機能: 二つの公開HTMLの静的ローカルリンク先を照合する。

    引数: なし。返り値: リンク検査件数(dict)。
    """
    count = 0
    for name in (MAIN_NAME,ALL_NAME):
        soup = BeautifulSoup((OUT/name).read_text(encoding='utf8'),'html.parser')
        for tag in soup.select('a[href],img[src]'):
            ref = tag.get('href',tag.get('src'))
            if ref.startswith(('http:','https:','#')):
                continue
            target = OUT/unquote(ref.split('#')[0].split('?')[0])
            assert target.exists(), str(target)
            count += 1
    return dict(全合格=True,静的リンク数=count)


def main() -> None:
    """機能: 主174売買図と全432条件を広狭画面で照合し、画像と証跡を保存する。

    引数: --links/--links-only/--only(str)は任意指定。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--links',action='store_true')
    parser.add_argument('--links-only',action='store_true')
    parser.add_argument('--only',choices=('main','all'))
    args = parser.parse_args()
    REVIEW.mkdir(parents=True,exist_ok=True)
    output = REVIEW/'HTML表示の独立検査.json'
    if args.links_only:
        proof = json.loads(output.read_text(encoding='utf8'))
        proof['リンク検査'] = links()
        output.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(proof['リンク検査'],ensure_ascii=False))
        return
    checks = []
    tests = ((MAIN_NAME,MAIN,'主HTML','main'),(ALL_NAME,ALL,'全一覧','all'))
    for name,script,label,kind in tests:
        if args.only and args.only!=kind:
            continue
        source = (OUT/name).read_text(encoding='utf8')
        BROWSER.PROBE = probe(script)
        for width in (1360,500):
            checks.append(BROWSER.render(source,label+str(width),width,1060))
    if args.only!='all':
        BROWSER.PROBE = '<script>document.body.dataset.check=JSON.stringify({全合格:true});</script>'
        extra = '''<script>
        const A=window.reportTest;A.STATE.get(0).session='2026-10-09_Day';A.drawChart(0);
        const box=document.querySelector('#method-0 .chart-box').outerHTML;
        document.querySelector('main').innerHTML='<h1>追加デイの売買図</h1><p>水色：元玉、橙色：保険玉。丸：新規、菱形：返済。</p>'+box;
        window.scrollTo(0,0);
        </script>'''
        checks.append(BROWSER.render((OUT/MAIN_NAME).read_text(encoding='utf8'),'追加デイの売買図',1360,880,extra))
    proof = dict(全合格=True,全条件表示=args.only is None,目視確認=False,検査=checks,
        主HTML_SHA256=hashlib.sha256((OUT/MAIN_NAME).read_bytes()).hexdigest(),
        全条件HTML_SHA256=hashlib.sha256((OUT/ALL_NAME).read_bytes()).hexdigest())
    if args.links:
        proof['リンク検査'] = links()
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
