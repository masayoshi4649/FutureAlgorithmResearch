"use strict";
const saved=JSON.parse(document.getElementById("saved-data").textContent);
const products=["TOPIX","NK225"], kinds=["Day","Night"];
const byRow=new Map(saved.rows.map(r=>[`${r.key}|${r.session}|${r.symbol}`,r]));
/**
 * 機能: 文字列をHTML表示用へエスケープする。
 * @param {string} value - 表示文字列。
 * @returns {string} 安全なHTML文字列。
 */
function escapeHtml(value){return String(value).replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));}
/**
 * 機能: 円額を符号付き整数へ表示する。
 * @param {number} value - 円額。
 * @returns {string} 桁区切り表示。
 */
function money(value){return (value>0?"+":"")+Math.round(value).toLocaleString("ja-JP");}
/**
 * 機能: 円額のセルを作る。
 * @param {number} value - 円額。
 * @returns {string} 正負色を付けた表セル。
 */
function cell(value){return `<td class="${value>0?"positive":value<0?"negative":""}">${money(value)}</td>`;}
/**
 * 機能: 一商品・指定条件の保存行を集計する。
 * @param {Array<object>} rows - 保存会計行。
 * @returns {object} 合計・黒赤無取引・赤字場の平均/中央値・平均黒字・損失規模。
 */
function stats(rows){
 const nets=rows.map(r=>r.net),wins=nets.filter(v=>v>0).sort((a,b)=>b-a);
 const losses=nets.filter(v=>v<0).map(v=>-v).sort((a,b)=>a-b),middle=Math.floor(losses.length/2);
 const sum=field=>rows.reduce((v,r)=>v+r[field],0);
 return {sessions:rows.length,profit:sum("profit"),loss:sum("loss"),net:sum("net"),
  black:nets.filter(v=>v>0).length,red:nets.filter(v=>v<0).length,
  empty:rows.filter(r=>r.entries===0).length,
  breakeven:rows.filter(r=>r.entries>0&&r.net===0).length,
  mean_loss:losses.length?losses.reduce((a,b)=>a+b,0)/losses.length:0,
  median_loss:losses.length?(losses.length%2?losses[middle]:(losses[middle-1]+losses[middle])/2):0,
  mean_win:wins.length?wins.reduce((a,b)=>a+b,0)/wins.length:0,
  entries:sum("entries"),maximum_loss:Math.max(0,-Math.min(0,...nets)),
  without_top3:sum("net")-wins.slice(0,3).reduce((a,b)=>a+b,0)};
}
/**
 * 機能: 商品・区分の現在選択を返す。
 * @param {string} kind - Day又はNight。
 * @param {string} product - TOPIX又はNK225。
 * @returns {string} 巡と条件の識別子。
 */
function chosen(kind,product){return document.getElementById(`${kind}-${product}`).value;}
/**
 * 機能: 選択済みの会計行を返す。
 * @param {string} product - 商品名。
 * @param {string|null} kind - 区分。nullは昼夜両方。
 * @returns {Array<object>} 保存行。
 */
function selected(product,kind=null){return saved.rows.filter(r=>r.symbol===product&&(!kind||r.kind===kind)&&r.key===chosen(r.kind,product));}
/**
 * 機能: 黒字・赤字・無取引と取引後ゼロを表示する。
 * @param {object} value - 集計結果。
 * @returns {string} 件数表示。
 */
function counts(value){return `${value.black}／${value.red}／${value.empty}`+(value.breakeven?`（取引後ゼロ${value.breakeven}）`:"");}
/**
 * 機能: 実際の買い・売り最大枚数を、純枚数と相殺せず表示する。
 * @param {Array<object>} rows - 選択した保存行。
 * @returns {string} 買い／売り枚数。旧資料に列がない場合は未集計。
 */
function maximumPositions(rows){
 if(!rows.length||rows.some(r=>r.max_long==null||r.max_short==null))return "未集計";
 return `${Math.max(...rows.map(r=>r.max_long))}／${Math.max(...rows.map(r=>r.max_short))}枚`;
}
/**
 * 機能: 選択した第二巡以降の旧核・追加・合算を全場と昼夜別に表示する。
 * 引数: なし。現在選択された保存行だけを参照する。
 * 返り値: なし。旧核・追加の内訳がない選択では内訳欄を隠す。
 */
function showComponents(){
 const lines=[];
 for(const kind of [null,...kinds])for(const product of products){
  const all=selected(product,kind),rows=all.filter(r=>r.components);
  if(!rows.length)continue;
  const component=part=>rows.reduce((v,r)=>v+r.components[part].net,0);
  const core=component("旧核"),extra=component("追加"),net=rows.reduce((v,r)=>v+r.net,0);
  const entries=rows.reduce((v,r)=>v+r.components["追加"].entries,0);
  const label=(kind===null?"昼夜":kind==="Day"?"日中":"夜間")+" "+product;
  lines.push(`<tr><td>${label}</td><td>${rows.length}／${all.length}場</td>${cell(core)}${cell(extra)}${cell(net)}${cell(net-core)}<td>${entries}</td><td>${maximumPositions(rows)}</td></tr>`);
 }
 document.getElementById("component-panel").hidden=lines.length===0;
 document.getElementById("component-body").innerHTML=lines.join("");
}
/**
 * 機能: 保存会計から全セッションと累計、短い要約を更新する。
 * 引数: なし。四つの選択値を参照する。
 * 返り値: なし。表示のみを変更する。
 */
