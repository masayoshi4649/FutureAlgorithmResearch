import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const source = path.join(here, 'report158.json');
const sourceBytes = await fs.readFile(source);
const report = JSON.parse(sourceBytes.toString('utf8'));
const sourceHash = createHash('sha256').update(sourceBytes).digest('hex');
const outputDir = path.join(root, 'outputs/00158_comparison');
const publicDir = path.join(root, 'アルゴリズム調査/00158_D07と改修候補の比較と未解決点');
const qaDir = path.join(here, 'xlsx_checks');
const filename = 'D07と改修候補の日中損益.xlsx';
const wb = Workbook.create();
const summary = wb.worksheets.add('比較');
const sheets = new Map(report.methods.map(m => [m.id, wb.worksheets.add(`日経_${m.id}`)]));
const checks = [];
const money = '#,##0;[Red](#,##0);"—"';
const expectedIds = ['D07', 'S01', 'J02', 'O01', 'O05', 'F05'];
if (JSON.stringify(report.methods.map(m => m.id)) !== JSON.stringify(expectedIds)) throw new Error('比較対象が不一致');
if (report.definition.financial_replays !== 0) throw new Error('保存再集計でない入力');

/**
 * 元会計との一致を検査する。
 * @param {number} actual - Excel計算値。
 * @param {number} expected - 保存会計値。
 * @param {string} label - 対象名。
 * @returns {void} 不一致なら停止する。
 */
function equal(actual, expected, label) {
  if (!Number.isFinite(actual) || !Number.isFinite(expected) || Math.abs(actual - expected) > 1e-6) {
    throw new Error(`${label}: ${actual} / ${expected}`);
  }
}

/**
 * 最終照合するセルを登録する。
 * @param {object} sheet - 対象シート。
 * @param {string} address - セル番地。
 * @param {number} expected - 元会計値。
 * @returns {void} 返り値なし。
 */
function expect(sheet, address, expected) {
  if (!Number.isFinite(expected)) throw new Error(`元数値なし: ${sheet.name}/${address}`);
  checks.push([sheet.name, address, expected]);
}

/**
 * 読みやすい共通書式を設定する。
 * @param {object} sheet - 対象シート。
 * @param {string} lastColumn - 最終列名。
 * @param {number} lastRow - 最終行。
 * @param {string} title - 表題。
 * @param {string} description - 短い説明。
 * @param {string} note - 範囲・単位。
 * @returns {void} 返り値なし。
 */
function style(sheet, lastColumn, lastRow, title, description, note) {
  sheet.showGridLines = false;
  sheet.getRange(`A1:${lastColumn}${lastRow}`).format = {
    font: {name: 'Yu Gothic', size: 10, color: '#21384D'},
    rowHeight: 25, columnWidth: 18, verticalAlignment: 'center',
  };
  sheet.getRange('A1').format.rowHeight = 10;
  sheet.getRange('A2').values = [[title]];
  sheet.getRange('A2').format.font = {size: 14, bold: true};
  sheet.getRange('A3').values = [[description]];
  sheet.getRange('A4').values = [[note]];
  sheet.getRange('A3:A4').format.font = {size: 10, color: '#536B80'};
  sheet.getRange(`B6:${lastColumn}${lastRow}`).format.horizontalAlignment = 'right';
  sheet.getRange(`B6:${lastColumn}${lastRow}`).setNumberFormat(money);
}

/**
 * 正式Excelテーブルを作る。
 * @param {object} sheet - 対象シート。
 * @param {string[]} headers - 列名。
 * @param {string} end - 最終列。
 * @param {number} last - 明細最終行。
 * @param {string} name - 一意のテーブル名。
 * @returns {void} 返り値なし。
 */
function table(sheet, headers, end, last, name) {
  sheet.getRange(`A5:${end}5`).values = [headers];
  const t = sheet.tables.add(`A5:${end}${last}`, true, name);
  t.showFilterButton = true;
  sheet.getRange(`A5:${end}5`).format = {
    fill: '#264D70', font: {bold: true, color: '#FFFFFF'},
    rowHeight: 43, wrapText: true, horizontalAlignment: 'center',
  };
}

