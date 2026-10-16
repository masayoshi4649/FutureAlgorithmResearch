/**
 * 機能: 元・反転の全表示を保存会計と独立照合し、操作と表示品質を検査する。
 * @returns {Object} 引数なし。返り値は検査結果と件数。
 */
function independentVerify() {
  const data = window.reportTest.data;
  const assert = (v, text) => { if (!v) throw Error(text); };
  const read = cell => Number(cell.textContent.replaceAll(',', '').replaceAll('円', '').replaceAll('%', '').replaceAll('−', '-').trim());
  let numbers = 0, colors = 0, views = 0, accounts = 0, filters = 0;
  const money = (cell, value, label) => {
    assert(Math.abs(read(cell) - value) < .501, label + ': ' + cell.textContent + '/' + value); numbers++;
    if (value < 0) {
      const marked = cell.matches('.loss') ? cell : cell.querySelector('.loss');
      assert(marked && getComputedStyle(marked).color === 'rgb(255, 147, 158)', '赤字色 ' + label); colors++;
    }
  };
  const counts = a => `${a.winning_sessions}／${a.losing_sessions}／${a.no_trade_sessions}`;
  const percent = value => value == null ? '—' : (value * 100).toFixed(1) + '%';
  if (data.final) {
    assert(data.pairs.length === 3 && data.sessions.length === 30, '3枠・30場');
    const pairInput = document.getElementById('pair-select'), delayInput = document.getElementById('delay-select');
    assert(pairInput.options.length === 3 && delayInput.options.length === 3, '選択肢数');
    for (const pair of data.pairs) for (const delay of [0, 1, 5]) {
      pairInput.value = pair.label; delayInput.value = String(delay); pairInput.dispatchEvent(new Event('change'));
      for (const field of ['entry', 'during', 'exit', 'execution']) assert(document.getElementById(field + '-text').textContent === pair.description[field], '条件同期 ' + field);
      const rows = document.getElementById('session-results').rows;
      assert(rows.length === 31 && rows[0].cells.length === 13, '全30場の元逆両商品13列');
      data.sessions.forEach((session, i) => {
        assert(rows[i].dataset.session === session, '場順');
        ['TOPIX', 'NK225'].forEach((symbol, s) => ['original', 'reverse'].forEach((variant, v) => {
          const result = data.final[delay][pair[variant].id], a = result.rows.find(r => r.session === session && r.symbol === symbol);
          assert(a && a.net === a.profit - a.loss, '元逆の保存会計');
          [a.profit, -a.loss, a.net].forEach((value, j) => money(rows[i].cells[1 + s * 6 + v * 3 + j], value, '場損益')); accounts++;
        }));
      });
      ['TOPIX', 'NK225'].forEach((symbol, s) => ['original', 'reverse'].forEach((variant, v) => {
        const result = data.final[delay][pair[variant].id];
        ['profit', 'loss', 'net'].forEach((key, j) => {
          const sum = result.rows.filter(r => r.symbol === symbol).reduce((a, r) => a + r[key], 0);
          assert(sum === result.periods['対象'][symbol][key], '合計加算');
          money(rows[30].cells[1 + s * 6 + v * 3 + j], key === 'loss' ? -sum : sum, '合計');
        });
      }));
      const periods = document.getElementById('period-results').rows; assert(periods.length === 12, '期間12行');
      ['前16', '後14', '対象'].forEach((period, p) => ['TOPIX', 'NK225'].forEach((symbol, s) => ['original', 'reverse'].forEach((variant, v) => {
        const a = data.final[delay][pair[variant].id].periods[period][symbol], row = periods[p * 4 + s * 2 + v];
        assert(row.cells[2].textContent === (v ? '反転' : '元'), '期間向き');
        [a.profit, -a.loss, a.net].forEach((value, j) => money(row.cells[j + 3], value, '期間'));
        assert(row.cells[6].textContent === percent(a.profit_share), '期間金額割合');
        assert(read(row.cells[7]) === a.trades && row.cells[8].textContent === counts(a), '期間組数と場数'); numbers += 3;
      })));
      const regime = document.getElementById('regime-results').rows;
      assert(regime.length === 6, '相場分類6行');
      data.regimes[pair.label].forEach((a, i) => {
        assert(regime[i].cells[0].textContent === a.regime && read(regime[i].cells[2]) === a.sessions, '分類と場数');
        money(regime[i].cells[3], a.original.net, '分類元'); money(regime[i].cells[4], a.reverse.net, '分類逆');
        assert(regime[i].cells[5].textContent === counts(a.reverse), '分類勝敗');
      });
      views++;
    }
    const overview = document.getElementById('overview-results').rows, latency = document.getElementById('latency-results').rows, stability = document.getElementById('stability-results').rows;
    assert(overview.length === 3 && latency.length === 6 && stability.length === 6, '概要・遅延・安定性の行数');
    const costs = document.getElementById('cost-results').rows; assert(costs.length === 6, '費用分解6行');
    data.pairs.forEach((pair, i) => ['TOPIX', 'NK225'].forEach((symbol, s) => {
      ['original', 'reverse'].forEach((variant, v) => money(overview[i].cells[1 + s * 2 + v].querySelector('.number'), data.final[5][pair[variant].id].periods['対象'][symbol].net, '概要収支'));
      ['original', 'reverse'].forEach((variant, v) => {
        const a = data.final[5][pair[variant].id].periods['対象'][symbol];
        [a.gross + a.spread_drag, -(a.spread_drag + a.fees), a.net].forEach((value, j) => money(costs[i * 2 + s].cells[2 + v * 3 + j], value, '中値と費用の分解'));
      });
      [0, 1, 5].forEach((delay, j) => money(latency[i * 2 + s].cells[j + 2], data.final[delay][pair.reverse.id].periods['対象'][symbol].net, '逆遅延収支'));
      const a = data.final[5][pair.reverse.id].periods['対象'][symbol], b = data.strict[pair.reverse.id][symbol], r = stability[i * 2 + s];
      [a.net, a.without_best_session, a.worst_session].forEach((value, j) => money(r.cells[j + 2], value, '安定性'));
      money(r.cells[5].querySelector('.number'), b.net, '鮮度3秒'); assert(r.cells[5].querySelector('small').textContent === b.trades + '組', '鮮度3秒組数');
    }));
    for (const button of document.querySelectorAll('[data-pair]')) { button.click(); assert(pairInput.value === button.dataset.pair && delayInput.value === '5', '概要から切替'); }
    pairInput.value = 'C'; delayInput.value = '5'; pairInput.dispatchEvent(new Event('change')); window.scrollTo(0, 0);
  } else {
    assert(data.rows.length === 188, '全188');
    const get = id => document.getElementById(id);
    const check = () => {
      const family = get('family-filter').value, mode = get('mode-filter').value, query = get('query-filter').value.toUpperCase().trim(), sort = get('sort-select').value;
      const expected = data.rows.filter(r => (!family || (family === 'solo' ? Boolean(r.config.solo) : !r.config.solo && r.parent_id.startsWith(family))) && (mode === '' || String(r.config.entry_mode) === mode) && (!query || r.parent_id.toUpperCase().includes(query)));
      expected.sort((a, b) => { if (sort === 'id') return a.parent_id.localeCompare(b.parent_id, 'ja', {numeric: true}); const [v, s] = sort.split('|'); return b[v][s].net - a[v][s].net || a.parent_id.localeCompare(b.parent_id); });
      const rows = [...get('all-results').rows]; assert(rows.length === expected.length, '絞込件数');
      rows.forEach((r, i) => {
        const saved = expected[i]; assert(r.dataset.id === saved.parent_id, '絞込並べ替え順');
        ['TOPIX', 'NK225'].forEach((symbol, s) => ['original', 'reverse'].forEach((variant, v) => {
          const a = saved[variant][symbol];
          [a.profit, -a.loss, a.net].forEach((value, j) => money(r.cells[1 + s * 6 + v * 3 + j].querySelector('.number'), value, '全条件元逆'));
          assert(r.cells[3 + s * 6 + v * 3].querySelector('small').textContent === percent(a.profit_share) + '／' + a.trades + '組', '全条件金額割合・組数'); numbers += 2;
        }));
      });
      assert(get('result-count').textContent.startsWith(expected.length + '／188'), '全条件件数表示'); filters++;
    };
    check();
    for (const family of [...get('family-filter').options]) for (const mode of [...get('mode-filter').options]) {
      get('family-filter').value = family.value; get('mode-filter').value = mode.value; get('mode-filter').dispatchEvent(new Event('change')); check();
    }
    get('family-filter').value = ''; get('mode-filter').value = '';
    for (const row of data.rows) { get('query-filter').value = row.parent_id; get('query-filter').dispatchEvent(new Event('input')); check(); }
    get('query-filter').value = '存在しないID'; get('query-filter').dispatchEvent(new Event('input')); check(); get('query-filter').value = '';
    for (const option of [...get('sort-select').options]) { get('sort-select').value = option.value; get('sort-select').dispatchEvent(new Event('change')); check(); }
    get('sort-select').value = 'id'; get('sort-select').dispatchEvent(new Event('change'));
    views = 188; accounts = 752;
  }
  for (const e of document.querySelectorAll('details')) e.open = true;
  assert(document.documentElement.scrollWidth <= innerWidth + 2, '文書横溢れ');
  for (const e of document.querySelectorAll('details')) e.open = false;
  assert(!/NaN|undefined|Infinity|__DATA__|__SCRIPT__/.test(document.body.innerText), '未定義表示');
  assert(!document.querySelector('script[src],link[href],img[src]'), '外部資源');
  assert((window.browserErrors || []).length === 0, 'JS例外');
  assert(getComputedStyle(document.body).backgroundColor === 'rgb(16, 21, 30)', 'ダークテーマ');
  return {全合格: true, 組遅延切替数: views, 場商品元逆数: accounts, 数値照合数: numbers, 赤字色照合数: colors,
    絞込並替照合数: filters, 文書幅: document.documentElement.scrollWidth, 画面幅: innerWidth, JS例外数: window.browserErrors.length};
}
try { document.body.dataset.check = JSON.stringify(independentVerify()); }
catch (e) { document.body.dataset.check = JSON.stringify({全合格: false, 理由: String(e), stack: e.stack}); }
