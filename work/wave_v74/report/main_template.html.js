
"use strict";
const D=JSON.parse(document.getElementById("report-data").textContent),STATE=new Map(),PERIODS=["前16","後13","全29"],NAMES={TOPIX:"TOPIXミニ10枚",NK225:"日経225マイクロ20枚"},PAUSES=["休止なし","2連敗10分","2連敗30分","2連敗収束待ち","2連敗10分＋収束","3連敗30分"],REASONS={1:"初期損切り",2:"トレーリング",3:"60分返済",4:"場内全返済",5:"基準方向の反転",10:"方向確認新規",11:"追跡極値からの反発新規"};
const NUMBER=new Intl.NumberFormat("ja-JP",{maximumFractionDigits:0}),CLOCK=new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",hour:"2-digit",minute:"2-digit",second:"2-digit",hourCycle:"h23"}),SHORT=new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",hour:"2-digit",minute:"2-digit",hourCycle:"h23"});
/**
 * 機能: 値を安全なHTML文字列へ変換する。
 * @param {unknown} v - 表示値。
 * @returns {string} エスケープした文字列。
 */
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
/**
 * 機能: 円の値を正負の色付きで整形する。
 * @param {number|null} v - 円金額。
 * @param {boolean} signed - 符号を付けるか。
 * @param {string} context - 損失又は手数料の文脈色。
 * @returns {string} 金額HTML。
 */
function money(v,signed=false,context=''){ return v==null?'—':`<span class="money ${context==='loss'?'negative':context==='fee'?'muted':v>0?"positive":v<0?"negative":""}">${signed&&v>0?"+":""}${NUMBER.format(v)}円</span>`;}
/**
 * 機能: 欠測に対応して百分率を整形する。
 * @param {number|null} v - 比率。
 * @returns {string} 百分率又はダッシュ。
 */
function pct(v){return v==null?'—':(v*100).toFixed(1)+'%';}
/**
 * 機能: セッション名を短い日本語へ整形する。
 * @param {string} s - 保存セッション名。
 * @returns {string} 日付とデイ・ナイト。
 */
function sessionName(s){return s.replace('_Day',' デイ').replace('_Night',' ナイト');}
/**
 * 機能: 同銘柄の全明細会計を表へ整形する。
 * @param {Array<object>} rows - ラベルと会計値。
 * @returns {string} 主指標テーブルのHTML。
 */
function table(rows){return `<div class="table-wrap"><table class="primary-table"><thead><tr><th>対象</th><th>利益</th><th>損失</th><th>収支</th><th>損失割合</th><th>取引数</th><th>勝率</th><th>平均利益／損失</th><th>手数料</th><th>休止回数</th></tr></thead><tbody>${rows.map(({label,data:a,total=false})=>`<tr${total?' class="total"':''}><td>${label}</td><td>${money(a?.profit)}</td><td>${money(a?.loss,false,'loss')}</td><td>${money(a?.net,true)}</td><td>${pct(a?.money_loss_share)}</td><td>${a?.trades??0}</td><td>${pct(a?.win_rate??(a?.trades?a.wins/a.trades:null))}</td><td>${a?.payoff==null?'—':a.payoff.toFixed(2)}</td><td>${money(a?.fees,false,'fee')}</td><td>${a?.pause_count??0}</td></tr>`).join('')}</tbody></table></div>`;}
/**
 * 機能: 代表の章と各切替操作を作成する。
 * @param {object} m - 手法。
 * @param {number} i - 章番号。
 * @returns {HTMLElement} 章要素。
 */
