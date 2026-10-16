/**
 * 機能: 保存文字列をHTMLへ安全に表示する。
 * @param {unknown} value 表示する値。
 * @returns {string} エスケープ済みの文字列。
 */
function esc(value){return String(value??'未収録').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

/**
 * 機能: 金額を円単位へ整形し、正負を区別する。
 * @param {number|null} value 金額。
 * @returns {string} 金額のHTML。
 */
function money(value){if(value==null)return '未収録';const n=Math.round(value)||0;return `<span class="${n>0?'positive':n<0?'negative':''}">${n>0?'+':n<0?'−':''}${Math.abs(n).toLocaleString('ja-JP')}</span>`;}

/**
 * 機能: 損失の絶対額を、利益と混同しない赤字・加算符号なしで表示する。
 * @param {number|null} value 損失の正の絶対額。
 * @returns {string} 損失額のHTML。
 */
function loss(value){if(value==null)return '未収録';const n=Math.round(Math.abs(value))||0;return `<span class="${n?'negative':''}">${n.toLocaleString('ja-JP')}</span>`;}

/**
 * 機能: 数値を丸め、欠測を0へ置換せず表示する。
 * @param {number|null} value 数値。
 * @param {number} digits 小数桁数。
 * @returns {string} 数値文字列。
 */
function num(value,digits=1){return value==null?'未収録':Number(value).toLocaleString('ja-JP',{maximumFractionDigits:digits});}

/**
 * 機能: 日本時間とセッション名を短く表示する。
 * @param {string|null} value 日時又はセッション。
 * @returns {string} 表示文字列。
 */
function time(value){return value?esc(value.replace('T',' ').replace('+09:00','').replace('_Day',' デイ').replace('_Night',' ナイト')):'未成立・未収録';}

/**
 * 機能: 一列目以外を右寄せしたスクロール可能な表を作る。
 * @param {string[]} headers 見出し。
 * @param {string[][]} rows HTMLセル行。
 * @returns {string} 表のHTML。
 */
function table(headers,rows){return `<div class="table-wrap"><table><thead><tr>${headers.map(v=>`<th scope="col">${esc(v)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}

/**
 * 機能: 商品内順位と開始日単位の順位を表示する。
 * @returns {void} 返り値なし。
 */
function ranking(){
 const rows=DATA.cases.map(c=>[esc(c.商品表記),`${DATA.worst[c.商品].indexOf(c.セッション)+1}位`,time(c.セッション),money(c.会計.利益円),loss(c.会計.損失円),money(c.会計.収支円),`<a href="#case-${esc(c.ID)}">全${c.取引.length}取引</a>`]);
 document.getElementById('rank-table').innerHTML=table(['商品','赤字順位','セッション','利益','損失','収支','板と注文'],rows);
 document.getElementById('day-table').innerHTML=table(['商品','順位','開始日','デイ＋ナイト収支'],Object.entries(DATA.days).flatMap(([s,days])=>days.map(([d,n],i)=>[esc(s),String(i+1),esc(d),money(n)])));
}

/**
 * 機能: 新規から基準返済までの清算評価額を描く。
 * @param {object} trade 表示取引。
 * @param {object} replay 同じ新規の再生結果。
 * @returns {string} 暗色背景用SVG。
 */
function chart(trade,replay){
 const data=DATA.charts[trade.ID],pts=data.points,w=900,h=225,left=83,right=28,top=28,bottom=42;
 const lo=Math.min(0,...pts.map(p=>p[1])),hi=Math.max(0,...pts.map(p=>p[1]));const span=hi-lo||1,pad=span*.1;
 const x=t=>left+(t-data.start)/Math.max(1,data.end-data.start)*(w-left-right);
 const y=n=>top+(hi+pad-n)/(span+2*pad)*(h-top-bottom);
 let svg=`<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(trade.ID)} 新規後の清算評価損益。将来を使う売買判断ではありません"><line class="zero" x1="${left}" x2="${w-right}" y1="${y(0)}" y2="${y(0)}"/>`;
 for(const n of [lo,0,hi])svg+=`<text x="${left-8}" y="${y(n)+4}" text-anchor="end">${num(n,0)}</text>`;
 let path='';pts.forEach((p,i)=>{path+=`${i===0||p[0]-pts[i-1][0]>30?'M':'L'}${x(p[0]).toFixed(2)},${y(p[1]).toFixed(2)} `;});
 svg+=`<path class="path" d="${path}"/><text x="10" y="17">円</text>`;
 const exit=replay?.変更?.E0_X1?.元新規の対応?.find(r=>r.元組===trade.組番号-1)?.再生;
 if(exit){const t=Date.parse(exit.返済約定)/1000;if(t<=data.end){svg+=`<line class="marker" x1="${x(t)}" x2="${x(t)}" y1="${top}" y2="${h-bottom}"/><text x="${Math.min(w-180,Math.max(left,x(t)+6))}" y="19" style="fill:#f1c471">X1返済 ${esc(exit.返済約定.slice(11,19))}</text>`;}}
 svg+=`<line class="end" x1="${x(data.end)}" x2="${x(data.end)}" y1="${top}" y2="${h-bottom}"/>`;
 for(let i=0;i<=4;i++){const t=data.start+(data.end-data.start)*i/4;const label=new Date(t*1000).toLocaleTimeString('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit'});svg+=`<text x="${x(t)}" y="${h-14}" text-anchor="middle">${label}</text>`;}
 return `<div class="table-wrap">${svg}</svg></div><p class="note">青：基準取引をその時点の返済気配で清算した場合の手数料後評価。黄：X1再生の返済。赤：基準の返済。描画は5秒区間の両極値を残して間引き、30秒超の空白は線を切っています。</p>`;
}

/**
 * 機能: 一取引の入口根拠と注文を時点別に分けて表示する。
 * @param {object} t 取引診断。
 * @param {object} c セッション診断。
 * @returns {string} 取引詳細のHTML。
 */
function tradeDetail(t,c){
 const key=c.セッション+'|'+c.商品,r=DATA.replay[key];
 const sourceRows=['TOPIX','NK225'].map(s=>{const e=t.二市場[s].旧入口,b=e.参照;return [esc(s),time(b.時刻),num(b.bid),num(b.買数量,0),num(b.ask),num(b.売数量,0),num(e.窓15.中値変化bp,2),num(e.窓300.中値変化bp,2),num(b.原本表示行,0)];});
 const gateRows=['TOPIX','NK225'].map(s=>{const e=t.二市場[s].追加J2;return [esc(s),time(e.参照.時刻),num(e.OFI15.比,3),e.OFI15.観測十分===true?'十分':e.OFI15.観測十分===false?'不足':'未収録',e.OFI15.同方向支持===true?'支持':e.OFI15.同方向支持===false?'支持未確認':'未収録',num(e.距離加重数量偏り,3),num(e.直進率300秒,3)];});
 const orderRows=Object.entries(t.時点).map(([name,b])=>[esc(name),time(b.時刻),num(b.価格),num(b.bid),num(b.買数量,0),num(b.ask),num(b.売数量,0),num(b.原本表示行,0)]);
 const compare=['E0_X0','E0_X1','E0_X2','E1_X0','E2_X0','E4_X0','E5_X0'].map(id=>{const n=r.変更[id].元新規の対応.find(a=>a.元組===t.組番号-1)?.再生;return [esc(id),n?time(n.返済判断):'同じ新規なし',n?num(n.返済価格):'—',n?money(n.収支):'—',n?money(n.収支-t.損益.収支円):'—'];});
 const notes=typeof t.コメント==='string'?t.コメント:JSON.stringify(t.コメント);
 const snapshots=Object.entries(t.二市場).map(([s,e])=>{const rows=['過去15秒参照','参照'].map(label=>{const b=e.旧入口[label];return [label==='参照'?'入口の参照板':'15秒窓の始点',time(b.時刻),num(b.bid),num(b.買数量,0),num(b.ask),num(b.売数量,0)];});return `<h4>${esc(s)}：直前からどう変わったか</h4>${table(['時点','参照時計','買気配','買数量','売気配','売数量'],rows)}`;}).join('');
 return `<details class="trade-detail" data-trade="${esc(t.ID)}" ${t.ID===c.代表大負けID?'open':''}><summary>${time(t.時点.発注判断.時刻)} ${esc(t.方向)} → ${money(t.損益.収支円)}円</summary><p class="case-note">${esc(notes)}</p><h4>① その時に見えていた両市場の入口根拠</h4>${table(['市場','参照時計','買気配','買数量','売気配','売数量','15秒変化bp','300秒変化bp','原本行'],sourceRows)}<p class="note">1bp＝0.01%。価格進行は旧入口の15秒格子で参照したもの。板の時刻と発注判断時刻は異なります。</p><details><summary>直前の板との差・追加のJ2判断</summary>${snapshots}${table(['市場','J2参照時計','15秒OFI比','観測','売買方向への支持','距離加重板偏り','300秒直進率'],gateRows)}<p>J2は明確な逆向きOFIを除外します。両市場からの積極的支持は必須ではありません。OFI比・板偏りは正が買い側、負が売り側です。表示数量の減少が約定か取消かは分かりません。</p></details>
 <h4>② 発注判断と約定、その後</h4>${table(['時点','原本の代理時計','売買側価格','買気配','買数量','売気配','売数量','原本行'],orderRows)}<p>保有中の最大清算評価：${money(t.事後.MFE円)}円／最小：${money(t.事後.MAE円)}円。基準の返済理由：${esc(t.返済理由)}。<strong>最大値・最小値は事後診断です。</strong></p>${chart(t,r)}
 <h4>③ 同じ新規に対し、防止策では実際にいつ降りたか</h4>${table(['条件','返済判断','返済価格','取引収支','基準との差'],compare)}<p class="note">「同じ新規なし」は見送り又は他の取引の保有中。損益0と決め付けず、その後の再エントリーを含む全場会計で評価しています。</p><details><summary>元データ・最初の状態変化を確認</summary><pre>${esc(JSON.stringify(t.事後,null,2))}</pre><p>出典：${esc(t.出典)}</p></details></details>`;
}

/**
 * 機能: 赤字6口座の全注文を欠落なく表示する。
 * @returns {void} 返り値なし。
 */
function cases(){
 document.getElementById('case-content').innerHTML=DATA.cases.map(c=>`<article class="case" id="case-${esc(c.ID)}"><h3>${esc(c.商品表記)} · ${time(c.セッション)} <span class="tag">赤字${DATA.worst[c.商品].indexOf(c.セッション)+1}位</span></h3><p>セッション収支 ${money(c.会計.収支円)}円。${esc(c.代表大負けコメント)}</p>${table(['新規判断（日本時間）','方向','新規→返済価格','返済時刻','収支','最大清算評価'],c.取引.map(t=>[time(t.時点.発注判断.時刻),esc(t.方向),`${num(t.時点.新規約定.価格)} → ${num(t.時点.返済約定.価格)}`,time(t.時点.返済約定.時刻),money(t.損益.収支円),money(t.事後.MFE円)]))}${c.取引.map(t=>tradeDetail(t,c)).join('')}</article>`).join('');
}

/**
 * 機能: 主対照の局所成績と全体成績を並べる。
 * @returns {void} 返り値なし。
 */
function headlines(){
 const ids=['E0_X0','E0_X1','E0_X2','E1_X0','E2_X0','E4_X0','E5_X0'];
 document.getElementById('headline-comparison').innerHTML=table(['条件','TOPIX 最悪3','TOPIX 全30','日経 最悪3','日経 全30'],ids.map(id=>{const a=DATA.effects.find(v=>v.id===id);return [esc(id),money(a.期間.赤字上位3.TOPIX.net),money(a.期間.全30.TOPIX.net),money(a.期間.赤字上位3.NK225.net),money(a.期間.全30.NK225.net)];}));
}

/**
 * 機能: 全18条件の利益変化と損失削減を別々に表示する。
 * @returns {void} 返り値なし。
 */
function comparison(){
 const scope=document.getElementById('scope').value;
 document.getElementById('comparison').innerHTML=['TOPIX','NK225'].map(s=>`<h3>${esc(s)} · ${esc(scope)}</h3>${table(['条件','利益','損失','収支','基準比収支','利益変化','損失削減','取引数','金額利益割合','最大時価下落'],DATA.effects.map(v=>{const a=v.期間[scope][s];return [esc(v.id),money(a.profit),loss(a.loss),money(a.net),money(a.収支変化),money(a.利益変化),money(a.損失削減),num(a.trades,0),num(a.profit_share==null?null:a.profit_share*100,2)+'%',num(a.drawdown,0)];}))}`).join('');
 document.getElementById('delays').innerHTML=table(['条件','TOPIX 1秒','5秒','15秒','日経 1秒','5秒','15秒'],DATA.effects.map(v=>[esc(v.id),...['TOPIX','NK225'].flatMap(s=>[1,5,15].map(d=>money(v.遅延[d][s].net)))]));
}

/**
 * 機能: 選択手法の全30場を両商品併記する。
 * @returns {void} 返り値なし。
 */
function sessions(){
 const id=document.getElementById('method').value,result=DATA.results[id];
 const rows=DATA.sessions.map(session=>[time(session),...['TOPIX','NK225'].flatMap(s=>{const a=result.rows.find(r=>r.session===session&&r.symbol===s);return ['profit','loss','net'].map(f=>f==='loss'?loss(a[f]):money(a[f]));})]);
 rows.push(['合計',...['TOPIX','NK225'].flatMap(s=>['profit','loss','net'].map(f=>f==='loss'?loss(result.periods.全30[s][f]):money(result.periods.全30[s][f])))]);
 document.getElementById('session-table').innerHTML=table(['セッション','TOPIX 利益','TOPIX 損失','TOPIX 収支','日経 利益','日経 損失','日経 収支'],rows);
}

// ----------------------------------------
// 初期表示と範囲切替。外部通信を行わず、同梱の会計だけを参照する。
document.getElementById('method').innerHTML=DATA.effects.map(v=>`<option value="${esc(v.id)}">${esc(v.id)}${v.id==='E0_X0'?'（従来J2）':''}</option>`).join('');
document.getElementById('method').addEventListener('change',sessions);
document.getElementById('scope').addEventListener('change',comparison);
ranking();cases();headlines();comparison();sessions();
window.reportTest={data:DATA,sessions,comparison};
