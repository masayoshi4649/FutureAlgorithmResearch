"use strict";
const D=JSON.parse(document.getElementById('report-data').textContent),NAMES={TOPIX:'TOPIXミニ10枚',NK225:'日経225マイクロ20枚'},NUMBER=new Intl.NumberFormat('ja-JP',{maximumFractionDigits:0}),CLOCK=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}),SHORT=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});

/**
 * 機能: 表示値をHTMLへ安全に埋め込む。
 * @param {unknown} value - 表示する値。
 * @returns {string} エスケープした文字列。
 */
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

/**
 * 機能: 円金額を符号と色付きで表示する。
 * @param {number|null} value - 円金額。
 * @param {boolean} signed - 正の符号を付けるか。
 * @param {boolean} loss - 損失列か。
 * @returns {string} 金額のHTML。
 */
function money(value,signed=false,loss=false){return value==null?'—':`<span class="money ${loss?'negative':value>0?'positive':value<0?'negative':''}">${signed&&value>0?'+':''}${NUMBER.format(value===0?0:value)}円</span>`;}

/**
 * 機能: 比率を百分率へ変換する。
 * @param {number|null} value - 小数比率。
 * @returns {string} 百分率又は未定義表示。
 */
function pct(value){return value==null?'—':(value*100).toFixed(1)+'%';}

/**
 * 機能: 保存セッション名を短い日本語へ変換する。
 * @param {string} value - セッション識別子。
 * @returns {string} 表示名。
 */
function sessionName(value){return value.replace('_Day',' デイ').replace('_Night',' ナイト');}

/**
 * 機能: 金額会計を同じ定義の列へ表示する。
 * @param {Array<object>} rows - labelと会計aを持つ行。
 * @param {boolean} stability - 場の勝敗・下落も表示するか。
 * @returns {string} 金額表のHTML。
 */
function table(rows,stability=false){return `<div class="table-wrap"><table class="money-table"><thead><tr><th>対象</th><th>利益</th><th>損失</th><th>収支</th><th>金額利益割合</th><th>平均勝ち／負け</th><th>取引数</th>${stability?'<th>黒字／赤字／取引なし場</th><th>最大下落</th>':'<th>勝ち／負け枚数</th>'}</tr></thead><tbody>${rows.map(({label,a,total=false})=>{if(!a)return `<tr><td>${label}</td><td colspan="8">未計算</td></tr>`;const share=a.profit+a.loss?a.profit/(a.profit+a.loss):null,payoff=a.payoff??((a.wins&&a.losses&&a.loss)?(a.profit/a.wins)/(a.loss/a.losses):null);return `<tr${total?' class="total"':''}><td>${label}</td><td>${money(a.profit)}</td><td>${money(a.loss,false,true)}</td><td>${money(a.net,true)}</td><td>${pct(share)}</td><td>${payoff==null?'—':payoff.toFixed(2)+'倍'}</td><td>${a.trades??a.campaigns??0}</td>${stability?`<td>${a.positive_sessions??'—'}／${a.negative_sessions??'—'}／${a.no_trade_sessions??'—'}</td><td>${money(a.drawdown,false,true)}</td>`:`<td>${a.winning_lots??0}／${a.losing_lots??0}</td>`}</tr>`;}).join('')}</tbody></table></div>`;}

/**
 * 機能: 五分足と全注文を同じ座標に描画する。
 * @param {object} method - 台帳付き表示条件。
 * @param {string} symbol - 商品識別子。
 * @param {string} session - セッション識別子。
 * @returns {string} SVG又はデータなし表示。
 */
