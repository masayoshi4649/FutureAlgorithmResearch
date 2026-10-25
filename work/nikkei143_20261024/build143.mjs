import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const work = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(work, '../..');
const source = path.join(work, 'report_data143.json');
const evidenceSource = path.join(work, 'F1始終値方向と深夜除外保有率143.json');
const outputDirectory = path.join(root, 'outputs/00143_nikkei_20261024');
const publicDirectory = path.join(root, 'アルゴリズム調査/00143_日経特化の方向偏りと深夜除外の改善');
const filename = '日経専用の方向別比較と全セッション損益.xlsx';
const sourceBytes = await fs.readFile(source);
const data = JSON.parse(sourceBytes.toString('utf8').replace(/^\uFEFF/, ''));
const evidenceBytes = await fs.readFile(evidenceSource);
const evidence = JSON.parse(evidenceBytes.toString('utf8').replace(/^\uFEFF/, ''));
const knownEnd = '2026-10-22_Day';
const scopeNames = { all: '既知開発50場', known: '比較47場', new: '診断3場' };
const groupNames = { all: '全方向・昼夜', Day: 'デイ', Night: 'ナイト', 上昇: '上昇場', 下落: '下落場', 横ばい: '横ばい場',
  Day_上昇: 'デイ・上昇', Day_下落: 'デイ・下落', Night_上昇: 'ナイト・上昇', Night_下落: 'ナイト・下落',
  同値: '同値場', Day_同値: 'デイ・同値', Night_同値: 'ナイト・同値' };
const moneyFormat = '#,##0;[Red](#,##0);"-"';

/**
 * 数値を独立計算した期待値と照合する。
 * @param {number} actual - 実際の数値。
 * @param {number} expected - 元資料から得た期待値。
 * @param {string} label - 不一致の項目名。
 * @param {number} tolerance - 許容誤差。
 * @returns {void} 不一致なら例外にする。
 */
function equal(actual, expected, label, tolerance = 0.001) {
  if (!Number.isFinite(actual) || !Number.isFinite(expected) || Math.abs(actual - expected) > tolerance) {
    throw new Error(`${label}: 実際${actual}／期待${expected}`);
  }
}

/**
 * 列番号をExcel列記号へ変換する。
 * @param {number} value - 1始まりの列番号。
 * @returns {string} Excel列記号。
 */
function column(value) {
  let result = '';
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + value % 26) + result;
    value = Math.floor(value / 26);
  }
  return result;
}

/**
 * 日本時間を時差のないExcel表示用日時へ変換する。
 * @param {string} value - 時差付きISO8601時計。
 * @returns {Date} 日本時間の表示日時。
 */
function clock(value) {
  if (!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)) throw new Error(`時差のない時計: ${value}`);
  const result = new Date(Date.parse(value) + 9 * 3600 * 1000);
  if (!Number.isFinite(result.valueOf())) throw new Error(`不正な時計: ${value}`);
  return result;
}

/**
 * 03～06時を除いたセッションの評価時間を返す。
 * @param {string} session - セッションID。
 * @returns {number} デイ420分又はナイト600分。
 */
function evaluationMinutes(session) {
  return session.endsWith('_Day') ? 420 : 600;
}

/**
 * 指定区分に該当する会計を選ぶ。
 * @param {object[]} rows - 一手法の会計。
 * @param {string} scope - all、known、new。
 * @param {string} group - 昼夜・始終値方向の区分。
 * @returns {object[]} 該当会計。
 */
function filterRows(rows, scope = 'all', group = 'all') {
  if (!(scope in scopeNames) || !(group in groupNames)) throw new Error(`未知区分: ${scope}/${group}`);
  return rows.filter(row => {
    if (scope !== 'all' && (scope === 'known' ? row.session > knownEnd : row.session <= knownEnd)) return false;
    if (group === 'all') return true;
    return group.split('_').every(part => part === 'Day' || part === 'Night'
      ? row.session.endsWith(`_${part}`) : row.direction === part);
  });
}

