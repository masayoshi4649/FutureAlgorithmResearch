const data=JSON.parse(document.getElementById('report-data').textContent);
const symbols=['TOPIX','NK225'];
const names={TOPIX:'TOPIXミニ',NK225:'日経マイクロ'};

/**
 * 機能: 識別番号に対応する表示要素を取得する。
 * @param {string} id - 要素の識別番号。
 * @returns {HTMLElement|null} 該当要素又は未存在時のnull。
 */
const byId=id=>document.getElementById(id);

/**
 * 機能: 文字列をHTML表示用に安全に変換する。
 * @param {string|number} value - 表示する文字列又は数値。
 * @returns {string} 特殊文字を置換した文字列。
 */
function escapeHtml(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

/**
 * 機能: 金額と枚数を原数値付きのセルへ表示する。
 * @param {number} value - 手数料後の円額。
 * @param {string} type - profit、loss又はnet。
 * @param {string} small - 補助となる枚数表示。
 * @returns {string} 金額セルのHTML。
 */
function money(value,type='net',small=''){
 const rounded=value===0?0:Math.round(value),className=type==='loss'&&value>0||type==='net'&&value<0||type==='cost_change'&&value>0?'loss':value>0||type==='cost_change'&&value<0?'positive':'muted';
 const sign=(type==='net'||type==='cost_change')&&rounded>0?'+':'';
 return `<td class="money ${className}"><span data-number="${value}">${sign}${rounded.toLocaleString('ja-JP')}円</span>${small?`<small>${escapeHtml(small)}</small>`:''}</td>`;
}

/**
 * 機能: 金額利益割合を小数一桁で表示する。
 * @param {number|null} value - 総利益を総利益と総損失の和で割った値。
 * @returns {string} 割合又は未定義の表示。
 */
function percent(value){return value==null?'—':(value*100).toFixed(1)+'%';}

/**
 * 機能: 配分と入口・取消・途中返済を短く説明する。
 * @param {object} config - 事前固定した条件。
 * @returns {string} 機械的条件の日本語説明。
 */
function rule(config){
 let text=config.selection==='regime'?'追従と指値反発のどちらか一源だけが全枠を使用します。':`追従${config.trend_budget}枚・指値反発${config.range_budget}枚の固定枠で独立運転します（日経は各2倍）。`;
 if(config.selection==='fixed')text+='現在状態による新規の選択は加えません。';
 else text+=`双方のERが${config.high_er}以上で共通方向を満たせば追従、${config.low_er}以下で範囲内・共通進行なしなら指値反発。${config.confirm_seconds}秒の確認後に許可し、中間や欠測は新規を見送ります。`;
 if(config.cancel_pending)text+='指値待機中に条件が失効すれば、次の有効気配で成立を先に確認してから未約定を取消します。';
 else if(config.range_budget)text+='予約済み指値は状態が変わっても待機を続けます。';
 if(config.exit_opposite_range)text+='反発保有中に反対の追従状態が成立すれば全返済します。';
 if(config.range_budget)text+=config.improve_limit?'指値成立時は当該の買ask／売bidで約定する気配改善代理です。':'指値成立時に気配が有利でも元の指値で支払う、価格改善なし対照です。';
 if(config.activate_anchor)text+='往復へ参加可能になった瞬間に、未予約・未保有の基準を当時価格へ更新します。';
 return text;
}

/**
 * 機能: 対照と理論主・前半代表の全期間比較を表示する。
 * @returns {undefined} 表を更新するため返り値はありません。
 */
function comparison(){
 byId('comparison').querySelector('tbody').innerHTML=data.highlights.map(id=>{
  const config=data.catalog.find(c=>c.id===id);
  const labels=[];if(id===data.primary)labels.push('理論主');if(id===data.selected)labels.push('前16場の参考代表');if(id==='M82_Q')labels.push('固定8：2');if(id==='J10_Q')labels.push('追従のみ');if(id==='O10_Q')labels.push('反発のみ');
  const description=config.selection==='regime'?'状態で一源だけ全枠':config.selection==='gated_fixed'?`状態で追従${config.trend_budget}・反発${config.range_budget}の各枠へ参加`:config.range_budget===0?`追従${config.trend_budget}枚のみ`:config.trend_budget===0?`指値反発${config.range_budget}枚のみ`:`追従${config.trend_budget}・反発${config.range_budget}の独立並行`;
  let text=`<tr data-id="${id}"><td><span class="method-id">${id}</span><span class="tag">${labels.join('・')}</span><span class="tag">${description}</span></td>`;
  for(const symbol of symbols){const r=data.results[id].periods['全30'][symbol];text+=money(r.net,'net',`${r.campaigns}親`)+`<td>${percent(r.profit_share)}</td><td>${r.positive_sessions} / ${r.session_count}</td>`+money(r.equity_drawdown,'loss');}
  return text+'</tr>';
 }).join('');
}

/**
 * 機能: 全30場と合計の金額・利益玉・損失玉枚数を表示する。
 * @param {object} result - 選択条件の保存済み会計。
 * @returns {undefined} 表を更新するため返り値はありません。
 */
function sessions(result){
 const rows=data.sessions.map(session=>({session,values:Object.fromEntries(symbols.map(symbol=>[symbol,result.rows.find(r=>r.symbol===symbol&&r.session===session)]))}));
 rows.push({session:'全30場 合計',values:result.periods['全30'],total:true});
 byId('session-results').innerHTML=rows.map(item=>{
  let text=`<tr data-session="${item.session}"${item.total?' class="total"':''}><td>${escapeHtml(item.session.replace('_Day',' デイ').replace('_Night',' ナイト'))}</td>`;
  for(const symbol of symbols){const r=item.values[symbol];text+=money(r.profit,'profit',`${r.winning_lots.toLocaleString('ja-JP')}枚`)+money(r.loss,'loss',`${r.losing_lots.toLocaleString('ja-JP')}枚`)+money(r.net,'net',`勝−負 ${(r.winning_lots-r.losing_lots).toLocaleString('ja-JP')}枚`);}
  return text+'</tr>';
 }).join('');
}

/**
 * 機能: 期間、戦略別、売買方向別の会計を表示する。
 * @param {object} result - 選択条件の保存済み会計。
 * @returns {undefined} 表を更新するため返り値はありません。
 */
function details(result){
 byId('period-results').innerHTML=['前16','後14','全30','デイ','ナイト'].flatMap(period=>symbols.map(symbol=>{
  const r=result.periods[period][symbol];return `<tr data-period="${period}" data-symbol="${symbol}"><td>${period}</td><td>${names[symbol]}</td>`+money(r.net)+`<td>${percent(r.profit_share)}</td><td>${r.positive_sessions} / ${r.losing_sessions} / ${r.no_trade_sessions}</td><td>${r.campaigns}</td>`+money(r.fees,'loss')+money(r.equity_drawdown,'loss')+money(r.without_best_day.net)+'</tr>';
 })).join('');
 byId('source-results').innerHTML=symbols.flatMap(symbol=>['J2','O06'].map(source=>{
  const r=result.periods['全30'][symbol].sources[source];return `<tr data-symbol="${symbol}" data-source="${source}"><td>${names[symbol]}</td><td>${source==='J2'?'J2 追従':'O06 指値反発'}</td>`+money(r.profit,'profit')+money(r.loss,'loss')+money(r.net)+money(r.fees,'loss')+`<td>${r.campaigns}</td></tr>`;
 })).join('');
 byId('direction-results').innerHTML=symbols.flatMap(symbol=>['買い','売り'].map(direction=>{
  const r=result.periods['全30'][symbol].directions[direction];return `<tr data-symbol="${symbol}" data-direction="${direction}"><td>${names[symbol]}</td><td>${direction}</td>`+money(r.profit,'profit')+money(r.loss,'loss')+money(r.net)+`<td>${r.campaigns}</td></tr>`;
 })).join('');
}

/**
 * 機能: 単独又は固定併用の対照と選択手法の会計差を表示する。
 * @param {string} id - 選択条件の識別番号。
 * @returns {undefined} 会計差を更新するため返り値はありません。
 */
function causes(id){
 const config=data.catalog.find(c=>c.id===id),suffix=config.improve_limit?'_Q':'';
 const references=config.range_budget===0?[`J10${suffix}`]:config.trend_budget===0?[`O10${suffix}`]:config.selection==='fixed'&&config.trend_budget===8&&config.range_budget===2?[`J8${suffix}`,`J10${suffix}`]:[`M82${suffix}`,`J10${suffix}`];
 byId('cause-results').innerHTML=symbols.flatMap(symbol=>references.map(reference=>{
  const a=data.results[id].periods['全30'][symbol],b=data.results[reference].periods['全30'][symbol];return `<tr data-symbol="${symbol}" data-reference="${reference}"><td>${names[symbol]}</td><td>${reference}</td>`+['net','profit','loss','fees'].map(field=>money(a[field]-b[field],field==='loss'||field==='fees'?'cost_change':'net')).join('')+`<td>${a.campaigns-b.campaigns}</td></tr>`;
 })).join('');
 const texts=data.cause_notes?.[id]||[];
 byId('cause-text').innerHTML=texts.map(text=>`<p>${escapeHtml(text)}</p>`).join('');
}

/**
 * 機能: 選択中の手法の説明と全会計を一括更新する。
 * @returns {undefined} 画面を更新するため返り値はありません。
 */
function render(){
 const id=byId('method-select').value,config=data.catalog.find(c=>c.id===id),result=data.results[id];
 byId('method-title').textContent=id+(id===data.primary?' · 理論主':id==='M82_Q'?' · 固定8：2配分':id===data.selected?' · 前16場の参考代表':'');
 byId('method-rule').textContent=rule(config);sessions(result);details(result);causes(id);
}

// ----------------------------------------
byId('conclusion').innerHTML=data.conclusion.map(text=>`<p class="conclusion-line">${escapeHtml(text)}</p>`).join('');
if(data.selected==='J8_Q'){const note=document.createElement('p');note.className='note';note.textContent='参考代表J8_Qは追従を8枚／16枚に縮小しただけで、新たな方向予測手法ではありません。J10_Qとの金額割合の微差には注文合計手数料の切捨ても影響します。';byId('comparison-section').append(note);}
byId('method-select').innerHTML=data.catalog.map(config=>`<option value="${config.id}">${config.id}${config.id===data.primary?'（理論主）':''}${config.id===data.selected?'（参考代表）':''}${config.improve_limit?'':'〔価格改善なし対照〕'}</option>`).join('');
byId('method-select').value=data.default_method;byId('method-select').addEventListener('change',render);comparison();render();
window.reportTest={data,render};
