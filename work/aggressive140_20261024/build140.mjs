import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const work = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(work, '../..');
const input = path.join(work, 'report_data140.json');
const publicDirectory = path.join(root, 'アルゴリズム調査/00140_参加機会の拡大と商品別戦略の再検証');
const outputDirectory = path.join(root, 'outputs/00140_aggressive_20261024');
const filename = '参加機会の改善と全セッション損益.xlsx';
const output = path.join(outputDirectory, filename);
const published = path.join(publicDirectory, filename);
const sourceBytes = await fs.readFile(input);
const data = JSON.parse(sourceBytes.toString('utf8').replace(/^\uFEFF/, ''));
const knownEnd = '2026-10-22_Day';
const symbols = ['NK225', 'TOPIX'];
const productNames = { NK225: '日経mini', TOPIX: 'TOPIXmini' };
const scopeNames = { all: '全50場', known: '既知47場', new: '追加3場' };
const expectedCounts = { all: 50, known: 47, new: 3 };
const scopeOrder = { all: 0, known: 1, new: 2 };
const selectedRank = new Map(data.selected.map((row, index) => [`${row.symbol}/${row.method}`, index]));

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

// ----------------------------------------
// 元の会計と集計を先に照合する。手数料を二重に控除しない。

if (!Array.isArray(data.rows) || !Array.isArray(data.summary) || !Array.isArray(data.selected)) {
  throw new Error('report_data140.json の構造が不正です');
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
const details = {};
const ranges = new Map();
const expectedCells = [];
const detailTotals = {};
const pairChecks = [];
const pairSummaryChecks = [];
const detailKeys = [...groups.keys()].sort((a, b) => (selectedRank.get(a) ?? 10000) - (selectedRank.get(b) ?? 10000) || a.localeCompare(b, 'en', { numeric: true }));
for (const groupKey of detailKeys) {
  const [symbol, method] = groupKey.split('/');
  const sheetName = `${symbol === 'NK225' ? '日経' : 'TOPIX'}_${method}`;
  const sheet = book.worksheets.add(sheetName);
  details[groupKey] = sheet;
  const ordered = groups.get(groupKey);
  if (ordered.length === 0 || ordered.length >= 10000) throw new Error(`${symbol} の明細数が想定外です: ${ordered.length}`);
  const end = ordered.length + 6;
  styleSheet(sheet, `A1:O${end}`);
  sheet.getRange('A2').values = [[`${productNames[symbol]} ${method} セッション損益`]];
  sheet.getRange('A3').values = [['片方向上限10枚。金額は円・手数料後。利益と損失は完結した一組の収支を正負に分類。']];
  sheet.getRange('A4').values = [[`昼基準：T06／夜基準：${symbol === 'NK225' ? 'U06' : 'T04'}。既知47場：9/21～10/22デイ。追加3場：10/22ナイト～10/23ナイト。`]];
  sheet.getRange('A5').values = [[method.startsWith('C') || method.startsWith('S')
    ? '追加入口は昼夜共通の比較。夜のみ米国開始前後15分は静観。累計は日時順。出典：00140保存会計。'
    : `${method.startsWith('R') ? '利確後の再参加条件のみ変更。' : '追加なし。'}昼夜別の基準手法で運用。累計は日時順。出典：00140保存会計。`]];
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
      row.entries, row.quantity, row.max_per_side, row.session <= knownEnd ? '既知47場' : '追加3場', row.first_minutes ?? null, row.held_minutes ?? null]);
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
// ペア取引は二脚を一組として別表に置き、単独商品の比較へ混ぜない。