/**
 * セッション集計を明細から独立計算する。
 * @param {object[]} rows - 対象会計。
 * @returns {object} 利益・損失・頻度・保有率の集計。
 */
function statistics(rows) {
  const sum = key => rows.reduce((total, row) => total + row[key], 0);
  const nets = rows.map(row => row.net).sort((a, b) => a - b);
  const losses = nets.filter(value => value < 0).map(value => -value).sort((a, b) => a - b);
  const median = values => values.length ? (values[Math.floor((values.length - 1) / 2)] + values[Math.floor(values.length / 2)]) / 2 : 0;
  return { sessions: rows.length, profit: sum('profit'), loss: sum('loss'), net: sum('net'),
    wins: nets.filter(value => value > 0).length, losses: losses.length, flat: rows.filter(row => row.entries === 0).length,
    avg_loss: losses.length ? losses.reduce((a, b) => a + b, 0) / losses.length : 0, median_loss: median(losses),
    max_loss: Math.max(0, ...losses), ex_top3: sum('net') - nets.filter(value => value > 0).slice(-3).reduce((a, b) => a + b, 0),
    median: median(nets), entries: sum('entries'),
    mean_holding_ratio: rows.length ? sum('holding_ratio_excluding_03_06') / rows.length : 0,
    time_weighted_holding_ratio: rows.length ? sum('held_minutes_excluding_03_06') / rows.reduce((total, row) => total + evaluationMinutes(row.session), 0) : 0,
    avg_held_quantity_excluding_03_06: rows.length ? sum('avg_held_quantity_excluding_03_06') / rows.length : 0 };
}

/**
 * analyze143の集計名を報告用の共通名へ対応付ける。
 * @param {object} source - 保存集計。flatは同値場、zero_entryは無取引場として区別する。
 * @returns {object} 元会計の意味を変えない表示用辞書。
 */
function normalizeStat(source) {
  const kind = source.kind ?? '全場', direction = source.direction ?? '全方向';
  const group = source.group ?? [kind === '全場' ? '' : kind, direction === '全方向' ? '' : direction].filter(Boolean).join('_');
  return { ...source, symbol: source.symbol ?? 'NK225', scope: source.scope ?? 'all', group: group || 'all',
    avg_loss: source.avg_loss ?? source.mean_loss,
    flat: source.zero_entry ?? source.flat,
    avg_held_quantity_excluding_03_06: source.avg_held_quantity_excluding_03_06 ?? source.average_quantity };
}

/**
 * シートの基本書式と簡潔な前提を配置する。
 * @param {object} sheet - 作成先シート。
 * @param {string} lastColumn - 最後の列記号。
 * @param {number} end - 最終行。
 * @param {string} title - 題名。
 * @param {string[]} notes - 3行までの前提。
 * @returns {void} 返り値なし。
 */
function style(sheet, lastColumn, end, title, notes) {
  sheet.showGridLines = false;
  sheet.getRange(`A1:${lastColumn}${end}`).format.font = { name: 'Yu Gothic', size: 10, color: '#172B44' };
  sheet.getRange(`A1:${lastColumn}${end}`).format.verticalAlignment = 'center';
  sheet.getRange(`A1:${lastColumn}${end}`).format.rowHeight = 22;
  sheet.getRange(`A1:${lastColumn}${end}`).format.columnWidth = 17;
  sheet.getRange('A2').values = [[title]];
  sheet.getRange('A2').format.font = { size: 14, bold: true };
  sheet.getRange('A2:J2').format.borders = { bottom: { color: '#7B91A7', style: 'thin' } };
  notes.forEach((note, index) => sheet.getRange(`A${index + 3}`).values = [[note]]);
  sheet.getRange('A3:A5').format.font = { color: '#52667C', size: 10 };
  sheet.tabColor = '#254567';
}

/**
 * 既に値と式を配置した範囲を正式なExcelテーブルにする。
 * @param {object} sheet - 対象シート。
 * @param {string[]} headers - 列見出し。
 * @param {number} start - 見出し行。
 * @param {number} end - 最終行。
 * @param {string} name - 一意な表名。
 * @returns {void} 返り値なし。
 */
