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
 * @param {string} type - 利益、損失、収支又は費用差の識別子。
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
 * 機能: 正規化した比較単位を円額と区別して表示する。
 * @param {number|null} value - 下方偏差又は収支の比較単位。
 * @returns {string} 原数値を保持した比較単位セル。
 */
function unit(value){return `<td class="unit"><span data-unit="${value==null?'null':value}">${value==null?'—':value.toFixed(3)}</span><small>比較単位</small></td>`;}

/**
 * 機能: 手法の位置付けを短い日本語へ変換する。
 * @param {string} id - 固定した識別番号。
 * @returns {string} 主、参考代表、対照等の表示。
 */
function label(id){
 const text=[];if(id===data.primary)text.push('事前主');if(id===data.selected)text.push('前16参考');
 if(data.labels[id])text.push(data.labels[id]);
 return text.join('・');
}

/**
 * 機能: 入口・途中・出口の条件を三つの短文へ分けて表示する。
 * @param {object} config - 事前固定した条件。
 * @returns {string} 日本語の条件説明HTML。
 */
function rule(config){
 const entrance=`両市場が5分で同じ方向へ各0.03%以上進み、直近15秒の自分の買い・売り気配も各1呼値以上進む旧J8条件。TOPIX8枚、日経16枚。`;
 const protection=['追加の利益保護なし。','最大順行が初期幅の2倍になったら、手数料込みの建値保護を追加。','最大順行が初期幅の2倍になったら、手数料込み建値と最大順行の半分を保護。'][config.trend_protection_mode];
 const middle=`初期損切りは始値の${(config.trend_initial_stop_bp/100).toFixed(1)}%。追尾は始値の0.4%幅。${protection}停止線は不利へ戻さない。`;
 const exit=`${config.trend_hold_seconds===0?'通常の保有期限なし。':'30分でも返済。'}停止条件成立後の次正常気配で返済。全玉を場内で閉じ、返済後30秒から次の候補で再参加。希望停止価格での約定は保証されない。`;
 return [['入口',entrance],['途中',middle],['出口',exit]].map(([name,text])=>`<p><b>${name}：</b>${escapeHtml(text)}</p>`).join('');
}

/**
 * 機能: 事前主、前16参考及び同執行対照の全31場を比較する。
 * @returns {undefined} 画面更新のため返り値はありません。
 */
function comparison(){
 byId('comparison').querySelector('tbody').innerHTML=data.highlights.map(id=>{
  let text=`<tr data-id="${id}"><td><span class="method-id">${id}</span><span class="tag">${label(id)}</span></td>`;
  for(const symbol of symbols){const r=data.results[id].periods['全31'][symbol],s=data.results[id].stability['全31'][symbol];text+=money(s.mean_losing_session_yen,'loss')+money(s.worst_session_loss_yen,'loss')+`<td>${r.positive_sessions} / ${s.active_sessions}<small>${percent(s.positive_session_rate)}</small></td><td>${s.no_trade_sessions}</td>`+unit(s.downside_rms_units)+money(r.net,'net',`設定${s.configured_quantity}枚・保有最大${Math.max(r.maximums.held_long,r.maximums.held_short)}枚・${r.campaigns}親`)+`<td>${percent(r.profit_share)}</td>`;}
  return text+'</tr>';
 }).join('');
}

/**
 * 機能: 全31場と合計の金額・利益玉・損失玉枚数を表示する。
 * @param {object} result - 選択条件の保存済み会計。
 * @returns {undefined} 画面更新のため返り値はありません。
 */
function sessions(result){
 const rows=data.sessions.map(session=>({session,values:Object.fromEntries(symbols.map(symbol=>[symbol,result.rows.find(r=>r.symbol===symbol&&r.session===session)]))}));
 rows.push({session:'全31場 合計',values:result.periods['全31'],total:true});
 byId('session-results').innerHTML=rows.map(item=>{
  let text=`<tr data-session="${item.session}"${item.total?' class="total"':''}><td>${escapeHtml(item.session.replace('_Day',' デイ').replace('_Night',' ナイト'))}</td>`;
  for(const symbol of symbols){const r=item.values[symbol];text+=money(r.profit,'profit',`${r.winning_lots.toLocaleString('ja-JP')}枚`)+money(r.loss,'loss',`${r.losing_lots.toLocaleString('ja-JP')}枚`)+money(r.net,'net',`勝−負 ${(r.winning_lots-r.losing_lots).toLocaleString('ja-JP')}枚`);}
  return text+'</tr>';
 }).join('');
}

/**
 * 機能: 期間、戦略別、売買方向別の保存会計を表示する。
 * @param {object} result - 選択条件の保存済み会計。
 * @returns {undefined} 画面更新のため返り値はありません。
 */
