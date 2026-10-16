/**
 * 機能: 全20条件の実玉群と親の金額及び枚数表示を照合する。
 * 引数: なし。
 * @returns {object} 金額と画面の検査件数。
 */
function independentVerify(){
 const data=window.reportTest.data,q=id=>document.getElementById(id);
 let amounts=0,accounts=0,additionalAccounts=0;
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
 if(!data.additional||data.additional.全合格!==true||data.additional.条件数!==20)throw Error('追加合算証跡が未掲載');
 if(data.additional.primary!==data.primary||data.additional.selected!==data.selected||data.sessions.includes(data.additional.session))throw Error('追加で条件又は元31を変更');
 if(data.selection_level===5&&!q('selection-note').textContent.includes('採用候補ではありません'))throw Error('参考の活動不足を隠した');
 for(const config of data.catalog){
  q('method-select').value=config.id;window.reportTest.render();
  const rule=q('method-rule').textContent;
  if(!rule.includes('入口')||!rule.includes('途中')||!rule.includes('出口'))throw Error('入口途中出口の説明欠落');
  if(config.id.startsWith('B')){
   if(config.trend_initial_quantity!==1||config.trend_growth_cushion_basis!=='initial_width')throw Error('新12の初回と余裕基準');
   if(!rule.includes(`初回の損切り幅の${config.trend_growth_cushion_initial_multiple}倍`))throw Error('新余裕幅の説明不一致');
   if(rule.includes('停止線も保全する')!==config.trend_growth_preserve_stop)throw Error('停止線保全の説明不一致');
  }else if(config.trend_growth_mode===0){
   if(!rule.includes('追加しない'))throw Error('固定数量の説明不一致');
  }else if(!rule.includes(`${config.trend_growth_cushion_ticks}呼値`))throw Error('旧対照の呼値余裕の説明不一致');
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
  const additionalRows=Array.from(q('additional-results').rows);
  if(additionalRows.length!==4)throw Error('追加1と全32の二会計4行がありません');
  for(let i=0;i<2;i++)for(let basis=0;basis<2;basis++){
   const period=i===0?'additional1':'all32',kind=basis===0?'cohorts':'parents',row=additionalRows[i*2+basis];
   if(row.dataset.period!==period||row.dataset.basis!==kind)throw Error('追加表の期間又は会計種類');
   for(let s=0;s<2;s++){
    const symbol=['TOPIX','NK225'][s],item=data.additional.results[config.id][symbol],account=item[period];
    three(row.cells,2+s*3,basis===0?account.cohorts:account);additionalAccounts++;
    const known=item.known31,added=item.additional1,total=item.all32;
    for(const field of ['profit','loss','net','gross','fees','winning_lots','losing_lots','flat_lots','lots']){
     const values=basis===0?[known.cohorts,added.cohorts,total.cohorts]:[known,added,total];
     if(Math.abs(values[0][field]+values[1][field]-values[2][field])>1e-5)throw Error('元31と追加1の金額又は枚数の合算不一致');
     const original=basis===0?result.periods['全31'][symbol].cohorts:result.periods['全31'][symbol];
     if(Math.abs(values[0][field]-original[field])>1e-5)throw Error('追加表で元31損益を差し替えた');
    }
   }
  }
  for(const row of q('period-results').rows){
   const value=result.periods[row.dataset.period][row.dataset.symbol];three(row.cells,2,value.cohorts);
   number(row.cells[7],value.equity_drawdown);number(row.cells[8],value.without_best_day.net);
  }
  for(const row of q('direction-results').rows){
   const value=result.periods['全31'][row.dataset.symbol].cohort_directions[row.dataset.direction];three(row.cells,2,value);
  }
  for(const row of q('stability-results').rows){
   const value=result.stability[row.dataset.period][row.dataset.symbol];
   number(row.cells[3],value.session_net_median_yen);number(row.cells[4],value.session_net_q25_yen);
   ['active_net_median_units','active_net_q25_units','worst_intraday_drawdown_units'].forEach((key,i)=>{
    const node=row.cells[5+i].querySelector('[data-unit]'),expected=value[key];
    if(!node||(expected==null?node.dataset.unit!=='null':Math.abs(Number(node.dataset.unit)-expected)>1e-10))throw Error('安定性比較単位の不一致');
   });
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
  if(row.cells[1].firstChild.textContent.trim()!==`${s.losing_sessions} / ${s.active_sessions}`)throw Error('活動場を分母にした赤字頻度');
  number(row.cells[2],s.mean_losing_session_yen);number(row.cells[3],s.worst_session_loss_yen);number(row.cells[6],r.net);
  if(Math.abs(Number(row.cells[6].querySelector('[data-best-day-net]').dataset.bestDayNet)-r.without_best_day.net)>1e-5)throw Error('最大利益日除外');
 }
 q('method-select').value=data.primary;window.reportTest.render();
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面外への横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 if(window.browserErrors.length)throw Error(window.browserErrors.join(' / '));
 return {全合格:true,条件数:20,会計表示数:accounts,追加会計表示数:additionalAccounts,金額表示数:amounts,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
