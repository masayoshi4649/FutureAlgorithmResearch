import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const work=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(work,'../..');
const filename='損切りなし両建ての全夜間損益.xlsx';
const publicDir=path.join(root,'アルゴリズム調査/00151_損切りなし両建てと利益玉トレーリング');
const output=path.join(root,'outputs/00151_no_stop_hedge');
const raw=await fs.readFile(path.join(work,'report151.json'));
const reportHash=createHash('sha256').update(raw).digest('hex');
const report=JSON.parse(raw.toString('utf8'));
const methods=report.methods;
const workbook=Workbook.create();
const comparison=workbook.worksheets.add('比較');
const details=new Map(methods.map(m=>[m.id,workbook.worksheets.add(`日経_${m.id}`)]));
const partial=workbook.worksheets.add('当夜途中');
const expected=[];
const images=[];
const moneyFormat='#,##0;[Red](#,##0);"—"';

/**
 * 独立会計とセルの数値を照合する。
 * @param {number} actual - 計算値。
 * @param {number} wanted - 原会計値。
 * @param {string} where - 検算箇所。
 * @returns {void} 不一致なら停止する。
 */
function equal(actual,wanted,where) {
  if (!Number.isFinite(actual)||!Number.isFinite(wanted)||Math.abs(actual-wanted)>0.0001) throw new Error(`${where}: ${actual} / ${wanted}`);
}

/**
 * シートの基本書式を整える。
 * @param {object} sheet - 対象シート。
 * @param {string} end - 最終列。
 * @param {number} last - 最終行。
 * @param {string} title - 表題。
 * @param {string} note - 対象範囲の説明。
 * @returns {void} 返り値なし。
 */
function style(sheet,end,last,title,note) {
  sheet.showGridLines=false;
  sheet.tabColor='#244A70';
  sheet.getRange(`A1:${end}${last}`).format={font:{name:'Yu Gothic',size:10,color:'#1B3048'},rowHeight:23,columnWidth:15,verticalAlignment:'center'};
  sheet.getRange(`A1:A${last}`).format.columnWidth=27;
  sheet.getRange('A2').values=[[title]];
  sheet.getRange('A2').format.font={bold:true,size:14};
  sheet.getRange(`A2:${end}2`).format.borders={bottom:{style:'thin',color:'#A5B5C5'}};
  sheet.getRange('A3').values=[['日経mini・片方向上限10枚・手数料0・次正常ラージ気配代理。2026/09/21〜10/23の完了25夜。']];
  sheet.getRange('A4').values=[['利益・損失は新規実約定IDごとの全返済収支で分類。旧親単位の利益損失とは異なります。未測定は空欄。']];
  sheet.getRange('A5').values=[[note]];
  sheet.getRange('A3:A5').format.font={size:10,color:'#52677C'};
}

/**
 * 見出しとフィルターを持つ正式テーブルを作る。
 * @param {object} sheet - シート。
 * @param {string[]} headers - 見出し。
 * @param {string} end - 最終列。
 * @param {number} last - 最終データ行。
 * @param {string} name - 一意のテーブル名。
 * @returns {void} 返り値なし。
 */
function table(sheet,headers,end,last,name) {
  sheet.getRange(`A6:${end}6`).values=[headers];
  const t=sheet.tables.add(`A6:${end}${last}`,true,name);
  t.showFilterButton=true;
  sheet.getRange(`A6:${end}6`).format={fill:'#244A70',font:{bold:true,color:'#FFFFFF'},horizontalAlignment:'center',wrapText:true,rowHeight:44,borders:{insideVertical:{style:'thin',color:'#FFFFFF'}}};
  sheet.freezePanes.freezeRows(6);
}

/**
 * 金額のゼロ・赤字表示を設定する。
 * @param {object} sheet - シート。
 * @param {string} address - 範囲。
 * @returns {void} 返り値なし。
 */
function money(sheet,address) {
  const r=sheet.getRange(address);r.setNumberFormat(moneyFormat);r.format.horizontalAlignment='right';
  r.conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{fill:'#FBEAEC',font:{color:'#A02836'}}});
}

/**
 * 明細の元数値を表示列へ対応させる。
 * @param {object} row - 独立会計の一場。
 * @returns {object} 列名と値。nullは未測定。
 */
