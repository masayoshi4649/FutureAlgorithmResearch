
"use strict";
const DATA=JSON.parse(document.getElementById("research-data").textContent),NS="http://www.w3.org/2000/svg",MINUTE=60000,BOX={left:82,right:1198,top:50,bottom:428};
const el={symbol:document.getElementById("symbol-select"),session:document.getElementById("session-select"),mode:document.getElementById("mode-select"),svg:document.getElementById("price-chart"),tooltip:document.getElementById("chart-tooltip"),wrap:document.getElementById("chart-wrap"),detail:document.getElementById("trade-detail"),title:document.getElementById("chart-title"),table:document.getElementById("all-trades"),protection:document.getElementById("show-protection"),profit:document.getElementById("profit-chart")};
const clock=new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}),calendar=new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",month:"2-digit",day:"2-digit"});
const state={symbol:"NK225",session:"2026-09-23_Day",mode:"fixed_entries",selected:null,start:0,end:1,fullStart:0,fullEnd:1,ymin:0,ymax:1,drag:null};
/**
 * 機能: 数値を日本語の桁区切りで整形する。
 * 引数: value {number} 数値、digits {number} 最大小数桁。
 * 返り値: {string} 整形した数値。
 */
function number(value,digits=1){return Number(value).toLocaleString("ja-JP",{maximumFractionDigits:digits});}
/**
 * 機能: 金額を符号付き万円へ変換する。
 * 引数: value {number} 円。
 * 返り値: {string} 符号付き万円。
 */
function money(value){return (value>0?"+":"")+number(value/10000,2);}
/**
 * 機能: セッション識別子を日本語へ変換する。
 * 引数: value {string} セッション識別子。
 * 返り値: {string} 日本語表示。
 */
function sessionLabel(value){return value.slice(5,10).replace("-","/")+" "+(value.endsWith("Day")?"デイ":"ナイト");}
/**
 * 機能: SVG要素を作成して追加する。
 * 引数: tag {string} 要素名、attrs {object} 属性、text {string|null} 文字、parent {Element} 追加先。
 * 返り値: {SVGElement} 作成要素。
 */
function svg(tag,attrs={},text=null,parent=el.svg){const node=document.createElementNS(NS,tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);if(text!==null)node.textContent=text;parent.appendChild(node);return node;}
/**
 * 機能: 比較中の方式の全取引を得る。
 * 引数: なし。
 * 返り値: {Array<object>} 取引一覧。
 */
function allTrades(){return DATA.methods.baseline.trades.concat(DATA.methods[state.mode].trades);}
/**
 * 機能: 表示対象の取引を絞り込む。
 * 引数: なし。
 * 返り値: {Array<object>} 取引一覧。
 */
function currentTrades(){return allTrades().filter(t=>t.symbol===state.symbol&&t.session===state.session);}
/**
 * 機能: 方式の表示色を得る。
 * 引数: trade {object} 取引。
 * 返り値: {string} 色。
 */
function tradeColor(trade){return trade.method==="baseline"?"#748293":"#006dbc";}
/**
 * 機能: 日時を横座標へ変換する。
 * 引数: time {number} 経過ミリ秒。
 * 返り値: {number} 横座標。
 */
function x(time){return BOX.left+(time-state.start)/(state.end-state.start)*(BOX.right-BOX.left);}
/**
 * 機能: 価格を縦座標へ変換する。
 * 引数: price {number} 価格。
 * 返り値: {number} 縦座標。
 */
function y(price){return BOX.bottom-(price-state.ymin)/(state.ymax-state.ymin)*(BOX.bottom-BOX.top);}
/**
 * 機能: 対象セッション全体へ表示範囲を設定する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function setFullRange(){const bars=DATA.candles[state.symbol+"/"+state.session];state.fullStart=bars[0].t-8*MINUTE;state.fullEnd=Math.max(bars.at(-1).t+5*MINUTE,...currentTrades().map(t=>t.exit_time_ms))+8*MINUTE;state.start=state.fullStart;state.end=state.fullEnd;}
/**
 * 機能: 取引群の利益・損失・収支・利益返却を集計する。
 * 引数: trades {Array<object>} 取引群。
 * 返り値: {object} 円単位の集計。
 */
