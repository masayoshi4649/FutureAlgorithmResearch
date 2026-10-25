import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const work = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(work, '../..');
const input = path.join(work, 'report_data141.json');
const publicDirectory = path.join(root, 'アルゴリズム調査/00141_追加三場の原板全行診断と昼夜別改善');
const outputDirectory = path.join(root, 'outputs/00141_raw_diagnosis_20261024');
const filename = '追加三場の原因と改善後の全セッション損益.xlsx';
const output = path.join(outputDirectory, filename);
const published = path.join(publicDirectory, filename);
const sourceBytes = await fs.readFile(input);
const data = JSON.parse(sourceBytes.toString('utf8').replace(/^\uFEFF/, ''));
const knownEnd = '2026-10-22_Day';
const symbols = ['NK225', 'TOPIX'];
const productNames = { NK225: '日経mini', TOPIX: 'TOPIXmini' };
const scopeNames = { all: '全50場', known: '対照47場', new: '診断3場' };
const expectedCounts = { all: 50, known: 47, new: 3 };
const scopeOrder = { all: 0, known: 1, new: 2 };
const selectedRank = new Map(data.selected.map((row, index) => [`${row.symbol}/${row.method}`, index]));
const selectedInfo = new Map(data.selected.map(row => [`${row.symbol}/${row.method}`, row]));

/**
 * 会計値を許容誤差付きで照合する。
 * @param {number} actual - 計算した数値。
 * @param {number} expected - 入力の期待数値。
 * @param {string} label - 対象項目。
 * @returns {void} 返り値なし。不一致なら処理を止める。
 */
function equal(actual, expected, label) {
  if (!Number.isFinite(actual) || !Number.isFinite(expected) || Math.abs(actual - expected) > 0.001) {
    throw new Error(`${label}: 実際=${actual} / 期待=${expected}`);
  }
}

/**
 * 未参加時の欠測と、測定されたゼロを区別して照合する。
 * @param {number|null|string} actual - 実際の値又は空欄。
 * @param {number|null} expected - 期待値又は未測定。
 * @param {string} label - 対象項目。
 * @returns {void} 返り値なし。不一致なら処理を止める。
 */
function equalNullable(actual, expected, label) {
  if (expected === null || expected === undefined) {
    if (actual !== null && actual !== undefined && actual !== '') throw new Error(`${label}: 欠測が数値へ置換されました`);
  } else {
    equal(actual, expected, label);
  }
}

/**
 * 指定した検証範囲のセッションだけを選ぶ。
 * @param {object[]} rows - 一手法・一商品のセッション会計。
 * @param {string} scope - all、known、newのいずれか。
 * @returns {object[]} 対象会計。
 */
function scoped(rows, scope) {
  if (!(scope in expectedCounts)) throw new Error(`不明な検証区分: ${scope}`);
  return rows.filter(row => scope === 'all' || (scope === 'known' ? row.session <= knownEnd : row.session > knownEnd));
}

/**
 * 参加したセッションの算術平均を計算する。
 * @param {object[]} rows - 対象セッション会計。
 * @param {string} field - 測定列の名前。
 * @returns {number|null} 算術平均。測定値が無ければnull。
 */
function participatingAverage(rows, field) {
  const values = rows.filter(row => row.entries > 0 && Number.isFinite(row[field])).map(row => row[field]);
  return values.length ? values.reduce((total, value) => total + value, 0) / values.length : null;
}

/**
 * 中央値を別計算し、入力の集計と照合する。
 * @param {number[]} values - 対象の値。
 * @returns {number} 対象値の中央値。
 */
function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

/**
 * シートの読みやすい基本書式を設定する。
 * @param {object} sheet - 対象シート。
 * @param {string} range - 実際に使用する範囲。
 * @returns {void} 返り値なし。
 */
function styleSheet(sheet, range) {
  sheet.showGridLines = false;
  sheet.getRange(range).format.font = { name: 'Yu Gothic', size: 10, color: '#172B44' };
  sheet.getRange(range).format.verticalAlignment = 'center';
  sheet.getRange(range).format.rowHeight = 22;
  sheet.getRange(range).format.columnWidth = 15;
  sheet.tabColor = '#254567';
  sheet.getRange('A2').format.font = { bold: true, size: 14 };
  sheet.getRange('A2:J2').format.borders = { bottom: { style: 'thin', color: '#7B91A7' } };
  sheet.getRange('A3:A5').format.font = { size: 10, color: '#52667C' };
}

/**
 * 列見出しだけに濃色と白文字を適用する。
 * @param {object} sheet - 対象シート。
 * @param {string} range - 見出しのセル範囲。
 * @returns {void} 返り値なし。
 */
function header(sheet, range) {
  sheet.getRange(range).format = {
    fill: '#254567', font: { bold: true, color: '#FFFFFF' },
    horizontalAlignment: 'center', verticalAlignment: 'center', wrapText: true, rowHeight: 34,
    borders: { insideVertical: { style: 'thin', color: '#FFFFFF' } },
  };
}

/**
 * 金額を整数円で表示し、負の収支を赤く示す。
 * @param {object} sheet - 対象シート。
 * @param {string} range - 金額の範囲。
 * @returns {void} 返り値なし。
 */
function money(sheet, range) {
  sheet.getRange(range).setNumberFormat('#,##0;[Red](#,##0);"-"');
  sheet.getRange(range).format.horizontalAlignment = 'right';
  sheet.getRange(range).conditionalFormats.add('cellIs', {
    operator: 'lessThan', formula: 0,
    format: { fill: '#FCEBEC', font: { color: '#A62932' } },
  });
}

