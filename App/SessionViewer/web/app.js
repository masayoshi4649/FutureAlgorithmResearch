'use strict';

const SERIES = ['price', 'short', 'long', 'realized', 'unrealized'];
const COLORS = {price: '#78c8f0', short: '#ee9baf', long: '#76d6ce', realized: '#b5a5f2', unrealized: '#e9c17d'};
const PLOT = {left: 76, right: 18, top: 10, bottom: 28};
const PAGE_SIZE = 100;
const number = new Intl.NumberFormat('ja-JP', {maximumFractionDigits: 2});
const clock = new Intl.DateTimeFormat('ja-JP', {timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'});
const dateClock = new Intl.DateTimeFormat('ja-JP', {timeZone: 'Asia/Tokyo', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'});
const state = {info: null, catalog: null, catalogPath: '', resource: null, mode: 'resource', data: null,
  full: null, view: null, cursor: null, selectedEvent: null, page: 0, generation: 0, catalogGeneration: 0,
  sessionGeneration: 0, controller: null, catalogController: null, sessionsController: null,
  fetchTimer: 0, drawFrame: 0, loading: false, drag: null, width: 0, sourceRevision: 0};

// ----------------------------------------
// 時刻・欠測・API契約の共通処理。

/**
 * IDから画面要素を得る。
 * @param {string} id - 要素ID。
 * @returns {HTMLElement} 対象要素。
 */
function el(id) { return document.getElementById(id); }

/**
 * 欠測を変換せず、有限数値だけを採用する。
 * @param {unknown} value - APIの値。
 * @returns {number|null} 有限数又はnull。
 */
function finite(value) { return typeof value === 'number' && Number.isFinite(value) ? value : null; }

/**
 * 数値又は未観測記号を表示する。
 * @param {number|null} value - 表示値。
 * @returns {string} 日本語数値又は長音記号。
 */
function formatNumber(value) { return finite(value) === null ? '—' : number.format(value); }

/**
 * エポックミリ秒をJSTで表示する。
 * @param {number|null} time - エポックミリ秒。
 * @param {boolean} full - 月日を含める場合true。
 * @param {boolean} millis - ミリ秒を含める場合true。
 * @returns {string} 表示日時。
 */
function formatTime(time, full = true, millis = false) {
  if (finite(time) === null) return '—';
  const tail = millis ? `.${String(Math.floor(time) % 1000).padStart(3, '0')}` : '';
  return (full ? dateClock : clock).format(new Date(time)) + tail;
}

/**
 * JSTの日時入力欄へ設定できる文字列を作る。
 * @param {number} time - エポックミリ秒。
 * @returns {string} タイムゾーンなしのJST日時。
 */
function inputTime(time) { return new Date(time + 9 * 3600000).toISOString().slice(0, 23); }

/**
 * 日時入力をブラウザーのローカル時間帯によらずJSTとして読む。
 * @param {string} value - 日時入力文字列。
 * @returns {number} エポックミリ秒。不正値はNaN。
 */
function parseJST(value) { return value ? Date.parse(`${value}+09:00`) : NaN; }

/**
 * APIの失敗を含む画面メッセージを設定する。
 * @param {string} message - 空文字なら解除。
 * @returns {void} 返り値なし。
 */
function showError(message) { el('error').textContent = message; el('error').hidden = !message; }

/**
 * 読込状態を視覚表示と支援技術へ伝える。
 * @param {boolean} loading - 読込中か。
 * @param {string} message - 状態説明。
 * @returns {void} 返り値なし。
 */
function setLoading(loading, message) {
  state.loading = loading;
  document.body.classList.toggle('is-loading', loading);
  el('charts').setAttribute('aria-busy', String(loading));
  el('status').textContent = message;
}

/**
 * 同一サーバーのJSON APIを読み、サーバーの日本語エラーを保持する。
 * @param {string} url - API相対URL。
 * @param {RequestInit} options - fetch設定。
 * @returns {Promise<object>} JSON結果。
 */
async function api(url, options = {}) {
  const response = await fetch(url, {...options, cache: 'no-store'});
  let data;
  try { data = await response.json(); } catch { throw new Error(`応答をJSONとして読めません（HTTP ${response.status}）`); }
  if (!response.ok) throw new Error(data.error || `取得に失敗しました（HTTP ${response.status}）`);
  return data;
}

/**
 * 時刻順配列で指定時刻以上、又は指定時刻より後の位置を探す。
 * @param {object[]} rows - tが昇順の配列。
 * @param {number} time - 検索時刻。
 * @param {boolean} after - 同時刻の最後を越える場合true。
 * @returns {number} 挿入位置。
 */
function bound(rows, time, after = false) {
  let left = 0, right = rows.length;
  while (left < right) { const middle = (left + right) >>> 1; if (rows[middle].t < time || (after && rows[middle].t === time)) left = middle + 1; else right = middle; }
  return left;
}

/**
 * 初回前と末尾後を外挿せず、同時刻では原配列の最終行を選ぶ。
 * @param {object[]} rows - 原行順を保持した時系列。
 * @param {number} time - 確認時刻。
 * @returns {{row:object|null,count:number}} 観測行とその同時刻件数。
 */
function valueAt(rows, time) {
  if (!rows.length || time < rows[0].t || time > rows[rows.length - 1].t) return {row: null, count: 0};
  const index = bound(rows, time, true) - 1, row = rows[index];
  return {row, count: bound(rows, row.t, true) - bound(rows, row.t)};
}

/**
 * 列名契約に従ってAPI配列を描画用へ写す。数量や損益は再計算しない。
 * @param {object} payload - /api/dataの応答。
 * @returns {object} 描画用データ。
 */
function normalize(payload) {
  const pcols = payload.price_columns || ['t', 'line', 'last', 'bid', 'ask'];
  const scols = payload.state_columns || ['t', 'sequence', 'source_line', 'long_qty', 'short_qty', 'realized_pnl_yen', 'unrealized_pnl_yen'];
  const ccols = payload.candle_columns || ['t', 'end_ms', 'open', 'high', 'low', 'close'];
  const prices = (payload.prices || []).map(row => ({t: finite(row[pcols.indexOf('t')]), line: row[pcols.indexOf('line')],
    last: finite(row[pcols.indexOf('last')]), bid: finite(row[pcols.indexOf('bid')]), ask: finite(row[pcols.indexOf('ask')])}));
  const states = (payload.states || []).map(row => ({t: finite(row[scols.indexOf('t')]), sequence: row[scols.indexOf('sequence')], line: row[scols.indexOf('source_line')],
    long: finite(row[scols.indexOf('long_qty')]), short: finite(row[scols.indexOf('short_qty')]),
    realized: finite(row[scols.indexOf('realized_pnl_yen')]), unrealized: finite(row[scols.indexOf('unrealized_pnl_yen')])}));
  const candles = (payload.candles || []).map(row => Object.fromEntries(ccols.map((key, index) => [key, finite(row[index])])));
  for (const rows of [prices, states, candles]) {
    for (let i = 0; i < rows.length; i += 1) if (rows[i].t === null || (i && rows[i].t < rows[i - 1].t)) throw new Error('時系列データの時刻順が不正です');
  }
  if (candles.some(row => row.end_ms === null || row.end_ms <= row.t)) throw new Error('分足の区間が不正です');
  const events = (payload.events || []).map((event, index) => ({...event, order: index})).filter(event => finite(event.timestamp_ms) !== null)
    .sort((a, b) => a.timestamp_ms - b.timestamp_ms || (finite(a.sequence) ?? a.order) - (finite(b.sequence) ?? b.order));
  return {...payload, interval: String(payload.interval || 'raw'), prices, states, candles, events};
}

/**
 * 取得済みの応答が分足か確認する。
 * @returns {boolean} 分足ならtrue。引数なし。
 */
function isBars() { return !!state.data && state.data.interval !== 'raw'; }

/**
 * 時刻に対応する価格区間を得る。場末だけは直前の足を選ぶ。
 * @param {number} time - 共通カーソル時刻。
 * @returns {object|null} 原板から集計したOHLC区間。
 */
function candleAt(time) {
  const rows = state.data?.candles || [];
  const index = Math.max(0, bound(rows, time, true) - 1), row = rows[index];
  return row && time >= row.t && (time < row.end_ms || index === rows.length - 1 && time === row.end_ms) ? row : null;
}

/**
 * 分足の最後状態を終了時刻で対応づける。
 * @param {object|null} candle - 選択した分足。
 * @returns {object|null} その区間の最後状態。隣の足で補完しない。
 */
function candleState(candle) {
  if (!candle) return null;
  const rows = state.data?.states || [], index = bound(rows, candle.end_ms, true) - 1;
  return index >= 0 && rows[index].t === candle.end_ms ? rows[index] : null;
}

/**
 * 選択した価格を得る。中値も両気配が既知のときだけ作る。
 * @param {object|null} row - 価格行。
 * @returns {number|null} 価格又は欠測。
 */
function priceValue(row) {
  if (!row) return null;
  const kind = el('price-field').value;
  return kind === 'mid' ? (row.bid !== null && row.ask !== null && row.bid < row.ask ? (row.bid + row.ask) / 2 : null) : row[kind];
}

/**
 * 表示範囲をセッション内へ収める。
 * @param {number} from - 希望開始時刻。
 * @param {number} to - 希望終了時刻。
 * @returns {number[]} 補正した開始と終了。
 */
function clampRange(from, to) {
  if (!state.full) return [from, to];
  const [start, end] = state.full, whole = end - start;
  const span = Math.min(whole, Math.max(Math.min(100, whole), to - from));
  const left = Math.max(start, Math.min(end - span, from));
  return [left, left + span];
}

/**
 * 表示範囲・入力欄・描画を更新し、縮約の再取得を予約する。
 * @param {number} from - 開始時刻。
 * @param {number} to - 終了時刻。
 * @param {boolean} fetchData - APIを再取得するか。
 * @returns {void} 返り値なし。
 */
function setView(from, to, fetchData = true) {
  if (!state.full || !Number.isFinite(from) || !Number.isFinite(to) || to <= from) return;
  state.view = clampRange(from, to); state.page = 0;
  syncRange(); scheduleDraw(); renderEvents();
  if (fetchData) queueData();
}

/**
 * 共通範囲入力と位置スライダーを同期する。
 * @returns {void} 返り値なし。引数なし。
 */
function syncRange() {
  if (!state.view || !state.full) return;
  el('range-from').value = inputTime(state.view[0]); el('range-to').value = inputTime(state.view[1]);
  const travel = (state.full[1] - state.full[0]) - (state.view[1] - state.view[0]);
  el('position-slider').disabled = travel <= 0;
  el('position-slider').value = travel > 0 ? String(Math.round((state.view[0] - state.full[0]) / travel * 1000)) : '0';
  el('session-start').textContent = formatTime(state.full[0]); el('session-end').textContent = formatTime(state.full[1]);
}

/**
 * 表示対象の変更時に旧要求を無効化する。
 * @returns {void} 返り値なし。引数なし。
 */
function resetData() {
  state.generation += 1; state.controller?.abort(); clearTimeout(state.fetchTimer);
  state.data = null; state.full = null; state.view = null; state.cursor = null; state.page = 0; state.selectedEvent = null;
  el('position-slider').disabled = true; el('quality').textContent = ''; el('files').replaceChildren();
  el('range-from').value = ''; el('range-to').value = ''; el('session-start').textContent = '—'; el('session-end').textContent = '—';
  el('resource-title').textContent = '資料を選択';
  scheduleDraw(); renderEvents();
}

// ----------------------------------------
// 資料の選択と非同期読込。

/**
 * 画面幅を含め、現在の対象と範囲のデータを取得する。
 * @returns {Promise<void>} 描画可能なデータを設定する。引数なし。
 */
async function loadData() {
  const query = new URLSearchParams();
  const requestInterval = el('interval').value, requestPrice = el('price-field').value;
  query.set('interval', requestInterval); query.set('price', requestPrice);
  if (state.mode === 'resource') {
    if (!state.catalog || !state.resource) return;
    query.set('catalog', state.catalog.catalog_id); query.set('resource', state.resource.id);
  } else {
    if (!el('symbol-input').value.trim() || !el('session-select').value) return;
    query.set('symbol', el('symbol-input').value.trim()); query.set('session', el('session-select').value);
  }
  const requestView = state.view ? [...state.view] : null;
  if (requestView) { query.set('from', String(Math.floor(requestView[0]))); query.set('to', String(Math.ceil(requestView[1]))); }
  query.set('width', String(Math.max(100, Math.floor(el('chart-price').clientWidth - PLOT.left - PLOT.right))));
  state.controller?.abort(); const controller = new AbortController(); state.controller = controller;
  const generation = ++state.generation; showError(''); setLoading(true, '表示データを読込中…');
  try {
    const payload = await api(`/api/data?${query}`, {signal: controller.signal});
    if (generation !== state.generation || controller.signal.aborted) return;
    const data = normalize(payload), range = data.range || {};
    if (data.interval !== requestInterval || requestInterval !== 'raw' && data.candle_price !== requestPrice) throw new Error('表示単位に対応した応答ではありません。アプリを更新してください');
    if (finite(range.start_ms) === null || finite(range.end_ms) === null || range.end_ms <= range.start_ms) throw new Error('セッションの表示範囲が不正です');
    state.data = data; state.full = [range.start_ms, range.end_ms];
    if (!state.view) state.view = clampRange(finite(range.from_ms) ?? range.start_ms, finite(range.to_ms) ?? range.end_ms);
    else state.view = clampRange(...state.view);
    syncRange(); renderMeta(); renderEvents(); scheduleDraw();
    const prices = isBars() ? data.candles.length : data.prices.length;
    setLoading(false, prices || data.states.length ? `${prices.toLocaleString('ja-JP')}${isBars() ? '本の分足' : '価格点'}・${data.states.length.toLocaleString('ja-JP')}状態点` : 'この範囲に観測データはありません');
  } catch (error) {
    if (generation !== state.generation || error.name === 'AbortError') return;
    showError(error.message); setLoading(false, '取得に失敗しました');
  }
}

/**
 * ズームとパンの連続操作をまとめ、古い応答は直ちに無効化する。
 * @returns {void} 返り値なし。引数なし。
 */
function queueData() {
  clearTimeout(state.fetchTimer); state.generation += 1; state.controller?.abort();
  state.fetchTimer = setTimeout(loadData, 180);
}

/**
 * リソース一覧JSONをパス又はアップロード内容から開く。
 * @param {string} path - サーバー上の一覧パス。アップロード時は空。
 * @param {object|null} catalog - アップロードした一覧。
 * @param {string} preferred - 優先リソースID。
 * @param {object} filters - URLで指定された銘柄・場・手法ID。
 * @returns {Promise<void>} 一覧設定後にデータを取得する。
 */
async function loadCatalog(path, catalog = null, preferred = '', filters = {}) {
  if (!catalog && !path.trim()) { showError('一覧ファイルのパスを指定してください'); return; }
  setMode('resource'); state.catalog = null; state.resource = null; el('resource-select').disabled = true;
  for (const id of ['resource-symbol', 'resource-session', 'resource-method']) el(id).disabled = true;
  state.catalogController?.abort(); const controller = new AbortController(); state.catalogController = controller;
  const generation = ++state.catalogGeneration;
  resetData(); setLoading(true, 'リソース一覧を読込中…'); showError('');
  try {
    const loaded = await api('/api/catalogs/load', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(catalog ? {catalog} : {path: path.trim()}), signal: controller.signal});
    if (generation !== state.catalogGeneration) return;
    if (!Array.isArray(loaded.resources)) throw new Error('リソース一覧の形式が不正です');
    state.catalog = loaded; state.catalogPath = catalog ? '' : path.trim();
    if (!loaded.resources.length) { setLoading(false, '一覧にリソースがありません'); return; }
    const seed = preferred ? loaded.resources.find(resource => resource.id === preferred) : loaded.resources.find(resource =>
      (!filters.symbol || resource.symbol === filters.symbol) && (!filters.session || resource.session === filters.session) && (!filters.method || methodKey(resource) === filters.method));
    rebuildResourceSelectors(seed || null);
    if (preferred && !seed || !preferred && Object.values(filters).some(Boolean) && !seed) {
      setLoading(false, '選択条件を確認してください'); showError(preferred ? `指定されたリソースがありません: ${preferred}` : '指定された銘柄・日付_セッション・手法IDの組合せがありません'); return;
    }
    setMode('resource'); selectResource();
  } catch (error) {
    if (generation !== state.catalogGeneration || error.name === 'AbortError') return;
    showError(error.message); setLoading(false, '一覧を開けませんでした');
  }
}

/**
 * 手法IDを持たない資料も、別の手法へ混ぜず識別する。
 * @param {object} resource - 一覧内の資源。
 * @returns {string} セレクト用の手法識別子。
 */
function methodKey(resource) { return resource.method_id || `@resource:${resource.id}`; }

/**
 * 実在する選択肢だけを配置し、残せる選択を維持する。
 * @param {string} id - セレクト要素ID。
 * @param {{value:string,label:string}[]} choices - 選択肢。
 * @param {string} wanted - 希望値。
 * @returns {string} 実際に選んだ値。
 */
function fillSelect(id, choices, wanted) {
  const select = el(id); select.replaceChildren();
  for (const choice of choices) { const option = document.createElement('option'); option.value = choice.value; option.textContent = choice.label; select.append(option); }
  select.disabled = !choices.length;
  if (!choices.length) { const option = document.createElement('option'); option.value = ''; option.textContent = '該当なし'; select.append(option); }
  else if (choices.some(choice => choice.value === wanted)) select.value = wanted;
  return select.value;
}

/**
 * 銘柄・場・手法・リソースの候補を実在する組合せへ連動させる。
 * @param {object|null} preferred - 一覧読込時に優先するリソース。
 * @returns {void} 選択肢を更新する。データ取得は呼出側で行う。
 */
function rebuildResourceSelectors(preferred = null) {
  const resources = state.catalog?.resources || [], unique = values => [...new Set(values)].sort((a, b) => a.localeCompare(b, 'ja'));
  const symbol = fillSelect('resource-symbol', unique(resources.map(resource => resource.symbol)).map(value => ({value, label: value})), preferred?.symbol || el('resource-symbol').value);
  const matchingSymbol = resources.filter(resource => resource.symbol === symbol);
  const session = fillSelect('resource-session', unique(matchingSymbol.map(resource => resource.session)).map(value => ({value, label: value})), preferred?.session || el('resource-session').value);
  const matchingSession = matchingSymbol.filter(resource => resource.session === session);
  const methods = unique(matchingSession.map(methodKey)).map(value => {
    const item = matchingSession.find(resource => methodKey(resource) === value);
    return {value, label: item.method_id === '*' ? '全手法（合計）' : item.method_id || `手法ID未指定（${item.id}）`};
  });
  const method = fillSelect('resource-method', methods, preferred ? methodKey(preferred) : el('resource-method').value);
  const candidates = matchingSession.filter(resource => methodKey(resource) === method);
  fillSelect('resource-select', candidates.map(resource => ({value: resource.id, label: [resource.title || resource.id, resource.product || resource.symbol].filter(Boolean).join(' ／ ')})), preferred?.id || el('resource-select').value);
}

/**
 * 選択された資源を反映し、再読み込み可能なURLを設定する。
 * @returns {void} 返り値なし。引数なし。
 */
function selectResource() {
  state.sourceRevision += 1;
  state.resource = state.catalog?.resources.find(resource => resource.id === el('resource-select').value) || null;
  resetData(); updateURL();
  if (state.resource) loadData(); else setLoading(false, '一覧JSONを開いてください');
}

/**
 * 表示形式変更時に古い画面を捨て、同じ時間範囲を新しい単位で取得する。
 * @returns {void} 返り値なし。引数なし。
 */
function reloadPresentation() {
  state.generation += 1; state.controller?.abort(); clearTimeout(state.fetchTimer);
  state.data = null; state.selectedEvent = null; state.page = 0;
  el('quality').textContent = ''; scheduleDraw(); renderEvents(); updateURL(); loadData();
}

/**
 * リソース表示と価格だけの表示を切り替える。
 * @param {string} mode - resource又はprice。
 * @returns {void} 返り値なし。
 */
function setMode(mode) {
  state.sourceRevision += 1;
  if (mode === 'price') { state.catalogGeneration += 1; state.catalogController?.abort(); }
  else { state.sessionGeneration += 1; state.sessionsController?.abort(); }
  state.mode = mode;
  el('resource-controls').hidden = mode !== 'resource'; el('price-controls').hidden = mode !== 'price';
  el('mode-resource').setAttribute('aria-pressed', String(mode === 'resource')); el('mode-price').setAttribute('aria-pressed', String(mode === 'price'));
}

/**
 * サーバーパス又は価格だけの指定をURLへ保持する。
 * @returns {void} 返り値なし。引数なし。
 */
function updateURL() {
  const url = new URL(location.href);
  for (const key of ['catalog', 'resource', 'symbol', 'session', 'method', 'interval', 'price']) url.searchParams.delete(key);
  if (state.mode === 'resource' && state.catalogPath && state.resource) {
    url.searchParams.set('catalog', state.catalogPath); url.searchParams.set('resource', state.resource.id);
    url.searchParams.set('symbol', state.resource.symbol); url.searchParams.set('session', state.resource.session); url.searchParams.set('method', methodKey(state.resource));
  }
  if (state.mode === 'price') { url.searchParams.set('symbol', el('symbol-input').value.trim()); url.searchParams.set('session', el('session-select').value); }
  url.searchParams.set('interval', el('interval').value); url.searchParams.set('price', el('price-field').value);
  history.replaceState(null, '', url);
}

/**
 * 銘柄の保存セッション一覧を取得する。
 * @param {string} preferred - 優先する場。
 * @returns {Promise<boolean>} 現在の要求に対する選択肢を設定できたか。
 */
async function loadSessions(preferred = '') {
  state.sessionsController?.abort(); const controller = new AbortController(); state.sessionsController = controller;
  const generation = ++state.sessionGeneration, symbol = el('symbol-input').value.trim();
  el('session-select').disabled = true; showError(''); setLoading(true, 'セッション一覧を読込中…');
  try {
    const data = await api(`/api/sessions?${new URLSearchParams({symbol})}`, {signal: controller.signal});
    if (generation !== state.sessionGeneration || state.mode !== 'price') return false;
    el('session-select').replaceChildren();
    for (const item of data.sessions || []) { const option = document.createElement('option'); option.value = item.session; option.textContent = item.session; el('session-select').append(option); }
    if ([...el('session-select').options].some(option => option.value === preferred)) el('session-select').value = preferred;
    else if (preferred) { el('session-select').disabled = !el('session-select').options.length; showError(`指定されたセッションがありません: ${preferred}`); setLoading(false, 'セッションを選択してください'); return false; }
    else if (el('session-select').options.length) el('session-select').selectedIndex = el('session-select').options.length - 1;
    el('session-select').disabled = !el('session-select').options.length;
    setLoading(false, el('session-select').options.length ? 'セッションを選択してください' : '保存済みセッションがありません');
    return !!el('session-select').options.length;
  } catch (error) { if (generation === state.sessionGeneration && error.name !== 'AbortError') { showError(error.message); setLoading(false, '一覧を取得できませんでした'); } }
  return false;
}

/**
 * アップロードJSONを解析してAPIへ送る。
 * @param {File|undefined} file - 選択された一覧ファイル。
 * @returns {Promise<void>} 一覧読込の完了。
 */
async function openFile(file) {
  if (!file) return;
  const revision = ++state.sourceRevision;
  try { const catalog = JSON.parse(await file.text()); if (revision === state.sourceRevision) await loadCatalog('', catalog); }
  catch (error) { if (revision === state.sourceRevision) showError(`一覧JSONを読めません: ${error.message}`); }
  el('catalog-upload').value = '';
}

/**
 * 価格時計、縮約件数、参照ファイルを小さく表示する。
 * @returns {void} 返り値なし。引数なし。
 */
function renderMeta() {
  const data = state.data; if (!data) return;
  const resource = data.resource || state.resource || {};
  el('resource-title').textContent = [resource.title || resource.id || el('symbol-input').value, resource.session || (state.mode === 'price' ? el('session-select').value : '')].filter(Boolean).join(' ／ ');
  const sample = data.sampling || {}, quality = data.quality || {};
  el('price-kind-label').textContent = `${el('price-field').selectedOptions[0].textContent}${isBars() ? `・${data.interval}分足` : '・raw'}`;
  const text = [`価格時計（JST）・受信時刻とは異なります`, `価格 ${formatNumber(sample.price_output ?? (isBars() ? data.candles.length : data.prices.length))} / ${formatNumber(sample.price_input)} ${isBars() ? '本 / 原行' : '点'}`,
    `状態 ${formatNumber(sample.state_output ?? data.states.length)} / ${formatNumber(sample.state_input)} 点`];
  if (isBars()) text.push('OHLCは原板全行から集計・保有とPLは各区間の最後値');
  if (sample.price_input > 0 && finite(sample.price_output) !== null) text.push(`価格点削減 ${(100 * (1 - sample.price_output / sample.price_input)).toFixed(1)}%`);
  if (quality.duplicate_clock_rows) text.push(`同価格時計 ${formatNumber(quality.duplicate_clock_rows)} 行`);
  if (quality.invalid_clock_rows) text.push(`時計不正 ${formatNumber(quality.invalid_clock_rows)} 行`);
  if (quality.reversed_clock_rows) text.push(`時計逆行 ${formatNumber(quality.reversed_clock_rows)} 行`);
  el('quality').replaceChildren(document.createTextNode(text.join(' ・ ')));
  for (const warning of quality.warnings || []) { const line = document.createElement('div'); line.className = 'warning'; line.textContent = String(warning); el('quality').append(line); }
  el('files').replaceChildren();
  for (const [key, value] of Object.entries(data.files || {})) {
    if (!value) continue;
    const dt = document.createElement('dt'), dd = document.createElement('dd'); dt.textContent = {market: '価格', pnl: '損益', catalog: '一覧'}[key] || key;
    dd.textContent = typeof value === 'string' ? value : JSON.stringify(value); el('files').append(dt, dd);
  }
}

/**
 * 表示区間とその両隣の点を原行順のまま得る。
 * @param {object[]} rows - 昇順時系列。
 * @returns {object[]} 描画に必要な行。
 */
function visibleRows(rows) { return !state.view ? [] : rows.slice(Math.max(0, bound(rows, state.view[0]) - 1), Math.min(rows.length, bound(rows, state.view[1], true) + 1)); }

/**
 * 表示範囲と重なる完全な足を得る。表示境界でOHLCを再集計しない。
 * @returns {object[]} 表示するOHLC区間。引数なし。
 */
function visibleCandles() { return !state.view ? [] : (state.data?.candles || []).filter(row => row.end_ms > state.view[0] && row.t <= state.view[1]); }

// ----------------------------------------
// 共通時刻を使った描画と操作。

/**
 * 枚数、価格、中心0の損益の目盛範囲を得る。
 * @param {string} series - 系列名。
 * @param {object[]} rows - 描画対象行。
 * @returns {number[]} 最小と最大。
 */
function domain(series, rows) {
  const vals = series === 'price' && isBars() ? rows.flatMap(row => [row.open, row.high, row.low, row.close]).filter(value => finite(value) !== null) :
    rows.map(row => series === 'price' ? priceValue(row) : row[series]).filter(value => finite(value) !== null);
  if (series === 'realized' || series === 'unrealized') {
    if (el('shared-scale').checked) for (const row of rows) for (const key of ['realized', 'unrealized']) if (finite(row[key]) !== null) vals.push(row[key]);
    let extent = 1; for (const value of vals) extent = Math.max(extent, Math.abs(value));
    return [-extent * 1.1, extent * 1.1];
  }
  if (series !== 'price') { let max = 1; for (const value of vals) max = Math.max(max, value); return [0, Math.max(1, Math.ceil(max * 1.1))]; }
  if (!vals.length) return [0, 1];
  let low = vals[0], high = vals[0]; for (const value of vals) { low = Math.min(low, value); high = Math.max(high, value); }
  const padding = Math.max(1, (high - low) * 0.08); return [low - padding, high + padding];
}

/**
 * Canvasを実画素へ合わせ、1系列を描画する。
 * @param {string} series - 描画する系列。
 * @returns {void} 返り値なし。
 */
function drawChart(series) {
  const canvas = el(`chart-${series}`), width = canvas.clientWidth, height = canvas.clientHeight;
  if (width < 1 || height < 1) return;
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) { canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr); }
  const ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, width, height);
  const pw = Math.max(1, width - PLOT.left - PLOT.right), ph = height - PLOT.top - PLOT.bottom;
  if (!state.data || !state.view) { ctx.fillStyle = '#6f859d'; ctx.font = '12px sans-serif'; ctx.textAlign = 'center'; ctx.fillText(state.loading ? '読込中…' : '表示データがありません', width / 2, height / 2); return; }
  const rows = series === 'price' && isBars() ? visibleCandles() : visibleRows(series === 'price' ? state.data.prices : state.data.states);
  const [lo, hi] = domain(series, rows), [from, to] = state.view;
  const x = time => PLOT.left + (time - from) / (to - from) * pw;
  const y = value => PLOT.top + (hi - value) / (hi - lo) * ph;
  ctx.font = '10px sans-serif'; ctx.textBaseline = 'middle'; ctx.lineWidth = 1;
  const steps = series === 'price' ? 4 : 2;
  for (let i = 0; i <= steps; i += 1) {
    const value = lo + (hi - lo) * i / steps, py = y(value);
    if ((series === 'short' || series === 'long') && !Number.isInteger(value)) continue;
    ctx.strokeStyle = Math.abs(value) < 1e-9 ? '#59718b' : '#223246'; ctx.beginPath(); ctx.moveTo(PLOT.left, py); ctx.lineTo(width - PLOT.right, py); ctx.stroke();
    ctx.textAlign = 'right'; ctx.fillStyle = '#8da2b9'; ctx.fillText(series === 'short' || series === 'long' ? String(Math.round(value)) : number.format(Math.round(value * 100) / 100), PLOT.left - 8, py);
  }
  const ticks = Math.max(1, Math.min(7, Math.floor(pw / 145)));
  for (let i = 0; i <= ticks; i += 1) {
    const at = from + (to - from) * i / ticks, px = x(at);
    ctx.strokeStyle = '#1d2b3a'; ctx.beginPath(); ctx.moveTo(px, PLOT.top); ctx.lineTo(px, height - PLOT.bottom); ctx.stroke();
    ctx.fillStyle = '#8499b0'; ctx.textAlign = i === 0 ? 'left' : i === ticks ? 'right' : 'center';
    ctx.fillText(formatTime(at, true, to - from < 5000), px, height - 12);
  }
  ctx.save(); ctx.beginPath(); ctx.rect(PLOT.left, PLOT.top, pw, ph); ctx.clip();
  ctx.strokeStyle = COLORS[series]; ctx.fillStyle = COLORS[series]; ctx.lineWidth = 1.4; ctx.beginPath();
  let previous = null, hasValue = false;
  if (series === 'price' && isBars()) {
    for (const row of rows) {
      if ([row.open, row.high, row.low, row.close].some(value => finite(value) === null)) continue;
      hasValue = true;
      const center = (Math.max(from, row.t) + Math.min(to, row.end_ms)) / 2;
      const px = x(center), candleWidth = Math.max(1, Math.min(16, Math.abs(x(Math.min(to, row.end_ms)) - x(Math.max(from, row.t))) * .7));
      ctx.strokeStyle = row.close >= row.open ? COLORS.long : COLORS.short; ctx.fillStyle = ctx.strokeStyle;
      ctx.beginPath(); ctx.moveTo(px, y(row.high)); ctx.lineTo(px, y(row.low)); ctx.stroke();
      const top = Math.min(y(row.open), y(row.close)), height = Math.max(1, Math.abs(y(row.open) - y(row.close)));
      ctx.fillRect(px - candleWidth / 2, top, candleWidth, height);
    }
  } else for (const row of rows) {
    const value = series === 'price' ? priceValue(row) : row[series];
    if (finite(value) === null) {
      if (previous && series !== 'price') ctx.lineTo(x(row.t), y(previous.value));
      previous = null; continue;
    }
    hasValue = true; const px = x(row.t), py = y(value);
    if (!previous) ctx.moveTo(px, py);
    else { if (series !== 'price') ctx.lineTo(px, y(previous.value)); ctx.lineTo(px, py); }
    if (series !== 'price' && isBars()) ctx.fillRect(px - 1, py - 1, 2, 2);
    previous = {value, time: row.t};
  }
  if (!(series === 'price' && isBars())) ctx.stroke();
  if (rows.length === 1 && hasValue && !(series === 'price' && isBars())) { const value = series === 'price' ? priceValue(rows[0]) : rows[0][series]; ctx.beginPath(); ctx.arc(x(rows[0].t), y(value), 2, 0, 2 * Math.PI); ctx.fill(); }
  if (state.cursor !== null && state.cursor >= from && state.cursor <= to) { ctx.strokeStyle = '#e1eaf0aa'; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(x(state.cursor), PLOT.top); ctx.lineTo(x(state.cursor), height - PLOT.bottom); ctx.stroke(); ctx.setLineDash([]); }
  ctx.restore();
  if (!hasValue) { ctx.fillStyle = '#71869d'; ctx.textAlign = 'center'; ctx.fillText(series === 'price' ? 'この範囲の価格は未観測' : 'この範囲の状態は未観測', PLOT.left + pw / 2, PLOT.top + ph / 2); }
}

