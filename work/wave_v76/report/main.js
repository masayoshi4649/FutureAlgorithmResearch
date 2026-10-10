
"use strict";
const D=JSON.parse(document.getElementById('report-data').textContent),STATE=new Map(),PERIODS=['前16','後13','全29'],NAMES={TOPIX:'TOPIXミニ10枚',NK225:'日経225マイクロ20枚'},REASONS={1:'保険の初期損切り',2:'保険のトレーリング',3:'保有時間上限',4:'場内全返済',6:'両市場の反対合意',7:'両市場の支持消失',10:'共同方向の新規',12:'返済後に再確認してドテン'},NUMBER=new Intl.NumberFormat('ja-JP',{maximumFractionDigits:0}),CLOCK=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}),SHORT=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
/**
 * 機能: 表示値をHTMLへ安全に埋め込む。
 * @param {unknown} v - 表示値。
 * @returns {string} 安全な文字列。
 */
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/**
 * 機能: 金額を文脈別の色で表示する。
 * @param {number|null} v - 円金額。
 * @param {boolean} signed - 正符号の有無。
 * @param {string} context - 損失又は手数料。
 * @returns {string} 円金額のHTML。
 */
function money(v,signed=false,context=''){return v==null?'—':`<span class="money ${context==='loss'?'negative':context==='fee'?'muted':v>0?'positive':v<0?'negative':''}">${signed&&v>0?'+':''}${NUMBER.format(v===0?0:v)}円</span>`;}
/**
 * 機能: 比率を百分率表示する。
 * @param {number|null} v - 比率。
 * @returns {string} 百分率又はダッシュ。
 */
function pct(v){return v==null?'—':(v*100).toFixed(1)+'%';}
/**
 * 機能: 場名を短く日本語表示する。
 * @param {string} s - 保存場名。
 * @returns {string} 場名。
 */
function sessionName(s){return s.replace('_Day',' デイ').replace('_Night',' ナイト');}
/**
 * 機能: 管理方式を短く表示する。
 * @param {object} c - 固定設定。
 * @returns {string} 管理名。
 */
function manager(c){return ['M0 保険だけ','M1 反対合意で撤退','M2 撤退後に反転','M3 支持消失も撤退'][c.manage_mode]+(c.manage_mode?`・${c.manage_confirm}秒確認`:'');}
/**
 * 機能: 全決済会計を共通金額表へ整形する。
 * @param {Array<object>} rows - ラベルと会計。
 * @returns {string} 金額表HTML。
 */
function table(rows){return `<div class="table-wrap"><table class="primary-table"><thead><tr><th>対象</th><th>利益</th><th>損失</th><th>収支</th><th>損失割合</th><th>取引数</th><th>平均一取引</th><th>勝率</th><th>平均利益／損失</th><th>手数料</th></tr></thead><tbody>${rows.map(({label,a,total=false})=>{const payoff=a.payoff??(a.wins&&a.losses?(a.profit/a.wins)/(a.loss/a.losses):null);return `<tr${total?' class="total"':''}><td>${label}</td><td>${money(a.profit)}</td><td>${money(a.loss,false,'loss')}</td><td>${money(a.net,true)}</td><td>${pct(a.money_loss_share)}</td><td>${a.trades}</td><td>${money(a.trades?a.net/a.trades:null,true)}</td><td>${pct(a.trades?a.wins/a.trades:null)}</td><td>${payoff==null?'—':payoff.toFixed(2)}</td><td>${money(a.fees,false,'fee')}</td></tr>`;}).join('')}</tbody></table></div>`;}
/**
 * 機能: 変更部分を比較する上部表を更新する。
 * @returns {void} 返り値なし。
 */
function designComparison(){const s=document.getElementById('comparison-symbol').value,p=document.getElementById('comparison-period').value;document.getElementById('design-comparison').innerHTML=table(D.comparisons.map(x=>({label:esc(x.label)+`<br><span class="id">${esc(x.id)}</span>`,a:x.periods[p][s],total:x.id===D.benchmark.id})));}
/**
 * 機能: 六機構の説明と件数・成績を表示する。
 * @returns {void} 返り値なし。
 */