/**
 * 赤字を条件付き書式で区別する。
 * @param {object} sheet - 対象シート。
 * @param {string} range - 金額範囲。
 * @returns {void} 返り値なし。
 */
function losses(sheet, range) {
  sheet.getRange(range).conditionalFormats.add('cellIs', {
    operator: 'lessThan', formula: 0,
    format: {fill: '#FBE9EB', font: {color: '#9C2632'}},
  });
}

// ----------------------------------------
// 6手法の同じ26場を各シートへ置き、利益と損失から収支・累計を求める。
for (const method of report.methods) {
  const sheet = sheets.get(method.id);
  if (method.rows.length !== 26) throw new Error(`${method.id}: 26場でない`);
  style(sheet, 'H', 32, `日経 ${method.id}　日中損益`, method.description,
    '片側mini10枚相当・手数料0。途中最悪は確定＋含み、最大下落は当場ピークからの落差。');
  sheet.getRange('A1:A32').format.columnWidth = 25;
  sheet.getRange('B1:B32').format.columnWidth = 12;
  method.rows.forEach((row, index) => {
    const n = index + 6;
    equal(row.profit - row.loss, row.net, `${method.id}/${row.session}`);
    sheet.getRange(`A${n}:H${n}`).values = [[row.session, row.direction, row.profit, row.loss,
      null, null, row.intraday_risk.min_equity, row.intraday_risk.max_drawdown]];
    sheet.getRange(`E${n}:F${n}`).formulas = [[`=C${n}-D${n}`, index === 0 ? `=E${n}` : `=F${n - 1}+E${n}`]];
    sheet.getRange(`B${n}`).format.horizontalAlignment = 'left';
    for (const [col, value] of [['C', row.profit], ['D', row.loss], ['E', row.net], ['F', row.cumulative],
      ['G', row.intraday_risk.min_equity], ['H', row.intraday_risk.max_drawdown]]) expect(sheet, `${col}${n}`, value);
  });
  table(sheet, ['セッション', '場の方向', '利益（円）', '損失（円）', '収支（円）', '累計（円）',
    '途中最悪収支（円）', '最大下落額（円）'], 'H', 31, `D158_${method.id}`);
  sheet.freezePanes.freezeRows(5);
  sheet.getRange('A32').values = [['累計／場内最悪値']];
  sheet.getRange('C32:H32').formulas = [['=SUM(C6:C31)', '=SUM(D6:D31)', '=C32-D32', '=F31', '=MIN(G6:G31)', '=MAX(H6:H31)']];
  sheet.getRange('A32:H32').format = {font: {bold: true}, borders: {top: {style: 'thin', color: '#93AABD'}}};
  for (const [col, key] of [['C', 'profit'], ['D', 'loss'], ['E', 'net'], ['F', 'net'], ['G', 'min_equity'], ['H', 'max_drawdown']]) {
    expect(sheet, `${col}32`, method.summary[key]);
  }
  losses(sheet, 'E6:G31');
}

// ----------------------------------------
// 比較表は各手法シートの計算値へ接続する。各手法の上位3黒字場を除く。
style(summary, 'M', 11, 'D07と改修候補の日中比較',
  '同じ完了26デイ・日経mini10枚相当・手数料0。保存済み結果を同じ親会計で比較。',
  'D07は00154の現行Go基準。夜間と途中場を含めず、全6手法に無取引場なし。');
