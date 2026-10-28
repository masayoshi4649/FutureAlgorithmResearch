import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../../..');
const work = path.dirname(here);
const source = path.join(work, 'report_data163.json');
const sourceBytes = await fs.readFile(source);
const report = JSON.parse(sourceBytes.toString('utf8'));
const sourceHash = createHash('sha256').update(sourceBytes).digest('hex');
const authoring = JSON.parse(await fs.readFile(path.join(here, 'authoring開始163.json'), 'utf8'));
if (!authoring.marker_executed || authoring.returncode !== 0) throw new Error('初回作者markerの記録が必要');
const completion = JSON.parse(await fs.readFile(path.join(work, '再生全完了163.json'), 'utf8'));
if (!completion.completed || completion.returncode !== 0) throw new Error('金融結果の確定前');
const qa = path.join(here, 'xlsx_checks');
const publicDir = path.join(root, 'アルゴリズム調査/00163_元手法への局所減枚と復元');
const outputDir = path.join(root, 'outputs/00163_transfer');
const filename = '元手法の局所減枚と復元の全セッション損益.xlsx';
const checks = [], tables = [], renders = [];
const money = '#,##0;[Red](#,##0);"—"';
const wb = Workbook.create();
const comparison = wb.worksheets.add('比較');
const methods = report.methods;
const sheets = new Map(methods.map(m => [m.id, wb.worksheets.add(`日経_${m.id}`)]));
if (methods.length !== 11 || sheets.size !== methods.length) throw new Error('条件数又はID重複');

/**
 * 元会計値との一致を確認する。
 * @param {number} actual - 表の計算値。
 * @param {number} expected - 原会計値。
 * @param {string} label - 照合対象。
 * @returns {void} 不一致時は例外。
 */
function equal(actual, expected, label) {
  if (!Number.isFinite(actual) || !Number.isFinite(expected) || Math.abs(actual - expected) > 1e-5) throw new Error(`${label}: ${actual} / ${expected}`);
}

/**
 * 保存値の独立検査用セルを登録する。
 * @param {object} sheet - シート。
 * @param {string} address - セル番地。
 * @param {number} expected - 原会計値。
 * @returns {void} 返り値なし。
 */
function expect(sheet, address, expected) {
  if (!Number.isFinite(expected)) throw new Error(`未確定値: ${sheet.name}/${address}`);
  checks.push([sheet.name, address, expected]);
}

/**
 * 表題と共通の読みやすい書式を設定する。
 * @param {object} sheet - シート。
 * @param {string} end - 最終列。
 * @param {number} last - 最終行。
 * @param {string} title - 表題。
 * @param {string} description - 短い説明。
 * @param {string} note - 会計又は制約の注記。
 * @returns {void} 返り値なし。
 */
function style(sheet, end, last, title, description, note) {
  sheet.showGridLines = false;
  sheet.getRange(`A1:${end}${last}`).format = {font: {name: 'Yu Gothic', size: 10, color: '#20384D'},
    rowHeight: 25, columnWidth: 16, verticalAlignment: 'center'};
  sheet.getRange('A1').format.rowHeight = 10;
  sheet.getRange('A2').values = [[title]];
  sheet.getRange('A2').format.font = {size: 14, bold: true};
  sheet.getRange('A3').values = [[description]];
  sheet.getRange('A4').values = [[note]];
  sheet.getRange('A3:A4').format.font = {size: 10, color: '#536B80'};
  sheet.getRange(`C6:${end}${last}`).format.horizontalAlignment = 'right';
  sheet.getRange(`C6:${end}${last}`).setNumberFormat(money);
  sheet.freezePanes.freezeRows(5);
}

/**
 * 正式Excelテーブルと見出し書式を設定する。
 * @param {object} sheet - シート。
 * @param {string[]} headers - 日本語見出し。
 * @param {string} end - 最終列。
 * @param {number} last - 最終明細行。
 * @param {string} name - 一意なテーブル名。
 * @returns {void} 返り値なし。
 */
function table(sheet, headers, end, last, name) {
  sheet.getRange(`A5:${end}5`).values = [headers];
  const t = sheet.tables.add(`A5:${end}${last}`, true, name);
  t.showFilterButton = true;
  sheet.getRange(`A5:${end}5`).format = {fill: '#264D70', font: {bold: true, color: '#FFFFFF'},
    rowHeight: 45, wrapText: true, horizontalAlignment: 'center'};
  tables.push({sheet: sheet.name, name, reference: `A5:${end}${last}`, rows: last - 5});
}

/**
 * 赤字を見分ける条件書式を設定する。
 * @param {object} sheet - シート。
 * @param {string} range - 対象範囲。
 * @returns {void} 返り値なし。
 */
