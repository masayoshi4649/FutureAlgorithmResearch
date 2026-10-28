import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const work = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(work, '../..');
const output = path.join(root, 'outputs/00145_profit_recycling');
const publication = path.join(root, 'アルゴリズム調査/00145_利益の分割回収と再参加の全場検証');
const data = JSON.parse(await fs.readFile(path.join(work, 'report145.json'), 'utf8'));
const book = Workbook.create();
const comparison = book.worksheets.add('比較');
const divisions = book.worksheets.add('昼夜と上昇下落');
const details = new Map();
const expected = [];
const currency = '#,##0;[Red](#,##0);"—"';

/**
 * 入力会計とExcel計算を照合する。
 * @param {number} actual - Excelの値。
 * @param {number} wanted - 元会計の値。
 * @param {string} label - 対象。
 * @returns {void} 不一致なら停止する。
 */
function equal(actual, wanted, label) {
  if (!Number.isFinite(actual) || Math.abs(actual - wanted) > 0.001) throw new Error(`${label}: ${actual}/${wanted}`);
}

/**
 * 読みやすい共通書式を適用する。
 * @param {object} sheet - 対象シート。
 * @param {string} last - 末列。
 * @param {number} end - 最終行。
 * @param {string} title - 題名。
 * @returns {void} 返り値なし。
 */
function style(sheet, last, end, title) {
  sheet.showGridLines = false;
  const area = sheet.getRange(`A1:${last}${end}`);
  area.format.font = { name: 'Yu Gothic', size: 10, color: '#1B3048' };
  area.format.rowHeight = 23;
  area.format.columnWidth = 18;
  area.format.verticalAlignment = 'center';
  sheet.getRange('A2').values = [[title]];
  sheet.getRange('A2').format.font = { bold: true, size: 14 };
  sheet.getRange(`A2:${last}2`).format.borders = { bottom: { style: 'thin', color: '#A5B5C5' } };
  sheet.getRange('A3').values = [['日経mini・片方向10枚・手数料0円。利益と損失は完結した親取引の収支を分類。']];
  sheet.getRange('A4').values = [['2026/09/21～10/23の全50場。ラージの次の正常気配をmini約定に代用した開発比較。']];
  sheet.getRange('A3:A5').format.font = { size: 10, color: '#52677C' };
  sheet.tabColor = '#244A70';
}

/**
 * 見出しとフィルター付き正式テーブルを作る。
 * @param {object} sheet - 対象。
 * @param {string[]} headers - 列名。
 * @param {string} last - 最後の列記号。
 * @param {number} end - データ最終行。
 * @param {string} name - 一意な表名。
 * @returns {void} 返り値なし。
 */
function table(sheet, headers, last, end, name) {
  sheet.getRange(`A6:${last}6`).values = [headers];
  sheet.tables.add(`A6:${last}${end}`, true, name).showFilterButton = true;
  sheet.getRange(`A6:${last}6`).format = { fill: '#244A70', font: { bold: true, color: '#FFFFFF' },
    wrapText: true, horizontalAlignment: 'center', rowHeight: 40,
    borders: { insideVertical: { style: 'thin', color: '#FFFFFF' } } };
  sheet.freezePanes.freezeRows(6);
}

/**
 * 金額と赤字の表示を設定する。
 * @param {object} sheet - 対象。
 * @param {string} address - 対象範囲。
 * @returns {void} 返り値なし。
 */
function money(sheet, address) {
  const range = sheet.getRange(address);
  range.setNumberFormat(currency);
  range.format.horizontalAlignment = 'right';
  range.conditionalFormats.add('cellIs', { operator: 'lessThan', formula: 0,
    format: { fill: '#FBEAEC', font: { color: '#A02836' } } });
}

/**
 * セッション会計の独立集計を返す。
 * @param {object[]} rows - 明細。
 * @returns {object} 比較用統計。
 */
function stats(rows) {
  const sum = k => rows.reduce((s, r) => s + r[k], 0);
  const nets = rows.map(r => r.net).sort((a, b) => a - b);
  const negatives = nets.filter(n => n < 0);
  return { profit: sum('profit'), loss: sum('loss'), net: sum('net'),
    wins: nets.filter(n => n > 0).length, losses: negatives.length,
    maxloss: negatives.length ? -negatives[0] : 0,
    avgloss: negatives.length ? -negatives.reduce((a, b) => a + b, 0) / negatives.length : 0,
    median: (nets[Math.floor((nets.length - 1) / 2)] + nets[Math.floor(nets.length / 2)]) / 2,
    ex3: sum('net') - nets.filter(n => n > 0).slice(-3).reduce((a, b) => a + b, 0), entries: sum('entries') };
}