function table(sheet, headers, start, end, name) {
  const last = column(headers.length);
  sheet.getRange(`A${start}:${last}${start}`).values = [headers];
  sheet.tables.add(`A${start}:${last}${end}`, true, name).showFilterButton = true;
  sheet.getRange(`A${start}:${last}${start}`).format = { fill: '#254567', font: { bold: true, color: '#FFFFFF' },
    horizontalAlignment: 'center', verticalAlignment: 'center', wrapText: true, rowHeight: 38,
    borders: { insideVertical: { color: '#FFFFFF', style: 'thin' } } };
}

/**
 * 金額列の表記と赤字の条件付き書式を設定する。
 * @param {object} sheet - 対象シート。
 * @param {string} range - 金額範囲。
 * @returns {void} 返り値なし。
 */
function money(sheet, range) {
  sheet.getRange(range).setNumberFormat(moneyFormat);
  sheet.getRange(range).format.horizontalAlignment = 'right';
  sheet.getRange(range).conditionalFormats.add('cellIs', { operator: 'lessThan', formula: 0,
    format: { fill: '#FCEBEC', font: { color: '#A62932' } } });
}

// ----------------------------------------
// 最終JSONを受け取るまでこのビルダーは実行しない。入力会計は書き換えない。

if (!Array.isArray(data.selected) || !Array.isArray(data.rows)) throw new Error('最終報告JSONの形式が不正です');
if (!data.selection_note || typeof data.selection_note !== 'string') throw new Error('比較案と約定模型の注記が必要です');
const labels = new Map(evidence.sessions.map(row => [row.session, row]));
if (labels.size !== 50 || evidence.sessions.some(row => !row.direction_qualified)) throw new Error('50場の方向根拠が揃いません');
const selected = new Map(data.selected.map(row => [row.method, row]));
if (selected.size !== data.selected.length || data.selected.some(row => row.symbol !== 'NK225')) throw new Error('日経以外又は重複した選抜です');
const groups = new Map([...selected].map(([method]) => [method, []]));
const rowKeys = new Set();
for (const original of data.rows) {
  const row = { ...original, direction: labels.get(original.session)?.direction,
    holding_ratio_excluding_03_06: original.holding_ratio_excluding_03_06 ?? original.holding_ratio,
    avg_held_quantity_excluding_03_06: original.avg_held_quantity_excluding_03_06 ?? original.average_quantity };
  const key = `${row.method}/${row.session}`;
  if (rowKeys.has(key) || row.symbol !== 'NK225' || !groups.has(row.method) || !row.direction) throw new Error(`明細の識別が不正です: ${key}`);
  rowKeys.add(key);
  if (original.direction && original.direction !== row.direction) throw new Error(`${key}: 始終値分類が原資料と異なります`);
  equal(row.profit - row.loss, row.net, `${key} 利益−損失`);
  equal(row.gross - row.fees, row.net, `${key} 費用前−費用`);
  for (const field of ['profit', 'loss', 'fees', 'entries', 'quantity', 'max_per_side', 'held_minutes', 'held_minutes_excluding_03_06', 'avg_held_quantity_excluding_03_06']) {
    if (!Number.isFinite(row[field]) || row[field] < 0) throw new Error(`${key}/${field} が欠測又は不正です`);
  }
  equal(row.holding_ratio_excluding_03_06, row.held_minutes_excluding_03_06 / evaluationMinutes(row.session), `${key} 03時以降除外率`);
  if (original.evaluation_minutes != null) equal(original.evaluation_minutes, evaluationMinutes(row.session), `${key} 評価時間`);
  if (row.max_per_side > 10 || row.holding_ratio_excluding_03_06 > 1 || row.held_minutes_excluding_03_06 > row.held_minutes + 1e-8) throw new Error(`${key} 保有量又は時間が不正です`);
  if (row.avg_held_quantity_excluding_03_06 < row.holding_ratio_excluding_03_06 - 1e-8 || row.avg_held_quantity_excluding_03_06 > 2 * row.max_per_side + 1e-8) throw new Error(`${key} 平均枚数が不正です`);
  groups.get(row.method).push(row);
}
for (const [method, rows] of groups) {
  rows.sort((a, b) => a.session.localeCompare(b.session));
  if (rows.length !== 50) throw new Error(`${method}: 50場がありません`);
}
const book = Workbook.create();
const comparison = book.worksheets.add('比較');
const directionView = book.worksheets.add('昼夜・方向比較');
const detailSheets = new Map([...selected].map(([method]) => [method, book.worksheets.add(`日経_${method}`)]));
const evidenceSheet = book.worksheets.add('始終値根拠');
const checks = [];
const manifests = [];

