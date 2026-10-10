"use strict";
const D=JSON.parse(document.getElementById('report-data').textContent),STATE={selectedId:null,symbol:'TOPIX',period:'全29'},NUMBER=new Intl.NumberFormat('ja-JP',{maximumFractionDigits:0});

/**
 * 機能: 表示文字をHTMLへ安全に埋め込む。
 * @param {unknown} v - 表示値。
 * @returns {string} 安全な文字列。
 */
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

/**
 * 機能: 円金額を文脈別に色分けする。
 * @param {number|null} v - 金額。
 * @param {boolean} signed - 正符号の有無。
 * @param {string} context - 損失又は費用。
 * @returns {string} 金額のHTML。
 */
function money(v,signed=false,context=''){return v==null?'—':`<span class="money ${context==='loss'?'negative':context==='fee'?'muted':v>0?'positive':v<0?'negative':''}">${signed&&v>0?'+':''}${NUMBER.format(v===0?0:v)}円</span>`;}

/**
 * 機能: 比率を百分率にする。
 * @param {number|null} v - 比率。
 * @returns {string} 百分率又はダッシュ。
 */
function pct(v){return v==null?'—':(v*100).toFixed(1)+'%';}

/**
 * 機能: 全建値金額と一組会計を同じ形式の表にする。
 * @param {Array<object>} rows - ラベルと会計。
 * @returns {string} 金額表のHTML。
 */
function table(rows){return `<div class="table-wrap"><table class="primary-table"><thead><tr><th>対象</th><th>利益</th><th>損失</th><th>収支</th><th>金額利益割合</th><th>利益／損失</th><th>組数</th><th>組勝率</th><th>勝ち／負け枚数</th><th>手数料</th></tr></thead><tbody>${rows.map(({label,a,total=false})=>{if(!a)return `<tr><td>${label}</td><td colspan="9" class="muted">未実施</td></tr>`;return `<tr${total?' class="total"':''}><td>${label}</td><td>${money(a.profit)}</td><td>${money(a.loss,false,'loss')}</td><td>${money(a.net,true)}</td><td>${pct(a.profit_share)}${a.goal80?' ✓':''}</td><td>${a.profit_loss_ratio==null?'—':a.profit_loss_ratio.toFixed(2)}</td><td>${a.trades}</td><td>${pct(a.win_rate)}</td><td>${a.winning_lots}／${a.losing_lots}</td><td>${money(a.fees,false,'fee')}</td></tr>`;}).join('')}</tbody></table></div>`;}

/**
 * 機能: フィルターで選ばれた固定条件を並べる。
 * @returns {Array<object>} 並べ替え済み条件列。
 */
function filtered(){const family=document.getElementById('family').value,policy=document.getElementById('policy').value,allocation=document.getElementById('allocation').value,sort=document.getElementById('sort').value;return D.methods.filter(m=>(!family||m.config.family===family)&&(!policy||String(m.config.policy)===policy)&&(!allocation||String(m.config.allocation)===allocation)).sort((x,y)=>{const a=x.periods[STATE.period]?.[STATE.symbol],b=y.periods[STATE.period]?.[STATE.symbol];if(sort==='id')return x.id.localeCompare(y.id);if(!a&&!b)return x.id.localeCompare(y.id);if(!a)return 1;if(!b)return -1;const av=sort==='net'?a.net:a.profit_share,bv=sort==='net'?b.net:b.profit_share;return (bv??-Infinity)-(av??-Infinity)||x.id.localeCompare(y.id);});}

/**
 * 機能: 一覧の金額割合と全明細損益を表示する。
 * @param {Array<object>} methods - フィルター後の条件。
 * @returns {string} 一覧HTML。
 */