/**
 * 同期カーソルの時刻、連番、5系列の値を更新する。
 * @returns {void} 返り値なし。引数なし。
 */
function renderCursor() {
  if (!state.data || !state.view) { for (const key of SERIES) el(`value-${key}`).textContent = '—'; el('cursor-time').textContent = '—'; el('cursor-detail').textContent = '時刻に合わせて5段を確認'; return; }
  const lastPrice = isBars() ? state.data.candles.at(-1)?.end_ms : state.data.prices.at(-1)?.t, lastState = state.data.states.at(-1)?.t;
  const latest = Math.min(state.view[1], Math.max(lastPrice ?? state.view[0], lastState ?? state.view[0]));
  const at = state.cursor ?? latest, candle = isBars() ? candleAt(at) : null;
  const prices = valueAt(state.data.prices, at), current = isBars() ? {row: candleState(candle), count: 1} : valueAt(state.data.states, at);
  const values = {price: isBars() ? candle?.close ?? null : priceValue(prices.row), short: current.row?.short ?? null, long: current.row?.long ?? null,
    realized: current.row?.realized ?? null, unrealized: current.row?.unrealized ?? null};
  for (const key of SERIES) { const node = el(`value-${key}`); node.textContent = formatNumber(values[key]); node.classList.toggle('negative', key.includes('realized') && values[key] < 0); node.classList.toggle('positive', key.includes('realized') && values[key] > 0); }
  el('cursor-time').textContent = candle ? `${formatTime(candle.t)}〜${formatTime(candle.end_ms)} JST` : `${state.cursor === null ? '表示終端 ' : ''}${formatTime(at, true, true)} JST`;
  const parts = [];
  if (isBars()) parts.push(candle ? `始 ${formatNumber(candle.open)}・高 ${formatNumber(candle.high)}・安 ${formatNumber(candle.low)}・終 ${formatNumber(candle.close)} ／ 保有・PLは区間末` : '対応する分足なし');
  if (prices.row) parts.push(`価格行 ${prices.row.line ?? '—'}・同時刻${prices.count}行`);
  if (current.row) parts.push(`状態seq ${current.row.sequence ?? '—'}・同時刻${current.count}行（最終）`);
  if (current.row?.line != null) parts.push(`状態元行 ${current.row.line}`);
  el('cursor-detail').textContent = parts.join(' ／ ') || '観測範囲外';
}