function familyTable(){document.getElementById('families').innerHTML=`<div class="table-wrap"><table class="family-table"><thead><tr><th>機構・前半固定ID</th><th>何を読むか</th><th>前16 TOP取引／活動場</th><th>前16 NK取引／活動場</th><th>必要件数</th><th>全29 TOP収支</th><th>全29 NK収支</th><th>後13有望条件</th></tr></thead><tbody>${D.families.map(f=>`<tr data-family="${f.family}"><td>${esc(f.family+'. '+f.name)}<br><a class="id" href="${esc(D.allUrl)}#${encodeURIComponent(f.id)}">${esc(f.id)}</a></td><td class="family-explanation">${esc(f.explanation)}</td><td>${f.periods.前16.TOPIX.trades}／${f.periods.前16.TOPIX.active_sessions}</td><td>${f.periods.前16.NK225.trades}／${f.periods.前16.NK225.active_sessions}</td><td>${f.eligible?'充足':'件数不足'}</td><td>${money(f.periods.全29.TOPIX.net,true)}</td><td>${money(f.periods.全29.NK225.net,true)}</td><td>${f.followPassed?'達成':'未達'}</td></tr>`).join('')}</tbody></table></div>`;}
/**
 * 機能: 固定代表の情報遅延感度を更新する。
 * @returns {void} 返り値なし。
 */
function familySensitivity(){const pool=[...D.families,D.benchmark],f=pool[Number(document.getElementById('family-sensitivity').value)],s=document.getElementById('family-symbol').value,p=document.getElementById('family-period').value;document.getElementById('family-delay-table').innerHTML=table(f.sensitivity.map(v=>({label:`情報遅延${v.delay}秒`,a:v.periods[p][s],total:v.delay===5})));}
/**
 * 機能: 売買図で選ばれた管理対照を返す。
 * @param {object} m - 主代表。
 * @param {object} state - 現在の操作状態。
 * @returns {object} 台帳付き結果。
 */
function variant(m,state){return state.variant===D.benchmark.id?D.benchmark:m.controls.find(x=>x.id===state.variant)??m;}
/**
 * 機能: 五分足と全注文の丸・菱形をSVGへ変換する。
 * @param {object} m - 台帳付き方式。
 * @param {object} state - 銘柄・場の操作状態。
 * @returns {string} 売買図SVG。
 */