const pairRows = [...(data.pair_rows ?? [])].sort((a, b) => a.method.localeCompare(b.method) || a.session.localeCompare(b.session));
let pairSheet = null;
if (pairRows.length) {
  pairSheet = book.worksheets.add('ペア_P03');
  const start = 14, end = start + pairRows.length - 1;
  const pairKeys = new Set(), cumulative = new Map(), values = [], netFormulas = [], cumulativeFormulas = [];
  const pairGroups = new Map();
  styleSheet(pairSheet, `A1:T${end}`);
  pairSheet.getRange('A2').values = [['二市場ペア取引（不採用の比較対象）']];
  pairSheet.getRange('A3').values = [['日経mini・TOPIXminiの二脚を一組で評価。各商品上限10枚。金額は円・手数料後。']];
  pairSheet.getRange('A4').values = [['初回まで・保有は判断起点。単独商品シートは約定起点のため、時間を直接比較しません。']];
  pairSheet.getRange('A5').values = [['元本差は判断時の絶対差の場内最大。片脚時間は各組の片脚保有秒の場内合計。出典：00140再生会計。']];
  pairSheet.getRange('A7:J7').values = [['対象', '総利益（円）', '総損失（円）', '収支（円）', '黒字場数', '赤字場数', '無取引場数', '新規組数', '手数料（円）', '上位3黒字除外（円）']];
  pairSheet.getRange('A13:T13').values = [[
    '手法ID', '開始日時', 'セッション', '利益（円）', '損失（円）', '収支（円）', '累計（円）',
    '内数手数料（円）', '費用前収支（円）', '新規回数', '二脚合計枚数', '商品別最大保有', '評価区分', '初回まで（分）', '保有（分）',
    '日経脚収支（円）', 'TOPIX脚収支（円）', '完結組数', '元本差最大（円）', '片脚保有合計（秒）',
  ]];
  for (const row of pairRows) {
    const key = `${row.method}/${row.session}`;
    if (pairKeys.has(key) || row.symbol !== 'PAIR') throw new Error(`ペア会計の重複又は種別不正: ${key}`);
    pairKeys.add(key);
    equal(row.profit - row.loss, row.net, `${key} ペア利益−損失`);
    equal(row.gross - row.fees, row.net, `${key} ペア費用前−手数料`);
    equal(row.nk_net + row.topix_net, row.net, `${key} 二脚合計`);
    for (const field of ['profit', 'loss', 'fees', 'entries', 'quantity', 'max_per_side', 'pair_count', 'mismatch', 'single_leg_seconds']) {
      if (!Number.isFinite(row[field]) || row[field] < 0) throw new Error(`${key} ペア${field}が不正です`);
    }
    if (row.max_per_side > 10) throw new Error(`${key} ペアの商品別上限超過`);
    const number = start + values.length;
    const kind = row.session.endsWith('_Day') ? 'デイ' : 'ナイト';
    const date = new Date(`${row.session.slice(0, 10)}T${kind === 'デイ' ? '08:45' : '17:00'}:00Z`);
    values.push([row.method, date, kind, row.profit, row.loss, null, null, row.fees, row.gross, row.entries, row.quantity,
      row.max_per_side, row.session <= knownEnd ? '既知47場' : '追加3場', row.first_minutes ?? null, row.held_minutes ?? null,
      row.nk_net, row.topix_net, row.pair_count, row.mismatch, row.single_leg_seconds]);
    netFormulas.push([`=D${number}-E${number}`]);
    cumulativeFormulas.push([`=SUMIFS($F$${start}:$F$${end},$A$${start}:$A$${end},A${number},$B$${start}:$B$${end},"<="&B${number})`]);
    const total = (cumulative.get(row.method) ?? 0) + row.net;
    cumulative.set(row.method, total);
    pairChecks.push({ row: number, net: row.net, cumulative: total });
    if (!pairGroups.has(row.method)) pairGroups.set(row.method, []);
    pairGroups.get(row.method).push({ ...row, row: number });
  }
  if (pairGroups.size !== 1) throw new Error('ペア比較の集計は一手法を想定しています');
  pairSheet.getRange(`A${start}:T${end}`).values = values;
  pairSheet.getRange(`F${start}:F${end}`).formulas = netFormulas;
  pairSheet.getRange(`G${start}:G${end}`).formulas = cumulativeFormulas;
  const records = [...pairGroups.values()][0];
  for (const [index, scope] of ['all', 'known', 'new'].entries()) {
    const selected = scoped(records, scope);
    if (selected.length !== expectedCounts[scope]) throw new Error(`ペアの${scope}場数が違います`);
    const first = selected[0].row, last = selected[selected.length - 1].row, number = index + 8;
    const ref = column => `${column}${first}:${column}${last}`;
    const net = ref('F');
    pairSheet.getRange(`A${number}`).values = [[scopeNames[scope]]];
    pairSheet.getRange(`B${number}:J${number}`).formulas = [[`=SUM(${ref('D')})`, `=SUM(${ref('E')})`, `=B${number}-C${number}`,
      `=COUNTIFS(${net},">0")`, `=COUNTIFS(${net},"<0")`, `=COUNTIFS(${ref('J')},"=0")`, `=SUM(${ref('J')})`,
      `=SUM(${ref('H')})`, `=D${number}-MAX(0,LARGE(${net},1))-MAX(0,LARGE(${net},2))-MAX(0,LARGE(${net},3))`]];
    const sum = field => selected.reduce((total, row) => total + row[field], 0);
    pairSummaryChecks.push({ row: number, expected: [sum('profit'), sum('loss'), sum('net'), selected.filter(row => row.net > 0).length,
      selected.filter(row => row.net < 0).length, selected.filter(row => row.entries === 0).length, sum('entries'), sum('fees'),
      sum('net') - selected.map(row => row.net).filter(value => value > 0).sort((a, b) => b - a).slice(0, 3).reduce((total, value) => total + value, 0)] });
  }
  const pairSummaryTable = pairSheet.tables.add('A7:J10', true, 'ペア_P03_対象別集計');
  pairSummaryTable.showFilterButton = true;
  const pairDetailTable = pairSheet.tables.add(`A13:T${end}`, true, 'ペア_P03_セッション会計');
  pairDetailTable.showFilterButton = true;
  header(pairSheet, 'A7:J7');
  header(pairSheet, 'A13:T13');
  money(pairSheet, 'B8:D10');
  money(pairSheet, 'I8:J10');
  money(pairSheet, `D${start}:I${end}`);
  money(pairSheet, `P${start}:Q${end}`);
  money(pairSheet, `S${start}:S${end}`);
  pairSheet.getRange(`B${start}:B${end}`).setNumberFormat('yyyy/mm/dd hh:mm');
  pairSheet.getRange(`J${start}:L${end}`).setNumberFormat('#,##0');
  pairSheet.getRange(`N${start}:O${end}`).setNumberFormat('0.0');
  pairSheet.getRange(`R${start}:R${end}`).setNumberFormat('#,##0');
  pairSheet.getRange(`T${start}:T${end}`).setNumberFormat('0.0');
  pairSheet.getRange(`A1:A${end}`).format.columnWidth = 16;
  pairSheet.getRange(`B1:B${end}`).format.columnWidth = 25;
  pairSheet.getRange(`C1:C${end}`).format.columnWidth = 19;
  pairSheet.getRange(`D1:J${end}`).format.columnWidth = 22;
  pairSheet.getRange(`K1:O${end}`).format.columnWidth = 19;
  pairSheet.getRange(`P1:T${end}`).format.columnWidth = 23;
  pairSheet.freezePanes.freezeRows(13);
  pairSheet.freezePanes.freezeColumns(3);
  detailTotals.PAIR = { end, rows: pairRows.length, methods: pairGroups.size };
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
comparison.getRange('A2').values = [['参加機会を増やす手法の比較']];
comparison.getRange('A3').values = [['日経mini・TOPIXminiは片方向上限10枚。金額は円・手数料後。候補を先に表示しています。']];
comparison.getRange('A4').values = [['全50場は選択候補のみ。既知47場と、条件固定後の追加3場を分けて比較します。']];
comparison.getRange('A5').values = [['初回まで・保有は、参加したセッションの算術平均（分）。同時保有上限と実際の最大保有を区別します。']];
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
    null, null, null, null, null, null, null, null, null, null, null, null, stat.name]];
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
// 運用IDの中にある昼夜別の基準手法と追加方式を、48区分で明示する。

