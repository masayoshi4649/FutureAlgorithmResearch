
const DATA=JSON.parse(document.getElementById('payload').textContent);const $=id=>document.getElementById(id);const PLOT={points:[],selected:-1,selectedKey:'',bounds:null};
/**
 * 機能: HTMLへ埋め込む文字列の特殊文字をエスケープする。
 * @param {unknown} value - 表示する値。
 * @returns {string} 安全なHTML文字列。
 */
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/**
 * 機能: 円を符号付き万円に整形する。
 * @param {number|null} value - 円。
 * @returns {string} 万円表記。
 */
function yen(value){return value==null?'—':`${value>0?'+':''}${(value/10000).toLocaleString('ja-JP',{minimumFractionDigits:1,maximumFractionDigits:1})}万円`;}
/**
 * 機能: Unix秒を日本時間で表示する。
 * @param {number} value - Unix秒。
 * @param {boolean} full - 日付と秒を含めるか。
 * @returns {string} 日本時間の文字列。
 */
function stamp(value,full=false){return new Date(value*1000).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',...(full?{month:'2-digit',day:'2-digit',second:'2-digit'}:{}),hour:'2-digit',minute:'2-digit'});}
/**
 * 機能: 列名に応じて表の値を整形する。
 * @param {string} key - 列名。
 * @param {unknown} value - 値。
 * @returns {string} 表示用文字列。
 */
function cell(key,value){if(value==null)return '—';if(typeof value==='number'){if(key.endsWith('円'))return yen(value);return value.toLocaleString('ja-JP',{maximumFractionDigits:3});}if(typeof value==='object')return esc(JSON.stringify(value));return esc(value);}
/**
 * 機能: 辞書配列をスクロール可能な表へ変換する。
 * @param {Array<object>} rows - 表示行。
 * @param {Array<string>|null} columns - 表示する列。
 * @returns {string} 表のHTML。
 */
function table(rows,columns=null){if(!rows?.length)return '<p class="muted">該当する記録はありません。</p>';const keys=columns||Object.keys(rows[0]);return `<div class="scroll"><table><thead><tr>${keys.map(k=>`<th>${esc(k)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${keys.map(k=>`<td class="${typeof row[k]==='number'&&k.includes('収支')?(row[k]<0?'negative':'positive'):''}">${cell(k,row[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
/**
 * 機能: 金額カードを作る。
 * @param {string} title - タイトル。
 * @param {string} value - 主な値。
 * @param {string} note - 補足。
 * @returns {string} カードHTML。
 */
function card(title,value,note=''){return `<div class="card"><span>${esc(title)}</span><strong>${esc(value)}</strong><span>${esc(note)}</span></div>`;}
/**
 * 機能: 結果の本文と比較表を描画する。
 * @returns {undefined} 返り値はない。
 */
function renderText(){const primary=DATA.primary||{};$('conclusions').innerHTML=`<ul class="result-list">${(DATA.conclusions||[]).map(s=>`<li>${esc(s)}</li>`).join('')}</ul>`;$('qualification').textContent=DATA.qualification||'候補数に対して独立したセッションが少なく、再現性のある法則を確認できたとはまだ判断しません。';$('scope').innerHTML=(DATA.scope||[]).map(s=>`<p>${esc(s)}</p>`).join('');$('primary-table').innerHTML=`<h3>${esc(primary.label||'時系列で選んだ条件の評価')}</h3>${table(primary.rows||[],primary.columns||null)}`;$('cards').innerHTML=(DATA.cards||[]).map(c=>card(c.title,c.value,c.note)).join('');$('comparisons').innerHTML=Object.entries(DATA.comparisons||{}).map(([name,group])=>`<h3>${esc(name)}</h3>${group.note?`<p class="muted">${esc(group.note)}</p>`:''}${table(Array.isArray(group)?group:group.rows,group.columns||null)}`).join('');$('diagnostics').innerHTML=(DATA.diagnostic_notes||[]).map(s=>`<p>${esc(s)}</p>`).join('')+Object.entries(DATA.diagnostics||{}).map(([name,rows])=>`<details><summary>${esc(name)}</summary>${table(Array.isArray(rows)?rows:[rows])}</details>`).join('');$('audit').innerHTML=(DATA.audit_notes||[]).map(s=>`<p>${esc(s)}</p>`).join('');}
/**
 * 機能: 選択中の条件と売買を取得する。
 * @returns {{method:object,trades:Array<object>,candles:Array<Array<number>>,key:string}} 表示対象。
 */
function current(){const method=DATA.methods.find(m=>m.id===$('method').value)||DATA.methods[0];const key=`${$('symbol').value}|${$('session').value}`;return {method,key,trades:(DATA.chart.trades||[]).filter(t=>t.method===method.id&&t.symbol===$('symbol').value&&t.session===$('session').value),candles:DATA.chart.candles[key]||[]};}
/**
 * 機能: 設定値を入口・出口の説明へ変換する。
 * @param {object} method - 売買条件。
 * @returns {string} 日本語の条件説明HTML。
 */
function rules(method){const config=method.config||method;const lines=method.rules||[];if(!lines.length){lines.push(`入口：${config.signal_name||config.family}。${config.entry_name||''}。`);lines.push(`出口：${config.exit_name||''}。初期損切り${config.initial_stop_atr??2}ATR、通常追跡${config.trail_atr??2}ATR。`);lines.push(`時間帯：${config.time_name||'変更なし'}。`);}return `<p><span class="badge">${esc(method.id)}</span>${esc(method.label||method.chart_label||method.signal_name||'')}</p>${lines.map(s=>`<p>${esc(s)}</p>`).join('')}`;}
/**
 * 機能: 選択条件の損益カード・売買表を再描画する。
 * @returns {undefined} 返り値はない。
 */
function renderSelection(){const {method,trades}=current();$('method-rule').innerHTML=rules(method);const closed=trades.filter(t=>t.closed),opened=trades.filter(t=>!t.closed),profit=closed.reduce((s,t)=>s+Math.max(0,t.net),0),loss=-closed.reduce((s,t)=>s+Math.min(0,t.net),0);$('session-cards').innerHTML=card('確定収支',yen(profit-loss),`利益 ${yen(profit)} ／ 損失 ${yen(loss)}`)+card('勝ち／返済済',`${closed.filter(t=>t.net>0).length}／${closed.length}`,`未返済 ${opened.length}件`)+card('未返済の評価損益',yen(opened.reduce((s,t)=>s+t.net,0)),'確定収支には含めない')+card('最大順行からの返却',yen(closed.reduce((s,t)=>s+t.giveback,0)),'費用控除前・各返済済取引の合計');const rows=trades.map((t,i)=>`<tr data-trade="${i}" class="${PLOT.selected===i?'selected-trade':''}"><td>${i+1}</td><td>${t.side>0?'ロング':'ショート'}</td><td>${stamp(t.signal,true)}</td><td>${stamp(t.entry,true)}</td><td>${t.ep.toLocaleString()}</td><td>${stamp(t.exit,true)}</td><td>${t.xp.toLocaleString()}</td><td class="${t.net<0?'negative':'positive'}">${yen(t.net)}</td><td>${yen(t.mfe)}</td><td>${yen(t.giveback)}</td><td>${t.atr.toFixed(2)}</td><td>${esc(t.reason)}</td></tr>`);$('trade-table').innerHTML=rows.length?`<div class="scroll"><table><thead><tr>${['番号','方向','検知','新規','新規価格','返済／評価','返済／評価価格','確定／評価損益','最大順行','利益返却','固定ATR','返済理由'].map(k=>`<th>${k}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`:'<p class="muted">この条件では当該セッションに約定がありません。信号があっても、期限・反発幅・保有中などの条件で約定しない場合があります。</p>';document.querySelectorAll('[data-trade]').forEach(row=>row.addEventListener('click',()=>{PLOT.selected=Number(row.dataset.trade);renderSelection();}));$('method-sessions').innerHTML=table((DATA.session_rows||[]).filter(r=>r.方式===method.id),DATA.session_columns||null);draw();}
/**
 * 機能: 暗色キャンバスへ確定５分足、米国開始窓、実約定位置を描く。
 * @returns {undefined} 返り値はない。
 */
function draw(){const {trades,candles}=current();const canvas=$('chart'),dpr=window.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;canvas.width=w*dpr;canvas.height=h*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.fillStyle='#0b1220';ctx.fillRect(0,0,w,h);PLOT.points=[];if(!candles.length){ctx.fillStyle='#b8c9df';ctx.fillText('表示用の確定５分足がありません',24,40);return;}let t0=candles[0][0]-150,t1=candles.at(-1)[0]+450;const session=$('session').value,night=session.endsWith('Night'),midnight=Date.parse(session.slice(0,10)+'T00:00:00+09:00')/1000,us0=midnight+22*3600+15*60,us1=midnight+23*3600;if($('range').value==='us'&&night){t0=Math.max(t0,us0-45*60);t1=Math.min(t1,us1+60*60);}const visible=candles.filter(c=>c[0]+300>=t0&&c[0]<=t1);let low=Math.min(...visible.map(c=>c[3])),high=Math.max(...visible.map(c=>c[2]));for(const t of trades){if(t.entry>=t0&&t.entry<=t1){low=Math.min(low,t.ep);high=Math.max(high,t.ep);}if(t.exit>=t0&&t.exit<=t1){low=Math.min(low,t.xp);high=Math.max(high,t.xp);}}const pad=Math.max((high-low)*.10,$('symbol').value==='NK225'?30:1);low-=pad;high+=pad;const L=14,R=78,T=26,B=43,W=w-L-R,H=h-T-B,x=t=>L+(t-t0)/(t1-t0)*W,y=p=>T+(high-p)/(high-low)*H;PLOT.bounds={t0,t1,low,high};if(night&&us1>=t0&&us0<=t1){ctx.fillStyle='#9683ff1f';ctx.fillRect(x(Math.max(t0,us0)),T,x(Math.min(t1,us1))-x(Math.max(t0,us0)),H);ctx.fillStyle='#b6a7ff';ctx.font='11px sans-serif';ctx.fillText('米国開始前後',Math.max(L+4,x(us0)+5),T+15);}ctx.font='11px sans-serif';for(let i=0;i<=5;i++){const price=low+(high-low)*i/5,py=y(price);ctx.strokeStyle='#23324a';ctx.beginPath();ctx.moveTo(L,py);ctx.lineTo(w-R,py);ctx.stroke();ctx.fillStyle='#afc0d8';ctx.fillText(price.toLocaleString('ja-JP',{maximumFractionDigits:$('symbol').value==='NK225'?0:1}),w-R+9,py+4);}for(let i=0;i<=6;i++){const t=t0+(t1-t0)*i/6,px=x(t);ctx.fillStyle='#99aecb';ctx.fillText(stamp(t),Math.max(4,Math.min(w-52,px-17)),h-17);}const bw=Math.max(2,Math.min(12,W/(t1-t0)*300*.65));for(const c of visible){const px=x(c[0]+150);ctx.strokeStyle=ctx.fillStyle=c[4]>=c[1]?'#57e4b0':'#ff8c99';ctx.beginPath();ctx.moveTo(px,y(c[2]));ctx.lineTo(px,y(c[3]));ctx.stroke();ctx.fillRect(px-bw/2,Math.min(y(c[1]),y(c[4])),bw,Math.max(1.5,Math.abs(y(c[1])-y(c[4]))));PLOT.points.push({x:px,y:y(c[4]),label:`５分足 ${stamp(c[0],true)}<br>始値 ${c[1]} ／ 高値 ${c[2]}<br>安値 ${c[3]} ／ 終値 ${c[4]}`});}ctx.save();ctx.beginPath();ctx.rect(L,T,W,H);ctx.clip();trades.forEach((tr,i)=>{const active=PLOT.selected===i,color=tr.side>0?'#57e4b0':'#ff8c99';ctx.lineWidth=active?2.5:1.3;ctx.globalAlpha=PLOT.selected>=0&&!active?.35:1;ctx.strokeStyle=color;ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(x(tr.entry),y(tr.ep));ctx.lineTo(x(tr.exit),y(tr.xp));ctx.stroke();ctx.setLineDash([]);if(tr.signal>=t0&&tr.signal<=t1){ctx.strokeStyle='#ffd375';ctx.beginPath();ctx.arc(x(tr.signal),y(tr.sp),active?6:4,0,2*Math.PI);ctx.stroke();PLOT.points.push({x:x(tr.signal),y:y(tr.sp),label:`#${i+1} 転換検知 ${stamp(tr.signal,true)}<br>条件設定 ${stamp(tr.condition,true)}`});}if(tr.entry>=t0&&tr.entry<=t1){const px=x(tr.entry),py=y(tr.ep),s=active?9:7;ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(px,py);ctx.lineTo(px-s,py+tr.side*s*1.7);ctx.lineTo(px+s,py+tr.side*s*1.7);ctx.closePath();ctx.fill();ctx.fillStyle='#edf3ff';ctx.font=active?'bold 13px sans-serif':'11px sans-serif';ctx.fillText(String(i+1),px+9,py+tr.side*13);PLOT.points.push({x:px,y:py,label:`#${i+1} ${tr.side>0?'買い':'売り'} ${stamp(tr.entry,true)}<br>価格 ${tr.ep} ／ ATR ${tr.atr.toFixed(2)}`});}if(tr.exit>=t0&&tr.exit<=t1){const px=x(tr.exit),py=y(tr.xp),s=active?7:5;ctx.strokeStyle=tr.closed?'#f2f6ff':'#a9b8d0';ctx.beginPath();if(tr.closed){ctx.moveTo(px-s,py-s);ctx.lineTo(px+s,py+s);ctx.moveTo(px-s,py+s);ctx.lineTo(px+s,py-s);}else{ctx.moveTo(px,py-s);ctx.lineTo(px+s,py);ctx.lineTo(px,py+s);ctx.lineTo(px-s,py);ctx.closePath();}ctx.stroke();PLOT.points.push({x:px,y:py,label:`#${i+1} ${tr.closed?'返済':'未返済の評価'} ${stamp(tr.exit,true)}<br>価格 ${tr.xp} ／ ${yen(tr.net)}<br>${esc(tr.reason)}`});}ctx.globalAlpha=1;});ctx.restore();}
/**
 * 機能: マウスに近いローソクまたは売買の説明を表示する。
 * @param {MouseEvent} event - マウス位置。
 * @returns {undefined} 返り値はない。
 */
function tooltip(event){const rect=$('chart').getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top;let nearest=null,distance=24;for(const point of PLOT.points){const d=Math.hypot(x-point.x,y-point.y);if(d<distance){nearest=point;distance=d;}}const tip=$('tooltip');if(!nearest){tip.style.display='none';return;}tip.innerHTML=nearest.label;tip.style.display='block';tip.style.left=Math.min(rect.width-340,Math.max(4,x+15))+'px';tip.style.top=Math.max(5,y-65)+'px';}
/**
 * 機能: 選択肢と操作イベントを初期化する。
 * @returns {undefined} 返り値はない。
 */
function initialize(){renderText();DATA.methods=DATA.methods||[];if(!DATA.methods.length)return;$('method').innerHTML=DATA.methods.map(m=>`<option value="${esc(m.id)}">${esc(m.label||m.chart_label||m.id)}</option>`).join('');const sessions=[...new Set(Object.keys(DATA.chart.candles||{}).map(k=>k.split('|')[1]))].sort();$('session').innerHTML=sessions.map(s=>`<option value="${esc(s)}">${esc(s.replace('_Day',' デイ').replace('_Night',' ナイト'))}</option>`).join('');if(DATA.default_method)$('method').value=DATA.default_method;if(DATA.default_session)$('session').value=DATA.default_session;for(const name of ['method','symbol','session','range'])$(name).addEventListener('change',()=>{PLOT.selected=-1;renderSelection();});$('reset').addEventListener('click',()=>{PLOT.selected=-1;renderSelection();});$('chart').addEventListener('mousemove',tooltip);$('chart').addEventListener('mouseleave',()=>{$('tooltip').style.display='none';});window.addEventListener('resize',draw);renderSelection();}
initialize();
