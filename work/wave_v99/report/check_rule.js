/**
 * 機能: 会計やDOMを使わず、全34条件の純粋な説明関数だけを検査する。
 * 引数: コマンド行の第2引数{string}は条件素材JSONのファイル名。
 * 返り値: 標準出力{string}へ日本語JSONの検査件数を返す。
 */
const fs=require('fs'),vm=require('vm'),path=require('path');
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const source=fs.readFileSync(path.join(__dirname,'main.js'),'utf8');

/**
 * 機能: 次の関数コメントまでにある純関数を、初期化コードから切り離す。
 * @param {string} name - 実際に定義されている関数名。
 * @returns {string} 説明又はHTMLエスケープ関数の定義。
 */
function definition(name){const start=source.indexOf(`function ${name}(`),end=source.indexOf('/**',start);if(start<0||end<0)throw Error('純関数を抽出できません');return source.slice(start,end);}
const context={};vm.createContext(context);
vm.runInContext(definition('escapeHtml')+definition('rule')+'\nthis.renderRule=rule;',context);
if(input.catalog.length!==34||input.primary!=='L1_C1_A7_X3')throw Error('条件数又は事前主');
const entrances={0:'候補から直ちに新規',1:'両市場の買い・売り気配が各1呼値',3:'候補から1W順行',5:'不利極値から半W回復',7:'局所有利極値から1W押し'};
const policies={C0:'価格時計差が10秒超なら待機取消',C1:'10秒超の価格時計差だけでは取消しない',C2:'共通の位相時刻後の証拠とは意味が違う',C3:'新しい両源で再準備'};
const counts={C0:0,C1:0,C2:0,C3:0,即時:0,X1:0,X3:0,L0:0,L1:0};
for(const config of input.catalog){
 const previous=/^A(0|1|3|5|7)_X(1|3)$/.exec(config.previous_id),html=context.renderRule(config);
 if(!previous||Number(previous[1])!==config.entry_wait_kind)throw Error('元条件の一致');
 counts[config.entry_support_lane]++;
 for(const text of ['入口','途中','出口',entrances[config.entry_wait_kind],'初期損切りは始値の0.1%','追尾は始値の0.4%幅','TOPIX8枚、日経16枚','全玉を場内で閉じ','停止線は不利へ戻さない'])if(!html.includes(text))throw Error(config.id+'の説明が欠落: '+text);
 if(config.entry_wait_kind){if(!html.includes(policies[config.entry_clock_policy])||!html.includes('出口幅と独立'))throw Error('時計政策又は独立幅');const sourceText=config.entry_support_lane==='L1'?'独立した過去300秒の取引価格':'旧の過去300秒の気配中値';if(!html.includes(sourceText))throw Error('現在支持の価格源');counts[config.entry_clock_policy]++;}
 else{if(!html.includes('追加の方向・両気配再確認なし')||/価格時計差|再準備/.test(html))throw Error('即時に新しい資格を追加');counts.即時++;}
 const exit=previous[2];counts['X'+exit]++;
 if(exit==='1'){if(config.trend_hold_seconds!==1800||config.trend_protection_mode!==0||!html.includes('実新規から30分で返済判断')||!html.includes('追加の利益保護なし'))throw Error('X1出口');}
 else if(config.trend_hold_seconds!==0||config.trend_protection_mode!==1||!html.includes('通常の保有期限なし')||!html.includes('最大順行が初期幅の2倍'))throw Error('X3出口');
 if(/undefined|NaN/.test(html))throw Error('未定義の説明');
}
if(counts.即時!==2||counts.X1!==17||counts.X3!==17||counts.L0!==18||counts.L1!==16||['C0','C1','C2','C3'].some(policy=>counts[policy]!==8))throw Error('組合せ欠落');
console.log(JSON.stringify({全合格:true,純条件説明検査:34,内訳:counts,会計読取:0,HTML生成:0}));
