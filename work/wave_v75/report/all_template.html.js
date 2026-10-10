
"use strict";
const D=JSON.parse(document.getElementById('report-data').textContent),LOOKUP=new Map(D.methods.map(m=>[m.id,m])),STATE={symbol:'TOPIX',period:'全29',id:D.selectedIds.find(id=>LOOKUP.has(id))??D.methods[0].id},NUMBER=new Intl.NumberFormat('ja-JP',{maximumFractionDigits:0});
/**
 * 機能: 表示値のHTML特殊文字をエスケープする。
 * @param {unknown} v - 表示値。
 * @returns {string} 安全な文字列。
 */
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/**
 * 機能: 金額を円と正負色で表示する。
 * @param {number|null} v - 金額。
 * @param {boolean} signed - 正符号を付けるか。
 * @param {string} context - 損失又は手数料の文脈色。
 * @returns {string} 金額HTML。
 */
function money(v,signed=false,context=''){ return v==null?'—':`<span class="money ${context==='loss'?'negative':context==='fee'?'muted':v>0?'positive':v<0?'negative':''}">${signed&&v>0?'+':''}${NUMBER.format(v)}円</span>`;}
/**
 * 機能: 比率を百分率として表示する。
 * @param {number|null} v - 比率。
 * @returns {string} 百分率又はダッシュ。
 */
function pct(v){return v==null?'—':(v*100).toFixed(1)+'%';}
/**
 * 機能: 金額・損失割合・取引数の共通テーブルを作る。
 * @param {Array<object>} rows - ラベルと会計。
 * @returns {string} 全明細金額表のHTML。
 */
function table(rows){return `<div class="table-wrap"><table class="primary-table"><thead><tr><th>対象</th><th>利益</th><th>損失</th><th>収支</th><th>損失割合</th><th>取引数</th><th>勝ち／負け枚数</th><th>手数料</th><th>平均一取引</th></tr></thead><tbody>${rows.map(({label,a,total=false})=>`<tr${total?' class="total"':''}><td>${esc(label)}</td><td>${money(a.profit)}</td><td>${money(a.loss,false,'loss')}</td><td>${money(a.net,true)}</td><td>${pct(a.money_loss_share)}</td><td>${a.trades}</td><td>${a.winning_lots}／${a.losing_lots}</td><td>${money(a.fees,false,'fee')}</td><td>${money(a.trades?a.net/a.trades:null,true)}</td></tr>`).join('')}</tbody></table></div>`;}
/**
 * 機能: 群・機構の絞込みと同銘柄指標による表示順を適用する。
 * @returns {Array<object>} 条件一覧。
 */
function filtered(){const group=document.getElementById('group').value,ref=document.getElementById('family').value,sort=document.getElementById('sort').value;return D.methods.filter(m=>(group==='all'||m.config.group===group)&&(ref==='all'||m.config.family===Number(ref))).sort((a,b)=>{const x=a.periods[STATE.period][STATE.symbol],y=b.periods[STATE.period][STATE.symbol];if(sort==='net')return y.net-x.net||a.id.localeCompare(b.id);if(sort==='share')return (x.money_loss_share??Infinity)-(y.money_loss_share??Infinity)||y.net-x.net||a.id.localeCompare(b.id);return a.id.localeCompare(b.id);});}
/**
 * 機能: 条件一覧を現在の銘柄と期間で更新する。
 * @returns {void} 返り値なし。
 */
function ranking(){const rows=filtered();document.getElementById('count').textContent=`${rows.length}／${D.methods.length}条件`;document.getElementById('ranking').innerHTML=`<table class="ranking-table"><thead><tr><th>条件ID</th><th>群</th><th>利益</th><th>損失</th><th>収支</th><th>損失割合</th><th>取引数</th><th>平均利益／損失</th><th>全29 TOP収支</th><th>全29 NK収支</th></tr></thead><tbody>${rows.map(m=>{const a=m.periods[STATE.period][STATE.symbol];return `<tr${m.id===STATE.id?' class="selected-row"':''}><td><button class="method-link" data-id="${esc(m.id)}">${esc(m.id)}</button>${D.selectedIds.includes(m.id)?' ★':D.representativeIds.includes(m.id)?' ◇':''}</td><td>${esc(m.config.group)}</td><td>${money(a.profit)}</td><td>${money(a.loss,false,'loss')}</td><td>${money(a.net,true)}</td><td>${pct(a.money_loss_share)}</td><td>${a.trades}</td><td>${a.payoff==null?'—':a.payoff.toFixed(2)}</td><td>${money(m.periods.全29.TOPIX.net,true)}</td><td>${money(m.periods.全29.NK225.net,true)}</td></tr>`;}).join('')}</tbody></table>`;document.querySelectorAll('.method-link').forEach(b=>b.addEventListener('click',()=>choose(b.dataset.id)));}
/**
 * 機能: 条件IDの選択をhashと全場表示へ反映する。
 * @param {string} id - 条件ID。
 * @returns {void} 返り値なし。
 */
function choose(id){if(!LOOKUP.has(id))return;STATE.id=id;document.getElementById('method').value=id;const hash=encodeURIComponent(id);if(location.hash.slice(1)!==hash)location.hash=hash;condition();ranking();}
/**
 * 機能: 選択した条件の説明・三期間・全29場を表示する。
 * @returns {void} 返り値なし。
 */
function condition(){const m=LOOKUP.get(STATE.id),symbol=STATE.symbol;document.getElementById('description').textContent=m.configText;document.getElementById('selected-note').textContent=D.selectedIds.includes(m.id)?'★ 前16で固定した主代表。後13で選び直していません。':'全条件の閲覧用。全29で良く見える条件を未見採用候補と呼びません。';document.getElementById('period-table').innerHTML=table(['前16','後13','全29'].map(p=>({label:p,a:m.periods[p][symbol],total:p==='全29'})));document.getElementById('sessions').innerHTML=table([...D.sessions.map(s=>({label:s.replace('_Day',' デイ').replace('_Night',' ナイト'),a:m.rows.find(r=>r.session===s&&r.symbol===symbol)})),{label:'全29合計',a:m.periods.全29[symbol],total:true}]);}
/**
 * 機能: 銘柄と期間を読み直し、一覧と選択会計を更新する。
 * @returns {void} 返り値なし。
 */
function render(){STATE.symbol=document.getElementById('symbol').value;STATE.period=document.getElementById('period').value;ranking();condition();}
// ----------------------------------------
// 保存結果だけで初期化し、IDの直接リンクにも対応する。
if(D.scopeText)document.getElementById('scope-description').textContent=D.scopeText;document.title=D.title;document.getElementById('title').textContent=D.title;document.getElementById('main-link').href=D.mainUrl;document.getElementById('method').innerHTML=D.methods.map(m=>`<option value="${esc(m.id)}">${esc(m.id)}</option>`).join('');document.getElementById('notes').innerHTML=D.notes.map(n=>`<li>${esc(n)}</li>`).join('');['symbol','period','group','family','sort'].forEach(id=>document.getElementById(id).addEventListener('change',render));document.getElementById('method').addEventListener('change',e=>choose(e.target.value));window.addEventListener('hashchange',()=>{const id=decodeURIComponent(location.hash.slice(1));if(LOOKUP.has(id)){STATE.id=id;document.getElementById('method').value=id;render();}});const initial=decodeURIComponent(location.hash.slice(1));if(LOOKUP.has(initial))STATE.id=initial;document.getElementById('method').value=STATE.id;render();window.reportTest={D,STATE,render,choose,filtered,condition,ranking};