/**
 * 価格時計をExcel上の日本時間の日時値へ変換する。
 * @param {number|string} value - epoch秒又はタイムゾーン付きISO時計。
 * @returns {Date} 日本時間の表示用日時値。時計が不明なら推定せず停止する。
 */
function excelClock(value) {
  if (typeof value !== 'number' && !(typeof value === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value))) {
    throw new Error(`損失時刻はepoch秒又はタイムゾーン付きISOで指定してください: ${value}`);
  }
  const stamp = typeof value === 'number' ? value * 1000 : Date.parse(value);
  if (!Number.isFinite(stamp)) throw new Error('損失時刻が不正です');
  return new Date(stamp + 9 * 3600 * 1000);
}

/**
 * 基準B5の中にある昼夜別の実手法を表示へ補足する。
 * @param {string} symbol - 日経又はTOPIXの銘柄ID。
 * @param {string} method - 保存会計の実行ID。
 * @param {string} group - Day又はNight。
 * @returns {string} 表示用のID。B5以外の構成は推定しない。
 */
function executionLabel(symbol, method, group) {
  return method === 'B5' ? `B5（${group === 'Day' ? 'T06' : symbol === 'NK225' ? 'U06' : 'T04'}）` : method;
}

/**
 * 原板へ戻れる損失時点と、明示された比較単位での金額差を表にする。
 * @param {object} workbook - 作成中のブック。
 * @param {object[]} events - 原seqと旧・新収支を持つ保存済み診断行。
 * @param {string} basis - 個別玉又はセッション等、金額を比べる範囲の説明。
 * @returns {object} シートと差額照合に使う行の組。
 */
function buildLossEvents(workbook, events, basis) {
  if (!basis || typeof basis !== 'string') throw new Error('loss_event_basis に金額の比較単位が必要です');
  const sheet = workbook.worksheets.add('具体損失時間');
  const end = events.length + 6;
  styleSheet(sheet, `A1:H${end}`);
  sheet.getRange('A2').values = [['損失が発生した時点と改善の比較']];
  sheet.getRange('A3').values = [[basis]];
  sheet.getRange('A4').values = [['時刻は原価格時計。原seqは0始まりで、未採番は空欄です。板受信時刻を復元したものではありません。']];
  sheet.getRange('A5').values = [['金額は円。差額は改善後収支から旧収支を引いた値です。出典：00141保存診断会計。']];
  sheet.getRange('A6:H6').values = [['セッション', '商品', '原価格時計', '原seq（0始まり）', '旧収支（円）', '改善後収支（円）', '差額（円）', '観測した問題']];
  const checks = [];
  for (let index = 0; index < events.length; index++) {
    const event = events[index], number = index + 7;
    if (!Number.isFinite(event.old_net) || !Number.isFinite(event.new_net)) throw new Error('損失時点の金額が不正です');
    if (!symbols.includes(event.symbol) || (event.seq !== null && (!Number.isInteger(event.seq) || event.seq < 0))) throw new Error('損失時点の銘柄・原seqが不正です');
    if (typeof event.change !== 'string' || !event.change) throw new Error('損失時点の問題説明がありません');
    sheet.getRange(`A${number}:H${number}`).values = [[event.session, productNames[event.symbol], excelClock(event.time), event.seq, event.old_net, event.new_net, null, event.change]];
    sheet.getRange(`G${number}`).formulas = [[`=F${number}-E${number}`]];
    checks.push({ row: number, expected: event.new_net - event.old_net });
  }
  const table = sheet.tables.add(`A6:H${end}`, true, '具体損失時間の比較');
  table.showFilterButton = true;
  header(sheet, 'A6:H6');
  money(sheet, `E7:G${end}`);
  sheet.getRange(`C7:C${end}`).setNumberFormat('yyyy/mm/dd hh:mm:ss');
  sheet.getRange(`D7:D${end}`).setNumberFormat('#,##0');
  sheet.getRange(`A1:A${end}`).format.columnWidth = 26;
  sheet.getRange(`B1:B${end}`).format.columnWidth = 16;
  sheet.getRange(`C1:C${end}`).format.columnWidth = 30;
  sheet.getRange(`D1:D${end}`).format.columnWidth = 22;
  sheet.getRange(`E1:G${end}`).format.columnWidth = 23;
  sheet.getRange(`H1:H${end}`).format.columnWidth = 65;
  sheet.getRange(`H7:H${end}`).format.wrapText = true;
  sheet.getRange(`A7:H${end}`).format.rowHeight = 36;
  sheet.freezePanes.freezeRows(6);
  return { sheet, checks, end };
}

// ----------------------------------------
// 元の会計と集計を先に照合する。手数料を二重に控除しない。