/**
 * 複数イベントの描画要求を1フレームへまとめる。
 * @returns {void} 返り値なし。引数なし。
 */
function scheduleDraw() {
  if (state.drawFrame) return;
  state.drawFrame = requestAnimationFrame(() => { state.drawFrame = 0; for (const key of SERIES) drawChart(key); renderCursor(); });
}

/**
 * ポインターの横位置を全グラフ共通の時刻に変換する。
 * @param {PointerEvent|WheelEvent} event - ポインターイベント。
 * @param {HTMLCanvasElement} canvas - 対象Canvas。
 * @returns {number} 時刻。
 */
function pointerTime(event, canvas) {
  const rect = canvas.getBoundingClientRect(), ratio = Math.max(0, Math.min(1, (event.clientX - rect.left - PLOT.left) / Math.max(1, rect.width - PLOT.left - PLOT.right)));
  return state.view[0] + ratio * (state.view[1] - state.view[0]);
}

/**
 * 全グラフのズーム、パン、キーボード操作を接続する。
 * @param {HTMLCanvasElement} canvas - 対象Canvas。
 * @returns {void} 返り値なし。
 */
function bindChart(canvas) {
  canvas.addEventListener('wheel', event => {
    if (!state.view) return; event.preventDefault();
    const anchor = pointerTime(event, canvas), factor = Math.exp(Math.max(-1, Math.min(1, event.deltaY * 0.002)));
    setView(anchor - (anchor - state.view[0]) * factor, anchor + (state.view[1] - anchor) * factor);
  }, {passive: false});
  canvas.addEventListener('pointerdown', event => {
    if (!state.view || event.button !== 0) return;
    state.drag = {x: event.clientX, range: [...state.view], width: canvas.clientWidth - PLOT.left - PLOT.right};
    canvas.setPointerCapture(event.pointerId); document.body.classList.add('is-dragging');
  });
  canvas.addEventListener('pointermove', event => {
    if (!state.view) return;
    if (state.drag) { const shift = (state.drag.x - event.clientX) / Math.max(1, state.drag.width) * (state.drag.range[1] - state.drag.range[0]); setView(state.drag.range[0] + shift, state.drag.range[1] + shift); }
    state.cursor = pointerTime(event, canvas); scheduleDraw();
    if (el('events-near').checked) { state.page = 0; renderEvents(); }
  });
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) canvas.addEventListener(type, () => { state.drag = null; document.body.classList.remove('is-dragging'); });
  canvas.addEventListener('pointerleave', () => { if (!state.drag && !state.selectedEvent) { state.cursor = null; scheduleDraw(); } });
  canvas.addEventListener('keydown', event => {
    if (!state.view) return;
    const [from, to] = state.view, span = to - from, center = (from + to) / 2;
    if (event.key === 'ArrowLeft') setView(from - span / 5, to - span / 5);
    else if (event.key === 'ArrowRight') setView(from + span / 5, to + span / 5);
    else if (event.key === '+' || event.key === '=') setView(center - span / 4, center + span / 4);
    else if (event.key === '-') setView(center - span, center + span);
    else if (event.key === 'Home') setView(...state.full);
    else if (event.key === 'Escape') { state.selectedEvent = null; state.cursor = null; scheduleDraw(); renderEvents(); }
    else return;
    event.preventDefault();
  });
}

