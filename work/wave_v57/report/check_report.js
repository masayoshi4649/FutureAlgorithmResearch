/**
 * 全条件・全商品・全場の表示関数と主条件固定を検査する。
 *
 * 引数: コマンドライン引数なし。
 * 返り値: なし。検査記録JSONを同フォルダへ保存する。
 * DOM代替による関数検査であり、実ブラウザーの見た目は別途確認する。
 */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const filename=path.resolve(__dirname,'../../../アルゴリズム調査/00054_補充監視3手法の実装とセッション損益/補充監視3手法の説明と損益.html');
const html=fs.readFileSync(filename,'utf8');
const payload=html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const script=html.match(/<script>\s*([\s\S]*?)<\/script>/)[1],data=JSON.parse(payload),nodes=new Map();
/**
 * 検査用の要素を取得する。
 * @param {string} id 要素ID。
 * @returns {Object} 値と表示HTMLを持つ代替要素。
 */
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',textContent:id==='data'?payload:'',innerHTML:'',addEventListener(){}});return nodes.get(id);}
/**
 * 表の本文を検査用のセル配列へ戻す。
 * @param {string} value 表HTML。
 * @returns {Array[]} セル配列。
 */
function rows(value){return [...value.matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/g)].map(m=>[...m[1].matchAll(/<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/g)].map(c=>c[1].replace(/<[^>]*>/g,'')));}
/**
 * 整形済み会計文字列を数値へ戻す。
 * @param {string} value 会計セル。
 * @returns {number} 数値。
 */
function amount(value){return Number(value.replaceAll(',',''));}
const context=vm.createContext({document:{getElementById:node,addEventListener(){}},console});
vm.runInContext(script,context,{timeout:20000});
let views=0,accounts=0,orders=0,amounts=0;
const fixed=new Map();
for(const f of data.families){
 const primary=data.results.methods.find(m=>m.family===f.id&&m.main);
 assert.equal(node(`condition-${f.id}`).value,primary.id);
 assert.equal(node(`price-${f.id}`).value,'中値');
 const r=rows(node(`primary-sessions-${f.id}`).innerHTML);
 assert.equal(r.length,24);
 for(let i=0;i<23;i++)for(let j=0;j<4;j++){
  const a=primary.accounts.find(a=>a.session===data.results.sessions[i]&&a.symbol===['TOPIX','NK225'][Math.floor(j/2)]);
  assert.equal(amount(r[i+1][j+1]),j%2===0?a.net:a.sensitivity['中値'].net);amounts++;
 }
 fixed.set(f.id,node(`primary-sessions-${f.id}`).innerHTML);
}
for(const m of data.results.methods){
 const family=m.family;
 node(`condition-${family}`).value=m.id;
 for(const symbol of ['TOPIX','NK225']){
 for(const mode of ['中値','売買気配','最後値']){
  node(`symbol-${family}`).value=symbol;node(`price-${family}`).value=mode;context.render(family);views++;
  assert.equal(node(`primary-sessions-${family}`).innerHTML,fixed.get(family));
  assert.equal(rows(node(`comparison-${family}`).innerHTML).length,5);
  const r=rows(node(`sessions-${family}`).innerHTML),selected=m.accounts.filter(a=>a.symbol===symbol);
  assert.equal(r.length,24);
  for(let i=0;i<selected.length;i++){
   const a=selected[i],v=mode==='最後値'?a:a.sensitivity[mode],expected=[v.profit,v.loss,v.net,v.win_qty,v.loss_qty,v.flat_qty,v.win_qty-v.loss_qty,v.cycles];
   assert.equal(r[i+1][0],a.session);
   for(let j=0;j<expected.length;j++){assert.equal(amount(r[i+1][j+1]),expected[j]);amounts++;}
   if(mode==='最後値'){
    node(`session-${family}`).value=a.session;context.renderOrders(family);
    assert.equal(rows(node(`orders-${family}`).innerHTML).length,a.orders.length+1);accounts++;orders+=a.orders.length;
   }
  }
  const period=rows(node(`periods-${family}`).innerHTML),expectedPeriods=data.periods[m.id][symbol][mode];
  assert.equal(period.length,expectedPeriods.length+1);
  for(let i=0;i<expectedPeriods.length;i++){
   const a=expectedPeriods[i],values=[a.profit,a.loss,a.net,a.win_qty,a.loss_qty,a.flat_qty,a.win_qty-a.loss_qty,a.cycles];
   for(let j=0;j<values.length;j++){assert.equal(amount(period[i+1][j+1]),values[j]);amounts++;}
  }
  const sensitivity=rows(node(`sensitivity-${family}`).innerHTML);
  assert.equal(sensitivity.length,4);
  for(let i=0;i<3;i++)for(let j=0;j<3;j++){
   assert.equal(amount(sensitivity[i+1][j+1]),data.sensitivity[m.id][symbol][i][['profit','loss','net'][j]]);amounts++;
  }
  for(const prefix of ['summary','periods','sessions','sensitivity','orders'])assert(!/NaN|undefined|Infinity/.test(node(`${prefix}-${family}`).innerHTML));
  if(mode!=='最後値')assert(node(`summary-${family}`).innerHTML.includes('—（未算出）'));
 }
 }
}
// ----------------------------------------
// 主条件の表が比較操作で変わらず、全注文と金額が表示されることを記録する。
const result={検査:'合格',表示条件商品数:views,口座数:accounts,全注文数:orders,検算数値:amounts,主条件固定:true,注記:'DOM代替の表示関数検査。実ブラウザー表示は独立検査を参照。'};
fs.writeFileSync(path.join(__dirname,'表示関数監査.json'),JSON.stringify(result,null,2),'utf8');
console.log(JSON.stringify(result));
