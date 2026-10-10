/**
 * 保存済みHTMLの表示コードをローカルの要素モデルで照合する。
 * 実ブラウザーやネットワークは使わず、原集計との値・件数・倍率一致を確認する。
 * 引数: なし。
 * 返り値: なし。成功時はJSON記録を保存し、不一致時は例外を返す。
 */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const work=__dirname,out=path.resolve(work,'../../アルゴリズム調査/00012_状態切替と柔軟な建玉管理'),page=path.join(out,'状態切替と柔軟な建玉管理.html'),source=fs.readFileSync(page,'utf8');
const rawWeeks=JSON.parse(fs.readFileSync(path.join(work,'週合計.json'),'utf8')),rawSessions=JSON.parse(fs.readFileSync(path.join(work,'セッション集計.json'),'utf8')),settings=JSON.parse(fs.readFileSync(path.join(work,'表示設定.json'),'utf8'));
const data=source.match(/<script type="application\/json" id="data">([\s\S]*?)<\/script>/)[1],script=source.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const elements={};
for(const id of ['data','symbol','method','factor','method-name','description','weekly','sessions','details-body'])elements[id]={value:'',innerHTML:'',textContent:'',events:{},addEventListener(name,fn){this.events[name]=fn;}};
elements.data.textContent=data;elements.symbol.value='NK225';elements.factor.value='1';
const context=vm.createContext({document:{getElementById(id){assert(id in elements,id);return elements[id];}}});
vm.runInContext(script,context);
assert.equal(elements.method.value,settings.default.NK225);
elements.symbol.value='TOPIX';elements.symbol.events.change();assert.equal(elements.method.value,settings.default.TOPIX);
assert.equal((elements.method.innerHTML.match(/<option /g)||[]).length,180);
const ids=[...source.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);assert.equal(new Set(ids).size,ids.length);
assert(source.includes('<details id="research-details">'));
assert(!/__(PAYLOAD|DETAILS)__/.test(source));
const cells=new Map(rawSessions.map(r=>[r.method_id+'|'+r.symbol+'|'+r.session,r]));
let views=0,rowsChecked=0;
/**
 * １表のHTMLを原集計の金額と枚数へ照合する。
 * @param {string} html - 描画された表。
 * @param {object[]} rows - 原集計の行。
 * @param {number} factor - 仮定換算倍率。
 * @returns {void} 返り値なし。
 */
function checkTable(html,rows,factor){
  const body=html.match(/<tbody>([\s\S]*?)<\/tbody>/)[1],rendered=[...body.matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map(m=>m[1]);
  assert.equal(rendered.length,rows.length);
  rendered.forEach((tr,i)=>{
    const values=[...tr.matchAll(/class="amount [^"]+">([^<]+)</g)].map(m=>m[1]);
    const units=[...tr.matchAll(/class="units">([^<]+)枚</g)].map(m=>Number(m[1].replaceAll(',','')));
    const row=rows[i],raw=[row.gross_profit_yen,-row.gross_loss_yen,row.net_yen];
    assert.deepEqual(units,[row.profit_units,row.loss_units,row.profit_units-row.loss_units]);
    raw.forEach((value,j)=>{
      const n=value*factor,expected=(n>0?'＋':n<0?'−':'')+(Math.abs(n)/10000).toLocaleString('ja-JP',{maximumFractionDigits:2})+'万円';
      assert.equal(values[j],expected);
    });
    rowsChecked++;
  });
}
// ----------------------------------------
// 全条件・銘柄・換算倍率で同じ保存済み金額を表示することを確認する。
for(const week of rawWeeks){
  elements.symbol.value=week.symbol;elements.method.value=week.method_id;
  for(const factor of [1,.1,.01]){
    elements.factor.value=String(factor);vm.runInContext('render()',context);
    checkTable(elements.weekly.innerHTML,[week],factor);
    const sessions=[];
    for(let day=21;day<=25;day++)for(const part of ['Day','Night'])sessions.push(cells.get(week.method_id+'|'+week.symbol+'|2026-09-'+day+'_'+part));
    checkTable(elements.sessions.innerHTML,sessions,factor);
    assert(elements.sessions.innerHTML.includes('9/25 夜間 → 9/26 朝'));
    assert(elements['method-name'].textContent.startsWith(week.method_id+' ／ '));
    assert.equal(elements.description.textContent.split('\n').length,2);
    assert(elements.description.textContent.startsWith(week.method_id.includes('_逆_')?'逆方向：':'同方向：'));
    views++;
  }
}
for(const match of source.matchAll(/href="([^"#]+)"/g)){
  const url=match[1];assert(!/^https?:/.test(url));assert(fs.existsSync(path.resolve(out,decodeURIComponent(url))),url);
}
const result={合格:true,表示組合せ:views,表の照合行数:rowsChecked,条件数:180,銘柄数:2,倍率:[1,.1,.01],銘柄別初期選択:settings.default,実ブラウザー確認:false,未確認理由:'既知のBrowser Use URLポリシー拒否を再試行せず、ローカルの表示コードだけを検査',HTML_SHA256:crypto.createHash('sha256').update(source).digest('hex')};
fs.writeFileSync(path.join(work,'表示静的検査.json'),JSON.stringify(result,null,2),'utf8');
fs.copyFileSync(path.join(work,'表示静的検査.json'),path.join(out,'資料/表示静的検査.json'));
console.log(JSON.stringify(result));