if (!Array.isArray(data.rows) || !Array.isArray(data.summary) || !Array.isArray(data.selected)) {
  throw new Error('report_data141.json の構造が不正です');
}
const groups = new Map();
const rowKeys = new Set();
for (const row of data.rows) {
  if (!symbols.includes(row.symbol) || !/^\d{4}-\d{2}-\d{2}_(Day|Night)$/.test(row.session)) {
    throw new Error(`商品または場名が不正です: ${row.symbol}/${row.session}`);
  }
  const key = `${row.symbol}/${row.method}/${row.session}`;
  if (rowKeys.has(key)) throw new Error(`会計が重複しています: ${key}`);
  rowKeys.add(key);
  equal(row.profit - row.loss, row.net, `${key} 費用後利益−損失`);
  equal(row.gross - row.fees, row.net, `${key} 費用前−手数料`);
  for (const field of ['profit', 'loss', 'fees', 'entries', 'quantity', 'max_per_side']) {
    if (!Number.isFinite(row[field]) || row[field] < 0) throw new Error(`${key} ${field}が不正です`);
  }
  if (row.max_per_side > 10) throw new Error(`${key} 同時保有が10枚を超えています`);
  for (const field of ['first_minutes', 'held_minutes']) {
    if (row[field] != null && (!Number.isFinite(row[field]) || row[field] < 0)) throw new Error(`${key} ${field}が不正です`);
  }
  const groupKey = `${row.symbol}/${row.method}`;
  if (!groups.has(groupKey)) groups.set(groupKey, []);
  groups.get(groupKey).push(row);
}
for (const rows of groups.values()) rows.sort((a, b) => a.session.localeCompare(b.session));
const summaryKeys = new Set();
for (const stat of data.summary) {
  const key = `${stat.symbol}/${stat.method}/${stat.scope}`;
  if (summaryKeys.has(key)) throw new Error(`集計が重複しています: ${key}`);
  summaryKeys.add(key);
  const rows = scoped(groups.get(`${stat.symbol}/${stat.method}`) ?? [], stat.scope);
  if (rows.length !== expectedCounts[stat.scope]) throw new Error(`${key}: 必要場数を満たしません`);
  const sums = field => rows.reduce((total, row) => total + row[field], 0);
  const nets = rows.map(row => row.net);
  const losses = nets.filter(value => value < 0);
  equal(stat.sessions, rows.length, `${key} 対象場`);
  for (const field of ['profit', 'loss', 'net', 'entries']) equal(stat[field], sums(field), `${key} ${field}`);
  equal(stat.wins, nets.filter(value => value > 0).length, `${key} 黒字場`);
  equal(stat.losses, losses.length, `${key} 赤字場`);
  equal(stat.flat, rows.filter(row => row.entries === 0).length, `${key} 無取引場`);
  equal(stat.median, median(nets), `${key} 中央値`);
  equal(stat.worst, Math.min(...nets), `${key} 最悪収支`);
  equal(stat.avg_loss, losses.length ? -losses.reduce((total, value) => total + value, 0) / losses.length : 0, `${key} 平均赤字`);
  equal(stat.ex_top3, sums('net') - nets.filter(value => value > 0).sort((a, b) => b - a).slice(0, 3).reduce((total, value) => total + value, 0), `${key} 上位3除外`);
  equalNullable(stat.first_minutes, participatingAverage(rows, 'first_minutes'), `${key} 初回待機`);
  equalNullable(stat.held_minutes, participatingAverage(rows, 'held_minutes'), `${key} 保有時間`);
  equal(stat.max_per_side, Math.max(...rows.map(row => row.max_per_side)), `${key} 保有上限`);
}
for (const row of data.selected) {
  for (const scope of ['all', 'known', 'new']) {
    if (!summaryKeys.has(`${row.symbol}/${row.method}/${scope}`)) {
      throw new Error(`選択候補の${scope}集計がありません: ${row.symbol}/${row.method}`);
    }
  }
}

// ----------------------------------------
// 二商品の明細を配置し、収支と日時順累計をExcel式で計算する。

const book = Workbook.create();
const comparison = book.worksheets.add('比較');
const dayNight = book.worksheets.add('昼夜比較');
const lossView = data.loss_events?.length ? buildLossEvents(book, data.loss_events, data.loss_event_basis) : null;
const details = {};
const ranges = new Map();
const expectedCells = [];
const detailTotals = {};
const detailKeys = [...groups.keys()].sort((a, b) => (selectedRank.get(a) ?? 10000) - (selectedRank.get(b) ?? 10000) || a.localeCompare(b, 'en', { numeric: true }));
for (const groupKey of detailKeys) {
  const [symbol, method] = groupKey.split('/');
  const info = selectedInfo.get(groupKey);
  if (!info?.label || !info.day_method || !info.night_method) throw new Error(`${groupKey} の昼夜仕様がありません`);
  const sheetName = `${symbol === 'NK225' ? '日経' : 'TOPIX'}_${method}`;
  const sheet = book.worksheets.add(sheetName);
  details[groupKey] = sheet;
  const ordered = groups.get(groupKey);
  if (ordered.length === 0 || ordered.length >= 10000) throw new Error(`${symbol} の明細数が想定外です: ${ordered.length}`);
  const end = ordered.length + 6;
  styleSheet(sheet, `A1:O${end}`);
  sheet.getRange('A2').values = [[`${productNames[symbol]} ${method} セッション損益`]];
  sheet.getRange('A3').values = [['片方向上限10枚。金額は円・手数料後。利益と損失は完結した一組の収支を正負に分類。']];
  sheet.getRange('A4').values = [[`昼：${executionLabel(symbol, info.day_method, 'Day')}／夜：${executionLabel(symbol, info.night_method, 'Night')}。対照47場：9/21～10/22デイ。診断3場：10/22ナイト～10/23ナイト。`]];
  sheet.getRange('A5').values = [[`${info.label}。出典：00141保存会計。診断3場は原因分析と改善に使用した期間です。`]];
  sheet.getRange('A6:O6').values = [[
    '手法ID', '開始日時', 'セッション', '利益（円）', '損失（円）', '収支（円）', '累計（円）',
    '内数手数料（円）', '費用前収支（円）', '新規回数', '新規枚数', '最大片方向保有', '評価区分', '初回まで（分）', '保有（分）',
  ]];
  const values = [], netFormulas = [], cumulativeFormulas = [];
  const cumulatives = new Map();
  for (const row of ordered) {
    const number = values.length + 7;
    const kind = row.session.endsWith('_Day') ? 'デイ' : 'ナイト';
    // Excelには日本時間の場開始を時差なしの日時値として格納する。
    const date = new Date(`${row.session.slice(0, 10)}T${kind === 'デイ' ? '08:45' : '17:00'}:00Z`);
    values.push([row.method, date, kind, row.profit, row.loss, null, null, row.fees, row.gross,
      row.entries, row.quantity, row.max_per_side, row.session <= knownEnd ? '対照47場' : '診断3場', row.first_minutes ?? null, row.held_minutes ?? null]);
    netFormulas.push([`=D${number}-E${number}`]);
    cumulativeFormulas.push([`=SUMIFS($F$7:$F$${end},$A$7:$A$${end},A${number},$B$7:$B$${end},"<="&B${number})`]);
    const groupKey = `${symbol}/${row.method}`;
    const cumulative = (cumulatives.get(row.method) ?? 0) + row.net;
    cumulatives.set(row.method, cumulative);
    if (!ranges.has(groupKey)) ranges.set(groupKey, []);
    ranges.get(groupKey).push({ row: number, session: row.session });
    expectedCells.push({ sheet: sheet.name, row: number, net: row.net, cumulative });
  }
  sheet.getRange(`A7:O${end}`).values = values;
  sheet.getRange(`F7:F${end}`).formulas = netFormulas;
  sheet.getRange(`G7:G${end}`).formulas = cumulativeFormulas;
  sheet.getRange(`B7:B${end}`).setNumberFormat('yyyy/mm/dd hh:mm');
  sheet.getRange(`J7:L${end}`).setNumberFormat('#,##0');
  sheet.getRange(`N7:O${end}`).setNumberFormat('0.0');
  sheet.getRange(`D7:O${end}`).format.horizontalAlignment = 'right';
  sheet.getRange(`M7:M${end}`).format.horizontalAlignment = 'left';
  const detailTable = sheet.tables.add(`A6:O${end}`, true, `${sheetName}_セッション会計`);
  detailTable.showFilterButton = true;
  header(sheet, 'A6:O6');
  money(sheet, `D7:I${end}`);
  sheet.freezePanes.freezeRows(6);
  sheet.freezePanes.freezeColumns(3);
  sheet.getRange(`A1:A${end}`).format.columnWidth = 16;
  sheet.getRange(`B1:B${end}`).format.columnWidth = 25;
  sheet.getRange(`C1:C${end}`).format.columnWidth = 12;
  sheet.getRange(`D1:I${end}`).format.columnWidth = 19;
  sheet.getRange(`J1:O${end}`).format.columnWidth = 17;
  detailTotals[groupKey] = { end, rows: ordered.length, methods: 1, sheet: sheetName };
  console.log(`${sheetName} ${ordered.length}会計を配置`);
}

