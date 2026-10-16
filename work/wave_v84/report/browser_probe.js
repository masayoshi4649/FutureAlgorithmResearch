/**
 * 機能: 順行と反転の全表示を、保存された別会計と照合する。
 * @returns {Object} 引数なし。返り値は操作と表示品質の検査件数。
 */
function independentVerify() {
  const data = window.reportTest.data, symbols = ['TOPIX', 'NK225'];
  const get = id => document.getElementById(id);
  const assert = (ok, label) => { if (!ok) throw Error(label); };
  const read = cell => Number(cell.textContent.replaceAll(',', '').replaceAll('円', '').replaceAll('−', '-').trim());
  const pct = value => value == null ? '—' : (100 * value).toFixed(1) + '%';
  let numbers = 0, colors = 0, views = 0, accounts = 0, filters = 0;
  const money = (cell, value, label) => {
    assert(Math.abs(read(cell) - value) < .501, label + ': ' + cell.textContent + '/' + value); numbers++;
    if (value < 0) {
      const mark = cell.matches('.loss') ? cell : cell.querySelector('.loss');
      assert(mark && getComputedStyle(mark).color === 'rgb(255, 147, 158)', '赤字色 ' + label); colors++;
    }
  };
  const sessions = (result, target) => {
    const rows = get(target).rows;
    assert(rows.length === 31 && rows[0].cells.length === 7, '全30場31行7列');
    data.sessions.forEach((session, i) => {
      assert(rows[i].dataset.session === session, '場順');
      symbols.forEach((symbol, s) => {
        const a = result.rows.find(r => r.session === session && r.symbol === symbol);
        [a.profit, -a.loss, a.net].forEach((v, j) => money(rows[i].cells[1 + s * 3 + j], v, '場損益')); accounts++;
      });
    });
    symbols.forEach((symbol, s) => ['profit', 'loss', 'net'].forEach((key, j) => {
      const total = result.rows.filter(r => r.symbol === symbol).reduce((sum, r) => sum + r[key], 0);
      assert(Math.abs(total - result.periods['対象'][symbol][key]) < 1e-6, '合計再加算');
      money(rows[30].cells[1 + s * 3 + j], key === 'loss' ? -total : total, '全場合計');
    }));
  };
  if (data.results) {
    assert(data.methods.length === 14 && data.sessions.length === 30, '固定14手法30場');
    const method = get('method-select'), model = get('model-select');
    assert(method.options.length === 14 && model.options.length === 2, '主選択肢');
    for (const m of data.methods) for (const mode of ['main', 'ideal']) {
      method.value = m.id; model.value = mode; model.dispatchEvent(new Event('change'));
      for (const field of ['entry', 'during', 'exit', 'condition']) assert(get(field + '-text').textContent === m[field], '条件同期');
      assert(get('model-description').textContent === data.model_descriptions[mode], '約定説明同期');
      const result = data.results[mode][m.id];
      sessions(result, 'session-results');
      const periods = get('period-results').rows; assert(periods.length === 6, '期間6行');
      ['前16', '後14', '対象'].forEach((period, p) => symbols.forEach((symbol, s) => {
        const a = result.periods[period][symbol], row = periods[p * 2 + s];
        [a.profit, -a.loss, a.net].forEach((v, j) => money(row.cells[j + 2], v, '期間損益'));
        assert(row.cells[5].textContent === pct(a.profit_share), '利益割合');
        assert(row.cells[6].textContent === (a.payoff == null ? '—' : a.payoff.toFixed(2) + '倍'), '平均勝負');
        assert(row.cells[7].textContent === `${a.winning_sessions}／${a.losing_sessions}／${a.no_trade_sessions}`, '勝敗休止'); numbers += 3;
      }));
      const cost = get('cost-results').rows; assert(cost.length === 2, '費用2行');
      symbols.forEach((symbol, s) => {
        const a = result.periods['対象'][symbol];
        [a.midpoint_gross, -a.spread_drag, -a.fees, a.net, -a.drawdown, a.worst_session, a.without_best_session].forEach((v, j) => money(cost[s].cells[j + 1], v, '費用分解'));
        assert(Math.abs(a.midpoint_gross - a.spread_drag - a.fees - a.net) < 1e-6, '同経路分解');
      });
      for (const kind of ['direction', 'turn']) {
        const rows = get(kind + '-comparison').rows, pairs = data.comparisons[kind];
        assert(rows.length === pairs.length * 2, '比較行数');
        pairs.forEach((pair, p) => symbols.forEach((symbol, s) => {
          const first = data.results[mode][pair.first].periods['対象'][symbol], second = data.results[mode][pair.second].periods['対象'][symbol];
          const cells = rows[p * 2 + s].cells, columns = kind === 'direction' ? [2, 3, 4] : [2, 4, 5];
          [first.net, second.net, second.net - first.net].forEach((v, j) => money(cells[columns[j]], v, '同幅比較'));
        }));
      }
      views++;
    }
    const overview = get('overview-results').rows, shown = data.methods.filter(m => m.overview);
    assert(overview.length === shown.length, '概要数');
    shown.forEach((m, i) => ['対象', '後14'].forEach((period, p) => symbols.forEach((symbol, s) => {
      money(overview[i].cells[2 + p * 2 + s], data.results.main[m.id].periods[period][symbol].net, '概要');
    })));
    for (const button of document.querySelectorAll('[data-method]')) { button.click(); assert(method.value === button.dataset.method, '概要から切替'); }
    const supplement = get('supplement-model-select');
    assert(supplement.options.length === 2 && data.supplement.method.id === 'F3_W64_V1', '追加参考');
    assert(!data.methods.some(m => m.id === 'F3_W64_V1'), '追加参考を主代表へ混入しない');
    for (const mode of ['main', 'ideal']) {
      supplement.value = mode; supplement.dispatchEvent(new Event('change'));
      const result = data.supplement.results[mode]; sessions(result, 'supplement-results');
      const rows = get('supplement-periods').rows; assert(rows.length === 6, '追加期間6行');
      ['前16', '後14', '対象'].forEach((period, p) => symbols.forEach((symbol, s) => {
        const a = result.periods[period][symbol], r = rows[p * 2 + s];
        [a.profit, -a.loss, a.net].forEach((v, j) => money(r.cells[j + 2], v, '追加期間'));
        assert(read(r.cells[5]) === a.trades && r.cells[6].textContent === pct(a.profit_share), '追加数と割合'); numbers += 2;
      })); views++;
    }
    method.value = data.methods[0].id; model.value = 'main'; model.dispatchEvent(new Event('change'));
    supplement.value = 'main'; supplement.dispatchEvent(new Event('change')); window.scrollTo(0, 0);
  } else {
    assert(data.rows.length === 108, '前半全108');
    const check = () => {
      const family = get('family-filter').value, query = get('query-filter').value.toUpperCase().trim(), sort = get('sort-select').value;
      const expected = data.rows.filter(r => (!family || String(r.config.family) === family) && (!query || r.config.id.toUpperCase().includes(query)));
      expected.sort((a, b) => sort === 'id' ? a.config.id.localeCompare(b.config.id, 'ja', {numeric: true}) : b.metrics[sort].net - a.metrics[sort].net || a.config.id.localeCompare(b.config.id));
      const rows = [...get('all-results').rows]; assert(rows.length === expected.length, '全条件件数');
      rows.forEach((r, i) => {
        const saved = expected[i]; assert(r.dataset.id === saved.config.id, '並べ替え');
        symbols.forEach((symbol, s) => {
          const a = saved.metrics[symbol];
          [a.cycle_profit, -a.cycle_loss, a.cycle_net].forEach((v, j) => money(r.cells[1 + s * 4 + j].querySelector('.number'), v, '全108損益'));
          assert(r.cells[4 + s * 4].textContent === pct(a.cycle_profit_share), '全108割合');
          assert(r.cells[3 + s * 4].querySelector('small').textContent === `${a.cycles}組`, '全108件数'); numbers += 2;
        });
      });
      assert(get('result-count').textContent.startsWith(expected.length + '／108'), '件数表示'); filters++;
    };
    check();
    for (const option of [...get('family-filter').options]) { get('family-filter').value = option.value; get('family-filter').dispatchEvent(new Event('change')); check(); }
    get('family-filter').value = '';
    for (const row of data.rows) { get('query-filter').value = row.config.id; get('query-filter').dispatchEvent(new Event('input')); check(); }
    get('query-filter').value = '存在しないID'; get('query-filter').dispatchEvent(new Event('input')); check(); get('query-filter').value = '';
    for (const option of [...get('sort-select').options]) { get('sort-select').value = option.value; get('sort-select').dispatchEvent(new Event('change')); check(); }
    get('sort-select').value = 'id'; get('sort-select').dispatchEvent(new Event('change')); views = 108;
  }
  for (const detail of document.querySelectorAll('details')) detail.open = true;
  assert(document.documentElement.scrollWidth <= innerWidth + 2, '文書横溢れ');
  for (const detail of document.querySelectorAll('details')) detail.open = false;
  assert(!/NaN|undefined|Infinity|__DATA__|__SCRIPT__/.test(document.body.innerText), '未定義表示');
  assert((window.browserErrors || []).length === 0, 'JS例外');
  assert(!document.querySelector('script[src],link[href],img[src]'), '外部資源');
  assert(getComputedStyle(document.body).backgroundColor === 'rgb(16, 21, 30)', 'ダークテーマ');
  return {全合格: true, 手法モデル切替数: views, 場商品表示数: accounts, 数値照合数: numbers, 赤字色照合数: colors,
    絞込並替照合数: filters, 文書幅: document.documentElement.scrollWidth, 画面幅: innerWidth, JS例外数: window.browserErrors.length};
}
try { document.body.dataset.check = JSON.stringify(independentVerify()); }
catch (e) { document.body.dataset.check = JSON.stringify({全合格: false, 理由: String(e), stack: e.stack}); }
