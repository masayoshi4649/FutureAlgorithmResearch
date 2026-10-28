import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const work = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(work, '../..');
const output = path.join(root, 'outputs/00148_preus_momentum');
const publication = path.join(root, 'アルゴリズム調査/00148_米国開始前の勢い入口と利益追跡');
const filename = '米国開始前の変更と全夜間損益.xlsx';
const report = JSON.parse(await fs.readFile(path.join(work, 'report.json'), 'utf8'));
const methods = [...report.methods].sort((a, b) => (a.id === 'D07' ? -1 : b.id === 'D07' ? 1 : a.id.localeCompare(b.id)));
if (methods.length < 17 || methods[0].id !== 'D07' || new Set(methods.map(method => method.id)).size !== methods.length) throw new Error('D07と事前登録した独立手法が必要です。');
const workbook = Workbook.create();
const comparison = workbook.worksheets.add('比較');
const details = new Map();
for (const method of methods) details.set(method.id, workbook.worksheets.add(`日経_${method.id}`));
const current = workbook.worksheets.add('当夜途中');
const expected = [];
const moneyFormat = '#,##0;[Red](#,##0);"—"';
const first = 7;
const last = 31;
const total = 32;

/**
 * 元会計とセル値を照合する。
 * @param {number} actual - Excel計算値。
 * @param {number} wanted - 元会計値。
 * @param {string} label - 検査対象。
 * @returns {void} 不一致なら停止する。
 */
function equal(actual, wanted, label) {
  if (!Number.isFinite(actual) || !Number.isFinite(wanted) || Math.abs(actual - wanted) > 0.001) {
    throw new Error(`${label}: 計算${actual}、元会計${wanted}`);
  }
}

/**
 * 読みやすい共通書式を設定する。
 * @param {object} sheet - 対象シート。
 * @param {string} endColumn - 最終列記号。
 * @param {number} endRow - 最終行。
 * @param {string} title - タイトル。
 * @param {string} context - 対象と定義。
 * @returns {void} 返り値なし。
 */
function style(sheet, endColumn, endRow, title, context) {
  sheet.showGridLines = false;
  sheet.tabColor = '#244A70';
  const area = sheet.getRange(`A1:${endColumn}${endRow}`);
  area.format.font = { name: 'Yu Gothic', size: 10, color: '#1B3048' };
  area.format.rowHeight = 23;
  area.format.columnWidth = 18;
  area.format.verticalAlignment = 'center';
  sheet.getRange(`A1:A${endRow}`).format.columnWidth = 28;
  sheet.getRange('A2').values = [[title]];
  sheet.getRange('A2').format.font = { bold: true, size: 14 };
  sheet.getRange(`A2:${endColumn}2`).format.borders = { bottom: { style: 'thin', color: '#A5B5C5' } };
  sheet.getRange('A3').values = [['日経mini・片方向上限10枚・手数料0円・気配差込み。利益と損失は完結した親取引の収支を分類。']];
  sheet.getRange('A4').values = [[context]];
  sheet.getRange('A3:A5').format.font = { size: 10, color: '#52677C' };
}

/**
 * 見出し・フィルターを持つ正式なExcelテーブルを追加する。
 * @param {object} sheet - 対象シート。
 * @param {string[]} headers - 各列名。
 * @param {string} endColumn - 最終列記号。
 * @param {number} endRow - データ最終行。
 * @param {string} name - 重複しない表名。
 * @returns {void} 返り値なし。
 */
function table(sheet, headers, endColumn, endRow, name) {
  sheet.getRange(`A6:${endColumn}6`).values = [headers];
  const created = sheet.tables.add(`A6:${endColumn}${endRow}`, true, name);
  created.showFilterButton = true;
  sheet.getRange(`A6:${endColumn}6`).format = {
    fill: '#244A70', font: { bold: true, color: '#FFFFFF' }, wrapText: true,
    horizontalAlignment: 'center', rowHeight: 40,
    borders: { insideVertical: { style: 'thin', color: '#FFFFFF' } },
  };
  sheet.freezePanes.freezeRows(6);
}

/**
 * 金額の数値書式と赤字の条件付き書式を設定する。
 * @param {object} sheet - 対象シート。
 * @param {string} address - 対象範囲。
 * @returns {void} 返り値なし。
 */