// ----------------------------------------
// 研究結果は入力値として保持し、収支・累計・総計はExcel式で求める。
for (const method of data.methods) {
  if (details.has(method.id)) throw new Error(`手法ID重複: ${method.id}`);
  const rows = data.rows.filter(r => r.method === method.id).sort((a, b) => a.session.localeCompare(b.session));
  if (rows.length !== 50 || new Set(rows.map(r => r.session)).size !== 50) throw new Error(`場数不足: ${method.id}`);
  const sheet = book.worksheets.add(`日経_${method.id}`);
  details.set(method.id, { sheet, rows });
  style(sheet, 'I', 58, `${method.id}　${method.name}`);
  sheet.getRange('A5').values = [[method.description]];
  sheet.getRange('A7:I56').values = rows.map(r => [r.session, r.session.endsWith('_Day') ? 'デイ' : 'ナイト',
    r.profit, r.loss, null, null, r.entries, r.parent_count, r.direction]);
  let total = 0;
  rows.forEach((r, i) => {
    equal(r.profit - r.loss, r.net, `${method.id}/${r.session}`);
    const n = i + 7; total += r.net;
    sheet.getRange(`E${n}:F${n}`).formulas = [[`=C${n}-D${n}`, `=SUM($E$7:E${n})`]];
    expected.push([sheet.name, `E${n}`, r.net], [sheet.name, `F${n}`, total]);
  });
  sheet.getRange('A57').values = [['累計']];
  sheet.getRange('C57:H57').formulas = [['=SUM(C7:C56)', '=SUM(D7:D56)', '=SUM(E7:E56)', '=F56', '=SUM(G7:G56)', '=SUM(H7:H56)']];
  table(sheet, ['セッション', '区分', '利益（円）', '損失（円）', '収支（円）', '累計（円）', '新規件数', '親取引数', '始終値方向'], 'I', 56, `Method_${method.id}`);
  money(sheet, 'C7:F57');
  sheet.getRange('A1:A58').format.columnWidth = 28;
  sheet.getRange('B1:B58').format.columnWidth = 12;
  sheet.getRange('G7:I56').format.horizontalAlignment = 'center';
  sheet.getRange('C57:I57').format.font = { bold: true };
}

// ----------------------------------------
// 先頭の比較表は手法別シートを直接参照する。
style(comparison, 'M', data.methods.length + 6, '利益回収・再参加の比較');
comparison.getRange('A5').values = [[data.conclusion]];
const compareHeaders = ['手法ID', '簡単な説明', '総利益（円）', '総損失（円）', '収支（円）', '利益損失比', '黒字場', '赤字場', '最大赤字（円）', '平均赤字（円）', '場収支中央値（円）', '上位3黒字除外（円）', '新規件数'];
data.methods.forEach((method, i) => {
  const n = i + 7, { sheet, rows } = details.get(method.id), s = stats(rows), prefix = `'${sheet.name}'!`;
  const nets = `${prefix}$E$7:$E$56`;
  comparison.getRange(`A${n}:M${n}`).values = [[method.id, method.name, null, null, null, null, null, null, null, null, null, s.ex3, null]];
  comparison.getRange(`C${n}:K${n}`).formulas = [[`=${prefix}C57`, `=${prefix}D57`, `=${prefix}E57`,
    `=IF(D${n}=0,"損失なし",C${n}/D${n})`, `=COUNTIFS(${nets},">0")`, `=COUNTIFS(${nets},"<0")`,
    `=MAX(0,-MIN(${nets}))`, `=IF(H${n}=0,0,-SUMIFS(${nets},${nets},"<0")/H${n})`, `=MEDIAN(${nets})`]];
  comparison.getRange(`M${n}`).formulas = [[`=${prefix}G57`]];
  comparison.getRange(`L${n}`).formulas = [[`=E${n}-MAX(0,LARGE(${nets},1))-MAX(0,LARGE(${nets},2))-MAX(0,LARGE(${nets},3))`]];
  for (const [column, value] of [['C', s.profit], ['D', s.loss], ['E', s.net], ['G', s.wins], ['H', s.losses], ['I', s.maxloss], ['J', s.avgloss], ['K', s.median], ['M', s.entries]]) expected.push([comparison.name, `${column}${n}`, value]);
});
table(comparison, compareHeaders, 'M', data.methods.length + 6, 'Comparison145');
comparison.getRange(`B1:B${data.methods.length + 6}`).format.columnWidth = 46;
comparison.getRange(`B7:B${data.methods.length + 6}`).format.wrapText = true;
comparison.getRange(`A7:M${data.methods.length + 6}`).format.rowHeight = 42;
money(comparison, `C7:E${data.methods.length + 6}`); money(comparison, `I7:L${data.methods.length + 6}`);
comparison.getRange(`F7:F${data.methods.length + 6}`).setNumberFormat('0.00');

