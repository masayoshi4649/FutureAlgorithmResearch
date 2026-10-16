/**
 * 機能: 全20条件の実玉群と親の金額及び枚数表示を照合する。
 * 引数: なし。
 * @returns {object} 金額と画面の検査件数。
 */
function independentVerify(){
 const data=window.reportTest.data,q=id=>document.getElementById(id);
 let amounts=0,accounts=0;
 const number=(cell,expected)=>{
  const node=cell.querySelector('[data-number]');
  if(!node||Math.abs(Number(node.dataset.number)-expected)>1e-5)throw Error('原金額の不一致');
  if(Number(node.textContent.replace(/[+,円]/g,''))!==Math.round(expected))throw Error('表示金額の不一致');
  amounts++;
 };
 const three=(cells,start,value)=>{
  ['profit','loss','net'].forEach((key,i)=>number(cells[start+i],value[key]));
  if(cells[start].querySelector('small').textContent!==`${value.winning_lots.toLocaleString('ja-JP')}枚`)throw Error('利益玉枚数');
  if(cells[start+1].querySelector('small').textContent!==`${value.losing_lots.toLocaleString('ja-JP')}枚`)throw Error('損失玉枚数');
  const text=`全決済${value.lots.toLocaleString('ja-JP')}枚・勝−負 ${(value.winning_lots-value.losing_lots).toLocaleString('ja-JP')}枚`;
  if(cells[start+2].querySelector('small').textContent!==text)throw Error('全返済及び枚数差');
 };
 if(q('method-select').options.length!==20||data.sessions.length!==31)throw Error('条件数と全場数');
 if(data.selection_level===5&&!q('selection-note').textContent.includes('採用候補ではありません'))throw Error('参考の活動不足を隠した');
 for(const config of data.catalog){
  q('method-select').value=config.id;window.reportTest.render();
  const result=data.results[config.id],rows=Array.from(q('session-results').rows);
  if(rows.length!==64)throw Error('31場及び合計の二会計');
  for(let i=0;i<32;i++)for(let basis=0;basis<2;basis++){
   const row=rows[i*2+basis],kind=basis===0?'cohorts':'parents';
   if(row.dataset.basis!==kind||row.dataset.session!==(i===31?'全31場 合計':data.sessions[i]))throw Error('会計種類又は場名');
   for(let s=0;s<2;s++){
    const symbol=['TOPIX','NK225'][s],value=i===31?result.periods['全31'][symbol]:result.rows.find(r=>r.session===data.sessions[i]&&r.symbol===symbol);
    three(row.cells,2+s*3,basis===0?value.cohorts:value);accounts++;
   }
  }
  for(const row of q('period-results').rows){
   const value=result.periods[row.dataset.period][row.dataset.symbol];three(row.cells,2,value.cohorts);
   number(row.cells[7],value.equity_drawdown);number(row.cells[8],value.without_best_day.net);
  }
  for(const row of q('direction-results').rows){
   const value=result.periods['全31'][row.dataset.symbol].cohort_directions[row.dataset.direction];three(row.cells,2,value);
  }
  for(const row of q('cause-results').rows){
   const symbol=row.dataset.symbol,a=result.periods['全31'][symbol],b=data.results[row.dataset.reference].periods['全31'][symbol];
   [a.net-b.net,a.cohorts.profit-b.cohorts.profit,a.cohorts.loss-b.cohorts.loss,a.fees-b.fees].forEach((x,i)=>number(row.cells[2+i],x));
  }
  for(const row of q('hidden-loss-results').rows){
   const d=data.report_diagnostics?.[config.id]?.[row.dataset.symbol]?.winning_parent_losing_cohorts;
   if(d){if(Number(row.cells[1].textContent)!==d.losing_cohorts||Number(row.cells[2].textContent)!==d.losing_lots)throw Error('親内負け玉');number(row.cells[3],d.loss);}
   else if(!row.cells[3].hasAttribute('data-unknown'))throw Error('未掲載をゼロへ偽装');
  }
  for(const row of q('budget-results').rows){
   const d=data.report_diagnostics?.[config.id]?.[row.dataset.symbol]?.risk_budget;
   if(d){if(Number(row.cells[1].textContent)!==d.excess_parents)throw Error('予算超過親数');['realized_excess_sum','maximum_realized_excess','maximum_observed_excess'].forEach((k,i)=>number(row.cells[2+i],d[k]));}
   else if(!row.cells[2].hasAttribute('data-unknown'))throw Error('予算の未掲載をゼロへ偽装');
  }
 }
 for(const symbol of ['TOPIX','NK225'])for(const row of q(`comparison-${symbol}`).querySelector('tbody').rows){
  const r=data.results[row.dataset.id].periods['全31'][symbol],s=data.results[row.dataset.id].stability['全31'][symbol];
  if(Number(row.cells[1].dataset.losingSessions)!==s.losing_sessions)throw Error('赤字場数');
  number(row.cells[2],s.mean_losing_session_yen);number(row.cells[3],s.worst_session_loss_yen);number(row.cells[6],r.net);
  if(Math.abs(Number(row.cells[6].querySelector('[data-best-day-net]').dataset.bestDayNet)-r.without_best_day.net)>1e-5)throw Error('最大利益日除外');
 }
 q('method-select').value=data.primary;window.reportTest.render();
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面外への横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 if(window.browserErrors.length)throw Error(window.browserErrors.join(' / '));
 return {全合格:true,条件数:20,会計表示数:accounts,金額表示数:amounts,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