// ----------------------------------------
// 選択候補を上に置き、既知区間と追加区間を混ぜずに比較する。

const summaryRows = [...data.summary].sort((a, b) => {
  const ar = selectedRank.get(`${a.symbol}/${a.method}`) ?? (symbols.indexOf(a.symbol) + 1) * 10000;
  const br = selectedRank.get(`${b.symbol}/${b.method}`) ?? (symbols.indexOf(b.symbol) + 1) * 10000;
  return ar - br || a.method.localeCompare(b.method, 'en', { numeric: true }) || scopeOrder[a.scope] - scopeOrder[b.scope];
});
const summaryEnd = summaryRows.length + 6;
styleSheet(comparison, `A1:Q${summaryEnd}`);
comparison.getRange('A2').values = [['原板診断を受けた改善手法の比較']];
comparison.getRange('A3').values = [['日経mini・TOPIXminiは片方向上限10枚。金額は円・手数料後。候補を先に表示しています。']];
if (!data.selection_note || typeof data.selection_note !== 'string') throw new Error('比較案と約定模型の説明がありません');
comparison.mergeCells('A4:J4');
comparison.getRange('A4').values = [[data.selection_note]];
comparison.getRange('A4:J4').format.wrapText = true;
comparison.getRange('A4:J4').format.rowHeight = 54;
comparison.getRange('A5').values = [['B5内部は日経：昼T06・夜U06、TOPIX：昼T06・夜T04。初回まで・保有は参加した場の平均（分）。']];
comparison.getRange('A6:Q6').values = [[
  '商品', '手法ID', '対象', '総利益（円）', '総損失（円）', '収支（円）', '黒字場数', '赤字場数',
  '上位3黒字除外（円）', '新規回数', '最悪収支（円）', '平均赤字（円）', '初回まで（分）', '保有（分）', '最大片方向保有', '手法名', '無取引場数',
]];
const comparisonChecks = [];
for (let index = 0; index < summaryRows.length; index++) {
  const stat = summaryRows[index];
  const number = index + 7;
  const selected = scoped(ranges.get(`${stat.symbol}/${stat.method}`) ?? [], stat.scope);
  const start = selected[0].row, end = selected[selected.length - 1].row;
  if (end - start + 1 !== selected.length) throw new Error('集計対象が連続範囲になっていません');
  const ref = column => `'${details[`${stat.symbol}/${stat.method}`].name}'!${column}${start}:${column}${end}`;
  const net = ref('F');
  comparison.getRange(`A${number}:P${number}`).values = [[productNames[stat.symbol], stat.method, scopeNames[stat.scope],
    null, null, null, null, null, null, null, null, null, null, null, null, stat.name ?? selectedInfo.get(`${stat.symbol}/${stat.method}`).label]];
  comparison.getRange(`D${number}:O${number}`).formulas = [[
    `=SUM(${ref('D')})`, `=SUM(${ref('E')})`, `=D${number}-E${number}`,
    `=COUNTIFS(${net},">0")`, `=COUNTIFS(${net},"<0")`,
    `=F${number}-MAX(0,LARGE(${net},1))-MAX(0,LARGE(${net},2))-MAX(0,LARGE(${net},3))`,
    `=SUM(${ref('J')})`, `=MIN(${net})`,
    `=IF(H${number}=0,0,-SUMIFS(${net},${net},"<0")/H${number})`,
    `=IF(COUNTIFS(${ref('J')},">0")=0,"",AVERAGEIFS(${ref('N')},${ref('J')},">0"))`,
    `=IF(COUNTIFS(${ref('J')},">0")=0,"",AVERAGEIFS(${ref('O')},${ref('J')},">0"))`,
    `=MAX(${ref('L')})`,
  ]];
  comparison.getRange(`Q${number}`).formulas = [[`=COUNTIFS(${ref('J')},"=0")`]];
  comparisonChecks.push({ row: number, expected: [stat.profit, stat.loss, stat.net, stat.wins, stat.losses, stat.ex_top3,
    stat.entries, stat.worst, stat.avg_loss, stat.first_minutes, stat.held_minutes, stat.max_per_side],
    noTrade: scoped(groups.get(`${stat.symbol}/${stat.method}`), stat.scope).filter(row => row.entries === 0).length });
}
const comparisonTable = comparison.tables.add(`A6:Q${summaryEnd}`, true, '手法の比較');
comparisonTable.showFilterButton = true;
header(comparison, 'A6:Q6');
money(comparison, `D7:F${summaryEnd}`);
money(comparison, `I7:I${summaryEnd}`);
money(comparison, `K7:L${summaryEnd}`);
comparison.getRange(`G7:H${summaryEnd}`).setNumberFormat('#,##0');
comparison.getRange(`J7:J${summaryEnd}`).setNumberFormat('#,##0');
comparison.getRange(`M7:N${summaryEnd}`).setNumberFormat('0.0');
comparison.getRange(`O7:O${summaryEnd}`).setNumberFormat('#,##0');
comparison.getRange(`Q7:Q${summaryEnd}`).setNumberFormat('#,##0');
comparison.getRange(`Q7:Q${summaryEnd}`).conditionalFormats.add('cellIs', {
  operator: 'greaterThan', formula: 0, format: { fill: '#FFF0CC', font: { color: '#805000' } },
});
comparison.getRange(`D7:O${summaryEnd}`).format.horizontalAlignment = 'right';
comparison.getRange(`A1:C${summaryEnd}`).format.columnWidth = 15;
comparison.getRange(`D1:F${summaryEnd}`).format.columnWidth = 20;
comparison.getRange(`G1:H${summaryEnd}`).format.columnWidth = 12;
comparison.getRange(`I1:I${summaryEnd}`).format.columnWidth = 24;
comparison.getRange(`J1:J${summaryEnd}`).format.columnWidth = 12;
comparison.getRange(`K1:L${summaryEnd}`).format.columnWidth = 20;
comparison.getRange(`M1:O${summaryEnd}`).format.columnWidth = 17;
comparison.getRange(`P1:P${summaryEnd}`).format.columnWidth = 62;
comparison.getRange(`Q1:Q${summaryEnd}`).format.columnWidth = 14;
if (summaryRows.length > 20) {
  comparison.freezePanes.freezeRows(6);
  comparison.freezePanes.freezeColumns(3);
}