// ----------------------------------------
// 50場ごとの会計。収支・日付順累計・深夜除外率をExcelで計算する。

for (const [method, rows] of groups) {
  const sheet = detailSheets.get(method), info = selected.get(method), end = rows.length + 6;
  if (!info.label || !info.day_method || !info.night_method) throw new Error(`${method}: 昼夜の手法説明がありません`);
  style(sheet, 'T', end, `日経mini ${method} セッション損益`, [
    '片方向上限10枚。円・手数料後。保有率はデイ420分／ナイト17～03時の600分。損益は全セッションを含みます。',
    `昼：${info.day_method}／夜：${info.night_method}。${info.label}`,
    '始終値方向は事後評価専用。平均枚数は同じ評価時間の合計保有枚数を平均し、両建ても合算します。']);
  const values = rows.map(row => [method, clock(`${row.session.slice(0, 10)}T${row.session.endsWith('_Day') ? '08:45' : '17:00'}:00+09:00`),
    row.session.endsWith('_Day') ? 'デイ' : 'ナイト', row.direction, row.profit, row.loss, null, null, row.fees, row.gross,
    row.entries, row.quantity, row.max_per_side, row.first_minutes ?? null, row.held_minutes, row.held_minutes_excluding_03_06,
    evaluationMinutes(row.session), null, row.avg_held_quantity_excluding_03_06,
    data.include_period_split ? (row.session <= knownEnd ? scopeNames.known : scopeNames.new) : scopeNames.all]);
  sheet.getRange(`A7:T${end}`).values = values;
  let cumulative = 0;
  rows.forEach((row, index) => {
    const n = index + 7;
    sheet.getRange(`G${n}:H${n}`).formulas = [[`=E${n}-F${n}`, `=SUMIFS($G$7:$G$${end},$B$7:$B$${end},"<="&B${n})`]];
    sheet.getRange(`R${n}`).formulas = [[`=P${n}/Q${n}`]];
    cumulative += row.net;
    checks.push({ sheet: sheet.name, cell: `G${n}`, expected: row.net }, { sheet: sheet.name, cell: `H${n}`, expected: cumulative },
      { sheet: sheet.name, cell: `R${n}`, expected: row.holding_ratio_excluding_03_06 });
  });
  table(sheet, ['手法ID', '開始日時', '昼夜', '始終値方向', '利益（円）', '損失（円）', '収支（円）', '累計（円）', '内数手数料（円）',
    '費用前収支（円）', '新規回数', '新規枚数', '最大片方向保有', '初回まで（分）', '全場保有（分）', '03時以降除外保有（分）',
    '評価時間（分）', '保有率', '平均保有枚数', '対象区分'], 6, end, `日経_${method}_全場会計`);
  money(sheet, `E7:J${end}`);
  sheet.getRange(`B7:B${end}`).setNumberFormat('yyyy/mm/dd hh:mm');
  sheet.getRange(`N7:Q${end}`).setNumberFormat('0.0');
  sheet.getRange(`R7:R${end}`).setNumberFormat('0.0%');
  sheet.getRange(`S7:S${end}`).setNumberFormat('0.00');
  sheet.getRange(`B1:B${end}`).format.columnWidth = 25;
  sheet.getRange(`C1:D${end}`).format.columnWidth = 13;
  sheet.getRange(`E1:J${end}`).format.columnWidth = 21;
  sheet.getRange(`O1:Q${end}`).format.columnWidth = 23;
  sheet.freezePanes.freezeRows(6);
  sheet.freezePanes.freezeColumns(2);
  manifests.push({ sheet: sheet.name, rows: rows.length, method });
}