function ranking(methods){return `<div class="table-wrap"><table class="ranking-table"><thead><tr><th>順</th><th>固定ID</th><th>金額利益割合</th><th>利益／損失</th><th>利益</th><th>損失</th><th>収支</th><th>組数</th><th>組勝率</th><th>追加回数</th></tr></thead><tbody>${methods.map((m,i)=>{const a=m.periods[STATE.period]?.[STATE.symbol],label=D.selectedIds.includes(m.id)?'［前半固定代表］':m.id===D.baselineId?'［基準］':'';return `<tr data-method-id="${esc(m.id)}"${m.id===STATE.selectedId?' class="total"':''}><td>${i+1}</td><td><button class="session-link condition-link" data-id="${esc(m.id)}">${esc(m.id)}</button><span class="small">${label}</span></td>${a?`<td>${pct(a.profit_share)}${a.goal80?' ✓':''}</td><td>${a.profit_loss_ratio==null?'—':a.profit_loss_ratio.toFixed(2)}</td><td>${money(a.profit)}</td><td>${money(a.loss,false,'loss')}</td><td>${money(a.net,true)}</td><td>${a.trades}</td><td>${pct(a.win_rate)}</td><td>${a.adds}</td>`:'<td colspan="8" class="muted">未実施</td>'}</tr>`;}).join('')}</tbody></table></div>`;}

/**
 * 機能: 一条件の期間比較と全30場を表示する。
 * @param {object} m - 固定条件。
 * @returns {string} 条件詳細のHTML。
 */
function condition(m){return `<h2>${esc(m.id)}</h2><p class="small">${esc(m.configText)}</p><h3>期間比較</h3><div class="period-table">${table(D.periodNames.map(p=>({label:esc(p),a:m.periods[p]?.[STATE.symbol],total:p===STATE.period})))}</div><h3>全30セッション</h3><div class="session-table">${table([...D.sessions.map(session=>({label:esc(session.replace('_Day',' デイ').replace('_Night',' ナイト')),a:m.rows.find(r=>r.session===session&&r.symbol===STATE.symbol)})),{label:'全29合計',a:m.periods.全29[STATE.symbol],total:true},{label:'全30合計',a:m.periods.全30?.[STATE.symbol],total:true}])}</div><p class="small">利益・損失は初回・追加の建値別に計算して合算します。組勝率は全返済で判定し、追加玉の勝敗数ではありません。</p>`;}

/**
 * 機能: 選択条件とURLのIDを更新する。
 * @param {string} id - 固定条件のID。
 * @returns {void} 返り値なし。
 */
function choose(id){if(!D.methods.some(m=>m.id===id))return;STATE.selectedId=id;location.hash=encodeURIComponent(id);render();}

/**
 * 機能: 一覧と選択条件を現在の商品・期間へ更新する。
 * @returns {void} 返り値なし。
 */
function render(){STATE.symbol=document.getElementById('symbol').value;STATE.period=document.getElementById('period').value;const rows=filtered(),count=rows.filter(m=>m.periods[STATE.period]?.[STATE.symbol]).length;document.getElementById('count').textContent=`固定${D.methods.length}条件／表示${rows.length}条件、選択期間の実施${count}条件。`;document.getElementById('ranking').innerHTML=ranking(rows);document.getElementById('ranking').querySelectorAll('[data-id]').forEach(b=>b.addEventListener('click',()=>choose(b.dataset.id)));const selected=D.methods.find(m=>m.id===STATE.selectedId);document.getElementById('condition').innerHTML=selected?condition(selected):'<p>条件IDを選択してください。</p>';}

// ----------------------------------------
// 保存した固定条件だけを表示し、ID付きURLから初期選択を復元する。
document.title=D.title;document.getElementById('title').textContent=D.title;document.getElementById('main-link').href=D.mainUrl;document.getElementById('notes').innerHTML=D.notes.map(x=>`<li>${esc(x)}</li>`).join('');const hash=decodeURIComponent(location.hash.slice(1));STATE.selectedId=D.methods.some(m=>m.id===hash)?hash:D.selectedIds[0];document.querySelectorAll('#filters select').forEach(e=>e.addEventListener('change',render));render();window.reportTest={D,STATE,render,choose,filtered,condition,ranking,table};
