
const DATA=JSON.parse(document.getElementById('data').textContent);
const $=id=>document.getElementById(id);
let selectedTrade=-1,windowRange=null,visibleTrades=[],chartGeometry=null;
const COLORS={bg:'#0b1422',line:'#293b54',text:'#b3c4da',up:'#5adeb3',down:'#ffb36b',exit:'#83bfff',open:'#c1a2ff'};

/**
 * 円の数値を万円で表示する。
 * @param {number} value - 円の値。
 * @returns {string} 万円の文字列。
 */
function yen(value){return (value>0?'＋':value<0?'−':'')+(Math.abs(value)/10000).toLocaleString('ja-JP',{maximumFractionDigits:2})+'万円';}
/**
 * 日本時間の時刻を表示する。
 * @param {number} value - Unix秒。
 * @returns {string} 時分秒。
 */
function timeText(value){return new Date(value*1000).toLocaleTimeString('ja-JP',{timeZone:'Asia/Tokyo',hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});}
/**
 * 表示文字をHTMLへ安全に入れる。
 * @param {unknown} value - 表示対象。
 * @returns {string} エスケープした文字。
 */
function esc(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/**
 * 現在の選択に対応するデータキーを返す。
 * @returns {string} 方式・セッション・銘柄のキー。
 */
function key(){return [$('method').value,$('session').value,$('symbol').value].join('|');}
/**
 * 高密度画面に合わせてキャンバスを準備する。
 * @param {string} id - 対象ID。
 * @param {number} height - 描画高さ。
 * @returns {object} 文脈と表示サイズ。
 */
function context(id,height){const el=$(id),ratio=window.devicePixelRatio||1,w=el.clientWidth;el.width=w*ratio;el.height=height*ratio;el.style.height=height+'px';const ctx=el.getContext('2d');ctx.scale(ratio,ratio);ctx.fillStyle=COLORS.bg;ctx.fillRect(0,0,w,height);ctx.font='12px "Yu Gothic UI",sans-serif';return {ctx,w,h:height};}
/**
 * 値幅・時間の目盛線を描く。
 * @param {object} target - 文脈とサイズ。
 * @param {number[]} bounds - 最小最大価格・時刻。
 * @param {boolean} moneyMode - 金額の表示か。
 * @returns {object} 座標変換関数と範囲。
 */
function axes(target,bounds,moneyMode=false){const {ctx,w,h}=target,[lo,hi,start,end]=bounds,p={l:75,r:w-25,t:24,b:h-36};const X=t=>p.l+(t-start)/(end-start)*(p.r-p.l),Y=v=>p.b-(v-lo)/(hi-lo)*(p.b-p.t);ctx.lineWidth=1;for(let i=0;i<=5;i++){const v=lo+(hi-lo)*i/5,y=Y(v);ctx.strokeStyle=COLORS.line;ctx.beginPath();ctx.moveTo(p.l,y);ctx.lineTo(p.r,y);ctx.stroke();ctx.fillStyle=COLORS.text;ctx.textAlign='right';ctx.fillText(moneyMode?(v/10000).toFixed(1)+'万':v.toLocaleString('ja-JP',{maximumFractionDigits:1}),p.l-10,y+4);}for(let i=0;i<=6;i++){const t=start+(end-start)*i/6,x=X(t);ctx.strokeStyle=COLORS.line;ctx.beginPath();ctx.moveTo(x,p.t);ctx.lineTo(x,p.b);ctx.stroke();ctx.fillStyle=COLORS.text;ctx.textAlign='center';ctx.fillText(timeText(t).slice(0,5),x,h-12);}return {X,Y,p,start,end,lo,hi};}
/**
 * 三角または菱形で新規・末尾評価を示す。
 * @param {CanvasRenderingContext2D} ctx - 文脈。
 * @param {number} x - 横位置。
 * @param {number} y - 縦位置。
 * @param {number} side - 売買方向。
 * @param {boolean} diamond - 菱形か。
 * @returns {void} 返り値なし。
 */
function marker(ctx,x,y,side,diamond=false){ctx.beginPath();if(diamond){ctx.moveTo(x,y-6);ctx.lineTo(x+6,y);ctx.lineTo(x,y+6);ctx.lineTo(x-6,y);}else{ctx.moveTo(x,y-side*7);ctx.lineTo(x-6,y+side*5);ctx.lineTo(x+6,y+side*5);}ctx.closePath();ctx.fill();ctx.strokeStyle='#07101d';ctx.lineWidth=1.5;ctx.stroke();}
/**
 * 選択条件のローソク足・全脚・評価曲線を描く。
 * @returns {void} 返り値なし。
 */
function draw(){const session=$('session').value,symbol=$('symbol').value,bars=DATA.candles[session+'|'+symbol]||[];const surface=context('price',490);if(!bars.length){surface.ctx.fillStyle=COLORS.text;surface.ctx.fillText('足がありません',25,35);return;}let start=windowRange?windowRange[0]:bars[0][0]-180,end=windowRange?windowRange[1]:Math.max(bars[bars.length-1][0]+480,...visibleTrades.map(t=>t.exit+120),...(DATA.curves[key()]||[]).map(r=>r[0]+120));const shown=bars.filter(b=>b[0]+300>=start&&b[0]<=end);const prices=shown.flatMap(b=>[b[2],b[3]]);for(const t of visibleTrades){if(t.entry>=start&&t.entry<=end)prices.push(t.ep);if(t.exit>=start&&t.exit<=end)prices.push(t.xp);}let lo=Math.min(...prices),hi=Math.max(...prices),pad=Math.max((hi-lo)*.11,symbol==='NK225'?30:1.5);lo-=pad;hi+=pad;const g=axes(surface,[lo,hi,start,end]);chartGeometry={...g,bars,session,symbol};const {ctx}=surface;ctx.save();ctx.beginPath();ctx.rect(g.p.l,g.p.t,g.p.r-g.p.l,g.p.b-g.p.t);ctx.clip();const bw=Math.max(2,Math.min(13,(g.p.r-g.p.l)*250/(end-start)));for(const b of shown){const x=g.X(b[0]+150),color=b[4]>=b[1]?COLORS.up:COLORS.down;ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,g.Y(b[2]));ctx.lineTo(x,g.Y(b[3]));ctx.stroke();const top=Math.min(g.Y(b[1]),g.Y(b[4])),bh=Math.max(1.5,Math.abs(g.Y(b[1])-g.Y(b[4])));ctx.fillRect(x-bw/2,top,bw,bh);}visibleTrades.forEach((t,index)=>{if(t.exit<start||t.entry>end)return;const color=t.side>0?COLORS.up:COLORS.down;ctx.globalAlpha=selectedTrade<0||selectedTrade===index?.88:.3;ctx.strokeStyle=color;ctx.lineWidth=selectedTrade===index?2.5:1.2;ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(g.X(t.condition),g.Y(t.ep));ctx.lineTo(g.X(t.entry),g.Y(t.ep));ctx.stroke();ctx.setLineDash([]);ctx.beginPath();ctx.moveTo(g.X(t.entry),g.Y(t.ep));ctx.lineTo(g.X(t.exit),g.Y(t.xp));ctx.stroke();ctx.fillStyle=color;marker(ctx,g.X(t.entry),g.Y(t.ep),t.side);ctx.fillStyle=t.closed?COLORS.exit:COLORS.open;if(t.closed){ctx.beginPath();ctx.arc(g.X(t.exit),g.Y(t.xp),4.3,0,Math.PI*2);ctx.fill();}else marker(ctx,g.X(t.exit),g.Y(t.xp),0,true);});ctx.restore();ctx.globalAlpha=1;ctx.fillStyle=COLORS.text;ctx.textAlign='left';ctx.fillText('５分足 ／ 原本順の指定価格約定',80,16);if(DATA.boundary>=start&&DATA.boundary<=end){const bx=g.X(DATA.boundary);ctx.strokeStyle='#c1a2ff';ctx.setLineDash([5,5]);ctx.beginPath();ctx.moveTo(bx,g.p.t);ctx.lineTo(bx,g.p.b);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#c1a2ff';ctx.fillText('追加区間 00:53 →',Math.min(bx+8,g.p.r-145),g.p.t+16);}drawEquity(start,end);}
/**
 * 確定損益と全建玉評価を同じ軸で描く。
 * @param {number} start - 表示開始。
 * @param {number} end - 表示終了。
 * @returns {void} 返り値なし。
 */
function drawEquity(start,end){const target=context('equity',190),curve=(DATA.curves[key()]||[]).filter(r=>r[0]>=start-60&&r[0]<=end+60);if(!curve.length)return;let values=curve.flatMap(r=>[r[2],r[5]]),lo=Math.min(0,...values),hi=Math.max(0,...values),pad=Math.max((hi-lo)*.15,10000);const g=axes(target,[lo-pad,hi+pad,start,end],true),ctx=target.ctx;for(const [column,color] of [[5,'#71859f'],[2,COLORS.exit]]){ctx.beginPath();curve.forEach((r,i)=>{const x=g.X(r[0]),y=g.Y(r[column]);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.strokeStyle=color;ctx.lineWidth=column===2?2:1;ctx.stroke();}ctx.fillStyle=COLORS.text;ctx.textAlign='left';ctx.fillText('青：全建玉評価（含み込み）　灰：確定損益',80,16);}
/**
 * 選択状態から数値・全脚明細と図を更新する。
 * @returns {void} 返り値なし。
 */
function update(){selectedTrade=-1;windowRange=null;const method=$('method').value,symbol=$('symbol').value,session=$('session').value;visibleTrades=DATA.trades.filter(t=>t.method===method&&t.symbol===symbol&&t.session===session).sort((a,b)=>a.entry-b.entry||a.leg-b.leg);const summary=DATA.summaries[key()]||{},definition=DATA.methods[method];$('rule').textContent=definition?definition.label+' ／ '+definition.rules[0]:'';const stats=[['返済脚の利益',yen(summary.profit_yen||0)],['返済脚の損失',yen(summary.loss_yen||0)],['全建玉評価',yen(summary.net_yen||0)],['含み損益',yen(summary.open_yen||0)],['最大下落',yen(-(summary.max_drawdown_yen||0))],['返済脚／未返済脚',`${summary.closed_count||0}／${summary.open_count||0}`]];$('chart-summary').innerHTML=stats.map(([label,value])=>'<div><small>'+label+'</small><b>'+value+'</b></div>').join('');const rows=visibleTrades.map((t,i)=>'<tr class="trade-row" data-index="'+i+'"><td>'+`${t.cycle}–${t.leg}`+'</td><td class="'+(t.side>0?'green':'orange')+'">'+(t.side>0?'買い':'売り')+'</td><td>'+timeText(t.entry)+'</td><td>'+t.ep.toLocaleString('ja-JP')+'</td><td>'+timeText(t.exit)+'</td><td>'+t.xp.toLocaleString('ja-JP')+'</td><td class="'+(t.pnl>=0?'positive':'negative')+'">'+yen(t.pnl)+'</td><td>'+t.holding.toFixed(1)+'分</td><td>'+esc(t.reason)+'</td><td>'+t.atr.toFixed(2)+'</td></tr>').join('');$('trade-table').innerHTML='<table><thead><tr>'+['組–脚','方向','新規時刻','新規価格','返済/評価時刻','返済/評価価格','収支','保有','理由','固定ATR'].map(x=>'<th>'+x+'</th>').join('')+'</tr></thead><tbody>'+rows+'</tbody></table>';$('chart-note').textContent='表の行を選ぶとその建玉の前後へ拡大します。「セッション全体」で戻せます。全'+visibleTrades.length+'脚を表示。ラージ換算。'+(summary.open_count?'未返済の脚は紫の菱形で末尾評価を示します。':'この区間の建玉はすべて返済済みです。');draw();}
/**
 * 売買の行を選択して周辺へ表示を拡大する。
 * @param {number} index - 売買一覧の添字。
 * @returns {void} 返り値なし。
 */
function focusTrade(index){selectedTrade=index;const t=visibleTrades[index];windowRange=[Math.min(t.condition,t.entry)-900,t.exit+900];document.querySelectorAll('.trade-row').forEach(el=>el.classList.toggle('selected',+el.dataset.index===index));draw();$('price').scrollIntoView({behavior:'smooth',block:'center'});}
/**
 * ポインター近傍の足と売買を表示する。
 * @param {MouseEvent} event - 移動イベント。
 * @returns {void} 返り値なし。
 */
function hover(event){if(!chartGeometry)return;const rect=$('price').getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top,g=chartGeometry,tip=$('tooltip');if(x<g.p.l||x>g.p.r||y<g.p.t||y>g.p.b){tip.style.display='none';return;}const t=g.start+(x-g.p.l)/(g.p.r-g.p.l)*(g.end-g.start),bar=g.bars.reduce((a,b)=>Math.abs(b[0]+150-t)<Math.abs(a[0]+150-t)?b:a);let text=timeText(bar[0]).slice(0,5)+' ５分足<br>始 '+bar[1]+'　高 '+bar[2]+'<br>安 '+bar[3]+'　終 '+bar[4];const near=visibleTrades.filter(r=>Math.abs(g.X(r.entry)-x)<12||Math.abs(g.X(r.exit)-x)<12).slice(0,4);for(const r of near)text+='<br>'+`${r.cycle}–${r.leg} `+(r.side>0?'買い':'売り')+' '+timeText(r.entry)+' → '+timeText(r.exit)+' '+yen(r.pnl);tip.innerHTML=text;tip.style.display='block';tip.style.left=Math.max(6,Math.min(x+14,rect.width-355))+'px';tip.style.top=Math.max(8,Math.min(y+12,320))+'px';}

// ----------------------------------------
// 選択要素と描画イベントを初期化する。
$('method').innerHTML=Object.entries(DATA.methods).map(([id,value])=>'<option value="'+esc(id)+'">'+esc(id+' ／ '+value.label)+'</option>').join('');
$('session').innerHTML=Object.entries(DATA.sessions).map(([id,label])=>'<option value="'+id+'">'+label+'</option>').join('');
$('method').value=DATA.primary.NK225;$('session').value=Object.keys(DATA.sessions).at(-1);
for(const id of ['method','session'])$(id).addEventListener('change',update);
$('symbol').addEventListener('change',()=>{$('method').value=DATA.primary[$('symbol').value];update();});
$('primary').addEventListener('click',()=>{$('method').value=DATA.primary[$('symbol').value];update();});
if($('board-chart'))$('board-chart').addEventListener('click',()=>{$('symbol').value='NK225';$('method').value='P16_R1_E1_X5_U0';update();$('charts').scrollIntoView({behavior:'smooth',block:'start'});});
$('reset').addEventListener('click',()=>{selectedTrade=-1;windowRange=null;document.querySelectorAll('.trade-row').forEach(el=>el.classList.remove('selected'));draw();});
$('trade-table').addEventListener('click',event=>{const row=event.target.closest('.trade-row');if(row)focusTrade(+row.dataset.index);});
$('price').addEventListener('mousemove',hover);$('price').addEventListener('mouseleave',()=>{$('tooltip').style.display='none';});
window.addEventListener('resize',draw);update();