/**
 * 選抜手法の明細に対する集計式の条件を作る。
 * @param {object} stat - 手法・範囲・昼夜方向を持つ集計行。
 * @returns {object} 範囲関数と条件の組。
 */
function criteria(stat) {
  const sheet = detailSheets.get(stat.method);
  const ref = c => `'${sheet.name}'!$${c}$7:$${c}$56`;
  const conditions = [ref('A'), `"${stat.method}"`];
  if (stat.scope !== 'all') {
    if (!data.include_period_split) throw new Error('47場・3場の比較にはinclude_period_split=trueを明示してください');
    conditions.push(ref('T'), `"${scopeNames[stat.scope]}"`);
  }
  for (const part of (stat.group ?? 'all').split('_')) {
    if (part === 'Day' || part === 'Night') conditions.push(ref('C'), `"${part === 'Day' ? 'デイ' : 'ナイト'}"`);
    else if (part !== 'all') conditions.push(ref('D'), `"${part}"`);
  }
  return { ref, conditions: conditions.join(',') };
}

/**
 * 簡潔な比較表を作り、選抜案は明細参照で再計算する。
 * @param {object} sheet - 作成先。
 * @param {object[]} stats - 保存集計。
 * @param {number} start - 見出し行。
 * @param {string} name - 正式テーブル名。
 * @param {boolean} linked - 選抜明細に連動させるか。
 * @returns {number} 最終行。
 */
function buildComparison(sheet, stats, start, name, linked) {
  const end = start + stats.length;
  const headers = ['手法ID', '区分', '対象', '場数', '総利益（円）', '総損失（円）', '収支（円）', '親PF', '黒字場', '赤字場', '無取引場',
    '平均赤字（円）', '中央赤字（円）', '最大赤字（円）', '上位3黒字除外（円）', '各場平均保有率', '時間加重保有率', '平均保有枚数', '新規回数', '手法名'];
  stats.forEach((stat, index) => {
    const n = start + index + 1, group = stat.group ?? 'all';
    if (stat.symbol !== 'NK225' || !(stat.scope in scopeNames) || !(group in groupNames)) throw new Error('比較の区分が不正です');
    const rows = linked ? filterRows(groups.get(stat.method), stat.scope, group) : null;
    const actual = linked ? statistics(rows) : stat;
    if (linked) {
      for (const key of ['sessions', 'profit', 'loss', 'net', 'wins', 'losses', 'flat', 'entries', 'avg_loss', 'ex_top3', 'mean_holding_ratio', 'time_weighted_holding_ratio']) equal(actual[key], stat[key], `${stat.method}/${stat.scope}/${group}/${key}`);
    }
    equal(stat.profit - stat.loss, stat.net, `${stat.method}/${group} 会計`);
    const maxLoss = linked ? actual.max_loss : Math.max(0, -stat.worst);
    sheet.getRange(`A${n}:T${n}`).values = [[stat.method, groupNames[group], scopeNames[stat.scope], actual.sessions,
      actual.profit, actual.loss, null, null, actual.wins, actual.losses, actual.flat, actual.avg_loss, actual.median_loss ?? null,
      maxLoss, actual.ex_top3, actual.mean_holding_ratio, actual.time_weighted_holding_ratio,
      actual.avg_held_quantity_excluding_03_06 ?? null, actual.entries, stat.name ?? selected.get(stat.method)?.label ?? stat.method]];
    sheet.getRange(`G${n}:H${n}`).formulas = [[`=E${n}-F${n}`, `=IF(F${n}=0,IF(E${n}=0,"算定不能","損失なし"),E${n}/F${n})`]];
    if (linked) {
      const { ref, conditions } = criteria({ ...stat, group });
      sheet.getRange(`D${n}:F${n}`).formulas = [[`=COUNTIFS(${conditions})`, `=SUMIFS(${ref('E')},${conditions})`, `=SUMIFS(${ref('F')},${conditions})`]];
      sheet.getRange(`I${n}:L${n}`).formulas = [[`=COUNTIFS(${conditions},${ref('G')},">0")`, `=COUNTIFS(${conditions},${ref('G')},"<0")`,
        `=COUNTIFS(${conditions},${ref('K')},"=0")`, `=IF(J${n}=0,0,-SUMIFS(${ref('G')},${conditions},${ref('G')},"<0")/J${n})`]];
      sheet.getRange(`P${n}:S${n}`).formulas = [[`=AVERAGEIFS(${ref('R')},${conditions})`, `=SUMIFS(${ref('P')},${conditions})/SUMIFS(${ref('Q')},${conditions})`,
        `=AVERAGEIFS(${ref('S')},${conditions})`, `=SUMIFS(${ref('K')},${conditions})`]];
    }
    for (const [cell, expected] of [['D', actual.sessions], ['E', actual.profit], ['F', actual.loss], ['G', actual.net], ['I', actual.wins], ['J', actual.losses],
      ['K', actual.flat], ['L', actual.avg_loss], ['N', maxLoss], ['O', actual.ex_top3], ['P', actual.mean_holding_ratio], ['Q', actual.time_weighted_holding_ratio], ['S', actual.entries]]) {
      checks.push({ sheet: sheet.name, cell: `${cell}${n}`, expected });
    }
    if (actual.loss > 0) checks.push({ sheet: sheet.name, cell: `H${n}`, expected: actual.profit / actual.loss });
  });
  table(sheet, headers, start, end, name);
  money(sheet, `E${start + 1}:G${end}`);
  money(sheet, `L${start + 1}:O${end}`);
  sheet.getRange(`H${start + 1}:H${end}`).setNumberFormat('0.00');
  sheet.getRange(`P${start + 1}:Q${end}`).setNumberFormat('0.0%');
  sheet.getRange(`R${start + 1}:R${end}`).setNumberFormat('0.00');
  sheet.getRange(`B1:C${end}`).format.columnWidth = 19;
  sheet.getRange(`E1:G${end}`).format.columnWidth = 22;
  sheet.getRange(`L1:O${end}`).format.columnWidth = 24;
  sheet.getRange(`P1:R${end}`).format.columnWidth = 23;
  sheet.getRange(`T1:T${end}`).format.columnWidth = 65;
  return end;
}

