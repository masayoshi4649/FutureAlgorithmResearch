import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const filename = '利益保護と再参加と入口見直しの全日中損益.xlsx';
const publicDir = path.join(root, 'アルゴリズム調査/00156_固定値幅の利益保護と遅い入口の再検証');
const outDir = path.join(root, 'outputs/00156_s01_exit');
const qaDir = path.join(here, 'xlsx_checks');
const sourcePath = path.join(here, 'report156_all.json');
const bytes = await fs.readFile(sourcePath);
const sourceHash = createHash('sha256').update(bytes).digest('hex');
const report = JSON.parse(bytes.toString('utf8'));
const methods = report.methods;
const current = report.current_rows ?? report.partial;
if (!Array.isArray(methods) || methods.length < 1) throw new Error('手法別の確定会計がありません');
if (new Set(methods.map(m => m.id)).size !== methods.length) throw new Error('同じ手法を重複掲載できません');
if (!Array.isArray(current) || current.length !== methods.length) throw new Error('途中会計の条件数が一致しません');
const baseline = methods.find(m => m.id === 'S01');
if (!baseline || baseline.rows.length !== 26) throw new Error('S01の26完了Dayがありません');
const baselineRows = [...baseline.rows].sort((a, b) => a.session.localeCompare(b.session));
const bySession = new Map(baselineRows.map((r, i) => [r.session, {row: r, excel: i + 6}]));
const lastDetail = 31;
const totalRow = 32;
const lastComparison = methods.length + 5;
const money = '#,##0;[Red](#,##0);"—"';
const integer = '#,##0;[Red](#,##0);"—"';
const wb = Workbook.create();
const summarySheet = wb.worksheets.add('比較');
const methodSheets = new Map(methods.map(m => [m.id, wb.worksheets.add(`日経_${m.id}`)]));
const currentSheet = wb.worksheets.add('10月27日デイ途中');
const checks = [];
const previews = [];

/**
 * 独立会計に対して有限数値が一致するか検査する。
 * @param {number} actual - Excelの計算値。
 * @param {number} expected - 元会計の値。
 * @param {string} label - 対象名。
 * @returns {void} 不一致の場合は停止する。
 */
function equal(actual, expected, label) {
  if (!Number.isFinite(actual) || !Number.isFinite(expected) || Math.abs(actual - expected) > 1e-5) {
    throw new Error(`${label}: ${actual} / ${expected}`);
  }
}

/**
 * 元会計の必須数値を取り出す。欠測をゼロへ置換しない。
 * @param {object} row - 会計行。
 * @param {string} key - 必須キー。
 * @returns {number} 確認した数値。
 */
function number(row, key) {
  const value = row[key];
  if (!Number.isFinite(value)) throw new Error(`必須数値なし: ${row.session ?? row.id ?? '集計'}/${key}`);
  return value;
}

/**
 * 最終照合に使用するセルと元数値を記録する。
 * @param {object} sheet - シート。
 * @param {string} cell - セル番地。
 * @param {number} expected - 元会計の値。
 * @returns {void} 返り値なし。
 */
function expect(sheet, cell, expected) {
  if (!Number.isFinite(expected)) throw new Error(`元会計の検査値が欠測: ${sheet.name}/${cell}`);
  checks.push([sheet.name, cell, expected]);
}

/**
 * 読み取り用の共通書式と短い条件を設定する。
 * @param {object} sheet - シート。
 * @param {string} lastColumn - 最終列。
 * @param {number} lastRow - 最終行。
 * @param {string} title - 表題。
 * @param {string} description - 手法又は集計対象。
 * @param {string} note - 金額単位や対象範囲。
 * @returns {void} 返り値なし。
 */
