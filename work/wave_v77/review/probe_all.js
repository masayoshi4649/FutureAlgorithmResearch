/**
 * 機能: 全492条件の一覧と全場表、未実施表示、絞込を独立に照合する。
 * @returns {object} 表示検査の件数と合否。
 */
function verifyAll(){
 const {D,STATE,render,condition,filtered}=window.reportTest;let amounts=0,views=0;
 const number=cell=>Number(cell.textContent.replace(/[円,＋+\s]/g,''));
 if(D.methods.length!==492)throw Error('固定条件数');
 for(const symbol of ['TOPIX','NK225']){
  document.getElementById('symbol').value=symbol;
  for(const period of D.periodNames){
   document.getElementById('period').value=period;render();const rows=document.querySelector('.ranking-table tbody').rows;
   if(rows.length!==492)throw Error('一覧件数');
   for(const row of rows){const m=D.methods.find(x=>x.id===row.dataset.methodId),a=m.periods[period]?.[symbol];
    if(!a){if(!row.textContent.includes('未実施'))throw Error('未見未実施を数値化');continue;}
    for(const [column,field] of [[4,'profit'],[5,'loss'],[6,'net']]){if(number(row.cells[column])!==Math.round(a[field]))throw Error('一覧金額');amounts++;}
   }views++;
  }
  for(const m of D.methods){
   const container=document.createElement('div');container.innerHTML=condition(m);const rows=container.querySelector('.session-table tbody').rows;
   if(rows.length!==32)throw Error('全場と合計行数');
   for(let j=0;j<30;j++){const a=m.rows.find(x=>x.session===D.sessions[j]&&x.symbol===symbol);
    if(!a){if(!rows[j].textContent.includes('未実施'))throw Error('未見未実施行');continue;}
    for(const [column,field] of [[1,'profit'],[2,'loss'],[3,'net']]){if(number(rows[j].cells[column])!==Math.round(a[field]))throw Error('全条件全場金額');amounts++;}
   }views++;
  }
 }
 for(const family of ['J','Q','P']){document.getElementById('family').value=family;render();if(filtered().length!==164)throw Error('群絞込');views++;}
 document.getElementById('family').value='';document.getElementById('symbol').value='TOPIX';document.getElementById('period').value='全29';render();
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義');
 return {全合格:true,表示切替数:views,金額照合数:amounts,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:getComputedStyle(document.documentElement).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(verifyAll());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