function aggregate(trades){return trades.reduce((a,t)=>({profit:a.profit+Math.max(0,t.net_yen),loss:a.loss+Math.max(0,-t.net_yen),net:a.net+t.net_yen,giveback:a.giveback+t.giveback_yen,count:a.count+1}),{profit:0,loss:0,net:0,giveback:0,count:0});}
/**
 * 機能: 全体比較の四つの主要数値を更新する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderMetrics(){const trades=currentTrades(),old=aggregate(trades.filter(t=>t.method==="baseline")),next=aggregate(trades.filter(t=>t.method!=="baseline"));document.getElementById("comparison-metrics").innerHTML=`<div class="metric"><small>元の出口・${old.count}取引</small><b class="base-color">${money(old.net)} 万円</b><span>利益 ${number(old.profit/10000,2)} ／ 損失 ${number(old.loss/10000,2)}</span></div><div class="metric"><small>利益保護候補・${next.count}取引</small><b class="new-color">${money(next.net)} 万円</b><span>利益 ${number(next.profit/10000,2)} ／ 損失 ${number(next.loss/10000,2)}</span></div><div class="metric"><small>収支の差</small><b class="${next.net>=old.net?"positive":"negative"}">${money(next.net-old.net)} 万円</b><span>利益保護候補 − 元の出口</span></div><div class="metric"><small>利益返却額の合計</small><b>${number(old.giveback/10000,2)} → ${number(next.giveback/10000,2)}</b><span>万円 ／ 各取引の保有中終値で評価</span></div>`;}
/**
 * 機能: 現在の表示範囲へ五分足、取引、軸を描く。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderChart(){const bars=DATA.candles[state.symbol+"/"+state.session],trades=currentTrades(),visible=bars.filter(b=>b.t>=state.start-5*MINUTE&&b.t<=state.end),values=[];for(const b of visible)values.push(b.low,b.high);for(const t of trades){if(t.entry_time_ms>=state.start&&t.entry_time_ms<=state.end)values.push(t.entry_price);if(t.exit_time_ms>=state.start&&t.exit_time_ms<=state.end)values.push(t.exit_price);}if(!values.length)for(const b of bars)values.push(b.low,b.high);const lo=Math.min(...values),hi=Math.max(...values),pad=Math.max((hi-lo)*.15,state.symbol==="NK225"?30:1.5);state.ymin=lo-pad;state.ymax=hi+pad;el.svg.replaceChildren();hideTooltip();const defs=svg("defs"),clip=svg("clipPath",{id:"plot-clip"},null,defs);svg("rect",{x:BOX.left,y:BOX.top,width:BOX.right-BOX.left,height:BOX.bottom-BOX.top},null,clip);svg("rect",{x:BOX.left,y:BOX.top,width:BOX.right-BOX.left,height:BOX.bottom-BOX.top,fill:"#fbfcfe"});for(let i=0;i<=5;i++){const price=state.ymin+(state.ymax-state.ymin)*i/5,py=y(price);svg("line",{x1:BOX.left,y1:py,x2:BOX.right,y2:py,stroke:"#e5ebf1"});svg("text",{x:BOX.left-12,y:py+4,"text-anchor":"end",fill:"#65768a","font-size":12},number(price,state.symbol==="NK225"?0:1));}const span=(state.end-state.start)/MINUTE,step=span>550?120:span>250?60:span>110?30:span>55?15:5;for(let t=Math.ceil(state.start/(step*MINUTE))*step*MINUTE;t<state.end;t+=step*MINUTE){svg("line",{x1:x(t),y1:BOX.top,x2:x(t),y2:BOX.bottom,stroke:"#e8edf3","stroke-dasharray":"3 4"});svg("text",{x:x(t),y:BOX.bottom+24,"text-anchor":"middle",fill:"#65768a","font-size":12},clock.format(t));if(clock.format(t)==="00:00")svg("text",{x:x(t),y:BOX.bottom+42,"text-anchor":"middle",fill:"#65768a","font-size":11},calendar.format(t));}const layer=svg("g",{"clip-path":"url(#plot-clip)"});const chosen=trades.find(t=>t.id===state.selected);if(chosen)svg("rect",{x:x(chosen.entry_time_ms),y:BOX.top,width:x(chosen.exit_time_ms)-x(chosen.entry_time_ms),height:BOX.bottom-BOX.top,fill:tradeColor(chosen),opacity:.045},null,layer);const bw=Math.max(1.5,Math.min(16,(BOX.right-BOX.left)/(span/5)*.66));for(const b of visible){const color=b.close>=b.open?"#238774":"#cb5b66";svg("line",{x1:x(b.t),y1:y(b.high),x2:x(b.t),y2:y(b.low),stroke:color,"stroke-width":1.2},null,layer);svg("rect",{x:x(b.t)-bw/2,y:Math.min(y(b.open),y(b.close)),width:bw,height:Math.max(1.4,Math.abs(y(b.open)-y(b.close))),fill:color},null,layer);}for(const t of trades)drawTrade(t,layer);svg("text",{x:BOX.left,y:24,fill:"#65768a","font-size":12},"価格（"+(state.symbol==="NK225"?"円":"ポイント")+"） / 確定5分足");svg("line",{id:"crosshair",x1:0,y1:BOX.top,x2:0,y2:BOX.bottom,stroke:"#617b94","stroke-dasharray":"4 3",visibility:"hidden"});el.title.textContent=state.symbol+" ・ "+sessionLabel(state.session);renderMetrics();renderDetail();for(const row of el.table.rows)row.classList.toggle("selected",row.dataset.rowId===state.selected);}
/**
 * 機能: 実際の一分時刻へ新規・返済と有効な保護価格を描く。
 * 引数: t {object} 取引、parent {SVGElement} 描画先。
 * 返り値: {undefined} なし。
 */
