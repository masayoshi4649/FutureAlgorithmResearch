const data=typeof document==='undefined'?null:JSON.parse(document.getElementById('report-data').textContent);
const symbols=['TOPIX','NK225'];
const names={TOPIX:'TOPIXミニ',NK225:'日経マイクロ'};

/**
 * 機能: 識別番号から表示要素を取得する。
 * @param {string} id - 要素の識別番号。
 * @returns {HTMLElement|null} 該当要素。
 */
function byId(id){return document.getElementById(id);}

/**
 * 機能: 日本語や識別番号を安全なHTML文字列へ変換する。
 * @param {string|number} value - 表示値。
 * @returns {string} 特殊文字を置換した文字列。
 */
function escapeHtml(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

/**
 * 機能: 手数料後円額と補助枚数を、原数値を保持して表示する。
 * @param {number|null} value - 金額。不明はnull。
 * @param {string} type - 利益、損失、収支又は費用差。
 * @param {string} small - 補助表示。
 * @returns {string} 表セルのHTML。不明をゼロへ置換しない。
 */
function money(value,type='net',small=''){
 if(value==null)return `<td class="muted" data-unknown="true">未掲載</td>`;
 if(!Number.isFinite(value))throw Error('表示金額が有限ではありません');
 const rounded=value===0?0:Math.round(value),cost=type==='loss'||type==='cost_change';
 const className=value===0?'muted':cost?(value>0?'loss':'positive'):(value<0?'loss':'positive');
 const sign=(type==='net'||type==='cost_change')&&rounded>0?'+':'';
 return `<td class="money ${className}"><span data-number="${value}">${sign}${rounded.toLocaleString('ja-JP')}円</span>${small?`<small>${escapeHtml(small)}</small>`:''}</td>`;
}

/**
 * 機能: 定義された割合を小数一桁で表示する。
 * @param {number|null} value - 比率。無取引などで定義されなければnull。
 * @returns {string} 割合又は横線。
 */
function percent(value){return value==null?'—':(value*100).toFixed(1)+'%';}

/**
 * 機能: 正規化比較値を円額とは別の単位で表示する。
 * @param {number|null} value - 比較単位の値。
 * @returns {string} 原数値付きセル。
 */
function unit(value){return `<td class="unit"><span data-unit="${value==null?'null':value}">${value==null?'—':value.toFixed(3)}</span><small>比較単位</small></td>`;}

/**
 * 機能: 親又は実玉群の利益・損失・収支と累計決済枚数を表示する。
 * @param {object} value - 指定集計の保存会計。
 * @returns {string} 三つのセル。枚数差を金額収支と混同しない。
 */
function accountCells(value){
 const lots=`全決済${value.lots.toLocaleString('ja-JP')}枚・勝−負 ${(value.winning_lots-value.losing_lots).toLocaleString('ja-JP')}枚`;
 return money(value.profit,'profit',`${value.winning_lots.toLocaleString('ja-JP')}枚`)+money(value.loss,'loss',`${value.losing_lots.toLocaleString('ja-JP')}枚`)+money(value.net,'net',lots);
}

/**
 * 機能: 主・参考代表・固定条件の説明を短く表示する。
 * @param {string} id - 条件の識別番号。
 * @returns {string} 手法の位置付け。
 */
function label(id){return [id===data.primary?'事前主':'',id===data.selected?(data.selection_level===5?'前16参考・活動基準不足':'前16参考'):'',data.labels[id]||''].filter(Boolean).join('・');}

/**
 * 機能: 初回枚数、増玉の数理条件、二出口を短い日本語にする。
 * @param {object} config - 固定済みの条件定義。
 * @returns {string} 入口・途中・出口の説明HTML。
 */
function rule(config){
 const mode=config.trend_growth_mode,initial=config.trend_initial_quantity;
 if(![0,1,2].includes(mode)||![null,1,2,4].includes(initial))throw Error('未知の数量配分');
 if(config.entry_wait_kind!==1||config.entry_support_lane!=='L1'||config.entry_clock_policy!=='C1'||config.entry_price_cap_multiple!==1)throw Error('今回の固定入口と異なります');
 const entrance=`両市場の方向と気配進行を確認して、${initial==null?'TOPIX8枚・日経16枚':`両商品とも初回${initial}枚`}で新規。元候補から不利側1W以内で判断。`;
 const middle=mode===0?'枚数は固定。追加しない。':`全玉の費用後利益で追加を支え、追加後の停止線まで${config.trend_growth_cushion_ticks}呼値の余裕があれば倍増。損失予算は初回のまま、最大TOPIX8枚・日経16枚。`;
 const exit=config.trend_hold_seconds===0?'通常期限なし。利益が伸びたら費用床を起動し、追加で解除しない。追尾又は停止で全量返済し、場内で閉じる。':'初回実約定から30分又は停止条件で全量返済。追加しても期限は延長せず、場内で閉じる。';
 return [['入口',entrance],['途中',middle],['出口',exit]].map(([name,text])=>`<p><b>${name}：</b>${escapeHtml(text)}</p>`).join('');
}

/**
 * 機能: 赤字頻度・赤字額と数量対照を商品別に比較する。
 * @returns {undefined} 表示の更新だけを行います。
 */
function comparison(){
 for(const symbol of symbols){
  byId(`comparison-${symbol}`).querySelector('tbody').innerHTML=data.highlights.map(id=>{
   const r=data.results[id].periods['全31'][symbol],s=data.results[id].stability['全31'][symbol],red=s.active_sessions?s.losing_sessions/s.active_sessions:null;
   const counts=`<td data-losing-sessions="${s.losing_sessions}">${s.losing_sessions} / ${s.active_sessions}<small>赤字率 ${percent(red)}・黒字${r.positive_sessions}場</small></td>`;
   const excluded=r.without_best_day.net,shown=Math.round(excluded),detail=`最大利益日除外 ${shown>0?'+':''}${shown.toLocaleString('ja-JP')}円`;
   const net=money(r.net,'net',`初回${s.configured_quantity}枚・実保有最大${s.actual_peak_quantity}枚`).replace('</td>',`<small data-best-day-net="${excluded}">${escapeHtml(detail)}</small></td>`);
   return `<tr data-id="${id}"><td><span class="method-id">${id}</span><span class="tag">${escapeHtml(label(id))}</span></td>`+counts+money(s.mean_losing_session_yen,'loss')+money(s.worst_session_loss_yen,'loss')+`<td>${s.no_trade_sessions}</td>`+unit(s.downside_rms_units)+net+`<td data-cohort-share="${r.cohorts.profit_share}" data-parent-share="${r.profit_share}">玉 ${percent(r.cohorts.profit_share)}<small>親 ${percent(r.profit_share)}・${r.campaigns}親</small></td></tr>`;
  }).join('');
 }
}

/**
 * 機能: 全31場と合計を、実玉群の主行と親合算の補助行で表示する。
 * @param {object} result - 選択した保存会計。
 * @returns {undefined} 同じ収支の二会計を加算せず併記します。
 */
function sessions(result){
 const rows=data.sessions.map(session=>({session,values:Object.fromEntries(symbols.map(symbol=>[symbol,result.rows.find(r=>r.session===session&&r.symbol===symbol)]))}));
 rows.push({session:'全31場 合計',values:result.periods['全31'],total:true});
 byId('session-results').innerHTML=rows.map(item=>['cohorts','parents'].map(basis=>{
  const labelText=item.session.replace('_Day',' デイ').replace('_Night',' ナイト'),kind=basis==='cohorts'?'実玉群':'親合算';
  let text=`<tr data-session="${item.session}" data-basis="${basis}" class="${basis==='cohorts'?'cohort-row':'parent-row'}${item.total?' total':''}"><td>${escapeHtml(labelText)}</td><td>${kind}</td>`;
  for(const symbol of symbols)text+=accountCells(basis==='cohorts'?item.values[symbol].cohorts:item.values[symbol]);
  return text+'</tr>';
 }).join('')).join('');
}

/**
 * 機能: 期間別と買売別の実玉群損益及び安定性を表示する。
 * @param {object} result - 保存済みの期間集計。
 * @returns {undefined} 表の表示を更新します。
 */
function details(result){
 byId('period-results').innerHTML=data.period_names.flatMap(period=>symbols.map(symbol=>{
  const r=result.periods[period][symbol];
  return `<tr data-period="${period}" data-symbol="${symbol}"><td>${period}</td><td>${names[symbol]}</td>`+accountCells(r.cohorts)+`<td>${percent(r.cohorts.profit_share)} / ${percent(r.profit_share)}</td><td>${r.positive_sessions} / ${r.losing_sessions} / ${r.no_trade_sessions}</td>`+money(r.equity_drawdown,'loss')+money(r.without_best_day.net)+'</tr>';
 })).join('');
 byId('stability-results').innerHTML=data.period_names.flatMap(period=>symbols.map(symbol=>{
  const s=result.stability[period][symbol];
  return `<tr data-period="${period}" data-symbol="${symbol}"><td>${period}</td><td>${names[symbol]}</td><td>${percent(s.positive_session_rate)}</td>`+money(s.session_net_median_yen)+money(s.session_net_q25_yen)+unit(s.active_net_median_units)+unit(s.active_net_q25_units)+unit(s.worst_intraday_drawdown_units)+'</tr>';
 })).join('');
 byId('direction-results').innerHTML=symbols.flatMap(symbol=>['買い','売り'].map(direction=>{
  const r=result.periods['全31'][symbol].cohort_directions[direction];
  return `<tr data-symbol="${symbol}" data-direction="${direction}"><td>${names[symbol]}</td><td>${direction}</td>`+accountCells(r)+`<td>${r.cohorts}</td></tr>`;
 })).join('');
}

/**
 * 機能: 黒字親内損失と実損失予算超過の報告用派生だけを表示する。
 * @param {string} id - 表示条件。
 * @returns {undefined} 欠けた派生は未掲載とし、ゼロへ置換しません。
 */
function diagnostics(id){
 byId('hidden-loss-results').innerHTML=symbols.map(symbol=>{
  const r=data.report_diagnostics?.[id]?.[symbol]?.winning_parent_losing_cohorts;
  return `<tr data-symbol="${symbol}"><td>${names[symbol]}</td><td>${r?.losing_cohorts??'未掲載'}</td><td>${r?.losing_lots??'未掲載'}</td>`+money(r?.loss??null,'loss')+'</tr>';
 }).join('');
 byId('budget-results').innerHTML=symbols.map(symbol=>{
  const r=data.report_diagnostics?.[id]?.[symbol]?.risk_budget;
  return `<tr data-symbol="${symbol}"><td>${names[symbol]}</td><td>${r?.excess_parents??'未掲載'}</td>`+money(r?.realized_excess_sum??null,'loss')+money(r?.maximum_realized_excess??null,'loss')+money(r?.maximum_observed_excess??null,'loss')+'</tr>';
 }).join('');
}

/**
 * 機能: 同Q対照・旧全量・出口差の正式会計を比較する。
 * @param {string} id - 選択条件。
 * @returns {undefined} 差額は表示だけで、再選定はしません。
 */
function causes(id){
 byId('cause-results').innerHTML=symbols.flatMap(symbol=>data.comparison_pairs[id].map(reference=>{
  const a=data.results[id].periods['全31'][symbol],b=data.results[reference].periods['全31'][symbol];
  return `<tr data-symbol="${symbol}" data-reference="${reference}"><td>${names[symbol]}</td><td>${reference}</td>`+money(a.net-b.net)+money(a.cohorts.profit-b.cohorts.profit,'net')+money(a.cohorts.loss-b.cohorts.loss,'cost_change')+money(a.fees-b.fees,'cost_change')+`<td>${a.campaigns-b.campaigns}</td></tr>`;
 })).join('');
 const notes=data.cause_notes?.[id];
 byId('cause-text').innerHTML=(Array.isArray(notes)?notes:typeof notes==='string'?[notes]:[]).map(text=>`<p>${escapeHtml(text)}</p>`).join('');
}

/**
 * 機能: 選択中の手法の短い説明と全会計を更新する。
 * @returns {undefined} 状態の表示だけを変更します。
 */
function render(){
 const id=byId('method-select').value,config=data.catalog.find(value=>value.id===id),result=data.results[id];
 byId('method-title').textContent=id+' · '+label(id);
 byId('method-rule').innerHTML=rule(config);
 sessions(result);details(result);diagnostics(id);causes(id);
}

// ----------------------------------------
if(typeof document!=='undefined'){
 byId('conclusion').innerHTML=data.conclusion.slice(0,3).map(text=>`<p class="conclusion-line">${escapeHtml(text)}</p>`).join('');
 byId('selection-note').textContent=data.selection_level===5?`前16参考 ${data.selected} は活動基準を満たさない参考比較です。採用候補ではありません。`:`前16参考 ${data.selected} は前半で固定した比較対象です。`;
 byId('conclusion-detail').innerHTML=data.conclusion.slice(3).map(text=>`<p>${escapeHtml(text)}</p>`).join('');
 byId('cause-general').innerHTML=Object.entries(data.cause_notes||{}).filter(([name,value])=>!data.catalog.some(config=>config.id===name)&&typeof value==='string').map(([name,value])=>`<p><b>${escapeHtml(name)}：</b>${escapeHtml(value)}</p>`).join('');
 byId('method-select').innerHTML=data.catalog.map(config=>`<option value="${config.id}">${config.id} ${escapeHtml(data.labels[config.id])}${config.id===data.primary?'（事前主）':''}${config.id===data.selected?(data.selection_level===5?'（前16参考・活動不足）':'（前16参考）'):''}</option>`).join('');
 byId('method-select').value=data.default_method;
 byId('method-select').addEventListener('change',render);
 comparison();render();
 window.reportTest={data,render,rule};
}
if(typeof module!=='undefined')module.exports={rule,money,accountCells,percent,escapeHtml};