/**
 * 取引を会計し直さずページ表示し、同時刻の連番を保持する。
 * @returns {void} 返り値なし。引数なし。
 */
function renderEvents() {
  const body = el('event-rows'); body.replaceChildren();
  let events = (state.data?.events || []).filter(event => !state.view || event.timestamp_ms >= state.view[0] && event.timestamp_ms <= state.view[1]);
  if (el('events-near').checked && state.cursor !== null) events = events.filter(event => Math.abs(event.timestamp_ms - state.cursor) <= 30000);
  const pages = Math.max(1, Math.ceil(events.length / PAGE_SIZE)); state.page = Math.max(0, Math.min(pages - 1, state.page));
  el('event-count').textContent = `${events.length.toLocaleString('ja-JP')}件`; el('events-page').textContent = `${state.page + 1} / ${pages}`;
  el('events-prev').disabled = state.page === 0; el('events-next').disabled = state.page >= pages - 1;
  for (const event of events.slice(state.page * PAGE_SIZE, (state.page + 1) * PAGE_SIZE)) {
    const row = document.createElement('tr'); row.dataset.time = String(event.timestamp_ms); row.tabIndex = 0;
    row.classList.toggle('selected', state.selectedEvent === event);
    const kind = event.type === 'Detach' ? '管理外移管' : event.type || '—';
    const method = event.method_id === '*' ? '全手法（合計）' : event.method_id || '—';
    const values = [formatTime(event.timestamp_ms, true, true), event.sequence ?? '—', kind, event.type === 'Detach' ? '—' : formatNumber(event.price), formatNumber(event.qty), formatNumber(event.realized_delta_yen), event.position_id || '—', method];
    for (let i = 0; i < values.length; i += 1) { const cell = document.createElement('td'); cell.textContent = String(values[i]); if (i >= 6) { cell.className = 'id-cell'; cell.title = String(values[i]); } if (i === 5 && event.realized_delta_yen < 0) cell.className = 'negative'; row.append(cell); }
    const select = () => { state.selectedEvent = event; state.cursor = event.timestamp_ms; scheduleDraw(); renderEvents(); };
    row.addEventListener('click', select); row.addEventListener('keydown', key => { if (key.key === 'Enter' || key.key === ' ') { key.preventDefault(); select(); } });
    body.append(row);
  }
  if (!events.length) { const row = document.createElement('tr'), cell = document.createElement('td'); cell.colSpan = 8; cell.className = 'empty-cell'; cell.textContent = state.data ? 'この範囲に取引はありません' : '資料を選択してください'; row.append(cell); body.append(row); }
}

