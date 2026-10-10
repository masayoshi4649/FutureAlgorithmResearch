/**
 * 保存HTMLのチャートを簡易DOM上で全選択組合せ検査する。
 * 引数: コマンド引数なし。
 * 返り値: なし (undefined)。画面描画の目視検査は代替しない。
 */
function main() {
  const fs = require('fs'), vm = require('vm'), path = require('path');
  const root = path.resolve(__dirname, '../../アルゴリズム調査/00018_市場原理からの再探索');
  const source = fs.readFileSync(path.join(root,'５分足と売買.html'),'utf8');
  const text = source.match(/<script id="chart-data" type="application\/json">([\s\S]*?)<\/script>/)[1];
  const data = JSON.parse(text);
  const context = new Proxy({}, {get:(target,key)=>target[key] || (()=>{}),set:(target,key,value)=>(target[key]=value,true)});
  const elements = {};
  for(const id of ['method','symbol','session','chart-summary','trade-table','chart-data','chart']) {
    elements[id]={value:id==='symbol'?'TOPIX':'',textContent:'',innerHTML:'',options:[],handlers:{},
      add(option){this.options.push(option);if(!this.value)this.value=option.value;},
      addEventListener(event,handler){this.handlers[event]=handler;},
      getBoundingClientRect(){return {width:1120,height:440};},getContext(){return context;}};
  }
  elements['chart-data'].textContent=text;
  const world={document:{getElementById:id=>elements[id]},window:{devicePixelRatio:1,addEventListener(){}},
    Option:function(label,value){this.label=label;this.value=value;},console,Date,Set,Math,JSON};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'chart.js'),'utf8'),world);
  let count=0;
  for(const id of Object.keys(data.methods))for(const symbol of ['TOPIX','NK225'])for(const session of data.sessions){
    elements.method.value=id;elements.symbol.value=symbol;elements.session.value=session;
    elements.method.handlers.change();
    if(/NaN|undefined/.test(elements['trade-table'].innerHTML+elements['chart-summary'].textContent))throw Error('表示に未定義値');
    const expected=data.trades[`${id}|${session}|${symbol}`].length;
    const actual=(elements['trade-table'].innerHTML.match(/<tr>/g)||[]).length-1;
    if(expected!==actual)throw Error('明細件数不一致');
    count++;
  }
  console.log(JSON.stringify({全チャート再描画数:count,構文と表示値検査:true,実ブラウザ目視:false}));
}
main();
