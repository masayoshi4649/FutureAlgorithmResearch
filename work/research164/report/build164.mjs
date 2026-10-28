import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const here=path.dirname(fileURLToPath(import.meta.url)),work=path.dirname(here);
const root=path.resolve(work,'../..'),qa=path.join(here,'xlsx_checks');
const source=path.join(work,'report_data164_all.json'),sourceBytes=await fs.readFile(source);
const report=JSON.parse(sourceBytes),sourceHash=createHash('sha256').update(sourceBytes).digest('hex');
const marker=JSON.parse(await fs.readFile(path.join(here,'authoring開始164.json'),'utf8'));
const first=JSON.parse(await fs.readFile(path.join(work,'再生全完了164.json'),'utf8'));
const second=JSON.parse(await fs.readFile(path.join(work,'r2/再生全完了164r2.json'),'utf8'));
const audit=JSON.parse(await fs.readFile(path.join(work,'audit/audit164_all.json'),'utf8'));
if(!marker.marker_executed||marker.returncode!==0||marker.source_sha256!==sourceHash)throw new Error('確定資料での作者開始記録が必要です');
if(!first.completed||first.returncode!==0||first.cases!==540||!second.completed||second.returncode!==0||second.cases!==324||!audit.passed)throw new Error('二巡の全結果と独立会計監査の確定が必要です');
const methods=report.methods;
if(methods.length!==32||new Set(methods.map(m=>m.id)).size!==32)throw new Error('固定32手法が必要です');
const scheduleMap=new Map();
for(const s of report.schedules){
  const key=`${s.pre}/${s.post}`;
  if(scheduleMap.has(key)){
    const prior=scheduleMap.get(key);
    if(JSON.stringify(prior.rows)!==JSON.stringify(s.rows))throw new Error('同一時間割の会計が不一致です');
    prior.aliases.push(...(s.aliases??[s.name]));
  }else scheduleMap.set(key,{...s,aliases:[...(s.aliases??[s.name])]});
}
const schedules=[...scheduleMap.values()];
const filename='J02改修と夜間独立手法の全セッション損益.xlsx';
const outputDir=path.join(root,'outputs/00164_research');
const publicDir=path.join(root,'アルゴリズム調査/00164_J02の日中改修と夜間の独立入口');
const wb=Workbook.create(),comparison=wb.worksheets.add('比較'),schedule=wb.worksheets.add('夜間の時間割');
const sheets=new Map(methods.map(m=>[m.id,wb.worksheets.add(`日経_${m.id.replace('NK225_','')}`)]));
const checks=[],texts=[],tables=[],previews=[];
const money='#,##0;[Red](#,##0);"—"',counts='#,##0';
const scopeNames={Day:'日中',PreUS:'米国前',PostUS:'米国後'};

/**
 * 元会計との数値一致を確認する。
 * @param {number} actual - 計算値。
 * @param {number} expected - 会計側の期待値。
 * @param {string} label - 対象名。
 * @returns {void} 返り値なし。不一致は例外。
 */
function equal(actual,expected,label){
  if(!Number.isFinite(actual)||!Number.isFinite(expected)||Math.abs(actual-expected)>1e-5)throw new Error(`${label}: ${actual}/${expected}`);
}

/**
 * 独立XML検算用の期待値を登録する。
 * @param {object} sheet - シート。
 * @param {string} address - セル番地。
 * @param {number|string} value - 期待値。
 * @returns {void} 返り値なし。
 */
function expect(sheet,address,value){(typeof value==='number'?checks:texts).push([sheet.name,address,value]);}

/**
 * 表題と共通書式を設定する。
 * @param {object} sheet - シート。
 * @param {string} end - 終列。
 * @param {number} last - 終行。
 * @param {string} title - 表題。
 * @param {string} note - 短い条件。
 * @returns {void} 返り値なし。
 */