function drawTrade(t,parent){const selected=t.id===state.selected,color=tradeColor(t),ex=x(t.entry_time_ms),ey=y(t.entry_price),xx=x(t.exit_time_ms),xy=y(t.exit_price),size=t.method==="baseline"?8:6;svg("line",{x1:ex,y1:ey,x2:xx,y2:xy,stroke:color,"stroke-width":selected?2:1.3,"stroke-dasharray":t.method==="baseline"?"3 4":"7 4",opacity:.8},null,parent);if(el.protection.checked&&t.protection.length){let d="";t.protection.forEach((p,i)=>{d+=(i?"H":"M")+x(p.t)+(i?"V":" ")+y(p.price);});d+="H"+xx;svg("path",{d,fill:"none",stroke:color,"stroke-width":1.4,opacity:.75,"stroke-dasharray":"2 3"},null,parent);}const g=svg("g",{"data-trade-id":t.id,style:"cursor:pointer"},null,parent),points=t.side===1?`${ex},${ey-size} ${ex-size},${ey+size} ${ex+size},${ey+size}`:`${ex},${ey+size} ${ex-size},${ey-size} ${ex+size},${ey-size}`;svg("polygon",{points,fill:t.method==="baseline"?"white":color,stroke:color,"stroke-width":2},null,g);svg("polygon",{points:`${xx},${xy-size} ${xx+size},${xy} ${xx},${xy+size} ${xx-size},${xy}`,fill:color,stroke:"white","stroke-width":2},null,g);svg("title",{},(t.method==="baseline"?"元":"保護候補")+" "+clock.format(t.entry_time_ms)+" "+number(t.entry_price)+" → "+clock.format(t.exit_time_ms)+" "+number(t.exit_price),g);if(selected){drawLabel(ex,ey,(t.side===1?"買い ":"売り ")+clock.format(t.entry_time_ms)+" / "+number(t.entry_price),color,t.side===1?28:-25,parent);drawLabel(xx,xy,(t.method==="baseline"?"元の返済 ":"保護候補の返済 ")+clock.format(t.exit_time_ms)+" / "+number(t.exit_price),color,t.side===1?-26:28,parent);if(t.mfe_yen>0){svg("circle",{cx:x(t.peak.t),cy:y(t.peak.price),r:5,fill:"white",stroke:"#ac7420","stroke-width":2},null,parent);drawLabel(x(t.peak.t),y(t.peak.price),"終値での最大含み益 "+money(t.mfe_yen)+"万円","#ac7420",t.side===1?-28:31,parent);}const pair=currentTrades().find(p=>p.method!==t.method&&p.entry_time_ms===t.entry_time_ms&&p.side===t.side);if(pair)drawLabel(x(pair.exit_time_ms),y(pair.exit_price),(pair.method==="baseline"?"元の返済 ":"保護候補の返済 ")+clock.format(pair.exit_time_ms)+" / "+number(pair.exit_price),tradeColor(pair),t.side===1?32:-32,parent);}}
/**
 * 機能: マーカー付近に背景付き文字を描く。
 * 引数: px/py {number} 座標、label/color {string} 文字・色、offset {number} 上下距離、parent {SVGElement} 描画先。
 * 返り値: {undefined} なし。
 */
