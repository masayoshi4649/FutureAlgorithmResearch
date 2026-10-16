/**
 * 機能: E01の全条件・会計単位・約定仮定を切り替え、保存会計と表示を独立照合する。
 * 引数: なし。
 * @returns {Object} 数値・操作・表示品質の確認件数。
 */
function independentVerify() {
  const data = JSON.parse(document.getElementById('report-data').textContent);
  const symbols = ['TOPIX', 'NK225'], periods = ['前16', '後14', '全30'];
  const get = id => document.getElementById(id);
  const assert = (ok, label) => { if (!ok) throw Error(label); };
  const number = node => Number(node.textContent.replaceAll(',', '').replaceAll('円', '').replaceAll('−', '-').trim());
  const pct = value => value == null ? '—' : (value * 100).toFixed(1) + '%';
  const selected = (row, cycle) => cycle ? [row.cycle_profit, row.cycle_loss, row.cycle_profit_share, row.cycle_payoff, row.cycles, row.cycle_wins, row.cycle_losses] : [row.profit, row.loss, row.profit_share, row.payoff, row.trades, row.wins, row.losses];
  let numbers = 0, colors = 0, views = 0, accounts = 0, operations = 0;
  const money = (cell, value, label) => {
    const node = cell.matches('.number') ? cell : cell.querySelector('.number');
    assert(node, '金額要素 ' + label);
    if (value == null) assert(node.textContent === '—', '未定義金額 ' + label);
    else assert(Math.abs(number(node) - value) <= .501, label + ' ' + node.textContent + '/' + value);
    numbers++;
    if (value < 0) {
      assert(node.classList.contains('loss') && getComputedStyle(node).color === 'rgb(255, 147, 158)', '赤字色 ' + label); colors++;
    }
  };
  const change = (id, value) => { get(id).value = value; get(id).dispatchEvent(new Event('change')); operations++; };
  const tableSessions = (result, cycle) => {
    const rows = get('session-results').rows;
    assert(rows.length === 31 && rows[0].cells.length === 7, '全30場31行7列');
    [...data.fixed['全30'], null].forEach((session, i) => {
      assert(rows[i].cells[0].textContent === (session ? session.replace('_Day', ' デイ').replace('_Night', ' ナイト') : '全30場 合計'), '場順');
      symbols.forEach((symbol, s) => {
        const a = session ? result.rows.find(r => r.session === session && r.symbol === symbol) : result.periods['全30'][symbol];
        const v = selected(a, cycle);
        [v[0], -v[1], a.net].forEach((x, j) => money(rows[i].cells[1 + s * 3 + j], x, '場金額'));
        const sub = [rows[i].cells[1 + s * 3], rows[i].cells[2 + s * 3], rows[i].cells[3 + s * 3]].map(c => c.querySelector('small').textContent);
        const expected = cycle ? [v[5] + '組', v[6] + '組', `新規${a.new_lots}／返済${a.exit_lots}枚`] : [a.winning_lots + '枚', a.losing_lots + '枚', new Intl.NumberFormat('ja-JP', {maximumFractionDigits: 0}).format(a.winning_lots - a.losing_lots) + '枚'];
        assert(JSON.stringify(sub) === JSON.stringify(expected), '場枚数・組数'); numbers += 3;
        if (session) accounts++;
      });
    });
  };
  assert(data.fixed.catalog.length === 25 && data.fixed['全30'].length === 30, '固定25条件30場');
  if (get('method-select')) {
    assert(get('method-select').options.length === 25 && get('account-select').options.length === 2, '主選択肢');
    for (const config of data.fixed.catalog) for (const model of ['observed', 'specified']) for (const unit of ['cycle', 'leg']) {
      change('method-select', config.id); change('model-select', model); change('account-select', unit);
      const cycle = unit === 'cycle', result = data.results[model][config.id], baseline = data.results[model].E01;
      for (const field of ['entry', 'during', 'exit', 'restart']) assert(get(field + '-description').textContent === data.descriptions[config.id][field], '説明同期');
      tableSessions(result, cycle);
      const primary = get('primary-results').rows;
      assert(primary.length === 6, '主3両市場6行');
      data.fixed.primary.forEach((id, p) => symbols.forEach((symbol, s) => {
        const a = data.results[model][id].periods['全30'][symbol], v = selected(a, cycle), cells = primary[p * 2 + s].cells;
        assert(cells[0].querySelector('button').dataset.method === id, '主代表不変');
        [v[0], -v[1], a.net].forEach((x, j) => money(cells[2 + j], x, '主3金額'));
        assert(cells[5].textContent === pct(v[2]), '主3割合');
        assert(cells[6].textContent === (v[3] == null ? '—' : v[3].toFixed(2) + '倍'), '主3平均勝負');
        assert(cells[7].textContent === `${a.positive_sessions} / 30` && number(cells[8]) === v[4], '主3勝場と件数'); numbers += 4;
      }));
      const periodRows = get('period-results').rows, differences = get('change-results').rows;
      assert(periodRows.length === 6 && differences.length === 6, '期間・差6行');
      periods.forEach((period, p) => symbols.forEach((symbol, s) => {
        const a = result.periods[period][symbol], b = baseline.periods[period][symbol], av = selected(a, cycle), bv = selected(b, cycle);
        const cells = periodRows[p * 2 + s].cells, dc = differences[p * 2 + s].cells;
        [av[0], -av[1], a.net].forEach((x, j) => money(cells[2 + j], x, '期間損益'));
        assert(cells[5].textContent === pct(av[2]), '期間割合');
        assert(cells[6].childNodes[0].textContent === `${a.positive_sessions} / ${a.active_sessions}`, '期間活動');
        assert(cells[6].querySelector('small').textContent === `無取引 ${a.no_trade_sessions}場`, '無取引数');
        money(cells[7], a.best_session_removed, '最良場除外'); money(cells[8], -a.max_drawdown, 'DD');
        [av[0] - bv[0], bv[1] - av[1], a.net - b.net].forEach((x, j) => money(dc[2 + j], x, '改修差'));
        assert(number(dc[5]) === av[4] - bv[4], '取引件数差');
        money(dc[6], av[4] ? a.net / av[4] : null, '平均収支'); numbers += 4;
      }));
      const oldRows = get('old-results').rows, expectedOld = data.old_comparison.filter(r => r.model === model);
      assert(oldRows.length === expectedOld.length, '旧照合行数');
      expectedOld.forEach((r, i) => [r.previous, r.same28, r.added2, r.total].forEach((x, j) => money(oldRows[i].cells[j + 2], x, '旧28接続')));
      const timeRows = get('time-results').rows;
      assert(timeRows.length === 12 && timeRows[0].cells.length === 10, '時間帯12行10列');
      data.fixed.primary.forEach((id, p) => ['', '_J', '_U', '_JU'].forEach((suffix, t) => {
        const cells = timeRows[p * 4 + t].cells;
        assert(cells[1].querySelector('a').dataset.timeMethod === id + suffix, '時間帯条件固定');
        symbols.forEach((symbol, s) => {
          const a = data.results[model][id + suffix].periods['全30'][symbol], b = data.results[model][id].periods['全30'][symbol];
          money(cells[2 + s * 4], a.net, '時間帯収支'); money(cells[3 + s * 4], a.net - b.net, '時間帯差');
          assert(cells[4 + s * 4].textContent === pct(selected(a, cycle)[2]), '時間帯割合');
          money(cells[5 + s * 4], -a.max_drawdown, '時間帯最大下落');
          assert(cells[2 + s * 4].querySelector('small').textContent.includes(String(a.time_forced_exits)), '時間帯返済数'); numbers += 2;
        });
      }));
      assert(cycle ? get('account-note').textContent.includes('親組＝') : get('account-note').textContent.includes('部分決済'), '会計説明');
      assert(model === 'observed' ? get('model-note').textContent.includes('現在値で約定') : get('model-note').textContent.includes('指定条件線'), 'モデル説明');
      views++;
    }
    for (const id of data.fixed.primary) {
      get('primary-results').querySelector(`[data-method="${id}"]`).click();
      assert(get('method-select').value === id, '主3ボタン切替'); operations++;
    }
    for (const id of data.fixed.primary) for (const suffix of ['', '_J', '_U', '_JU']) {
      const link = get('time-results').querySelector(`[data-time-method="${id + suffix}"]`);
      // 隔離複製へ付けたbase要素による別URL移動だけを止め、製品の切替処理は実行する。
      link.addEventListener('click', event => event.preventDefault(), {once: true});
      link.click();
      assert(get('method-select').value === id + suffix, '時間帯リンク切替'); operations++;
    }
    change('method-select', 'E01_GPDC'); change('model-select', 'observed'); change('account-select', 'cycle');
    window.scrollTo(0, 0);
  } else {
    for (const model of ['observed', 'specified']) for (const period of periods) {
      change('model-select', model); change('period-select', period);
      const rows = get('all-results').rows; assert(rows.length === 25 && rows[0].cells.length === 13, '全25比較行列');
      let positive = 0;
      data.fixed.catalog.forEach((config, i) => {
        const result = data.results[model][config.id];
        assert(rows[i].cells[0].querySelector('a').textContent === config.id, '条件順序');
        const link = rows[i].cells[0].querySelector('a').getAttribute('href');
        assert(link.includes('id=' + config.id) && link.endsWith('model=' + model), '主レポート指定リンク');
        if (symbols.every(symbol => result.periods[period][symbol].net > 0)) positive++;
        symbols.forEach((symbol, s) => {
          const a = result.periods[period][symbol];
          [a.cycle_profit, -a.cycle_loss, a.net].forEach((x, j) => money(rows[i].cells[1 + s * 6 + j], x, '全25金額'));
          assert(rows[i].cells[4 + s * 6].textContent === pct(a.cycle_profit_share), '全25割合');
          assert(rows[i].cells[5 + s * 6].textContent === `${a.positive_sessions} / ${a.sessions}`, '全25黒字場');
          assert(number(rows[i].cells[6 + s * 6]) === a.cycles, '全25親組数'); numbers += 3;
        });
      });
      assert(get('all-count').textContent.includes('収支プラス：' + positive + '条件'), '両黒字条件数'); views++;
    }
    change('model-select', 'observed'); change('period-select', '全30');
  }
  for (const detail of document.querySelectorAll('details')) detail.open = true;
  assert(document.documentElement.scrollWidth <= innerWidth + 2, '本文横はみ出し');
  for (const detail of document.querySelectorAll('details')) detail.open = false;
  assert(!/NaN|undefined|Infinity|__DATA__|__SCRIPT__/.test(document.body.innerText), '未展開・非数');
  assert((window.browserErrors || []).length === 0, 'JS例外');
  assert(!document.querySelector('script[src],link[href],img[src]'), '外部資源なし');
  assert(getComputedStyle(document.body).backgroundColor === 'rgb(16, 21, 30)', 'ダークテーマ');
  return {全合格: true, 手法モデル会計切替数: views, 場商品表示数: accounts, 数値照合数: numbers, 赤字色照合数: colors,
    操作数: operations, 文書幅: document.documentElement.scrollWidth, 画面幅: innerWidth, JS例外数: window.browserErrors.length};
}
try { document.body.dataset.check = JSON.stringify(independentVerify()); }
catch (e) { document.body.dataset.check = JSON.stringify({全合格: false, 理由: String(e), stack: e.stack}); }
