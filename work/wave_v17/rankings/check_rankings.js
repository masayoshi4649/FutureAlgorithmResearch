/**
 * 保存済みランキングHTMLを原集計と独立順位へ静的照合する。
 * 引数: なし。返り値: なし。ブラウザー・通信・売買再計算は行わない。
 */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),vm=require('node:vm'),crypto=require('node:crypto');
const work=__dirname,base=path.resolve(work,'..'),out=path.resolve(work,'../../../アルゴリズム調査/00012_状態切替と柔軟な建玉管理'),page=path.join(out,'週収支ランキングと両銘柄共通手法.html');
const source=fs.readFileSync(page,'utf8'),dataText=source.match(/<script type="application\/json" id="data">([\s\S]*?)<\/script>/)[1],data=JSON.parse(dataText),script=source.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const raw=JSON.parse(fs.readFileSync(path.join(base,'週合計.json'),'utf8')),expected=JSON.parse(fs.readFileSync(path.join(work,'audit_expected_rankings.json'),'utf8')),cells=new Map(raw.map(r=>[r.method_id+'|'+r.symbol,r]));
for(const s of ['NK225','TOPIX'])assert.deepEqual(data.single[s].map(x=>x.id),expected['銘柄別全順位'][s].slice(0,5));
assert.deepEqual(data.common.map(x=>x.id),expected['共通資格全順位'].slice(0,5).map(x=>x.id));
assert.equal(data.common[4].stable,false);
for(const [i,row] of data.common.entries()){
 assert.equal(row.stable,expected['共通資格全順位'][i]['頑健条件適合']);
 assert(Math.abs(row.score-expected['共通資格全順位'][i].score)<1e-9);
}
for(const item of data.comparisons)for(const s of ['NK225','TOPIX']){
 const r=cells.get(item.id+'|'+s);
 for(const k of ['gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','unit_balance','money_ratio','unit_payoff','positive_sessions','drawdown_yen','max_long','max_short','max_gross'])assert.equal(item.rows[s][k],r[k]);
}
const elements={};
for(const id of ['data','factor','nk-ranking','top-ranking','common-ranking','comparisons','examples'])elements[id]={innerHTML:'',textContent:'',value:'',events:{},addEventListener(name,fn){this.events[name]=fn;}};
for(const item of data.comparisons)elements['reason-'+item.id]={open:false};
elements.data.textContent=dataText;elements.factor.value='1';
const location={hash:''},window={events:{},addEventListener(n,fn){this.events[n]=fn;}},context=vm.createContext({document:{getElementById(id){return elements[id]||null;}},location,window});
vm.runInContext(script,context);
let count=0;
/**
 * 描画済みの表を円額・枚数・順位で照合する。
 * @param {string} html - 表HTML。
 * @param {object[]} items - 順位の手法。
 * @param {string|null} symbol - 単独銘柄、または共通ならnull。
 * @param {number} factor - 仮定倍率。
 * @returns {void} 返り値なし。
 */
function tableCheck(html,items,symbol,factor){
 const rows=[...html.matchAll(/<tr data-method="([^"]+)">([\s\S]*?)<\/tr>/g)];assert.equal(rows.length,5);
 rows.forEach((match,i)=>{
  const item=items[i];assert.equal(match[1],item.id);
  const amounts=[...match[2].matchAll(/class="amount [^"]+">([^<]+)</g)].map(m=>m[1]),units=[...match[2].matchAll(/class="unitline">([^<]+)枚</g)].map(m=>Number(m[1].replaceAll(',',''))),want=[];
  if(symbol){const r=cells.get(item.id+'|'+symbol),o=cells.get(item.id+'|'+(symbol==='NK225'?'TOPIX':'NK225'));want.push([r.gross_profit_yen,r.profit_units],[-r.gross_loss_yen,r.loss_units],[r.net_yen,r.unit_balance],[o.net_yen,o.unit_balance]);}
  else for(const kind of ['profit','loss','net'])for(const s of ['NK225','TOPIX']){const r=cells.get(item.id+'|'+s);want.push(kind==='profit'?[r.gross_profit_yen,r.profit_units]:kind==='loss'?[-r.gross_loss_yen,r.loss_units]:[r.net_yen,r.unit_balance]);}
  assert.equal(amounts.length,want.length);assert.equal(units.length,want.length);
  want.forEach(([value,quantity],j)=>{const n=value*factor,display=(n>0?'＋':n<0?'−':'')+(Math.abs(n)/10000).toLocaleString('ja-JP',{maximumFractionDigits:2})+'万円';assert.equal(amounts[j],display);assert.equal(units[j],quantity);count++;});
 });
}
// ----------------------------------------
// 全倍率の表、理由リンク、金額倍率によらない順位を確認する。
for(const factor of [1,.1,.01]){
 elements.factor.value=String(factor);elements.factor.events.change();
 tableCheck(elements['nk-ranking'].innerHTML,data.single.NK225,'NK225',factor);
 tableCheck(elements['top-ranking'].innerHTML,data.single.TOPIX,'TOPIX',factor);
 tableCheck(elements['common-ranking'].innerHTML,data.common,null,factor);
 assert.equal((elements.comparisons.innerHTML.match(/<details /g)||[]).length,data.comparisons.length);
}
location.hash='#reason-'+encodeURIComponent(data.common[0].id);window.events.hashchange();assert.equal(elements['reason-'+data.common[0].id].open,true);
for(const match of source.matchAll(/href="([^"#]+)"/g)){assert(!/^https?:/.test(match[1]));assert(fs.existsSync(path.resolve(out,decodeURIComponent(match[1]))),match[1]);}
assert(!source.includes('__PAYLOAD__'));
const record={合格:true,順位照合:'銘柄別５件×２、共通５件を独立順位と一致',金額枚数照合セル数:count,倍率:[1,.1,.01],比較ID数:data.comparisons.length,第５位の安定確認:false,ブラウザー:'既知のURLポリシー拒否を再試行せず、表示コードをローカル検査',HTML_SHA256:crypto.createHash('sha256').update(source).digest('hex')};
fs.writeFileSync(path.join(work,'ランキング表示静的検査.json'),JSON.stringify(record,null,2),'utf8');
fs.copyFileSync(path.join(work,'ランキング表示静的検査.json'),path.join(out,'資料/ランキング/ランキング表示静的検査.json'));
console.log(JSON.stringify(record));
