import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../..');
const publicDir=path.join(root,'アルゴリズム調査/00154_D07の利益返しと多枚数新規の改善');
const outDir=path.join(root,'outputs/00154_d07_profit');
const filename='D07の利益保護と段階投入の全セッション損益.xlsx';
const bytes=await fs.readFile(path.join(here,'report154_combined.json'));
const reportHash=createHash('sha256').update(bytes).digest('hex');
const report=JSON.parse(bytes.toString('utf8'));
const methods=report.methods;
if(methods.length!==23||report.summary.complete_sessions!==51)throw new Error('固定23条件・51完了場の元会計ではありません');
const lastCase=methods.length+5;
const workbook=Workbook.create();
const summary=workbook.worksheets.add('比較');
const checks=[],pictures=[];
const money='#,##0;[Red](#,##0);"—"';
const baseline=methods.find(x=>x.id==='D07');
const baseBySession=new Map(baseline.rows.map(r=>[r.session,r]));

/**
 * 元会計とExcel計算の数値を一致確認する。
 * @param {number} actual - 計算値。
 * @param {number} expected - 元会計。
 * @param {string} label - 検査対象。
 * @returns {void} 不一致なら停止する。
 */
function equal(actual,expected,label){if(!Number.isFinite(actual)||!Number.isFinite(expected)||Math.abs(actual-expected)>1e-5)throw new Error(`${label}: ${actual} / ${expected}`);}

/**
 * 仕上げ時に検算する元数値を記録する。
 * @param {object} sheet - シート。
 * @param {string} cell - セル番地。
 * @param {number} expected - 独立会計。
 * @returns {void} 返り値なし。
 */
function check(sheet,cell,expected){checks.push([sheet.name,cell,expected]);}

/**
 * 短い表題と同じ大きさの本文を用意する。
 * @param {object} sheet - シート。
 * @param {string} end - 最終列。
 * @param {number} last - 最終行。
 * @param {string} title - 表題。
 * @param {string} description - 条件の短い説明。
 * @param {string} note - 比較範囲。
 * @returns {void} 返り値なし。
 */
function style(sheet,end,last,title,description,note){
 sheet.showGridLines=false;
 sheet.getRange(`A1:${end}${last}`).format={font:{name:'Yu Gothic',size:10,color:'#21384D'},rowHeight:25,columnWidth:17,verticalAlignment:'center'};
 sheet.getRange(`A1:A${last}`).format.columnWidth=27;
 sheet.getRange('A1').format.rowHeight=10;
 sheet.getRange('A2').values=[[title]];sheet.getRange('A2').format.font={bold:true,size:14};
 sheet.getRange('A3').values=[[description]];
 sheet.getRange('A4').values=[[note]];sheet.getRange('A3:A4').format.font={color:'#536B80',size:10};
 sheet.getRange(`B6:${end}${last}`).setNumberFormat(money);
 sheet.getRange(`B6:${end}${last}`).format.horizontalAlignment='right';
}

/**
 * 一意名を持つフィルター付き正式テーブルを配置する。
 * @param {object} sheet - シート。
 * @param {string[]} headers - 見出し。
 * @param {string} end - 最終列。
 * @param {number} last - 明細最終行。
 * @param {string} name - テーブル名。
 * @returns {void} 返り値なし。
 */
function table(sheet,headers,end,last,name){
 sheet.getRange(`A5:${end}5`).values=[headers];
 const t=sheet.tables.add(`A5:${end}${last}`,true,name);t.showFilterButton=true;
 sheet.getRange(`A5:${end}5`).format={fill:'#264D70',font:{bold:true,color:'#FFFFFF'},rowHeight:43,wrapText:true,horizontalAlignment:'center'};
 sheet.freezePanes.freezeRows(5);
}