function negative(sheet, range) {
  sheet.getRange(range).conditionalFormats.add('cellIs', {operator: 'lessThan', formula: 0,
    format: {fill: '#FBE9EB', font: {color: '#9C2632'}}});
}

// ----------------------------------------
// 全53場の実配賦金額。F00は事前固定した昼夜案の保存行を連結する。
for (const m of methods) {
  const sheet = sheets.get(m.id), last = m.rows.length + 5, total = last + 1;
  if (m.rows.length !== 53) throw new Error(`場数不一致: ${m.id}`);
  style(sheet, 'J', total, `日経 ${m.id}　全セッション損益`, m.description,
    '片側micro100枚＝mini10枚相当／費用0。利益・損失は返済配賦別。ラージ次気配約定。全53場は既知資料。');
  sheet.getRange(`A1:A${total}`).format.columnWidth = 25;
  sheet.getRange(`B1:B${total}`).format.columnWidth = 12;
  sheet.getRange(`J1:J${total}`).format.columnWidth = 12;
  let cumulative = 0;
  m.rows.forEach((r, i) => {
    const n = i + 6;
    equal(r.profit - r.loss, r.net, `${m.id}/${r.session}`);
    cumulative += r.net;
    equal(cumulative, r.cumulative, `${m.id}/${r.session}/累計`);
    const split = {train: '前30場', validation: '次10場', test: '後13場'}[r.split];
    if (!split) throw new Error('未知の資料区分');
    sheet.getRange(`A${n}:J${n}`).values = [[r.session, split, r.profit, r.loss, null, null,
      r.minimum_equity, r.maximum_dd, r.new_orders, r.component]];
    sheet.getRange(`E${n}:F${n}`).formulas = [[`=C${n}-D${n}`, i ? `=F${n-1}+E${n}` : `=E${n}`]];
    ['C','D','E','F','G','H','I'].forEach((col, j) => expect(sheet, `${col}${n}`,
      [r.profit,r.loss,r.net,cumulative,r.minimum_equity,r.maximum_dd,r.new_orders][j]));
  });
  table(sheet, ['セッション','資料区分','利益（円）','損失（円）','収支（円）','累計（円）',
    '場内最悪収支（円）','最大下落額（円）','新規回数','実行条件'], 'J', last, `R163_${m.id}`);
  sheet.getRange(`I6:I${total}`).setNumberFormat('0');
  sheet.getRange(`J6:J${last}`).format.horizontalAlignment = 'left';
  sheet.getRange(`A${total}`).values = [['累計／場内最悪値']];
  sheet.getRange(`C${total}:I${total}`).formulas = [[`=SUM(C6:C${last})`,`=SUM(D6:D${last})`,`=C${total}-D${total}`,
    `=F${last}`,`=MIN(G6:G${last})`,`=MAX(H6:H${last})`,`=SUM(I6:I${last})`]];
  sheet.getRange(`A${total}:J${total}`).format = {font: {bold: true}, borders: {top: {style: 'thin', color: '#93AABD'}}};
  const s = m.summary['全場_全場'];
  ['C','D','E','F','G','H','I'].forEach((col, i) => expect(sheet, `${col}${total}`,
    [s.profit,s.loss,s.net,s.net,s.worst_equity,s.maximum_dd,m.rows.reduce((n,r)=>n+r.new_orders,0)][i]));
  negative(sheet, `E6:G${last}`);
  renders.push([sheet.name, `A1:J${total}`]);
}

// ----------------------------------------
// 同じ比較表で全体・昼・夜・後半を区別。総額だけでなく赤字の頻度と深さを併記する。
const groups = [['全場_全場','全53場'],['Day_全場','日中27場'],['Night_全場','夜間26場'],
  ['全場_前40','前40場'],['Day_前40','前40の日中'],['Night_前40','前40の夜間'],
  ['全場_後13','後13場'],['Day_後13','後13の日中'],['Night_後13','後13の夜間']];
const rows = groups.flatMap(([key, label]) => methods.map(m => [key,label,m]));
const last = rows.length + 5;
style(comparison, 'M', last, '元手法の局所減枚と復元の比較',
  '片側micro100枚＝mini10枚相当／費用0。場内最悪は確定＋全玉含み、最大下落は当場ピークから。C50は一律半量の対照。',
  `前40場で昼${report.selected.Day}・夜${report.selected.Night}を固定しF00へ連結。後13場も既知資料。運用採用を意味しない。`);
