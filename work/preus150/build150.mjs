import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const work = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(work, '../..');
const output = path.join(root, 'outputs/00150_preus_activity');
const publication = path.join(root, 'アルゴリズム調査/00150_D07の米国前しきい値緩和と開始前リセット');
const filename = 'D07の積極性と全夜間損益.xlsx';
const inputPaths = ['report150.json', 'data/時刻前後の市場診断150.json', 'data/現物営業日21場の参考診断150.json'];
const inputBytes = await Promise.all(inputPaths.map(p => fs.readFile(path.join(work,p))));
const inputHashes = inputBytes.map((b,i) => ({path:inputPaths[i],sha256:createHash('sha256').update(b).digest('hex')}));
const [report,clocks,calendar] = inputBytes.map(b => JSON.parse(b.toString('utf8')));
const methods = [...report.methods];
if (methods[0].id !== 'C00' || new Set(methods.map(m => m.id)).size !== methods.length) throw new Error('C00と独立条件が必要です。');
const workbook = Workbook.create();
const comparison = workbook.worksheets.add('比較');
const details = new Map(methods.map(m => [m.id, workbook.worksheets.add(`日経_${m.id}`)]));
const current = workbook.worksheets.add('当夜途中');
const marketSheet = workbook.worksheets.add('時刻観測');
const expected = [];
const renders = [];
const formatMoney = '#,##0;[Red](#,##0);"—"';

/**
 * 元会計と計算結果を検算する。
 * @param {number} actual - セルの数値。
 * @param {number} wanted - 原会計の数値。
 * @param {string} label - 検算位置。
 * @returns {void} 不一致なら停止する。
 */
function equal(actual,wanted,label) {
  if (!Number.isFinite(actual) || !Number.isFinite(wanted) || Math.abs(actual-wanted)>0.0001) throw new Error(`${label}: ${actual} / ${wanted}`);
}

/**
 * 共通の読みやすい表書式を設定する。
 * @param {object} sheet - 対象シート。
 * @param {string} end - 最終列。
 * @param {number} rows - 最終行。
 * @param {string} title - 見出し。
 * @param {string} context - 条件説明。
 * @returns {void} 返り値なし。
 */
function style(sheet,end,rows,title,context) {
  sheet.showGridLines=false;
  sheet.tabColor='#244A70';
  const area=sheet.getRange(`A1:${end}${rows}`);
  area.format.font={name:'Yu Gothic',size:10,color:'#1B3048'};
  area.format.rowHeight=23;
  area.format.columnWidth=17;
  area.format.verticalAlignment='center';
  sheet.getRange(`A1:A${rows}`).format.columnWidth=27;
  sheet.getRange('A2').values=[[title]];
  sheet.getRange('A2').format.font={bold:true,size:14};
  sheet.getRange(`A2:${end}2`).format.borders={bottom:{style:'thin',color:'#A5B5C5'}};
  sheet.getRange('A3').values=[['日経mini・片方向上限10枚・手数料0円・気配差込み。2026/09/21〜10/23の既知25夜。']];
  sheet.getRange('A4').values=[[context]];
  sheet.getRange('A3:A5').format.font={size:10,color:'#52677C'};
}

/**
 * 明示名の正式なExcelテーブルを追加する。
 * @param {object} sheet - 対象シート。
 * @param {string[]} headers - 列見出し。
 * @param {number} begin - 見出し行。
 * @param {number} last - 最終データ行。
 * @param {string} end - 最終列。
 * @param {string} name - 表名。
 * @returns {void} 返り値なし。
 */
function table(sheet,headers,begin,last,end,name) {
  sheet.getRange(`A${begin}:${end}${begin}`).values=[headers];
  const t=sheet.tables.add(`A${begin}:${end}${last}`,true,name);
  t.showFilterButton=true;
  sheet.getRange(`A${begin}:${end}${begin}`).format={fill:'#244A70',font:{bold:true,color:'#FFFFFF'},
    horizontalAlignment:'center',wrapText:true,rowHeight:42,
    borders:{insideVertical:{style:'thin',color:'#FFFFFF'}}};
  if (begin===6) sheet.freezePanes.freezeRows(6);
}

/**
 * 金額と赤字セルを整える。
 * @param {object} sheet - 対象シート。
 * @param {string} address - 金額範囲。
 * @returns {void} 返り値なし。
 */
