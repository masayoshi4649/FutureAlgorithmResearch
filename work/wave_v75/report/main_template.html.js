
"use strict";
const D=JSON.parse(document.getElementById('report-data').textContent),STATE=new Map(),PERIODS=['前16','後13','全29'],NAMES={TOPIX:'TOPIXミニ10枚',NK225:'日経225マイクロ20枚'},REASONS={1:'初期損切り',2:'トレーリング',3:'時間上限返済',4:'場内全返済',10:'方向確認新規'},NUMBER=new Intl.NumberFormat('ja-JP',{maximumFractionDigits:0}),CLOCK=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}),SHORT=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
/**
 * 機能: 表示値を安全なHTML文字列にする。
 * @param {unknown} v - 表示値。
 * @returns {string} エスケープ済み文字列。
 */
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/**
 * 機能: 円金額に文脈別の色を付ける。
 * @param {number|null} v - 円金額。
 * @param {boolean} signed - 正符号を付けるか。
 * @param {string} context - 損失又は手数料。
 * @returns {string} 金額HTML。
 */
function money(v,signed=false,context=''){return v==null?'—':`<span class="money ${context==='loss'?'negative':context==='fee'?'muted':v>0?'positive':v<0?'negative':''}">${signed&&v>0?'+':''}${NUMBER.format(v)}円</span>`;}
/**
 * 機能: 比率を百分率として表示する。
 * @param {number|null} v - 比率。
 * @returns {string} 百分率又はダッシュ。
 */
function pct(v){return v==null?'—':(v*100).toFixed(1)+'%';}
/**
 * 機能: 保存場名を短く整形する。
 * @param {string} s - 保存場名。
 * @returns {string} 日本語の場名。
 */
function sessionName(s){return s.replace('_Day',' デイ').replace('_Night',' ナイト');}
/**
 * 機能: 同商品金額と一取引平均を共通表へ整形する。
 * @param {Array<object>} rows - ラベルと会計値。
 * @returns {string} 会計表HTML。
 */
function table(rows){return `<div class="table-wrap"><table class="primary-table"><thead><tr><th>対象</th><th>利益</th><th>損失</th><th>収支</th><th>損失割合</th><th>取引数</th><th>平均一取引</th><th>勝率</th><th>平均利益／損失</th><th>手数料</th></tr></thead><tbody>${rows.map(({label,a,total=false})=>`<tr${total?' class="total"':''}><td>${label}</td><td>${money(a.profit)}</td><td>${money(a.loss,false,'loss')}</td><td>${money(a.net,true)}</td><td>${pct(a.money_loss_share)}</td><td>${a.trades}</td><td>${money(a.trades?a.net/a.trades:null,true)}</td><td>${pct(a.trades?a.wins/a.trades:null)}</td><td>${a.payoff==null?'—':a.payoff.toFixed(2)}</td><td>${money(a.fees,false,'fee')}</td></tr>`).join('')}</tbody></table></div>`;}
/**
 * 機能: 七機構の説明・必要件数と全期間収支を表示する。
 * @returns {void} 返り値なし。
 */
function familyTable(){document.getElementById('families').innerHTML=`<div class="table-wrap"><table class="family-table"><thead><tr><th>機構・前半固定ID</th><th>何を読むか</th><th>前16 TOP取引／活動場</th><th>前16 NK取引／活動場</th><th>必要件数</th><th>全29 TOP収支</th><th>全29 NK収支</th><th>後13有望条件</th></tr></thead><tbody>${D.families.map(f=>`<tr data-family="${f.family}"><td>${esc(f.family+'. '+f.name)}<br><a class="id" href="${esc(D.allUrl)}#${encodeURIComponent(f.id)}">${esc(f.id)}</a></td><td class="family-explanation">${esc(f.explanation)}</td><td>${f.periods.前16.TOPIX.trades}／${f.periods.前16.TOPIX.active_sessions}</td><td>${f.periods.前16.NK225.trades}／${f.periods.前16.NK225.active_sessions}</td><td>${f.eligible?'充足':'件数不足'}</td><td>${money(f.periods.全29.TOPIX.net,true)}</td><td>${money(f.periods.全29.NK225.net,true)}</td><td>${f.followPassed?'達成':'未達'}</td></tr>`).join('')}</tbody></table></div>`;}
/**
 * 機能: 選んだ機構代表とS対照の固定遅延感度を表示する。
 * @returns {void} 返り値なし。
 */