function detailValues(row) {
  return {B:row.profit,C:row.loss,F:row.target_net,G:row.post?.net??null,
    H:row.trail?.profit??null,I:row.trail?.loss??null,J:row.boundary?.profit??null,K:row.boundary?.loss??null,
    L:row.max_unrealized_loss,M:row.equity_drawdown,N:row.max_long,O:row.max_short,
    P:row.entries,Q:row.target_entries,R:row.entry_quantity,
    S:row.held_seconds===null?null:row.held_seconds/60,T:row.hedged_seconds===null?null:row.hedged_seconds/60,
    U:row.long_cap_seconds===null?null:row.long_cap_seconds/60,V:row.short_cap_seconds===null?null:row.short_cap_seconds/60,
    W:row.cap_rejected_notices,X:row.rejected_notices,Y:row.reentry_entries,Z:row.positive_decision_negative_fill};
}

// ----------------------------------------
// 手法別の25夜を正式テーブルにし、収支・累計・総計を数式にする。
for(const method of methods) {
  const sheet=details.get(method.id);
  const rows=[...method.rows].sort((a,b)=>a.session.localeCompare(b.session));
  if(rows.length!==25)throw new Error(`${method.id}: 完了25夜ではありません。`);
  const scope=method.saved_control?'保存対照。未測定の含み損・DD・返済内訳は空欄。':method.config.scope==='pre'?'P：新手法は米国開始15分前まで、後半は保存S04。含み損・DD・保有時間・返済内訳は前半だけ。':'N：新手法を全夜運転。含み損・DD・保有時間・返済内訳も全夜。';
  style(sheet,'Z',32,`${method.id}　全夜間の利益・損失・収支`,`${method.description}。${scope}`);
  let cumulative=0;
  rows.forEach((row,i)=>{
    const n=i+7;
    equal(row.profit-row.loss,row.net,`${method.id}/${row.session}`);
    sheet.getRange(`A${n}`).values=[[row.session]];
    const values=detailValues(row);
    for(const [col,value] of Object.entries(values)) {
      sheet.getRange(`${col}${n}`).values=[[value]];
      if(value!==null)expected.push([sheet.name,`${col}${n}`,value]);
    }
    for(const [col,key] of [['S','held_seconds'],['T','hedged_seconds'],['U','long_cap_seconds'],['V','short_cap_seconds']]) {
      if(row[key]!==null)sheet.getRange(`${col}${n}`).formulas=[[`=${row[key]}/60`]];
    }
    sheet.getRange(`D${n}:E${n}`).formulas=[[`=B${n}-C${n}`,i===0?`=D${n}`:`=E${n-1}+D${n}`]];
    if(row.post)sheet.getRange(`G${n}`).formulas=[[`=D${n}-F${n}`]];
    cumulative+=row.net;
    expected.push([sheet.name,`D${n}`,row.net],[sheet.name,`E${n}`,cumulative]);
  });
  sheet.getRange('A32').values=[['25夜累計／最大']];
  sheet.getRange('B32:E32').formulas=[['=SUM(B7:B31)','=SUM(C7:C31)','=B32-C32','=E31']];
  for(const col of Object.keys(detailValues(rows[0])).filter(x=>!['B','C'].includes(x))) {
    const values=rows.map(row=>detailValues(row)[col]).filter(v=>v!==null);
    if(values.length===0)continue;
    if(values.length!==25)throw new Error(`${method.id}/${col}: 欠測混在`);
    const maximum=['L','M','N','O'].includes(col);
    sheet.getRange(`${col}32`).formulas=[[`=${maximum?'MAX':'SUM'}(${col}7:${col}31)`]];
    expected.push([sheet.name,`${col}32`,maximum?Math.max(...values):values.reduce((s,v)=>s+v,0)]);
  }
  expected.push([sheet.name,'B32',method.summary.profit],[sheet.name,'C32',method.summary.loss],[sheet.name,'D32',method.summary.net],[sheet.name,'E32',method.summary.net]);
  table(sheet,['セッション','利益（円）','損失（円）','全夜収支（円）','累計（円）','対象区間収支','保存後半収支','利益追尾の利益','利益追尾の損失','境界清算の利益','境界清算の損失','最大含み損（円）','対象区間DD','最大買い枚数','最大売り枚数','全夜新規件数','対象区間新規','全新規枚数','保有（分）','両建て（分）','買い上限（分）','売り上限（分）','上限拒否・縮小件数','通知全拒否件数','実再参加件数','判断利益→実損失'], 'Z',31,`Method151_${method.id}`);
  money(sheet,'B7:M32');sheet.getRange('N7:R32').setNumberFormat('#,##0');sheet.getRange('S7:V32').setNumberFormat('#,##0.0');sheet.getRange('W7:Z32').setNumberFormat('#,##0');
  sheet.getRange('A32:Z32').format.font={bold:true};sheet.getRange('A32:Z32').format.borders={top:{style:'thin',color:'#A5B5C5'}};
  images.push([sheet,'Z',32]);
}

