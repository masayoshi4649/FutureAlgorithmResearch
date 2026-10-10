/**
 * 固定候補の損益画面を原集計と照合し、ブラウザを使用せず表示用コードを検査します。
 * 引数: なし。
 * 返り値: なし。監査結果を同じ作業フォルダへ保存します。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');
const crypto = require('crypto');
const root = path.resolve(__dirname, '../..');
const target = path.join(root, 'M3_逆_A00_360分版');
const html = fs.readFileSync(path.join(target, '損益.html'), 'utf8');
const payload = JSON.parse(fs.readFileSync(path.join(target, 'セッション損益.json'), 'utf8'));
const originals = JSON.parse(fs.readFileSync(path.join(root, 'work/wave_v19/セッション比較.json'), 'utf8')).filter(r => r.method_id === 'V0800');
originals.push(...JSON.parse(fs.readFileSync(path.join(root, 'work/wave_v20/結果.json'), 'utf8')).filter(r => r.method_id === 'V0800' && r.quantity === 1));
const symbols = ['TOPIX', 'NK225'];
const caps = {TOPIX: 10, NK225: 20};
const numeric = ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units', 'unit_balance', 'cycles'];
const inline = JSON.parse(html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const source = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(x => x[1]).join('\n');
const report = {合格: false, 元集計照合セル数: 0, 初期表示表数: 0, 全選択組合せ数: 0, 補正入力数: 0, 週集計照合数: 0, リンク: [], レビュー: []};

/**
 * 主キーをセッション名と銘柄から作成します。
 * @param {Object} row - 台帳の１行。
 * @returns {string} 一意のキー。
 */
function key(row) { return row.session + '/' + row.symbol; }

/**
 * タグと区切り記号を取り除き、表示値を数値へ戻します。
 * @param {string} value - 表示された円額や枚数。
 * @returns {number} 表示数値。
 */
function number(value) {
  return Number(value.replace(/<[^>]*>/g, '').replace(/,/g, '').replace(/＋/g, '+').replace(/−/g, '-').replace(/[^0-9+.-]/g, ''));
}

/**
 * 表の行をセルごとの文字列へ分割します。
 * @param {string} value - 行を含むHTML。
 * @returns {Object[]} 見出しと値セル。
 */
