"""固定会計の全五十八表示と売買図を隔離した実ブラウザで独立検査する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import unquote

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'アルゴリズム調査/00069_T1L1_R01の全セッションと金額評価'
SOURCE = OUT / 'T1L1_R01の全セッション結果.html'
VISUAL = HERE / 'visual'


PROBE = r'''<script>
/**
 * 機能: 保存値とは独立に比率を計算し、全銘柄・場の表示と売買図を照合する。
 * @returns {object} 表示件数、金額件数、暗色と画面幅の検査結果。
 */
function independentVerify(){
 const {D,STATE}=window.reportTest;
 let accounts=0,numbers=0,markers=0,ratios=0,histories=0;
 const el=id=>document.getElementById(id);
 const number=cell=>Number(cell.textContent.replace(/[,\s円＋+]/g,'').replace('−','-'));
 const fmt=new Intl.NumberFormat('ja-JP',{maximumFractionDigits:0});
 const clock=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
 const names={TOPIX:'TOPIXミニ10枚',NK225:'NK225マイクロ20枚'};
 const labels={1:'初期損切り',2:'通常トレール',3:'保有期限',4:'場内全返済',10:'反転確認の新規',13:'段階利益固定'};
 const sessionName=key=>key.replace('_Day',' デイ').replace('_Night',' ナイト');
 const near=(a,b,name)=>{if(!Number.isFinite(a)||Math.abs(a-b)>1e-7)throw Error(name+':'+a+'/'+b);};
 const rate=(v,percent=false)=>v===null?'—':percent?(v*100).toFixed(2)+'%':v.toFixed(3);
 const independent=r=>{
  const p=r.campaign_profit,l=r.campaign_loss;
  near(p-l,r.net,'利益−損失と収支');
  const lossShare=p+l?l/(p+l):null,pf=l?p/l:null,count=r.campaigns?r.campaign_losses/r.campaigns:null;
  if(r.money_loss_share!==lossShare||r.profit_loss_ratio!==pf||r.count_loss_rate!==count)throw Error('保存率の計算');
  return {lossShare,pf,count};
 };
 const moneyRow=(tr,r,label)=>{
  if(tr.cells[0].textContent.trim().replace(/\s+追加$/,'')!==label)throw Error('行見出し:'+tr.cells[0].textContent+'/'+label);
  for(const [col,field]of[[1,'campaign_profit'],[2,'campaign_loss'],[3,'net'],[6,'campaigns'],[7,'fees']]){
   near(number(tr.cells[col]),r[field],'表示金額:'+field);numbers++;
  }
  const a=independent(r);
  if(tr.cells[4].textContent!==rate(a.lossShare,true)||tr.cells[5].textContent!==rate(a.pf))throw Error('表示金額率');
  ratios+=2;
 };
 if(D.sessions.length!==29||D.rows.length!==58)throw Error('保存口座数');
 const cards=el('summary').querySelectorAll('article');
 for(const [j,symbol]of['TOPIX','NK225'].entries()){
  const r=D.periods['全29'][symbol],card=cards[j];
  if(card.querySelector('h2').textContent!==names[symbol])throw Error('合計カード銘柄');
  const a=independent(r);
  if(card.querySelector('.big').textContent!==rate(a.lossShare,true))throw Error('合計カード率');
  const cash=card.querySelectorAll('.row strong');
  for(const [k,field]of['campaign_profit','campaign_loss','net'].entries()){
   near(number(cash[k]),r[field],'合計カード金額');numbers++;
  }
  if(card.querySelector('.row.small span:last-child').textContent!==rate(a.pf))throw Error('合計カード利益損失比');
 }
 for(const symbol of['TOPIX','NK225']){
  el('symbol-buttons').querySelector(`[data-symbol="${symbol}"]`).click();
  if(STATE.symbol!==symbol)throw Error('銘柄切替');
  const pressed=el('symbol-buttons').querySelectorAll('[aria-pressed="true"]');
  if(pressed.length!==1||pressed[0].dataset.symbol!==symbol)throw Error('選択ボタン');
  const trs=el('sessions').querySelector('tbody').rows;
  if(trs.length!==30)throw Error('全場テーブル行数');
  const source=D.rows.filter(r=>r.symbol===symbol);
  for(const [j,session]of D.sessions.entries()){
   const r=source.find(r=>r.session===session);
   moneyRow(trs[j],r,sessionName(session));
  }
  const total=D.periods['全29'][symbol];
  moneyRow(trs[29],total,'全29合計');
  for(const field of['campaign_profit','campaign_loss','net','fees','campaigns','campaign_wins','campaign_losses','winning_lots','losing_lots']){
   near(source.reduce((n,r)=>n+r[field],0),total[field],'全場合計:'+field);
  }
  const prs=el('periods').querySelector('tbody').rows;
  for(const [j,name]of['既存28','追加デイ','全29'].entries())moneyRow(prs[j],D.periods[name][symbol],name);
  const wrs=el('weeks').querySelector('tbody').rows;
  for(const [j,r]of D.weeks[symbol].entries())moneyRow(wrs[j],r,r.label);
  moneyRow(wrs[wrs.length-1],total,'全29合計');
  for(const field of['campaign_profit','campaign_loss','net','fees'])near(D.weeks[symbol].reduce((n,r)=>n+r[field],0),total[field],'週合計:'+field);
  const aux=el('auxiliary').querySelector('tbody').rows;
  for(let j=0;j<aux.length;j++){
   const r=j===29?total:source.find(r=>r.session===D.sessions[j]);
   if(aux[j].cells[1].textContent!==`${r.campaign_wins}／${r.campaign_losses}`||aux[j].cells[2].textContent!==rate(independent(r).count,true)||aux[j].cells[3].textContent!==`${r.winning_lots}／${r.losing_lots}`)throw Error('補助回数枚数');
  }
  const sizes=el('size-metrics').querySelector('tbody').rows[0],aw=total.campaign_wins?total.campaign_profit/total.campaign_wins:null,al=total.campaign_losses?total.campaign_loss/total.campaign_losses:null;
  if(sizes.cells[1].textContent!==(aw===null?'—':fmt.format(aw)+'円')||sizes.cells[2].textContent!==(al===null?'—':fmt.format(al)+'円')||sizes.cells[3].textContent!==rate(aw!==null&&al!==null?aw/al:null))throw Error('平均損益表示');
  near(number(sizes.cells[4]),total.max_campaign_loss,'最大負け');
  if(sizes.cells[5].textContent!==`${total.max_long}／${total.max_short}`)throw Error('最大枚数');
  for(const [j,session]of D.sessions.entries()){
   if(j%2===0)el('sessions').querySelector(`button[data-session="${session}"]`).click();
   else{el('session-select').value=session;el('session-select').dispatchEvent(new Event('change'));}
   if(STATE.session!==session||el('session-select').value!==session)throw Error('場切替');
   const selected=el('sessions').querySelectorAll('tr.selected');
   if(selected.length!==1||selected[0].dataset.session!==session)throw Error('選択場強調');
   const key=`${session}|${symbol}`,bars=D.bars[key],orders=D.orders[key],svg=el('chart').querySelector('svg');
   if(!bars.length||!svg||/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('売買図の有限値');
   const marks=svg.querySelectorAll('.order-marker');
   if(marks.length!==orders.length||marks.length!==D.rows.find(r=>r.session===session&&r.symbol===symbol).campaigns*2)throw Error('新規返済点数');
   const left=Math.min(...bars.map(b=>b[0]),...orders.map(o=>o[9])),right=Math.max(...bars.map(b=>b[0]+300),...orders.map(o=>o[9]),left+300);
   const prices=bars.flatMap(b=>[b[2],b[3]]).concat(orders.map(o=>o[5])),lo=Math.min(...prices),hi=Math.max(...prices),pad=Math.max((hi-lo)*.08,symbol==='TOPIX'?.5:10),low=lo-pad,high=hi+pad;
   for(const [k,o]of orders.entries()){
    const mark=marks[k],shape=mark.querySelector(o[7]===1?'circle':'path'),xx=76+(o[9]-left)/(right-left)*902,yy=18+(high-o[5])/(high-low)*290;
    if(!shape)throw Error('新規円返済菱形');
    if(o[7]===1){near(Number(shape.getAttribute('cx')),xx,'新規時刻座標');near(Number(shape.getAttribute('cy')),yy,'新規価格座標');}
    else{const xy=shape.getAttribute('d').match(/[-+]?\d*\.?\d+(?:e[-+]?\d+)?/gi).map(Number);near(xy[0],xx,'返済時刻座標');near(xy[1]+5,yy,'返済価格座標');}
    const expected=`${clock.format(new Date(o[9]*1000))} ${o[7]===1?'新規':'返済'} ${o[3]===1?'買い':'売り'} ${o[4]}枚 @${o[5]} ${labels[o[6]]??o[6]}`;
    if(mark.querySelector('title').textContent!==expected||shape.getAttribute('fill')!==(o[3]===1?'#76d9ff':'#ffc978'))throw Error('マーカー内容と色');
   }
   if(orders.length){
    const hs=el('history').querySelector('tbody').rows;
    if(hs.length!==orders.length)throw Error('履歴数');
    for(const [k,o]of orders.entries()){
     const expected=[clock.format(new Date(o[9]*1000)),o[7]===1?'新規':'返済',o[3]===1?'買い':'売り',String(o[4]),String(o[5]),String(labels[o[6]]??o[6]),String(o[2])];
     for(let col=0;col<7;col++)if(hs[k].cells[col].textContent!==expected[col])throw Error('履歴列:'+col);
     histories++;
    }
   }else if(!el('history').textContent.includes('無取引'))throw Error('無取引表示');
   markers+=marks.length;accounts++;
  }
 }
 el('symbol-buttons').querySelector('[data-symbol="TOPIX"]').click();
 el('session-select').value=D.sessions.at(-1);el('session-select').dispatchEvent(new Event('change'));
 const bg=getComputedStyle(document.body).backgroundColor;
 if(bg!=='rgb(11, 18, 29)'||getComputedStyle(document.documentElement).colorScheme!=='dark')throw Error('暗色背景');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面外への横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,セッション表示数:accounts,表示金額数:numbers,金額率数:ratios,売買点数:markers,履歴数:histories,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:bg};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''


def main() -> None:
    """機能: 旧隔離表示器を再利用し、広狭幅・表・売買図を検査する。

    引数: なし。返り値: なし(None)。公開HTMLは読取専用で検査複製だけを保存する。
    """
    HERE.mkdir(exist_ok=True)
    VISUAL.mkdir(exist_ok=True)
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('表示検査器', ROOT / 'work/wave_v52/review/verify_report.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.OUT, helper.VISUAL, helper.PROBE = OUT, VISUAL, PROBE
    source = SOURCE.read_text(encoding='utf8')
    links = 0
    for tag in BeautifulSoup(source, 'html.parser').select('a[href],img[src]'):
        value = tag.get('href', tag.get('src'))
        assert not value.startswith(('http:', 'https:')), '外部表示通信が設定されています'
        if value.startswith('#'):
            continue
        assert (OUT / unquote(value.split('#')[0].split('?')[0])).exists(), value
        links += 1
    # ----------------------------------------
    # 全表示の機械照合後、目視対象を全体・狭幅・全場テーブル・売買図へ分ける。
    screens = [helper.render(source, '全体', 1450, 1500), helper.render(source, '狭幅', 520, 1350),
        helper.render(source, '全セッション表', 1450, 1700,
            '<script>document.querySelector("main").replaceChildren(document.querySelector("#session-heading"),document.querySelector("#sessions"));window.scrollTo(0,0);</script>'),
        helper.render(source, '売買図と履歴', 1450, 1250,
            '<script>const s=document.querySelector("#chart").closest("section");document.querySelector("main").replaceChildren(s);s.querySelector("details").open=true;window.scrollTo(0,0);</script>')]
    result = dict(全合格=True, 静的リンク数=links, 目視確認=False,
        検査='全29×2の表示金額・金額率・合計・操作・売買点座標・全履歴・暗色・狭幅をChromeで確認。複製HTMLだけを検査。',
        HTML_SHA256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(), 結果=screens)
    (HERE / 'HTML表示の独立検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
