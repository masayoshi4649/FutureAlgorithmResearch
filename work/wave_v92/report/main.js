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
 const text=[];if(id===data.primary)text.push('理論主');if(id===data.selected)text.push('前16場の参考代表');
 if(id==='J8')text.push('追従8枚だけ');if(id==='J10')text.push('追従10枚だけ・同上限対照');if(id==='M82')text.push('旧固定8：2');
 if(id==='R0'||id==='R0_C')text.push('同じ成行・回復確認なし');if(id==='R_B25_C_TR')text.push('統合の再参加対照');if(id==='O10_F10_TR')text.push('中心を更新する旧動作');
 if(id==='M_RB25_C')text.push('配分：追従8・回復反発2');if(id==='M_KS25')text.push('配分：追従8・中心帰還反発2');
 return text.join('・');
}

/**
 * 機能: 入口・途中・出口の条件を三つの短文へ分けて表示する。
 * @param {object} config - 事前固定した条件。
 * @returns {string} 日本語の条件説明HTML。
 */
function rule(config){
 const portions=`追従${config.trend_budget}・反発${config.range_budget}枚の固定枠（日経は各2倍）。`;
 const hasTrend=config.trend_budget>0,hasRange=config.range_budget>0;
 let entrance=portions;
 if(hasTrend)entrance+=config.ungated_trend||config.selection==='fixed'?'追従は元のJ2判定で入ります。':`追従はJ2に高ER${config.high_er}と${config.trend_mode_confirm_seconds??config.confirm_seconds}秒確認を追加。`;
 if(hasRange){
  const width=config.range_width_mode==='opening_fraction'?`始値${(config.range_width_fraction*100).toFixed(2)}%を呼値へ切り上げた幅`:`${config.width_ticks}ラージ呼値幅`;
  if(config.range_entry_kind==='recovery_market'){
   const confirmation=config.recovery_confirmation==='none'?'回復を待たず':config.recovery_confirmation==='self'?`自己midが観測極値から${config.recovery_fraction}幅戻ったら`:`両市場のmidが各観測極値から各${config.recovery_fraction}幅戻ったら`;
   entrance+=`低ER・範囲内で中心を準備し、${width}の最初の上下逸脱で反対側を選択。${confirmation}、判断後の次気配で成行新規。`;
  }else{
   entrance+=`反発は${width}の上下到達で片側指値。`;
   if(config.persistent_arm)entrance+=`低ER${config.low_er}・範囲内を${config.confirm_seconds}秒確認して基準を一度準備します。`;
   else if(config.selection!=='fixed')entrance+=`新規には低ER${config.low_er}・範囲内の${config.confirm_seconds}秒確認が必要。`;
  }
 }
 let middle='';
 if(hasRange&&config.persistent_arm)middle+=`分類不明でも基準を保持。${config.watch_clear_common==='adverse'&&config.range_entry_kind==='recovery_market'?'逸脱監視方向に反する両市場共同進行':'両市場の明確な共同進行'}又は基準±3幅で解除（方向未選択時は共同進行だけで解除）。`;
 else if(hasRange&&config.cancel_pending)middle+='待機条件が失効したら、次有効気配で成立を先に確認して未約定を取消。';
 else if(hasRange)middle+='予約した指値は状態が変わっても維持。';
 if(hasRange&&config.activate_anchor&&!config.persistent_arm)middle+='反発へ参加可能になった時に、未予約・未保有の基準だけ当時価格へ更新。';
 if(hasRange&&config.range_reentry_kind!=='legacy'){
  middle+=`${config.center_after==='all'?'全返済後':'手数料後黒字の全返済後'}は旧中心を保持。`;
  if(config.range_reentry_kind!=='keep')middle+=`${config.range_reentry_kind==='return_both'?'両市場同時':'自己'}の${config.center_fraction}幅中心帯への帰還を確認し、さらに別行の新逸脱で再参加。`;
  else middle+='帰還確認を加えず、同じ中心からの新規を許可。';
  if(config.center_after!=='all')middle+='赤字後は元の再準備動作。';
  if(config.center_release&&!config.persistent_arm)middle+='中心保持中の共同進行又は3幅破綻で解除し、次の低ER準備を待ちます。';
 }
 if(!middle)middle='途中の方向判定による変更は加えません。';
 let exit='';
 if(config.reverse_sources!=='none'){
  const proof={common:'二市場の共同方向の反対',quotes:'両市場30秒のbid／ask各1呼値の逆進行',either:'共同方向の反対又は両市場の短期両気配逆行'}[config.reverse_kind];
  const scope={trend:'追従',range:'反発',both:'両源'}[config.reverse_sources];
  exit+=`${scope}は${proof}を${config.reverse_confirm_seconds}秒確認して返済（ER不要）。`;
  if(config.reverse_kind==='either')exit+='二つの証拠は別々に確認してからOR。';
 }
 if(hasRange){
  exit+=config.range_profit_mode==='trail'?`${config.profit_activate_widths}幅順行で${config.profit_trail_widths}幅追跡を開始。`:`利確${config.target_widths}幅。`;
  exit+=config.range_stop_kind==='witness_extreme'?'判断時の観測mid極値の1呼値外を固定失敗線にし、清算気配が越えたら返済。':`初期損切り${config.stop_widths}幅。`;
 }
 if(hasTrend)exit+=`追従は始値${(config.trend_width_fraction*100).toFixed(1)}%で追跡、${config.trend_hold_seconds>=1e20?'固定保有期限なし':`${config.trend_hold_seconds/60}分まで`}。`;
 exit+='全建玉をセッション内で返済します。';
 return [['入口',entrance],['途中',middle],['出口',exit]].map(([name,text])=>`<p><b>${name}：</b>${escapeHtml(text)}</p>`).join('');
}

