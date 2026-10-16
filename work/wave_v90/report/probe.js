/**
 * 機能: 全42手法の金額・枚数・源別・期間と画面品質を元会計へ照合する。
 * @returns {object} 照合数と画面品質の独立検査結果。
 */
function independentVerify(){
 const data=window.reportTest.data,render=window.reportTest.render,q=id=>document.getElementById(id);let count=0;
 const number=(cell,expected)=>{const node=cell.querySelector('[data-number]');if(!node||Math.abs(Number(node.dataset.number)-expected)>1e-5)throw Error('元金額との差');if(Number(node.textContent.replace(/[+,円]/g,''))!==Math.round(expected))throw Error('表示金額');count++;};
 const percent=value=>value==null?'—':(value*100).toFixed(1)+'%';
 if(q('method-select').options.length!==42||data.sessions.length!==30)throw Error('条件又は場数');
 for(const config of data.catalog){
  q('method-select').value=config.id;render();const result=data.results[config.id],rows=q('session-results').rows;
  if(rows.length!==31)throw Error('30場と合計の行数');
  for(let i=0;i<31;i++)for(let j=0;j<2;j++){
   const symbol=['TOPIX','NK225'][j],value=i===30?result.periods['全30'][symbol]:result.rows.find(r=>r.session===data.sessions[i]&&r.symbol===symbol);
   if(i<30&&rows[i].dataset.session!==data.sessions[i])throw Error('場名');
   ['profit','loss','net'].forEach((field,k)=>number(rows[i].cells[1+j*3+k],value[field]));
   const expected=[`${value.winning_lots.toLocaleString('ja-JP')}枚`,`${value.losing_lots.toLocaleString('ja-JP')}枚`,`勝−負 ${(value.winning_lots-value.losing_lots).toLocaleString('ja-JP')}枚`];
   expected.forEach((text,k)=>{if(rows[i].cells[1+j*3+k].querySelector('small').textContent!==text)throw Error('決済枚数');});
  }
  const periods=q('period-results').rows;if(periods.length!==10)throw Error('期間の行数');
  for(const row of periods){const value=result.periods[row.dataset.period][row.dataset.symbol];for(const[i,field]of[[2,'net'],[6,'fees'],[7,'equity_drawdown']])number(row.cells[i],value[field]);number(row.cells[8],value.without_best_day.net);if(row.cells[3].textContent!==percent(value.profit_share)||row.cells[4].textContent!==`${value.positive_sessions} / ${value.losing_sessions} / ${value.no_trade_sessions}`||Number(row.cells[5].textContent)!==value.campaigns)throw Error('期間割合と件数');}
  const sources=q('source-results').rows;if(sources.length!==4)throw Error('源の行数');
  for(const row of sources){const value=result.periods['全30'][row.dataset.symbol].sources[row.dataset.source];for(const[i,field]of[[2,'profit'],[3,'loss'],[4,'net'],[5,'fees']])number(row.cells[i],value[field]);if(Number(row.cells[6].textContent)!==value.campaigns)throw Error('源別親数');}
  const directions=q('direction-results').rows;if(directions.length!==4)throw Error('方向の行数');
  for(const row of directions){const value=result.periods['全30'][row.dataset.symbol].directions[row.dataset.direction];['profit','loss','net'].forEach((field,k)=>number(row.cells[2+k],value[field]));if(Number(row.cells[5].textContent)!==value.campaigns)throw Error('方向別親数');}
  for(const row of q('cause-results').rows){const a=result.periods['全30'][row.dataset.symbol],b=data.results[row.dataset.reference].periods['全30'][row.dataset.symbol];['net','profit','loss','fees'].forEach((field,k)=>number(row.cells[2+k],a[field]-b[field]));if(Number(row.cells[6].textContent)!==a.campaigns-b.campaigns)throw Error('差の件数');}
  const text=q('method-rule').textContent;
  if(config.selection==='fixed'&&!text.includes('選択は加えません'))throw Error('固定配分説明');
  if(config.selection==='regime'&&!text.includes('一源だけ'))throw Error('排他選択説明');
  if(config.selection!=='fixed'&&(!text.includes(`${config.high_er}以上`)||!text.includes(`${config.low_er}以下`)||!text.includes(`${config.confirm_seconds}秒`)))throw Error('状態閾値説明');
  if(config.cancel_pending&&!text.includes('未約定を取消'))throw Error('取消説明');
  if(config.exit_opposite_range&&!text.includes('反対の追従'))throw Error('途中返済説明');
  if(config.range_budget&&config.improve_limit&&!text.includes('気配改善代理'))throw Error('約定価格改善説明');
  if(config.range_budget&&!config.improve_limit&&!text.includes('価格改善なし対照'))throw Error('悲観価格対照説明');
  if(config.activate_anchor&&!text.includes('当時価格へ更新'))throw Error('基準更新説明');
 }
 const rows=q('comparison').querySelector('tbody').rows;if(rows.length!==data.highlights.length)throw Error('主比較行数');
 for(let i=0;i<rows.length;i++){if(rows[i].dataset.id!==data.highlights[i])throw Error('主比較ID');for(let j=0;j<2;j++){const value=data.results[data.highlights[i]].periods['全30'][['TOPIX','NK225'][j]];number(rows[i].cells[1+j*4],value.net);number(rows[i].cells[4+j*4],value.equity_drawdown);if(rows[i].cells[2+j*4].textContent!==percent(value.profit_share)||rows[i].cells[3+j*4].textContent!==`${value.positive_sessions} / ${value.session_count}`||rows[i].cells[1+j*4].querySelector('small').textContent!==`${value.campaigns}親`)throw Error('主比較割合と件数');}}
 q('method-select').value=data.default_method;render();
 for(const item of document.querySelectorAll('.loss'))if(getComputedStyle(item).color!=='rgb(255, 144, 150)')throw Error('損失色');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 if(/NaN|undefined|__DATA__|__STYLE__/.test(document.body.innerText))throw Error('未定義');
 if(window.browserErrors?.length)throw Error(browserErrors.join(' / '));
 return {全合格:true,条件切替数:42,セッション口座表示数:2520,照合金額数:count,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor,JavaScriptエラー:0};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