function update(){
 const total={TOPIX:[0,0,0],NK225:[0,0,0]},missing=[];
 document.getElementById("allocation-note").textContent=kinds.flatMap(kind=>products.map(product=>{
  const rows=selected(product,kind),allocations=[...new Set(rows.map(r=>r.allocation))];
  return `${kind==="Day"?"日中":"夜間"} ${product}：${allocations.join("／")}`;
 })).join("。 ");
 document.getElementById("session-body").innerHTML=saved.sessions.map(scene=>{
  const kind=scene.endsWith("_Day")?"Day":"Night";
  let line=`<tr data-session="${escapeHtml(scene)}"><td>${escapeHtml(scene.replace("_Day"," デイ").replace("_Night"," ナイト"))}</td>`;
  for(const product of products){
   const row=byRow.get(`${chosen(kind,product)}|${scene}|${product}`);
   if(!row){missing.push(scene+" "+product);line+='<td class="missing" colspan="4">未収録</td>';continue;}
   total[product][0]+=row.profit;total[product][1]+=row.loss;total[product][2]+=row.net;
   line+=cell(row.profit)+cell(-row.loss)+cell(row.net)+cell(total[product][2]);
  }
  return line+"</tr>";
 }).join("");
 document.getElementById("session-total").innerHTML=`<tr><td>${saved.sessions.length}場 累計</td>`+
  products.map(p=>{const s=total[p];return cell(s[0])+cell(-s[1])+cell(s[2])+cell(s[2]);}).join("")+"</tr>";
 const warning=document.getElementById("missing-warning");warning.hidden=missing.length===0;
 warning.textContent=missing.length?`選択した条件に未収録が${missing.length}商品場あります。累計は収録済みだけで、0円補完していません。`:"";
 document.getElementById("selected-summary").innerHTML=products.map(product=>{
  const s=stats(selected(product)),name=product==="TOPIX"?"TOPIXミニ":"日経マイクロ";
  return `<article><h2>${name}・昼夜合計</h2><div class="metrics"><div><span>収支</span><b class="${s.net<0?"negative":"positive"}">${money(s.net)}円</b></div><div><span>黒／赤／無取引</span><b>${counts(s)}</b></div><div><span>赤字平均</span><b>${money(-s.mean_loss)}円</b></div><div><span>赤字中央値</span><b>${money(-s.median_loss)}円</b></div><div><span>最大赤字</span><b>${money(-s.maximum_loss)}円</b></div><div><span>平均黒字</span><b>${money(s.mean_win)}円</b></div><div><span>上位3黒字除外</span><b>${money(s.without_top3)}円</b></div></div><p class="count">収録${s.sessions}場／新規${s.entries}回</p></article>`;
 }).join("");
 document.getElementById("split-body").innerHTML=kinds.flatMap(kind=>products.map(product=>{
  const key=chosen(kind,product),s=stats(selected(product,kind));
  const rows=selected(product,kind),cap=Math.max(...rows.map(r=>r.position_cap));
  return `<tr><td>${kind==="Day"?"日中":"夜間"} ${product}</td><td>${escapeHtml(key)}</td>${cell(s.net)}<td>${counts(s)}</td>${cell(-s.mean_loss)}${cell(-s.median_loss)}${cell(-s.maximum_loss)}${cell(s.mean_win)}${cell(s.without_top3)}<td>${s.entries}</td><td>${cap}枚</td><td>${maximumPositions(rows)}</td></tr>`;
 })).join("");
 showComponents();
}
/**
 * 機能: 全候補の保存会計を区分・商品別に表示する。
 * 引数: なし。saved.rowsを参照する。
 * 返り値: なし。比較表だけを作る。
 */
function showComparisons(){
 const groups=new Map();
 for(const row of saved.rows){const key=`${row.key}|${row.kind}|${row.symbol}`;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
 document.getElementById("comparison-body").innerHTML=[...groups.values()].map(rows=>{
  const first=rows[0],s=stats(rows);
  return `<tr><td>${escapeHtml(first.key)}</td><td>${first.kind==="Day"?"日中":"夜間"}</td><td>${first.symbol}</td>${cell(s.net)}<td>${counts(s)}</td>${cell(-s.mean_loss)}${cell(-s.median_loss)}${cell(-s.maximum_loss)}${cell(s.mean_win)}${cell(s.without_top3)}<td>${s.entries}</td><td>${first.position_cap}枚</td><td>${maximumPositions(rows)}</td></tr>`;
 }).join("");
 const list=document.createElement("ul");
 for(const source of saved.reads){
  const item=document.createElement("li"),link=document.createElement("a");
  link.href="../../"+source.path;link.textContent=source.path;item.append(link);
  const digest=document.createElement("small");digest.textContent=" / SHA256 "+source.sha256;
  item.append(digest);list.append(item);
 }
 document.getElementById("source-links").append(list);
}
for(const kind of kinds)for(const product of products)document.getElementById(`${kind}-${product}`).addEventListener("change",update);
showComparisons();update();