function style(sheet,end,last,title,note){
  sheet.showGridLines=false;
  sheet.getRange(`A1:${end}${last}`).format={font:{name:'Yu Gothic',size:10,color:'#20384D'},rowHeight:25,columnWidth:16,verticalAlignment:'center'};
  sheet.getRange('A1').format.rowHeight=10;
  sheet.getRange('A2').values=[[title]];sheet.getRange('A2').format.font={size:14,bold:true};
  sheet.getRange('A3').values=[[note]];sheet.getRange('A3:A4').format.font={size:10,color:'#536B80',italic:true};
  sheet.getRange(`D6:${end}${last}`).setNumberFormat(money);
  sheet.getRange(`D6:${end}${last}`).format.horizontalAlignment='right';
  sheet.freezePanes.freezeRows(5);
}

/**
 * 正式ExcelTableを一意名で作る。
 * @param {object} sheet - シート。
 * @param {string[]} headers - 列見出し。
 * @param {string} end - 終列。
 * @param {number} header - 見出し行。
 * @param {number} last - 最終データ行。
 * @param {string} name - 表名。
 * @returns {void} 返り値なし。
 */
function table(sheet,headers,end,header,last,name){
  sheet.getRange(`A${header}:${end}${header}`).values=[headers];
  const t=sheet.tables.add(`A${header}:${end}${last}`,true,name);t.showFilterButton=true;
  sheet.getRange(`A${header}:${end}${header}`).format={fill:'#264D70',font:{bold:true,color:'#FFFFFF'},rowHeight:43,wrapText:true,horizontalAlignment:'center'};
  tables.push({sheet:sheet.name,name,reference:`A${header}:${end}${last}`,rows:last-header});
  headers.forEach((v,i)=>expect(sheet,`${String.fromCharCode(65+i)}${header}`,v));
}

/**
 * 負数を強調する条件付き書式を設定する。
 * @param {object} sheet - シート。
 * @param {string} range - 範囲。
 * @returns {void} 返り値なし。
 */
function negative(sheet,range){sheet.getRange(range).conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{fill:'#FBE9EB',font:{color:'#9C2632'}}});}

/**
 * 期間区分の行番地を返す。
 * @param {object} method - 手法データ。
 * @param {boolean} isFront - 前40場内を選ぶ場合は真。
 * @returns {number[]} Excel行番号。
 */
function matchingRows(method,isFront){return method.rows.flatMap((r,i)=>['train','validation'].includes(r.split)===isFront?[i+6]:[]);}

/**
 * 一つの会計表の数値・数式と累計を設定する。
 * @param {object} sheet - シート。
 * @param {object[]} rows - 場ごとの会計。
 * @param {object} summary - 合計会計。
 * @param {number} header - 見出し行。
 * @param {Function} labels - 行の先頭3列を返す関数。
 * @returns {void} 返り値なし。
 */
function accounting(sheet,rows,summary,header,labels){
  const last=header+rows.length,total=last+1;let cumulative=0;
  if(rows.length!==27)throw new Error('適用場数が27場ではありません');
  rows.forEach((r,i)=>{
    const n=header+i+1;cumulative+=r.net;equal(r.profit-r.loss,r.net,'返済収支');equal(cumulative,r.cumulative,'累計');
    const prefix=labels(r);
    sheet.getRange(`A${n}:K${n}`).values=[[...prefix,r.profit,r.loss,null,null,r.minimum_equity,r.maximum_dd,r.new_orders,null]];
    sheet.getRange(`F${n}:G${n}`).formulas=[[`=D${n}-E${n}`,i?`=G${n-1}+F${n}`:`=F${n}`]];
    sheet.getRange(`K${n}`).formulas=[[`=IF(J${n}=0,1,0)`]];
    ['D','E','F','G','H','I','J','K'].forEach((c,j)=>expect(sheet,`${c}${n}`,[r.profit,r.loss,r.net,cumulative,r.minimum_equity,r.maximum_dd,r.new_orders,r.new_orders===0?1:0][j]));
    prefix.forEach((v,j)=>expect(sheet,`${String.fromCharCode(65+j)}${n}`,v));
  });
  sheet.getRange(`J${header+1}:K${total}`).setNumberFormat(counts);
  sheet.getRange(`A${total}`).values=[['累計／場内最悪値']];
  sheet.getRange(`D${total}:K${total}`).formulas=[[`=SUM(D${header+1}:D${last})`,`=SUM(E${header+1}:E${last})`,`=D${total}-E${total}`,`=G${last}`,`=MIN(H${header+1}:H${last})`,`=MAX(I${header+1}:I${last})`,`=SUM(J${header+1}:J${last})`,`=SUM(K${header+1}:K${last})`]];
  sheet.getRange(`A${total}:K${total}`).format.font={bold:true};
  ['D','E','F','G','H','I','J','K'].forEach((c,j)=>expect(sheet,`${c}${total}`,[summary.profit,summary.loss,summary.net,summary.net,summary.minimum_equity,summary.maximum_dd,rows.reduce((a,r)=>a+r.new_orders,0),summary.no_entries][j]));
  negative(sheet,`F${header+1}:H${last}`);
}

