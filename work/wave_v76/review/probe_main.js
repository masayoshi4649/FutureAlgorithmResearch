/**
 * 機能: 元会計から渡された全管理対照の表示・操作・売買座標を独立に検査する。
 * @returns {object} 検査件数と表示品質。
 */
function independentVerify(){
 const {D,STATE}=window.reportTest;
 let tables=0,accounts=0,markers=0,numbers=0;
 const number=cell=>Number(cell.textContent.replace(/[,\s円＋+]/g,'').replace('−','-'));
 const near=(a,b,label)=>{if(!Number.isFinite(a)||Math.abs(a-b)>1e-6)throw Error(label+':'+a+'/'+b);};
 const percent=v=>v==null?'—':(v*100).toFixed(1)+'%';
 const change=(e,value)=>{e.value=value;e.dispatchEvent(new Event('change'));};
 const row=(tr,a)=>{
  for(const [i,k] of [[1,'profit'],[2,'loss'],[3,'net'],[5,'trades'],[9,'fees']]){near(number(tr.cells[i]),a[k],k);numbers++;}
  near(a.profit-a.loss,a.net,'利益−損失');
  const share=a.profit+a.loss?a.loss/(a.profit+a.loss):null,payoff=a.wins&&a.losses?(a.profit/a.wins)/(a.loss/a.losses):null;
  if(tr.cells[4].textContent!==percent(share)||tr.cells[7].textContent!==percent(a.trades?a.wins/a.trades:null))throw Error('比率');
  if(a.trades)near(number(tr.cells[6]),Math.sign(a.net)*Math.round(Math.abs(a.net/a.trades)),'平均一取引');else if(tr.cells[6].textContent!=='—')throw Error('無取引平均');
  if(tr.cells[8].textContent!==(payoff==null?'—':payoff.toFixed(2)))throw Error('平均勝負比');
 };
 const table=(box,values)=>{const trs=box.querySelector('tbody').rows;if(trs.length!==values.length)throw Error('表件数');values.forEach((a,i)=>row(trs[i],a));tables++;};
 if(D.methods.length!==3||D.families.length!==6||D.sessions.length!==29)throw Error('入力範囲');
 for(const symbol of ['TOPIX','NK225'])for(const period of ['前16','後13','全29']){
  change(document.getElementById('comparison-symbol'),symbol);change(document.getElementById('comparison-period'),period);
  table(document.getElementById('design-comparison'),D.comparisons.map(x=>x.periods[period][symbol]));
 }
 for(const [i,f] of [...D.families,D.benchmark].entries()){
  if(i<6){const tr=document.querySelector(`.family-table [data-family="${f.family}"]`);near(number(tr.cells[5]),f.periods.全29.TOPIX.net,'機構TOP');near(number(tr.cells[6]),f.periods.全29.NK225.net,'機構NK');if(tr.cells[4].textContent!==(f.eligible?'充足':'件数不足'))throw Error('件数不足');}
  change(document.getElementById('family-sensitivity'),String(i));
  for(const s of ['TOPIX','NK225'])for(const p of ['前16','後13','全29']){change(document.getElementById('family-symbol'),s);change(document.getElementById('family-period'),p);table(document.getElementById('family-delay-table'),f.sensitivity.map(x=>x.periods[p][s]));}
 }
 for(const [i,m] of D.methods.entries()){
  const e=document.getElementById(`method-${i}`),insurance=m.controls.find(x=>x.config.manage_mode===0);
  for(const symbol of ['TOPIX','NK225']){
   e.querySelector(`[data-symbol="${symbol}"]`).click();if(STATE.get(m.id).symbol!==symbol)throw Error('銘柄操作');
   for(const period of ['前16','後13','全29']){
    change(e.querySelector('.period-select'),period);
    table(e.querySelector('.comparison'),[m.periods[period][symbol],insurance.periods[period][symbol],D.benchmark.periods[period][symbol]]);
    table(e.querySelector('.management-comparison'),m.controls.map(x=>x.periods[period][symbol]));
    table(e.querySelector('.delay-table'),m.sensitivity.map(x=>x.periods[period][symbol]));
    table(e.querySelector('.exit-reasons'),[...Object.values(m.exitReasons[period][symbol]),m.flipPeriods[period][symbol]]);
    const a=m.periods[period][symbol],tr=e.querySelector('.detail-table tbody').rows[0];
    if(tr.cells[0].textContent!==`${a.winning_lots}／${a.losing_lots}`)throw Error('勝負枚数');
    for(const [col,k] of [[1,'max_trade_loss'],[2,'drawdown'],[3,'without_best_session'],[4,'spread_drag'],[6,'flip_count']])near(number(tr.cells[col]),a[k],k);
   }
   const rs=D.sessions.map(s=>m.rows.find(r=>r.session===s&&r.symbol===symbol)),total=m.periods.全29[symbol];
   table(e.querySelector('.session-table'),[...rs,total]);table(e.querySelector('.week-table'),[...m.weeks[symbol],total]);
   for(const k of ['profit','loss','net','fees','trades','winning_lots','losing_lots']){near(rs.reduce((a,r)=>a+r[k],0),total[k],'全場和');near(m.weeks[symbol].reduce((a,r)=>a+r[k],0),total[k],'週和');}
   for(const source of [...m.controls,D.benchmark]){
    change(e.querySelector('.variant-select'),source.id);
    for(const [j,session] of D.sessions.entries()){
     if(j%2===0)e.querySelector(`.session-link[data-session="${session}"]`).click();else change(e.querySelector('.session-select'),session);
     if(STATE.get(m.id).session!==session||STATE.get(m.id).variant!==source.id)throw Error('図切替');
     const key=session+'|'+symbol,orders=source.orders[key],bars=D.bars[key],svg=e.querySelector('.chart svg'),a=source.rows.find(r=>r.session===session&&r.symbol===symbol);
     if(!svg||/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('図の有限性');
     const ms=svg.querySelectorAll('.order-marker');if(ms.length!==orders.length||orders.length!==2*a.trades)throw Error('売買点数');
     const left=Math.min(...bars.map(b=>b[0]),...orders.map(o=>o[9])),right=Math.max(...bars.map(b=>b[0]+300),...orders.map(o=>o[9]));
     const values=bars.flatMap(b=>[b[2],b[3]]).concat(orders.map(o=>o[5])),lo=Math.min(...values),hi=Math.max(...values),pad=Math.max((hi-lo)*.08,symbol==='TOPIX'?.5:5);
     const x=t=>67+(t-left)/(right-left)*1097,y=p=>18+(hi+pad-p)/(hi-lo+2*pad)*329;
     orders.forEach((o,k)=>{if(Number(ms[k].dataset.reason)!==o[6]||Number(ms[k].dataset.new)!==o[7]||o[0]<=o[1])throw Error('注文種別/因果順');const shape=ms[k].querySelector(o[7]?'circle':'path');if(!shape)throw Error('形状');if(o[7]){near(+shape.getAttribute('cx'),x(o[9]),'新規x');near(+shape.getAttribute('cy'),y(o[5]),'新規y');}else{const xy=shape.getAttribute('d').match(/[-+]?\d*\.?\d+(?:e[-+]?\d+)?/gi).map(Number);near(xy[0],x(o[9]),'返済x');near(xy[1]+6,y(o[5]),'返済y');}});
     const trs=e.querySelector('.history-table tbody').rows;if(trs.length!==orders.length)throw Error('履歴件数');orders.forEach((o,k)=>{near(number(trs[k].cells[4]),o[4],'枚数');near(number(trs[k].cells[5]),o[5],'値');if(o[7]===0)near(number(trs[k].cells[7]),source.orderNet[key][k],'決済損益');});
     accounts++;markers+=orders.length;
    }
   }
  }
  e.querySelector('[data-symbol="TOPIX"]').click();change(e.querySelector('.period-select'),'全29');change(e.querySelector('.variant-select'),m.id);change(e.querySelector('.session-select'),D.sessions.at(-1));
 }
 window.scrollTo(0,0);
 if(getComputedStyle(document.documentElement).colorScheme!=='dark'||document.documentElement.scrollWidth>innerWidth+2)throw Error('暗色/横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,照合表数:tables,保存場表示数:accounts,金額照合数:numbers,売買点数:markers,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