function style(sheet, lastColumn, lastRow, title, description, note) {
  sheet.showGridLines = false;
  sheet.getRange(`A1:${lastColumn}${lastRow}`).format = {
    font: {name: 'Yu Gothic', size: 10, color: '#21384D'},
    rowHeight: 25, columnWidth: 18, verticalAlignment: 'center',
  };
  sheet.getRange(`A1:A${lastRow}`).format.columnWidth = 25;
  sheet.getRange('A1').format.rowHeight = 10;
  sheet.getRange('A2').values = [[title]];
  sheet.getRange('A2').format.font = {size: 14, bold: true};
  sheet.getRange('A3').values = [[description]];
  sheet.getRange('A4').values = [[note]];
  sheet.getRange('A3:A4').format.font = {size: 10, color: '#536B80'};
  sheet.getRange(`C6:${lastColumn}${lastRow}`).setNumberFormat(money);
  sheet.getRange(`C6:${lastColumn}${lastRow}`).format.horizontalAlignment = 'right';
}

/**
 * フィルターを備える正式なExcelテーブルを配置する。
 * @param {object} sheet - シート。
 * @param {string[]} headers - 一行見出し。
 * @param {string} end - 最終列。
 * @param {number} last - 明細最終行。
 * @param {string} name - 一意なテーブル名。
 * @returns {void} 返り値なし。
 */
function table(sheet, headers, end, last, name) {
  sheet.getRange(`A5:${end}5`).values = [headers];
  const result = sheet.tables.add(`A5:${end}${last}`, true, name);
  result.showFilterButton = true;
  sheet.getRange(`A5:${end}5`).format = {
    fill: '#264D70', font: {bold: true, color: '#FFFFFF'},
    rowHeight: 43, wrapText: true, horizontalAlignment: 'center',
  };
  sheet.freezePanes.freezeRows(5);
}

/**
 * 赤字金額に同じ条件付き表示を適用する。
 * @param {object} sheet - シート。
 * @param {string} range - 対象金額範囲。
 * @returns {void} 返り値なし。
 */
function losses(sheet, range) {
  sheet.getRange(range).conditionalFormats.add('cellIs', {
    operator: 'lessThan', formula: 0,
    format: {fill: '#FBE9EB', font: {color: '#9C2632'}},
  });
}

/**
 * 入口条件の調査IDだけでは意味が伝わらない部分を短い日本語へ展開する。
 * @param {object} method - 元会計の手法と説明。
 * @returns {string} 売買条件を変えない表示用説明。
 */
function description(method) {
  if (method.id === 'S01') return '現行基準。別入口の利益保護を追加したD07';
  const labels = {
    E01: '確定2分の順行を確認して新規・出口はS01',
    E02: '確定2分の順行を確認して新規・20pt利益追尾',
    E03: '確定2分の順行を確認して新規・40pt利益追尾',
    E04: '完成1分足が2本連続順行なら新規・出口はS01',
    E05: '完成1分足が2本連続順行なら新規・20pt利益追尾',
    E06: '完成1分足が2本連続順行なら新規・40pt利益追尾',
    E07: '急伸後の停滞を見送る・出口はS01',
    E08: '急伸後の停滞を見送る・20pt利益追尾',
    E09: '急伸後の停滞を見送る・40pt利益追尾',
  };
  return labels[method.id] ?? method.description;
}