comparison.getRange(`A1:A${last}`).format.columnWidth = 16;
comparison.getRange(`B1:B${last}`).format.columnWidth = 11;
comparison.getRange(`C1:C${last}`).format.columnWidth = 14;
comparison.getRange(`G1:H${last}`).format.columnWidth = 12;
rows.forEach(([key,label,m], i) => {
  const n = i + 6, s = m.summary[key], sn = `'日経_${m.id}'`, end = m.rows.length + 5;
  const selected = m.id==='F00'?'固定昼夜合成':Object.entries(report.selected).filter(([,v])=>v===m.id).map(([k])=>k==='Day'?'昼選択':'夜選択').join('・');
  comparison.getRange(`A${n}:M${n}`).values = [[label,m.id,selected,null,null,null,
    s.negative_sessions,s.no_entries,-s.mean_red,Math.max(0,-s.minimum_session),
    s.worst_equity,s.maximum_dd,s.excluding_top3]];
  const [kind, split] = key.split('_');
  const matchingRows = m.rows.flatMap((row, index) =>
    (kind==='全場'||row.kind===kind) && (split==='全場'||(row.split==='test')===(split==='後13')) ? [index+6] : []);
  equal(matchingRows.length,s.sessions,`${key}/分母`);
  const sum = col => key==='全場_全場'?`SUM(${sn}!${col}6:${col}${end})`:
    `SUM(${matchingRows.map(row => `${sn}!${col}${row}`).join(',')})`;
  comparison.getRange(`D${n}:F${n}`).formulas = [[`=${sum('C')}`,`=${sum('D')}`,`=D${n}-E${n}`]];
  comparison.getRange(`A${n}:C${n}`).format.horizontalAlignment = 'left';
  ['D','E','F','G','H','I','J','K','L','M'].forEach((col,j) => expect(comparison,`${col}${n}`,
    [s.profit,s.loss,s.net,s.negative_sessions,s.no_entries,-s.mean_red,Math.max(0,-s.minimum_session),
      s.worst_equity,s.maximum_dd,s.excluding_top3][j]));
});
table(comparison,['対象','手法','事前選択','利益（円）','損失（円）','収支（円）','赤字場数','無取引場数',
  '平均赤字（円）','最大赤字（円）','場内最悪収支（円）','最大下落額（円）','大勝ち3場除外収支（円）'],'M',last,'R163_comparison');
comparison.getRange(`G6:H${last}`).setNumberFormat('0');
negative(comparison,`F6:F${last}`); negative(comparison,`K6:K${last}`); negative(comparison,`M6:M${last}`);
renders.unshift([comparison.name, `A1:M${last}`]);

// ----------------------------------------
// 一度の最終再計算、全セル照合、全シート描画、正式xlsx保存を順に行う。
wb.recalculate();
for (const [name,address,value] of checks) equal(wb.worksheets.getItem(name).getRange(address).values[0][0], value, `${name}/${address}`);
await fs.mkdir(qa, {recursive: true});
const inspect = await wb.inspect({kind:'table',range:'比較!A1:M31',include:'values,formulas',tableMaxRows:31,tableMaxCols:13});
await fs.writeFile(path.join(qa,'比較の検査.ndjson'), inspect.ndjson, 'utf8');
const errors = await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',
  options:{useRegex:true,maxResults:100},summary:'式エラー検査'});
await fs.writeFile(path.join(qa,'式エラーの検査.ndjson'), errors.ndjson, 'utf8');
const previews=[];
for (const [sheetName,range] of renders) {
  const image = await wb.render({sheetName,range,scale:1.25,format:'png'});
  const target=path.join(qa,`${sheetName}.png`);
  await fs.writeFile(target,new Uint8Array(await image.arrayBuffer()));
  previews.push({sheet:sheetName,path:target,range});
}
await fs.mkdir(outputDir,{recursive:true}); await fs.mkdir(publicDir,{recursive:true});
const workbook = await SpreadsheetFile.exportXlsx(wb);
const target=path.join(outputDir,filename), publicPath=path.join(publicDir,filename);
await workbook.save(target); await fs.copyFile(target,publicPath);
const workbookHash=createHash('sha256').update(await fs.readFile(target)).digest('hex');
if(createHash('sha256').update(await fs.readFile(source)).digest('hex')!==sourceHash)throw new Error('確定会計が途中で変更された');
await fs.writeFile(path.join(qa,'Excel照合163.json'),JSON.stringify({passed:true,checks:checks.length,check_cells:checks,
  sheets:methods.length+1,tables,previews,source_sha256:sourceHash,workbook_sha256:workbookHash,output:publicPath,
  known_development:true,terminal_proxy:false,native_excel_recalculation:false},null,2),'utf8');
console.log(JSON.stringify({passed:true,sheets:methods.length+1,checks:checks.length,source_sha256:sourceHash,workbook_sha256:workbookHash,output:publicPath}));