function money(sheet,address) {
  const range=sheet.getRange(address);
  range.setNumberFormat(formatMoney);
  range.format.horizontalAlignment='right';
  range.conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{fill:'#FBEAEC',font:{color:'#A02836'}}});
}

/**
 * JSONの原会計から独立に総計を求める。
 * @param {object[]} rows - 各セッションの原会計。
 * @returns {object} 合計と損失頻度。
 */
function totals(rows) {
  const sum=k=>rows.reduce((v,r)=>v+r[k],0);
  const nets=rows.map(r=>r.net).sort((a,b)=>b-a);
  return {profit:sum('profit'),loss:sum('loss'),net:sum('net'),entries:sum('entries'),
    pre:rows.reduce((s,r)=>s+r.pre.net,0),post:rows.reduce((s,r)=>s+r.post.net,0),
    wins:nets.filter(x=>x>0).length,losses:nets.filter(x=>x<0).length,
    maxloss:Math.max(0,-Math.min(...nets)),ex3:sum('net')-nets.slice(0,3).reduce((s,n)=>s+Math.max(0,n),0),
    zero_entries:rows.filter(r=>r.entries===0).length};
}

// ----------------------------------------
// 手法ごとの完了25夜。前後段と全夜の収支・累計はセル式で所有する。
for (const method of methods) {
  const rows=[...method.rows].sort((a,b)=>a.session.localeCompare(b.session));
  if (rows.length!==25 || new Set(rows.map(r=>r.session)).size!==25) throw new Error(`${method.id}:25夜ではありません。`);
  method.rows=rows;
  const sheet=details.get(method.id);
  style(sheet,'R',32,`${method.id}　全夜間の損益`,'利益・損失は完結親単位。前後は初回新規時刻で区分。最下行の保有率・枚数は平均、初回新規までの分数は中央値。');
  sheet.getRange('A5').values=[[method.description]];
  sheet.getRange('A7:R31').values=rows.map(r=>[r.session,r.pre.profit,r.pre.loss,null,r.post.profit,r.post.loss,null,null,null,null,null,r.entries,r.pre.entries,r.post.entries,r.max_per_side,r.pre_activity.holding_ratio,r.pre_activity.average_quantity,r.pre_activity.first_entry_delay_minutes]);
  let cumulative=0;
  rows.forEach((r,i)=>{
    const n=i+7;
    equal(r.pre.profit-r.pre.loss,r.pre.net,`${method.id}/${r.session}/前`);
    equal(r.post.profit-r.post.loss,r.post.net,`${method.id}/${r.session}/後`);
    equal(r.pre.profit+r.post.profit,r.profit,`${method.id}/${r.session}/利益`);
    equal(r.pre.loss+r.post.loss,r.loss,`${method.id}/${r.session}/損失`);
    equal(r.pre.net+r.post.net,r.net,`${method.id}/${r.session}/全夜`);
    sheet.getRange(`D${n}`).formulas=[[`=B${n}-C${n}`]];
    sheet.getRange(`G${n}:K${n}`).formulas=[[`=E${n}-F${n}`,`=B${n}+E${n}`,`=C${n}+F${n}`,`=H${n}-I${n}`,i===0?`=J${n}`:`=K${n-1}+J${n}`]];
    cumulative+=r.net;
    for (const [col,value] of [['D',r.pre.net],['G',r.post.net],['H',r.profit],['I',r.loss],['J',r.net],['K',cumulative]]) expected.push([sheet.name,`${col}${n}`,value]);
  });
  sheet.getRange('A32').values=[['25夜累計']];
  sheet.getRange('B32:R32').formulas=[['=SUM(B7:B31)','=SUM(C7:C31)','=B32-C32','=SUM(E7:E31)','=SUM(F7:F31)','=E32-F32','=B32+E32','=C32+F32','=H32-I32','=K31','=SUM(L7:L31)','=SUM(M7:M31)','=SUM(N7:N31)','=MAX(O7:O31)','=AVERAGE(P7:P31)','=AVERAGE(Q7:Q31)','=IF(COUNT(R7:R31)=0,"未参加",MEDIAN(R7:R31))']];
  table(sheet,['セッション','前半利益（円）','前半損失（円）','前半収支（円）','後半利益（円）','後半損失（円）','後半収支（円）','全夜利益（円）','全夜損失（円）','全夜収支（円）','累計（円）','新規件数','前半新規件数','後半新規件数','最大片側保有枚数','前半保有率','前半平均保有枚数','初回新規まで（分）'],6,31,'R',`Method150_${method.id}`);
  money(sheet,'B7:K32');
  sheet.getRange('L7:O32').setNumberFormat('#,##0');
  sheet.getRange('A32:R32').format.font={bold:true};
  sheet.getRange('A32:R32').format.borders={top:{style:'thin',color:'#A5B5C5'}};
  const s=totals(rows);
  for (const [col,value] of [['D',s.pre],['G',s.post],['H',s.profit],['I',s.loss],['J',s.net],['K',s.net],['L',s.entries]]) expected.push([sheet.name,`${col}32`,value]);
  sheet.getRange('P7:P32').setNumberFormat('0.0%');
  sheet.getRange('Q7:Q32').setNumberFormat('0.00');
  sheet.getRange('R7:R32').setNumberFormat('0.0');
  expected.push([sheet.name,'P32',method.pre_activity.mean_holding_ratio],[sheet.name,'Q32',method.pre_activity.mean_quantity]);
  if (method.pre_activity.median_first_entry_minutes!==null) expected.push([sheet.name,'R32',method.pre_activity.median_first_entry_minutes]);
  renders.push([sheet,'R',32]);
}