function build(m,i){const e=document.createElement('section');e.className='method';e.id=`method-${i}`;e.dataset.methodId=m.id;e.innerHTML=`<h2>${i+1}. ${esc(m.title)}</h2><div class="id">${esc(m.id)}</div><p class="small">${esc(m.configText)}。前16の活動条件${m.eligible?'充足':'未達'}、後13の両銘柄有望条件${m.followPassed?'充足':'未達'}。</p><div class="steps">${[['入口','entry'],['途中','middle'],['出口','exit']].map(([name,k])=>`<div class="step"><strong>${name}</strong><p>${esc(m.steps[k])}</p></div>`).join('')}</div><div class="pair">${['TOPIX','NK225'].map(s=>`<div class="card">${NAMES[s]}・全29<strong>${money(m.periods.全29[s].net,true)}</strong><span class="small">損失割合 ${pct(m.periods.全29[s].money_loss_share)}</span></div>`).join('')}</div><div class="controls symbol-switch">${['TOPIX','NK225'].map(s=>`<button data-symbol="${s}" aria-pressed="${s==='TOPIX'}">${NAMES[s]}</button>`).join('')}<label>期間 <select class="period-select">${PERIODS.map(p=>`<option${p==='全29'?' selected':''}>${p}</option>`).join('')}</select></label></div><h3>素朴基準と選定代表</h3><div class="comparison"></div><h3>同じ入口・帯・出口幅で休止だけを比較</h3><div class="pause-comparison"></div><details><summary>同設定の診断対照（いずれも休止なし）</summary><div class="control-comparison"></div></details><details class="sessions-details"><summary>全29セッションの利益・損失・収支</summary><div class="session-table"></div></details><details><summary>週合計と全29合計</summary><div class="week-table"></div></details><details><summary>枚数・含み込み下落・休止解除後</summary><div class="detail-table"></div></details><h3>五分足・新規返済・休止</h3><label>場 <select class="session-select">${D.sessions.map(s=>`<option value="${esc(s)}">${esc(sessionName(s))}</option>`).join('')}</select></label><div class="legend"><span>●新規／◇返済</span><span style="color:#70daff">青＝買い</span><span style="color:#ffad73">橙＝売り</span><span style="color:#ffd082">橙帯＝新規休止</span><span>↑買い／↓売り</span></div><div class="chart-box"><div class="chart-title"></div><div class="chart"></div></div><details><summary>新規・返済の履歴</summary><div class="table-wrap history"></div></details><details><summary>休止開始・再開の区間</summary><div class="pause-history"></div></details>`;STATE.set(i,{symbol:'TOPIX',period:'全29',session:D.sessions[0]});e.querySelectorAll('[data-symbol]').forEach(b=>b.addEventListener('click',()=>{STATE.get(i).symbol=b.dataset.symbol;updateMethod(i);}));e.querySelector('.period-select').addEventListener('change',v=>{STATE.get(i).period=v.target.value;updateMethod(i);});e.querySelector('.session-select').addEventListener('change',v=>{STATE.get(i).session=v.target.value;drawChart(i);});return e;}
/**
 * 機能: 選んだ銘柄・期間の比較と全場損益を更新する。
 * @param {number} i - 章番号。
 * @returns {void} 返り値なし。
 */
