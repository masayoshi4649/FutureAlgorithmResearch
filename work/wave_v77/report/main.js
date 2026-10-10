"use strict";
const D=JSON.parse(document.getElementById('report-data').textContent),STATE=new Map(),PERIODS=D.periodNames,
NAMES={TOPIX:'TOPIXミニ・最大10枚',NK225:'日経225マイクロ・最大20枚'},
REASONS={1:'初期損切り',2:'利益保護・トレーリング',3:'保有時間上限',4:'場内全返済',6:'二市場の反対合意',8:'構造幅・追加後の損失枠超過',9:'進展不足と支持不足',10:'最初の新規',11:'順行後の追加'},
NUMBER=new Intl.NumberFormat('ja-JP',{maximumFractionDigits:0}),
CLOCK=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}),
SHORT=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});

/**
 * 機能: 表示値をHTMLへ安全に埋め込む。
 * @param {unknown} v - 表示値。
 * @returns {string} 安全な文字列。
 */
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

/**
 * 機能: 金額を利益・損失・費用の文脈で色分けする。
 * @param {number|null} v - 円金額。
 * @param {boolean} signed - 正符号の有無。
 * @param {string} context - 損失又は費用の表示指定。
 * @returns {string} 金額のHTML。
 */
function money(v,signed=false,context=''){return v==null?'—':`<span class="money ${context==='loss'?'negative':context==='fee'?'muted':v>0?'positive':v<0?'negative':''}">${signed&&v>0?'+':''}${NUMBER.format(v===0?0:v)}円</span>`;}

/**
 * 機能: 比率を百分率へ変換する。
 * @param {number|null} v - 比率。
 * @returns {string} 百分率又はダッシュ。
 */
function pct(v){return v==null?'—':(v*100).toFixed(1)+'%';}

/**
 * 機能: 保存場名を日本語へ短くする。
 * @param {string} s - 保存場名。
 * @returns {string} 場名。
 */
function sessionName(s){return s.replace('_Day',' デイ').replace('_Night',' ナイト');}

/**
 * 機能: 保護方式と数量配分の名称を返す。
 * @param {object} c - 固定設定。
 * @returns {string} 管理名称。
 */
function manager(c){return ['P0 従来','P1 分離','P2 建値保護','P3 利益固定','P4 高安損切り','P5 進展不足'][c.policy]+(c.allocation?'・A1 段階追加':'・A0 全量');}

/**
 * 機能: 建値別利益・損失と組数を共通表に表示する。
 * @param {Array<object>} rows - ラベルと会計。
 * @returns {string} 金額表のHTML。
 */
function table(rows){return `<div class="table-wrap"><table class="primary-table"><thead><tr><th>対象</th><th>利益</th><th>損失</th><th>収支</th><th>金額利益割合</th><th>利益／損失</th><th>組数</th><th>組勝率</th><th>平均一組</th><th>手数料</th></tr></thead><tbody>${rows.map(({label,a,total=false})=>{if(!a)return `<tr><td>${label}</td><td colspan="9" class="muted">未実施</td></tr>`;const share=a.profit_share??(a.profit+a.loss?a.profit/(a.profit+a.loss):null),ratio=a.profit_loss_ratio??(a.loss?a.profit/a.loss:null);return `<tr${total?' class="total"':''}><td>${label}</td><td>${money(a.profit)}</td><td>${money(a.loss,false,'loss')}</td><td>${money(a.net,true)}</td><td>${pct(share)}${a.goal80?' ✓':''}</td><td>${ratio==null?'—':ratio.toFixed(2)}</td><td>${a.trades}</td><td>${pct(a.win_rate??(a.trades?a.wins/a.trades:null))}</td><td>${money(a.trades?a.net/a.trades:null,true)}</td><td>${money(a.fees,false,'fee')}</td></tr>`;}).join('')}</tbody></table></div>`;}

/**
 * 機能: 上部の固定代表と基準比較を更新する。
 * @returns {void} 返り値なし。
 */