// ----------------------------------------
// 比較は各明細から参照し、入口緩和の差はA00に対する前半差で示す。
const last=methods.length+6;
const a00=methods.find(m=>m.id==='A00');
if (!a00) throw new Error('入口緩和の基準A00がありません。');
const a00Row=methods.indexOf(a00)+7;
style(comparison,'Q',last,'D07の前半積極性と全夜間損益','C00・S04・S02は149の保存対照を再会計。A00は17時解禁・前半補完なし。A01以降は前半だけ変更。');
comparison.getRange('A5').values=[['前半保有率は17時〜米国開始15分前に1枚以上持った時間。平均枚数は無保有時間も含む。']];
methods.forEach((method,i)=>{
  const n=i+7;
  const p=`'日経_${method.id}'!`;
  const nets=`${p}$J$7:$J$31`;
  const firstEntries=`${p}$R$7:$R$31`;
  comparison.getRange(`A${n}`).values=[[method.id]];
  comparison.getRange(`B${n}:Q${n}`).formulas=[[`=${p}D32`,`=${p}G32`,`=${p}J32`,`=${p}H32`,`=${p}I32`,`=IF(F${n}=0,"損失なし",E${n}/F${n})`,
    `=COUNTIFS(${nets},">0")`,`=COUNTIFS(${nets},"<0")`,`=MAX(0,-MIN(${nets}))`,
    `=D${n}-MAX(0,LARGE(${nets},1))-MAX(0,LARGE(${nets},2))-MAX(0,LARGE(${nets},3))`,
    `=${p}M32`,`=COUNT(${firstEntries})`,`=${p}P32`,`=${p}Q32`,`=${p}L32`,`=B${n}-$B$${a00Row}`]];
  const s=totals(method.rows);
  for (const [col,value] of [['B',s.pre],['C',s.post],['D',s.net],['E',s.profit],['F',s.loss],['H',s.wins],['I',s.losses],['J',s.maxloss],['K',s.ex3],['L',method.pre.entries],['M',method.pre_activity.participating_nights],['N',method.pre_activity.mean_holding_ratio],['O',method.pre_activity.mean_quantity],['P',s.entries],['Q',s.pre-totals(a00.rows).pre]]) expected.push([comparison.name,`${col}${n}`,value]);
  if (s.loss) expected.push([comparison.name,`G${n}`,s.profit/s.loss]);
});
table(comparison,['手法ID','前半収支（円）','後半収支（円）','全夜収支（円）','総利益（円）','総損失（円）','利益損失比','黒字場数','赤字場数','最大赤字（円）','上位3黒字除外（円）','前半新規件数','前半参加場数','前半保有率','前半平均保有枚数','全夜新規件数','A00前半差（円）'],6,last,'Q','Comparison150');
comparison.getRange(`A1:A${last}`).format.columnWidth=12;
money(comparison,`B7:F${last}`);money(comparison,`J7:K${last}`);money(comparison,`Q7:Q${last}`);
comparison.getRange(`G7:G${last}`).setNumberFormat('0.00');
comparison.getRange(`N7:N${last}`).setNumberFormat('0.0%');
comparison.getRange(`O7:O${last}`).setNumberFormat('0.00');
renders.unshift([comparison,'Q',last]);