function familySensitivity(){const f=D.families[Number(document.getElementById('family-sensitivity').value)],s=document.getElementById('family-symbol').value,p=document.getElementById('family-period').value;document.getElementById('family-delay-table').innerHTML=table(f.sensitivity.flatMap(v=>[{label:`遅延${v.delay}秒・共同J`,a:v.joint.periods[p][s],total:v.delay===5},{label:`遅延${v.delay}秒・自己対照S`,a:v.single.periods[p][s]}]));}
/**
 * 機能: 主代表の章と銘柄・期間・売買図の操作を作る。
 * @param {object} m - 主代表。
 * @param {number} i - 章番号。
 * @returns {HTMLElement} 章要素。
 */
function build(m,i){const e=document.createElement('section');e.className='method';e.id=`method-${i}`;e.dataset.methodId=m.id;e.innerHTML=`<h2>${i+1}. ${esc(m.title)}</h2><div class="id">${esc(m.id)}</div><p class="small">${esc(m.configText)}。後13有望条件${m.followPassed?'達成':'未達'}。</p>${m.finding?`<p class="small finding">${esc(m.finding)}</p>`:''}<div class="steps">${[['入口','entry'],['途中','middle'],['出口','exit']].map(([n,k])=>`<div class="step"><strong>${n}</strong><p>${esc(m.steps[k])}</p></div>`).join('')}</div><div class="pair">${['TOPIX','NK225'].map(s=>`<div class="card">${NAMES[s]}・共同J全29<strong>${money(m.periods.全29[s].net,true)}</strong><span class="small">損失割合 ${pct(m.periods.全29[s].money_loss_share)}</span></div>`).join('')}</div><div class="controls symbol-switch">${['TOPIX','NK225'].map(s=>`<button data-symbol="${s}" aria-pressed="${s==='TOPIX'}">${NAMES[s]}</button>`).join('')}<label>期間 <select class="period-select">${PERIODS.map(p=>`<option${p==='全29'?' selected':''}>${p}</option>`).join('')}</select></label></div><h3>共同Jと同設定の自己証拠S</h3><div class="comparison"></div><p class="delta small"></p><p class="small">Sも同じ両市場観測可能時点を使います。相手の内容を使わない対照ですが、入口時刻・再準備が変わるため完全同一機会の比較ではありません。</p><details class="sessions-details"><summary>全29セッションの利益・損失・収支</summary><div class="session-table"></div></details><details><summary>週合計と全29合計</summary><div class="week-table"></div></details><details><summary>勝ち負け枚数・最大損失・気配差</summary><div class="detail-table"></div></details><details><summary>固定条件の遅延1／5／15／60秒感度</summary><div class="delay-table"></div></details><h3>五分足と全注文</h3><div class="controls"><label>方式 <select class="variant-select"><option value="J">共同J</option><option value="S">自己対照S</option></select></label><label>場 <select class="session-select">${D.sessions.map(s=>`<option value="${esc(s)}">${esc(sessionName(s))}</option>`).join('')}</select></label></div><p class="small">五分足は結果図解のみ。判定は原板です。新規●／返済◇、青↑＝買い、橙↓＝売り。</p><div class="chart-box"><div class="chart-title"></div><div class="chart"></div></div><details><summary>新規・返済の全履歴</summary><div class="table-wrap history"></div></details>`;STATE.set(i,{symbol:'TOPIX',period:'全29',session:D.sessions[0],variant:'J'});e.querySelectorAll('[data-symbol]').forEach(b=>b.addEventListener('click',()=>{STATE.get(i).symbol=b.dataset.symbol;updateMethod(i);}));e.querySelector('.period-select').addEventListener('change',v=>{STATE.get(i).period=v.target.value;updateMethod(i);});e.querySelector('.session-select').addEventListener('change',v=>{STATE.get(i).session=v.target.value;drawChart(i);});e.querySelector('.variant-select').addEventListener('change',v=>{STATE.get(i).variant=v.target.value;drawChart(i);});return e;}
/**
 * 機能: 主代表の共同対照・全場・週・感度を選択した銘柄で更新する。
 * @param {number} i - 章番号。
 * @returns {void} 返り値なし。
 */
