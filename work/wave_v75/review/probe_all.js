/**
 * 機能: 全336条件の銘柄・期間・条件群と全セッションを表示照合する。
 * @returns {object} 検査件数と表示品質。
 */
function independentVerify(){
 const {D,STATE,condition,ranking}=window.reportTest;
 let cells=0,accounts=0,lists=0;
 const number=cell=>Number(cell.textContent.replace(/[,\s円＋+]/g,'').replace('−','-'));
 const near=(a,b,label)=>{if(!Number.isFinite(a)||Math.abs(a-b)>1e-6)throw Error(label+':'+a+'/'+b);};
 const percent=v=>v==null?'—':(v*100).toFixed(1)+'%';
 const change=(id,v)=>{const e=document.getElementById(id);e.value=v;e.dispatchEvent(new Event('change'));};
 const row=(tr,a)=>{
  for(const [i,k] of [[1,'profit'],[2,'loss'],[3,'net'],[5,'trades'],[7,'fees']]){near(number(tr.cells[i]),a[k],k);cells++;}
  near(a.profit-a.loss,a.net,'利益−損失');
  if(tr.cells[4].textContent!==percent(a.profit+a.loss?a.loss/(a.profit+a.loss):null)||tr.cells[6].textContent!==`${a.winning_lots}／${a.losing_lots}`)throw Error('比率/枚数');
  if(a.trades)near(number(tr.cells[8]),Math.sign(a.net)*Math.round(Math.abs(a.net/a.trades)),'平均');else if(tr.cells[8].textContent!=='—')throw Error('無取引');
 };
 const table=(id,values)=>{const trs=document.querySelector(`#${id} tbody`).rows;if(trs.length!==values.length)throw Error('行数');values.forEach((a,i)=>row(trs[i],a));};
 if(D.methods.length!==336||D.sessions.length!==29||D.selectedIds.length!==3||D.representativeIds.length!==7)throw Error('範囲');
 for(const symbol of ['TOPIX','NK225']){
  change('symbol',symbol);
  for(const period of ['前16','後13','全29']){
   change('period',period);change('group','all');change('family','all');change('sort','id');
   const trs=document.querySelector('#ranking tbody').rows,expected=[...D.methods].sort((a,b)=>a.id.localeCompare(b.id));
   if(trs.length!==336)throw Error('全一覧');
   expected.forEach((m,i)=>{const a=m.periods[period][symbol],tr=trs[i];if(tr.querySelector('button').dataset.id!==m.id)throw Error('ID順');for(const [j,k] of [[2,'profit'],[3,'loss'],[4,'net'],[6,'trades']])near(number(tr.cells[j]),a[k],k);if(tr.cells[5].textContent!==percent(a.money_loss_share))throw Error('一覧比率');near(number(tr.cells[8]),m.periods.全29.TOPIX.net,'全29TOP');near(number(tr.cells[9]),m.periods.全29.NK225.net,'全29NK');});lists++;
  }
  for(const m of D.methods){
   STATE.id=m.id;condition();
   table('period-table',['前16','後13','全29'].map(p=>m.periods[p][symbol]));
   table('sessions',[...D.sessions.map(s=>m.rows.find(r=>r.session===s&&r.symbol===symbol)),m.periods.全29[symbol]]);accounts+=29;
  }
 }
 for(const group of ['共同判定','自市場証拠の対照'])for(let family=1;family<=7;family++){
  change('group',group);change('family',String(family));const trs=document.querySelector('#ranking tbody').rows;
  if(trs.length!==24)throw Error('機構絞り込み');for(const tr of trs){const m=D.methods.find(m=>m.id===tr.querySelector('button').dataset.id);if(m.config.group!==group||m.config.family!==family)throw Error('群絞り込み');}lists++;
 }
 change('group','all');change('family','all');
 for(const order of ['net','share']){
  change('sort',order);const rs=Array.from(document.querySelector('#ranking tbody').rows).map(tr=>D.methods.find(m=>m.id===tr.querySelector('button').dataset.id).periods[STATE.period][STATE.symbol]);
  for(let i=1;i<rs.length;i++){if(order==='net'&&rs[i].net>rs[i-1].net)throw Error('収支順');if(order==='share'&&(rs[i].money_loss_share??Infinity)<(rs[i-1].money_loss_share??Infinity))throw Error('割合順');}lists++;
 }
 change('method',D.selectedIds[1]);if(STATE.id!==D.selectedIds[1]||decodeURIComponent(location.hash.slice(1))!==STATE.id)throw Error('選択hash');
 const button=document.querySelector('#ranking .method-link');button.click();if(STATE.id!==button.dataset.id)throw Error('一覧から選択');
 change('symbol','TOPIX');change('period','全29');change('method',D.selectedIds[1]);
 if(getComputedStyle(document.documentElement).colorScheme!=='dark')throw Error('暗色');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義');
 return {全合格:true,全条件数:D.methods.length,保存口座表示数:accounts,金額照合数:cells,一覧条件照合数:lists,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