/**
 * 機能: 理論主、前16参考及び同執行対照の全31場を比較する。
 * @returns {undefined} 画面更新のため返り値はありません。
 */
function comparison(){
 byId('comparison').querySelector('tbody').innerHTML=data.highlights.map(id=>{
  let text=`<tr data-id="${id}"><td><span class="method-id">${id}</span><span class="tag">${label(id)}</span></td>`;
  for(const symbol of symbols){const r=data.results[id].periods['全31'][symbol],maximum=Math.max(r.maximums.occupied_long,r.maximums.occupied_short);text+=money(r.net,'net',`${r.campaigns}親・片方向最大占有${maximum}枚`)+`<td>${percent(r.profit_share)}</td><td>${r.positive_sessions} / ${r.session_count}</td>`+money(r.equity_drawdown,'loss');}
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
 const config=data.catalog.find(c=>c.id===id);
 const references=data.comparison_pairs?.[id]||
  (config.range_budget===0?[config.trend_budget===10?'J10':'J8']:config.trend_budget===0?['O10']:['J8','J10','M82']);
 byId('cause-results').innerHTML=symbols.flatMap(symbol=>references.map(reference=>{
  const a=data.results[id].periods['全31'][symbol],b=data.results[reference].periods['全31'][symbol];return `<tr data-symbol="${symbol}" data-reference="${reference}"><td>${names[symbol]}</td><td>${reference}</td>`+['net','profit','loss','fees'].map(field=>money(a[field]-b[field],field==='loss'||field==='fees'?'cost_change':'net')).join('')+`<td>${a.campaigns-b.campaigns}</td></tr>`;
 })).join('');
 const notes=data.cause_notes?.[id];
 byId('cause-text').innerHTML=(Array.isArray(notes)?notes:typeof notes==='string'?[notes]:[]).map(text=>`<p>${escapeHtml(text)}</p>`).join('');
}

/**
 * 機能: 固定配分の相関と同時損失を、束縛された追加診断から二文で表示する。
 * @returns {undefined} 表示更新のため返り値はありません。
 */
function allocationDiagnosis(){
 const rows=data.allocation_diagnostic?.行||[];
 const top=rows.find(row=>row.手法==='M_RB25_C'&&row.銘柄==='TOPIX'),nk=rows.find(row=>row.手法==='M_RB25_C'&&row.銘柄==='NK225');
 if(!top||!nk){byId('allocation-diagnosis').textContent='';return;}
 byId('allocation-diagnosis').textContent=`M_RB25_Cの源別場収支相関はTOPIX${top.源別場収支相関.toFixed(3)}・日経${nk.源別場収支相関.toFixed(3)}でも、両源赤字は${top.二源とも赤字場数}/${nk.二源とも赤字場数}場、追従赤字を合計黒字へ救った場は双方${top.追従赤字から合計黒字場数}でした。同上限J10より場収支の標準偏差は小さくなりましたが、収支も減りました。`;
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
byId('cause-general').innerHTML=Object.entries(data.cause_notes||{}).filter(([name,value])=>!data.catalog.some(config=>config.id===name)&&typeof value==='string').map(([name,value])=>`<p data-cause="${escapeHtml(name)}"><b>${escapeHtml(name)}：</b>${escapeHtml(value)}</p>`).join('');
byId('method-select').innerHTML=data.catalog.map(config=>`<option value="${config.id}">${config.id}${config.id===data.primary?'（理論主）':''}${config.id===data.selected?'（参考代表）':''}</option>`).join('');
byId('method-select').value=data.default_method;byId('method-select').addEventListener('change',render);allocationDiagnosis();comparison();render();
window.reportTest={data,render};
