const DATA=JSON.parse(document.getElementById('report-data').textContent);
const SYMBOLS=['TOPIX','NK225'];
const NAMES={TOPIX:'TOPIXミニ',NK225:'日経マイクロ'};
const byId=id=>document.getElementById(id);

/**
 * 機能: HTMLへ埋める文字列を安全に表示する。
 * @param {string} value - 表示する文字列。
 * @returns {string} エスケープ済み文字列。
 */
function esc(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

/**
 * 機能: 金額を符号と色付きで表示する。
 * @param {number} value - 円額。
 * @param {boolean} loss - 損失絶対額を表示するか。
 * @returns {string} 数値HTML。
 */
function money(value,loss=false){const v=Math.round(value),cls=loss?'loss':v>0?'gain':v<0?'loss':'neutral';return `<span class="${cls}" data-number="${value}">${!loss&&v>0?'+':''}${v.toLocaleString('ja-JP')}円</span>`;}

/**
 * 機能: 金額利益割合や保有率を百分率にする。
 * @param {number|null} value - 0から1の割合又は欠測。
 * @returns {string} 百分率。
 */
function pct(value){return value==null?'—':(100*value).toFixed(1)+'%';}

/**
 * 機能: 商品別の保存済み全30場成績を得る。
 * @param {string} id - 配分ID。
 * @param {string} symbol - 商品。
 * @returns {object} 全期間成績。
 */
function total(id,symbol){return DATA.results[id].periods['全30'][symbol];}

/**
 * 機能: 配分と事前主案・前半選定の区分を示す。
 * @param {string} id - 配分ID。
 * @returns {string} ラベルHTML。
 */
function title(id){const c=DATA.results[id].config,b=c.budgets;let tag=id===DATA.primary?(id===DATA.selected?'事前主案・前16選定':'事前主案'):id===DATA.selected?'前16選定参考':id==='A0820'?'全30後の参考':id==='GU_HALF'?'半量対照':'単独・配分対照';return `<span class="tag">${tag}</span>${b.GU} / ${b.M3} / ${b.C03}<small>${esc(id)}</small>`;}

/**
 * 機能: 比較用の同一指標を商品別に表示する。
 * @param {string[]} ids - 対象配分の一覧。
 * @returns {string} 表の全行。
 */
function comparisonRows(ids){return ids.map(id=>`<tr data-id="${id}"><td>${title(id)}</td>${SYMBOLS.map(symbol=>{const a=total(id,symbol);return `<td>${money(a.net)}</td><td>${pct(a.profit_share)}</td><td>${a.positive_sessions} / ${a.sessions}</td><td>${money(a.max_drawdown,true)}</td>`;}).join('')}</tr>`).join('');}

/**
 * 機能: 各場の手数料後の利益・損失・収支と売買枚数を示す。
 * @param {object} a - 場又は期間の保存会計。
 * @returns {string} 商品1つの3セル。
 */
function pnlCells(a){return `<td>${money(a.profit)}</td><td>${money(a.loss,true)}</td><td>${money(a.net)}<small>${a.new_lots.toLocaleString('ja-JP')} / ${a.closed_lots.toLocaleString('ja-JP')}枚</small></td>`;}

/**
 * 機能: 選択した固定配分の全30場と補助表を描画する。
 * @returns {void} 返り値なし。
 */
function render(){
 const id=byId('method-select').value,result=DATA.results[id],b=result.config.budgets;
 byId('allocation').textContent=`TOPIX：GU ${b.GU}・M3 ${b.M3}・C03 ${b.C03}枚 ／ 日経：GU ${b.GU*2}・M3 ${b.M3*2}・C03 ${b.C03*2}枚。各枠は固定し、成績で入れ替えません。`;
 const lookup=new Map(result.rows.map(r=>[r.session+'|'+r.symbol,r]));
 byId('session-results').innerHTML=DATA.sessions.map(session=>`<tr data-session="${session}"><td>${session.replace('_Day',' デイ').replace('_Night',' ナイト')}</td>${SYMBOLS.map(s=>pnlCells(lookup.get(session+'|'+s))).join('')}</tr>`).join('')+`<tr class="total"><td>全30セッション</td>${SYMBOLS.map(s=>pnlCells(total(id,s))).join('')}</tr>`;
 // ----------------------------------------
 byId('period-results').innerHTML=SYMBOLS.map(symbol=>['前16','後14','全30'].map(period=>{const a=result.periods[period][symbol];return `<tr data-symbol="${symbol}" data-period="${period}"><td>${NAMES[symbol]}</td><td>${period}</td><td>${money(a.net)}</td><td>${pct(a.profit_share)}</td><td>${a.positive_sessions} / ${a.negative_sessions} / ${a.no_trade_sessions}</td><td>${a.campaigns}</td><td>${money(a.fees,true)}</td><td>${money(a.max_drawdown,true)}</td><td>${money(a.best_three_removed)}</td></tr>`;}).join('')).join('');
 byId('source-results').innerHTML=SYMBOLS.map(symbol=>['GU','M3','C03'].map(source=>{const rows=result.rows.filter(r=>r.symbol===symbol),sum=field=>rows.reduce((v,r)=>v+r.source_totals[source][field],0),a=DATA.source_contributions[id]?.['全30']?.[symbol]?.[source];return `<tr data-symbol="${symbol}" data-source="${source}"><td>${NAMES[symbol]}</td><td>${source}</td><td>${a?money(a.profit):'—'}</td><td>${a?money(a.loss,true):'—'}</td><td>${money(sum('net'))}</td><td>${money(sum('fees'),true)}</td><td>${a?a.campaigns:'—'}</td></tr>`;}).join('')).join('');
}

/**
 * 機能: 保存済み事後相関を、売買判定と区別して表示する。
 * @returns {void} 返り値なし。
 */
function renderDiversity(){
 const corr=v=>v==null?'—':v.toFixed(3);
 byId('diversity-results').innerHTML=SYMBOLS.map(symbol=>(DATA.diversity[symbol]?.pairs||[]).map(p=>`<tr><td>${NAMES[symbol]}</td><td>${p.sources.map(esc).join(' × ')}</td><td>${corr(p.session_correlation)}</td><td>${corr(p.minute_correlation)}</td><td>${pct(p.opposite_active_fraction)}</td><td>${pct(p.same_active_fraction)}</td><td>${pct(p.mutual_active_fraction)}</td></tr>`).join('')).join('');
}

/**
 * 機能: 同量GU対照に対する追加源のリスクと収支を表示する。
 * @returns {void} 返り値なし。
 */
function renderRisk(){
 byId('risk-results').innerHTML=Object.keys(DATA.risk_attribution).map(id=>SYMBOLS.map(symbol=>{const r=DATA.risk_attribution[id]['全30'][symbol],a=r.allocated_gu_only,b=r.portfolio;return `<tr data-id="${id}" data-symbol="${symbol}"><td>${esc(id)}</td><td>${NAMES[symbol]}</td><td>${money(a.net)}</td><td>${money(b.net)}</td><td>${money(a.max_drawdown,true)}</td><td>${money(b.max_drawdown,true)}</td><td>${a.return_drawdown.toFixed(3)} → ${b.return_drawdown.toFixed(3)}</td><td>${a.positive_sessions} → ${b.positive_sessions}</td></tr>`;}).join('')).join('');
}

/**
 * 機能: 事前主案の赤字場を源別収支へ分解して表示する。
 * @returns {void} 返り値なし。事後説明だけに使用する。
 */
function renderFailures(){
 byId('failure-results').innerHTML=SYMBOLS.map(symbol=>(DATA.diagnosis[DATA.primary]?.[symbol]||[]).map(row=>`<tr data-symbol="${symbol}" data-session="${row.session}"><td>${NAMES[symbol]}</td><td>${row.session.replace('_Day',' デイ').replace('_Night',' ナイト')}</td>${['GU','M3','C03'].map(source=>`<td>${money(row.sources[source].net)}</td>`).join('')}<td>${money(row.net)}</td></tr>`).join('')).join('');
}

// ----------------------------------------
for(const c of DATA.catalog){const o=document.createElement('option');o.value=c.id;o.textContent=`${c.id}｜GU ${c.budgets.GU}・M3 ${c.budgets.M3}・C03 ${c.budgets.C03}`;byId('method-select').append(o);}
byId('method-select').value=DATA.primary;byId('method-select').addEventListener('change',render);
byId('comparison').querySelector('tbody').innerHTML=comparisonRows(DATA.highlights);
byId('all-comparison').innerHTML=comparisonRows(DATA.catalog.map(c=>c.id));
const lines=Array.isArray(DATA.conclusion)?DATA.conclusion:[];
byId('conclusion').innerHTML=(lines.length?lines:['事前主案は GU 6・M3 2・C03 2 枚。前16場で選んだ参考と、単独運転・半量GUを同じ条件で比較します。']).map(v=>`<p>${esc(v)}</p>`).join('');
render();renderDiversity();renderRisk();renderFailures();
window.reportTest={data:DATA,render,total,comparisonRows};