// ----------------------------------------
// 保存された全条件の集計を、選定案と区別した別テーブルへ配置する。

const fullComparisonChecks = [];
const groupOrder = { '全場': 0, Day: 1, Night: 2, '上昇': 3, '下落': 4 };
const groupNames = { '全場': '全場', Day: 'デイ', Night: 'ナイト', '上昇': '上昇', '下落': '下落' };
const fullComparisons = [...(data.comparison_summary ?? []).map(row => ({ ...row, group: '全場' })), ...(data.comparisons ?? [])];
fullComparisons.sort((a, b) => symbols.indexOf(a.symbol) - symbols.indexOf(b.symbol) || a.method.localeCompare(b.method, 'en', { numeric: true })
  || scopeOrder[a.scope] - scopeOrder[b.scope] || groupOrder[a.group] - groupOrder[b.group]);
let fullComparisonRange = null;
if (fullComparisons.length) {
  const heading = summaryEnd + 5, end = heading + fullComparisons.length;
  const keys = new Set();
  comparison.getRange(`A${summaryEnd + 3}`).values = [['全条件の保存集計（選定案以外も含む）']];
  comparison.getRange(`A${summaryEnd + 3}`).format.font = { name: 'Yu Gothic', bold: true, size: 12, color: '#172B44' };
  comparison.getRange(`A${summaryEnd + 4}`).values = [['R列の区分（全場・デイ・ナイト・上昇・下落）とS列の対象場数を確認してください。']];
  comparison.getRange(`A${summaryEnd + 4}`).format.font = { name: 'Yu Gothic', size: 10, color: '#52667C' };
  comparison.getRange(`A${heading}:S${end}`).format.font = { name: 'Yu Gothic', size: 10, color: '#172B44' };
  comparison.getRange(`A${heading}:S${end}`).format.rowHeight = 22;
  comparison.getRange(`A${heading}:S${heading}`).values = [[...comparison.getRange('A6:Q6').values[0], '区分', '対象場数']];
  for (let index = 0; index < fullComparisons.length; index++) {
    const row = fullComparisons[index], number = heading + index + 1;
    const key = `${row.symbol}/${row.method}/${row.scope}/${row.group}`;
    if (keys.has(key) || !symbols.includes(row.symbol) || !(row.scope in scopeNames) || !(row.group in groupNames)) throw new Error(`全条件集計が不正です: ${key}`);
    keys.add(key);
    equal(row.profit - row.loss, row.net, `${key}/保存集計収支`);
    comparison.getRange(`A${number}:S${number}`).values = [[productNames[row.symbol], row.method, scopeNames[row.scope], row.profit, row.loss,
      null, row.wins, row.losses, row.ex_top3, row.entries, row.worst, row.avg_loss, row.first_minutes ?? null, row.held_minutes ?? null,
      row.max_per_side, row.name, row.flat, groupNames[row.group], row.sessions]];
    comparison.getRange(`F${number}`).formulas = [[`=D${number}-E${number}`]];
    fullComparisonChecks.push({ row: number, expected: row.net });
  }
  for (const stat of data.comparison_summary ?? []) {
    const parts = (data.comparisons ?? []).filter(row => row.symbol === stat.symbol && row.method === stat.method && row.scope === stat.scope && ['Day', 'Night'].includes(row.group));
    if (parts.length !== 2) throw new Error(`全条件の昼夜が揃いません: ${stat.symbol}/${stat.method}/${stat.scope}`);
    for (const field of ['sessions', 'profit', 'loss', 'net', 'entries', 'wins', 'losses', 'flat']) equal(parts.reduce((total, row) => total + row[field], 0), stat[field], `全条件昼夜合計/${stat.symbol}/${stat.method}/${stat.scope}/${field}`);
  }
  const table = comparison.tables.add(`A${heading}:S${end}`, true, '全条件と区分の比較');
  table.showFilterButton = true;
  header(comparison, `A${heading}:S${heading}`);
  money(comparison, `D${heading + 1}:F${end}`);
  money(comparison, `I${heading + 1}:I${end}`);
  money(comparison, `K${heading + 1}:L${end}`);
  comparison.getRange(`M${heading + 1}:N${end}`).setNumberFormat('0.0');
  for (const range of [`G${heading + 1}:H${end}`, `J${heading + 1}:J${end}`, `O${heading + 1}:O${end}`, `Q${heading + 1}:Q${end}`, `S${heading + 1}:S${end}`]) comparison.getRange(range).setNumberFormat('#,##0');
  comparison.getRange(`R1:R${end}`).format.columnWidth = 14;
  comparison.getRange(`S1:S${end}`).format.columnWidth = 12;
  fullComparisonRange = `A${heading}:J${Math.min(end, heading + 12)}`;
}