function drawLabel(px,py,label,color,offset,parent){const anchor=px>BOX.right-220?"end":px<BOX.left+190?"start":"middle",lx=anchor==="end"?px-10:anchor==="start"?px+10:px;svg("text",{x:lx,y:Math.max(BOX.top+15,Math.min(BOX.bottom-7,py+offset)),"text-anchor":anchor,fill:color,"font-size":12,"font-weight":700,stroke:"white","stroke-width":4,"paint-order":"stroke"},label,parent);}
/**
 * 機能: 選んだ取引の具体的な損益と利益返却を表示する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderDetail(){const t=allTrades().find(v=>v.id===state.selected);if(!t){el.detail.textContent="このセッションに取引はありません。";el.profit.replaceChildren();return;}el.detail.innerHTML=`<div class="metric"><small>${t.method==="baseline"?"元の出口":"利益保護候補"} ／ ${t.side===1?"買い":"売り"}</small><b>${clock.format(t.entry_time_ms)} → ${clock.format(t.exit_time_ms)}</b><span>${number(t.entry_price)} → ${number(t.exit_price)} ／ ${number(t.duration_min,0)}分</span></div><div class="metric"><small>費用控除後の収支</small><b class="${t.net_yen>=0?"positive":"negative"}">${money(t.net_yen)} 万円</b><span>${t.reason}</span></div><div class="metric"><small>保有中の最大含み益</small><b>${money(t.mfe_yen)} 万円</b><span>1分終値・費用控除前</span></div><div class="metric"><small>返済までに戻した利益</small><b class="after">${number(t.giveback_yen/10000,2)} 万円</b><span>最大含み益 − 実現値幅</span></div>`;renderProfit(t);}
/**
 * 機能: 選択取引と同じ入口の比較取引の保有中損益を描く。
 * 引数: selected {object} 選択取引。
 * 返り値: {undefined} なし。
 */