summary.tabColor = '#264D70';
summary.getRange('A1:A11').format.columnWidth = 14;
summary.getRange('B1:M11').format.columnWidth = 17;
for (const [index, method] of report.methods.entries()) {
  const n = index + 6;
  const sn = `'日経_${method.id}'`;
  summary.getRange(`A${n}`).values = [[method.id]];
  summary.getRange(`B${n}:M${n}`).formulas = [[
    `=${sn}!C32`, `=${sn}!D32`, `=${sn}!E32`, `=D${n}-$D$6`,
    `=COUNTIF(${sn}!E6:E31,"<0")`, `=-SUMIF(${sn}!E6:E31,"<0")/F${n}`,
    `=-MIN(${sn}!E6:E31)`,
    `=D${n}-MAX(0,LARGE(${sn}!E6:E31,1))-MAX(0,LARGE(${sn}!E6:E31,2))-MAX(0,LARGE(${sn}!E6:E31,3))`,
    `=${sn}!G32`, `=${sn}!H32`, `=COUNTA(${sn}!A6:A31)`,
    `=COUNTIF(${sn}!E6:E31,"=0")`,
  ]];
  const s = method.summary;
  for (const [col, value] of [['B', s.profit], ['C', s.loss], ['D', s.net], ['E', s.vs_d07], ['F', s.losses],
    ['G', s.avgloss], ['H', s.maxloss], ['I', s.ex3], ['J', s.min_equity], ['K', s.max_drawdown], ['L', 26], ['M', s.zero]]) {
    expect(summary, `${col}${n}`, value);
  }
}
table(summary, ['手法', '利益（円）', '損失（円）', '収支（円）', 'D07との差（円）', '赤字場数',
  '平均赤字（円）', '最大赤字（円）', '上位3黒字除外（円）', '途中最悪収支（円）', '最大下落額（円）', '対象場数', '収支ゼロ場'],
  'M', 11, 'D158_comparison');
losses(summary, 'D6:E11');
losses(summary, 'I6:J11');

// ----------------------------------------
// 式の再計算、原会計照合、入力変化への連動、描画、保存を一度のビルダーで実行する。
wb.recalculate();
for (const [name, address, value] of checks) equal(wb.worksheets.getItem(name).getRange(address).values[0][0], value, `${name}/${address}`);
const testSheet = sheets.get('D07');
const original = testSheet.getRange('C6').values[0][0];
testSheet.getRange('C6').values = [[original + 100]];
wb.recalculate();
equal(summary.getRange('D6').values[0][0], report.methods[0].summary.net + 100, '入力変更と累計連動');
testSheet.getRange('C6').values = [[original]];
wb.recalculate();
for (const [name, address, value] of checks) equal(wb.worksheets.getItem(name).getRange(address).values[0][0], value, `復元/${name}/${address}`);
await fs.mkdir(qaDir, {recursive: true});
const inspected = await wb.inspect({kind: 'table', range: '比較!A1:M11', include: 'values,formulas', tableMaxRows: 11, tableMaxCols: 13});
await fs.writeFile(path.join(qaDir, '比較の検査.ndjson'), inspected.ndjson, 'utf8');
const errors = await wb.inspect({kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',
  options: {useRegex: true, maxResults: 100}, summary: '最終式エラー検査'});
await fs.writeFile(path.join(qaDir, '式エラーの検査.ndjson'), errors.ndjson, 'utf8');
const previews = [];
for (const name of ['比較', ...report.methods.map(m => `日経_${m.id}`)]) {
  const image = await wb.render({sheetName: name, range: name === '比較' ? 'A1:M11' : 'A1:H32', scale: 1.5, format: 'png'});
  const imagePath = path.join(qaDir, `${name}.png`);
  await fs.writeFile(imagePath, new Uint8Array(await image.arrayBuffer()));
  previews.push(imagePath);
}
await fs.mkdir(outputDir, {recursive: true});
await fs.mkdir(publicDir, {recursive: true});
const xlsx = await SpreadsheetFile.exportXlsx(wb);
const outputPath = path.join(outputDir, filename);
await xlsx.save(outputPath);
await fs.copyFile(outputPath, path.join(publicDir, filename));
const hash = createHash('sha256').update(await fs.readFile(outputPath)).digest('hex');
if (createHash('sha256').update(await fs.readFile(source)).digest('hex') !== sourceHash) throw new Error('元会計が変更された');
await fs.writeFile(path.join(qaDir, 'Excel照合158.json'), JSON.stringify({passed: true, checks: checks.length,
  input_mutation_recalculation: true, source_unchanged: true, book_sha256: hash,
  report_sha256: sourceHash, checks, previews, native_excel_recalculation: false}, null, 2), 'utf8');
console.log(JSON.stringify({passed: true, sheets: 7, tables: 7, checks: checks.length, book_sha256: hash, output: path.join(publicDir, filename)}));