const dayNightChecks = [];
const dayNightParts = new Map((data.parts ?? []).filter(row => symbols.includes(row.symbol) && ['Day', 'Night'].includes(row.group))
  .map(row => [`${row.symbol}/${row.method}/${row.scope}/${row.group}`, row]));
const dayNightEnd = detailKeys.length * 6 + 6;
styleSheet(dayNight, `A1:Q${dayNightEnd}`);
dayNight.getRange('A2').values = [['昼夜別の基準手法と収支']];
dayNight.getRange('A3').values = [['運用IDは組み合わせの名称。日経は昼T06・夜U06、TOPIXは昼T06・夜T04を基準とします。']];
dayNight.getRange('A4').values = [['C・Sの追加入口は昼夜共通で比較しました。夜のみ米国開始前後15分は静観します。昼夜専用の追加入口ではありません。']];
dayNight.getRange('A5').values = [['金額は円・手数料後。全期間は昼25場・夜25場、既知は昼24場・夜23場、追加は昼1場・夜2場。']];
dayNight.getRange('A6:Q6').values = [[
  '商品', '運用ID', '昼夜', '対象', '基準手法', '追加方式', '対象場数', '利益（円）', '損失（円）', '収支（円）',
  '新規数', '黒字場数', '赤字場数', '無取引場数', '平均赤字（円）', '最大赤字（円）', '上位3黒字除外（円）',
]];
const extraDescriptions = {
  B5: '追加なし', R02: '利確後の再参加。待機条件だけの対照', R09: '利確後に1枚で再参加',
  C33: '先着採用。40分の低効率帯の端から反転、追加最大2枚',
  S33: '独立枠。40分の低効率帯の端から反転、追加最大2枚',
  C36: '先着採用。40分の効率で追従・反転を切替、追加最大5枚',
  S36: '独立枠。40分の効率で追従・反転を切替、追加最大5枚',
};
for (const groupKey of detailKeys) {
  const [symbol, method] = groupKey.split('/');
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
        group === 'Day' ? 'T06' : symbol === 'NK225' ? 'U06' : 'T04', extraDescriptions[method]]];
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
const probeSheet = details['NK225/B5'];
const originalProfit = probeSheet.getRange('D7').values[0][0];
const originalNet = probeSheet.getRange('F7').values[0][0];
const originalCumulative = probeSheet.getRange('G7').values[0][0];
const probeMethod = probeSheet.getRange('A7').values[0][0];
const probeSummaryRow = summaryRows.findIndex(row => row.symbol === 'NK225' && row.method === probeMethod && row.scope === 'all') + 7;
const originalSummaryNet = comparison.getRange(`F${probeSummaryRow}`).values[0][0];
const probeDayNightRow = dayNightChecks.find(row => row.symbol === 'NK225' && row.method === 'B5' && row.scope === 'all' && row.group === 'Day').row;
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
for (const check of pairChecks) {
  const values = pairSheet.getRange(`F${check.row}:G${check.row}`).values[0];
  equal(values[0], check.net, `ペア/${check.row}/収支`);
  equal(values[1], check.cumulative, `ペア/${check.row}/累計`);
}
for (const check of pairSummaryChecks) {
  const values = pairSheet.getRange(`B${check.row}:J${check.row}`).values[0];
  check.expected.forEach((value, index) => equal(values[index], value, `ペア集計/${check.row}/${index}`));
}
for (const check of dayNightChecks) {
  const values = dayNight.getRange(`G${check.row}:Q${check.row}`).values[0];
  check.expected.forEach((value, index) => equal(values[index], value, `昼夜比較/${check.row}/${index}`));
}
for (const stat of data.summary) {
  const checks = dayNightChecks.filter(row => row.symbol === stat.symbol && row.method === stat.method && row.scope === stat.scope);
  for (const [index, field] of [[0, 'sessions'], [1, 'profit'], [2, 'loss'], [3, 'net'], [4, 'entries'], [5, 'wins'], [6, 'losses'], [7, 'flat']]) {
    equal(checks.reduce((total, row) => total + row.expected[index], 0), stat[field], `${stat.symbol}/${stat.method}/${stat.scope} 昼夜合計${field}`);
  }
}
const errors = await book.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',
  options: { useRegex: true, maxResults: 30 }, maxChars: 5000 });