function chart(m,state){const key=state.session+'|'+state.symbol,candles=D.bars[key]??[],orders=m.orders[key]??[];if(!candles.length)return '<div class="empty">五分足なし</div>';const W=1180,H=390,L=67,R=16,T=18,B=43,prices=[...candles.flatMap(x=>[x[2],x[3]]),...orders.map(o=>o[5])],low=Math.min(...prices),high=Math.max(...prices),pad=Math.max((high-low)*.08,state.symbol==='TOPIX'?.5:5),ymin=low-pad,ymax=high+pad,first=Math.min(candles[0][0],...(orders.length?orders.map(o=>o[9]):[candles[0][0]])),last=Math.max(candles.at(-1)[0]+300,...(orders.length?orders.map(o=>o[9]):[candles.at(-1)[0]+300])),X=t=>L+(t-first)/(last-first)*(W-L-R),Y=p=>T+(ymax-p)/(ymax-ymin)*(H-T-B);let shapes='';for(let i=0;i<=5;i++){const p=ymin+(ymax-ymin)*i/5,y=Y(p);shapes+=`<line x1="${L}" x2="${W-R}" y1="${y}" y2="${y}" stroke="#294158"/><text x="${L-8}" y="${y+4}" fill="#b4c8dd" text-anchor="end" font-size="12">${p.toFixed(state.symbol==='TOPIX'?1:0)}</text>`;}for(let i=0;i<=6;i++){const t=first+(last-first)*i/6,x=X(t);shapes+=`<line x1="${x}" x2="${x}" y1="${T}" y2="${H-B}" stroke="#1e344a"/><text x="${x}" y="${H-14}" fill="#b4c8dd" text-anchor="middle" font-size="12">${SHORT.format(t*1000)}</text>`;}const bw=Math.min(8,(W-L-R)*200/(last-first));for(const c of candles){const x=X(c[0]+150),up=c[4]>=c[1],color=up?'#77e0b5':'#ff929f';shapes+=`<line x1="${x}" x2="${x}" y1="${Y(c[2])}" y2="${Y(c[3])}" stroke="${color}"/><rect x="${x-bw/2}" y="${Math.min(Y(c[1]),Y(c[4]))}" width="${bw}" height="${Math.max(1,Math.abs(Y(c[1])-Y(c[4])))}" fill="${color}"/>`;}orders.forEach((o,i)=>{const x=X(o[9]),y=Y(o[5]),color=o[3]===1?'#70daff':'#ff929f',stroke=o[6]===12?'#ffd082':'#09111b',shape=o[7]===1?`<circle cx="${x}" cy="${y}" r="5.5" fill="${color}" stroke="${stroke}" stroke-width="2"/>`:`<path d="M${x},${y-6}L${x+6},${y}L${x},${y+6}L${x-6},${y}Z" fill="${color}" stroke="${stroke}" stroke-width="1.5"/>`;shapes+=`<g class="order-marker" data-order-index="${i}" data-reason="${o[6]}" data-new="${o[7]}">${shape}<title>${esc(CLOCK.format(o[9]*1000)+' '+(o[7]?'新規':'返済')+' '+(o[3]===1?'買い':'売り')+' '+o[4]+'枚 @'+o[5]+' '+REASONS[o[6]])}</title></g>`;});return `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(sessionName(state.session)+' '+NAMES[state.symbol]+' 五分足と全注文')}">${shapes}</svg>`;}
/**
 * 機能: 新規と返済の全注文を判断時刻も添えて表示する。
 * @param {object} m - 台帳付き方式。
 * @param {object} state - 銘柄・場の操作状態。
 * @returns {string} 注文履歴HTML。
 */
function history(m,state){const key=state.session+'|'+state.symbol,orders=m.orders[key]??[];return `<div class="table-wrap history"><table class="history-table"><thead><tr><th>約定時刻</th><th>判断時刻</th><th>取引</th><th>売買</th><th>枚数</th><th>価格</th><th>理由</th><th>決済収支</th></tr></thead><tbody>${orders.map((o,i)=>`<tr data-order-index="${i}"><td>${CLOCK.format(o[9]*1000)}</td><td>${CLOCK.format(m.decisionTimes[key][i]*1000)}</td><td>${o[7]?(o[6]===12?'↔ ドテン新規':'新規'):'返済'}</td><td>${o[3]===1?'＋ 買い':'− 売り'}</td><td>${o[4]}</td><td>${o[5].toFixed(state.symbol==='TOPIX'?1:0)}</td><td>${esc(REASONS[o[6]]??o[6])}</td><td>${money(m.orderNet[key][i],true)}</td></tr>`).join('')}</tbody></table>${orders.length?'':'<div class="empty">取引なし</div>'}</div>`;}
/**
 * 機能: 主章の構造と操作イベントを作る。
 * @param {object} m - 主代表。
 * @param {number} i - 章番号。
 * @returns {HTMLElement} 主章。
 */
