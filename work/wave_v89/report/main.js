const DATA=JSON.parse(document.getElementById('report-data').textContent);
const SYMBOLS=['TOPIX','NK225'];
const NAMES={TOPIX:'TOPIXミニ',NK225:'日経マイクロ'};
const SOURCES=['GU','M3','C03'];

/**
 * 機能: 文書内の指定要素を取得する。
 * @param {string} id - 要素ID。
 * @returns {HTMLElement|null} 対象要素。
 */
const byId=id=>document.getElementById(id);

/**
 * 機能: HTMLへ埋める文字列を安全に表示する。
 * @param {string} value - 表示する文字列。
 * @returns {string} エスケープ済み文字列。
 */
function esc(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

/**
 * 機能: 円額を符号と色付きで表示する。
 * @param {number} value - 円額。
 * @param {boolean} loss - 損失絶対額を表示するか。
 * @returns {string} 数値HTML。
 */
function money(value,loss=false){const rounded=Math.round(value),v=rounded===0?0:rounded,cls=loss?'loss':v>0?'gain':v<0?'loss':'neutral';return `<span class="${cls}" data-number="${value}">${!loss&&v>0?'+':''}${v.toLocaleString('ja-JP')}円</span>`;}

/**
 * 機能: 金額利益割合を百分率にする。
 * @param {number|null} value - 0から1の割合又は未定義。
 * @returns {string} 百分率。
 */
function pct(value){return value==null?'—':(100*value).toFixed(1)+'%';}

/**
 * 機能: 商品別の全30場成績を得る。
 * @param {string} id - 条件ID。
 * @param {string} symbol - 商品。
 * @returns {object} 保存済み全期間成績。
 */
function total(id,symbol){return DATA.results[id].periods['全30'][symbol];}

/**
 * 機能: ゲートの条件を短い日本語へ変換する。
 * @param {object} config - 固定条件。
 * @returns {string} ゲート名。
 */
function gateName(config){const g=config.gate,scope=g.history_mode==='carry'?'成績持越':'場ごと';if(g.mode==='all')return '常時参加';if(g.mode==='streak')return `${g.loss_count}連敗で停止・${scope}`;return `${g.window}親・${Math.round(g.threshold*100)}%${g.reverse?'未満':'以上'}・${scope}`;}

/**
 * 機能: 選択した停止と再開の条件を平易に示す。
 * @param {object} config - 固定条件。
 * @returns {string} 判定の説明文。
 */
function rule(config){const g=config.gate;if(g.mode==='all')return '三手法へ固定枠を配分し、各手法の新規を常に許可します。';const suffix='同じ時計の結果は使いません。'+(g.history_mode==='carry'?'セッションを跨いで過去成績だけを引き継ぎます。':'過去成績は各セッションの開始でリセットします。');if(g.mode==='streak')return `仮想成績が${g.loss_count}連敗した手法の新規を休み、仮想親が0以上で終われば再開します。${suffix}`;return `直近${g.window}仮想親の手数料後利益割合が${Math.round(g.threshold*100)}%${g.reverse?'未満':'以上'}の手法だけ、新規に参加します。${suffix}`;}

/**
 * 機能: 条件IDと配分、事前主案・参考・対照の区分を表示する。
 * @param {string} id - 条件ID。
 * @returns {string} ラベルHTML。
 */
function title(id){const c=DATA.results[id].config,b=c.budgets;let tag=id===DATA.primary?(id===DATA.selected?'事前主案・前16選定':'事前主案'):id===DATA.selected?'前16選定参考':c.gate.mode==='all'?'常時参加対照':DATA.both_eighty.includes(id)?'両商品80%候補':'比較条件';return `<span class="tag">${tag}</span>${esc(gateName(c))}<small>GU ${b.GU} / M3 ${b.M3} / C03 ${b.C03}｜${esc(id)}</small>`;}

/**
 * 機能: 比較用の同一指標を商品別に表示する。
 * @param {string[]} ids - 対象条件ID。
 * @returns {string} 表の全行。
 */
function comparisonRows(ids){return ids.map(id=>`<tr data-id="${id}"><td>${title(id)}</td>${SYMBOLS.map(symbol=>{const a=total(id,symbol);return `<td>${money(a.net)}<small>${a.campaigns}親</small></td><td>${pct(a.profit_share)}</td><td>${a.positive_sessions} / ${a.sessions}</td><td>${money(a.max_drawdown,true)}</td>`;}).join('')}</tr>`).join('');}

/**
 * 機能: 手数料後の利益・損失・収支と売買枚数を示す。
 * @param {object} a - 場又は期間の保存会計。
 * @returns {string} 商品1つの3セル。
 */
function pnlCells(a){return `<td>${money(a.profit)}</td><td>${money(a.loss,true)}</td><td>${money(a.net)}<small>${a.new_lots.toLocaleString('ja-JP')} / ${a.closed_lots.toLocaleString('ja-JP')}枚</small></td>`;}

/**
 * 機能: 選択条件の全30場、期間別、源別、見送り効果を描画する。
 * @returns {void} 返り値なし。
 */
function render(){
 const id=byId('method-select').value,result=DATA.results[id],b=result.config.budgets;
 byId('method-rule').textContent=rule(result.config);
 byId('allocation').textContent=`TOPIX：GU ${b.GU}・M3 ${b.M3}・C03 ${b.C03}枚 ／ 日経：GU ${b.GU*2}・M3 ${b.M3*2}・C03 ${b.C03*2}枚。各枠を固定し、親の途中で増減しません。`;
 const lookup=new Map(result.rows.map(r=>[r.session+'|'+r.symbol,r]));
 byId('session-results').innerHTML=DATA.sessions.map(session=>`<tr data-session="${session}"><td>${session.replace('_Day',' デイ').replace('_Night',' ナイト')}</td>${SYMBOLS.map(symbol=>pnlCells(lookup.get(session+'|'+symbol))).join('')}</tr>`).join('')+`<tr class="total"><td>全30セッション</td>${SYMBOLS.map(symbol=>pnlCells(total(id,symbol))).join('')}</tr>`;
 // ----------------------------------------
 byId('period-results').innerHTML=SYMBOLS.map(symbol=>['前16','後14','全30'].map(period=>{const a=result.periods[period][symbol];return `<tr data-symbol="${symbol}" data-period="${period}"><td>${NAMES[symbol]}</td><td>${period}</td><td>${money(a.net)}</td><td>${pct(a.profit_share)}</td><td>${a.positive_sessions} / ${a.negative_sessions} / ${a.no_trade_sessions}</td><td>${a.campaigns}</td><td>${money(a.fees,true)}</td><td>${money(a.max_drawdown,true)}</td><td>${money(a.best_three_removed)}</td></tr>`;}).join('')).join('');
 byId('source-results').innerHTML=SYMBOLS.map(symbol=>SOURCES.map(source=>{const rows=result.rows.filter(r=>r.symbol===symbol),sum=field=>rows.reduce((v,r)=>v+r.source_totals[source][field],0),a=DATA.source_contributions[id]?.['全30']?.[symbol]?.[source];return `<tr data-symbol="${symbol}" data-source="${source}"><td>${NAMES[symbol]}</td><td>${source}</td><td>${a?money(a.profit):'—'}</td><td>${a?money(a.loss,true):'—'}</td><td>${money(sum('net'))}</td><td>${money(sum('fees'),true)}</td><td>${a?a.campaigns:'—'}</td></tr>`;}).join('')).join('');
 byId('gate-results').innerHTML=SYMBOLS.map(symbol=>['前16','後14','全30'].map(period=>{const a=result.periods[period][symbol];return `<tr data-symbol="${symbol}" data-period="${period}"><td>${NAMES[symbol]}</td><td>${period}</td><td>${a.gate_eligible}</td><td>${a.gate_allowed}</td><td>${a.gate_rejected}</td><td>${a.gate_warmup}</td><td>${a.virtual_campaigns}</td></tr>`;}).join('')).join('');
 byId('difference-results').innerHTML=SYMBOLS.map(symbol=>{const d=DATA.differences[id]?.['全30']?.[symbol];if(!d)return '';return `<tr data-symbol="${symbol}"><td>${NAMES[symbol]}</td><td>${money(d.base_net)}</td><td>${money(d.actual_net)}</td><td>${money(d.saved_loss)}</td><td>${money(d.missed_profit,true)}</td><td>${money(d.delta)}</td></tr>`;}).join('');
}

/**
 * 機能: 事前主案が回復初動を見送り、後から再開した4親を表示する。
 * @returns {void} 返り値なし。将来の親収支は事後説明として表示する。
 */
function renderCases(){byId('case-results').innerHTML=DATA.cases.map((value,index)=>`<tr data-case="${index}"><td>${NAMES[value.symbol]}</td><td>${value.session.replace('_Day',' デイ').replace('_Night',' ナイト')}</td><td>${esc(value.clock.slice(11,19))}</td><td>${pct(value.past_share)}</td><td>${value.accepted?'参加を再開':'見送り'}</td><td>${money(value.base_net)}</td></tr>`).join('');}

// ----------------------------------------

for(const c of DATA.catalog){const option=document.createElement('option');option.value=c.id;option.textContent=`${c.id}｜${gateName(c)}｜${c.budgets.GU}/${c.budgets.M3}/${c.budgets.C03}`;byId('method-select').append(option);}
byId('method-select').value=DATA.primary;
byId('method-select').addEventListener('change',render);
byId('comparison').querySelector('tbody').innerHTML=comparisonRows(DATA.highlights);
byId('all-comparison').innerHTML=comparisonRows(DATA.catalog.map(c=>c.id));
const lines=Array.isArray(DATA.conclusion)?DATA.conclusion:[];
byId('conclusion').innerHTML=(lines.length?lines:['事前主案はGU 6・M3逆 2・C03 2枚。直近16仮想親の利益割合60%以上の手法だけ参加し、成績だけを次セッションへ引き継ぎます。']).map(value=>`<p>${esc(value)}</p>`).join('');
render();renderCases();
window.reportTest={data:DATA,render,total,comparisonRows,gateName,rule};