// ----------------------------------------
// 取得済み当夜は実現と含みを分離し、25夜合計へ加算しない。
const partial=[...report.partial].sort((a,b)=>a.id.localeCompare(b.id));
style(current,'F',partial.length+6,'2026/10/26ナイト　取得済み途中評価','21:13:52まで。既知3波を含む資料。終端一括返済をせず、完了25夜の合計から除外。');
current.getRange('A3').values=[['日経mini・片方向上限10枚・手数料0円・気配差込み。当夜の取得済み範囲だけを表示。']];
partial.forEach((row,i)=>{
  const n=i+7;
  current.getRange(`A${n}:F${n}`).values=[[row.id,row.net,row.unrealized,null,row.entries,row.max_per_side]];
  current.getRange(`D${n}`).formulas=[[`=B${n}+C${n}`]];
  equal(row.net+row.unrealized,row.equity,`${row.id}/途中評価`);
  expected.push([current.name,`D${n}`,row.equity]);
});
table(current,['手法ID','実現収支（円）','含み損益（円）','合計評価（円）','新規件数','最大片側保有枚数'],6,partial.length+6,'F','Partial150');
money(current,`B7:D${partial.length+6}`);
renders.push([current,'F',partial.length+6]);

// ----------------------------------------
// 時計窓を場単位で比較し、固定25日の主分析と参考21営業日を区別する。
const marketRows=[];
/**
 * 記述統計の要約行を追加する。
 * @param {string} group - 観測集団。
 * @param {string} comparisonName - 比較窓。
 * @param {string} label - 指標名。
 * @param {string} unit - 単位。
 * @param {object} item - 場単位の対比較。
 * @returns {void} 返り値なし。
 */
function marketRow(group,comparisonName,label,unit,item) {
  marketRows.push([group,comparisonName,label,unit,item.n,item.event_mean,item.control_mean,null,...item.mean_difference_ci95]);
}
for (const [group,source] of [['9時25時計窓',clocks.groups['デイ']],['9時21営業日参考',calendar.comparisons],['米国25夜',clocks.groups['ナイト']]]) {
  for (const [metric,label,unit] of [['abs_change_mean','絶対1分変化の平均','pt'],['range_mid','正常中値の高低差','pt'],['spread_p90','分末気配差の90%点','pt'],['jump_50_rate','50pt以上変化の率','割合'],['jump_100_rate','100pt以上変化の率','割合'],['jump_200_rate','200pt以上変化の率','割合']]) {
    marketRow(group,'直後15分 − 次15分',label,unit,source['開始後15分対次15分'].metrics[metric]);
  }
}
marketRow('米国25夜','直前15分 − 直後15分','絶対1分変化の平均','pt',clocks.groups['ナイト']['直前15分対開始後15分'].metrics.abs_change_mean);
marketRow('米国25夜','前後30分 − 次30分','絶対1分変化の平均','pt',clocks.groups['ナイト']['イベント対直後30分'].metrics.abs_change_mean);
const marketLast=marketRows.length+6;
style(marketSheet,'J',marketLast+5,'9時と米国開始の前後の値動き','直後15分は開始〜15分後、次15分は15〜30分後。差の95%区間は場単位の再標本化。');
marketSheet.getRange('A3').values=[['日経ラージの正常気配。9/21〜10/23のデイ25・夜25。利益や勝率の表ではありません。']];
marketSheet.getRange('A5').values=[['9時と米国開始の直後は活発。米国開始前15分は静かで、前後全体が一様に急変するわけではない。']];
marketSheet.getRange(`A7:J${marketLast}`).values=marketRows;
marketRows.forEach((row,i)=>{
  const n=i+7;
  marketSheet.getRange(`H${n}`).formulas=[[`=F${n}-G${n}`]];
  marketSheet.getRange(`F${n}:J${n}`).setNumberFormat(row[3]==='割合'?'0.0%':'#,##0.0');
  expected.push([marketSheet.name,`H${n}`,row[5]-row[6]]);
});
table(marketSheet,['観測集団','比較窓','指標','単位','比較場数','対象平均','対照平均','差','差95%下限','差95%上限'],6,marketLast,'J','Market150');
marketSheet.getRange(`A1:A${marketLast+5}`).format.columnWidth=24;
marketSheet.getRange(`B1:B${marketLast+5}`).format.columnWidth=30;
marketSheet.getRange(`C1:C${marketLast+5}`).format.columnWidth=30;
marketSheet.getRange(`D1:E${marketLast+5}`).format.columnWidth=12;
marketSheet.getRange(`A${marketLast+2}`).values=[['21営業日は元25場を変更しない追加参考診断。9/21・22・23・10/12の現物休場を公式カレンダーで区別。']];
marketSheet.getRange(`A${marketLast+3}`).values=[['出典：JPX休業日一覧 https://www.jpx.co.jp/corporate/about-jpx/calendar/index.html']];
marketSheet.getRange(`A${marketLast+4}`).values=[['分母は各場の観測できた連続1分差。空分は補完せず、異常BBOは除外済み。価格時計と受信時計は別。']];
renders.push([marketSheet,'J',marketLast+4]);

