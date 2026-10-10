
const DATA=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);
/**
 * HTMLへ表示する文字をエスケープする。
 * @param {unknown} value - 表示する値。
 * @returns {string} 安全な文字列。
 */
function esc(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/**
 * 参考円額へ選択倍率を掛け、万円表示する。
 * @param {number} value - 基準円額。
 * @returns {string} 換算後の万円表示。
 */
function money(value){const n=value*Number($('factor').value);return (n>0?'＋':n<0?'−':'')+(Math.abs(n)/10000).toLocaleString('ja-JP',{maximumFractionDigits:2})+'万円';}
/**
 * 金額と仮想枚数のセルを作る。
 * @param {number} value - 基準円額。
 * @param {number} units - 返済した仮想枚数、または差引枚数。
 * @returns {string} 表示セルのHTML。
 */
function cell(value,units){return '<td><div class="amount '+(value>0?'profit':value<0?'loss':'flat')+'">'+money(value)+'</div><div class="units">'+units.toLocaleString('ja-JP',{maximumFractionDigits:4})+'枚</div></td>';}
/**
 * １区間の利益・損失・差引を同じ列で表示する。
 * @param {object} row - 正規化した区間集計。
 * @returns {string} 表の１行。
 */
function rowHTML(row){return '<tr><td>'+esc(row.label)+'</td>'+cell(row.profit_yen,row.profit_units)+cell(-row.loss_yen,row.loss_units)+cell(row.net_yen,row.profit_units-row.loss_units)+'</tr>';}
/**
 * 集計行を表へまとめる。
 * @param {object[]} rows - 区間集計の配列。
 * @returns {string} 表HTML。
 */
function table(rows){return '<table><thead><tr><th>区間</th><th>利益（金額／枚数）</th><th>損失（金額／枚数）</th><th>差引（金額／枚数差）</th></tr></thead><tbody>'+rows.map(rowHTML).join('')+'</tbody></table>';}
/**
 * 銘柄に存在する手法だけを選択肢にする。
 * @param {string|undefined} preferred - 引き継ぐ手法ID。
 * @returns {void} 返り値なし。
 */
function updateMethods(preferred){const methods=DATA.methods.filter(m=>m.symbols.includes($('symbol').value));$('method').innerHTML=methods.map(m=>'<option value="'+esc(m.id)+'">'+esc(m.id+' ／ '+m.name)+'</option>').join('');$('method').value=methods.some(m=>m.id===preferred)?preferred:methods[0].id;render();}
/**
 * 選択中の手法について短い説明と全区間の金額・枚数を描画する。
 * @returns {void} 返り値なし。
 */
function render(){const method=DATA.methods.find(m=>m.id===$('method').value),result=DATA.results[method.id+'|'+$('symbol').value];$('method-name').textContent=method.id+' ／ '+method.name;$('description').textContent=method.description.join('\n');$('weekly').innerHTML=table([result.weekly]);$('sessions').innerHTML=table(result.sessions);$('details-body').innerHTML='<p>同値返済：'+result.weekly.flat_units.toLocaleString('ja-JP')+'枚。最大同時保有：買い'+result.max_long+'枚・売り'+result.max_short+'枚・合計'+result.max_gross+'枚。</p><p>金額の換算倍率を変えても仮想枚数は変わりません。負け枚数が多くても、損失を小さくし利益を伸ばせば収支が正になる場合があります。</p><pre>'+esc(method.details||'')+'</pre>';}
// ----------------------------------------
// 選択変更を表示更新へ接続する。価格取得・売買再計算は行わない。
$('symbol').addEventListener('change',()=>updateMethods($('method').value));
$('method').addEventListener('change',render);$('factor').addEventListener('change',render);
updateMethods(DATA.default_method);