function build(m,i){const e=document.createElement('section');e.className='method';e.id=`method-${i}`;e.dataset.methodId=m.id;e.innerHTML=`<h2>${i+1}. ${esc(m.title)}</h2><div class="id">${esc(m.id)}</div><p class="small">${esc(m.configText)}。後13有望条件${m.followPassed?'達成':'未達'}。</p><div class="steps">${[['入口','entry'],['途中','middle'],['出口','exit']].map(([n,k])=>`<div class="step"><strong>${n}</strong><p>${esc(m.steps[k])}</p></div>`).join('')}</div>${m.finding?`<p class="finding small">${esc(m.finding)}</p>`:''}<div class="pair">${['TOPIX','NK225'].map(s=>`<div class="card">${NAMES[s]}・全29<strong>${money(m.periods.全29[s].net,true)}</strong><span class="small">損失割合 ${pct(m.periods.全29[s].money_loss_share)}</span></div>`).join('')}</div><div class="controls symbol-switch">${['TOPIX','NK225'].map(s=>`<button data-symbol="${s}" aria-pressed="${s==='TOPIX'}">${NAMES[s]}</button>`).join('')}<label>期間 <select class="period-select">${PERIODS.map(p=>`<option${p==='全29'?' selected':''}>${p}</option>`).join('')}</select></label></div><h3>現方式・同設定の保険だけ・従来J1基準</h3><div class="comparison"></div><p class="delta small"></p><details><summary>同じ入口・保険幅・保有上限の七管理対照</summary><div class="management-comparison"></div></details><details class="sessions-details"><summary>全29セッションの利益・損失・収支</summary><div class="session-table"></div></details><details><summary>週合計と全29合計</summary><div class="week-table"></div></details><details><summary>出口理由・ドテン収支・勝ち負け枚数・最大損失</summary><div class="exit-reasons"></div><div class="detail-table"></div></details><details><summary>同設定の遅延1／5／15秒感度</summary><div class="delay-table"></div></details><h3>五分足と全売買</h3><div class="controls"><label>売買図の方式 <select class="variant-select">${m.controls.map(x=>`<option value="${esc(x.id)}"${x.id===m.id?' selected':''}>${esc(manager(x.config))}</option>`).join('')}<option value="${esc(D.benchmark.id)}">従来J1基準</option></select></label><label>場 <select class="session-select">${D.sessions.map(s=>`<option value="${s}">${esc(sessionName(s))}</option>`).join('')}</select></label></div><div class="chart-title"></div><div class="legend"><span>丸＝新規、菱形＝返済</span><span style="color:var(--cyan)">青＝買い</span><span style="color:var(--red)">桃＝売り</span><span style="color:var(--amber)">黄輪郭＝再確認後ドテン</span></div><div class="chart-box"><div class="chart"></div></div><div class="order-history"></div>`;STATE.set(m.id,{symbol:'TOPIX',period:'全29',variant:m.id,session:D.sessions[0]});e.querySelectorAll('[data-symbol]').forEach(b=>b.addEventListener('click',()=>{STATE.get(m.id).symbol=b.dataset.symbol;render(e,m);}));for(const [cls,key] of [['period-select','period'],['variant-select','variant'],['session-select','session']])e.querySelector('.'+cls).addEventListener('change',ev=>{STATE.get(m.id)[key]=ev.target.value;render(e,m);});return e;}
/**
 * 機能: 主章の比較会計、全場、週、理由、売買図を現在状態へ更新する。
 * @param {HTMLElement} e - 主章。
 * @param {object} m - 主代表。
 * @returns {void} 返り値なし。
 */