// ----------------------------------------
// 運用IDの中にある昼夜別の基準手法と追加方式を、48区分で明示する。

const dayNightChecks = [];
const dayNightParts = new Map((data.parts ?? []).filter(row => symbols.includes(row.symbol) && ['Day', 'Night'].includes(row.group))
  .map(row => [`${row.symbol}/${row.method}/${row.scope}/${row.group}`, row]));
const dayNightEnd = detailKeys.length * 6 + 6;
styleSheet(dayNight, `A1:Q${dayNightEnd}`);
dayNight.getRange('A2').values = [['昼夜別の基準手法と収支']];
dayNight.getRange('A3').values = [['運用IDは昼夜の組み合わせを表します。昼夜それぞれの実行手法を明記します。']];
dayNight.getRange('A4').values = [['診断3場は原因分析と改善に使用した期間です。昼夜別の比較を、未見期間の実証とは扱いません。']];
dayNight.getRange('A5').values = [['金額は円・手数料後。全期間は昼25場・夜25場、対照は昼24場・夜23場、診断は昼1場・夜2場。']];
dayNight.getRange('A6:Q6').values = [[
  '商品', '運用ID', '昼夜', '対象', '実行手法', '運用説明', '対象場数', '利益（円）', '損失（円）', '収支（円）',
  '新規数', '黒字場数', '赤字場数', '無取引場数', '平均赤字（円）', '最大赤字（円）', '上位3黒字除外（円）',
]];
for (const groupKey of detailKeys) {
  const [symbol, method] = groupKey.split('/');
  const info = selectedInfo.get(groupKey);
  for (const scope of ['all', 'known', 'new']) {
    const span = scoped(ranges.get(groupKey), scope);
    const first = span[0].row, last = span[span.length - 1].row;
    const ref = column => `'${details[groupKey].name}'!${column}${first}:${column}${last}`;
    const net = ref('F'), kind = ref('C');
    for (const group of ['Day', 'Night']) {
      const number = dayNightChecks.length + 7;
      const rows = scoped(groups.get(groupKey), scope).filter(row => row.session.endsWith(`_${group}`));
      const expectedCount = scope === 'all' ? 25 : scope === 'known' ? (group === 'Day' ? 24 : 23) : (group === 'Day' ? 1 : 2);
      if (rows.length !== expectedCount) throw new Error(`${groupKey}/${scope}/${group} の場数不一致`);
      const sum = field => rows.reduce((total, row) => total + row[field], 0);
      const losses = rows.filter(row => row.net < 0).map(row => row.net);
      const expected = [rows.length, sum('profit'), sum('loss'), sum('net'), sum('entries'), rows.filter(row => row.net > 0).length,
        losses.length, rows.filter(row => row.entries === 0).length, losses.length ? -losses.reduce((a, b) => a + b, 0) / losses.length : 0,
        Math.max(0, -Math.min(...rows.map(row => row.net))),
        sum('net') - rows.map(row => row.net).filter(value => value > 0).sort((a, b) => b - a).slice(0, 3).reduce((a, b) => a + b, 0)];
      const part = dayNightParts.get(`${groupKey}/${scope}/${group}`);
      if (!part) throw new Error(`${groupKey}/${scope}/${group} の保存集計がありません`);
      const fields = ['sessions', 'profit', 'loss', 'net', 'entries', 'wins', 'losses', 'flat', 'avg_loss'];
      fields.forEach((field, index) => equal(expected[index], part[field], `${groupKey}/${scope}/${group}/${field}`));
      equal(expected[9], Math.max(0, -part.worst), `${groupKey}/${scope}/${group}/最大赤字`);
      equal(expected[10], part.ex_top3, `${groupKey}/${scope}/${group}/上位3黒字除外`);
      dayNight.getRange(`A${number}:F${number}`).values = [[productNames[symbol], method, group === 'Day' ? 'デイ' : 'ナイト', scopeNames[scope],
        executionLabel(symbol, group === 'Day' ? info.day_method : info.night_method, group), info.label]];
      const firstWin = `MAX(0,_xlfn.MAXIFS(${net},${kind},C${number}))`;
      const secondWin = `IF(COUNTIFS(${net},${firstWin},${kind},C${number})>=2,${firstWin},MAX(0,_xlfn.MAXIFS(${net},${kind},C${number},${net},"<"&${firstWin})))`;
      const thirdWin = `IF(COUNTIFS(${net},${firstWin},${kind},C${number})>=3,${firstWin},IF(COUNTIFS(${net},${secondWin},${kind},C${number})+COUNTIFS(${net},">"&${secondWin},${kind},C${number})>=3,${secondWin},MAX(0,_xlfn.MAXIFS(${net},${kind},C${number},${net},"<"&${secondWin}))))`;
      dayNight.getRange(`G${number}:Q${number}`).formulas = [[
        `=COUNTIFS(${kind},C${number})`, `=SUMIFS(${ref('D')},${kind},C${number})`, `=SUMIFS(${ref('E')},${kind},C${number})`, `=H${number}-I${number}`,
        `=SUMIFS(${ref('J')},${kind},C${number})`, `=COUNTIFS(${net},">0",${kind},C${number})`, `=COUNTIFS(${net},"<0",${kind},C${number})`,
        `=COUNTIFS(${ref('J')},"=0",${kind},C${number})`, `=IF(M${number}=0,0,-SUMIFS(${net},${net},"<0",${kind},C${number})/M${number})`,
        `=MAX(0,-_xlfn.MINIFS(${net},${kind},C${number}))`,
        `=J${number}-${firstWin}-${secondWin}-${thirdWin}`,
      ]];
      dayNightChecks.push({ row: number, symbol, method, scope, group, expected });
    }
  }
}
const dayNightTable = dayNight.tables.add(`A6:Q${dayNightEnd}`, true, '昼夜別比較');
dayNightTable.showFilterButton = true;
header(dayNight, 'A6:Q6');
money(dayNight, `H7:J${dayNightEnd}`);
money(dayNight, `O7:Q${dayNightEnd}`);
dayNight.getRange(`G7:G${dayNightEnd}`).setNumberFormat('#,##0');
dayNight.getRange(`K7:N${dayNightEnd}`).setNumberFormat('#,##0');
dayNight.getRange(`A1:E${dayNightEnd}`).format.columnWidth = 14;
dayNight.getRange(`F1:F${dayNightEnd}`).format.columnWidth = 48;
dayNight.getRange(`F7:F${dayNightEnd}`).format.wrapText = true;
dayNight.getRange(`A7:Q${dayNightEnd}`).format.rowHeight = 36;
dayNight.getRange(`G1:G${dayNightEnd}`).format.columnWidth = 12;
dayNight.getRange(`H1:J${dayNightEnd}`).format.columnWidth = 20;
dayNight.getRange(`K1:N${dayNightEnd}`).format.columnWidth = 13;
dayNight.getRange(`O1:Q${dayNightEnd}`).format.columnWidth = 23;
dayNight.freezePanes.freezeRows(6);
dayNight.freezePanes.freezeColumns(4);