// ----------------------------------------
// 全体・昼夜・始終値方向と、選定外も含む全試行を分けて表示する。

const computed = [];
for (const [method, rows] of groups) {
  for (const group of ['all', 'Day', 'Night', '上昇', '下落', '同値', 'Day_上昇', 'Day_下落', 'Night_上昇', 'Night_下落', 'Day_同値', 'Night_同値']) {
    const subset = filterRows(rows, 'all', group);
    if (subset.length) computed.push({ method, symbol: 'NK225', scope: 'all', group, name: selected.get(method).label, ...statistics(subset) });
  }
}
const comparisonStats = (data.summary ?? computed.filter(stat => stat.group === 'all')).map(normalizeStat).filter(stat => selected.has(stat.method));
const parts = (data.parts ?? computed.filter(stat => stat.group !== 'all')).map(normalizeStat).filter(stat => selected.has(stat.method) && stat.group !== 'all');
const fullMap = new Map();
for (const original of [...(data.comparison_summary ?? []), ...(data.comparisons ?? [])]) {
  const stat = normalizeStat(original), key = `${stat.method}/${stat.scope}/${stat.group}`;
  if (fullMap.has(key)) {
    for (const field of ['sessions', 'profit', 'loss', 'net', 'entries']) equal(fullMap.get(key)[field], stat[field], `${key} 重複集計`);
  } else fullMap.set(key, stat);
}
const allStats = [...fullMap.values()];
const fullStart = comparisonStats.length + 11;
style(comparison, 'T', fullStart + allStats.length, '日経専用の利益率・活動・損失の比較', [
  '日経mini・片方向上限10枚・円・手数料後。親PF＝全完結親の総利益÷総損失。全50場は既知の研究期間です。',
  data.selection_note,
  `出典：${data.source_note ?? '00143保存会計・原板Lastの始終値照合'}。保有率は03～06時除外、損益は深夜分も含みます。`]);