// ----------------------------------------
// 完了26デイを各手法の正式テーブルへ置き、収支と累計を計算する。
for (const method of methods) {
  const sheet = methodSheets.get(method.id);
  const rows = [...method.rows].sort((a, b) => a.session.localeCompare(b.session));
  if (rows.length !== 26 || rows.some(r => !r.session.endsWith('_Day'))) throw new Error(`${method.id}: 完了26デイではありません`);
  if (new Set(rows.map(r => r.session)).size !== 26) throw new Error(`${method.id}: セッション重複`);
  style(sheet, 'H', totalRow, `日経 ${method.id}　日中損益`, description(method),
    '日経mini上限10枚・手数料0。途中最悪＝確定＋含みの最小、最大下落＝当場ピークからの落差。');
  sheet.getRange(`B1:B${totalRow}`).format.columnWidth = 12;
  let cumulative = 0;
  rows.forEach((row, i) => {
    const n = i + 6;
    const profit = number(row, 'profit'), loss = number(row, 'loss'), net = number(row, 'net');
    const risk = row.intraday_risk;
    if (!risk) throw new Error(`${method.id}/${row.session}: 場内時価の再会計がありません`);
    const minEquity = number(risk, 'min_equity'), drawdown = number(risk, 'max_drawdown');
    const reference = bySession.get(row.session);
    if (!reference) throw new Error(`${method.id}: 基準にない場 ${row.session}`);
    equal(profit - loss, net, `${method.id}/${row.session}/親会計`);
    sheet.getRange(`A${n}:H${n}`).values = [[row.session, row.direction, profit, loss, null, null, minEquity, drawdown]];
    sheet.getRange(`E${n}:F${n}`).formulas = [[`=C${n}-D${n}`, i === 0 ? `=E${n}` : `=F${n - 1}+E${n}`]];
    cumulative += net;
    for (const [column, value] of [['C', profit], ['D', loss], ['E', net], ['F', cumulative], ['G', minEquity], ['H', drawdown]]) {
      expect(sheet, `${column}${n}`, value);
    }
  });
  table(sheet, ['セッション', '場の方向', '利益（円）', '損失（円）', '収支（円）', '累計（円）',
    '途中最悪収支（円）', '最大下落額（円）'], 'H', lastDetail, `D156_${method.id}`);
  sheet.getRange(`A${totalRow}`).values = [['累計']];
  for (const column of ['C', 'D']) sheet.getRange(`${column}${totalRow}`).formulas = [[`=SUM(${column}6:${column}${lastDetail})`]];
  sheet.getRange(`E${totalRow}:F${totalRow}`).formulas = [[`=C${totalRow}-D${totalRow}`, `=F${lastDetail}`]];
  sheet.getRange(`G${totalRow}:H${totalRow}`).formulas = [[`=MIN(G6:G${lastDetail})`, `=MAX(H6:H${lastDetail})`]];
  sheet.getRange(`A${totalRow}`).values = [['累計／場内最悪値']];
  sheet.getRange(`A${totalRow}:H${totalRow}`).format = {font: {bold: true}, borders: {top: {style: 'thin', color: '#93AABD'}}};
  losses(sheet, `E6:F${lastDetail}`);
  for (const [column, key] of [['C', 'profit'], ['D', 'loss'], ['E', 'net']]) expect(sheet, `${column}${totalRow}`, number(method.summary, key));
  expect(sheet, `G${totalRow}`, Math.min(...rows.map(r => r.intraday_risk.min_equity)));
  expect(sheet, `H${totalRow}`, Math.max(...rows.map(r => r.intraday_risk.max_drawdown)));
  previews.push([sheet, 'H', totalRow]);
}

// ----------------------------------------
// 比較は各手法の完成値を参照し、赤字場数・深さと大勝ち除外も同時に示す。
style(summarySheet, 'M', lastComparison, '利益保護・再参加・入口の比較',
  '2026/09/21～10/26の26完了デイ。10/27途中は別表。',
  'E/F/R/Lは調査00156内の比較ID。ラージ次正常気配の約定模型。手数料0。');
