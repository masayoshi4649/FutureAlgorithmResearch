/**
 * 公開HTMLそのもののデータ・表示関数を、保存会計へ独立照合する。
 * 金融判断、金融核、表示生成スクリプトは呼び出さない。
 */
"use strict";
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const assert=require("node:assert/strict"),crypto=require("node:crypto");
const ROOT=path.resolve(__dirname,"../../.."),TASK=path.join(ROOT,"work/regime131_20261020");
const PUBLIC=path.join(ROOT,"アルゴリズム調査/00131_時間帯と値動き状態を切り替える全場参加");
const HTML=path.join(PUBLIC,"時間帯と値動き状態を切り替える手法の全セッション損益.html");
const FINAL=path.join(TASK,"公開候補の43場統合.json");
const html=fs.readFileSync(HTML,"utf8"),canonical=readJson(FINAL);
const scripts=[...html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)];
const savedText=scripts.find(m=>/\bid="saved-data"/.test(m[1]))[2];
const saved=JSON.parse(savedText),logic=scripts.filter(m=>!/\bid="saved-data"/.test(m[1])).map(m=>m[2]).join("\n");
const products=["TOPIX","NK225"],kinds=["Day","Night"],fields=["profit","loss","net","entries"];
const checkedSources=new Map(),nodes=new Map(),options=new Map(),checks={rows:0,states:0,cell_sets:0,metrics:0};

/**
 * 機能: UTF-8 JSONを読む。
 * @param {string} file - 入力の絶対パス。
 * @returns {object} 解析したデータ。
 */
function readJson(file){return JSON.parse(fs.readFileSync(file,"utf8").replace(/^\uFEFF/,""));}
/**
 * 機能: ファイルのSHA256を計算する。
 * @param {string} file - 入力パス。
 * @returns {string} 16進指紋。
 */
