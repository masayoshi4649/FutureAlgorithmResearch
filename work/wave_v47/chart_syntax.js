
const data=JSON.parse(document.getElementById('chart-data').textContent),select=document.getElementById('method'),canvas=document.getElementById('chart');
const names={1:'初期損切り',2:'追跡返済',7:'部分利確',8:'360分返済',9:'場内返済',20:'初回新規',30:'減量',31:'復元',32:'実損失条件返済'};
const nf=new Intl.NumberFormat('ja-JP');let active=0,scale={};
/**
 * 機能: 原本の秒時刻を日本時間で表示する。
 * @param {number} value - 秒時刻。
 * @returns {string} 時分秒。
 */
function clock(value){return new Date(value*1000).toLocaleTimeString('ja-JP',{timeZone:'Asia/Tokyo',hour12:false});}
/**
 * 機能: 内蔵注文表と会計値から一画面を描く。
 * @returns {undefined} 返り値なし。
 */
function draw(){
 const d=data[active],ratio=devicePixelRatio||1,w=canvas.clientWidth,h=760;
 canvas.width=w*ratio;canvas.height=h*ratio;const c=canvas.getContext('2d');c.scale(ratio,ratio);c.fillStyle='#0f1b2b';c.fillRect(0,0,w,h);
 const left=75,right=w-25,x=t=>left+(t-d.start)/(d.end-d.start)*(right-left);
 const allPrices=d.candles.flatMap(v=>v.slice(1)).concat(d.orders.map(v=>v[6]));let lo=Math.min(...allPrices),hi=Math.max(...allPrices);const pad=(hi-lo)*.06||1;lo-=pad;hi+=pad;
 const y=p=>410-(p-lo)/(hi-lo)*360;scale={left,right,start:d.start,end:d.end};
 c.font='12px Meiryo';c.fillStyle='#bed0e5';c.fillText('先物価格',left,25);
 for(let j=0;j<=5;j++){let yy=50+j*72,p=hi-(hi-lo)*j/5;c.strokeStyle='#29405b';c.beginPath();c.moveTo(left,yy);c.lineTo(right,yy);c.stroke();c.fillStyle='#a9bdd5';c.fillText(nf.format(Math.round(p*10)/10),2,yy+4);}
 for(const v of d.candles){let xx=x(v[0]+150),col=v[4]>=v[1]?'#69d6b0':'#ff8f9e';c.strokeStyle=col;c.fillStyle=col;c.beginPath();c.moveTo(xx,y(v[2]));c.lineTo(xx,y(v[3]));c.stroke();let bw=Math.max(2,(right-left)*220/(d.end-d.start));c.fillRect(xx-bw/2,Math.min(y(v[1]),y(v[4])),bw,Math.max(1,Math.abs(y(v[1])-y(v[4])));}
 for(const o of d.orders){let xx=x(o[0]),yy=y(o[6]),reason=o[7],side=o[4];c.strokeStyle=c.fillStyle=reason===30?'#ffa866':reason===31?'#cdadff':o[8]===1?(side===1?'#71caff':'#ff9cd0'):'#f8dc83';c.lineWidth=1.7;c.beginPath();
  if(reason===20){let s=side===1?-1:1;c.moveTo(xx,yy+s*7);c.lineTo(xx-5,yy-s*4);c.lineTo(xx+5,yy-s*4);c.closePath();c.fill();}
  else if(reason===30){c.strokeRect(xx-4,yy-4,8,8);}
  else if(reason===31){c.moveTo(xx,yy-6);c.lineTo(xx+5,yy);c.lineTo(xx,yy+6);c.lineTo(xx-5,yy);c.closePath();c.stroke();}
  else{c.moveTo(xx-4,yy-4);c.lineTo(xx+4,yy+4);c.moveTo(xx-4,yy+4);c.lineTo(xx+4,yy-4);c.stroke();}
 }
 // ----------------------------------------
 // 価格図と別の目盛で同時保有量・実現と含みの合計を表示する。
 c.lineWidth=1;c.fillStyle='#bed0e5';c.fillText('同時保有枚数（買い 青・売り 桃）',left,450);
 for(const [col,index] of [['#71caff',2],['#ff9cd0',3]]){c.strokeStyle=col;c.beginPath();let prev=null;d.tracking.forEach((v,i)=>{let xx=x(v[0]),yy=540-v[index]/d.cap*70;if(i===0)c.moveTo(xx,yy);else{c.lineTo(xx,prev);c.lineTo(xx,yy);}prev=yy;});c.stroke();}
 c.fillStyle='#a9bdd5';c.fillText(String(d.cap),35,476);c.fillText('0',35,544);
 const es=d.tracking.map(v=>v[1]);let emin=Math.min(0,...es),emax=Math.max(0,...es);let span=emax-emin||1,ey=v=>705-(v-emin)/span*120;
 c.fillStyle='#bed0e5';c.fillText('時価損益（円）',left,570);c.strokeStyle='#526782';c.beginPath();c.moveTo(left,ey(0));c.lineTo(right,ey(0));c.stroke();c.strokeStyle='#8fcaff';c.beginPath();d.tracking.forEach((v,i)=>{if(i===0)c.moveTo(x(v[0]),ey(v[1]));else c.lineTo(x(v[0]),ey(v[1]));});c.stroke();c.fillStyle='#a9bdd5';c.fillText(nf.format(emax),0,590);c.fillText(nf.format(emin),0,708);
 const cut=Date.parse('2026-09-29T21:00:00+09:00')/1000;c.strokeStyle='#b99acb';c.setLineDash([3,5]);c.beginPath();c.moveTo(x(cut),35);c.lineTo(x(cut),710);c.stroke();c.setLineDash([]);
 for(let t=d.start;t<=d.end;t+=7200){c.fillStyle='#bacce1';c.fillText(clock(t).slice(0,5),x(t)-16,739);}
 const t=d.totals;document.getElementById('summary').textContent=`${d.symbol==='TOPIX'?'TOPIXミニ':'NK225マイクロ'}｜利益 ${nf.format(t.gross_profit_yen)}円 ／ 損失 ${nf.format(t.gross_loss_yen)}円 ／ 収支 ${nf.format(t.net_yen)}円｜勝ち ${t.profit_units}枚・負け ${t.loss_units}枚`;
 document.getElementById('orders').innerHTML=d.orders.map(o=>`<tr><td>${clock(o[0])}</td><td>${names[o[7]]||o[7]}</td><td>${o[4]===1?'買い':'売り'}</td><td>${o[5]}</td><td>${nf.format(o[6])}</td><td>${o[1]}</td><td>${o[2]}</td></tr>`).join('');
}
data.forEach((d,i)=>{const o=document.createElement('option');o.value=i;o.textContent=d.name+' / '+d.symbol;select.append(o);});active=data.findIndex(d=>d.id==='G150_F50_N1__V000'&&d.symbol==='TOPIX');select.value=active;
select.addEventListener('change',()=>{active=Number(select.value);draw();});window.addEventListener('resize',draw);
canvas.addEventListener('mousemove',e=>{const r=canvas.getBoundingClientRect(),t=scale.start+(e.clientX-r.left-scale.left)/(scale.right-scale.left)*(scale.end-scale.start);let orders=data[active].orders.filter(o=>Math.abs(o[0]-t)<(scale.end-scale.start)*12/(scale.right-scale.left));document.getElementById('hover').textContent=orders.length?orders.map(o=>`${clock(o[0])} ${names[o[7]]} ${o[5]}枚 @${nf.format(o[6])}`).join(' ／ '):clock(t)+'：近い注文なし';});draw();