function updateMethod(i){const m=D.methods[i],s=STATE.get(i),e=document.getElementById(`method-${i}`),a=m.periods[s.period][s.symbol],base=m.baseline.periods[s.period][s.symbol];e.querySelectorAll('[data-symbol]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.symbol===s.symbol)));e.querySelector('.comparison').innerHTML=table([{label:`素朴基準 ${esc(m.baseline.id)}`,data:base},{label:`基準別比較代表 ${esc(m.id)}`,data:a,total:true}]);e.querySelector('.pause-comparison').innerHTML=table(m.pauseComparison.map(p=>({label:esc(PAUSES[p.config.pause_mode])+` <span class="id">${esc(p.id)}</span>`,data:p.periods[s.period][s.symbol],total:p.id===m.id})));e.querySelector('.control-comparison').innerHTML=table([{label:'同設定・通常方向・休止なし',data:m.pauseComparison[0].periods[s.period][s.symbol]},...m.controls.map(p=>({label:esc(p.config.group)+` <span class="id">${esc(p.id)}</span>`,data:p.periods[s.period][s.symbol]}))]);const rows=D.sessions.map(session=>({label:`<button class="session-link" data-session="${esc(session)}">${esc(sessionName(session))}</button>`,data:m.rows.find(r=>r.session===session&&r.symbol===s.symbol)})),total={label:'全29合計',data:m.periods.全29[s.symbol],total:true};e.querySelector('.session-table').innerHTML=table([...rows,total]);e.querySelector('.week-table').innerHTML=table([...m.weeks[s.symbol].map(w=>({label:esc(w.label),data:w})),total]);e.querySelector('.detail-table').innerHTML=`<div class="table-wrap"><table><thead><tr><th>勝ち枚数</th><th>負け枚数</th><th>含み込み最大下落</th><th>最大買／売枚数</th><th>休止分</th><th>再開後最初の取引</th><th>同収支</th></tr></thead><tbody><tr><td>${a.winning_lots}</td><td>${a.losing_lots}</td><td>${money(a.drawdown,false,'loss')}</td><td>${a.max_long}／${a.max_short}</td><td>${(a.paused_seconds/60).toFixed(1)}</td><td>${a.resumed_trades}</td><td>${money(a.resumed_net,true)}</td></tr></tbody></table></div>`;e.querySelectorAll('.session-link').forEach(b=>b.addEventListener('click',()=>{s.session=b.dataset.session;drawChart(i);}));drawChart(i);}
/**
 * 機能: 注文の新規返済と建玉方向を表示する。
 * @param {Array<number>} o - 注文十列。
 * @returns {string} 平易な売買説明。
 */
function action(o){const buy=o[3]>0,open=o[7]===1;return `${buy?'↑買い':'↓売り'}${open?`新規（${buy?'ロング':'ショート'}）`:`返済（${buy?'ショート':'ロング'}）`}`;}
/**
 * 機能: 五分足・全注文・休止帯と履歴を描画する。
 * @param {number} i - 章番号。
 * @returns {void} 返り値なし。
 */
function drawChart(i){const s=STATE.get(i),m=D.methods[i],e=document.getElementById(`method-${i}`),key=s.session+'|'+s.symbol,bs=D.bars[key]??[],os=m.orders[key]??[],ps=m.pauses[key]??[],a=m.rows.find(r=>r.session===s.session&&r.symbol===s.symbol);e.querySelector('.session-select').value=s.session;e.querySelectorAll('.session-link').forEach(b=>b.closest('tr').classList.toggle('selected-row',b.dataset.session===s.session));e.querySelector('.chart-title').innerHTML=`<span>${esc(sessionName(s.session))}／${NAMES[s.symbol]}</span><span>${money(a.net,true)} · ${a.trades}取引 · 休止${a.pause_count}回</span>`;if(!bs.length)e.querySelector('.chart').innerHTML='<div class="empty">足データなし</div>';else{const W=1000,H=360,L=80,R=20,T=20,B=45,pw=W-L-R,ph=H-T-B,left=Math.min(...bs.map(b=>b[0]),...os.map(o=>o[9])),right=Math.max(...bs.map(b=>b[0]+300),...os.map(o=>o[9])),vs=bs.flatMap(b=>[b[2],b[3]]).concat(os.map(o=>o[5])),lo=Math.min(...vs),hi=Math.max(...vs),pad=Math.max((hi-lo)*.08,s.symbol==='TOPIX'?.5:10),min=lo-pad,max=hi+pad,x=t=>L+(t-left)/(right-left)*pw,y=p=>T+(max-p)/(max-min)*ph;let grid='';for(let j=0;j<=5;j++){const yy=T+j*ph/5;grid+=`<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#30465c"/><text x="${L-8}" y="${yy+4}" text-anchor="end" fill="#b7cbe2" font-size="12">${(max-j*(max-min)/5).toFixed(s.symbol==='TOPIX'?1:0)}</text>`;}for(let j=0;j<=6;j++){const t=left+j*(right-left)/6;grid+=`<text x="${x(t)}" y="${H-15}" text-anchor="middle" fill="#b7cbe2" font-size="12">${SHORT.format(new Date(t*1000))}</text>`;}const shade=ps.map(p=>`<rect class="pause-zone" data-mode="${p[2]}" x="${x(Math.max(left,p[0]))}" y="${T}" width="${Math.max(0,x(Math.min(right,p[1]))-x(Math.max(left,p[0])))}" height="${ph}" fill="#d49b3e" opacity=".17"><title>${esc(PAUSES[p[2]])} ${CLOCK.format(new Date(p[0]*1000))}〜${CLOCK.format(new Date(p[1]*1000))}</title></rect>`).join(''),cw=Math.max(1,Math.min(12,pw/bs.length*.7)),candles=bs.map(b=>{const xx=x(b[0]+150),color=b[4]>=b[1]?'#74cbb6':'#e8869b';return `<g><title>${SHORT.format(new Date(b[0]*1000))} 始${b[1]} 高${b[2]} 安${b[3]} 終${b[4]}</title><line x1="${xx}" y1="${y(b[2])}" x2="${xx}" y2="${y(b[3])}" stroke="${color}"/><rect x="${xx-cw/2}" y="${Math.min(y(b[1]),y(b[4]))}" width="${cw}" height="${Math.max(1,Math.abs(y(b[1])-y(b[4])))}" fill="${color}" opacity=".8"/></g>`;}).join(''),marks=os.map(o=>{const xx=x(o[9]),yy=y(o[5]);return `<g class="order-marker" data-side="${o[3]}" data-open="${o[7]}"><title>${CLOCK.format(new Date(o[9]*1000))} ${esc(action(o))} ${o[4]}枚 @${o[5]} ${esc(REASONS[o[6]])}</title>${o[7]===1?`<circle cx="${xx}" cy="${yy}" r="4" fill="${o[3]>0?'#70daff':'#ffad73'}" stroke="#0b1623"/>`:`<path d="M${xx} ${yy-5} L${xx+5} ${yy} L${xx} ${yy+5} L${xx-5} ${yy}Z" fill="${o[3]>0?'#70daff':'#ffad73'}" stroke="#0b1623"/>`}</g>`;}).join('');e.querySelector('.chart').innerHTML=`<svg class="chart-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(sessionName(s.session))}の五分足と売買・休止"><rect width="${W}" height="${H}" fill="#0b1623"/>${shade}${grid}${candles}${marks}</svg>`;}e.querySelector('.history').innerHTML=os.length?`<table><thead><tr><th>約定時刻</th><th>売買</th><th>枚数</th><th>価格</th><th>理由</th><th>判断行→約定行</th></tr></thead><tbody>${os.map(o=>`<tr><td>${CLOCK.format(new Date(o[9]*1000))}</td><td>${esc(action(o))}</td><td>${o[4]}</td><td>${o[5]}</td><td>${esc(REASONS[o[6]])}</td><td>${o[1]}→${o[0]}</td></tr>`).join('')}</tbody></table>`:'<div class="empty">売買なし。勝ちには含めません。</div>';e.querySelector('.pause-history').innerHTML=ps.length?`<div class="table-wrap"><table><thead><tr><th>開始</th><th>終了／場内停止</th><th>方式</th><th>分</th></tr></thead><tbody>${ps.map(p=>`<tr><td>${CLOCK.format(new Date(p[0]*1000))}</td><td>${CLOCK.format(new Date(p[1]*1000))}</td><td>${esc(PAUSES[p[2]])}</td><td>${((p[1]-p[0])/60).toFixed(1)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="small">この場の休止なし。</p>';}
/**
 * 機能: 参照値の価格・由来・欠測を銘柄別に表示する。
 * @returns {void} 返り値なし。
 */
function referenceTable(){const symbol=document.getElementById('reference-symbol').value;document.getElementById('reference-table').innerHTML=`<div class="table-wrap"><table><thead><tr><th>場</th><th>始値</th><th>由来</th><th>前保存場値</th><th>前保存場</th><th>日次PreviousClose参考</th><th>利用開始行</th></tr></thead><tbody>${D.sessions.map(session=>{const r=D.references[session+'|'+symbol],a=r.ref_open,b=r.ref_prev;return `<tr><td>${esc(sessionName(session))}</td><td>${a.value}</td><td>${a.kind==='feed_OpeningPrice_current_session'?'当該場feed始値':'初約定の観測始値'}</td><td>${b.value??'欠測'}</td><td>${b.source_session?esc(sessionName(b.source_session)):'保存なし'}${b.weekend_gap?'（週末）':''}</td><td>${r.daily_previous_feed.value??'欠測'}</td><td>始${a.known_from_i}／前${b.known_from_i}</td></tr>`;}).join('')}</tbody></table></div><p class="small">前保存場値は公式終値保証なし。日次PreviousCloseは別の参照で、今回は新規条件に使いません。初場の前値は補完しません。</p>`;}
/**
 * 機能: 事後追加した新規方向だけの三代表を主レポート上部へ表示する。
 * @returns {void} 返り値なし。追加資料がなければ表示しない。
 */
function extensionOverview(){const ext=D.extensionSummary,e=document.getElementById('extension-overview');if(!ext){e.hidden=true;return;}e.hidden=false;e.innerHTML=`<h2>新規方向のみ制限の追加検証</h2><p>${esc(ext.conclusion)}</p><p class="small">第一段階で追加した「基準を跨いだら返済」を外し、連敗休止240条件を事後追加。既存48＋追加240の前16だけで選び、後13で変更していません。未知データの検証ではありません。</p><div class="extension-table">${table(ext.methods.flatMap(m=>['TOPIX','NK225'].map(symbol=>({label:esc(m.id)+'／'+NAMES[symbol],data:m.periods.全29[symbol]}))))}</div><p><a href="${esc(ext.url)}">追加3代表の説明・全29場・五分足と休止</a> · <a href="${esc(ext.allUrl)}">追加240条件の一覧</a></p>`;}

// ----------------------------------------
// 固定結果だけで画面を初期化する。銘柄の円を合算しない。
document.getElementById('stage-description').textContent=D.stageText??'第一段階480条件の比較です。';extensionOverview();document.getElementById('execution-summary').textContent=`比較代表の出口幅は${D.summary.widths.join('／')}%、60分で返済判断。条件成立後の次観測ラージ板bid/askをミニ・マイクロの約定に代用。${D.summary.conditionLabel??'全480'}で両銘柄の全29黒字は${D.summary.bothPositiveCount}条件です。`;document.getElementById('research').innerHTML=`<ul>${D.research.map((r,i)=>`<li>${['利益玉と損失玉の実現行動を研究。','取得原価の代理と価格継続を研究。','為替の損切り注文と価格加速を研究。'][i]} <a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}</a></li>`).join('')}</ul>`;document.title=D.title;document.getElementById('title').textContent=D.title;document.getElementById('conclusion').textContent=D.conclusion;document.getElementById('nav').innerHTML=D.methods.map((m,i)=>`<a href="#method-${i}">${i+1}. ${esc(m.title)}</a>`).join('');D.methods.forEach((m,i)=>document.getElementById('methods').append(build(m,i)));D.methods.forEach((m,i)=>updateMethod(i));document.getElementById('notes').innerHTML=`<ul class="notes">${D.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`;document.getElementById('all-link').href=D.allUrl;document.getElementById('reference-symbol').addEventListener('change',referenceTable);referenceTable();document.getElementById('all-link').textContent=D.allLinkText??'全480条件の一覧と全セッション';window.reportTest={D,STATE,updateMethod,drawChart,referenceTable,extensionOverview};