function renderProfit(selected){el.profit.replaceChildren();const pair=currentTrades().find(t=>t.method!==selected.method&&t.entry_time_ms===selected.entry_time_ms&&t.side===selected.side),trades=pair?[selected,pair]:[selected],mult=selected.symbol==="NK225"?.1:1,start=selected.entry_time_ms,end=Math.max(...trades.map(t=>t.exit_time_ms)),values=trades.flatMap(t=>t.holding_path.map(p=>p.points*mult)),low=Math.min(0,...values),high=Math.max(0,...values),pad=Math.max((high-low)*.12,.2),ymin=low-pad,ymax=high+pad,xx=t=>82+(t-start)/Math.max(MINUTE,end-start)*1116,yy=v=>164-(v-ymin)/(ymax-ymin)*128;for(let i=0;i<=3;i++){const v=ymin+(ymax-ymin)*i/3;svg("line",{x1:82,x2:1198,y1:yy(v),y2:yy(v),stroke:"#e5ebf1"},null,el.profit);svg("text",{x:70,y:yy(v)+4,"text-anchor":"end",fill:"#65768a","font-size":11},number(v,1),el.profit);}svg("line",{x1:82,x2:1198,y1:yy(0),y2:yy(0),stroke:"#9fafbe","stroke-dasharray":"3 4"},null,el.profit);svg("text",{x:82,y:18,fill:"#65768a","font-size":12},"選択取引の含み損益（万円・費用控除前）／ 同じ入口がある場合は重ねて表示",el.profit);for(const t of trades){const color=tradeColor(t),d=t.holding_path.map((p,i)=>(i?"L":"M")+xx(p.t)+" "+yy(p.points*mult)).join(" ");svg("path",{d,stroke:color,"stroke-width":t.id===selected.id?2.2:1.6,fill:"none"},null,el.profit);const last=t.holding_path.at(-1);svg("circle",{cx:xx(last.t),cy:yy(last.points*mult),r:4,fill:color},null,el.profit);svg("text",{x:xx(last.t),y:190,"text-anchor":xx(last.t)>1100?"end":"middle",fill:color,"font-size":11},(t.method==="baseline"?"元の返済 ":"保護候補の返済 ")+clock.format(last.t),el.profit);}svg("text",{x:82,y:190,fill:"#65768a","font-size":11},"新規 "+clock.format(start),el.profit);document.getElementById("profit-note").textContent=pair?"利益保護候補の返済後は、その建玉の損益線を延長していません。元の建玉がその後に取り戻した利益も、失った利益も灰色の線で確認できます。":"この取引と同一時刻・方向の元取引はありません。再エントリーのため、単独の保有中損益を表示しています。";}
/**
 * 機能: 全セッションの収支と利益返却を並べる。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderSummary(){let html="";for(const symbol of ["NK225","TOPIX"]){for(const session of [...DATA.sessions,null]){const filter=t=>t.symbol===symbol&&(!session||t.session===session),a=aggregate(DATA.methods.baseline.trades.filter(filter)),b=aggregate(DATA.methods[state.mode].trades.filter(filter));html+=`<tr${session?"":" style='font-weight:700;background:#edf5ff'"}><td>${symbol}</td><td>${session?sessionLabel(session):"合計"}</td><td>${number(a.profit/10000,2)}</td><td>${number(a.loss/10000,2)}</td><td>${money(a.net)}</td><td>${number(b.profit/10000,2)}</td><td>${number(b.loss/10000,2)}</td><td>${money(b.net)}</td><td class="${b.net>=a.net?"positive":"negative"}">${money(b.net-a.net)}</td><td>${number(a.giveback/10000,2)}</td><td>${number(b.giveback/10000,2)}</td></tr>`;}}document.getElementById("session-table").innerHTML=html;}
/**
 * 機能: 比較中の全取引を一覧にする。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderTable(){let html="";const trades=allTrades().sort((a,b)=>a.session.localeCompare(b.session)||a.symbol.localeCompare(b.symbol)||a.entry_time_ms-b.entry_time_ms||a.method.localeCompare(b.method));for(const t of trades)html+=`<tr data-row-id="${t.id}"><td><button class="row-button" data-trade-id="${t.id}">表示 ${t.number}</button></td><td class="${t.method==="baseline"?"base-color":"new-color"}">${t.method==="baseline"?"元の出口":"利益保護候補"}</td><td>${t.symbol}</td><td>${sessionLabel(t.session)}</td><td>${t.side===1?"買い":"売り"}</td><td>${calendar.format(t.entry_time_ms)} ${clock.format(t.entry_time_ms)}</td><td class="number">${number(t.entry_price)}</td><td>${calendar.format(t.exit_time_ms)} ${clock.format(t.exit_time_ms)}</td><td class="number">${number(t.exit_price)}</td><td class="number ${t.net_yen>=0?"positive":"negative"}">${money(t.net_yen)}</td><td class="number">${money(t.mfe_yen)}</td><td class="number">${number(t.giveback_yen/10000,2)}</td><td>${t.reason}</td></tr>`;el.table.innerHTML=html;document.getElementById("trade-list-title").textContent="比較中の全"+trades.length+"取引";}
/**
 * 機能: 親の比較JSONに記載された手法を説明する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderRule(){const m=DATA.methods.selected,rule=m.rule??{},labels={kind:"出口種類",trigger:"保護開始の利益幅",width:"追跡幅",retain:"利益保持率",window:"参照本数",delay:"追加遅延"};const selectionText=DATA.selection.description??DATA.selection.note??"利益を早く確保する効果と、その後の値動きを逃す代償を見るための比較候補です。元方式を上回る手法として採用を推薦するものではありません。";document.getElementById("selection-note").textContent=selectionText;document.getElementById("rule-name").textContent=m.name??"検証結果の利益保護候補";document.getElementById("rule-description").textContent=m.description??Object.entries(rule).map(([k,v])=>(labels[k]??k)+"："+v).join(" ／ ");document.getElementById("mode-note").textContent=state.mode==="fixed_entries"?"入口固定の比較：元の12取引と同じ時刻・価格・方向で入り、返済だけを変更します。早期返済しても追加の新規は行いません。出口単体の効果を見るための比較で、そのまま自動売買の運用成績ではありません。":"運用の比較：新規ルールは同じでも、早期返済によって45分の待機後に再度エントリーできるため、取引数や次の入口は変わります。入口固定の比較と区別して評価してください。";}
/**
 * 機能: セッション・銘柄・比較方法の切替を反映する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function onSelectionChange(){state.symbol=el.symbol.value;state.session=el.session.value;state.mode=el.mode.value;state.selected=currentTrades().find(t=>t.method!=="baseline")?.id??currentTrades()[0]?.id??null;renderRule();renderSummary();renderTable();setFullRange();renderChart();}
/**
 * 機能: マーカーや表の行で取引を選ぶ。
 * 引数: event {Event} クリックイベント。
 * 返り値: {undefined} なし。
 */
