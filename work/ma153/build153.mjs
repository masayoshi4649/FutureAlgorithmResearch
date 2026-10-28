import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../..');
const publicDir=path.join(root,'アルゴリズム調査/00153_移動平均の傾きと比例枚数');
const output=path.join(root,'outputs/00153_ma_allocation');
const filename='移動平均の傾きと比例枚数の全セッション損益.xlsx';
const raw=await fs.readFile(path.join(here,'report153_combined.json'));
const reportHash=createHash('sha256').update(raw).digest('hex');
const report=JSON.parse(raw.toString('utf8'));
const workbook=Workbook.create();
const summary=workbook.worksheets.add('比較');
const methods=report.methods;
const expected=[];
const pictures=[];
const number='#,##0;[Red](#,##0);"—"';

/**
 * 独立集計値とExcel計算を照合する。
 * @param {number} actual - 計算値。
 * @param {number} wanted - 元会計。
 * @param {string} where - 対象。
 * @returns {void} 不一致なら停止する。
 */
function equal(actual,wanted,where){if(!Number.isFinite(actual)||!Number.isFinite(wanted)||Math.abs(actual-wanted)>1e-5)throw new Error(`${where}: ${actual} / ${wanted}`);}

/**
 * 簡潔な見出しと正式テーブルの書式を用意する。
 * @param {object} sheet - 対象シート。
 * @param {string} end - 最終列。
 * @param {number} last - 最終行。
 * @param {string} title - 表題。
 * @param {string} note - 条件。
 * @returns {void} 返り値なし。
 */
function style(sheet,end,last,title,note){
  sheet.showGridLines=false;
  sheet.getRange(`A1:${end}${last}`).format={font:{name:'Yu Gothic',size:10,color:'#20364A'},rowHeight:24,columnWidth:16,verticalAlignment:'center'};
  sheet.getRange(`A1:A${last}`).format.columnWidth=27;
  sheet.getRange('A1').values=[[title]];sheet.getRange('A1').format.font={bold:true,size:14};
  sheet.getRange('A2').values=[['2026/09/21〜10/26デイ・51完了場。日経mini／TOPIXmini各上限10枚・手数料0。']];
  sheet.getRange('A3').values=[[note]];
  sheet.getRange('A4').values=[['利益・損失＝FIFO返済配賦別。親＝初回から全返済まで。ラージ気配による模型で、mini実約定の検証ではありません。']];
  sheet.getRange('A2:A4').format.font={color:'#52677C',italic:true,size:10};
  sheet.getRange(`B6:${end}${last}`).setNumberFormat(number);
  sheet.getRange(`B6:${end}${last}`).format.horizontalAlignment='right';
}

/**
 * フィルター付きのExcel正式テーブルを作る。
 * @param {object} sheet - 対象。
 * @param {string[]} headers - 見出し。
 * @param {string} end - 最終列。
 * @param {number} last - 明細最終行。
 * @param {string} name - 一意名。
 * @returns {void} 返り値なし。
 */
function table(sheet,headers,end,last,name){
  sheet.getRange(`A5:${end}5`).values=[headers];
  const t=sheet.tables.add(`A5:${end}${last}`,true,name);t.showFilterButton=true;
  sheet.getRange(`A5:${end}5`).format={fill:'#244A70',font:{bold:true,color:'#FFFFFF'},rowHeight:42,wrapText:true,horizontalAlignment:'center'};
  sheet.freezePanes.freezeRows(5);
}

/**
 * 数値比較用のセルを記録する。
 * @param {object} sheet - シート。
 * @param {string} cell - セル番地。
 * @param {number} value - 元数値。
 * @returns {void} 返り値なし。
 */
function check(sheet,cell,value){expected.push([sheet.name,cell,value]);}

