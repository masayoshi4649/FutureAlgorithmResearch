
"use strict";
const DATA = JSON.parse(document.getElementById("embedded-data").textContent);
/**
 * テキストをHTML用にエスケープします。
 * @param {unknown} value - 表示する値。
 * @returns {string} 安全なHTML文字列。
 */
function escapeText(value){return String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));}
/**
 * 方式名を日本語の短い表示へ変換します。
 * @param {string} value - 固定された識別子。
 * @returns {string} 表示名。
 */
function methodLabel(value){return value.replace("logistic_","線形・").replace("lstm_","LSTM・").replace("上昇固定","常時ロング").replace("下降固定","常時ショート").replace("元4ATR","元の4ATR出口").replace("利益保護","利益保護出口");}
/**
 * 円を万円で表示します。
 * @param {number} value - 円単位の金額。
 * @returns {string} 符号付き万円表示。
 */
function money(value){const x=value/10000;return (x>0?"+":"")+Number(x.toFixed(2)).toLocaleString("ja-JP");}
/**
 * セッション名を日本語へ変換します。
 * @param {string} value - セッション識別子。
 * @returns {string} 短いセッション表示。
 */
function sessionLabel(value){return value.replace("2026-","").replace("_Day"," デイ").replace("_Night"," ナイト");}
/**
 * 表の各セルをエスケープしてHTMLにします。
 * @param {string[]} headers - 列の名前。
 * @param {unknown[][]} rows - 表示する行。
 * @returns {string} 表を包むHTML。
 */
function table(headers,rows){return '<div class="table-wrap"><table><thead><tr>'+headers.map(x=>'<th>'+escapeText(x)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(x=>'<td>'+escapeText(x)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';}
/**
 * 選択した表示期間に存在する方式だけを設定します。
 * @param {boolean} initial - 初回かどうか。
 * @returns {void} 選択肢と結果を更新します。
 */
function setMethods(initial){const period=document.getElementById('period').value;const source=period==='live'?DATA.live:DATA.historical;const select=document.getElementById('method');const previous=select.value;let names=[...new Set(source.map(x=>x['方式']))];names.sort((a,b)=>a==='過去だけで選択'?-1:b==='過去だけで選択'?1:a.localeCompare(b,'ja'));select.innerHTML=names.map(x=>'<option value="'+escapeText(x)+'">'+escapeText(methodLabel(x))+'</option>').join('');select.value=names.includes(previous)?previous:(names.includes('過去だけで選択')?'過去だけで選択':names.includes('機械14/利益保護')?'機械14/利益保護':names[0]);renderProfit();}
/**
 * セッションごとの確定収支を符号付き棒で描きます。
 * @param {Object[]} rows - 選択中の収支行。
 * @returns {void} SVGを更新します。
 */
function renderChart(rows){const svg=document.getElementById('session-chart');const height=Math.max(150,rows.length*38+55);svg.setAttribute('viewBox','0 0 1000 '+height);const max=Math.max(10000,...rows.map(r=>Math.abs(r['収支円'])));let shapes='<text x="15" y="24" font-size="13" fill="#566a79">確定収支（万円）</text><line x1="570" x2="570" y1="36" y2="'+(height-10)+'" stroke="#9eb2c0"/>';rows.forEach((r,i)=>{const y=46+i*38;const width=Math.abs(r['収支円'])/max*300;const x=r['収支円']>=0?570:570-width;shapes+='<text x="15" y="'+(y+17)+'" font-size="14" fill="#172a3a">'+escapeText(sessionLabel(r['セッション'])+' '+r['銘柄'])+'</text><rect x="'+x+'" y="'+y+'" width="'+width+'" height="25" rx="3" fill="'+(r['収支円']>=0?'#28718c':'#b75b52')+'"/><text x="905" y="'+(y+17)+'" font-size="14" fill="#172a3a">'+money(r['収支円'])+'</text>';});svg.innerHTML=shapes;}
/**
 * 方式と期間の選択に対応する確定取引・未返済を表示します。
 * @returns {void} 合計、表、グラフを更新します。
 */
function renderProfit(){const period=document.getElementById('period').value;const method=document.getElementById('method').value;const symbol=document.getElementById('symbol').value;const source=period==='live'?DATA.live:DATA.historical;const rows=source.filter(r=>r['方式']===method&&(symbol==='all'||r['銘柄']===symbol)&&(period!=='test'||DATA.testSessions.includes(r['セッション'])));const fields=['利益円','損失円','収支円','取引数'];document.getElementById('totals').innerHTML=fields.map((f,i)=>{const total=rows.reduce((a,r)=>a+r[f],0);return '<div class="stat"><span>'+['確定利益（万円）','確定損失（万円）','確定収支（万円）','返済済み取引数'][i]+'</span><strong class="'+(i===2?(total>=0?'positive':'negative'):'')+'">'+(i===3?total:money(total))+'</strong></div>';}).join('');const family=method.split('/')[0];document.getElementById('method-description').textContent=family==='過去だけで選択'?'前のセッションまでの結果から、次に使う方式を固定した手順。':DATA.names[family]||'事前固定したモデルまたは方向対照。';let headers=['セッション','銘柄','利益','損失','確定収支','返済件数','費用倍収支'];let values=rows.map(r=>[sessionLabel(r['セッション']),r['銘柄'],money(r['利益円']),money(r['損失円']),money(r['収支円']),r['取引数'],money(r['費用倍収支円'])]);if(period==='live'){headers.push('未返済数','未返済評価損益');values=values.map((v,i)=>v.concat(rows[i]['未返済数'],money(rows[i]['未返済評価損益円'])));}document.getElementById('profit-table').innerHTML=table(headers,values);renderChart(rows);}
/**
 * 固定した予測成績から先行時間と間隔を選んで表示します。
 * @returns {void} 予測の件数・正答率を更新します。
 */
function renderPrediction(){const method=document.getElementById('prediction-method').value;const horizon=Number(document.getElementById('horizon').value);const selected=document.getElementById('spacing').value;const spacing=selected==='nonoverlap'?horizon:5;const rows=DATA.accuracy.filter(r=>r['方式']===method&&r['予測先分']===horizon&&r['標本間隔分']===spacing);const percent=x=>x==null?'—':(100*x).toFixed(1)+'%';document.getElementById('prediction-table').innerHTML=table(['銘柄','評価可能','予測数','横ばい','方向判定','正答','正答率','均衡正答率'],rows.map(r=>[r['銘柄'],r['評価可能'],r['予測数'],r['横ばい数'],r['方向判定数'],r['正答数'],percent(r['正答率']),percent(r['均衡正答率'])]));}
// ----------------------------------------
const predictionMethods=[...new Set(DATA.accuracy.map(x=>x['方式']))];document.getElementById('prediction-method').innerHTML=predictionMethods.map(x=>'<option value="'+escapeText(x)+'">'+escapeText(methodLabel(x))+'</option>').join('');document.getElementById('prediction-method').value='lstm_60';document.getElementById('period').addEventListener('change',()=>setMethods(false));document.getElementById('method').addEventListener('change',renderProfit);document.getElementById('symbol').addEventListener('change',renderProfit);['prediction-method','horizon','spacing'].forEach(id=>document.getElementById(id).addEventListener('change',renderPrediction));setMethods(true);renderPrediction();