function designComparison(){const s=document.getElementById('comparison-symbol').value,p=document.getElementById('comparison-period').value;document.getElementById('design-comparison').innerHTML=table([D.benchmark,...D.methods].map(x=>({label:esc(x.title)+`<br><span class="id">${esc(x.id)}</span>`,a:x.periods[p]?.[s],total:x.id===D.benchmark.id})));}

/**
 * 機能: 売買図の選択方式を返す。
 * @param {object} m - 主代表。
 * @param {object} state - 現在の操作状態。
 * @returns {object} 台帳付き条件。
 */
function variant(m,state){return state.variant===D.benchmark.id?D.benchmark:m.controls.find(x=>x.id===state.variant)??m;}

/**
 * 機能: 五分足と初回・追加・全返済の全注文をSVGへ変換する。
 * @param {object} m - 台帳付き条件。
 * @param {object} state - 商品と場の操作状態。
 * @returns {string} 売買図のSVG。
 */
function chart(m,state){const key=state.session+'|'+state.symbol,candles=D.bars[key]??[],orders=m.orders[key]??[];if(!candles.length)return '<div class="empty">五分足なし</div>';const W=1180,H=390,L=67,R=16,T=18,B=43,prices=[...candles.flatMap(x=>[x[2],x[3]]),...orders.map(o=>o[5])],low=Math.min(...prices),high=Math.max(...prices),pad=Math.max((high-low)*.08,state.symbol==='TOPIX'?.5:5),ymin=low-pad,ymax=high+pad,first=Math.min(candles[0][0],...(orders.length?orders.map(o=>o[11]):[candles[0][0]])),last=Math.max(candles.at(-1)[0]+300,...(orders.length?orders.map(o=>o[11]):[candles.at(-1)[0]+300])),X=t=>L+(t-first)/(last-first)*(W-L-R),Y=p=>T+(ymax-p)/(ymax-ymin)*(H-T-B);let shapes='';
// ----------------------------------------
// 時刻と価格の目盛りを、全注文を含む同じ座標へ配置する。
for(let i=0;i<=5;i++){const p=ymin+(ymax-ymin)*i/5,y=Y(p);shapes+=`<line x1="${L}" x2="${W-R}" y1="${y}" y2="${y}" stroke="#294158"/><text x="${L-8}" y="${y+4}" fill="#b4c8dd" text-anchor="end" font-size="12">${p.toFixed(state.symbol==='TOPIX'?1:0)}</text>`;}for(let i=0;i<=6;i++){const t=first+(last-first)*i/6,x=X(t);shapes+=`<line x1="${x}" x2="${x}" y1="${T}" y2="${H-B}" stroke="#1e344a"/><text x="${x}" y="${H-14}" fill="#b4c8dd" text-anchor="middle" font-size="12">${SHORT.format(t*1000)}</text>`;}
// ----------------------------------------
// 五分足の四本値と全約定を描き、初回と追加も別注文として残す。
const bw=Math.min(8,(W-L-R)*200/(last-first));for(const c of candles){const x=X(c[0]+150),color=c[4]>=c[1]?'#77e0b5':'#ff929f';shapes+=`<line x1="${x}" x2="${x}" y1="${Y(c[2])}" y2="${Y(c[3])}" stroke="${color}"/><rect x="${x-bw/2}" y="${Math.min(Y(c[1]),Y(c[4]))}" width="${bw}" height="${Math.max(1,Math.abs(Y(c[1])-Y(c[4])))}" fill="${color}"/>`;}orders.forEach((o,i)=>{const x=X(o[11]),y=Y(o[5]),color=o[3]===1?'#70daff':'#ff929f',stroke=o[6]===11?'#ffd082':'#09111b',shape=o[7]===1?`<circle cx="${x}" cy="${y}" r="5.5" fill="${color}" stroke="${stroke}" stroke-width="2"/>`:`<path d="M${x},${y-6}L${x+6},${y}L${x},${y+6}L${x-6},${y}Z" fill="${color}" stroke="${stroke}" stroke-width="1.5"/>`;shapes+=`<g class="order-marker" data-order-index="${i}" data-reason="${o[6]}" data-new="${o[7]}">${shape}<title>${esc(CLOCK.format(o[11]*1000)+' '+(o[7]?'新規':'返済')+' '+(o[3]===1?'買い':'売り')+' '+o[4]+'枚 @'+o[5]+' '+REASONS[o[6]])}</title></g>`;});return `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(sessionName(state.session)+' '+NAMES[state.symbol]+' 五分足と全注文')}">${shapes}</svg>`;}