function updateMethod(i){const m=D.methods[i],s=STATE.get(i),e=document.getElementById(`method-${i}`),a=m.periods[s.period][s.symbol],b=m.single.periods[s.period][s.symbol],c=m.comparison[s.period][s.symbol];e.querySelectorAll('[data-symbol]').forEach(v=>v.setAttribute('aria-pressed',String(v.dataset.symbol===s.symbol)));e.querySelector('.period-select').value=s.period;e.querySelector('.comparison').innerHTML=table([{label:`共同J ${esc(m.id)}`,a,total:true},{label:`自己対照S ${esc(m.single.id)}`,a:b}]);e.querySelector('.delta').innerHTML=`平均一取引の差（J−S）${money(c.平均一取引収支変化,true)}、損失割合の差 ${c.金額損失割合変化==null?'—':(c.金額損失割合変化*100).toFixed(1)+'pt'}。${esc(c.診断)}`;const rows=D.sessions.map(session=>({label:`<button class="session-link" data-session="${esc(session)}">${esc(sessionName(session))}</button>`,a:m.rows.find(r=>r.session===session&&r.symbol===s.symbol)})),total={label:'共同J全29合計',a:m.periods.全29[s.symbol],total:true};e.querySelector('.session-table').innerHTML=table([...rows,total]);e.querySelector('.week-table').innerHTML=table([...m.weeks[s.symbol].map(w=>({label:esc(w.label),a:w})),total]);e.querySelector('.detail-table').innerHTML=`<div class="table-wrap"><table><thead><tr><th>方式</th><th>勝ち／負け枚数</th><th>最大一取引損失</th><th>含み込み最大下落</th><th>最大買／売枚数</th><th>気配差負担</th></tr></thead><tbody>${[['共同J',a],['自己対照S',b]].map(([label,v])=>`<tr><td>${label}</td><td>${v.winning_lots}／${v.losing_lots}</td><td>${money(v.max_trade_loss,false,'loss')}</td><td>${money(v.drawdown,false,'loss')}</td><td>${v.max_long}／${v.max_short}</td><td>${money(v.spread_drag,false,'fee')}</td></tr>`).join('')}</tbody></table></div>`;e.querySelector('.delay-table').innerHTML=table(m.sensitivity.flatMap(v=>[{label:`遅延${v.delay}秒・共同J`,a:v.joint.periods[s.period][s.symbol],total:v.delay===5},{label:`遅延${v.delay}秒・自己対照S`,a:v.single.periods[s.period][s.symbol]}]));e.querySelectorAll('.session-link').forEach(b=>b.addEventListener('click',()=>{s.session=b.dataset.session;drawChart(i);}));drawChart(i);}
/**
 * 機能: 注文を売買と建玉方向で説明する。
 * @param {Array<number>} o - 注文十列。
 * @returns {string} 売買の説明。
 */
function action(o){const buy=o[3]>0,open=o[7]===1;return `${buy?'↑買い':'↓売り'}${open?`新規（${buy?'ロング':'ショート'}）`:`返済（${buy?'ショート':'ロング'}）`}`;}
/**
 * 機能: 選んだJ又はSの五分足・全注文・履歴を描く。
 * @param {number} i - 章番号。
 * @returns {void} 返り値なし。
 */