// ----------------------------------------
// 手法別に27場を掲載する。説明は短く、詳細は別紙へ分ける。
const numericHeaders=['利益（円）','損失（円）','収支（円）','累計（円）','場内最悪収支（円）','最大下落額（円）','新規回数','無取引'];
for(const m of methods){
  const sh=sheets.get(m.id);
  style(sh,'K',33,`${m.id}　${scopeNames[m.scope]}の損益`,m.description);
  sh.getRange('A4').values=[['片側micro100枚＝mini10枚相当／手数料0／ラージ気配代理。無取引は1、取引ありは0。']];
  sh.getRange('A1:A33').format.columnWidth=25;sh.getRange('B1:B33').format.columnWidth=13;
  sh.getRange('C1:C33').format.columnWidth=9;sh.getRange('J1:K33').format.columnWidth=11;
  accounting(sh,m.rows,m.summary.全場,5,r=>[r.session,r.session==='2026-10-27_Night'?'追加1場':(['train','validation'].includes(r.split)?'前40場内':'旧後13場内'),r.direction]);
  table(sh,['セッション','資料区分','場方向',...numericHeaders],'K',5,32,`R164_${m.id}`);
  previews.push([sh.name,'A1:K33']);
}

// ----------------------------------------
// 全32手法を1行ずつ比較し、前半と確認区間を併記する。
const last=methods.length+5;
style(comparison,'O',last,'J02改修と夜間独立手法　32手法の比較','全場は各27場。前40場内で候補を固定し、旧後13場＋追加夜1場で確認しています。');
comparison.getRange('A4').values=[['第二巡は全54場を確認後の既知資料による追加開発。損失は正額、場内最悪は確定＋含み。前半の固定は採用推奨ではありません。']];
comparison.getRange(`A1:A${last}`).format.columnWidth=24;comparison.getRange(`B1:C${last}`).format.columnWidth=12;
comparison.getRange(`H1:I${last}`).format.columnWidth=11;comparison.getRange(`O1:O${last}`).format.columnWidth=19;
methods.forEach((m,i)=>{
  const n=i+6,sh=sheets.get(m.id),s=m.summary.全場;
  const chosen=m.first_round_selected&&m.second_round_selected?'第1・2巡':m.second_round_selected?'第2巡':m.first_round_selected?'第1巡':'';
  comparison.getRange(`A${n}:O${n}`).values=[[m.id,scopeNames[m.scope],chosen,null,null,null,null,s.negative_sessions,s.no_entries,s.mean_loss,s.maximum_loss,s.minimum_equity,null,null,s.excluding_top3]];
  const sum=front=>`SUM(${matchingRows(m,front).map(r=>`'${sh.name}'!F${r}`).join(',')})`;
  equal(matchingRows(m,true).length,m.summary.前40内.sessions,'前半場数');equal(matchingRows(m,false).length,m.summary.確認14内.sessions,'確認場数');
  comparison.getRange(`D${n}:G${n}`).formulas=[[`='${sh.name}'!D33`,`='${sh.name}'!E33`,`=D${n}-E${n}`,`=F${n}/27`]];
  comparison.getRange(`M${n}:N${n}`).formulas=[[`=${sum(true)}`,`=${sum(false)}`]];
  ['D','E','F','G','H','I','J','K','L','M','N','O'].forEach((c,j)=>expect(comparison,`${c}${n}`,[s.profit,s.loss,s.net,s.average,s.negative_sessions,s.no_entries,s.mean_loss,s.maximum_loss,s.minimum_equity,m.summary.前40内.net,m.summary.確認14内.net,s.excluding_top3][j]));
  expect(comparison,`A${n}`,m.id);expect(comparison,`B${n}`,scopeNames[m.scope]);expect(comparison,`C${n}`,chosen);
});
table(comparison,['手法ID','時間帯','前半の固定','利益（円）','損失（円）','収支（円）','1場平均（円）','赤字場数','無取引場数','平均赤字（円）','最大赤字（円）','場内最悪収支（円）','前40場内収支（円）','確認14場内収支（円）','大勝ち3場除外収支（円）'],'O',5,last,'R164_comparison');
comparison.getRange(`H6:I${last}`).setNumberFormat(counts);negative(comparison,`F6:G${last}`);negative(comparison,`L6:O${last}`);
previews.unshift([comparison.name,`A1:O${last}`]);

