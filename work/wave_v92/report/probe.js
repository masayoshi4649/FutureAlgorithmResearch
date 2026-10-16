/**
 * 機能: 全36条件の金額・枚数・源別・期間を正式会計へ独立照合する。
 * @returns {object} 全表示の照合数と画面品質の検査結果。
 */
function independentVerify(){
 const data=window.reportTest.data,render=window.reportTest.render,q=id=>document.getElementById(id);let count=0;
 const number=(cell,expected)=>{const node=cell.querySelector('[data-number]');if(!node||Math.abs(Number(node.dataset.number)-expected)>1e-5)throw Error('元金額との差');if(Number(node.textContent.replace(/[+,円]/g,''))!==Math.round(expected))throw Error('表示金額');count++;};
 const percent=value=>value==null?'—':(value*100).toFixed(1)+'%';
 if(q('method-select').options.length!==36||data.sessions.length!==31)throw Error('条件又は場数');
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
  const sources=q('source-results').rows;if(sources.length!==4)throw Error('源の行数');
  for(const row of sources){const value=result.periods['全31'][row.dataset.symbol].sources[row.dataset.source];for(const[i,field]of[[2,'profit'],[3,'loss'],[4,'net'],[5,'fees']])number(row.cells[i],value[field]);if(Number(row.cells[6].textContent)!==value.campaigns)throw Error('源別親数');}
  const directions=q('direction-results').rows;if(directions.length!==4)throw Error('方向の行数');
  for(const row of directions){const value=result.periods['全31'][row.dataset.symbol].directions[row.dataset.direction];['profit','loss','net'].forEach((field,k)=>number(row.cells[2+k],value[field]));if(Number(row.cells[5].textContent)!==value.campaigns)throw Error('方向別親数');}
  for(const row of q('cause-results').rows){const a=result.periods['全31'][row.dataset.symbol],b=data.results[row.dataset.reference].periods['全31'][row.dataset.symbol];['net','profit','loss','fees'].forEach((field,k)=>number(row.cells[2+k],a[field]-b[field]));if(Number(row.cells[6].textContent)!==a.campaigns-b.campaigns)throw Error('差の件数');}
  const text=q('method-rule').textContent;
  if(!text.includes('入口：')||!text.includes('途中：')||!text.includes('出口：'))throw Error('三部品説明');
  if(config.persistent_arm&&(!text.includes('分類不明でも基準を保持')||!text.includes('基準±3幅')))throw Error('準備解除説明');
  if(config.range_entry_kind==='recovery_market'&&(!text.includes('次気配で成行新規')||config.recovery_confirmation==='both'&&!text.includes('両市場のmid')))throw Error('回復確認説明');
  if(config.range_stop_kind==='witness_extreme'&&!text.includes('極値の1呼値外'))throw Error('固定極値停止');
  if(config.range_reentry_kind!=='legacy'&&(!text.includes('旧中心を保持')||config.range_reentry_kind!=='keep'&&!text.includes('別行の新逸脱')))throw Error('中心帰還説明');
  if(config.range_budget&&config.range_profit_mode==='trail'&&!text.includes(`${config.profit_trail_widths}幅追跡`))throw Error('利益追跡');
 }
 const rows=q('comparison').querySelector('tbody').rows;if(rows.length!==data.highlights.length)throw Error('主比較行数');
 for(let i=0;i<rows.length;i++){if(rows[i].dataset.id!==data.highlights[i])throw Error('主比較ID');for(let j=0;j<2;j++){const symbol=['TOPIX','NK225'][j],value=data.results[data.highlights[i]].periods['全31'][symbol];number(rows[i].cells[1+j*4],value.net);number(rows[i].cells[4+j*4],value.equity_drawdown);if(rows[i].cells[2+j*4].textContent!==percent(value.profit_share)||rows[i].cells[3+j*4].textContent!==`${value.positive_sessions} / ${value.session_count}`||rows[i].cells[1+j*4].querySelector('small').textContent!==`${value.campaigns}親・片方向最大占有${Math.max(value.maximums.occupied_long,value.maximums.occupied_short)}枚`)throw Error('主比較割合と件数');}}
 if(!data.highlights.includes('J10')||!data.highlights.includes('R_B25_C_TR'))throw Error('同上限又は再参加対照の欠落');
 if(!data.highlights.includes('M_RB25_C')||!data.highlights.includes('M_KS25'))throw Error('固定配分2案の欠落');
 if(data.allocation_diagnostic){
  const items=data.allocation_diagnostic.行,top=items.find(row=>row.手法==='M_RB25_C'&&row.銘柄==='TOPIX'),nk=items.find(row=>row.手法==='M_RB25_C'&&row.銘柄==='NK225');
  const expected=`M_RB25_Cの源別場収支相関はTOPIX${top.源別場収支相関.toFixed(3)}・日経${nk.源別場収支相関.toFixed(3)}でも、両源赤字は${top.二源とも赤字場数}/${nk.二源とも赤字場数}場、追従赤字を合計黒字へ救った場は双方${top.追従赤字から合計黒字場数}でした。同上限J10より場収支の標準偏差は小さくなりましたが、収支も減りました。`;
  if(q('allocation-diagnosis').textContent!==expected||top.追従赤字から合計黒字場数!==nk.追従赤字から合計黒字場数)throw Error('固定配分診断の説明');
 }
 if(JSON.stringify([...q('conclusion').children].map(node=>node.textContent))!==JSON.stringify(data.conclusion.slice(0,3))||JSON.stringify([...q('conclusion-detail').children].map(node=>node.textContent))!==JSON.stringify(data.conclusion.slice(3)))throw Error('補足結論');
 const general=Object.entries(data.cause_notes||{}).filter(([name,value])=>!data.catalog.some(config=>config.id===name)&&typeof value==='string');
 if(q('cause-general').children.length!==general.length)throw Error('一般原因件数');
 for(let i=0;i<general.length;i++){const[name,value]=general[i],node=q('cause-general').children[i];if(node.dataset.cause!==name||node.textContent!==`${name}：${value}`)throw Error('一般原因内容');}
 q('method-select').value=data.default_method;render();
 for(const item of document.querySelectorAll('.loss'))if(getComputedStyle(item).color!=='rgb(255, 144, 150)')throw Error('損失色');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 if(/NaN|undefined|__DATA__|__STYLE__/.test(document.body.innerText))throw Error('未定義');
 if(window.browserErrors?.length)throw Error(browserErrors.join(' / '));
 return {全合格:true,条件切替数:36,セッション口座表示数:2232,照合金額数:count,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor,JavaScriptエラー:0};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