// ----------------------------------------
// 比較は手法別テーブルの総計と全夜収支から計算する。
const last=methods.length+6;
style(comparison,'T',last,'損切りなし両建てと利益玉トレーリング','Pは前半変更＋保存S04後半、Nは全夜変更。利益追尾益・境界損・含み損・DDはPでは前半のみ。');
methods.forEach((method,i)=>{
  const n=i+7,p=`'日経_${method.id}'!`,nets=`${p}$D$7:$D$31`;
  comparison.getRange(`A${n}:B${n}`).values=[[method.id,method.saved_control?'保存対照':method.config.scope==='pre'?'前半のみ変更':'全夜変更']];
  comparison.getRange(`C${n}:L${n}`).formulas=[[`=${p}B32`,`=${p}C32`,`=${p}D32`,`=IF(D${n}=0,"損失なし",C${n}/D${n})`,
    `=COUNTIF(${nets},">0")`,`=COUNTIF(${nets},"<0")`,`=MAX(0,-MIN(${nets}))`,
    `=IF(H${n}=0,0,-SUMIF(${nets},"<0",${nets})/H${n})`,
    `=IF(H${n}=0,0,MEDIAN(FILTER(-${nets},${nets}<0)))`,
    `=E${n}-MAX(0,LARGE(${nets},1))-MAX(0,LARGE(${nets},2))-MAX(0,LARGE(${nets},3))`]];
  comparison.getRange(`R${n}`).formulas=[[`=${p}P32`]];
  if(!method.saved_control) {
    for(const [col,source] of [['M','F'],['N','H'],['O','K'],['P','L'],['Q','M'],['S','W'],['T','Y']])comparison.getRange(`${col}${n}`).formulas=[[`=${p}${source}32`]];
    for(const [col,value] of [['M',method.target_summary.net],['N',method.summary.trail.profit],['O',method.summary.boundary.loss],['P',method.summary.max_unrealized_loss],['Q',method.summary.equity_drawdown],['S',method.summary.cap_rejected_notices],['T',method.summary.reentry_entries]])expected.push([comparison.name,`${col}${n}`,value]);
  }
  for(const [col,key] of [['C','profit'],['D','loss'],['E','net'],['F','pf'],['G','wins'],['H','losses'],['I','maxloss'],['J','avgloss'],['K','medianloss'],['L','ex3'],['R','entries']])if(method.summary[key]!==null)expected.push([comparison.name,`${col}${n}`,method.summary[key]]);
});
table(comparison,['手法ID','変更区間','総利益（円）','総損失（円）','全夜収支（円）','利益損失比','黒字場数','赤字場数','最大赤字（円）','平均赤字（円）','赤字中央値（円）','上位3黒字除外','対象区間収支','利益追尾の利益','境界清算の損失','最大含み損','対象区間DD','全夜新規件数','上限拒否・縮小','実再参加件数'],'T',last,'Comparison151');
comparison.getRange(`A1:A${last}`).format.columnWidth=12;
money(comparison,`C7:E${last}`);money(comparison,`I7:Q${last}`);comparison.getRange(`F7:F${last}`).setNumberFormat('0.00');
images.unshift([comparison,'T',last]);