function chart(method,symbol,session){const key=session+'|'+symbol,candles=D.bars[key]??[],orders=method.orders[key]??[];if(!candles.length)return '<div class="empty">五分足なし</div>';const W=1180,H=390,L=70,R=18,T=18,B=43,prices=[...candles.flatMap(x=>[x[2],x[3]]),...orders.map(o=>o.price)],low=Math.min(...prices),high=Math.max(...prices),pad=Math.max((high-low)*.08,symbol==='TOPIX'?.5:5),ymin=low-pad,ymax=high+pad,first=Math.min(candles[0][0],...(orders.length?orders.map(o=>o.time):[candles[0][0]])),last=Math.max(candles.at(-1)[0]+300,...(orders.length?orders.map(o=>o.time):[candles.at(-1)[0]+300])),X=t=>L+(t-first)/(last-first)*(W-L-R),Y=p=>T+(ymax-p)/(ymax-ymin)*(H-T-B);let shapes='';
// ----------------------------------------
// 保存セッションをJSTで表示し、全注文を目盛範囲へ含める。
for(let i=0;i<=5;i++){const p=ymin+(ymax-ymin)*i/5,y=Y(p);shapes+=`<line x1="${L}" x2="${W-R}" y1="${y}" y2="${y}" stroke="#2c435a"/><text x="${L-8}" y="${y+4}" fill="#b7cce0" text-anchor="end" font-size="12">${p.toFixed(symbol==='TOPIX'?1:0)}</text>`;}for(let i=0;i<=6;i++){const t=first+(last-first)*i/6,x=X(t);shapes+=`<line x1="${x}" x2="${x}" y1="${T}" y2="${H-B}" stroke="#1e344b"/><text x="${x}" y="${H-14}" fill="#b7cce0" text-anchor="middle" font-size="12">${SHORT.format(t*1000)}</text>`;}
// ----------------------------------------
// 足は説明専用、新規は丸、返済は菱形とする。
const bw=Math.min(8,(W-L-R)*200/(last-first));for(const c of candles){const x=X(c[0]+150),color=c[4]>=c[1]?'#7ce0b1':'#ff99a7';shapes+=`<line x1="${x}" x2="${x}" y1="${Y(c[2])}" y2="${Y(c[3])}" stroke="${color}"/><rect x="${x-bw/2}" y="${Math.min(Y(c[1]),Y(c[4]))}" width="${bw}" height="${Math.max(1,Math.abs(Y(c[1])-Y(c[4])))}" fill="${color}"/>`;}orders.forEach((o,i)=>{const x=X(o.time),y=Y(o.price),color=o.side===1?'#79dfff':'#ff99a7',shape=o.isNew?`<circle cx="${x}" cy="${y}" r="5.5" fill="${color}" stroke="#07101c" stroke-width="2"/>`:`<path d="M${x},${y-6}L${x+6},${y}L${x},${y+6}L${x-6},${y}Z" fill="${color}" stroke="#07101c" stroke-width="1.5"/>`;shapes+=`<g class="order-marker" data-order-index="${i}" data-new="${o.isNew?1:0}">${shape}<title>${esc(CLOCK.format(o.time*1000)+' '+(o.isNew?'新規':'返済')+' '+(o.side===1?'買い':'売り')+' '+o.qty+'枚 @'+o.price+' '+o.reason)}</title></g>`;});return `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(sessionName(session)+' '+NAMES[symbol]+' 五分足と全売買')}">${shapes}</svg>`;}

/**
 * 機能: 全注文の判断・約定時刻と手数料後収支を表示する。
 * @param {object} method - 台帳付き表示条件。
 * @param {string} symbol - 商品識別子。
 * @param {string} session - セッション識別子。
 * @returns {string} 注文表のHTML。
 */
function history(method,symbol,session){const orders=method.orders[session+'|'+symbol]??[];return `<div class="table-wrap"><table class="order-table"><thead><tr><th>判断時刻</th><th>約定時刻</th><th>新規／返済</th><th>買売</th><th>枚数</th><th>約定値</th><th>理由</th><th>手数料</th><th>返済収支</th></tr></thead><tbody>${orders.map((o,i)=>`<tr data-order-index="${i}"><td>${CLOCK.format(o.decision*1000)}</td><td>${CLOCK.format(o.time*1000)}</td><td>${o.isNew?'新規':'返済'}</td><td>${o.side===1?'買い':'売り'}</td><td>${o.qty}</td><td>${o.price.toFixed(symbol==='TOPIX'?1:0)}</td><td>${esc(o.reason)}</td><td>${NUMBER.format(o.fee)}円</td><td>${money(o.net,true)}</td></tr>`).join('')}</tbody></table>${orders.length?'':'<div class="empty">取引なし</div>'}</div>`;}