// ----------------------------------------
// 手法ごとに全51場を掲載し、収支・累計・基準差を計算する。
for(const method of methods){
 const sheet=workbook.worksheets.add(`日経_${method.id}`);
 const rows=[...method.rows].sort((a,b)=>a.session.localeCompare(b.session));
 if(rows.length!==51)throw new Error(`${sheet.name}の場数が不正です`);
 style(sheet,'M',57,`日経 ${method.id}　各セッションの損益`,method.description,'日経mini上限10枚・手数料0。利益／損失は一連の売買を合算。初回・追撃・回転の内訳も表示。51完了場のみ。');
 sheet.getRange('B1:C57').format.columnWidth=9;
 let accumulated=0;
 rows.forEach((r,i)=>{
  const n=i+6;equal(r.profit-r.loss,r.net,`${method.id}/${r.session}/親会計`);
  equal(r.initial.net+r.addition.net+r.reentry.net,r.net,`${method.id}/${r.session}/玉別内訳`);
  sheet.getRange(`A${n}:M${n}`).values=[[r.session,r.kind==='Day'?'デイ':'ナイト',r.direction,r.profit,r.loss,null,null,null,r.initial.net,r.addition.net,r.reentry.net,r.entries,r.entry_quantity]];
  sheet.getRange(`F${n}:H${n}`).formulas=[[`=D${n}-E${n}`,i===0?`=F${n}`:`=G${n-1}+F${n}`,method.id==='D07'?`=F${n}-F${n}`:`=F${n}-'日経_D07'!F${n}`]];
  accumulated+=r.net;
  for(const [col,value] of [['D',r.profit],['E',r.loss],['F',r.net],['G',accumulated],['H',r.net-baseBySession.get(r.session).net],['I',r.initial.net],['J',r.addition.net],['K',r.reentry.net],['L',r.entries],['M',r.entry_quantity]])check(sheet,`${col}${n}`,value);
 });
 table(sheet,['セッション','区分','場の方向','利益（円）','損失（円）','収支（円）','累計（円）','D07差（円）','初回玉収支（円）','追撃玉収支（円）','回転玉収支（円）','新規件数','新規枚数'],'M',56,`D154_${method.id}`);
 sheet.getRange('A57').values=[['累計']];
 for(const col of ['D','E','H','I','J','K','L','M'])sheet.getRange(`${col}57`).formulas=[[`=SUM(${col}6:${col}56)`]];
 sheet.getRange('F57:G57').formulas=[['=D57-E57','=G56']];
 sheet.getRange('A57:M57').format={font:{bold:true},borders:{top:{style:'thin',color:'#93AABD'}}};
 sheet.getRange('F6:K56').conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{fill:'#FBE9EB',font:{color:'#9C2632'}}});
 check(sheet,'D57',method.summary.profit);check(sheet,'E57',method.summary.loss);check(sheet,'F57',method.summary.net);
 check(sheet,'I57',method.summary.initial_net);check(sheet,'J57',method.summary.addition_net);check(sheet,'K57',method.summary.reentry_net);
 pictures.push([sheet,'M',57]);
}

// ----------------------------------------
// 比較表は明細の完成値を参照し、昼夜と大勝ち除外を併記する。
style(summary,'N',lastCase,'D07の利益保護と段階投入の比較','2026/09/21～10/26デイの51完了場。今日の途中結果は別シート。','利益／損失は一連の売買を合算。上位3黒字場を除いた収支も表示。既知資料での比較、ラージ次正常気配の約定模型。');
summary.getRange(`A1:A${lastCase}`).format.columnWidth=15;summary.getRange(`B1:B${lastCase}`).format.columnWidth=52;
methods.forEach((m,i)=>{
 const n=i+6,p=`'日経_${m.id}'!`,net=`${p}$F$6:$F$56`,kind=`${p}$B$6:$B$56`,direction=`${p}$C$6:$C$56`;
 summary.getRange(`A${n}:N${n}`).values=[[m.id,m.description,null,null,null,null,null,null,null,null,null,null,null,null]];
 summary.getRange(`C${n}:N${n}`).formulas=[[`=${p}D57`,`=${p}E57`,`=${p}F57`,`=IF(D${n}=0,"",C${n}/D${n})`,`=COUNTIFS(${net},"<0")`,`=IF(G${n}=0,0,-SUMIFS(${net},${net},"<0")/G${n})`,`=MAX(0,-MIN(${net}))`,`=E${n}-MAX(0,LARGE(${net},1))-MAX(0,LARGE(${net},2))-MAX(0,LARGE(${net},3))`,`=SUMIFS(${net},${kind},"デイ")`,`=SUMIFS(${net},${kind},"ナイト")`,`=SUMIFS(${net},${direction},"上昇")`,`=SUMIFS(${net},${direction},"下落")`]];
 for(const [col,value] of [['C',m.summary.profit],['D',m.summary.loss],['E',m.summary.net],['G',m.summary.losses],['H',m.summary.avgloss],['I',m.summary.maxloss],['J',m.summary.ex3],['K',m.day.net],['L',m.night.net],['M',m.up.net],['N',m.down.net]])check(summary,`${col}${n}`,value);
 if(m.summary.pf!==null)check(summary,`F${n}`,m.summary.pf);
});
table(summary,['手法','簡単な説明','総利益（円）','総損失（円）','収支（円）','利益／損失','赤字場数','平均赤字（円）','最大赤字（円）','上位3黒字除外','デイ収支（円）','ナイト収支（円）','上昇場収支（円）','下落場収支（円）'],'N',lastCase,'D154_comparison');
summary.getRange(`B6:B${lastCase}`).format={wrapText:true,rowHeight:43,horizontalAlignment:'left'};
summary.getRange(`F6:F${lastCase}`).setNumberFormat('0.00');
summary.getRange(`E6:E${lastCase}`).conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{font:{color:'#9C2632'},fill:'#FBE9EB'}});
pictures.unshift([summary,'N',lastCase]);

