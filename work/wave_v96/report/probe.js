/**
 * 機能: 全18条件の金額・枚数・源別・期間を正式会計へ独立照合する。
 * @returns {object} 全表示の照合数と画面品質の検査結果。
 */
function independentVerify(){
 const data=window.reportTest.data,render=window.reportTest.render,q=id=>document.getElementById(id);let count=0,unitCount=0;
 const number=(cell,expected)=>{const node=cell.querySelector('[data-number]');if(!node||Math.abs(Number(node.dataset.number)-expected)>1e-5)throw Error('元金額との差');if(Number(node.textContent.replace(/[+,円]/g,''))!==Math.round(expected))throw Error('表示金額');count++;};
 const percent=value=>value==null?'—':(value*100).toFixed(1)+'%';
 const unit=(cell,expected)=>{const node=cell.querySelector('[data-unit]');if(!node)throw Error('比較単位なし');if(expected==null){if(node.dataset.unit!=='null'||node.textContent!=='—')throw Error('未知比較単位');}else if(Math.abs(Number(node.dataset.unit)-expected)>1e-9||node.textContent!==expected.toFixed(3))throw Error('比較単位表示');unitCount++;};
 if(q('method-select').options.length!==18||data.sessions.length!==31)throw Error('条件又は場数');
 const rules=q('rules-detail').textContent;
 if(!['全18で旧J8候補と旧J2許可を固定','通常30分と通常期限なし','TOPIX8枚・日経16枚','場末60秒前','損失後の反対方向禁止は追加しない'].every(value=>rules.includes(value))||/R4|P1許可|数量対照4/.test(rules))throw Error('今回の固定条件と詳細説明');
 for(const config of data.catalog){
  q('method-select').value=config.id;render();const result=data.results[config.id],rows=q('session-results').rows;
  if(rows.length!==32)throw Error('31場と合計の行数');
  for(let i=0;i<32;i++)for(let j=0;j<2;j++){
   const symbol=['TOPIX','NK225'][j],value=i===31?result.periods['全31'][symbol]:result.rows.find(r=>r.session===data.sessions[i]&&r.symbol===symbol);
   if(i<31&&rows[i].dataset.session!==data.sessions[i])throw Error('場名');
   ['profit','loss','net'].forEach((field,k)=>number(rows[i].cells[1+j*3+k],value[field]));
   const expected=[`${value.winning_lots.toLocaleString('ja-JP')}枚`,`${value.losing_lots.toLocaleString('ja-JP')}枚`,`勝−負 ${(value.winning_lots-value.losing_lots).toLocaleString('ja-JP')}枚`];
   expected.forEach((text,k)=>{if(rows[i].cells[1+j*3+k].querySelector('small').textContent!==text)throw Error('決済枚数');});
  }
  const periods=q('period-results').rows;if(periods.length!==16)throw Error('期間の行数');
  for(const row of periods){const value=result.periods[row.dataset.period][row.dataset.symbol];for(const[i,field]of[[2,'net'],[6,'fees'],[7,'equity_drawdown']])number(row.cells[i],value[field]);number(row.cells[8],value.without_best_day.net);if(row.cells[3].textContent!==percent(value.profit_share)||row.cells[4].textContent!==`${value.positive_sessions} / ${value.losing_sessions} / ${value.no_trade_sessions}`||Number(row.cells[5].textContent)!==value.campaigns)throw Error('期間割合と件数');}
  const stableRows=q('stability-results').rows;if(stableRows.length!==16)throw Error('安定期間の行数');
  for(const row of stableRows){const s=result.stability[row.dataset.period][row.dataset.symbol];for(const[i,field]of[[2,'mean_losing_session_yen'],[3,'worst_session_loss_yen'],[9,'session_net_median_yen'],[10,'session_net_q25_yen']])number(row.cells[i],s[field]);for(const[i,field]of[[5,'downside_rms_units'],[6,'active_downside_rms_units'],[7,'active_net_median_units'],[8,'active_net_q25_units'],[11,'worst_intraday_drawdown_units']])unit(row.cells[i],s[field]);if(row.cells[4].textContent!==percent(s.positive_session_rate))throw Error('活動黒字率');}
  const sources=q('source-results').rows;if(sources.length!==4)throw Error('源の行数');
  for(const row of sources){const value=result.periods['全31'][row.dataset.symbol].sources[row.dataset.source];for(const[i,field]of[[2,'profit'],[3,'loss'],[4,'net'],[5,'fees']])number(row.cells[i],value[field]);if(Number(row.cells[6].textContent)!==value.campaigns)throw Error('源別親数');}
  const directions=q('direction-results').rows;if(directions.length!==4)throw Error('方向の行数');
  for(const row of directions){const value=result.periods['全31'][row.dataset.symbol].directions[row.dataset.direction];['profit','loss','net'].forEach((field,k)=>number(row.cells[2+k],value[field]));if(Number(row.cells[5].textContent)!==value.campaigns)throw Error('方向別親数');}
  for(const row of q('cause-results').rows){const a=result.periods['全31'][row.dataset.symbol],b=data.results[row.dataset.reference].periods['全31'][row.dataset.symbol];['net','profit','loss','fees'].forEach((field,k)=>number(row.cells[2+k],a[field]-b[field]));if(Number(row.cells[6].textContent)!==a.campaigns-b.campaigns)throw Error('差の件数');}
  const text=q('method-rule').textContent;
  if(!text.includes('入口：')||!text.includes('途中：')||!text.includes('出口：'))throw Error('三部品説明');
  if(!text.includes(`TOPIX${config.trend_budget}枚、日経${config.trend_budget*2}枚`))throw Error('固定数量');
  if(!text.includes(`初期損切りは始値の${(config.trend_initial_stop_bp/100).toFixed(1)}%`)||!text.includes('追尾は始値の0.4%幅')||!text.includes('停止線は不利へ戻さない'))throw Error('初期幅と利益追尾の分離');
  if(!text.includes(config.trend_hold_seconds===0?'通常の保有期限なし':'30分でも返済'))throw Error('通常期限の説明');
  const protection=['追加の利益保護なし','手数料込みの建値保護を追加','最大順行の半分を保護'][config.trend_protection_mode];
  if(!text.includes(protection)||!text.includes('停止条件成立後の次正常気配')||!text.includes('返済後30秒'))throw Error('利益床と執行及び再参加の説明');
  if(config.loss_reentry_kind!=='none'&&(!text.includes('同方向への再参加は許す')||!text.includes('実返済後')||!text.includes('復活させない')))throw Error('直前実親と候補消費');
  if(config.loss_reentry_kind==='sustained_price_quotes'&&!text.includes('10秒確認'))throw Error('持続条件');
  if(config.range_budget>0){
   if(!text.includes('分類不明でも基準を保持')||!text.includes('基準±3幅')||!text.includes('両市場mid')||!text.includes('次気配で成行新規'))throw Error('回復と準備の説明');
   if(!text.includes('価格源と回復mid・執行BBOは別'))throw Error('価格と執行の別源');
   if(config.range_entry_context==='observable'&&!text.includes('初回回復で両市場の現在価格'))throw Error('現在可観測性gate');
   if(config.range_entry_context==='confirmed_range'&&!text.includes('現在往復の確認済み状態'))throw Error('現在確認gate');
   if(config.range_entry_max_risk_widths>0&&!text.includes(`予定停止距離が${config.range_entry_max_risk_widths}幅以内`))throw Error('予定距離ゲート説明');
   if(config.range_entry_min_center_ratio>0&&!text.includes(`費用込み中心利益／予定リスクが${config.range_entry_min_center_ratio}以上`))throw Error('費用込み距離比説明');
   if((config.range_entry_max_risk_widths>0||config.range_entry_min_center_ratio>0)&&!text.includes('同じ古い回復を再利用しません'))throw Error('見送り消費説明');
   if(config.range_stop_kind==='width_or_witness'&&(!text.includes('LastPriceの固定1幅停止OR')||!text.includes('清算bid／ask')))throw Error('停止ORの価格基準');
   if(config.range_stop_kind==='witness_extreme'&&!text.includes('mid極値の1呼値外'))throw Error('固定極値停止');
   if(config.range_target_kind==='center'&&!text.includes('新規判断時の中心へLastPrice'))throw Error('当時中心固定');
   if(config.range_target_kind==='center_plus'&&!text.includes('中心から順行側へ0.5幅'))throw Error('中心拡張目標');
   if(config.range_failure_reentry_kind!=='legacy'&&(!text.includes('極値破りの返済予約と料金後の実損切り')||!text.includes('解除行より後に新中心')))throw Error('実損切り後の新準備説明');
   if(config.range_failure_reentry_kind==='prepare_reset'&&!text.includes('全参照窓が返済後'))throw Error('新窓の必要条件');
  }
 }
 const rows=q('comparison').querySelector('tbody').rows;if(rows.length!==data.highlights.length)throw Error('主比較行数');
 for(let i=0;i<rows.length;i++){if(rows[i].dataset.id!==data.highlights[i])throw Error('主比較ID');for(let j=0;j<2;j++){const symbol=['TOPIX','NK225'][j],value=data.results[data.highlights[i]].periods['全31'][symbol],s=data.results[data.highlights[i]].stability['全31'][symbol],offset=1+j*7;number(rows[i].cells[offset],s.mean_losing_session_yen);number(rows[i].cells[offset+1],s.worst_session_loss_yen);unit(rows[i].cells[offset+4],s.downside_rms_units);number(rows[i].cells[offset+5],value.net);if(rows[i].cells[offset+2].firstChild.textContent!==`${value.positive_sessions} / ${s.active_sessions}`||rows[i].cells[offset+2].querySelector('small').textContent!==percent(s.positive_session_rate)||Number(rows[i].cells[offset+3].textContent)!==s.no_trade_sessions||rows[i].cells[offset+6].textContent!==percent(value.profit_share)||rows[i].cells[offset+5].querySelector('small').textContent!==`設定${s.configured_quantity}枚・保有最大${Math.max(value.maximums.held_long,value.maximums.held_short)}枚・${value.campaigns}親`)throw Error('主比較安定性と件数');}}
 if(!['S10_M1_UNL','S40_M0_H30','S10_M0_UNL','S10_M2_UNL'].every(id=>data.highlights.includes(id)))throw Error('主と出口対照の欠落');
 if(JSON.stringify([...q('conclusion').children].map(node=>node.textContent))!==JSON.stringify(data.conclusion.slice(0,3))||JSON.stringify([...q('conclusion-detail').children].map(node=>node.textContent))!==JSON.stringify(data.conclusion.slice(3)))throw Error('補足結論');
 const general=Object.entries(data.cause_notes||{}).filter(([name,value])=>!data.catalog.some(config=>config.id===name)&&typeof value==='string');
 if(q('cause-general').children.length!==general.length)throw Error('一般原因件数');
 for(let i=0;i<general.length;i++){const[name,value]=general[i],node=q('cause-general').children[i],citation=name==='場内返済'?' JPXの立会時間':'';if(node.dataset.cause!==name||node.textContent!==`${name}：${value}${citation}`)throw Error('一般原因内容');if(citation&&node.querySelector('a')?.href!=='https://www.jpx.co.jp/derivatives/rules/trading-hours/')throw Error('立会時間出典');}
 q('method-select').value=data.default_method;render();
 for(const item of document.querySelectorAll('.loss'))if(getComputedStyle(item).color!=='rgb(255, 144, 150)')throw Error('損失色');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 if(innerWidth>=1800&&q('comparison').parentElement.scrollWidth>q('comparison').parentElement.clientWidth+2)throw Error('広幅比較表の右端隠れ');
 if(/NaN|undefined|__DATA__|__STYLE__/.test(document.body.innerText))throw Error('未定義');
 if(window.browserErrors?.length)throw Error(browserErrors.join(' / '));
 return {全合格:true,条件切替数:18,セッション口座表示数:1116,照合金額数:count,比較単位照合数:unitCount,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor,JavaScriptエラー:0};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