function money(sheet, address) {
  const range = sheet.getRange(address);
  range.setNumberFormat(moneyFormat);
  range.format.horizontalAlignment = 'right';
  range.conditionalFormats.add('cellIs', { operator: 'lessThan', formula: 0,
    format: { fill: '#FBEAEC', font: { color: '#A02836' } } });
}

/**
 * 元JSONから比較値を独立集計する。
 * @param {object[]} rows - 完了25夜の会計。
 * @returns {object} 検算用合計・頻度・損失と上位3場除外収支。
 */
function stats(rows) {
  const sum = key => rows.reduce((value, row) => value + Number(row[key]), 0);
  const nets = rows.map(row => row.net).sort((a, b) => b - a);
  return { profit: sum('profit'), loss: sum('loss'), net: sum('net'), entries: sum('entries'),
    quantity: sum('quantity'), pre: sum('pre_net'), post: sum('post_net'),
    wins: nets.filter(value => value > 0).length, losses: nets.filter(value => value < 0).length,
    maxloss: Math.max(0, -Math.min(...nets)), ex3: sum('net') - nets.slice(0, 3).reduce((s, n) => s + Math.max(0, n), 0) };
}

/**
 * 一場の親取引数を読み出す。
 * @param {object} row - 元会計行。
 * @returns {number} 明示件数又は親一覧の長さ。
 */
function parentCount(row) {
  if (Number.isFinite(row.parent_count)) return row.parent_count;
  if (Number.isFinite(row.parents)) return row.parents;
  if (Array.isArray(row.parents)) return row.parents.length;
  if (Array.isArray(row.parent_records)) return row.parent_records.length;
  throw new Error(`${row.session}: 親取引数がありません。`);
}

/**
 * 途中評価の買い又は売り保有枚数を読み取る。
 * @param {object} row - 途中会計。
 * @param {number} side - 買い1又は売り-1。
 * @returns {number} 対象方向の未決済枚数。
 */
function held(row, side) {
  const explicit = side > 0 ? row.long_qty : row.short_qty;
  if (Number.isFinite(explicit)) return explicit;
  if (Array.isArray(row.positions)) return row.positions.reduce((sum, position) => {
    const direction = Number(position.side);
    const quantity = Number(position.quantity ?? position.qty);
    if (!Number.isFinite(direction) || !Number.isFinite(quantity)) throw new Error(`${row.id}: 保有玉の形式を確認してください。`);
    return sum + (direction === side ? quantity : 0);
  }, 0);
  throw new Error(`${row.id}: 途中保有枚数がありません。`);
}

// ----------------------------------------
// 方法別の25夜。入力会計を保持し、収支・累計・総計をExcel式で計算する。
for (const method of methods) {
  const rows = [...method.rows].sort((a, b) => a.session.localeCompare(b.session));
  if (rows.length !== 25 || new Set(rows.map(row => row.session)).size !== 25) throw new Error(`${method.id}: 完了25夜ではありません。`);
  method.rows = rows;
  const sheet = details.get(method.id);
  style(sheet, 'K', 33, `${method.id}　全夜間の利益・損失・収支`, '2026/09/21～10/23の既知25夜。前段は米国開始15分前まで、後段は米国開始15分後から。');
  sheet.getRange('A5').values = [[method.description]];
  sheet.getRange(`A${first}:K${last}`).values = rows.map(row => [row.session, row.direction, row.profit, row.loss, null, null,
    row.entries, row.quantity, row.pre_net, row.post_net, parentCount(row)]);
  let cumulative = 0;
  rows.forEach((row, index) => {
    const n = index + first;
    equal(row.profit - row.loss, row.net, `${method.id}/${row.session}/収支`);
    equal(row.pre_net + row.post_net, row.net, `${method.id}/${row.session}/前後段`);
    cumulative += row.net;
    sheet.getRange(`E${n}:F${n}`).formulas = [[`=C${n}-D${n}`, index === 0 ? `=E${n}` : `=F${n - 1}+E${n}`]];
    expected.push([sheet.name, `E${n}`, row.net], [sheet.name, `F${n}`, cumulative]);
  });
  sheet.getRange(`A${total}`).values = [['25夜累計']];
  sheet.getRange(`C${total}:K${total}`).formulas = [[`=SUM(C${first}:C${last})`, `=SUM(D${first}:D${last})`, `=C${total}-D${total}`, `=F${last}`,
    `=SUM(G${first}:G${last})`, `=SUM(H${first}:H${last})`, `=SUM(I${first}:I${last})`, `=SUM(J${first}:J${last})`, `=SUM(K${first}:K${last})`]];
  table(sheet, ['セッション', '始終値方向', '利益（円）', '損失（円）', '収支（円）', '累計（円）', '新規件数', '新規合計枚数', '前段収支（円）', '後段収支（円）', '親取引数'], 'K', last, `Method148_${method.id}`);
  money(sheet, `C${first}:F${total}`);
  money(sheet, `I${first}:J${total}`);
  sheet.getRange(`B1:B33`).format.columnWidth = 14;
  sheet.getRange(`G7:H32`).setNumberFormat('#,##0');
  sheet.getRange(`K7:K32`).setNumberFormat('#,##0');
  sheet.getRange(`A${total}:K${total}`).format.font = { bold: true };
  sheet.getRange(`A${total}:K${total}`).format.borders = { top: { style: 'thin', color: '#A5B5C5' } };
  const values = stats(rows);
  for (const [col, value] of [['C', values.profit], ['D', values.loss], ['E', values.net], ['F', values.net], ['G', values.entries], ['H', values.quantity], ['I', values.pre], ['J', values.post]]) expected.push([sheet.name, `${col}${total}`, value]);
}