function parseRows(value) {
  return [...value.matchAll(/<tr>([\s\S]*?)<\/tr>/g)].filter(x => !x[1].includes('class="empty"')).map(x => ({
    label: (x[1].match(/<th[^>]*>([\s\S]*?)<\/th>/) || [])[1],
    cells: [...x[1].matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map(y => y[1])
  }));
}

/**
 * １枚の原集計を使って期待する金額・決済枚数を独立集計します。
 * @param {Object[]} rows - 集計対象の原記録。
 * @param {number} quantity - 固定保有枚数。
 * @returns {Object} 各項目の合計。
 */
function expected(rows, quantity) {
  const value = {};
  for (const field of numeric) value[field] = rows.reduce((n, r) => n + r[field], 0) * (field === 'cycles' ? 1 : quantity);
  return value;
}

/**
 * 表の１行の全数値を期待値と照合します。
 * @param {Object} row - 表示されたセル群。
 * @param {Object} totals - 期待する集計。
 * @returns {void} 返り値なし。
 */
function checkCells(row, totals) {
  assert.equal(row.cells.length, 6);
  assert.equal(number(row.cells[0]), totals.gross_profit_yen);
  assert.equal(number(row.cells[1]), totals.gross_loss_yen);
  assert.equal(number(row.cells[2]), totals.net_yen);
  assert.deepEqual(row.cells[3].replace(/枚/g, '').split('/').map(Number), [totals.profit_units, totals.loss_units, totals.zero_units]);
  assert.equal(number(row.cells[4]), totals.unit_balance);
  assert.equal(number(row.cells[5]), totals.cycles);
}

/**
 * 固定の収録期間の週区分を独立した期待値として返します。
 * @param {Object} row - 原記録。
 * @returns {string} 週の月曜日。
 */
function expectedWeek(row) { return row.session.startsWith('2026-09-28') ? '2026-09-28' : '2026-09-21'; }

/**
 * セッション表、合計、週表の全セルを照合します。
 * @param {Object} fragments - 検査対象のHTML断片。
 * @param {Object[]} rows - 選択される原記録。
 * @param {number} quantity - 固定保有枚数。
 * @returns {void} 返り値なし。
 */
function checkTables(fragments, rows, quantity) {
  const ordered = rows.slice().sort((a,b) => b.session.localeCompare(a.session));
  const sessions = parseRows(fragments.sessions);
  assert.equal(sessions.length, ordered.length);
  for (let i = 0; i < ordered.length; i++) {
    const r = ordered[i];
    assert.ok(sessions[i].label.includes(r.session.slice(0,10)));
    assert.ok(sessions[i].label.includes(r.session.endsWith('Day') ? 'デイ' : 'ナイト'));
    assert.ok(sessions[i].label.includes(r.phase === '条件固定後' ? '固定後' : '調整使用'));
    checkCells(sessions[i], expected([r], quantity));
  }
  checkCells(parseRows(fragments.total)[0], expected(rows, quantity));
  const groups = new Map();
  for (const r of rows) {
    const w = expectedWeek(r);
    if (!groups.has(w)) groups.set(w, []);
    groups.get(w).push(r);
  }
  const weeks = parseRows(fragments.weeks);
  const dates = [...groups.keys()].sort().reverse();
  assert.equal(weeks.length, dates.length);
  for (let i = 0; i < dates.length; i++) {
    assert.ok(weeks[i].label.startsWith(dates[i]));
    assert.ok(weeks[i].label.includes(`${groups.get(dates[i]).length}セッション収録`));
    checkCells(weeks[i], expected(groups.get(dates[i]), quantity));
    report.週集計照合数++;
  }
}

// ----------------------------------------
// 集計データと埋め込みデータの一致、および元台帳との対応を確認します。
assert.equal(payload.strategy_id, 'V0800');
assert.equal(payload.quantity_basis, 1);
assert.equal(payload.records.length, 22);
assert.equal(new Set(payload.records.map(key)).size, 22);
assert.equal(inline.length, 22);
const lookup = new Map(payload.records.map(r => [key(r), r]));
for (const r of originals) {
  const current = lookup.get(key(r));
  assert.ok(current);
  for (const [field, value] of Object.entries(r)) {
    if (typeof value === 'number') assert.equal(current[field] + 0, value + 0);
    else assert.deepEqual(current[field], value);
  }
  assert.equal(current.quantity, 1);
  assert.equal(current.phase, r.session === '2026-09-28_Day' ? '条件固定後' : '調整に使用');
  report.元集計照合セル数++;
}
for (const r of inline) assert.deepEqual(r, lookup.get(key(r)));

// ----------------------------------------
// JavaScript無効時にも表示される初期HTMLを全表で確認します。
for (const symbol of symbols) {
  const fragments = {};
  for (const name of ['sessions', 'total', 'weeks']) {
    const tag = name === 'total' ? 'tfoot' : 'tbody';
    fragments[name] = html.match(new RegExp(`<${tag} id="${name}-${symbol}">([\\s\\S]*?)<\\/${tag}>`))[1];
    report.初期表示表数++;
  }
  checkTables(fragments, payload.records.filter(r => r.symbol === symbol), 1);
  const options = html.match(new RegExp(`<select id="qty-${symbol}"[^>]*>([\\s\\S]*?)<\\/select>`))[1];
  assert.deepEqual([...options.matchAll(/value="(\d+)"/g)].map(x => Number(x[1])), Array.from({length: caps[symbol]}, (_, i) => i + 1));
}

// ----------------------------------------
// 画面要素の最小模擬を作り、実際の表示コードとイベント処理を実行します。
const nodes = new Map();
const ids = ['data', 'phase', 'part', ...symbols.flatMap(s => ['qty-', 'summary-', 'sessions-', 'total-', 'weeks-'].map(p => p + s))];
for (const id of ids) nodes.set(id, {innerHTML: '', value: id.startsWith('qty-') ? '1' : 'all', textContent: id === 'data' ? JSON.stringify(inline) : '', listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; }});
const context = vm.createContext({document: {getElementById(id) { assert.ok(nodes.has(id), id); return nodes.get(id); }}});
vm.runInContext(source, context, {timeout: 1000});

/**
 * 動的描画後の全表と上部カードを独立値に照合します。
 * @param {string} symbol - 銘柄。
 * @param {number} quantity - 期待する保有枚数。
 * @param {string} phase - 検証区分。
 * @param {string} part - 時間帯。
 * @returns {void} 返り値なし。
 */
