/**
 * 機能: 全38手法の金額・枚数・源別・期間と画面品質を元会計へ照合する。
 * @returns {object} 照合数と画面品質の独立検査結果。
 */
function independentVerify(){
 const data=window.reportTest.data,render=window.reportTest.render,q=id=>document.getElementById(id);let count=0;
 const number=(cell,expected)=>{const node=cell.querySelector('[data-number]');if(!node||Math.abs(Number(node.dataset.number)-expected)>1e-5)throw Error('元金額との差');if(Number(node.textContent.replace(/[+,円]/g,''))!==Math.round(expected))throw Error('表示金額');count++;};
 const percent=value=>value==null?'—':(value*100).toFixed(1)+'%';
 if(q('method-select').options.length!==38||data.sessions.length!==31)throw Error('条件又は場数');
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
  const periods=q('period-results').rows;if(periods.length!==14)throw Error('期間の行数');
  for(const row of periods){const value=result.periods[row.dataset.period][row.dataset.symbol];for(const[i,field]of[[2,'net'],[6,'fees'],[7,'equity_drawdown']])number(row.cells[i],value[field]);number(row.cells[8],value.without_best_day.net);if(row.cells[3].textContent!==percent(value.profit_share)||row.cells[4].textContent!==`${value.positive_sessions} / ${value.losing_sessions} / ${value.no_trade_sessions}`||Number(row.cells[5].textContent)!==value.campaigns)throw Error('期間割合と件数');}
  const sources=q('source-results').rows;if(sources.length!==4)throw Error('源の行数');
  for(const row of sources){const value=result.periods['全31'][row.dataset.symbol].sources[row.dataset.source];for(const[i,field]of[[2,'profit'],[3,'loss'],[4,'net'],[5,'fees']])number(row.cells[i],value[field]);if(Number(row.cells[6].textContent)!==value.campaigns)throw Error('源別親数');}
  const directions=q('direction-results').rows;if(directions.length!==4)throw Error('方向の行数');
  for(const row of directions){const value=result.periods['全31'][row.dataset.symbol].directions[row.dataset.direction];['profit','loss','net'].forEach((field,k)=>number(row.cells[2+k],value[field]));if(Number(row.cells[5].textContent)!==value.campaigns)throw Error('方向別親数');}
  for(const row of q('cause-results').rows){const a=result.periods['全31'][row.dataset.symbol],b=data.results[row.dataset.reference].periods['全31'][row.dataset.symbol];['net','profit','loss','fees'].forEach((field,k)=>number(row.cells[2+k],a[field]-b[field]));if(Number(row.cells[6].textContent)!==a.campaigns-b.campaigns)throw Error('差の件数');}
  const text=q('method-rule').textContent;
  if(!text.includes('入口：')||!text.includes('途中：')||!text.includes('出口：'))throw Error('三部品説明');
  if(config.selection==='regime'&&!text.includes('一源だけ'))throw Error('排他説明');
  if(config.persistent_arm&&(!text.includes('分類不明でも基準を保持')||!text.includes('基準±3幅')))throw Error('準備解除説明');
  if(config.reverse_sources!=='none'&&(!text.includes(`${config.reverse_confirm_seconds}秒`)||!text.includes('ER不要')))throw Error('反対出口説明');
  if(config.reverse_kind==='either'&&!text.includes('別々に確認してからOR'))throw Error('独立OR時計');
  if(config.range_budget&&config.range_profit_mode==='trail'&&!text.includes(`${config.profit_trail_widths}幅追跡`))throw Error('利益追跡');
  if(config.trend_budget&&config.trend_hold_seconds>=1e20&&!text.includes('固定保有期限なし'))throw Error('保有期限');
 }
 const fresh=q('fresh-results').rows;if(fresh.length!==data.fresh_highlights.length)throw Error('追加場行数');
 for(let i=0;i<fresh.length;i++){if(fresh[i].dataset.id!==data.fresh_highlights[i])throw Error('追加場手法');for(let j=0;j<2;j++){const value=data.results[data.fresh_highlights[i]].periods['追加1'][['TOPIX','NK225'][j]];['profit','loss','net'].forEach((field,k)=>number(fresh[i].cells[1+j*3+k],value[field]));if(fresh[i].cells[3+j*3].querySelector('small').textContent!==`片方向最大占有${Math.max(value.maximums.occupied_long,value.maximums.occupied_short)}枚`)throw Error('追加場占有');}}
 const rows=q('comparison').querySelector('tbody').rows;if(rows.length!==data.highlights.length)throw Error('主比較行数');
 for(let i=0;i<rows.length;i++){if(rows[i].dataset.id!==data.highlights[i])throw Error('主比較ID');for(let j=0;j<2;j++){const symbol=['TOPIX','NK225'][j],value=data.results[data.highlights[i]].periods['全31'][symbol],old=data.results[data.highlights[i]].periods['旧30'][symbol];number(rows[i].cells[1+j*5],value.net);number(rows[i].cells[2+j*5],old.net);number(rows[i].cells[5+j*5],value.equity_drawdown);if(rows[i].cells[3+j*5].textContent!==percent(value.profit_share)||rows[i].cells[4+j*5].textContent!==`${value.positive_sessions} / ${value.session_count}`||rows[i].cells[1+j*5].querySelector('small').textContent!==`${value.campaigns}親・片方向最大占有${Math.max(value.maximums.occupied_long,value.maximums.occupied_short)}枚`)throw Error('主比較割合と件数');}}
 if(!data.highlights.includes('J10'))throw Error('同上限追従対照の欠落');
 const effects=q('allocation-summary').querySelectorAll('[data-reference]');if(effects.length!==2)throw Error('配分比較の区別');
 for(const reference of ['J8','J10'])for(const symbol of ['TOPIX','NK225']){
  const context=q('allocation-summary').querySelector(`[data-reference="${reference}"]`),nodes=context.querySelector(`[data-symbol="${symbol}"]`).querySelectorAll('[data-number]'),a=data.results.M82.periods['全31'][symbol],b=data.results[reference].periods['全31'][symbol],expected=[a.net-b.net,a.equity_drawdown-b.equity_drawdown];
  if(nodes.length!==2)throw Error('配分効果セル');
  for(let i=0;i<2;i++){if(Math.abs(Number(nodes[i].dataset.number)-expected[i])>1e-5||Number(nodes[i].textContent.replace(/[+,円]/g,''))!==Math.round(expected[i]))throw Error('配分効果金額');count++;}
 }
 if(!q('allocation-summary').querySelector('[data-reference="J8"]').textContent.includes('追従8枚への反発2枚追加')||!q('allocation-summary').querySelector('[data-reference="J10"]').textContent.includes('同上限で追従10枚を8：2へ配分変更'))throw Error('配分比較の説明');
 if(JSON.stringify([...q('conclusion').children].map(node=>node.textContent))!==JSON.stringify(data.conclusion.slice(0,3))||JSON.stringify([...q('conclusion-detail').children].map(node=>node.textContent))!==JSON.stringify(data.conclusion.slice(3)))throw Error('補足結論');
 const general=Object.entries(data.cause_notes||{}).filter(([name,value])=>!data.catalog.some(config=>config.id===name)&&typeof value==='string');
 if(q('cause-general').children.length!==general.length)throw Error('一般原因件数');
 for(let i=0;i<general.length;i++){const[name,value]=general[i],node=q('cause-general').children[i];if(node.dataset.cause!==name||node.textContent!==`${name}：${value}`)throw Error('一般原因内容');}
 q('method-select').value=data.default_method;render();
 for(const item of document.querySelectorAll('.loss'))if(getComputedStyle(item).color!=='rgb(255, 144, 150)')throw Error('損失色');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 if(/NaN|undefined|__DATA__|__STYLE__/.test(document.body.innerText))throw Error('未定義');
 if(window.browserErrors?.length)throw Error(browserErrors.join(' / '));
 return {全合格:true,条件切替数:38,セッション口座表示数:2356,照合金額数:count,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor,JavaScriptエラー:0};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