// ----------------------------------------
// 入力の変更伝播を確認し、原値へ戻してから全表を検算・描画・保存する。
const probe=details.get('C00');
const old=probe.getRange('B7').values[0][0];
const firstNet=methods[0].rows[0].net;
const baseline=totals(methods[0].rows).net;
probe.getRange('B7').values=[[old+123]];
equal(probe.getRange('J7').values[0][0],firstNet+123,'入力変更と全夜収支');
equal(probe.getRange('K31').values[0][0],baseline+123,'入力変更と累計');
equal(comparison.getRange('D7').values[0][0],baseline+123,'入力変更と比較');
probe.getRange('B7').values=[[old]];
workbook.recalculate();
for (const [name,cell,value] of expected) equal(workbook.worksheets.getItem(name).getRange(cell).values[0][0],value,`${name}/${cell}`);
await fs.mkdir(output,{recursive:true});
await fs.mkdir(publication,{recursive:true});
const checks=path.join(work,'xlsx_checks');
await fs.mkdir(checks,{recursive:true});
const inspected=await workbook.inspect({kind:'table',range:'比較!A6:Q10',include:'values,formulas',tableMaxRows:5,tableMaxCols:17,maxChars:6500});
await fs.writeFile(path.join(checks,'比較の検査.ndjson'),inspected.ndjson,'utf8');
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},maxChars:5000});
await fs.writeFile(path.join(checks,'式エラーの検査.ndjson'),errors.ndjson,'utf8');
let firstReport=null;
try { firstReport=JSON.parse(await fs.readFile(path.join(work,'first_report150.json'),'utf8')); } catch (error) { if (error.code!=='ENOENT') throw error; }
const renderReused=[];
for (const [sheet,col,row] of renders) {
  if (process.env.PREUS150_RENDER_ONLY && process.env.PREUS150_RENDER_ONLY!==sheet.name) continue;
  const picture=path.join(checks,`${sheet.name}.png`);
  let exists=true;
  try { await fs.access(picture); } catch { exists=false; }
  const identifier=sheet.name.startsWith('日経_')?sheet.name.slice(3):null;
  const previous=identifier && firstReport?.methods.find(m=>m.id===identifier);
  const unchanged=previous && JSON.stringify(previous)===JSON.stringify(methods.find(m=>m.id===identifier));
  if (exists && firstReport && (unchanged || sheet===marketSheet)) {
    renderReused.push(sheet.name);
    continue;
  }
  const image=await workbook.render({sheetName:sheet.name,range:`A1:${col}${row}`,scale:1,format:'png'});
  await fs.writeFile(picture,new Uint8Array(await image.arrayBuffer()));
}
const exported=await SpreadsheetFile.exportXlsx(workbook);
for (const input of inputHashes) {
  const currentHash=createHash('sha256').update(await fs.readFile(path.join(work,input.path))).digest('hex');
  if (currentHash!==input.sha256) throw new Error(`作成中に原会計・観測資料が変更されました: ${input.path}`);
}
await exported.save(path.join(output,filename));
await fs.copyFile(path.join(output,filename),path.join(publication,filename));
await fs.writeFile(path.join(checks,'Excel計算との照合.json'),JSON.stringify({verified_cells:expected.length,sheets:methods.length+3,tables:methods.length+3,complete_sessions:25,partial_excluded:true,input_change_propagated:true,restored:true,unchanged_render_reused:renderReused,inputs:inputHashes,output:path.join(publication,filename)},null,2),'utf8');
console.log(JSON.stringify({output:path.join(publication,filename),sheets:methods.length+3,verified:expected.length}));