summarySheet.tabColor = '#264D70';
summarySheet.getRange(`A1:A${lastComparison}`).format.columnWidth = 12;
summarySheet.getRange(`B1:B${lastComparison}`).format.columnWidth = 48;
methods.forEach((method, i) => {
  const n = i + 6, sheet = `'日経_${method.id}'!`, range = `${sheet}$E$6:$E$${lastDetail}`;
  const category = method.id === 'S01' ? '基準' : (method.group_label ?? (method.id.startsWith('R') ? '再参加の変更' : method.id.startsWith('L') ? '再参加の損切り変更' : '入口・出口の変更'));
  summarySheet.getRange(`A${n}:B${n}`).values = [[method.id, `${category}：${description(method)}`]];
  summarySheet.getRange(`C${n}:J${n}`).formulas = [[
    `=${sheet}C${totalRow}`, `=${sheet}D${totalRow}`, `=${sheet}E${totalRow}`,
    `=IF(D${n}=0,"",C${n}/D${n})`, `=COUNTIFS(${range},"<0")`,
    `=IF(G${n}=0,0,-SUMIFS(${range},${range},"<0")/G${n})`, `=MAX(0,-MIN(${range}))`,
    `=E${n}-MAX(0,LARGE(${range},1))-MAX(0,LARGE(${range},2))-MAX(0,LARGE(${range},3))`,
  ]];
  summarySheet.getRange(`K${n}`).values = [[number(method.summary, 'entries')]];
  summarySheet.getRange(`L${n}:M${n}`).formulas = [[`=${sheet}G${totalRow}`, `=${sheet}H${totalRow}`]];
  for (const [column, key] of [['C', 'profit'], ['D', 'loss'], ['E', 'net'],
    ['G', 'losses'], ['H', 'avgloss'], ['I', 'maxloss'], ['J', 'ex3'], ['K', 'entries']]) expect(summarySheet, `${column}${n}`, number(method.summary, key));
  if (method.summary.loss > 0) expect(summarySheet, `F${n}`, method.summary.profit / method.summary.loss);
  expect(summarySheet, `L${n}`, Math.min(...method.rows.map(r => r.intraday_risk.min_equity)));
  expect(summarySheet, `M${n}`, Math.max(...method.rows.map(r => r.intraday_risk.max_drawdown)));
});
table(summarySheet, ['手法', '簡単な説明', '総利益（円）', '総損失（円）', '収支（円）', '利益／損失',
  '赤字場数', '平均赤字（円）', '最大赤字場（円）', '上位3黒字除外（円）',
  '新規回数', '途中最悪収支（円）', '最大下落額（円）'], 'M', lastComparison, 'D156_comparison');
summarySheet.getRange(`B6:B${lastComparison}`).format = {wrapText: true, rowHeight: 43, horizontalAlignment: 'left'};
summarySheet.getRange(`F6:F${lastComparison}`).setNumberFormat('0.00');
losses(summarySheet, `E6:E${lastComparison}`);
previews.unshift([summarySheet, 'M', lastComparison]);

// ----------------------------------------
// 途中末尾は架空返済せず、完結親・継続親の確定分と含みを分ける。
style(currentSheet, 'K', lastComparison, '10月27日デイの途中損益',
  '15:20未満の固定資料。完了26デイの合計には含めない。',
  '利益－損失＋継続親実現＝確定収支。確定＋含み＝時価収支。実アプリの約定とは別の模型。');