await fs.writeFile(path.join(work, 'xlsx数式エラー確認140.jsonl'), errors.ndjson, 'utf8');
const inspection = await book.inspect({ kind: 'table', range: `比較!A6:P${Math.min(summaryEnd, 15)}`,
  include: 'values,formulas', tableMaxRows: 10, tableMaxCols: 16, maxChars: 6500 });
await fs.writeFile(path.join(work, 'xlsx比較確認140.jsonl'), inspection.ndjson, 'utf8');
const renderRanges = [['比較', `A1:J${Math.min(summaryEnd, 19)}`, 'xlsx比較140.png'],
  ['比較', `A19:J${summaryEnd}`, 'xlsx比較TOPIX140.png'],
  ['比較', `K6:Q${Math.min(summaryEnd, 19)}`, 'xlsx比較右140.png']];
renderRanges.push(['昼夜比較', 'A1:J18', 'xlsx昼夜比較140.png'], ['昼夜比較', 'K6:Q18', 'xlsx昼夜比較右140.png'], ['昼夜比較', 'A31:J42', 'xlsx昼夜比較TOPIX140.png']);
for (const sheet of Object.values(details)) renderRanges.push([sheet.name, 'A1:J15', `xlsx${sheet.name}140.png`]);
renderRanges.push(['日経_B5', 'K6:O15', 'xlsx日経_B5右140.png'], ['TOPIX_C33', 'K6:O15', 'xlsxTOPIX_C33右140.png']);
if (pairSheet) renderRanges.push(['ペア_P03', 'A1:J18', 'xlsxペア_P03140.png'], ['ペア_P03', 'K13:T20', 'xlsxペア_P03右140.png']);
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
await fs.writeFile(path.join(work, 'xlsx照合140.json'), JSON.stringify({
  入力: input, 入力SHA256: createHash('sha256').update(sourceBytes).digest('hex'),
  全会計数: data.rows.length, ペア会計数: pairRows.length, 商品別: detailTotals, 集計数: comparisonChecks.length, 昼夜集計数: dayNightChecks.length,
  全収支と累計と集計の数値照合: true, 代表利益入力変更による再計算確認と復元: true, 旧追加区分: { 既知: 47, 追加: 3 },
  出力: output, 指定公開先: published, 同一ファイルSHA256: sha256,
  注記: '収支と累計をExcel式で計算。Excelアプリでの操作確認は別。',
}, null, 2) + '\n', 'utf8');
console.log(`保存完了: ${published}`);