function render(e,m){const state=STATE.get(m.id),s=state.symbol,p=state.period,insurance=m.controls.find(c=>c.config.manage_mode===0),a=m.periods[p][s],b=insurance.periods[p][s];e.querySelectorAll('[data-symbol]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.symbol===s)));e.querySelector('.comparison').innerHTML=table([{label:'現方式',a,total:true},{label:'同設定M0・保険だけ',a:b},{label:'従来J1基準・入口300秒',a:D.benchmark.periods[p][s]}]);e.querySelector('.delta').innerHTML=`同設定M0からの変化：収支 ${money(a.net-b.net,true)}、利益 ${money(a.profit-b.profit,true)}、損失 ${money(a.loss-b.loss,true)}、取引数 ${a.trades-b.trades>=0?'+':''}${a.trades-b.trades}。損失だけの減少を成功とは扱いません。`;e.querySelector('.management-comparison').innerHTML=table(m.controls.map(c=>({label:esc(manager(c.config)),a:c.periods[p][s],total:c.id===m.id})));e.querySelector('.session-table').innerHTML=table([...D.sessions.map(session=>({label:`<button class="session-link" data-session="${session}">${esc(sessionName(session))}</button>`,a:m.rows.find(r=>r.session===session&&r.symbol===s)})),{label:'全29合計',a:m.periods.全29[s],total:true}]);e.querySelectorAll('.session-link').forEach(x=>x.addEventListener('click',()=>{state.session=x.dataset.session;e.querySelector('.session-select').value=state.session;render(e,m);e.querySelector('.chart-box').scrollIntoView({block:'center',behavior:'smooth'});}));e.querySelector('.week-table').innerHTML=table([...m.weeks[s].map(x=>({label:esc(x.label),a:x})),{label:'全29合計',a:m.periods.全29[s],total:true}]);e.querySelector('.exit-reasons').innerHTML=table([...Object.entries(m.exitReasons[p][s]).map(([reason,x])=>({label:esc(REASONS[reason]),a:x})),{label:'うちドテン新規の決済',a:m.flipPeriods[p][s]}]);e.querySelector('.detail-table').innerHTML=`<div class="table-wrap"><table class="detail-table-inner"><thead><tr><th>勝ち／負け枚数</th><th>最大単一損失</th><th>最大時価下落</th><th>最大黒字場除外収支</th><th>気配差負担</th><th>平均保有</th><th>ドテン新規数</th></tr></thead><tbody><tr><td>${a.winning_lots}／${a.losing_lots}</td><td>${money(a.max_trade_loss,false,'loss')}</td><td>${money(a.drawdown,false,'loss')}</td><td>${money(a.without_best_session,true)}</td><td>${money(a.spread_drag,false,'fee')}</td><td>${a.trades?(a.hold_seconds/a.trades/60).toFixed(1)+'分':'—'}</td><td>${a.flip_count??0}</td></tr></tbody></table></div>`;e.querySelector('.delay-table').innerHTML=table(m.sensitivity.map(v=>({label:`情報遅延${v.delay}秒`,a:v.periods[p][s],total:v.delay===5})));const chosen=variant(m,state);e.querySelector('.chart-title').innerHTML=`<span>${esc(sessionName(state.session)+' '+NAMES[s])}</span><span class="id">${esc(chosen.id)}</span>`;e.querySelector('.chart').innerHTML=chart(chosen,state);e.querySelector('.order-history').innerHTML=history(chosen,state);}
// ----------------------------------------
// 保存結果で初期化する。研究中の選定や注文はブラウザ内で実行しない。
document.title=D.title;document.getElementById('title').textContent=D.title;document.getElementById('conclusion').innerHTML=D.conclusions.map(x=>`<p>${esc(x)}</p>`).join('');document.getElementById('all-link').href=D.allUrl;document.getElementById('notes').innerHTML=D.notes.map(x=>`<li>${esc(x)}</li>`).join('');document.getElementById('research').innerHTML=D.research.map(x=>`<li><a href="${esc(x.URL)}">${esc(x.研究)}</a> — ${esc(x.限界)}</li>`).join('');document.getElementById('nav').innerHTML=D.methods.map((m,i)=>`<a href="#method-${i}">${i+1}. ${esc(m.title)}</a>`).join('');familyTable();document.getElementById('family-sensitivity').innerHTML=[...D.families,D.benchmark].map((f,i)=>`<option value="${i}">${esc(f.name??'従来J1基準')}</option>`).join('');['comparison-symbol','comparison-period'].forEach(id=>document.getElementById(id).addEventListener('change',designComparison));['family-sensitivity','family-symbol','family-period'].forEach(id=>document.getElementById(id).addEventListener('change',familySensitivity));D.methods.forEach((m,i)=>{const e=build(m,i);document.getElementById('methods').append(e);render(e,m);});designComparison();familySensitivity();window.reportTest={D,STATE,render,chart,history,table,variant,familyTable,familySensitivity,designComparison};