function sha(file){return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");}
/**
 * 機能: 保存値を比較し、失敗位置を明記する。
 * @param {*} actual - 実際の値。
 * @param {*} expected - 独立に算出した値。
 * @param {string} label - 検査名。
 * @returns {void} 不一致なら例外。
 */
function same(actual,expected,label){assert.deepEqual(actual,expected,label);}
/**
 * 機能: 生成元とは別の桁区切り処理で期待表示を作る。
 * @param {number} n - 円額。
 * @returns {string} 符号付きの整数表示。
 */
function yen(n){
 const rounded=Math.round(n);
 return (rounded>0?"+":"")+String(rounded).replace(/\B(?=(\d{3})+(?!\d))/g,",");
}
/**
 * 機能: 表示処理に必要なDOM操作だけを記録する。
 * @param {string} id - 要素識別子。
 * @returns {object} 値・HTML・イベントを保持する試験用要素。
 */
function node(id){return {id,value:"",innerHTML:"",textContent:"",hidden:false,children:[],listeners:{},
 addEventListener(name,callback){this.listeners[name]=callback;},
 append(child){this.children.push(child);}};}
/**
 * 機能: HTMLの行からセル文字列を抜き出す。
 * @param {string} text - テーブル部分のHTML。
 * @returns {Array<Array<string>>} 全行のセル文字列。
 */
function table(text){return [...text.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/g)].map(
 m=>[...m[1].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map(x=>x[1]));}
/**
 * 機能: 金額・黒赤場・赤字の平均と中央値を保存会計から独立集計する。
 * @param {Array<object>} rows - 商品場の保存会計。
 * @returns {object} 表示に使う集計。
 */
function aggregate(rows){
 const net=rows.reduce((a,r)=>a+r.net,0),positives=rows.filter(r=>r.net>0).map(r=>r.net).sort((a,b)=>b-a);
 const negatives=rows.filter(r=>r.net<0).map(r=>-r.net).sort((a,b)=>a-b),n=negatives.length;
 const middle=n?(n%2?negatives[(n-1)/2]:(negatives[n/2-1]+negatives[n/2])/2):0;
 return {net,black:positives.length,red:n,empty:rows.filter(r=>r.entries===0).length,
  breakeven:rows.filter(r=>r.entries>0&&r.net===0).length,mean_loss:n?negatives.reduce((a,b)=>a+b,0)/n:0,
  median_loss:middle,maximum_loss:n?negatives[n-1]:0,
  mean_win:positives.length?positives.reduce((a,b)=>a+b,0)/positives.length:0,
  without_top3:net-positives.slice(0,3).reduce((a,b)=>a+b,0),
  entries:rows.reduce((a,r)=>a+r.entries,0)};
}
/**
 * 機能: 現在の4選択に対応する保存行を選ぶ。
 * @param {string} product - 商品。
 * @param {?string} kind - 昼夜、又は全体。
 * @returns {Array<object>} 選択された保存会計。
 */
function rowsFor(product,kind=null){return saved.rows.filter(r=>r.symbol===product&&(!kind||r.kind===kind)
 &&r.key===nodes.get(`${r.kind}-${product}`).value);}
/**
 * 機能: 黒字・赤字・休止の件数を独立表示する。
 * @param {object} a - 独立集計。
 * @returns {string} 件数表示。
 */
function counts(a){return `${a.black}／${a.red}／${a.empty}`+(a.breakeven?`（取引後ゼロ${a.breakeven}）`:"");}

// ----------------------------------------
// 埋め込み会計を、HTMLとは別に保存された元会計へ全件照合する。
assert.equal(saved.sessions.length,43);
assert.equal(new Set(saved.sessions).size,43);
same([...saved.sessions].sort(),saved.sessions,"場の時系列順");
same(saved.defaults,canonical.selection,"既定選択と公開候補");
for(const r of saved.rows){
 if(!checkedSources.has(r.origin))checkedSources.set(r.origin,readJson(path.join(ROOT,r.origin)));
 const matches=checkedSources.get(r.origin).rows.filter(x=>x.method===r.method&&x.symbol===r.symbol&&x.session===r.session);
 assert.equal(matches.length,1,`元会計の一意性:${r.key}/${r.session}/${r.symbol}`);
 for(const f of fields)assert.equal(r[f],matches[0][f],`保存値:${r.key}/${r.session}/${r.symbol}/${f}`);
 for(const f of ["max_long","max_short","components"])if(r[f]!=null)same(r[f],matches[0][f],`追加欄:${f}`);
 checks.rows++;
}
for(const r of canonical.rows){
 const matches=saved.rows.filter(x=>x.session===r.session&&x.symbol===r.symbol
  &&x.key===canonical.selection[r.kind][r.symbol]);
 assert.equal(matches.length,1);
 for(const f of fields)assert.equal(matches[0][f],r[f],"公開43場統合");
}
assert.equal(canonical.rows.length,86);

// ----------------------------------------
// HTMLの実際の選択肢と、実際に埋め込まれたJSを使って表示する。
for(const match of html.matchAll(/\bid="([^"]+)"/g))nodes.set(match[1],node(match[1]));
nodes.get("saved-data").textContent=savedText;
for(const match of html.matchAll(/<select id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)){
 const opts=[...match[2].matchAll(/<option value="([^"]+)"([^>]*)>([\s\S]*?)<\/option>/g)];
 options.set(match[1],opts.map(o=>o[1]));
 const selected=opts.filter(o=>/\bselected\b/.test(o[2]));
 assert.equal(selected.length,1,"各選択は初期値ひとつ");
 nodes.get(match[1]).value=selected[0][1];
 const [kind,product]=match[1].split("-");
 same(options.get(match[1]),saved.options[kind][product],"HTML選択肢");
 same(selected[0][1],canonical.selection[kind][product],"HTML初期選択");
}
const sandbox={document:{getElementById(id){assert(nodes.has(id),`未知要素:${id}`);return nodes.get(id);},
 createElement(tag){return node(tag);}}};
const context=vm.createContext(sandbox);
vm.runInContext(logic,context,{timeout:10000,filename:HTML});

/**
 * 機能: 現在表示された43行・累計・商品カード・昼夜表を独立照合する。
 * @param {string} label - 選択状態の識別子。
 * @returns {void} 全セルが一致しなければ例外。
 */
function verify(label){
 const rendered=table(nodes.get("session-body").innerHTML);
 assert.equal(rendered.length,43,label);
 const sums={TOPIX:[0,0,0],NK225:[0,0,0]};
 let missing=0;
 for(let i=0;i<saved.sessions.length;i++){
  const session=saved.sessions[i],kind=session.endsWith("_Day")?"Day":"Night";
  const expected=[session.replace("_Day"," デイ").replace("_Night"," ナイト")];
  for(const product of products){
   const records=rowsFor(product,kind).filter(r=>r.session===session);
   if(records.length===0){expected.push("未収録");missing++;continue;}
   assert.equal(records.length,1);const r=records[0];
   sums[product][0]+=r.profit;sums[product][1]+=r.loss;sums[product][2]+=r.net;
   expected.push(yen(r.profit),yen(-r.loss),yen(r.net),yen(sums[product][2]));
   checks.cell_sets++;
  }
  same(rendered[i],expected,`${label}/${session}`);
 }
 const foot=[`${saved.sessions.length}場 累計`];
 for(const product of products)foot.push(yen(sums[product][0]),yen(-sums[product][1]),yen(sums[product][2]),yen(sums[product][2]));
 same(table(nodes.get("session-total").innerHTML),[foot],"累計行");
 same(nodes.get("missing-warning").hidden,missing===0,"未収録の零補完なし");
 const articles=[...nodes.get("selected-summary").innerHTML.matchAll(/<article>([\s\S]*?)<\/article>/g)];
 assert.equal(articles.length,2);
 for(let i=0;i<products.length;i++){
  const a=aggregate(rowsFor(products[i]));
  const metrics=[...articles[i][1].matchAll(/<span>([^<]*)<\/span><b[^>]*>(.*?)<\/b>/g)]
   .map(m=>[m[1],m[2]]);
  const expected=[["収支",yen(a.net)+"円"],["黒／赤／無取引",counts(a)],["赤字平均",yen(-a.mean_loss)+"円"],
   ["赤字中央値",yen(-a.median_loss)+"円"],["最大赤字",yen(-a.maximum_loss)+"円"],
   ["平均黒字",yen(a.mean_win)+"円"],["上位3黒字除外",yen(a.without_top3)+"円"]];
  same(metrics,expected,`${label}/${products[i]}/カード`);checks.metrics+=7;
 }
 const splits=table(nodes.get("split-body").innerHTML);
 assert.equal(splits.length,4);
 let si=0;
 for(const kind of kinds)for(const product of products){
  const rows=rowsFor(product,kind),a=aggregate(rows),maximum=rows.some(r=>r.max_long==null||r.max_short==null)?
   "未集計":`${Math.max(...rows.map(r=>r.max_long))}／${Math.max(...rows.map(r=>r.max_short))}枚`;
  const expected=[`${kind==="Day"?"日中":"夜間"} ${product}`,nodes.get(`${kind}-${product}`).value,
   yen(a.net),counts(a),yen(-a.mean_loss),yen(-a.median_loss),yen(-a.maximum_loss),
   yen(a.mean_win),yen(a.without_top3),String(a.entries),
   `${Math.max(...rows.map(r=>r.position_cap))}枚`,maximum];
  same(splits[si++],expected,"昼夜別表示");
 }
 checks.states++;
}
verify("初期表示");
const initial={};
for(const product of products){
 const a=aggregate(rowsFor(product)),c=canonical.summary[product]["全体"];
 for(const f of ["net","black","red","empty","entries","without_top3"])assert.equal(a[f],c[f],"公開候補累計");
 same(a.mean_loss,c.mean_red,"赤字平均");same(a.mean_win,c.mean_black,"平均黒字");
 initial[product]=a;
}
for(const [id,values] of options){
 const target=nodes.get(id),original=target.value;
 assert.equal(typeof target.listeners.change,"function","選択変更のイベント接続");
 for(const value of values){
  target.value=value;target.listeners.change();verify(`${id}=${value}`);
 }
 target.value=original;target.listeners.change();
}
verify("初期選択へ復帰");

// ----------------------------------------
// 静的リンク・JS生成の出典リンクの実在と、引用ファイル指紋を検査する。
const links=[];
for(const match of html.slice(0,html.indexOf('<script')).matchAll(/\bhref="([^"]+)"/g)){
 if(/^(https?:|#)/.test(match[1]))continue;
 const resolved=path.resolve(PUBLIC,decodeURIComponent(match[1]));
 assert(fs.existsSync(resolved),`静的リンク不存在:${match[1]}`);links.push(match[1]);
}
const sourceLinks=nodes.get("source-links").children[0].children;
assert.equal(sourceLinks.length,saved.reads.length);
for(let i=0;i<saved.reads.length;i++){
 const source=saved.reads[i],link=sourceLinks[i].children[0];
 same(link.href,"../../"+source.path,"生成出典リンク");
 assert.equal(sha(path.resolve(PUBLIC,link.href)),source.sha256,"引用指紋");
 links.push(link.href);
}
assert.equal(fs.readFileSync(HTML,"utf8"),html,"監査中のHTML変更なし");
const proof={passed:true,financial_replays:0,market_API:0,browser_reuse:false,
 method:"公開HTMLから抜いたJSを独立DOM記録器で実行し、元会計・公開43場統合・独立集計へ照合。実画面確認は別担当。",
 checks,initial_selection:canonical.selection,initial_summary:initial,
 presentation_notes:["初回監査で検出した旧W12等の『-0』表示は公開側で修正済み。今回の監査は修正後HTMLを読む。"],
 static_and_generated_links_checked:links.length,links,
 sources:{html:{path:path.relative(ROOT,HTML),sha256:sha(HTML)},
  canonical:{path:path.relative(ROOT,FINAL),sha256:sha(FINAL)},
  checker:{path:path.relative(ROOT,__filename),sha256:sha(__filename)}}};
const target=path.join(__dirname,`公開HTMLの独立データと選択切替監査_${Date.now()}.json`);
fs.writeFileSync(target,JSON.stringify(proof,null,2)+"\n","utf8");
console.log(target,JSON.stringify(checks),"合格");
