/**
 * 機能: 注文手法の全表示を独立照合し、切替・数値・赤字色・狭幅を確認する。
 * @returns {Object} 引数なし。返り値は検査件数と表示品質。
 */
function independentVerify() {
  const data = window.reportTest.data, symbols = ['TOPIX', 'NK225'];
  const assert = (ok, label) => { if (!ok) throw Error(label); };
  const get = id => document.getElementById(id);
  const read = cell => Number(cell.textContent.replaceAll(',', '').replaceAll('円', '').replaceAll('−', '-').trim());
  const percentage = value => value == null ? '—' : (100 * value).toFixed(1) + '%';
  let numbers = 0, colors = 0, views = 0, accounts = 0, filters = 0, modified = 0;
  const money = (cell, value, label) => {
    assert(Math.abs(read(cell) - value) < .501, label + ': ' + cell.textContent + ' / ' + value); numbers++;
    if (value < 0) {
      const element = cell.matches('.loss') ? cell : cell.querySelector('.loss');
      assert(element && getComputedStyle(element).color === 'rgb(255, 147, 158)', '赤字色 ' + label); colors++;
    }
  };
  const unit = (a, type) => type === 'cycle'
    ? {profit: a.cycle_profit, loss: a.cycle_loss, net: a.cycle_net, share: a.cycle_profit_share, count: a.cycles}
    : {profit: a.profit, loss: a.loss, net: a.net, share: a.profit_share, count: a.trades};
  const checkSessions = (result, type, target) => {
    const rows = get(target).rows;
    assert(rows.length === 31 && rows[0].cells.length === 7, '全30場31行7列 ' + target);
    data.sessions.forEach((session, i) => {
      assert(rows[i].dataset.session === session, '場順');
      symbols.forEach((symbol, s) => {
        const a = unit(result.rows.find(r => r.session === session && r.symbol === symbol), type);
        assert(Math.abs(a.profit - a.loss - a.net) < 1e-6, '保存会計');
        [a.profit, -a.loss, a.net].forEach((v, j) => money(rows[i].cells[1 + 3 * s + j], v, '場損益')); accounts++;
      });
    });
    symbols.forEach((symbol, s) => {
      const a = unit(result.periods['対象'][symbol], type);
      ['profit', 'loss', 'net'].forEach((key, j) => {
        const total = result.rows.filter(r => r.symbol === symbol).reduce((sum, r) => sum + unit(r, type)[key], 0);
        assert(Math.abs(total - a[key]) < 1e-6, '合計再加算');
        money(rows[30].cells[1 + 3 * s + j], key === 'loss' ? -total : total, '合計');
      });
    });
  };
  if (data.final) {
    assert([2, 12].includes(data.methods.length) && data.sessions.length === 30, '主2又は家族12・全30場');
    const method = get('method-select'), type = get('unit-select');
    assert(method.options.length === data.methods.length && type.options.length === 2 && type.value === 'cycle', '選択肢と初期会計');
    for (const m of data.methods) for (const u of ['cycle', 'leg']) {
      method.value = m.id; type.value = u; method.dispatchEvent(new Event('change'));
      const result = data.final['0'][m.id];
      for (const field of ['entry', 'during', 'exit', 'execution']) assert(get(field + '-text').textContent === m[field], '説明同期 ' + field);
      assert(get('size-description').textContent === m.allocation, '枚数説明同期');
      checkSessions(result, u, 'session-results');
      const periods = get('period-results').rows; assert(periods.length === 6, '期間6行');
      ['前16', '後14', '対象'].forEach((period, p) => symbols.forEach((symbol, s) => {
        const base = result.periods[period][symbol], a = unit(base, u), row = periods[p * 2 + s];
        [a.profit, -a.loss, a.net].forEach((v, j) => money(row.cells[j + 2], v, '期間損益'));
        assert(row.cells[5].textContent === percentage(a.share), '期間割合');
        assert(row.cells[6].textContent === `${base.winning_sessions}／${base.losing_sessions}／${base.no_trade_sessions}`, '勝敗休止'); numbers += 2;
      }));
      const inventories = get('inventory-results').rows, groups = get('group-results').rows, logical = get('logical-results').rows;
      assert(inventories.length === 2 && groups.length === 4 && logical.length === 2, '在庫・会計・費用表');
      symbols.forEach((symbol, s) => {
        const a = result.periods['対象'][symbol], row = inventories[s];
        [a.gross, -a.fees, a.net].forEach((v, j) => money(row.cells[j + 1], v, '在庫収支'));
        assert(row.cells[4].textContent === `${a.max_long}／${a.max_short}`, '片方向玉');
        assert(row.cells[5].textContent === `${a.max_gross}／${a.max_net}`, '総玉と差引');
        [-a.drawdown, a.worst_session, a.without_best_session].forEach((v, j) => money(row.cells[j + 6], v, '安定性'));
        ['cycle', 'leg'].forEach((v, n) => {
          const b = unit(a, v), r = groups[s * 2 + n];
          [b.profit, -b.loss, b.net].forEach((x, j) => money(r.cells[j + 2], x, '親組と脚'));
          assert(r.cells[5].textContent === percentage(b.share) && read(r.cells[6]) === b.count, '親組と脚割合・件数'); numbers += 2;
        });
        const decomposition = [data.ideal[m.id].periods['対象'][symbol].net];
        if (data.ideal_fee) decomposition.push(data.ideal_fee[m.id].periods['対象'][symbol].net);
        decomposition.push(a.midpoint_gross, -a.spread_drag, -a.fees, a.net);
        assert(logical[s].cells.length === decomposition.length + 1, '費用分解列数');
        decomposition.forEach((v, j) => money(logical[s].cells[j + 1], v, '別再生と同経路分解'));
        assert(Math.abs(a.midpoint_gross - a.spread_drag - a.fees - a.net) < 1e-6, '中値分解恒等式');
      }); views++;
    }
    const overview = get('overview-results').rows;
    assert(overview.length === data.methods.length, '概要数');
    data.methods.forEach((m, i) => symbols.forEach((symbol, s) => {
      const a = data.final['0'][m.id].periods['対象'][symbol];
      money(overview[i].cells[2 + s].querySelector('.number'), a.net, '概要収支');
      assert(overview[i].cells[2 + s].querySelector('small').textContent === '親組 ' + percentage(a.cycle_profit_share), '概要割合');
      money(overview[i].cells[4 + s], data.final['0'][m.id].periods['後14'][symbol].net, '概要後半');
    }));
    for (const button of document.querySelectorAll('[data-method]')) {
      button.click(); assert(method.value === button.dataset.method, '概要から切替');
    }
    const seeds = get('seed-results').rows, randomness = get('randomness-results').rows;
    assert(seeds.length === 20 && randomness.length === 2, '乱数20種');
    data.sensitivity.rows.forEach((r, i) => {
      assert(read(seeds[i].cells[0]) === r.seed, '乱数種順');
      symbols.forEach((symbol, s) => money(seeds[i].cells[s + 1], r.metrics[symbol].net, '乱数別収支'));
    });
    symbols.forEach((symbol, s) => {
      const a = data.sensitivity.symbols[symbol], r = randomness[s];
      [a.mean_net, a.median_net, a.worst_net, a.best_net].forEach((v, j) => money(r.cells[j + 1], v, '乱数要約'));
      assert(r.cells[5].textContent === `${a.profitable_seeds}／20`, '乱数黒字数');
    });
    if (data.persistent) {
      const rows = get('persistent-comparison').rows, select = get('persistent-select');
      assert(data.persistent.length === 3 && rows.length === 6 && select.options.length === 3, '改修固定3条件');
      data.persistent.forEach((r, i) => {
        symbols.forEach((symbol, s) => ['original', 'result'].forEach((kind, k) => {
          const a = r[kind].periods['対象'][symbol];
          [a.cycle_profit, -a.cycle_loss, a.net].forEach((v, j) => money(rows[i * 2 + s].cells[2 + 3 * k + j], v, '指値維持の比較'));
        }));
        select.value = r.parent_id; select.dispatchEvent(new Event('change'));
        checkSessions(r.result, 'cycle', 'persistent-results'); modified++;
      });
      select.value = data.persistent[0].parent_id; select.dispatchEvent(new Event('change'));
    }
    method.value = data.methods[0].id; type.value = 'cycle'; method.dispatchEvent(new Event('change')); window.scrollTo(0, 0);
  } else {
    assert(data.rows.length === 288, '全288条件');
    const check = () => {
      const family = get('family-filter').value, query = get('query-filter').value.toUpperCase().trim(), sort = get('sort-select').value;
      const expected = data.rows.filter(r => (!family || String(r.config.family) === family) && (!query || r.config.id.toUpperCase().includes(query)));
      expected.sort((a, b) => sort === 'id' ? a.config.id.localeCompare(b.config.id, 'ja', {numeric: true}) : b.metrics[sort].net - a.metrics[sort].net || a.config.id.localeCompare(b.config.id));
      const rows = [...get('all-results').rows]; assert(rows.length === expected.length, '全条件件数');
      rows.forEach((r, i) => {
        const saved = expected[i]; assert(r.dataset.id === saved.config.id, '表示順');
        symbols.forEach((symbol, s) => {
          const a = saved.metrics[symbol];
          [a.cycle_profit, -a.cycle_loss, a.cycle_net].forEach((v, j) => money(r.cells[1 + s * 4 + j].querySelector('.number'), v, '全条件損益'));
          assert(r.cells[4 + s * 4].textContent === percentage(a.cycle_profit_share), '全条件割合');
          assert(r.cells[3 + s * 4].querySelector('small').textContent === `${a.cycles}組`, '全条件組数'); numbers += 2;
        });
      });
      assert(get('result-count').textContent.startsWith(expected.length + '／288'), '件数表示'); filters++;
    };
    check();
    for (const option of [...get('family-filter').options]) { get('family-filter').value = option.value; get('family-filter').dispatchEvent(new Event('change')); check(); }
    get('family-filter').value = '';
    for (const r of data.rows) { get('query-filter').value = r.config.id; get('query-filter').dispatchEvent(new Event('input')); check(); }
    get('query-filter').value = '該当しないID'; get('query-filter').dispatchEvent(new Event('input')); check(); get('query-filter').value = '';
    for (const option of [...get('sort-select').options]) { get('sort-select').value = option.value; get('sort-select').dispatchEvent(new Event('change')); check(); }
    get('sort-select').value = 'id'; get('sort-select').dispatchEvent(new Event('change')); views = 288;
  }
  for (const detail of document.querySelectorAll('details')) detail.open = true;
  assert(document.documentElement.scrollWidth <= innerWidth + 2, '文書横溢れ');
  for (const detail of document.querySelectorAll('details')) detail.open = false;
  assert(!/NaN|undefined|Infinity|__DATA__|__SCRIPT__/.test(document.body.innerText), '未定義表示');
  assert(!document.querySelector('script[src],link[href],img[src]'), '外部資源');
  assert((window.browserErrors || []).length === 0, 'JS例外');
  assert(getComputedStyle(document.body).backgroundColor === 'rgb(16, 21, 30)', 'ダークテーマ');
  return {全合格: true, 手法会計切替数: views, 場商品表示数: accounts, 改修切替数: modified, 数値照合数: numbers, 赤字色照合数: colors,
    絞込並替照合数: filters, 文書幅: document.documentElement.scrollWidth, 画面幅: innerWidth, JS例外数: window.browserErrors.length};
}
try { document.body.dataset.check = JSON.stringify(independentVerify()); }
catch (e) { document.body.dataset.check = JSON.stringify({全合格: false, 理由: String(e), stack: e.stack}); }