// ----------------------------------------
// 同じ夜間構成の重複表は統合し、全選択履歴を名称に残す。
const end=schedules.length*32+1;
style(schedule,'K',end,'夜間の時間割　前半と後半の合算','保存会計の連結です。米国開始前後15分は静観。新しい手法IDは付けていません。');
schedule.getRange(`A1:A${end}`).format.columnWidth=25;schedule.getRange(`B1:C${end}`).format.columnWidth=24;schedule.getRange(`J1:K${end}`).format.columnWidth=11;
schedules.forEach((s,i)=>{
  const header=5+i*32;
  if(s.synthetic_method_id!==null)throw new Error('夜間構成に合成IDがあります');
  schedule.getRange(`A${header-1}`).values=[[s.aliases.join(' / ')]];
  expect(schedule,`A${header-1}`,s.aliases.join(' / '));
  accounting(schedule,s.rows,s.summary.全場,header,r=>[r.session,s.pre,s.post]);
  table(schedule,['セッション','米国前の手法ID','米国後の手法ID',...numericHeaders],'K',header,header+27,`R164_schedule_${i+1}`);
});
previews.splice(1,0,[schedule.name,`A1:K${end}`]);

// ----------------------------------------
// 再計算・全セル照合・エラー検査・全シート描画を経て保存する。
wb.recalculate();
for(const [sn,address,value]of checks)equal(wb.worksheets.getItem(sn).getRange(address).values[0][0],value,`${sn}/${address}`);
for(const [sn,address,value]of texts)if(wb.worksheets.getItem(sn).getRange(address).values[0][0]!==value)throw new Error(`文字照合失敗 ${sn}/${address}`);
await fs.mkdir(qa,{recursive:true});
const inspection=await wb.inspect({kind:'table',range:'比較!A1:O37',include:'values,formulas',tableMaxRows:37,tableMaxCols:15});
await fs.writeFile(path.join(qa,'比較の検査.ndjson'),inspection.ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100}});
await fs.writeFile(path.join(qa,'式エラーの検査.ndjson'),errors.ndjson);
if(!errors.ndjson.includes('matched 0 entries'))throw new Error('式エラー検索を確認してください');
const rendered=[];
for(const [sheetName,range]of previews){
  const image=await wb.render({sheetName,range,scale:1.25,format:'png'}),target=path.join(qa,`${sheetName}.png`);
  await fs.writeFile(target,new Uint8Array(await image.arrayBuffer()));rendered.push({sheet:sheetName,path:target,range});
}
await fs.mkdir(outputDir,{recursive:true});await fs.mkdir(publicDir,{recursive:true});
const output=await SpreadsheetFile.exportXlsx(wb),target=path.join(outputDir,filename);
await output.save(target);await fs.copyFile(target,path.join(publicDir,filename));
const exported=await fs.readFile(target),workbookHash=createHash('sha256').update(exported).digest('hex');
await fs.writeFile(path.join(qa,'作者期待値164.json'),JSON.stringify({source,source_sha256:sourceHash,workbook:path.join(publicDir,filename),workbook_sha256:workbookHash,checks,texts,tables,previews:rendered,sheets:[comparison.name,schedule.name,...sheets.values()].map(x=>typeof x==='string'?x:x.name),schedules:schedules.map(s=>({pre:s.pre,post:s.post,aliases:s.aliases}))},null,2));
console.log(JSON.stringify({sheets:34,tables:tables.length,cells:checks.length,texts:texts.length,workbook_sha256:workbookHash}));