// ----------------------------------------
// 代表入力を一時変更して依存式を確認し、復元後に全明細・集計を照合する。

book.recalculate();
const probeSheet = details[detailKeys[0]];
const probeSymbol = detailKeys[0].split('/')[0];
const originalProfit = probeSheet.getRange('D7').values[0][0];
const originalNet = probeSheet.getRange('F7').values[0][0];
const originalCumulative = probeSheet.getRange('G7').values[0][0];
const probeMethod = probeSheet.getRange('A7').values[0][0];
const probeSummaryRow = summaryRows.findIndex(row => row.symbol === probeSymbol && row.method === probeMethod && row.scope === 'all') + 7;
const originalSummaryNet = comparison.getRange(`F${probeSummaryRow}`).values[0][0];
const probeDayNightRow = dayNightChecks.find(row => row.symbol === probeSymbol && row.method === probeMethod && row.scope === 'all' && row.group === 'Day').row;
const originalDayNightNet = dayNight.getRange(`J${probeDayNightRow}`).values[0][0];
try {
  probeSheet.getRange('D7').values = [[originalProfit + 1000]];
  book.recalculate();
  equal(probeSheet.getRange('F7').values[0][0], originalNet + 1000, '代表入力変更後の収支');
  equal(probeSheet.getRange('G7').values[0][0], originalCumulative + 1000, '代表入力変更後の累計');
  equal(comparison.getRange(`F${probeSummaryRow}`).values[0][0], originalSummaryNet + 1000, '代表入力変更後の全場集計');
  equal(dayNight.getRange(`J${probeDayNightRow}`).values[0][0], originalDayNightNet + 1000, '代表入力変更後の昼夜集計');
} finally {
  probeSheet.getRange('D7').values = [[originalProfit]];
  book.recalculate();
}
for (const check of expectedCells) {
  const values = book.worksheets.getItem(check.sheet).getRange(`F${check.row}:G${check.row}`).values[0];
  equal(values[0], check.net, `${check.sheet}/${check.row} 収支`);
  equal(values[1], check.cumulative, `${check.sheet}/${check.row} 累計`);
}
for (const check of comparisonChecks) {
  const values = comparison.getRange(`D${check.row}:O${check.row}`).values[0];
  check.expected.forEach((value, index) => equalNullable(values[index], value, `比較/${check.row}/${index}`));
  equal(comparison.getRange(`Q${check.row}`).values[0][0], check.noTrade, `比較/${check.row}/無取引`);
}
for (const check of fullComparisonChecks) equal(comparison.getRange(`F${check.row}`).values[0][0], check.expected, `全条件比較/${check.row}/収支`);
for (const check of dayNightChecks) {
  const values = dayNight.getRange(`G${check.row}:Q${check.row}`).values[0];
  check.expected.forEach((value, index) => equal(values[index], value, `昼夜比較/${check.row}/${index}`));
}
if (lossView) {
  for (const check of lossView.checks) equal(lossView.sheet.getRange(`G${check.row}`).values[0][0], check.expected, `具体損失時間/${check.row}/差額`);
}
for (const stat of data.summary) {
  const checks = dayNightChecks.filter(row => row.symbol === stat.symbol && row.method === stat.method && row.scope === stat.scope);
  for (const [index, field] of [[0, 'sessions'], [1, 'profit'], [2, 'loss'], [3, 'net'], [4, 'entries'], [5, 'wins'], [6, 'losses'], [7, 'flat']]) {
    equal(checks.reduce((total, row) => total + row.expected[index], 0), stat[field], `${stat.symbol}/${stat.method}/${stat.scope} 昼夜合計${field}`);
  }
}
const errors = await book.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',
  options: { useRegex: true, maxResults: 30 }, maxChars: 5000 });
