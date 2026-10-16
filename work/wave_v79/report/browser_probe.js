/**
 * 機能: 全条件・全場の表示値と板の根拠をブラウザ上で独立照合する。
 * @returns {object} 検査件数、表示品質、通信制限の結果。
 */
function independentVerify(){
 const test=window.reportTest,data=test.data;
 const read=(cell)=>Number(cell.textContent.replaceAll(',','').replaceAll('−','-').replaceAll('円','').replaceAll('%','').trim());
 const assert=(value,message)=>{if(!value)throw Error(message);};
 const close=(cell,value,label,digits=0)=>{if(value==null){assert(cell.textContent.includes('未収録'),label+'欠測');return;}assert(Math.abs(read(cell)-value)<=.501*10**(-digits),label+': '+read(cell)+' / '+value);};
 let lossColors=0;
 const lossCheck=(cell,value)=>{close(cell,value,'損失絶対額');assert(!/[+＋−-]/.test(cell.textContent),'損失の符号');if(value>0){const span=cell.querySelector('.negative');assert(span&&!cell.querySelector('.positive'),'損失の赤色指定');assert(getComputedStyle(span).color==='rgb(255, 156, 156)','損失の実描画色');lossColors++;}};
 const stamp=value=>value.replace('T',' ').replace('+09:00','').replace('_Day',' デイ').replace('_Night',' ナイト');
 let sessions=0,sessionNumbers=0,scopes=0,scopeNumbers=0,quoteValues=0,orderValues=0,trades=0,svgPoints=0;
 assert(data.effects.length===18,'手法数');assert(data.sessions.length===30,'場数');
 const method=document.getElementById('method');
 for(const condition of data.effects){
  method.value=condition.id;method.dispatchEvent(new Event('change'));
  const rows=document.querySelectorAll('#session-table tbody tr');assert(rows.length===31,'30場＋合計');
  const result=data.results[condition.id];
  for(let i=0;i<30;i++){
   assert(rows[i].cells[0].textContent===stamp(data.sessions[i]),'場名');
   for(const [n,symbol] of ['TOPIX','NK225'].entries()){
    const a=result.rows.find(v=>v.session===data.sessions[i]&&v.symbol===symbol);
    assert(a.net===a.profit-a.loss,'保存会計');
    for(const [j,key] of ['profit','loss','net'].entries()){close(rows[i].cells[1+n*3+j],a[key],condition.id+'/'+symbol+'/'+key);sessionNumbers++;}
    lossCheck(rows[i].cells[2+n*3],a.loss);
    sessions++;
   }
  }
  assert(rows[30].cells[0].textContent==='合計','合計行');
  for(const [n,symbol] of ['TOPIX','NK225'].entries())for(const [j,key] of ['profit','loss','net'].entries()){
   const sum=result.rows.filter(v=>v.symbol===symbol).reduce((a,v)=>a+v[key],0);
   assert(sum===result.periods.全30[symbol][key],'合計の足算');close(rows[30].cells[1+n*3+j],sum,'合計');sessionNumbers++;
   if(key==='loss')lossCheck(rows[30].cells[1+n*3+j],sum);
  }
 }
 const scope=document.getElementById('scope');assert(scope.options.length===6,'範囲数');
 for(const option of scope.options){
  scope.value=option.value;scope.dispatchEvent(new Event('change'));
  const tables=document.querySelectorAll('#comparison table');assert(tables.length===2,'比較商品の数');
  for(const [n,symbol] of ['TOPIX','NK225'].entries()){
   const rows=tables[n].tBodies[0].rows;assert(rows.length===18,'比較手法数');
   for(const [i,effect] of data.effects.entries()){
    const a=effect.期間[option.value][symbol],row=rows[i];assert(row.cells[0].textContent===effect.id,'条件ID');
    for(const [j,key] of ['profit','loss','net','収支変化','利益変化','損失削減','trades'].entries()){close(row.cells[1+j],a[key],'比較'+key);scopeNumbers++;}
    close(row.cells[8],a.profit_share==null?null:a.profit_share*100,'金額利益割合',2);close(row.cells[9],a.drawdown,'最大時価下落');scopeNumbers+=2;scopes++;
    lossCheck(row.cells[2],a.loss);
   }
  }
 }
 const delays=document.querySelectorAll('#delays tbody tr');assert(delays.length===18,'遅延表数');
 let delayValues=0;
 for(const [i,effect] of data.effects.entries())for(const [n,symbol] of ['TOPIX','NK225'].entries())for(const [j,delay] of [1,5,15].entries()){
  close(delays[i].cells[1+n*3+j],effect.遅延[delay][symbol].net,'遅延収支');delayValues++;
 }
 assert(data.cases.length===6,'診断口座数');
 const rankRows=document.querySelectorAll('#rank-table tbody tr');assert(rankRows.length===6,'順位行数');
 data.cases.forEach((c,i)=>lossCheck(rankRows[i].cells[4],c.会計.損失円));
 for(const c of data.cases){
  const article=document.getElementById('case-'+c.ID);assert(article,'ケースDOM');
  const summary=article.querySelector(':scope > .table-wrap table').tBodies[0].rows;assert(summary.length===c.取引.length,'ケース取引一覧数');
  const total=c.取引.reduce((sum,t)=>sum+t.損益.収支円,0);assert(total===c.会計.収支円,'ケース収支の足算');
  for(const [i,t] of c.取引.entries()){
   close(summary[i].cells[4],t.損益.収支円,'取引一覧収支');
   const detail=document.querySelector('[data-trade="'+t.ID+'"]');assert(detail,'詳細DOM');
   detail.open=true;
   const tables=detail.querySelectorAll(':scope > .table-wrap > table');assert(tables.length===3,'入口・注文・比較の3表');
   for(const [j,symbol] of ['TOPIX','NK225'].entries()){
    const e=t.二市場[symbol].旧入口,b=e.参照,row=tables[0].tBodies[0].rows[j];
    assert(row.cells[0].textContent===symbol,'入口商品');assert(row.cells[1].textContent===stamp(b.時刻),'根拠時刻');
    for(const [column,value,digits] of [[2,b.bid,1],[3,b.買数量,0],[4,b.ask,1],[5,b.売数量,0],[6,e.窓15.中値変化bp,2],[7,e.窓300.中値変化bp,2],[8,b.原本表示行,0]]){close(row.cells[column],value,'入口板',digits);quoteValues++;}
   }
   const orderRows=tables[1].tBodies[0].rows;assert(orderRows.length===Object.keys(t.時点).length,'判断約定行数');
   for(const [j,[label,b]] of Object.entries(t.時点).entries()){
    const row=orderRows[j];assert(row.cells[0].textContent===label,'注文時点名');assert(row.cells[1].textContent===stamp(b.時刻),'注文時点時計');
    for(const [column,value,digits] of [[2,b.価格,1],[3,b.bid,1],[4,b.買数量,0],[5,b.ask,1],[6,b.売数量,0],[7,b.原本表示行,0]]){close(row.cells[column],value,'注文板',digits);orderValues++;}
   }
   const replay=data.replay[c.セッション+'|'+c.商品],compareRows=tables[2].tBodies[0].rows,ids=['E0_X0','E0_X1','E0_X2','E1_X0','E2_X0','E4_X0','E5_X0'];
   assert(compareRows.length===7,'同新規の再生比較数');
   for(const [j,id] of ids.entries()){
    const r=replay.変更[id].元新規の対応.find(v=>v.元組===t.組番号-1)?.再生,row=compareRows[j];
    if(r){assert(row.cells[1].textContent===stamp(r.返済判断),'再生判断時刻');close(row.cells[2],r.返済価格,'再生返済価格',1);close(row.cells[3],r.収支,'再生収支');close(row.cells[4],r.収支-t.損益.収支円,'再生差分');}
    else assert(row.cells[1].textContent==='同じ新規なし'&&row.cells[3].textContent==='—','見送りを0へ誤変換');
   }
   const svg=detail.querySelector('svg'),chart=data.charts[t.ID];assert(svg,'SVG存在');assert(svg.querySelector('path.path'),'評価損益線');assert(!/NaN|Infinity|undefined/.test(svg.outerHTML),'グラフ非数');
   assert(chart.points.length>0,'描画点');assert(chart.start<=chart.end,'描画時計');
   assert(chart.points.every(p=>Number.isFinite(p[0])&&Number.isFinite(p[1])),'曲線有限値');
   assert((svg.querySelector('path.path').getAttribute('d').match(/[ML]/g)||[]).length===chart.points.length,'保存点とSVG点の一致');
   const exit=replay.変更.E0_X1.元新規の対応.find(v=>v.元組===t.組番号-1)?.再生;
   const markerExpected=exit&&Date.parse(exit.返済約定)/1000<=chart.end;
   assert(svg.querySelectorAll('line.marker').length===(markerExpected?1:0),'X1返済マーカー');
   svgPoints+=chart.points.length;trades++;
  }
 }
 assert(trades===18&&document.querySelectorAll('svg.chart').length===18,'18取引18SVG');
 const details=[...document.querySelectorAll('details')],openStates=details.map(d=>d.open);
 details.forEach(d=>d.open=true);
 assert(document.documentElement.scrollWidth<=innerWidth+2,'全詳細展開時の文書横溢れ');
 details.forEach((d,i)=>d.open=openStates[i]);
 method.value='E0_X0';method.dispatchEvent(new Event('change'));scope.value='全30';scope.dispatchEvent(new Event('change'));
 for(const detail of document.querySelectorAll('.trade-detail')){const c=data.cases.find(c=>c.取引.some(t=>t.ID===detail.dataset.trade));detail.open=detail.dataset.trade===c.代表大負けID;}
 assert(document.documentElement.scrollWidth<=innerWidth+2,'文書横溢れ '+document.documentElement.scrollWidth+'/'+innerWidth);
 assert(!/undefined|NaN|Infinity|__DATA__/.test(document.body.innerText),'未定義表示');
 assert(!document.querySelector('script[src],link[href],img[src]'),'外部リソース参照');
 return {全合格:true,手法数:18,範囲数:6,場商品照合数:sessions,場と合計の金額照合数:sessionNumbers,範囲条件商品照合数:scopes,範囲表示数値照合数:scopeNumbers,遅延表示金額数:delayValues,損失赤色かつ符号なし照合数:lossColors,診断口座数:6,取引詳細数:trades,SVG数:18,描画点数:svgPoints,入口板数値照合数:quoteValues,注文時点数値照合数:orderValues,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor,外部通信:'複製HTMLのCSP connect-src none・拒否プロキシで禁止'};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