// ----------------------------------------
// 未完了親の部分実現を完結親と分け、途中末尾で架空清算しない。
const partial=workbook.worksheets.add('10月27日デイ途中');
style(partial,'K',lastCase,'10月27日デイの途中結果','12:08未満の取得済み末尾まで。実行中アプリの実約定とは別の模型。','完了取引の利益－損失＋継続中の実現＝実現収支。11:21:41欄は同時刻の模型。手動決済を模擬しません。');
const current=report.current_rows;
if(current.length!==23)throw new Error('途中結果が23条件ではありません');
current.forEach((r,i)=>{
 const n=i+6,stop=r.at_actual_stop;
 partial.getRange(`A${n}:K${n}`).values=[[r.id,r.profit,r.loss,r.open_parent_realized,null,r.unrealized,null,r.remaining_qty,stop.realized,stop.unrealized,null]];
 partial.getRange(`E${n}`).formulas=[[`=B${n}-C${n}+D${n}`]];
 partial.getRange(`G${n}`).formulas=[[`=E${n}+F${n}`]];
 partial.getRange(`K${n}`).formulas=[[`=I${n}+J${n}`]];
 for(const [col,value] of [['B',r.profit],['C',r.loss],['D',r.open_parent_realized],['E',r.net],['F',r.unrealized],['G',r.equity],['H',r.remaining_qty],['I',stop.realized],['J',stop.unrealized],['K',stop.equity]])check(partial,`${col}${n}`,value);
});
table(partial,['手法','完了取引利益（円）','完了取引損失（円）','継続中実現（円）','実現収支（円）','含み損益（円）','時価収支（円）','未返済枚数','11:21実現（円）','11:21含み（円）','11:21時価（円）'],'K',lastCase,'D154_current');
pictures.push([partial,'K',lastCase]);

// ----------------------------------------
// 全数式・全シートを検査してから、一つの成果物を同一内容で保存する。
workbook.recalculate();
for(const [name,cell,value] of checks)equal(workbook.worksheets.getItem(name).getRange(cell).values[0][0],value,`${name}/${cell}`);
const qa=path.join(here,'xlsx_checks');
await fs.mkdir(qa,{recursive:true});await fs.mkdir(outDir,{recursive:true});await fs.mkdir(publicDir,{recursive:true});
const inspect=await workbook.inspect({kind:'table',range:`比較!A5:N${lastCase}`,include:'values,formulas',tableMaxRows:24,tableMaxCols:14,maxChars:8000});
await fs.writeFile(path.join(qa,'比較の検査.ndjson'),inspect.ndjson);
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},maxChars:4000});
await fs.writeFile(path.join(qa,'式エラーの検査.ndjson'),errors.ndjson);
for(const [sheet,col,row] of pictures){const png=await workbook.render({sheetName:sheet.name,range:`A1:${col}${row}`,scale:1,format:'png'});await fs.writeFile(path.join(qa,`${sheet.name}.png`),new Uint8Array(await png.arrayBuffer()));}
if(createHash('sha256').update(await fs.readFile(path.join(here,'report154_combined.json'))).digest('hex')!==reportHash)throw new Error('作成中に独立会計が変わりました');
const output=await SpreadsheetFile.exportXlsx(workbook);await output.save(path.join(outDir,filename));await fs.copyFile(path.join(outDir,filename),path.join(publicDir,filename));
await fs.writeFile(path.join(qa,'Excel照合154.json'),JSON.stringify({report_sha256:reportHash,checked_cells:checks.length,sheets:25,tables:25,complete_sessions:51,current_separate:true},null,2));
console.log(JSON.stringify({path:path.join(publicDir,filename),sheets:pictures.length,checked:checks.length}));
