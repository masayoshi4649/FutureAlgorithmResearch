import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const work = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(work, '../..');
const folder = path.join(root, 'アルゴリズム調査/00139_複数追撃と早期参加の全体検証');
const output = path.join(folder, '段階投入と早期参加の全セッション損益.xlsx');
const sources = ['results', 'extra_results', 'early_results', 'recycle_results', 'protect_results', 'guard_results'];
const summary = JSON.parse(await fs.readFile(path.join(folder, '比較集計.json'), 'utf8'));
const html = await fs.readFile(path.join(folder, '段階投入と早期参加の全セッション損益.html'), 'utf8');
const published = JSON.parse(html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const selected = ['B5', 'B2', 'P07', 'C04', 'CHA', 'C10'];
const methods = [...selected, ...Object.keys(published.names).filter(x => !selected.includes(x))];
const records = [];
const keys = new Set();
for (const source of sources) {
  const data = JSON.parse(await fs.readFile(path.join(root, `work/tranche139_20261022/${source}/結果.json`), 'utf8'));
  for (const row of data.rows) {
    const key = `${row.method}/${row.symbol}/${row.session}`;
    if (keys.has(key)) throw new Error(`重複会計: ${key}`);
    keys.add(key);
    if (Math.abs(row.profit - row.loss - row.net) > 0.001) throw new Error(`会計不一致: ${key}`);
    records.push(row);
  }
}
if (records.length !== 13724 || methods.length !== 146) throw new Error('保存済み件数が想定と異なります');

// ----------------------------------------
// 書式と検証に用いる関数。

/**
 * シートの基本書式を設定する。
 * @param {object} sheet - 対象シート。
 * @param {string} range - 使用するセル範囲。
 * @returns {void} 返り値なし。
 */
function styleSheet(sheet, range) {
  sheet.showGridLines = false;
  sheet.getRange(range).format.font = { name: 'Yu Gothic', size: 10, color: '#192B42' };
  sheet.getRange(range).format.rowHeight = 21;
  sheet.getRange(range).format.verticalAlignment = 'center';
  sheet.getRange(range).format.columnWidth = 15;
  sheet.tabColor = '#234567';
}

/**
 * 表の見出しに色と配置を設定する。
 * @param {object} sheet - 対象シート。
 * @param {string} range - 見出し範囲。
 * @returns {void} 返り値なし。
 */
function styleHeader(sheet, range) {
  sheet.getRange(range).format = {
    fill: '#234567', font: { bold: true, color: '#FFFFFF' },
    horizontalAlignment: 'center', verticalAlignment: 'center',
    wrapText: true, rowHeight: 32,
    borders: { insideVertical: { style: 'thin', color: '#FFFFFF' } },
  };
}

/**
 * 負の損益を赤色で示す。
 * @param {object} sheet - 対象シート。
 * @param {string} range - 金額範囲。
 * @returns {void} 返り値なし。
 */
function money(sheet, range) {
  sheet.getRange(range).setNumberFormat('#,##0;[Red](#,##0);"-"');
  sheet.getRange(range).conditionalFormats.add('cellIs', {
    operator: 'lessThan', formula: 0,
    format: { fill: '#FCE8E8', font: { color: '#A42828' } },
  });
}

/**
 * 数値を許容誤差付きで照合する。
 * @param {number} actual - 実際の計算値。
 * @param {number} expected - 保存済みの期待値。
 * @param {string} label - 照合対象の名前。
 * @returns {void} 返り値なし。不一致なら例外。
 */
function equal(actual, expected, label) {
  if (typeof actual !== 'number' || Math.abs(actual - expected) > 0.001) {
    throw new Error(`${label}: ${actual} / ${expected}`);
  }
}

// ----------------------------------------
// 二銘柄の全会計を別シートへ配置する。

const book = Workbook.create();
const main = book.worksheets.add('比較');
const detailSheets = {
  NK225: book.worksheets.add('日経セッション'),
  TOPIX: book.worksheets.add('TOPIXセッション'),
};
const products = { NK225: '日経mini', TOPIX: 'TOPIXmini' };
const spans = {};
const allChecks = [];
for (const [symbol, sheet] of Object.entries(detailSheets)) {
  const values = [], calc = [];
  spans[symbol] = {};
  for (const method of methods) {
    const rows = records.filter(x => x.symbol === symbol && x.method === method).sort((a, b) => a.session.localeCompare(b.session));
    if (rows.length !== 47) throw new Error(`全47場不足: ${symbol}/${method}`);
    const start = values.length + 7;
    let cumulative = 0;
    for (const row of rows) {
      cumulative += row.net;
      const nr = values.length + 7;
      // 累計はセッション時点の保存値。並べ替えても日時との対応が変わらない。
      values.push([method, new Date(`${row.session.slice(0, 10)}T00:00:00Z`), row.kind === 'Day' ? 'デイ' : 'ナイト', row.profit, row.loss, null, cumulative, row.fees, row.entries, row.quantity, row.max_per_side, row.session <= '2026-10-21_Day' ? '既知45場' : '追加2場']);
      calc.push([`=D${nr}-E${nr}`]);
      allChecks.push({ sheet: sheet.name, row: nr, net: row.net, cumulative });
    }
    spans[symbol][method] = { start, end: values.length + 6 };
    equal(cumulative, summary.summary[symbol][method]['全47場'].net, `${symbol}/${method}累計`);
  }
  const end = values.length + 6;
  styleSheet(sheet, `A1:L${end}`);
  sheet.getRange('A2').values = [[`${products[symbol]} 全47セッションの損益（円・手数料後）`]];
  sheet.getRange('A2').format.font = { size: 14, bold: true };
  sheet.getRange('A3').values = [['上限は片方向10枚。実保有枚数は手法ごとに異なります。手法IDで絞り込めます。']];
  sheet.getRange('A4').values = [['出典：00139の保存済み6結果。利益・損失は初回と追加をまとめた一組の費用後損益を正負に分類。']];
  sheet.getRange('A5').values = [['累計は各手法の当該セッションまで。追加2場も完全未知データではありません。']];
  sheet.getRange('A6:L6').values = [['手法ID', '開始日', 'セッション', '利益（円）', '損失（円）', '収支（円）', '時点累計（円）', '内数手数料（円）', '新規回数', '新規枚数', '最大片方向保有', '評価区分']];
  sheet.getRange(`A7:L${end}`).values = values;
  sheet.getRange(`F7:F${end}`).formulas = calc;
  sheet.getRange(`B7:B${end}`).setNumberFormat('yyyy/mm/dd');
  sheet.getRange(`D7:K${end}`).format.horizontalAlignment = 'right';
  sheet.getRange(`I7:K${end}`).setNumberFormat('#,##0');
  sheet.getRange(`A6:L${end}`).format.rowHeight = 21;
  sheet.tables.add(`A6:L${end}`, true, symbol === 'NK225' ? '日経損益' : 'TOPIX損益');
  styleHeader(sheet, 'A6:L6');
  money(sheet, `D7:H${end}`);
  sheet.freezePanes.freezeRows(6);
  sheet.freezePanes.freezeColumns(3);
  sheet.getRange(`A1:A${end}`).format.columnWidth = 17;
  sheet.getRange(`B1:B${end}`).format.columnWidth = 16;
  sheet.getRange(`C1:C${end}`).format.columnWidth = 12;
  sheet.getRange(`D1:H${end}`).format.columnWidth = 19;
  sheet.getRange(`I1:L${end}`).format.columnWidth = 17;
  console.log(`${symbol}: ${values.length}行を配置`);
}

// ----------------------------------------
// 全146条件の集計と主要比較を同一シートへまとめる。

const fullStart = 25;
const fullEnd = fullStart + methods.length * 2 - 1;
styleSheet(main, `A1:O${fullEnd}`);
main.getRange('A2').values = [['現行維持と段階投入の比較']];
main.getRange('A2').format.font = { size: 14, bold: true };
main.getRange('A3').values = [['現時点では現行B5を基本に維持。減枚・追撃は利益と損失の交換で、全面的な改善は未確認。']];
main.getRange('A4').values = [['2026/09/21デイ～10/22デイの47場。金額は円・手数料後。両商品とも片方向上限10枚。']];
main.getRange('A5').values = [['B5は現在の昼夜別手法（日中T06・夜間TOPIX T04／日経U06）。初期E01へ戻す意味ではありません。']];
main.getRange('A7:H7').values = [['商品', '手法ID', '累計収支（円）', '赤字場数／47', '平均赤字（円）', '最大赤字（円）', '上位3黒字除外（円）', '読み方']];
const descriptions = {
  B5: '現行5枚。基本の比較元', B2: '主担当だけ2枚。補完は従来どおり',
  P07: '2枚から1枚ずつ追撃。利益も減少', C04: '時間帯・支持に応じて初回と追撃を変更',
  CHA: 'C04の追撃玉を早めに利益保護', C10: 'C04の追撃に30秒の支持継続を要求',
};
main.getRange('A21').values = [['平均赤字・最大赤字は、収支が赤字のセッションだけで計算した正の損失額。']];
main.getRange('A22').values = [['早期参加28条件はいずれも両銘柄で累計赤字。待機短縮は採用を見送り。詳細と限界は結論.md。']];
main.getRange('A24:O24').values = [['商品', '手法ID', '手法名', '総利益（円）', '総損失（円）', '累計収支（円）', '赤字場数', '平均赤字（円）', '最大赤字（円）', '上位3黒字除外（円）', '内数手数料（円）', '買い収支（円）', '売り収支（円）', '最大片方向保有', '無取引場数']];
const rowRefs = {}, numericChecks = [];
let index = fullStart;
for (const symbol of ['NK225', 'TOPIX']) {
  rowRefs[symbol] = {};
  for (const method of methods) {
    const stat = summary.summary[symbol][method]['全47場'];
    const span = spans[symbol][method];
    const sheet = detailSheets[symbol];
    const ref = col => `'${sheet.name}'!${col}${span.start}:${col}${span.end}`;
    const net = ref('F');
    rowRefs[symbol][method] = index;
    main.getRange(`A${index}:O${index}`).values = [[products[symbol], method, published.names[method].name, null, null, null, null, null, null, null, null, stat.buy, stat.sell, stat.max_per_side, stat.no_trade]];
    main.getRange(`D${index}:K${index}`).formulas = [[
      `=SUM(${ref('D')})`, `=SUM(${ref('E')})`, `=D${index}-E${index}`,
      `=COUNTIFS(${net},"<0")`, `=IF(G${index}=0,0,-SUMIFS(${net},${net},"<0")/G${index})`,
      `=MAX(0,-MIN(${net}))`,
      `=F${index}-MAX(0,LARGE(${net},1))-MAX(0,LARGE(${net},2))-MAX(0,LARGE(${net},3))`,
      `=SUM(${ref('H')})`,
    ]];
    numericChecks.push({ row: index, expected: [stat.profit, stat.loss, stat.net, stat.reds, stat.mean_loss, stat.max_loss, stat.top3_removed, stat.fees] });
    index++;
  }
}
let nr = 8;
for (const symbol of ['NK225', 'TOPIX']) {
  for (const method of selected) {
    const r = rowRefs[symbol][method];
    main.getRange(`A${nr}:H${nr}`).values = [[products[symbol], method, null, null, null, null, null, descriptions[method]]];
    main.getRange(`C${nr}:G${nr}`).formulas = [[`=F${r}`, `=G${r}`, `=H${r}`, `=I${r}`, `=J${r}`]];
    nr++;
  }
}
main.tables.add(`A24:O${fullEnd}`, true, '全条件比較');
styleHeader(main, 'A7:H7');
styleHeader(main, 'A24:O24');
main.getRange('A8:H13').format.fill = '#F0F4F8';
main.getRange('A14:H19').format.fill = '#F8F9FB';
money(main, 'C8:C19');
money(main, 'E8:G19');
money(main, `D25:F${fullEnd}`);
money(main, `H25:M${fullEnd}`);
main.getRange(`G25:G${fullEnd}`).setNumberFormat('0');
main.getRange(`N25:O${fullEnd}`).setNumberFormat('0');
main.getRange(`A1:A${fullEnd}`).format.columnWidth = 17;
main.getRange(`B1:B${fullEnd}`).format.columnWidth = 16;
main.getRange(`C1:C${fullEnd}`).format.columnWidth = 39;
main.getRange(`D1:G${fullEnd}`).format.columnWidth = 22;
main.getRange(`H1:H${fullEnd}`).format.columnWidth = 47;
main.getRange(`I1:O${fullEnd}`).format.columnWidth = 22;
main.freezePanes.freezeRows(5);
main.freezePanes.freezeColumns(2);

// ----------------------------------------
// 計算照合・画像確認用の出力と保存。

book.recalculate();
for (const check of numericChecks) {
  const actual = main.getRange(`D${check.row}:K${check.row}`).values[0];
  check.expected.forEach((v, i) => equal(actual[i], v, `集計${check.row}/${i}`));
}
for (const [symbol, sheet] of Object.entries(detailSheets)) {
  const actual = sheet.getRange('F7:G6868').values;
  const checks = allChecks.filter(x => x.sheet === sheet.name);
  checks.forEach((v, i) => {
    equal(actual[i][0], v.net, `${symbol}/${i}/収支`);
    equal(actual[i][1], v.cumulative, `${symbol}/${i}/累計`);
  });
}
const errors = await book.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!', options: { useRegex: true, maxResults: 10 }, maxChars: 2000 });
await fs.writeFile(path.join(work, '数式エラー確認.jsonl'), errors.ndjson, 'utf8');
const inspected = await book.inspect({ kind: 'table', range: '比較!A7:H19', include: 'values,formulas', tableMaxRows: 13, tableMaxCols: 8, maxChars: 6000 });
await fs.writeFile(path.join(work, '主要比較確認.jsonl'), inspected.ndjson, 'utf8');
for (const [sheetName, range, filename] of [['比較','A1:H19','比較.png'], ['日経セッション','A1:L14','日経.png'], ['TOPIXセッション','A1:L14','TOPIX.png']]) {
  const preview = await book.render({ sheetName, range, scale: 1.5, format: 'png' });
  await fs.writeFile(path.join(work, filename), new Uint8Array(await preview.arrayBuffer()));
}
await (await SpreadsheetFile.exportXlsx(book)).save(output);
await fs.writeFile(path.join(work, '照合結果.json'), JSON.stringify({ 会計数: records.length, 手法数: methods.length, セッション数: 47, 集計照合数: numericChecks.length, 全収支と時点累計の照合: true, 出力: output }, null, 2), 'utf8');
console.log(`保存完了: ${output}`);