function drawChart(i){const s=STATE.get(i),m=s.variant==='S'?D.methods[i].single:D.methods[i],e=document.getElementById(`method-${i}`),key=s.session+'|'+s.symbol,bs=D.bars[key]??[],os=m.orders[key]??[],a=m.rows.find(r=>r.session===s.session&&r.symbol===s.symbol);e.querySelector('.session-select').value=s.session;e.querySelector('.variant-select').value=s.variant;e.querySelectorAll('.session-link').forEach(b=>b.closest('tr').classList.toggle('selected-row',b.dataset.session===s.session));e.querySelector('.chart-title').innerHTML=`<span>${esc(sessionName(s.session))}／${NAMES[s.symbol]}／${s.variant}</span><span>${money(a.net,true)} · ${a.trades}取引</span>`;if(!bs.length)e.querySelector('.chart').innerHTML='<div class="empty">足データなし</div>';else{const W=1000,H=360,L=80,R=20,T=20,B=45,pw=W-L-R,ph=H-T-B,left=Math.min(...bs.map(b=>b[0]),...os.map(o=>o[9])),right=Math.max(...bs.map(b=>b[0]+300),...os.map(o=>o[9])),values=bs.flatMap(b=>[b[2],b[3]]).concat(os.map(o=>o[5])),lo=Math.min(...values),hi=Math.max(...values),pad=Math.max((hi-lo)*.08,s.symbol==='TOPIX'?.5:10),min=lo-pad,max=hi+pad,x=t=>L+(t-left)/(right-left)*pw,y=p=>T+(max-p)/(max-min)*ph;let grid='';for(let j=0;j<=5;j++){const yy=T+j*ph/5;grid+=`<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#30465c"/><text x="${L-8}" y="${yy+4}" text-anchor="end" fill="#b7cbe2" font-size="12">${(max-j*(max-min)/5).toFixed(s.symbol==='TOPIX'?1:0)}</text>`;}for(let j=0;j<=6;j++){const t=left+j*(right-left)/6;grid+=`<text x="${x(t)}" y="${H-15}" text-anchor="middle" fill="#b7cbe2" font-size="12">${SHORT.format(new Date(t*1000))}</text>`;}const cw=Math.max(1,Math.min(12,pw/bs.length*.7)),candles=bs.map(b=>{const xx=x(b[0]+150),color=b[4]>=b[1]?'#74cbb6':'#e8869b';return `<g><title>${SHORT.format(new Date(b[0]*1000))} 始${b[1]} 高${b[2]} 安${b[3]} 終${b[4]}</title><line x1="${xx}" y1="${y(b[2])}" x2="${xx}" y2="${y(b[3])}" stroke="${color}"/><rect x="${xx-cw/2}" y="${Math.min(y(b[1]),y(b[4]))}" width="${cw}" height="${Math.max(1,Math.abs(y(b[1])-y(b[4])))}" fill="${color}" opacity=".8"/></g>`;}).join(''),markers=os.map(o=>{const xx=x(o[9]),yy=y(o[5]),color=o[3]>0?'#70daff':'#ffad73';return `<g class="order-marker" data-side="${o[3]}" data-open="${o[7]}"><title>${CLOCK.format(new Date(o[9]*1000))} ${esc(action(o))} ${o[4]}枚 @${o[5]} ${esc(REASONS[o[6]])}</title>${o[7]===1?`<circle cx="${xx}" cy="${yy}" r="4" fill="${color}" stroke="#0b1623"/>`:`<path d="M${xx} ${yy-5} L${xx+5} ${yy} L${xx} ${yy+5} L${xx-5} ${yy}Z" fill="${color}" stroke="#0b1623"/>`}</g>`;}).join('');e.querySelector('.chart').innerHTML=`<svg class="chart-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(sessionName(s.session))}の五分足と全売買"><rect width="${W}" height="${H}" fill="#0b1623"/>${grid}${candles}${markers}</svg>`;}e.querySelector('.history').innerHTML=os.length?`<table><thead><tr><th>約定時刻</th><th>売買</th><th>枚数</th><th>価格</th><th>理由</th><th>判断行→約定行</th></tr></thead><tbody>${os.map(o=>`<tr><td>${CLOCK.format(new Date(o[9]*1000))}</td><td>${esc(action(o))}</td><td>${o[4]}</td><td>${o[5]}</td><td>${esc(REASONS[o[6]])}</td><td>${o[1]}→${o[0]}</td></tr>`).join('')}</tbody></table>`:'<div class="empty">売買なし。勝ちには含めません。</div>';}
/**
 * 機能: 同基準100の二市場中値を欠測で線を切って描画する。
 * @returns {void} 返り値なし。
 */