/**
 * ファイル入力、表示範囲と全体UIのイベントを接続する。
 * @returns {void} 返り値なし。引数なし。
 */
function bindUI() {
  el('catalog-form').addEventListener('submit', event => { event.preventDefault(); loadCatalog(el('catalog-path').value); });
  el('catalog-upload').addEventListener('change', event => openFile(event.target.files[0]));
  el('resource-select').addEventListener('change', selectResource);
  for (const id of ['resource-symbol', 'resource-session', 'resource-method']) el(id).addEventListener('change', () => { rebuildResourceSelectors(); selectResource(); });
  el('mode-resource').addEventListener('click', () => { setMode('resource'); selectResource(); });
  el('mode-price').addEventListener('click', async () => { setMode('price'); resetData(); if (await loadSessions()) { updateURL(); loadData(); } });
  el('symbol-input').addEventListener('change', () => { resetData(); loadSessions(); });
  el('price-controls').addEventListener('submit', event => { event.preventDefault(); resetData(); updateURL(); loadData(); });
  el('price-field').addEventListener('change', reloadPresentation);
  el('interval').addEventListener('change', reloadPresentation);
  el('shared-scale').addEventListener('change', scheduleDraw);
  el('range-form').addEventListener('submit', event => {
    event.preventDefault(); const from = parseJST(el('range-from').value), to = parseJST(el('range-to').value);
    if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) { showError('開始より後の終了日時をJSTで指定してください'); return; }
    showError(''); setView(from, to);
  });
  document.querySelectorAll('.preset').forEach(button => button.addEventListener('click', () => {
    if (!state.full || !state.view) return;
    if (button.dataset.span === 'all') { setView(...state.full); return; }
    const span = Number(button.dataset.span), center = state.cursor ?? (state.view[0] + state.view[1]) / 2; setView(center - span / 2, center + span / 2);
  }));
  el('position-slider').addEventListener('input', () => { if (!state.full || !state.view) return; const span = state.view[1] - state.view[0], from = state.full[0] + (state.full[1] - state.full[0] - span) * Number(el('position-slider').value) / 1000; setView(from, from + span); });
  el('events-near').addEventListener('change', () => { state.page = 0; renderEvents(); });
  el('events-prev').addEventListener('click', () => { state.page -= 1; renderEvents(); }); el('events-next').addEventListener('click', () => { state.page += 1; renderEvents(); });
  for (const key of SERIES) bindChart(el(`chart-${key}`));
  let dragDepth = 0;
  window.addEventListener('dragenter', event => { if (event.dataTransfer?.types.includes('Files')) { event.preventDefault(); dragDepth += 1; document.body.classList.add('drop-active'); } });
  window.addEventListener('dragover', event => { if (event.dataTransfer?.types.includes('Files')) event.preventDefault(); });
  window.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) document.body.classList.remove('drop-active'); });
  window.addEventListener('drop', event => { event.preventDefault(); dragDepth = 0; document.body.classList.remove('drop-active'); openFile(event.dataTransfer?.files[0]); });
  const resize = new ResizeObserver(() => { scheduleDraw(); const width = el('chart-price').clientWidth; if (Math.abs(width - state.width) >= 30) { state.width = width; if (state.data) queueData(); } });
  resize.observe(el('charts')); window.addEventListener('resize', scheduleDraw);
}

