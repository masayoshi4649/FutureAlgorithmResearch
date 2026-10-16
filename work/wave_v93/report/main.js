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
 const hasTrend=config.trend_budget>0,hasRange=config.range_budget>0;
 let entrance=`追従${config.trend_budget}・反発${config.range_budget}枚（日経は各2倍）。`;
 if(hasTrend)entrance+='追従は元J2の二市場共通方向で新規。';
 if(hasRange){
  entrance+='低ERで中心を準備→1幅逸脱→両市場midが観測極値から各0.25幅回復→次気配で成行新規。';
  if(config.range_entry_max_risk_widths>0)entrance+=`予定停止距離が${config.range_entry_max_risk_widths}幅以内の場合だけ参加。`;
  if(config.range_entry_min_center_ratio>0)entrance+=`費用込み中心利益／予定リスクが${config.range_entry_min_center_ratio}以上の場合だけ参加。`;
  if(config.range_entry_max_risk_widths>0||config.range_entry_min_center_ratio>0)entrance+='最初の回復で判定し、見送り後は同じ古い回復を再利用しません。';
 }
 let middle=hasRange?'分類不明でも基準を保持。監視方向に反する共同方向又は基準±3幅で解除。':'追従の枠は単独で運転。';
 const failure=config.range_failure_reentry_kind;
 if(hasRange&&failure!=='legacy'){
  middle+='極値破りの返済予約と料金後の実損切りが揃ったら反発だけ休止。';
  middle+=failure==='return_self'?'旧失敗中心の自己0.25幅帯へ戻るまで待つ。':failure==='return_both'?'旧失敗中心の双方0.25幅帯へ同時に戻るまで待つ。':'全参照窓が返済後となり、有効raw否定→確認済み往復へ変わるまで待つ。';
  middle+='解除行より後に新中心を準備し、新しい逸脱と回復を要求。';
 }
 let exit='';
 if(hasRange){
  exit+=config.range_stop_kind==='width_or_witness'?'LastPriceの固定1幅停止OR、判断時mid極値の1呼値外を清算bid／askが破る停止。':config.range_stop_kind==='witness_extreme'?'判断時mid極値の1呼値外を清算bid／askが破ったら停止。':'LastPriceが実新規から逆に1幅進んだら停止。';
  exit+=config.range_target_kind==='center'?'新規判断時の中心へLastPriceが戻れば利確。':config.range_target_kind==='center_plus'?'新規判断時の中心から順行側へ0.5幅進めば利確。':`LastPriceが実新規から順行${config.target_widths}幅で利確。`;
 }
 if(hasTrend)exit+=`追従は始値${(config.trend_width_fraction*100).toFixed(1)}%幅の追跡、旧対照の${config.trend_hold_seconds/60}分期限。`;
 exit+='返済も次気配。全建玉を場内返済。';
 return [['入口',entrance],['途中',middle],['出口',exit]].map(([name,text])=>`<p><b>${name}：</b>${escapeHtml(text)}</p>`).join('');
}

/**
 * 機能: 事前主、前16参考及び同執行対照の全31場を比較する。
 * @returns {undefined} 画面更新のため返り値はありません。
 */
function comparison(){
 byId('comparison').querySelector('tbody').innerHTML=data.highlights.map(id=>{
  let text=`<tr data-id="${id}"><td><span class="method-id">${id}</span><span class="tag">${label(id)}</span></td>`;
  for(const symbol of symbols){const r=data.results[id].periods['全31'][symbol],maximum=Math.max(r.maximums.occupied_long,r.maximums.occupied_short);text+=money(r.net,'net',`${r.campaigns}親／${r.active_sessions}活動場・最大${maximum}枚`)+`<td>${percent(r.profit_share)}</td><td>${r.positive_sessions} / ${r.session_count}</td>`+money(r.equity_drawdown,'loss');}
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
