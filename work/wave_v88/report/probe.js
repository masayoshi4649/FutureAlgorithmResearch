/**
 * 機能: 全22配分・全30場・期間・源別表を保存数値と照合する。
 * @returns {object} 検査件数と画面品質。
 */
function independentVerify(){
 const d=window.reportTest.data,render=window.reportTest.render,q=id=>document.getElementById(id);
 let numbers=0,views=0;
 const eq=(cell,expected)=>{const span=cell.querySelector('[data-number]');if(!span||Math.abs(Number(span.dataset.number)-expected)>1e-6)throw Error('数値:'+expected+' / '+cell.textContent);const plain=span.textContent.replace(/[+,円]/g,'');if(Number(plain)!==Math.round(expected))throw Error('表示数字');numbers++;};
 const percentage=v=>v==null?'—':(v*100).toFixed(1)+'%';
 if(q('method-select').options.length!==22)throw Error('選択数');
 for(const config of d.catalog){
  q('method-select').value=config.id;render();const result=d.results[config.id],rows=q('session-results').rows;
  if(rows.length!==31)throw Error('30場と合計');
  for(let i=0;i<30;i++){
   const name=d.sessions[i];if(rows[i].dataset.session!==name)throw Error('場名');
   for(let j=0;j<2;j++){
    const symbol=['TOPIX','NK225'][j],a=result.rows.find(r=>r.session===name&&r.symbol===symbol);
    ['profit','loss','net'].forEach((field,k)=>eq(rows[i].cells[1+j*3+k],a[field]));
    if(rows[i].cells[3+j*3].querySelector('small').textContent!==`${a.new_lots.toLocaleString('ja-JP')} / ${a.closed_lots.toLocaleString('ja-JP')}枚`)throw Error('枚数');
   }
  }
  for(let j=0;j<2;j++)['profit','loss','net'].forEach((field,k)=>eq(rows[30].cells[1+j*3+k],result.periods['全30'][['TOPIX','NK225'][j]][field]));
  const periods=q('period-results').rows;if(periods.length!==6)throw Error('期間数');
  for(const row of periods){const a=result.periods[row.dataset.period][row.dataset.symbol];for(const [index,field]of[[2,'net'],[6,'fees'],[7,'max_drawdown'],[8,'best_three_removed']])eq(row.cells[index],a[field]);if(row.cells[3].textContent!==percentage(a.profit_share)||row.cells[4].textContent!==`${a.positive_sessions} / ${a.negative_sessions} / ${a.no_trade_sessions}`||row.cells[5].textContent!==String(a.campaigns))throw Error('期間比率/場/親');}
  const sources=q('source-results').rows;if(sources.length!==6)throw Error('源表');
  for(const row of sources){const list=result.rows.filter(r=>r.symbol===row.dataset.symbol),a=d.source_contributions[config.id]['全30'][row.dataset.symbol][row.dataset.source];for(const[index,field]of[[4,'net'],[5,'fees']])eq(row.cells[index],list.reduce((sum,r)=>sum+r.source_totals[row.dataset.source][field],0));eq(row.cells[2],a.profit);eq(row.cells[3],a.loss);if(row.cells[6].textContent!==String(a.campaigns))throw Error('源別親');}
  views++;
 }
 // ----------------------------------------
 const compare=(body,ids)=>{const rows=body.rows;if(rows.length!==ids.length)throw Error('比較行数');for(let i=0;i<ids.length;i++){const id=ids[i];if(rows[i].dataset.id!==id)throw Error('比較ID');for(let j=0;j<2;j++){const a=d.results[id].periods['全30'][['TOPIX','NK225'][j]];eq(rows[i].cells[1+j*4],a.net);eq(rows[i].cells[4+j*4],a.max_drawdown);if(rows[i].cells[2+j*4].textContent!==percentage(a.profit_share)||rows[i].cells[3+j*4].textContent!==`${a.positive_sessions} / ${a.sessions}`)throw Error('比較割合/場数');}}};
 compare(q('comparison').querySelector('tbody'),d.highlights);compare(q('all-comparison'),d.catalog.map(c=>c.id));
 const pairs=['TOPIX','NK225'].flatMap(symbol=>(d.diversity[symbol]?.pairs||[]).map(p=>({symbol,...p}))),diversity=q('diversity-results').rows;
 if(diversity.length!==pairs.length)throw Error('補完性の行数');
 for(let i=0;i<pairs.length;i++){const p=pairs[i],r=diversity[i];for(const[index,field]of[[2,'session_correlation'],[3,'minute_correlation']])if(r.cells[index].textContent!==(p[field]==null?'—':p[field].toFixed(3)))throw Error('相関');for(const[index,field]of[[4,'opposite_active_fraction'],[5,'same_active_fraction'],[6,'mutual_active_fraction']])if(r.cells[index].textContent!==percentage(p[field]))throw Error('保有重複');}
 const risk=q('risk-results').rows;if(risk.length!==Object.keys(d.risk_attribution).length*2)throw Error('同枚数対照数');for(const row of risk){const r=d.risk_attribution[row.dataset.id]['全30'][row.dataset.symbol],a=r.allocated_gu_only,b=r.portfolio;eq(row.cells[2],a.net);eq(row.cells[3],b.net);eq(row.cells[4],a.max_drawdown);eq(row.cells[5],b.max_drawdown);if(row.cells[6].textContent!==`${a.return_drawdown.toFixed(3)} → ${b.return_drawdown.toFixed(3)}`||row.cells[7].textContent!==`${a.positive_sessions} → ${b.positive_sessions}`)throw Error('同枚数比率/場');}
 const failures=q('failure-results').rows;if(failures.length!==6)throw Error('赤字場数');for(const row of failures){const a=d.diagnosis[d.primary][row.dataset.symbol].find(r=>r.session===row.dataset.session);['GU','M3','C03'].forEach((s,j)=>eq(row.cells[2+j],a.sources[s].net));eq(row.cells[5],a.net);}
 q('method-select').value=d.primary;render();
 for(const loss of document.querySelectorAll('.loss')){if(loss.textContent.includes('+')||getComputedStyle(loss).color!=='rgb(255, 144, 150)')throw Error('損失表示色/符号');}
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 if(/NaN|undefined|__DATA__|__STYLE__/.test(document.body.innerText))throw Error('未定義');
 if(window.browserErrors?.length)throw Error(browserErrors.join(' / '));
 return {全合格:true,配分切替数:views,照合金額数:numbers,セッション口座表示数:views*60,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor,JavaScriptエラー:0};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