await fs.writeFile(path.join(work, 'xlsx数式エラー確認141.jsonl'), errors.ndjson, 'utf8');
const inspection = await book.inspect({ kind: 'table', range: `比較!A6:P${Math.min(summaryEnd, 15)}`,
  include: 'values,formulas', tableMaxRows: 10, tableMaxCols: 16, maxChars: 6500 });
await fs.writeFile(path.join(work, 'xlsx比較確認141.jsonl'), inspection.ndjson, 'utf8');
const renderRanges = [['比較', `A1:J${Math.min(summaryEnd, 19)}`, 'xlsx比較141.png'],
  ['比較', `K6:Q${Math.min(summaryEnd, 19)}`, 'xlsx比較右141.png']];
if (summaryEnd > 19) renderRanges.push(['比較', `A19:J${summaryEnd}`, 'xlsx比較TOPIX141.png'], ['比較', `K19:Q${summaryEnd}`, 'xlsx比較TOPIX右141.png']);
renderRanges.push(['昼夜比較', `A1:J${Math.min(dayNightEnd, 18)}`, 'xlsx昼夜比較141.png'], ['昼夜比較', `K6:Q${Math.min(dayNightEnd, 18)}`, 'xlsx昼夜比較右141.png']);
if (dayNightEnd === 54) renderRanges.push(['昼夜比較', 'A19:J30', 'xlsx昼夜比較日経改善141.png'], ['昼夜比較', 'A43:J54', 'xlsx昼夜比較TOPIX改善141.png']);
if (lossView) renderRanges.push(['具体損失時間', `A1:H${Math.min(lossView.end, 18)}`, 'xlsx具体損失時間141.png']);
if (fullComparisonRange) {
  renderRanges.push(['比較', `A${summaryEnd + 3}:J${summaryEnd + 17}`, 'xlsx全条件比較141.png']);
  renderRanges.push(['比較', `K${summaryEnd + 5}:S${summaryEnd + 17}`, 'xlsx全条件比較右141.png']);
}
for (const sheet of Object.values(details)) renderRanges.push([sheet.name, 'A1:J15', `xlsx${sheet.name}141.png`]);
for (const symbol of symbols) {
  const name = details[detailKeys.find(key => key.startsWith(`${symbol}/`))].name;
  renderRanges.push([name, 'K6:O15', `xlsx${name}右141.png`]);
}
for (const [sheetName, range, name] of renderRanges) {
  const preview = await book.render({ sheetName, range, scale: 1.5, format: 'png' });
  await fs.writeFile(path.join(work, name), new Uint8Array(await preview.arrayBuffer()));
}
await fs.mkdir(outputDirectory, { recursive: true });
await fs.mkdir(publicDirectory, { recursive: true });
await (await SpreadsheetFile.exportXlsx(book)).save(output);
await fs.copyFile(output, published);
const payload = await fs.readFile(output);
const publishedPayload = await fs.readFile(published);
const sha256 = createHash('sha256').update(payload).digest('hex');
if (!payload.equals(publishedPayload)) throw new Error('指定公開先と出力ファイルが一致しません');
await fs.writeFile(path.join(work, 'xlsx照合141.json'), JSON.stringify({
  入力: input, 入力SHA256: createHash('sha256').update(sourceBytes).digest('hex'),
  全会計数: data.rows.length, 商品別: detailTotals, 集計数: comparisonChecks.length, 昼夜集計数: dayNightChecks.length,
  全条件比較数: fullComparisonChecks.length, 損失時点数: lossView?.checks.length ?? 0,
  全収支と累計と集計の数値照合: true, 代表利益入力変更による再計算確認と復元: true, 評価区分: { 対照: 47, 診断: 3 },
  出力: output, 指定公開先: published, 同一ファイルSHA256: sha256,
  注記: '収支と累計をExcel式で計算。Excelアプリでの操作確認は別。',
}, null, 2) + '\n', 'utf8');
console.log(`保存完了: ${published}`);
