/**
 * 機能: 保存会計と実ブラウザの切替・数値・色・狭幅表示を独立照合する。
 * @returns {Object} 引数なし。返り値は検査件数と表示品質。
 */
function independentVerify() {
  const test = window.reportTest, data = test.data;
  const assert = (value, message) => { if (!value) throw Error(message); };
  const read = cell => Number(cell.textContent.replaceAll(',', '').replaceAll('円', '').replaceAll('%', '').replaceAll('倍', '').replaceAll('−', '-').trim());
  const close = (cell, value, label, digits = 0) => {
    if (value == null) { assert(cell.textContent.trim() === '—', label + 'の欠測'); return; }
    assert(Math.abs(read(cell) - value) <= 0.501 * 10 ** (-digits), label + ': ' + cell.textContent + '/' + value);
  };
  const time = value => value == null ? '—' : value < 60 ? Number(value.toFixed(1)) + '秒' : value < 3600 ? Number((value / 60).toFixed(1)) + '分' : Number((value / 3600).toFixed(2)) + '時間';
  let numeric = 0, colors = 0, views = 0, accounts = 0, filters = 0;
  const number = (cell, value, label) => {
    close(cell, value, label); numeric++;
    if (value < 0) {
      const target = cell.matches('.loss') ? cell : cell.querySelector('.loss');
      assert(target && getComputedStyle(target).color === 'rgb(255, 147, 158)', '負値赤色 ' + label); colors++;
    }
  };

  // ----------------------------------------
  if (data.final) {
    assert(data.methods.length === 9 && data.sessions.length === 30, '9手法・30場');
    const method = document.getElementById('method-select'), delay = document.getElementById('delay-select');
    assert(method.options.length === 9 && delay.options.length === 3, '選択肢数');
    for (const m of data.methods) for (const wait of [0, 1, 5]) {
      method.value = m.id; delay.value = String(wait); method.dispatchEvent(new Event('change'));
      for (const field of ['entry', 'during', 'exit', 'execution']) assert(document.getElementById(field + '-text').textContent === m[field], '条件説明同期 ' + field);
      const result = data.final[String(wait)][m.id], rows = document.getElementById('session-results').rows;
      assert(rows.length === 31, '30場・合計1行');
      data.sessions.forEach((session, i) => {
        assert(rows[i].dataset.session === session, '場順');
        ['TOPIX', 'NK225'].forEach((symbol, s) => {
          const a = result.rows.find(r => r.session === session && r.symbol === symbol);
          assert(a && a.net === a.profit - a.loss, '各場会計');
          [a.profit, -a.loss, a.net].forEach((value, j) => number(rows[i].cells[1 + s * 3 + j], value, m.id + '/' + symbol)); accounts++;
        });
      });
      ['TOPIX', 'NK225'].forEach((symbol, s) => ['profit', 'loss', 'net'].forEach((key, j) => {
        const total = result.rows.filter(r => r.symbol === symbol).reduce((sum, r) => sum + r[key], 0);
        assert(total === result.periods['対象'][symbol][key], '合計の会計一致');
        number(rows[30].cells[1 + s * 3 + j], key === 'loss' ? -total : total, '合計');
      }));
      const periods = document.getElementById('period-results').rows;
      assert(periods.length === 6, '前半後半全体の各商品');
      ['前16', '後14', '対象'].forEach((period, p) => ['TOPIX', 'NK225'].forEach((symbol, s) => {
        const a = result.periods[period][symbol], r = periods[p * 2 + s];
        [a.profit, -a.loss, a.net].forEach((value, j) => number(r.cells[2 + j], value, '期間損益'));
        close(r.cells[5], a.profit_share == null ? null : 100 * a.profit_share, '金額割合', 1);
        close(r.cells[6], a.trades, '組数'); close(r.cells[7], a.payoff, '平均勝負', 2); numeric += 3;
        assert(r.cells[8].textContent === `${a.winning_sessions}／${a.losing_sessions}／${a.no_trade_sessions}`, '勝敗場');
      }));
      const holds = document.getElementById('holding-results').rows, bins = document.getElementById('holding-bins').rows;
      assert(holds.length === 2 && bins.length === 2, '保有時間2商品');
      ['TOPIX', 'NK225'].forEach((symbol, s) => {
        const a = result.periods['対象'][symbol], r = holds[s];
        ['average_hold_seconds', 'hold_median', 'hold_p95', 'hold_max'].forEach((key, j) => { assert(r.cells[j + 1].textContent === time(a[key]), '保有実績 ' + key); numeric++; });
        assert(r.cells[5].textContent === a.trades + '組', '保有組数');
        assert(a.hold_bins.reduce((sum, n) => sum + n, 0) === a.trades, '保有区分合計');
        a.hold_bins.forEach((n, j) => { assert(bins[s].cells[j + 1].childNodes[0].textContent === n + '組', '保有区分'); numeric++; });
      });
      views++;
    }
    const main = [...new Set([...data.initial, ...data.repaired])];
    const latency = document.getElementById('latency-results').rows, overview = document.getElementById('overview-results').rows;
    assert(latency.length === 12 && overview.length === 6, '主代表6');
    main.forEach((id, i) => {
      ['TOPIX', 'NK225'].forEach((symbol, s) => {
        number(overview[i].cells[1 + s].querySelector('.number'), data.final[5][id].periods['対象'][symbol].net, '全体一覧');
        number(overview[i].cells[3 + s], data.final[5][id].periods['後14'][symbol].net, '後半一覧');
        [0, 1, 5].forEach((wait, j) => number(latency[i * 2 + s].cells[2 + j], data.final[wait][id].periods['対象'][symbol].net, '遅延比較'));
      });
    });
    const changes = document.getElementById('change-results').rows; assert(changes.length === 6, '改修6行');
    for (let i = 0; i < 3; i++) ['TOPIX', 'NK225'].forEach((symbol, s) => {
      const a = data.final[5][data.initial[i]].periods['対象'][symbol], b = data.final[5][data.repaired[i]].periods['対象'][symbol], r = changes[2 * i + s];
      number(r.cells[2], a.loss - b.loss, '損失削減'); close(r.cells[3], a.profit - b.profit, '失った利益'); numeric++;
      number(r.cells[4], b.net - a.net, '収支改善');
      const averages = r.cells[5].querySelectorAll('.number'); assert(averages.length === 2, '一組平均前後');
      number(averages[0], a.average_net, '旧一組平均'); number(averages[1], b.average_net, '新一組平均');
      assert(r.cells[6].textContent === `${a.trades} → ${b.trades}`, '取引数前後');
    });
    const strict = document.getElementById('strict-results').rows; assert(strict.length === 3, '鮮度3代表');
    Object.entries(data.strict).forEach(([id, result], i) => ['TOPIX', 'NK225'].forEach((symbol, s) => {
      number(strict[i].cells[1 + s].querySelector('.number'), result[symbol].net, '厳格鮮度');
      assert(strict[i].cells[1 + s].querySelector('small').textContent === result[symbol].trades + '組', '厳格鮮度組数');
    }));
    for (const button of document.querySelectorAll('[data-method]')) { button.click(); assert(method.value === button.dataset.method && delay.value === '5', '概要から選択'); }
    method.value = data.repaired[0]; delay.value = '5'; method.dispatchEvent(new Event('change')); window.scrollTo(0, 0);
  } else {
    assert(data.rows.length === 188 && data.count === 188, '全188条件');
    const input = id => document.getElementById(id);
    const checkRows = () => {
      const stage = input('stage-filter').value, family = input('family-filter').value, mode = input('mode-filter').value;
      const query = input('query-filter').value.toUpperCase().trim(), sort = input('sort-select').value;
      const expected = data.rows.filter(r => (!stage || r.stage === stage) && (!family || (family === 'solo' ? Boolean(r.config.solo) : !r.config.solo && r.description.entry_model.id.startsWith(family))) && (mode === '' || String(r.config.entry_mode) === mode) && (!query || r.config.id.toUpperCase().includes(query)));
      expected.sort((a, b) => sort === 'id' ? (a.stage === b.stage ? a.config.id.localeCompare(b.config.id, 'ja', {numeric: true}) : a.stage === '初回' ? -1 : 1) : b.metrics[sort].net - a.metrics[sort].net || a.config.id.localeCompare(b.config.id));
      const rows = [...input('all-results').rows]; assert(rows.length === expected.length, '絞込件数');
      rows.forEach((r, i) => {
        const saved = expected[i]; assert(r.dataset.id === saved.config.id, '絞込順序');
        ['TOPIX', 'NK225'].forEach((symbol, s) => {
          const a = saved.metrics[symbol]; [a.profit, -a.loss, a.net].forEach((v, j) => number(r.cells[1 + s * 5 + j], v, '全条件損益'));
          const pct = r.cells[4 + s * 5]; assert(pct.childNodes[0].textContent === (a.profit_share == null ? '—' : (a.profit_share * 100).toFixed(1) + '%'), '全条件金額割合');
          assert(pct.querySelector('small').textContent === a.trades + '組', '全条件組数');
          assert(r.cells[5 + s * 5].textContent === time(a.hold_median), '全条件保有中央値'); numeric += 3;
        });
      });
      assert(input('result-count').textContent.startsWith(expected.length + '／188'), '絞込件数表示'); filters++;
    };
    checkRows();
    for (const stage of [...input('stage-filter').options]) for (const family of [...input('family-filter').options]) for (const mode of [...input('mode-filter').options]) {
      input('stage-filter').value = stage.value; input('family-filter').value = family.value; input('mode-filter').value = mode.value;
      input('mode-filter').dispatchEvent(new Event('change')); checkRows();
    }
    for (const id of ['stage-filter', 'family-filter', 'mode-filter']) input(id).value = '';
    for (const row of data.rows) { input('query-filter').value = row.config.id; input('query-filter').dispatchEvent(new Event('input')); checkRows(); }
    input('query-filter').value = '存在しないID'; input('query-filter').dispatchEvent(new Event('input')); checkRows();
    input('query-filter').value = '';
    for (const sort of ['TOPIX', 'NK225', 'id']) { input('sort-select').value = sort; input('sort-select').dispatchEvent(new Event('change')); checkRows(); }
    views = 188; accounts = 376;
  }
  // ----------------------------------------
  for (const detail of document.querySelectorAll('details')) detail.open = true;
  assert(document.documentElement.scrollWidth <= innerWidth + 2, '詳細全展開時の文書横溢れ ' + document.documentElement.scrollWidth + '/' + innerWidth);
  for (const detail of document.querySelectorAll('details')) detail.open = false;
  assert(!/NaN|undefined|Infinity|__DATA__|__SCRIPT__/.test(document.body.innerText), '未定義表示');
  assert(!document.querySelector('script[src],link[href],img[src]'), '外部資源');
  assert((window.browserErrors || []).length === 0, 'JS例外 ' + JSON.stringify(window.browserErrors));
  assert(getComputedStyle(document.body).backgroundColor === 'rgb(16, 21, 30)', 'ダークテーマ');
  return {全合格: true, 手法遅延切替数: views, 場商品数: accounts, 数値照合数: numeric, 赤字色照合数: colors,
    絞込並替照合数: filters, 文書幅: document.documentElement.scrollWidth, 画面幅: innerWidth,
    背景: getComputedStyle(document.body).backgroundColor, JS例外数: window.browserErrors.length};
}
try { document.body.dataset.check = JSON.stringify(independentVerify()); }
catch (error) { document.body.dataset.check = JSON.stringify({全合格: false, 理由: String(error), stack: error.stack}); }