/**
 * 起動情報とURL指定を読み、既定リソースを開く。
 * @returns {Promise<void>} 初回表示準備の完了。引数なし。
 */
async function init() {
  bindUI(); scheduleDraw();
  const revision = state.sourceRevision;
  try {
    state.info = await api('/api/info'); const params = new URLSearchParams(location.search);
    if (revision !== state.sourceRevision) return;
    const path = params.get('catalog') || state.info.default_catalog || ''; el('catalog-path').value = path;
    for (const [key, id, allowed] of [['interval', 'interval', ['raw', '1', '5', '15']], ['price', 'price-field', ['last', 'mid', 'bid', 'ask']]]) {
      if (!params.has(key)) continue;
      if (!allowed.includes(params.get(key))) throw new Error(`URLの${key}が不正です`);
      el(id).value = params.get(key);
    }
    if (params.get('symbol') && params.get('session') && !params.get('catalog') && !params.get('resource') && !params.get('method')) { setMode('price'); el('symbol-input').value = params.get('symbol'); if (await loadSessions(params.get('session'))) await loadData(); }
    else if (path) await loadCatalog(path, null, params.get('resource') || '', {symbol: params.get('symbol') || '', session: params.get('session') || '', method: params.get('method') || ''});
    else setLoading(false, '一覧JSON又は価格セッションを選択してください');
  } catch (error) { showError(error.message); setLoading(false, '起動情報を取得できませんでした'); }
}

init();