function onTradeClick(event){const target=event.target.closest("[data-trade-id]");if(!target)return;state.selected=target.dataset.tradeId;const t=allTrades().find(v=>v.id===state.selected);state.symbol=t.symbol;state.session=t.session;el.symbol.value=state.symbol;el.session.value=state.session;setFullRange();renderChart();}
/**
 * 機能: 表示範囲を保存された時間範囲へ収める。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function clampRange(){if(state.start<state.fullStart){state.end+=state.fullStart-state.start;state.start=state.fullStart;}if(state.end>state.fullEnd){state.start-=state.end-state.fullEnd;state.end=state.fullEnd;}}
/**
 * 機能: 時間軸を拡大・縮小する。
 * 引数: factor {number} 表示幅の倍率。
 * 返り値: {undefined} なし。
 */
function zoom(factor){const center=(state.start+state.end)/2,span=Math.max(30*MINUTE,Math.min(state.fullEnd-state.fullStart,(state.end-state.start)*factor));state.start=center-span/2;state.end=center+span/2;clampRange();renderChart();}
/**
 * 機能: 選択取引の入口から、元の返済または改善返済の後まで表示する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function viewTrade(){const t=allTrades().find(v=>v.id===state.selected);if(!t)return;const pair=currentTrades().find(p=>p.method!==t.method&&p.entry_time_ms===t.entry_time_ms&&p.side===t.side),last=Math.max(t.exit_time_ms,pair?.exit_time_ms??t.exit_time_ms);state.start=Math.max(state.fullStart,t.entry_time_ms-20*MINUTE);state.end=Math.min(state.fullEnd,last+60*MINUTE);renderChart();}
/**
 * 機能: ブラウザー座標をSVG座標へ変換する。
 * 引数: event {PointerEvent} 操作イベント。
 * 返り値: {DOMPoint} SVG座標。
 */