/**
 * 機能: 追加も含む全注文と判断・約定時刻・料金を表示する。
 * @param {object} m - 台帳付き方式。
 * @param {object} state - 商品と場の操作状態。
 * @returns {string} 注文履歴のHTML。
 */
function history(m,state){const key=state.session+'|'+state.symbol,orders=m.orders[key]??[];return `<div class="table-wrap history"><table class="history-table"><thead><tr><th>約定時刻</th><th>判断時刻</th><th>組</th><th>注文</th><th>売買</th><th>枚数</th><th>価格</th><th>理由</th><th>注文料金</th><th>全返済の組収支</th></tr></thead><tbody>${orders.map((o,i)=>`<tr data-order-index="${i}"><td>${CLOCK.format(o[11]*1000)}</td><td>${CLOCK.format(m.decisionTimes[key][i]*1000)}</td><td>${o[2]}</td><td>${o[7]?(o[6]===11?'追加新規':'初回新規'):'全返済'}</td><td>${o[3]===1?'＋ 買い':'− 売り'}</td><td>${o[4]}</td><td>${o[5].toFixed(state.symbol==='TOPIX'?1:0)}</td><td>${esc(REASONS[o[6]]??o[6])}</td><td>${money(o[8],false,'fee')}</td><td>${money(m.orderNet[key][i],true)}</td></tr>`).join('')}</tbody></table>${orders.length?'':'<div class="empty">取引なし</div>'}</div>`;}

/**
 * 機能: 建値明細と一組会計を分ける補足表を作る。
 * @param {object} a - 選択期間の会計。
 * @returns {string} リスクと枚数表のHTML。
 */
function details(a){return `<div class="table-wrap"><table class="detail-table-inner"><thead><tr><th>勝ち枚数</th><th>負け枚数</th><th>初回・追加建値数</th><th>追加回数</th><th>最大買い／売り</th><th>一組最大負け</th><th>最大時価下落</th><th>最大黒字場除外収支</th><th>同利益割合</th><th>組利益／組損失</th></tr></thead><tbody><tr><td>${a.winning_lots}</td><td>${a.losing_lots}</td><td>${a.legs}</td><td>${a.adds}</td><td>${a.max_long}／${a.max_short}</td><td>${money(a.max_trade_loss,false,'loss')}</td><td>${money(a.drawdown,false,'loss')}</td><td>${money(a.without_best_session,true)}</td><td>${pct(a.without_best_profit_share)}</td><td>${money(a.campaign_profit)}／${money(a.campaign_loss,false,'loss')}</td></tr></tbody></table></div>`;}

/**
 * 機能: 初回と二回の追加を建値別に表示する。
 * @param {Array<object>} rows - 三建値の損益。
 * @returns {string} 相殺前の建値別表HTML。
 */
