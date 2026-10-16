/**
 * 機能: 全81条件の全場・期間・源別・見送り効果を保存数値と照合する。
 * @returns {object} 検査件数と画面品質。
 */
function independentVerify(){
 const data=window.reportTest.data,render=window.reportTest.render,q=id=>document.getElementById(id);
 let numbers=0,views=0;
 const eq=(cell,expected)=>{const span=cell.querySelector('[data-number]');if(!span||Math.abs(Number(span.dataset.number)-expected)>1e-6)throw Error('数値:'+expected+' / '+cell.textContent);const plain=span.textContent.replace(/[+,円]/g,'');if(Number(plain)!==Math.round(expected))throw Error('表示数字');numbers++;};
 const percentage=value=>value==null?'—':(value*100).toFixed(1)+'%';
 if(q('method-select').options.length!==81)throw Error('選択数');
 for(const config of data.catalog){
  q('method-select').value=config.id;render();const result=data.results[config.id],rows=q('session-results').rows;
  if(rows.length!==31)throw Error('30場と合計');
  for(let i=0;i<30;i++){
   const session=data.sessions[i];if(rows[i].dataset.session!==session)throw Error('場名');
   for(let j=0;j<2;j++){
    const symbol=['TOPIX','NK225'][j],value=result.rows.find(r=>r.session===session&&r.symbol===symbol);
    ['profit','loss','net'].forEach((field,k)=>eq(rows[i].cells[1+j*3+k],value[field]));
    if(rows[i].cells[3+j*3].querySelector('small').textContent!==`${value.new_lots.toLocaleString('ja-JP')} / ${value.closed_lots.toLocaleString('ja-JP')}枚`)throw Error('枚数');
   }
  }
  for(let j=0;j<2;j++)['profit','loss','net'].forEach((field,k)=>eq(rows[30].cells[1+j*3+k],result.periods['全30'][['TOPIX','NK225'][j]][field]));
  // ----------------------------------------
  const periods=q('period-results').rows;if(periods.length!==6)throw Error('期間数');
  for(const row of periods){const value=result.periods[row.dataset.period][row.dataset.symbol];for(const[index,field]of[[2,'net'],[6,'fees'],[7,'max_drawdown'],[8,'best_three_removed']])eq(row.cells[index],value[field]);if(row.cells[3].textContent!==percentage(value.profit_share)||row.cells[4].textContent!==`${value.positive_sessions} / ${value.negative_sessions} / ${value.no_trade_sessions}`||row.cells[5].textContent!==String(value.campaigns))throw Error('期間比率/場/親');}
  const sources=q('source-results').rows;if(sources.length!==6)throw Error('源表');
  for(const row of sources){const list=result.rows.filter(r=>r.symbol===row.dataset.symbol),value=data.source_contributions[config.id]['全30'][row.dataset.symbol][row.dataset.source];for(const[index,field]of[[4,'net'],[5,'fees']])eq(row.cells[index],list.reduce((sum,r)=>sum+r.source_totals[row.dataset.source][field],0));eq(row.cells[2],value.profit);eq(row.cells[3],value.loss);if(row.cells[6].textContent!==String(value.campaigns))throw Error('源別親');}
  const gates=q('gate-results').rows;if(gates.length!==6)throw Error('判断表');
  for(const row of gates){const value=result.periods[row.dataset.period][row.dataset.symbol];for(const[index,field]of[[2,'gate_eligible'],[3,'gate_allowed'],[4,'gate_rejected'],[5,'gate_warmup'],[6,'virtual_campaigns']])if(row.cells[index].textContent!==String(value[field]))throw Error('判断件数');}
  const differences=q('difference-results').rows;if(differences.length!==2)throw Error('見送り効果の行数');
  for(const row of differences){const value=data.differences[config.id]['全30'][row.dataset.symbol];for(const[index,field]of[[1,'base_net'],[2,'actual_net'],[3,'saved_loss'],[4,'missed_profit'],[5,'delta']])eq(row.cells[index],value[field]);}
  const g=config.gate,text=q('method-rule').textContent;
  if(g.mode==='all'){if(!text.includes('常に許可'))throw Error('常時参加説明');}
  else{
   if(g.mode==='share'&&(!text.includes(`直近${g.window}仮想親`)||!text.includes(`${Math.round(g.threshold*100)}%${g.reverse?'未満':'以上'}`)))throw Error('金額比説明');
   if(g.mode==='streak'&&!text.includes(`${g.loss_count}連敗`))throw Error('連敗説明');
   if(g.history_mode==='carry'&&!text.includes('過去成績だけ'))throw Error('成績持越説明');
   if(g.history_mode==='session'&&!text.includes('リセット'))throw Error('リセット説明');
  }
  views++;
 }
 // ----------------------------------------
 const compare=(body,ids)=>{const rows=body.rows;if(rows.length!==ids.length)throw Error('比較行数');for(let i=0;i<ids.length;i++){const id=ids[i];if(rows[i].dataset.id!==id)throw Error('比較ID');for(let j=0;j<2;j++){const value=data.results[id].periods['全30'][['TOPIX','NK225'][j]];eq(rows[i].cells[1+j*4],value.net);eq(rows[i].cells[4+j*4],value.max_drawdown);if(rows[i].cells[1+j*4].querySelector('small').textContent!==`${value.campaigns}親`||rows[i].cells[2+j*4].textContent!==percentage(value.profit_share)||rows[i].cells[3+j*4].textContent!==`${value.positive_sessions} / ${value.sessions}`)throw Error('比較割合/場/親');}}};
 compare(q('comparison').querySelector('tbody'),data.highlights);compare(q('all-comparison'),data.catalog.map(c=>c.id));
 const cases=q('case-results').rows;if(cases.length!==4)throw Error('具体親4行');
 for(let i=0;i<cases.length;i++){const value=data.cases[i],row=cases[i];if(row.dataset.case!==String(i)||row.cells[2].textContent!==value.clock.slice(11,19)||row.cells[3].textContent!==percentage(value.past_share)||row.cells[4].textContent!==(value.accepted?'参加を再開':'見送り'))throw Error('具体親の当時判断');eq(row.cells[5],value.base_net);}
 q('method-select').value=data.primary;render();
 for(const loss of document.querySelectorAll('.loss')){if(loss.textContent.includes('+')||getComputedStyle(loss).color!=='rgb(255, 144, 150)')throw Error('損失表示色/符号');}
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 if(/NaN|undefined|__DATA__|__STYLE__/.test(document.body.innerText))throw Error('未定義');
 if(window.browserErrors?.length)throw Error(browserErrors.join(' / '));
 return {全合格:true,条件切替数:views,照合金額数:numbers,セッション口座表示数:views*60,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor,JavaScriptエラー:0};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