function checkDynamic(symbol, quantity, phase, part) {
  const rows = payload.records.filter(r => r.symbol === symbol && (phase === 'all' || r.phase === phase) && (part === 'all' || r.session.endsWith('_' + part)));
  checkTables(Object.fromEntries(['sessions', 'total', 'weeks'].map(n => [n, nodes.get(n + '-' + symbol).innerHTML])), rows, quantity);
  const summary = [...nodes.get('summary-' + symbol).innerHTML.matchAll(/<strong[^>]*>([\s\S]*?)<\/strong>/g)].map(x => number(x[1]));
  const totals = expected(rows, quantity);
  assert.deepEqual(summary, [totals.net_yen, totals.gross_profit_yen, totals.gross_loss_yen, rows.length]);
}

for (const symbol of symbols) for (let quantity = 1; quantity <= caps[symbol]; quantity++) {
  for (const phase of ['all', '条件固定後', '調整に使用']) for (const part of ['all', 'Day', 'Night']) {
    nodes.get('qty-' + symbol).value = String(quantity);
    nodes.get('phase').value = phase;
    nodes.get('part').value = part;
    nodes.get('qty-' + symbol).listeners.change();
    checkDynamic(symbol, quantity, phase, part);
    report.全選択組合せ数++;
  }
}
for (const symbol of symbols) for (const [raw, quantity] of [['0',1], ['-1',1], ['100', caps[symbol]], ['1.9',1], ['NaN',1], ['Infinity',1]]) {
  nodes.get('qty-' + symbol).value = raw;
  nodes.get('phase').value = 'all';
  nodes.get('part').value = 'all';
  nodes.get('qty-' + symbol).listeners.change();
  checkDynamic(symbol, quantity, 'all', 'all');
  report.補正入力数++;
}
for (const symbol of symbols) nodes.get('qty-' + symbol).value = String(caps[symbol]);
for (const phase of ['all', '条件固定後', '調整に使用']) for (const part of ['all', 'Day', 'Night']) {
  nodes.get('phase').value = phase;
  nodes.get('part').value = part;
  for (const control of ['phase', 'part']) {
    nodes.get(control).listeners.change();
    for (const symbol of symbols) checkDynamic(symbol, caps[symbol], phase, part);
  }
}

// ----------------------------------------
// 外部接続を使用せず、全ローカルリンクと表示上の前提を確認します。
const allIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(x => x[1]));
for (const match of html.matchAll(/href="([^"]+)"/g)) {
  const href = match[1];
  assert.ok(!/^https?:/i.test(href), '今回の報告はローカル資料のみ');
  if (href.startsWith('#')) assert.ok(allIds.has(href.slice(1)), href);
  else assert.ok(fs.existsSync(path.resolve(target, decodeURIComponent(href.split('#')[0]))), href);
  report.リンク.push({参照: href, 存在: true});
}
assert.ok(html.includes('枚数差＝利益枚数−損失枚数'));
assert.ok(html.includes('途中の含み損・最大ドローダウンは損失欄に含みません'));
assert.ok(html.includes('全枚数を同時に新規・返済する前提の比例換算'));
assert.ok(html.includes('ナイトの日付は開始日'));
assert.ok(!/fetch\s*\(|XMLHttpRequest|WebSocket/.test(source));
report.レビュー = ['金額は円、決済枚数は枚、取引回数は回で区別されています。', '利益・損失枚数と枚数差は定義済み。損益０枚数も別掲され、決済累計と同時保有は区別されています。', '損失は確定損失の絶対額。含み損と最大ドローダウンを含まない説明があります。', '固定枚数の変更は金額・決済枚数の比例換算であり、取引回数とセッション数は増えません。', '週別合計は収録件数を表示し、未完成の１週間を完成済みと誤認させない表示です。'];
report.合格 = true;
report.監査時刻 = new Date().toISOString();
report.HTML_SHA256 = crypto.createHash('sha256').update(html).digest('hex');
report.JSON_SHA256 = crypto.createHash('sha256').update(fs.readFileSync(path.join(target, 'セッション損益.json'))).digest('hex');
fs.writeFileSync(path.join(__dirname, '表示監査.json'), JSON.stringify(report, null, 2), 'utf8');
process.stdout.write(JSON.stringify(report, null, 2) + '\n');