function partsTable(rows){return `<div class="table-wrap"><table class="parts-table"><thead><tr><th>建値</th><th>利益</th><th>損失</th><th>収支</th><th>建値数</th><th>決済枚数</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${['初回','追加1','追加2'][r.stage]}</td><td>${money(r.profit)}</td><td>${money(r.loss,false,'loss')}</td><td>${money(r.net,true)}</td><td>${r.legs}</td><td>${r.lots}</td></tr>`).join('')}</tbody></table></div>`;}

/**
 * 機能: 固定代表の章と操作イベントを作る。
 * @param {object} m - 台帳付き代表。
 * @param {number} i - 章番号。
 * @returns {HTMLElement} 章の要素。
 */
function build(m,i){const e=document.createElement('section');e.className='method';e.id='method-'+i;e.dataset.methodId=m.id;e.innerHTML=`<h2>${i+1}. ${esc(m.title)}</h2><div class="id">${esc(m.id)}</div><p class="small">${esc(m.configText)}。</p><div class="steps">${[['入口','entry'],['途中','middle'],['出口','exit']].map(([n,k])=>`<div class="step"><strong>${n}</strong><p>${esc(m.steps[k])}</p></div>`).join('')}</div><p class="finding small">${esc(m.finding)}</p><div class="controls symbol-switch">${['TOPIX','NK225'].map(s=>`<button data-symbol="${s}" aria-pressed="${s==='TOPIX'}">${NAMES[s]}</button>`).join('')}<label>期間 <select class="period-select">${PERIODS.map(p=>`<option${p==='全30'?' selected':''}>${p}</option>`).join('')}</select></label></div><div class="comparison"></div><details><summary>同じ入口・初期幅・期限でP1〜5と全量／段階追加を比較</summary><div class="management-comparison"></div><p class="small">P2の追従幅は初期幅、他は倍幅。数量・出口の変更で後続の売買機会も変わるため、同一取引だけの比較ではありません。</p></details><details class="sessions-details"><summary>全30セッションの利益・損失・収支</summary><div class="session-table"></div></details><details><summary>週合計と全30合計</summary><div class="week-table"></div></details><details><summary>初回・追加の損失、勝ち負け枚数と最大損失</summary><div class="parts"></div><div class="detail-table"></div><div class="exit-reasons"></div></details><details><summary>同じ固定代表の情報遅延1／5／15秒感度（既往29のみ）</summary><div class="delay-table"></div></details><h3>五分足と全売買</h3><div class="controls"><label>図の方式 <select class="variant-select">${m.controls.map(x=>`<option value="${esc(x.id)}"${x.id===m.id?' selected':''}>${esc(manager(x.config))}</option>`).join('')}${m.controls.some(x=>x.id===D.benchmark.id)?'':`<option value="${esc(D.benchmark.id)}">従来J1基準</option>`}</select></label><label>場 <select class="session-select">${D.sessions.map(s=>`<option value="${s}">${esc(sessionName(s))}</option>`).join('')}</select></label></div><div class="chart-title"></div><div class="legend"><span>丸＝初回・追加、菱形＝全返済</span><span style="color:var(--cyan)">青＝買い</span><span style="color:var(--red)">桃＝売り</span><span style="color:var(--amber)">黄輪郭＝追加</span></div><div class="chart-box"><div class="chart"></div></div><div class="order-history"></div>`;STATE.set(m.id,{symbol:'TOPIX',period:'全30',variant:m.id,session:D.sessions[0]});e.querySelectorAll('[data-symbol]').forEach(b=>b.addEventListener('click',()=>{STATE.get(m.id).symbol=b.dataset.symbol;render(e,m);}));for(const [cls,key] of [['period-select','period'],['variant-select','variant'],['session-select','session']])e.querySelector('.'+cls).addEventListener('change',ev=>{STATE.get(m.id)[key]=ev.target.value;render(e,m);});return e;}

/**
 * 機能: 章の金額・対照・全場・週・追加玉・売買図を更新する。
 * @param {HTMLElement} e - 主章。
 * @param {object} m - 固定代表。
 * @returns {void} 返り値なし。
 */
function render(e,m){const state=STATE.get(m.id),s=state.symbol,p=state.period,a=m.periods[p][s],v=variant(m,state);e.querySelectorAll('[data-symbol]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.symbol===s)));e.querySelector('.period-select').value=p;e.querySelector('.variant-select').value=state.variant;e.querySelector('.session-select').value=state.session;e.querySelector('.comparison').innerHTML=table([{label:'現方式',a,total:true},{label:'従来J1基準',a:D.benchmark.periods[p][s]}]);e.querySelector('.management-comparison').innerHTML=table(m.controls.map(x=>({label:esc(manager(x.config))+`<br><span class="id">${esc(x.id)}</span>`,a:x.periods[p][s],total:x.id===m.id})));e.querySelector('.session-table').innerHTML=table([...D.sessions.map(session=>({label:`<button class="session-link" data-session="${session}">${esc(sessionName(session))}</button>`,a:m.rows.find(r=>r.session===session&&r.symbol===s)})),{label:'全30合計',a:m.periods.全30[s],total:true}]);e.querySelectorAll('[data-session]').forEach(b=>b.addEventListener('click',()=>{state.session=b.dataset.session;state.variant=m.id;render(e,m);}));e.querySelector('.week-table').innerHTML=table([...m.weeks[s].map(a=>({label:esc(a.label),a})),{label:'全30合計',a:m.periods.全30[s],total:true}]);e.querySelector('.parts').innerHTML=partsTable(m.parts[p][s]);e.querySelector('.detail-table').innerHTML=details(a);e.querySelector('.exit-reasons').innerHTML=`<div class="table-wrap"><table class="exit-table"><thead><tr><th>返済理由</th><th>利益</th><th>損失</th><th>収支</th><th>組数</th></tr></thead><tbody>${Object.entries(m.exitReasons[p][s]).map(([reason,a])=>`<tr><td>${esc(REASONS[reason])}</td><td>${money(a.profit)}</td><td>${money(a.loss,false,'loss')}</td><td>${money(a.net,true)}</td><td>${a.trades}</td></tr>`).join('')}</tbody></table></div>`;const dp=p==='追加1'||p==='全30'?'全29':p;e.querySelector('.delay-table').innerHTML=`${p!==dp?'<p class="small">未見の遅延感度は未実施のため全29を表示します。</p>':''}`+table(m.sensitivity.map(x=>({label:`情報遅延${x.delay}秒・${dp}`,a:x.periods[dp][s],total:x.delay===5})));e.querySelector('.chart-title').innerHTML=`<span>${esc(sessionName(state.session))} · ${NAMES[s]}</span><span class="id">${esc(v.id)}</span>`;e.querySelector('.chart').innerHTML=chart(v,state);e.querySelector('.order-history').innerHTML=history(v,state);}

// ----------------------------------------
// 固定資料を初期表示し、検査器へ同じ表示関数を公開する。
document.title=D.title;document.getElementById('title').textContent=D.title;document.getElementById('conclusion').innerHTML=D.conclusions.map(x=>`<p>${esc(x)}</p>`).join('');document.getElementById('notes').innerHTML=D.notes.map(n=>`<li>${esc(n)}</li>`).join('');document.getElementById('research').innerHTML=D.research.map(x=>`<li><a href="${esc(x.URL)}">${esc(x.研究)}</a>：${esc(x.根拠と限界)}</li>`).join('');document.getElementById('all-link').href=D.allUrl;document.getElementById('nav').innerHTML=D.methods.map((m,i)=>`<a href="#method-${i}">${i+1}. ${esc(m.config.entry)}</a>`).join('');for(let i=0;i<D.methods.length;i++){const e=build(D.methods[i],i);document.getElementById('methods').append(e);render(e,D.methods[i]);}for(const id of ['comparison-symbol','comparison-period'])document.getElementById(id).addEventListener('change',designComparison);designComparison();window.reportTest={D,STATE,render,build,chart,history,table,variant,designComparison,details,partsTable};

// ----------------------------------------
// 比較対象の存在範囲を表示し、未設定の管理対照を検証済みと見せない。
document.getElementById('mechanisms').innerHTML=D.mechanismNotes.map(x=>`<li>${esc(x)}</li>`).join('');
for(const m of D.methods){if(m.controls.length===1){const e=document.querySelector(`.method[data-method-id="${m.id}"] .management-comparison`).parentElement;e.querySelector('summary').textContent='同条件の対照範囲';e.querySelector('p').textContent='このP0・0.4%幅では管理変更対照は未設定です。上の従来J1基準は同じ出口・幅・期限・枚数・待機で入口だけを変えた比較です。';}}