// ----------------------------------------
// 銘柄と手法ごとに51場を残し、収支・累計だけはExcel数式で計算する。
for(const method of methods){
  const symbol=method.symbol==='NK225'?'日経':'TOPIX';
  const sheet=workbook.worksheets.add(`${symbol}_${method.id}`);
  const rows=[...method.rows].sort((a,b)=>a.session.localeCompare(b.session));
  if(rows.length!==51)throw new Error(`${sheet.name}: 51場ではありません`);
  const last=56,total=57;
  style(sheet,'N',total,`${symbol} ${method.id}　各セッションの利益・損失・収支`,method.description);
  sheet.getRange('B1:B57').format.columnWidth=10;
  let cumulative=0;
  rows.forEach((row,i)=>{
    const n=i+6;
    equal(row.profit-row.loss,row.net,`${sheet.name}/${row.session}`);
    sheet.getRange(`A${n}:N${n}`).values=[[row.session,row.kind==='Day'?'デイ':'ナイト',row.profit,row.loss,null,null,row.parent_profit,row.parent_loss,row.entries,row.additions,row.reductions,row.max_qty,row.held_rate,row.equity_drawdown]];
    sheet.getRange(`E${n}:F${n}`).formulas=[[`=C${n}-D${n}`,i===0?`=E${n}`:`=F${n-1}+E${n}`]];
    cumulative+=row.net;
    for(const [col,value] of [['C',row.profit],['D',row.loss],['E',row.net],['F',cumulative],['G',row.parent_profit],['H',row.parent_loss],['I',row.entries],['J',row.additions],['K',row.reductions],['L',row.max_qty],['M',row.held_rate],['N',row.equity_drawdown]])check(sheet,`${col}${n}`,value);
  });
  table(sheet,['セッション','区分','利益（円）','損失（円）','収支（円）','累計（円）','親利益（円）','親損失（円）','初回件数','追加件数','縮小件数','最大保有枚数','保有時間率','時価最大DD（円）'],'N',last,`MA153_${method.symbol}_${method.id}`);
  sheet.getRange('A57').values=[['累計／平均／最大']];
  for(const col of ['C','D','G','H','I','J','K'])sheet.getRange(`${col}57`).formulas=[[`=SUM(${col}6:${col}56)`]];
  sheet.getRange('E57:F57').formulas=[['=C57-D57','=F56']];
  sheet.getRange('L57:N57').formulas=[['=MAX(L6:L56)','=AVERAGE(M6:M56)','=MAX(N6:N56)']];
  sheet.getRange('M6:M57').setNumberFormat('0.0%');
  sheet.getRange('A57:N57').format={font:{bold:true},borders:{top:{style:'thin',color:'#9EAFBF'}}};
  sheet.getRange('E6:F56').conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{font:{color:'#A02836'},fill:'#FBEAEC'}});
  check(sheet,'C57',method.summary.profit);check(sheet,'D57',method.summary.loss);check(sheet,'E57',method.summary.net);
  pictures.push([sheet,'N',57]);
}

// ----------------------------------------
// 昼夜を分けた比較を同じ数値表から計算し、主な安定性指標だけを並べる。
const end=methods.length+5;
style(summary,'P',end,'傾きに比例する枚数配分の比較','同じ入口・出口で数量だけを比較できるのはM09／F01／F10。M12は途中増減も変更。');
methods.forEach((method,i)=>{
  const n=i+6,symbol=method.symbol==='NK225'?'日経':'TOPIX',prefix=`'${symbol}_${method.id}'!`;
  const nets=`${prefix}$E$6:$E$56`,kinds=`${prefix}$B$6:$B$56`;
  summary.getRange(`A${n}:P${n}`).values=[[`${symbol}_${method.id}`,method.description,null,null,null,null,null,null,null,null,null,method.summary.medianloss,null,null,null,null]];
  summary.getRange(`C${n}:K${n}`).formulas=[[`=${prefix}C57`,`=${prefix}D57`,`=${prefix}E57`,`=IF(D${n}=0,"",C${n}/D${n})`,
    `=COUNTIFS(${nets},">0")`,`=COUNTIFS(${nets},"<0")`,`=COUNTIFS(${prefix}$I$6:$I$56,0)`,`=MAX(0,-MIN(${nets}))`,`=IF(H${n}=0,"",-SUMIFS(${nets},${nets},"<0")/H${n})`]];
  summary.getRange(`M${n}:P${n}`).formulas=[[`=E${n}-MAX(0,LARGE(${nets},1))-MAX(0,LARGE(${nets},2))-MAX(0,LARGE(${nets},3))`,`=SUMIFS(${nets},${kinds},"デイ")`,`=SUMIFS(${nets},${kinds},"ナイト")`,`=${prefix}I57`]];
  for(const [col,key] of [['C','profit'],['D','loss'],['E','net'],['G','wins'],['H','losses'],['I','no_trade'],['J','maxloss'],['K','avgloss'],['L','medianloss'],['M','ex3'],['P','entries']])if(method.summary[key]!==null)check(summary,`${col}${n}`,method.summary[key]);
  if(method.summary.pf!==null)check(summary,`F${n}`,method.summary.pf);
  check(summary,`N${n}`,method.day.net);check(summary,`O${n}`,method.night.net);
});
table(summary,['銘柄・手法','簡単な説明','総利益（円）','総損失（円）','収支（円）','利益／損失','黒字場数','赤字場数','無取引場数','最大赤字（円）','平均赤字（円）','赤字中央値（円）','上位3黒字除外','デイ収支（円）','ナイト収支（円）','初回件数'],'P',end,'MA153_comparison');
summary.getRange(`A1:A${end}`).format.columnWidth=20;
summary.getRange(`B1:B${end}`).format.columnWidth=54;
summary.getRange(`B6:B${end}`).format={wrapText:true,rowHeight:44,horizontalAlignment:'left'};
summary.getRange(`F6:F${end}`).setNumberFormat('0.00');
summary.getRange(`E6:E${end}`).conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{font:{color:'#A02836'},fill:'#FBEAEC'}});
pictures.unshift([summary,'P',end]);