// ----------------------------------------
// 途中場は完結玉・未完結玉の部分実現・未返済含みを分離し、25夜累計へ含めない。
const current=[...report.partial].sort((a,b)=>a.id.localeCompare(b.id));
style(partial,'M',current.length+6,'2026/10/26ナイト　取得済み途中だけの評価','21:13:52未満の既知資料。終端一括返済なし。完了25夜の統計から除外。含み損とDDは新手法の対象区間だけ。');
partial.getRange('A3').values=[['日経mini・片方向上限10枚・手数料0・次正常ラージ気配代理。']];
current.forEach((row,i)=>{
  const n=i+7;
  const long=row.lot_details.filter(l=>l.side>0).reduce((s,l)=>s+l.remaining,0);
  const short=row.lot_details.filter(l=>l.side<0).reduce((s,l)=>s+l.remaining,0);
  partial.getRange(`A${n}:M${n}`).values=[[row.id,row.risk_scope,null,row.unrealized,null,row.profit,row.loss,row.open_lot_realized,row.entries,long,short,row.max_unrealized_loss,row.equity_drawdown]];
  partial.getRange(`C${n}`).formulas=[[`=F${n}-G${n}+H${n}`]];partial.getRange(`E${n}`).formulas=[[`=C${n}+D${n}`]];
  for(const [col,value] of [['C',row.net],['D',row.unrealized],['E',row.equity],['F',row.profit],['G',row.loss],['H',row.open_lot_realized],['I',row.entries],['J',long],['K',short],['L',row.max_unrealized_loss],['M',row.equity_drawdown]])if(value!==null)expected.push([partial.name,`${col}${n}`,value]);
});
table(partial,['手法ID','リスク集計区間','全実現収支','未返済含み','合計時価','完結玉利益','完結玉損失','未完結玉部分実現','新規件数','残買い枚数','残売り枚数','最大含み損','対象区間DD'],'M',current.length+6,'Partial151');
money(partial,`C7:H${current.length+6}`);money(partial,`L7:M${current.length+6}`);
images.push([partial,'M',current.length+6]);

// ----------------------------------------
// 原値変更の伝播と復元、元会計照合、全シート描画、正式xlsx出力を行う。
const first=methods[0],probe=details.get(first.id),old=probe.getRange('B7').values[0][0];
probe.getRange('B7').values=[[old+123]];
equal(probe.getRange('D7').values[0][0],first.rows[0].net+123,'明細の入力変更');
equal(probe.getRange('E31').values[0][0],first.summary.net+123,'累計の入力変更');
equal(comparison.getRange('E7').values[0][0],first.summary.net+123,'比較への変更伝播');
probe.getRange('B7').values=[[old]];
workbook.recalculate();
for(const [name,cell,value] of expected)equal(workbook.worksheets.getItem(name).getRange(cell).values[0][0],value,`${name}/${cell}`);
const checks=path.join(work,'xlsx_checks');await fs.mkdir(checks,{recursive:true});await fs.mkdir(output,{recursive:true});await fs.mkdir(publicDir,{recursive:true});
const inspected=await workbook.inspect({kind:'table',range:'比較!A6:T10',include:'values,formulas',tableMaxRows:5,tableMaxCols:20,maxChars:6000});
await fs.writeFile(path.join(checks,'比較の検査.ndjson'),inspected.ndjson,'utf8');
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},maxChars:4000});
await fs.writeFile(path.join(checks,'式エラーの検査.ndjson'),errors.ndjson,'utf8');
for(const [sheet,col,row] of images) {
  const picture=await workbook.render({sheetName:sheet.name,range:`A1:${col}${row}`,scale:1,format:'png'});
  await fs.writeFile(path.join(checks,`${sheet.name}.png`),new Uint8Array(await picture.arrayBuffer()));
}
const afterHash=createHash('sha256').update(await fs.readFile(path.join(work,'report151.json'))).digest('hex');
if(afterHash!==reportHash)throw new Error('作成中に原会計が変更されました。');
const exported=await SpreadsheetFile.exportXlsx(workbook);await exported.save(path.join(output,filename));await fs.copyFile(path.join(output,filename),path.join(publicDir,filename));
await fs.writeFile(path.join(checks,'Excel計算との照合.json'),JSON.stringify({verified_cells:expected.length,sheets:methods.length+2,tables:methods.length+2,report_sha256:reportHash,complete_sessions:25,partial_excluded:true,unmeasured_remains_blank:true,input_change_propagated:true,restored:true},null,2),'utf8');
console.log(JSON.stringify({output:path.join(publicDir,filename),sheets:methods.length+2,verified:expected.length}));
