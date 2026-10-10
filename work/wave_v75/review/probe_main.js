/**
 * 機能: 固定台帳と主報告の全操作・金額・売買座標を独立照合する。
 * @returns {object} 照合件数と表示品質。
 */
function independentVerify(){
 const {D,STATE}=window.reportTest;
 let tables=0,accounts=0,markers=0,numbers=0,indexed=0;
 const number=cell=>Number(cell.textContent.replace(/[,\s円＋+]/g,'').replace('−','-'));
 const near=(a,b,label)=>{if(!Number.isFinite(a)||Math.abs(a-b)>1e-6)throw Error(label+':'+a+'/'+b);};
 const percent=v=>v==null?'—':(v*100).toFixed(1)+'%';
 const sum=(rs,k)=>rs.reduce((n,r)=>n+r[k],0);
 const row=(tr,a)=>{
  for(const [i,k] of [[1,'profit'],[2,'loss'],[3,'net'],[5,'trades'],[9,'fees']]){near(number(tr.cells[i]),a[k],k);numbers++;}
  near(a.profit-a.loss,a.net,'利益−損失');
  const share=a.profit+a.loss?a.loss/(a.profit+a.loss):null,payoff=a.wins&&a.losses?(a.profit/a.wins)/(a.loss/a.losses):null;
  if(tr.cells[4].textContent!==percent(share)||tr.cells[7].textContent!==percent(a.trades?a.wins/a.trades:null))throw Error('比率');
  if(a.trades)near(number(tr.cells[6]),Math.sign(a.net)*Math.round(Math.abs(a.net/a.trades)),'平均一取引');else if(tr.cells[6].textContent!=='—')throw Error('無取引平均');
  if(tr.cells[8].textContent!==(payoff==null?'—':payoff.toFixed(2)))throw Error('平均勝負比');
 };
 const table=(box,values)=>{const trs=box.querySelector('tbody').rows;if(trs.length!==values.length)throw Error('表件数');values.forEach((a,i)=>row(trs[i],a));tables++;};
 const change=(e,value)=>{e.value=value;e.dispatchEvent(new Event('change'));};
 if(D.methods.length!==3||D.families.length!==7||D.sessions.length!==29)throw Error('入力範囲');
 if(!D.sharedOpportunity||document.getElementById('shared-opportunity').hidden)throw Error('同機会診断');
 for(const symbol of ['TOPIX','NK225'])for(const period of ['前16','後13','全29']){
  change(document.getElementById('opportunity-symbol'),symbol);change(document.getElementById('opportunity-period'),period);
  const c=D.sharedOpportunity.比較[period][symbol],trs=document.querySelector('.opportunity-table tbody').rows;
  if(trs.length!==3)throw Error('診断の群数');
  ['全S1','相手確認あり','相手確認なし'].forEach((k,i)=>{const a=c[k],tr=trs[i];for(const [col,key] of [[1,'利益'],[2,'損失'],[3,'収支'],[5,'取引数']])near(number(tr.cells[col]),a[key],'診断:'+key);near(number(tr.cells[6]),Math.sign(a.収支)*Math.round(Math.abs(a.平均一取引収支)),'診断平均');if(tr.cells[4].textContent!==percent(a.金額損失割合)||tr.cells[7].textContent!==percent(a.勝率))throw Error('診断比率');});
  for(const k of ['利益','損失','収支','取引数'])near(c.相手確認あり[k]+c.相手確認なし[k],c.全S1[k],'群の和');tables++;
 }
 for(const [i,f] of D.families.entries()){
  const tr=document.querySelector(`.family-table [data-family="${f.family}"]`);
  near(number(tr.cells[5]),f.periods.全29.TOPIX.net,'七機構TOP');near(number(tr.cells[6]),f.periods.全29.NK225.net,'七機構NK');
  if(tr.cells[4].textContent!==(f.eligible?'充足':'件数不足'))throw Error('件数不足');
  change(document.getElementById('family-sensitivity'),String(i));
  for(const symbol of ['TOPIX','NK225'])for(const period of ['前16','後13','全29']){
   change(document.getElementById('family-symbol'),symbol);change(document.getElementById('family-period'),period);
   table(document.getElementById('family-delay-table'),f.sensitivity.flatMap(x=>[x.joint.periods[period][symbol],x.single.periods[period][symbol]]));
  }
 }
 for(const [i,m] of D.methods.entries()){
  const e=document.getElementById(`method-${i}`);
  for(const symbol of ['TOPIX','NK225']){
   e.querySelector(`[data-symbol="${symbol}"]`).click();if(STATE.get(i).symbol!==symbol)throw Error('銘柄操作');
   for(const period of ['前16','後13','全29']){
    change(e.querySelector('.period-select'),period);if(STATE.get(i).period!==period)throw Error('期間操作');
    table(e.querySelector('.comparison'),[m.periods[period][symbol],m.single.periods[period][symbol]]);
    table(e.querySelector('.delay-table'),m.sensitivity.flatMap(x=>[x.joint.periods[period][symbol],x.single.periods[period][symbol]]));
    const trs=e.querySelector('.detail-table tbody').rows;
    for(const [j,a] of [m.periods[period][symbol],m.single.periods[period][symbol]].entries()){
     if(trs[j].cells[1].textContent!==`${a.winning_lots}／${a.losing_lots}`)throw Error('勝負枚数');
     for(const [col,k] of [[2,'max_trade_loss'],[3,'drawdown'],[5,'spread_drag']])near(number(trs[j].cells[col]),a[k],k);
     if(trs[j].cells[4].textContent!==`${a.max_long}／${a.max_short}`)throw Error('最大枚数');
    }
   }
   const rows=D.sessions.map(session=>m.rows.find(r=>r.session===session&&r.symbol===symbol)),total=m.periods.全29[symbol];
   table(e.querySelector('.session-table'),[...rows,total]);table(e.querySelector('.week-table'),[...m.weeks[symbol],total]);
   for(const k of ['profit','loss','net','fees','trades','winning_lots','losing_lots']){near(sum(rows,k),total[k],'全場合計');near(sum(m.weeks[symbol],k),total[k],'週合計');}
   for(const variant of ['J','S']){
    change(e.querySelector('.variant-select'),variant);const source=variant==='J'?m:m.single;
    for(const [j,session] of D.sessions.entries()){
     if(j%2===0)e.querySelector(`.session-link[data-session="${session}"]`).click();else change(e.querySelector('.session-select'),session);
     if(STATE.get(i).session!==session||STATE.get(i).variant!==variant)throw Error('場と方式の操作');
     const key=session+'|'+symbol,orders=source.orders[key],bars=D.bars[key],svg=e.querySelector('.chart svg'),account=source.rows.find(r=>r.session===session&&r.symbol===symbol);
     if(!svg||/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('図の有限性');
     const ms=svg.querySelectorAll('.order-marker');if(ms.length!==orders.length||orders.length!==2*account.trades)throw Error('売買点数');
     const left=Math.min(...bars.map(b=>b[0]),...orders.map(o=>o[9])),right=Math.max(...bars.map(b=>b[0]+300),...orders.map(o=>o[9]));
     const values=bars.flatMap(b=>[b[2],b[3]]).concat(orders.map(o=>o[5])),lo=Math.min(...values),hi=Math.max(...values),pad=Math.max((hi-lo)*.08,symbol==='TOPIX'?.5:10);
     const x=t=>80+(t-left)/(right-left)*900,y=p=>20+(hi+pad-p)/(hi-lo+2*pad)*295;
     orders.forEach((o,k)=>{
      if(Number(ms[k].dataset.side)!==o[3]||Number(ms[k].dataset.open)!==o[7]||o[0]<=o[1])throw Error('売買種別/因果順');
      const shape=ms[k].querySelector(o[7]===1?'circle':'path');if(!shape)throw Error('売買形状');
      if(o[7]===1){near(Number(shape.getAttribute('cx')),x(o[9]),'新規x');near(Number(shape.getAttribute('cy')),y(o[5]),'新規y');}
      else{const xy=shape.getAttribute('d').match(/[-+]?\d*\.?\d+(?:e[-+]?\d+)?/gi).map(Number);near(xy[0],x(o[9]),'返済x');near(xy[1]+5,y(o[5]),'返済y');}
     });
     if(orders.length){const hs=e.querySelector('.history tbody').rows;if(hs.length!==orders.length)throw Error('履歴行数');orders.forEach((o,k)=>{near(number(hs[k].cells[2]),o[4],'履歴枚数');near(number(hs[k].cells[3]),o[5],'履歴値');if(hs[k].cells[5].textContent!==`${o[1]}→${o[0]}`)throw Error('履歴順');});}
     else if(!e.querySelector('.history').textContent.includes('売買なし'))throw Error('無取引');
     markers+=ms.length;accounts++;
    }
   }
  }
 }
 for(const session of D.sessions){change(document.getElementById('indexed-session'),session);const svg=document.querySelector('#indexed-chart svg');if(!svg||svg.querySelectorAll('.index-line').length!==2||/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('二市場線');indexed++;}
 for(let i=0;i<D.methods.length;i++){const e=document.getElementById(`method-${i}`);e.querySelector('[data-symbol="TOPIX"]').click();change(e.querySelector('.period-select'),'全29');change(e.querySelector('.variant-select'),'J');change(e.querySelector('.session-select'),D.sessions.at(-1));}
 if(getComputedStyle(document.documentElement).colorScheme!=='dark')throw Error('暗色');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,照合表数:tables,保存場表示数:accounts,金額照合数:numbers,売買点数:markers,二市場比較図数:indexed,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