// ----------------------------------------
// 途中参考は完了51場に加算しない。実現と含みを分けて示す。
if(report.partial?.length){
  const sheet=workbook.worksheets.add('10月26日ナイト途中');
  const partial=report.partial;
  style(sheet,'H',partial.length+5,'10月26日ナイトの既取得途中参考','21:13:52未満。末尾で仮精算せず、51完了場の比較から除外。');
  partial.forEach((row,i)=>{
    const n=i+6;
    sheet.getRange(`A${n}:H${n}`).values=[[`${row.symbol==='NK225'?'日経':'TOPIX'}_${row.id}`,row.profit,row.loss,null,row.unrealized,null,row.entries,row.remaining_qty]];
    sheet.getRange(`D${n}`).formulas=[[`=B${n}-C${n}`]];
    sheet.getRange(`F${n}`).formulas=[[`=D${n}+E${n}`]];
    check(sheet,`D${n}`,row.net);check(sheet,`F${n}`,row.equity);
  });
  table(sheet,['銘柄・手法','実現利益（円）','実現損失（円）','実現収支（円）','未返済含み（円）','時価収支（円）','初回件数','未返済枚数'],'H',partial.length+5,'MA153_partial');
  pictures.push([sheet,'H',partial.length+5]);
}

// ----------------------------------------
// 数式計算と全シートの描画を確認して、正式ファイルを一つ出力する。
workbook.recalculate();
for(const [name,cell,value] of expected)equal(workbook.worksheets.getItem(name).getRange(cell).values[0][0],value,`${name}/${cell}`);
const checks=path.join(here,'xlsx_checks');
await fs.mkdir(checks,{recursive:true});await fs.mkdir(publicDir,{recursive:true});await fs.mkdir(output,{recursive:true});
const inspection=await workbook.inspect({kind:'table',range:'比較!A5:P10',include:'values,formulas',tableMaxRows:6,tableMaxCols:16,maxChars:5000});
await fs.writeFile(path.join(checks,'比較の検査.ndjson'),inspection.ndjson);
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:50},maxChars:3000});
await fs.writeFile(path.join(checks,'式エラーの検査.ndjson'),errors.ndjson);
for(const [sheet,col,row] of pictures){
  const picture=await workbook.render({sheetName:sheet.name,range:`A1:${col}${row}`,scale:1,format:'png'});
  await fs.writeFile(path.join(checks,`${sheet.name}.png`),new Uint8Array(await picture.arrayBuffer()));
}
if(createHash('sha256').update(await fs.readFile(path.join(here,'report153_combined.json'))).digest('hex')!==reportHash)throw new Error('作成中に元会計が変化しました');
const exported=await SpreadsheetFile.exportXlsx(workbook);
await exported.save(path.join(output,filename));await fs.copyFile(path.join(output,filename),path.join(publicDir,filename));
await fs.writeFile(path.join(checks,'Excel照合153.json'),JSON.stringify({report_sha256:reportHash,verified_cells:expected.length,sheets:pictures.length,tables:pictures.length,complete_sessions:51,partial_excluded:true},null,2));
console.log(JSON.stringify({path:path.join(publicDir,filename),sheets:pictures.length,verified:expected.length}));
