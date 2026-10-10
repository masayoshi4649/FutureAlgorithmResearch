/**
 * 自作HTMLの埋込データと描画コードをブラウザーなしで検査する。
 * 引数: なし。HTMLは今回の生成物だけを読む。
 * 返り値: なし。結果をJSONへ保存し、不一致は例外にする。
 */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const work=__dirname,root=path.resolve(work,'../..');
const report=path.join(root,'アルゴリズム調査/00011_一週間データでの再検証/一週間データでの再検証.html');
const page=fs.readFileSync(report,'utf8');
const payload=page.match(/<script type="application\/json" id="data">([\s\S]*?)<\/script>/)[1];
const code=page.match(/<script>([\s\S]*?)<\/script>/)[1];
const source=JSON.parse(payload);
let operations=0;
const context=new Proxy({},{get:(target,key)=>{
  if(key==='measureText')return text=>({width:String(text).length*6});
  return (...args)=>{for(const value of args)if(typeof value==='number')assert(Number.isFinite(value),'描画の非有限数 '+String(key));operations++;};
},set:(target,key,value)=>{target[key]=value;return true;}});
const elements={};
/**
 * UI通信を伴わない模擬要素を用意する。
 * @param {string} id - ローカル文書の要素ID。
 * @returns {object} 最小限のDOMとCanvasの模擬値。
 */
function element(id){if(!elements[id])elements[id]={id,value:id==='symbol'?'NK225':'',textContent:id==='data'?payload:'',innerHTML:'',clientWidth:1200,width:1200,height:490,style:{},listeners:{},
 addEventListener(type,listener){this.listeners[type]=listener;},getContext(){return context;},scrollIntoView(){},getBoundingClientRect(){return {left:0,top:0,width:1200,height:490};}};return elements[id];}
const sandbox={document:{getElementById:element,querySelectorAll:()=>[]},window:{devicePixelRatio:1,addEventListener:()=>{}},console};
vm.createContext(sandbox);
vm.runInContext(code+'\nglobalThis.localQA={update,refreshMethods,focusTrade,hover};',sandbox,{timeout:30000});
let cells=0,rows=0,summaryChecks=0,focusChecks=0;
for(const [method,definition] of Object.entries(source.methods))for(const symbol of new Set(definition.symbols))for(const session of Object.keys(source.sessions)){
  element('symbol').value=symbol;sandbox.localQA.refreshMethods(method);element('method').value=method;element('session').value=session;
  sandbox.localQA.update();
  const key=[method,session,symbol].join('|'),summary=source.summaries[key];
  assert(summary,'対象セルの集計なし '+key);assert(source.candles[session+'|'+symbol].length,'足なし '+key);
  const visible=source.trades.filter(t=>t.method===method&&t.symbol===symbol&&t.session===session);
  const expected=source.trades.filter(t=>t.method===method&&t.session===session&&(definition.engine==='pair'||t.symbol===symbol));
  const net=expected.reduce((n,t)=>n+t.pnl,0);
  assert(Math.abs(net-summary.net_yen)<1e-6,'図の収支と全脚が不一致 '+key);
  assert.equal((element('trade-table').innerHTML.match(/class="trade-row"/g)||[]).length,visible.length,'表示脚数 '+key);
  assert(!element('trade-table').innerHTML.includes('NaN'),'表示にNaN '+key);
  assert(!element('chart-summary').innerHTML.includes('NaN'),'概要にNaN '+key);
  if(visible.length){sandbox.localQA.focusTrade(visible.length-1);focusChecks++;}
  cells++;rows+=visible.length;summaryChecks++;
}
let localLinks=0;
for(const match of page.matchAll(/href="([^"]+)"/g)){
  const href=match[1];if(href.startsWith('#')){assert(page.includes('id="'+href.slice(1)+'"'),'章リンク '+href);continue;}
  if(/^https?:/.test(href))continue;
  assert(fs.existsSync(path.resolve(path.dirname(report),href.split('#')[0])),'ローカルリンク先なし '+href);localLinks++;
}
const result={HTML:report,表示セル数:cells,表示脚総数:rows,全脚収支との一致セル数:summaryChecks,拡大操作検査数:focusChecks,有限描画操作数:operations,ローカルリンク数:localLinks,
 検査方法:'自作HTMLの埋込データとJavaScriptをローカルVMで実行。DOM/Canvasは模擬であり、ブラウザー通信・画面描画は行わない。',
 ブラウザー表示確認:'未完了：ローカルHTMLを開く操作がBrowser Use URL policyにより拒否されたため、迂回や別ブラウザーを使用していない。',
 拒否原文:'Browser Use rejected this action due to browser security policy. Reason: The browser URL policy blocks this action.',
 承認審査との区別:'automatic approval review の拒否ではなく、Browser UseのURLポリシーによる拒否。',
 SHA256:crypto.createHash('sha256').update(page).digest('hex')};
fs.writeFileSync(path.join(work,'報告静的実行検査.json'),JSON.stringify(result,null,2),'utf8');
console.log(JSON.stringify(result));