const comparisonEnd = buildComparison(comparison, comparisonStats, 6, '日経主要候補比較', true);
comparison.getRange(`A${fullStart - 2}`).values = [['全試行の保存集計（選定外も含む）']];
comparison.getRange(`A${fullStart - 2}`).format.font = { bold: true, size: 12 };
if (allStats.length) buildComparison(comparison, allStats, fullStart, '日経全試行比較', false);
comparison.freezePanes.freezeRows(6);
comparison.freezePanes.freezeColumns(3);
style(directionView, 'T', parts.length + 6, '昼夜・上昇下落別の比較', [
  '上昇／下落は各場の最初のLastと、公式終了直前6分以内の最終Lastで分類。売買判断へ渡さない事後区分です。',
  '保有率の分母はデイ420分／ナイト600分。各場率の単純平均と時間加重を分けます。',
  '昼夜専用の運用IDは各手法の明細冒頭へ記載。全50場は設計と改善に使用した既知データです。']);
const partsEnd = buildComparison(directionView, parts, 6, '日経昼夜方向比較', true);
directionView.freezePanes.freezeRows(6);
directionView.freezePanes.freezeColumns(3);

// ----------------------------------------
// 方向を決めた50場の始終値をそのまま明示し、公式終値と代理観測を区別する。

const originals = [...evidence.sessions].sort((a, b) => a.session.localeCompare(b.session));
style(evidenceSheet, 'O', originals.length + 6, '始終値方向の根拠', [
  '当場最初の有効Lastを始値、公式終了前6分以内の最終有効Lastを終値代理とします。',
  `公式終了時刻の観測${evidence.公式引け確認数}場／直前6分の代理${evidence.直前6分代理数}場。清算時点の中値変化とは区別します。`,
  '原seqは0始まり。時計は原データの価格時計で、受信時計ではありません。価格差はExcel式で計算します。']);
evidenceSheet.getRange('A7:O56').values = originals.map(row => [row.session, row.first_price, clock(row.first_price_time), row.final_price,
  clock(row.final_price_time), null, row.direction, row.start_lag_seconds, row.seconds_before_official_end,
  row.first_evidence.seq0, row.final_evidence.seq0, row.basis, row.book_sha256, row.first_evidence.line_sha256, row.final_evidence.line_sha256]);
originals.forEach((row, index) => {
  const n = index + 7;
  evidenceSheet.getRange(`F${n}`).formulas = [[`=D${n}-B${n}`]];
  checks.push({ sheet: evidenceSheet.name, cell: `F${n}`, expected: row.change });
});
table(evidenceSheet, ['セッション', '最初のLast', '最初の価格時計', '最後のLast', '最後の価格時計', '価格差', '始終値方向', '開始後の秒数',
  '終了前の秒数', '最初の原seq', '最後の原seq', '終値の根拠', '原板SHA256', '最初の行SHA256', '最後の行SHA256'], 6, 56, '始終値方向根拠50場');
evidenceSheet.getRange('A1:A56').format.columnWidth = 28;
for (const c of ['C', 'E']) { evidenceSheet.getRange(`${c}1:${c}56`).format.columnWidth = 29; evidenceSheet.getRange(`${c}7:${c}56`).setNumberFormat('yyyy/mm/dd hh:mm:ss'); }
evidenceSheet.getRange('B7:B56').setNumberFormat('#,##0.0');
for (const c of ['D', 'F']) evidenceSheet.getRange(`${c}7:${c}56`).setNumberFormat('#,##0.0;[Red](#,##0.0);"-"');
evidenceSheet.getRange('L1:L56').format.columnWidth = 37;
evidenceSheet.getRange('M1:O56').format.columnWidth = 72;
evidenceSheet.freezePanes.freezeRows(6);

// ----------------------------------------
// 再計算・値照合・全シート描画の後に公開先と出力先へ同じファイルを保存する。