function details(result){
 byId('period-results').innerHTML=data.period_names.flatMap(period=>symbols.map(symbol=>{
  const r=result.periods[period][symbol];return `<tr data-period="${period}" data-symbol="${symbol}"><td>${period}</td><td>${names[symbol]}</td>`+money(r.net)+`<td>${percent(r.profit_share)}</td><td>${r.positive_sessions} / ${r.losing_sessions} / ${r.no_trade_sessions}</td><td>${r.campaigns}</td>`+money(r.fees,'loss')+money(r.equity_drawdown,'loss')+money(r.without_best_day.net)+'</tr>';
 })).join('');
 byId('stability-results').innerHTML=data.period_names.flatMap(period=>symbols.map(symbol=>{
  const s=result.stability[period][symbol];return `<tr data-period="${period}" data-symbol="${symbol}"><td>${period}</td><td>${names[symbol]}</td>`+money(s.mean_losing_session_yen,'loss')+money(s.worst_session_loss_yen,'loss')+`<td>${percent(s.positive_session_rate)}</td>`+unit(s.downside_rms_units)+unit(s.active_downside_rms_units)+unit(s.active_net_median_units)+unit(s.active_net_q25_units)+money(s.session_net_median_yen)+money(s.session_net_q25_yen)+unit(s.worst_intraday_drawdown_units)+'</tr>';
 })).join('');
 byId('source-results').innerHTML=symbols.flatMap(symbol=>['J2','O06'].map(source=>{
  const r=result.periods['全31'][symbol].sources[source];return `<tr data-symbol="${symbol}" data-source="${source}"><td>${names[symbol]}</td><td>${source==='J2'?'J2 追従':'反発・回復'}</td>`+money(r.profit,'profit')+money(r.loss,'loss')+money(r.net)+money(r.fees,'loss')+`<td>${r.campaigns}</td></tr>`;
 })).join('');
 byId('direction-results').innerHTML=symbols.flatMap(symbol=>['買い','売り'].map(direction=>{
  const r=result.periods['全31'][symbol].directions[direction];return `<tr data-symbol="${symbol}" data-direction="${direction}"><td>${names[symbol]}</td><td>${direction}</td>`+money(r.profit,'profit')+money(r.loss,'loss')+money(r.net)+`<td>${r.campaigns}</td></tr>`;
 })).join('');
}

/**
 * 機能: 同数量の単独又は固定併用対照との会計差を表示する。
 * @param {string} id - 選択条件の識別番号。
 * @returns {undefined} 画面更新のため返り値はありません。
 */
function causes(id){
 const references=data.comparison_pairs[id];
 byId('cause-results').innerHTML=symbols.flatMap(symbol=>references.map(reference=>{
  const a=data.results[id].periods['全31'][symbol],b=data.results[reference].periods['全31'][symbol];return `<tr data-symbol="${symbol}" data-reference="${reference}"><td>${names[symbol]}</td><td>${reference}</td>`+['net','profit','loss','fees'].map(field=>money(a[field]-b[field],field==='loss'||field==='fees'?'cost_change':'net')).join('')+`<td>${a.campaigns-b.campaigns}</td></tr>`;
 })).join('');
 const notes=data.cause_notes?.[id];
 byId('cause-text').innerHTML=(Array.isArray(notes)?notes:typeof notes==='string'?[notes]:[]).map(text=>`<p>${escapeHtml(text)}</p>`).join('');
}

/**
 * 機能: 選択中の手法の説明と全会計を一括更新する。
 * @returns {undefined} 画面更新のため返り値はありません。
 */
function render(){
 const id=byId('method-select').value,config=data.catalog.find(c=>c.id===id),result=data.results[id];
 byId('method-title').textContent=id+(label(id)?' · '+label(id):'');
 byId('method-rule').innerHTML=rule(config);sessions(result);details(result);causes(id);
}

// ----------------------------------------
byId('conclusion').innerHTML=data.conclusion.slice(0,3).map(text=>`<p class="conclusion-line">${escapeHtml(text)}</p>`).join('');
byId('conclusion-detail').innerHTML=data.conclusion.slice(3).map(text=>`<p>${escapeHtml(text)}</p>`).join('');
byId('cause-general').innerHTML=Object.entries(data.cause_notes||{}).filter(([name,value])=>!data.catalog.some(config=>config.id===name)&&typeof value==='string').map(([name,value])=>`<p data-cause="${escapeHtml(name)}"><b>${escapeHtml(name)}：</b>${escapeHtml(value)}${name==='場内返済'?' <a href="https://www.jpx.co.jp/derivatives/rules/trading-hours/">JPXの立会時間</a>':''}</p>`).join('');
byId('method-select').innerHTML=data.catalog.map(config=>`<option value="${config.id}">${config.id} ${escapeHtml(data.labels[config.id])}${config.id===data.primary?'（事前主）':''}${config.id===data.selected?'（参考代表）':''}</option>`).join('');
byId('method-select').value=data.default_method;byId('method-select').addEventListener('change',render);comparison();render();
window.reportTest={data,render};