// ----------------------------------------
// 比較値は各方法の完了25夜だけを参照する。方法間の合計は作らない。
const compareLast = methods.length + 6;
style(comparison, 'N', compareLast, '米国開始前の変更と全夜間比較', '後段は開場から仮想継続したD07。実アプリの途中新規起動・時間切替とは同値ではない研究用の合成。');
comparison.getRange('A5').values = [['今回24条件は米国前を改善せず。D07維持。今夜は取れても過去25夜で悪化。']];
methods.forEach((method, index) => {
  const n = first + index;
  const sheet = details.get(method.id);
  const prefix = `'${sheet.name}'!`;
  const nets = `${prefix}$E$7:$E$31`;
  const values = stats(method.rows);
  comparison.getRange(`A${n}:N${n}`).values = [[method.id, method.short_description ?? method.description, null, null, null, null, null, null, null, null, null, null, null, null]];
  comparison.getRange(`C${n}:N${n}`).formulas = [[`=${prefix}C32`, `=${prefix}D32`, `=${prefix}E32`, `=E${n}-$E$7`,
    `=IF(D${n}=0,"損失なし",C${n}/D${n})`, `=COUNTIFS(${nets},">0")`, `=COUNTIFS(${nets},"<0")`, `=MAX(0,-MIN(${nets}))`,
    `=E${n}-MAX(0,LARGE(${nets},1))-MAX(0,LARGE(${nets},2))-MAX(0,LARGE(${nets},3))`, `=${prefix}G32`, `=${prefix}I32`, `=${prefix}J32`]];
  for (const [col, value] of [['C', values.profit], ['D', values.loss], ['E', values.net], ['F', values.net - stats(methods[0].rows).net], ['H', values.wins], ['I', values.losses], ['J', values.maxloss], ['K', values.ex3], ['L', values.entries], ['M', values.pre], ['N', values.post]]) expected.push([comparison.name, `${col}${n}`, value]);
  if (values.loss > 0) expected.push([comparison.name, `G${n}`, values.profit / values.loss]);
});
table(comparison, ['手法ID', '簡単な説明', '総利益（円）', '総損失（円）', '収支（円）', 'D07との差（円）', '利益損失比', '黒字場数', '赤字場数', '最大赤字（円）', '上位3黒字除外（円）', '新規件数', '前段収支（円）', '後段収支（円）'], 'N', compareLast, 'Comparison148');
comparison.getRange(`A1:A${compareLast}`).format.columnWidth = 12;
comparison.getRange(`B1:B${compareLast}`).format.columnWidth = 54;
comparison.getRange(`B7:B${compareLast}`).format.wrapText = true;
comparison.getRange(`A7:N${compareLast}`).format.rowHeight = 36;
comparison.getRange(`G7:G${compareLast}`).setNumberFormat('0.00');
money(comparison, `C7:F${compareLast}`);
money(comparison, `J7:K${compareLast}`);
money(comparison, `M7:N${compareLast}`);