book.recalculate();
const firstMethod = [...selected.keys()][0], firstSheet = detailSheets.get(firstMethod);
const summaryProbe = comparisonStats.findIndex(stat => stat.method === firstMethod && stat.scope === 'all') + 7;
if (summaryProbe < 7) throw new Error('代表方法の全場集計がありません');
const originalProfit = firstSheet.getRange('E7').values[0][0];
const originalHeld = firstSheet.getRange('P7').values[0][0];
const originalNet = firstSheet.getRange('G7').values[0][0];
const originalSummary = comparison.getRange(`G${summaryProbe}`).values[0][0];
const originalRatio = comparison.getRange(`P${summaryProbe}`).values[0][0];
try {
  firstSheet.getRange('E7').values = [[originalProfit + 1000]];
  firstSheet.getRange('P7').values = [[originalHeld + 1]];
  book.recalculate();
  equal(firstSheet.getRange('G7').values[0][0], originalNet + 1000, '利益入力変更後の収支');
  equal(comparison.getRange(`G${summaryProbe}`).values[0][0], originalSummary + 1000, '利益入力変更後の集計');
  equal(comparison.getRange(`P${summaryProbe}`).values[0][0], originalRatio + 1 / 420 / 50, '分数入力変更後の平均保有率');
} finally {
  firstSheet.getRange('E7').values = [[originalProfit]];
  firstSheet.getRange('P7').values = [[originalHeld]];
  book.recalculate();
}
for (const check of checks) equal(book.worksheets.getItem(check.sheet).getRange(check.cell).values[0][0], check.expected, `${check.sheet}!${check.cell}`);
const errors = await book.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',
  options: { useRegex: true, maxResults: 100 }, maxChars: 9000 });
await fs.writeFile(path.join(work, 'xlsx数式エラー確認143.jsonl'), errors.ndjson, 'utf8');
const renders = [[comparison.name, `A1:J${Math.min(comparisonEnd, 20)}`], [comparison.name, `K6:T${Math.min(comparisonEnd, 20)}`],
  [directionView.name, `A1:J${Math.min(partsEnd, 18)}`], [directionView.name, `K6:T${Math.min(partsEnd, 18)}`],
  [evidenceSheet.name, 'A1:I16'], [evidenceSheet.name, 'J6:O12']];
if (allStats.length) renders.push([comparison.name, `A${fullStart - 2}:J${fullStart + Math.min(allStats.length, 12)}`]);
for (const sheet of detailSheets.values()) renders.push([sheet.name, 'A1:J16'], [sheet.name, 'K6:T16']);
const previews = [];
for (const [sheetName, range] of renders) {
  const preview = await book.render({ sheetName, range, scale: 1.5, format: 'png' });
  const target = path.join(work, `xlsx143_${String(previews.length + 1).padStart(2, '0')}_${sheetName}.png`);
  await fs.writeFile(target, new Uint8Array(await preview.arrayBuffer()));
  previews.push({ sheetName, range, path: target });
}
await fs.mkdir(outputDirectory, { recursive: true });
await fs.mkdir(publicDirectory, { recursive: true });
const output = path.join(outputDirectory, filename), published = path.join(publicDirectory, filename);
await (await SpreadsheetFile.exportXlsx(book)).save(output);
await fs.copyFile(output, published);
const bytes = await fs.readFile(output);
if (!bytes.equals(await fs.readFile(published))) throw new Error('公開先と出力先が一致しません');
await fs.writeFile(path.join(work, 'xlsx照合143.json'), JSON.stringify({ 入力: source, 入力SHA256: createHash('sha256').update(sourceBytes).digest('hex'),
  始終値SHA256: createHash('sha256').update(evidenceBytes).digest('hex'), 明細: manifests, 会計数: data.rows.length,
  比較数: comparisonStats.length, 昼夜方向数: parts.length, 全条件集計数: allStats.length, 照合数: checks.length,
  検算セル: checks, 描画: previews, 出力: output, 公開先: published, SHA256: createHash('sha256').update(bytes).digest('hex') }, null, 2), 'utf8');
console.log(`保存完了: ${published}`);