function pointerPosition(event){return new DOMPoint(event.clientX,event.clientY).matrixTransform(el.svg.getScreenCTM().inverse());}
/**
 * 機能: チャート移動の開始位置を記憶する。
 * 引数: event {PointerEvent} 押下イベント。
 * 返り値: {undefined} なし。
 */
function onPointerDown(event){if(event.button!==0||event.target.closest("[data-trade-id]"))return;const p=pointerPosition(event);state.drag={x:p.x,start:state.start,end:state.end};el.svg.setPointerCapture(event.pointerId);}
/**
 * 機能: チャートを移動するか、五分足の値を表示する。
 * 引数: event {PointerEvent} 移動イベント。
 * 返り値: {undefined} なし。
 */
function onPointerMove(event){const p=pointerPosition(event);if(state.drag){const offset=(p.x-state.drag.x)/(BOX.right-BOX.left)*(state.drag.end-state.drag.start);state.start=state.drag.start-offset;state.end=state.drag.end-offset;clampRange();renderChart();return;}if(p.x<BOX.left||p.x>BOX.right||p.y<BOX.top||p.y>BOX.bottom){hideTooltip();return;}const time=state.start+(p.x-BOX.left)/(BOX.right-BOX.left)*(state.end-state.start),bars=DATA.candles[state.symbol+"/"+state.session];let near=bars[0];for(const b of bars)if(Math.abs(b.t-time)<Math.abs(near.t-time))near=b;if(Math.abs(near.t-time)>5*MINUTE){hideTooltip();return;}const line=document.getElementById("crosshair");line.setAttribute("x1",x(near.t));line.setAttribute("x2",x(near.t));line.setAttribute("visibility","visible");el.tooltip.innerHTML=`${calendar.format(near.t)} <b>${clock.format(near.t)}〜${clock.format(near.t+5*MINUTE)}</b><br>始値 ${number(near.open)}　高値 ${number(near.high)}<br>安値 ${number(near.low)}　終値 ${number(near.close)}<br>出来高 ${number(near.volume,0)}`;el.tooltip.classList.remove("hidden");const r=el.wrap.getBoundingClientRect();el.tooltip.style.left=Math.max(0,Math.min(r.width-el.tooltip.offsetWidth-4,event.clientX-r.left+15))+"px";el.tooltip.style.top=Math.max(0,event.clientY-r.top-el.tooltip.offsetHeight-12)+"px";}
/**
 * 機能: チャート移動を終了する。
 * 引数: event {PointerEvent} 解放イベント。
 * 返り値: {undefined} なし。
 */
function onPointerUp(event){state.drag=null;if(el.svg.hasPointerCapture(event.pointerId))el.svg.releasePointerCapture(event.pointerId);}
/**
 * 機能: 五分足の情報表示を隠す。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function hideTooltip(){el.tooltip.classList.add("hidden");const line=document.getElementById("crosshair");if(line)line.setAttribute("visibility","hidden");}

// ----------------------------------------
// 初期画面を九月二十三日のNK225に設定し、表示の操作を接続する。
for(const session of DATA.sessions){const o=document.createElement("option");o.value=session;o.textContent=sessionLabel(session);el.session.appendChild(o);}el.session.value=state.session;
for(const control of [el.symbol,el.session,el.mode])control.addEventListener("change",onSelectionChange);el.protection.addEventListener("change",renderChart);el.table.addEventListener("click",onTradeClick);el.svg.addEventListener("click",onTradeClick);
document.getElementById("zoom-in").addEventListener("click",()=>zoom(.65));document.getElementById("zoom-out").addEventListener("click",()=>zoom(1/.65));document.getElementById("view-all").addEventListener("click",()=>{setFullRange();renderChart();});document.getElementById("view-trade").addEventListener("click",viewTrade);
el.svg.addEventListener("pointerdown",onPointerDown);el.svg.addEventListener("pointermove",onPointerMove);el.svg.addEventListener("pointerup",onPointerUp);el.svg.addEventListener("pointercancel",onPointerUp);el.svg.addEventListener("pointerleave",hideTooltip);onSelectionChange();