const splitRows = [];
const splitChecks = [];
for (const method of data.methods) for (const group of ['デイ', 'ナイト', '上昇', '下落']) {
  const { rows } = details.get(method.id);
  const selected = rows.filter(r => group === 'デイ' || group === 'ナイト' ? r.session.endsWith(group === 'デイ' ? '_Day' : '_Night') : r.direction === group);
  if (!selected.length) continue;
  const s = stats(selected); splitRows.push([method.id, group, selected.length, s.profit, s.loss, s.net, s.loss ? s.profit / s.loss : '損失なし', s.losses, s.avgloss, s.maxloss, s.entries]);
  splitChecks.push(s);
}
style(divisions, 'K', splitRows.length + 6, '昼夜・始終値方向を分けた比較');
divisions.getRange('A5').values = [['方向は事後分類。終値・当日の最終値幅を売買判断には使いません。']];
divisions.getRange(`A7:K${splitRows.length + 6}`).values = splitRows;
splitRows.forEach((row, i) => {
  const n = i + 7, s = splitChecks[i], prefix = `'${details.get(row[0]).sheet.name}'!`;
  const category = `${prefix}$${row[1] === 'デイ' || row[1] === 'ナイト' ? 'B' : 'I'}$7:$${row[1] === 'デイ' || row[1] === 'ナイト' ? 'B' : 'I'}$56`;
  const condition = `${category},B${n}`, nets = `${prefix}$E$7:$E$56`;
  divisions.getRange(`C${n}:I${n}`).formulas = [[`=COUNTIFS(${condition})`, `=SUMIFS(${prefix}$C$7:$C$56,${condition})`,
    `=SUMIFS(${prefix}$D$7:$D$56,${condition})`, `=D${n}-E${n}`, `=IF(E${n}=0,"損失なし",D${n}/E${n})`,
    `=COUNTIFS(${condition},${nets},"<0")`, `=IF(H${n}=0,0,-SUMIFS(${nets},${condition},${nets},"<0")/H${n})`]];
  divisions.getRange(`K${n}`).formulas = [[`=SUMIFS(${prefix}$G$7:$G$56,${condition})`]];
  for (const [column, value] of [['D', s.profit], ['E', s.loss], ['F', s.net], ['H', s.losses], ['I', s.avgloss], ['K', s.entries]]) expected.push([divisions.name, `${column}${n}`, value]);
});
table(divisions, ['手法ID', '区分', '場数', '利益（円）', '損失（円）', '収支（円）', '利益損失比', '赤字場', '平均赤字（円）', '最大赤字（円）', '新規件数'], 'K', splitRows.length + 6, 'Divisions145');
money(divisions, `D7:F${splitRows.length + 6}`); money(divisions, `I7:J${splitRows.length + 6}`);
divisions.getRange(`G7:G${splitRows.length + 6}`).setNumberFormat('0.00');

// ----------------------------------------
// 全式と保存値を照合し、各シートを描画してから書き出す。
book.recalculate();
for (const [name, address, value] of expected) equal(book.worksheets.getItem(name).getRange(address).values[0][0], value, `${name}/${address}`);
const first = details.get(data.methods[0].id).sheet;
const original = first.getRange('C7').values[0][0], priorTotal = comparison.getRange('E7').values[0][0];
first.getRange('C7').values = [[original + 1000]]; book.recalculate();
equal(comparison.getRange('E7').values[0][0], priorTotal + 1000, '再計算');
first.getRange('C7').values = [[original]]; book.recalculate();
const errors = await book.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!', options: { useRegex: true, maxResults: 100 }, maxChars: 6000 });
await fs.writeFile(path.join(work, 'xlsx数式検査145.jsonl'), errors.ndjson);
await fs.mkdir(output, { recursive: true }); await fs.mkdir(publication, { recursive: true });
let index = 0;
for (const sheet of [comparison, divisions, ...[...details.values()].map(x => x.sheet)]) {
  const preview = await book.render({ sheetName: sheet.name, range: sheet === comparison ? 'A1:M17' : sheet === divisions ? 'A1:K16' : 'A1:I16', scale: 1.5 });
  await fs.writeFile(path.join(work, `preview_${String(++index).padStart(2, '0')}_${sheet.name}.png`), new Uint8Array(await preview.arrayBuffer()));
}
const filename = '利益の分割回収と再参加の全セッション損益.xlsx';
const xlsx = await SpreadsheetFile.exportXlsx(book);
await xlsx.save(path.join(output, filename)); await fs.copyFile(path.join(output, filename), path.join(publication, filename));
await fs.writeFile(path.join(work, 'xlsx内部照合145.json'), JSON.stringify({ checked: expected.length, worksheets: index, methods: data.methods.length, sessions_per_method: 50, recalculation: true }, null, 2));
console.log(`出力完了: ${data.methods.length}手法・各50場`);