function drawIndexedPrices(){const session=document.getElementById('indexed-session').value,rows=D.indexedPrices[session]??[],values=rows.flatMap(r=>r.slice(1).filter(v=>v!=null));if(!values.length){document.getElementById('indexed-chart').innerHTML='<p class="empty">同期可能な観測なし</p>';return;}const W=1000,H=280,L=65,R=20,T=20,B=40,left=rows[0][0],right=rows.at(-1)[0],pad=Math.max((Math.max(...values)-Math.min(...values))*.1,.01),min=Math.min(...values)-pad,max=Math.max(...values)+pad,x=t=>L+(t-left)/(right-left)*(W-L-R),y=v=>T+(max-v)/(max-min)*(H-T-B);let grid='';for(let j=0;j<=4;j++){const v=max-j*(max-min)/4,yy=y(v);grid+=`<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#30465c"/><text x="${L-8}" y="${yy+4}" text-anchor="end" fill="#b7cbe2" font-size="12">${v.toFixed(2)}</text>`;}for(let j=0;j<=6;j++){const t=left+j*(right-left)/6;grid+=`<text x="${x(t)}" y="${H-12}" text-anchor="middle" fill="#b7cbe2" font-size="12">${SHORT.format(new Date(t*1000))}</text>`;}const paths=[1,2].map(column=>{let path='',started=false;for(const r of rows){if(r[column]==null){started=false;continue;}path+=(started?'L':'M')+x(r[0])+' '+y(r[column])+' ';started=true;}return `<path class="index-line" data-symbol="${column===1?'TOPIX':'NK225'}" d="${path}" fill="none" stroke="${column===1?'#70daff':'#ffad73'}" stroke-width="1.5"/>`;}).join('');document.getElementById('indexed-chart').innerHTML=`<svg class="indexed-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="二指数中値の基準100比較"><rect width="${W}" height="${H}" fill="#0b1623"/>${grid}${paths}</svg>`;}
/**
 * 機能: 固定したS1売買を当時の相手確認の有無で分けた診断を表示する。
 * @returns {void} 返り値なし。診断データがなければ節を隠す。
 */
function sharedOpportunity(){const e=document.getElementById('shared-opportunity');if(!D.sharedOpportunity){e.hidden=true;return;}e.hidden=false;const s=document.getElementById('opportunity-symbol').value,p=document.getElementById('opportunity-period').value,c=D.sharedOpportunity.比較[p][s];document.getElementById('opportunity-table').innerHTML=`<div class="table-wrap"><table class="opportunity-table"><thead><tr><th>同じS1機会の分類</th><th>利益</th><th>損失</th><th>収支</th><th>損失割合</th><th>取引数</th><th>平均一取引</th><th>勝率</th></tr></thead><tbody>${[['全S1','全S1'],['相手確認あり','相手確認あり'],['相手確認なし','相手確認なし']].map(([label,k])=>{const a=c[k];return `<tr><td>${label}</td><td>${money(a.利益)}</td><td>${money(a.損失,false,'loss')}</td><td>${money(a.収支,true)}</td><td>${pct(a.金額損失割合)}</td><td>${a.取引数}</td><td>${money(a.平均一取引収支,true)}</td><td>${pct(a.勝率)}</td></tr>`;}).join('')}</tbody></table></div><p class="small">確認あり−なしの平均一取引差 ${money(c.平均一取引差,true)}。少数件の分類差から利益を保証しません。</p>`;}
// ----------------------------------------
// 固定結果のみを初期表示し、手法の再選定や通信は行わない。
document.title=D.title;document.getElementById('title').textContent=D.title;document.getElementById('conclusion').innerHTML=D.conclusions.map(t=>`<p>${esc(t)}</p>`).join('');familyTable();document.getElementById('family-sensitivity').innerHTML=D.families.map((f,i)=>`<option value="${i}">${esc(f.family+'. '+f.name)}</option>`).join('');['family-sensitivity','family-symbol','family-period'].forEach(id=>document.getElementById(id).addEventListener('change',familySensitivity));familySensitivity();document.getElementById('nav').innerHTML=D.methods.map((m,i)=>`<a href="#method-${i}">${i+1}. ${esc(m.title)}</a>`).join('');D.methods.forEach((m,i)=>document.getElementById('methods').append(build(m,i)));D.methods.forEach((m,i)=>updateMethod(i));document.getElementById('indexed-session').innerHTML=D.sessions.map(s=>`<option value="${esc(s)}">${esc(sessionName(s))}</option>`).join('');document.getElementById('indexed-session').addEventListener('change',drawIndexedPrices);drawIndexedPrices();document.getElementById('notes').innerHTML=D.notes.map(n=>`<li>${esc(n)}</li>`).join('');document.getElementById('research').innerHTML=D.research.slice(0,4).map(r=>`<li><a href="${esc(r.URL)}" target="_blank" rel="noopener noreferrer">${esc(r.名称)}</a>：${esc(r.本件への推論)}</li>`).join('');document.getElementById('all-link').href=D.allUrl;['opportunity-symbol','opportunity-period'].forEach(id=>document.getElementById(id).addEventListener('change',sharedOpportunity));sharedOpportunity();window.reportTest={D,STATE,updateMethod,drawChart,familyTable,familySensitivity,drawIndexedPrices,sharedOpportunity};
