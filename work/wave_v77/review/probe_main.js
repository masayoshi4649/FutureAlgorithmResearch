/**
 * 機能: 全代表の商品・期間・全場と対照を操作し、実DOM金額と全売買点を照合する。
 * @returns {object} 表示検査の件数と合否。
 */
function verifyMain(){
 const {D,STATE,render}=window.reportTest;let views=0,amounts=0,markers=0;
 const number=cell=>Number(cell.textContent.replace(/[円,＋+\s]/g,''));
 for(const [idx,m] of D.methods.entries()){
  const e=document.querySelector('#method-'+idx),state=STATE.get(m.id);
  for(const symbol of ['TOPIX','NK225']){
   state.symbol=symbol;state.variant=m.id;
   for(const period of D.periodNames){
    state.period=period;render(e,m);const actual=e.querySelector('.comparison tbody tr'),a=m.periods[period][symbol];
    for(const [column,field] of [[1,'profit'],[2,'loss'],[3,'net'],[9,'fees']]){if(number(actual.cells[column])!==Math.round(a[field]))throw Error('期間金額 '+m.id+'/'+symbol+'/'+period+'/'+field);amounts++;}
    views++;
   }
   state.period='全30';render(e,m);
   const rows=e.querySelector('.session-table tbody').rows;
   if(rows.length!==31)throw Error('全30行と合計');
   for(let j=0;j<30;j++){
    const a=m.rows.find(r=>r.session===D.sessions[j]&&r.symbol===symbol);
    for(const [column,field] of [[1,'profit'],[2,'loss'],[3,'net'],[9,'fees']]){if(number(rows[j].cells[column])!==Math.round(a[field]))throw Error('全場金額');amounts++;}
   }
   for(const session of D.sessions){
    state.session=session;render(e,m);const key=session+'|'+symbol,orders=m.orders[key],svg=e.querySelector('.chart-svg');
    if(!svg||/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('売買図');
    if(svg.querySelectorAll('.order-marker').length!==orders.length)throw Error('注文点数');
    const rows=e.querySelector('.history-table tbody').rows;if(rows.length!==orders.length)throw Error('注文履歴');
    orders.forEach((o,k)=>{if(number(rows[k].cells[5])!==o[4]||number(rows[k].cells[6])!==o[5]||number(rows[k].cells[8])!==o[8])throw Error('注文表示');});
    markers+=orders.length;views++;
   }
   for(const c of m.controls){state.variant=c.id;render(e,m);const key=state.session+'|'+symbol;if(e.querySelectorAll('.order-marker').length!==c.orders[key].length)throw Error('対照切替');views++;}
  }
  state.symbol='TOPIX';state.period='全30';state.variant=m.id;state.session=D.sessions[0];render(e,m);
 }
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,表示切替数:views,金額照合数:amounts,売買点数:markers,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:getComputedStyle(document.documentElement).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(verifyMain());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