// ----------------------------------------
// 当夜途中は含み損益を含めて別表に示し、完了25夜に足さない。
const partialRows = [...report.partial].sort((a, b) => (a.id === 'D07' ? -1 : b.id === 'D07' ? 1 : a.id.localeCompare(b.id)));
if (partialRows.length !== methods.length) throw new Error('途中比較と完了場比較の手法数が一致しません。');
style(current, 'H', partialRows.length + 6, '2026/10/26ナイト　米国開始前の途中評価', '21:13:52までの保存スナップショット。終端で強制返済せず含み損益を表示。完了25夜に含めない。');
current.getRange('A5').values = [['新規合計枚数は累計約定枚数。未約定待機・売買回数・同時保有枚数とは区別する。']];
partialRows.forEach((row, index) => {
  const n = first + index;
  equal(row.net + row.unrealized, row.equity, `${row.id}/途中評価`);
  current.getRange(`A${n}:H${n}`).values = [[row.id, row.net, row.unrealized, null, row.entries, row.quantity, held(row, 1), held(row, -1)]];
  current.getRange(`D${n}`).formulas = [[`=B${n}+C${n}`]];
  expected.push([current.name, `D${n}`, row.equity]);
});
table(current, ['手法ID', '実現収支（円）', '含み損益（円）', '合計評価（円）', '新規件数', '新規合計枚数', '買い保有枚数', '売り保有枚数'], 'H', partialRows.length + 6, 'CurrentPartial148');
current.getRange(`A1:A${partialRows.length + 6}`).format.columnWidth = 14;
money(current, `B7:D${partialRows.length + 6}`);

// ----------------------------------------
// 入力変更が明細・累計・比較へ伝播することを確認してから原値へ戻す。
const probe = details.get('D07');
const originalProfit = probe.getRange('C7').values[0][0];
const originalNet = methods[0].rows[0].net;
const baseNet = stats(methods[0].rows).net;
probe.getRange('C7').values = [[originalProfit + 123]];
equal(probe.getRange('E7').values[0][0], originalNet + 123, '入力変更と明細収支');
equal(probe.getRange('F31').values[0][0], baseNet + 123, '入力変更と累計');
equal(comparison.getRange('E7').values[0][0], baseNet + 123, '入力変更と比較');
probe.getRange('C7').values = [[originalProfit]];
workbook.recalculate();
for (const [name, address, value] of expected) equal(workbook.worksheets.getItem(name).getRange(address).values[0][0], value, `${name}/${address}`);
await fs.mkdir(output, { recursive: true });
await fs.mkdir(publication, { recursive: true });
await fs.mkdir(path.join(work, 'xlsx_checks'), { recursive: true });
const inspected = await workbook.inspect({ kind: 'table', range: '比較!A6:N10', include: 'values,formulas', tableMaxRows: 5, tableMaxCols: 14, maxChars: 6000 });
await fs.writeFile(path.join(work, 'xlsx_checks/比較の検査.ndjson'), inspected.ndjson, 'utf8');
const errors = await workbook.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!', options: { useRegex: true, maxResults: 100 }, maxChars: 6000 });
await fs.writeFile(path.join(work, 'xlsx_checks/式エラーの検査.ndjson'), errors.ndjson, 'utf8');
for (const sheet of [comparison, ...details.values(), current]) {
  if (process.env.PREUS148_RENDER_ONLY && process.env.PREUS148_RENDER_ONLY !== sheet.name) continue;
  const columns = sheet === comparison ? 'N' : sheet === current ? 'H' : 'K';
  const endRow = sheet === comparison ? compareLast : sheet === current ? partialRows.length + 6 : 32;
  const image = await workbook.render({ sheetName: sheet.name, range: `A1:${columns}${endRow}`, scale: 1, format: 'png' });
  await fs.writeFile(path.join(work, 'xlsx_checks', `${sheet.name}.png`), new Uint8Array(await image.arrayBuffer()));
}
const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(path.join(output, filename));
await fs.copyFile(path.join(output, filename), path.join(publication, filename));
await fs.writeFile(path.join(work, 'xlsx_checks/Excel計算との照合.json'), JSON.stringify({ verified_cells: expected.length, input_change_propagation: true, restored_input: true, sheets: methods.length + 2, tables: methods.length + 2, complete_sessions_per_method: 25, partial_excluded: true, output: path.join(publication, filename) }, null, 2), 'utf8');
console.log(JSON.stringify({ workbook: path.join(publication, filename), sheets: methods.length + 2, tables: methods.length + 2, verified_cells: expected.length }, null, 2));