currentSheet.getRange(`A1:A${lastComparison}`).format.columnWidth = 12;
currentSheet.getRange(`B6:K${lastComparison}`).setNumberFormat(money);
currentSheet.getRange(`B6:K${lastComparison}`).format.horizontalAlignment = 'right';
current.forEach((row, i) => {
  const n = i + 6;
  const profit = number(row, 'profit'), loss = number(row, 'loss');
  const open = number(row, 'open_parent_realized'), net = number(row, 'net');
  const unrealized = number(row, 'unrealized'), equity = number(row, 'equity');
  const risk = row.intraday_risk;
  if (!risk) throw new Error(`${row.id}: 途中場の時価再会計がありません`);
  equal(profit - loss + open, net, `${row.id}/途中親会計`);
  equal(net + unrealized, equity, `${row.id}/途中時価`);
  currentSheet.getRange(`A${n}:K${n}`).values = [[row.id, profit, loss, open,
    null, unrealized, null, number(row, 'remaining_qty'), number(row, 'entries'),
    number(risk, 'min_equity'), number(risk, 'max_drawdown')]];
  currentSheet.getRange(`E${n}`).formulas = [[`=B${n}-C${n}+D${n}`]];
  currentSheet.getRange(`G${n}`).formulas = [[`=E${n}+F${n}`]];
  for (const [column, key] of [['B', 'profit'], ['C', 'loss'], ['D', 'open_parent_realized'], ['E', 'net'],
    ['F', 'unrealized'], ['G', 'equity'], ['H', 'remaining_qty'], ['I', 'entries']]) expect(currentSheet, `${column}${n}`, number(row, key));
  expect(currentSheet, `J${n}`, risk.min_equity);
  expect(currentSheet, `K${n}`, risk.max_drawdown);
});
table(currentSheet, ['手法', '完結親利益（円）', '完結親損失（円）', '継続親実現（円）',
  '確定収支（円）', '含み損益（円）', '時価収支（円）', '未返済枚数', '新規回数',
  '途中最悪収支（円）', '最大下落額（円）'], 'K', lastComparison, 'D156_current');
currentSheet.getRange(`H6:I${lastComparison}`).setNumberFormat(integer);
losses(currentSheet, `E6:G${lastComparison}`);
previews.push([currentSheet, 'K', lastComparison]);

// ----------------------------------------
// 原会計の全値、数式の再計算、全シートの描画を検査して同一成果を保存する。
const testSheet = methodSheets.get('S01');
const original = testSheet.getRange('C6').values[0][0];
const comparisonIndex = methods.findIndex(m => m.id === 'S01') + 6;
testSheet.getRange('C6').values = [[original + 100]];
equal(summarySheet.getRange(`E${comparisonIndex}`).values[0][0], baseline.summary.net + 100, '総収支の変更追従');
testSheet.getRange('C6').values = [[original]];
wb.recalculate();
for (const [sheet, cell, expected] of checks) equal(wb.worksheets.getItem(sheet).getRange(cell).values[0][0], expected, `${sheet}/${cell}`);
await fs.mkdir(qaDir, {recursive: true});
await fs.mkdir(outDir, {recursive: true});
await fs.mkdir(publicDir, {recursive: true});
const inspect = await wb.inspect({kind: 'table', range: `比較!A5:M${lastComparison}`,
  include: 'values,formulas', tableMaxRows: methods.length + 1, tableMaxCols: 13, maxChars: 14000});
await fs.writeFile(path.join(qaDir, '比較の検査.ndjson'), inspect.ndjson);
const errors = await wb.inspect({kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',
  options: {useRegex: true, maxResults: 100}, maxChars: 4000});
await fs.writeFile(path.join(qaDir, '式エラーの検査.ndjson'), errors.ndjson);
for (const [sheet, column, row] of previews) {
  const png = await wb.render({sheetName: sheet.name, range: `A1:${column}${row}`, scale: 1, format: 'png'});
  await fs.writeFile(path.join(qaDir, `${sheet.name}.png`), new Uint8Array(await png.arrayBuffer()));
}
if (createHash('sha256').update(await fs.readFile(sourcePath)).digest('hex') !== sourceHash) throw new Error('作成中に会計原本が変化しました');
const output = await SpreadsheetFile.exportXlsx(wb);
await output.save(path.join(outDir, filename));
await fs.copyFile(path.join(outDir, filename), path.join(publicDir, filename));
await fs.writeFile(path.join(qaDir, 'Excel照合156.json'), JSON.stringify({
  source_sha256: sourceHash, sheets: previews.length, tables: previews.length,
  checked_cells: checks.length, complete_sessions: 26, current_separate: true,
  change_recalculate_restore_checked: true,
}, null, 2));
console.log(JSON.stringify({path: path.join(publicDir, filename), sheets: previews.length, checked: checks.length}));
