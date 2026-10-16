const METHODS = Object.fromEntries(DATA.methods.map((m) => [m.id, m]));

/**
 * 保存された方法・遅延・期間の会計を取得する。
 * @param {string} id - 手法ID。
 * @param {number|string} delay - 発注待ち秒。
 * @param {string} period - 前16、後14又は対象。
 * @param {string} symbol - 商品キー。
 * @returns {Object} 保存会計。
 */
function account(id, delay, period, symbol) {
  return DATA.final[String(delay)][id].periods[period][symbol];
}

/**
 * 同じ総収支を親組又は決済脚の利益・損失へ分けて表示する。
 * @param {Object} a - 保存会計。
 * @param {string} unit - cycle 又は leg。
 * @returns {Object} 表示用の利益、損失、収支、金額割合、件数。
 */
function unitAccount(a, unit) {
  return unit === "cycle" ? {profit: a.cycle_profit, loss: a.cycle_loss, net: a.cycle_net, share: a.cycle_profit_share, count: a.cycles}
    : {profit: a.profit, loss: a.loss, net: a.net, share: a.profit_share, count: a.trades};
}

/**
 * 保存がある数量だけを表示し、未保存をゼロにしない。
 * @param {number|null|undefined} value - 数量。
 * @returns {string} 数値又は未保存の印。
 */
function quantity(value) {
  return typeof value === "number" ? NUMBER.format(value) : "—";
}

/**
 * 指定条件の両商品・全30場を常時表示表へ描画する。
 * @param {string} id - 手法ID。
 * @param {number|string} delay - 発注待ち秒。
 * @param {string} unit - cycle 又は leg。
 * @returns {void} 返り値なし。
 */
function allSessions(id, delay, unit) {
  const result = DATA.final[String(delay)][id];
  const lookup = Object.fromEntries(result.rows.map((r) => [r.session + "|" + r.symbol, r]));
  let rows = DATA.sessions.map((session) => `<tr data-session="${session}"><th scope="row">${session.replace("_Day", " デイ").replace("_Night", " ナイト")}</th>` + ["TOPIX", "NK225"].map((symbol) => {
    const a = unitAccount(lookup[session + "|" + symbol], unit);
    return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td>`;
  }).join("") + "</tr>").join("");
  rows += '<tr class="total"><th scope="row">全30場 合計</th>' + ["TOPIX", "NK225"].map((symbol) => {
    const a = unitAccount(result.periods["対象"][symbol], unit);
    return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td>`;
  }).join("") + "</tr>";
  put("session-results", rows);
  document.getElementById("session-caption").textContent = `${id} · 追加発注遅延0・有効気配で約定 · ${unit === "cycle" ? "親組" : "決済脚"}単位 · 夜間は開始日に帰属`;
}

/**
 * 在庫・料金・親組と脚の会計を選択条件へ同期する。
 * @param {string} id - 手法ID。
 * @param {number|string} delay - 発注待ち秒。
 * @returns {void} 返り値なし。
 */
function renderInventory(id, delay) {
  put("inventory-results", ["TOPIX", "NK225"].map((symbol) => {
    const a = account(id, delay, "対象", symbol);
    return `<tr><th scope="row">${symbolName(symbol)}</th><td>${amount(a.gross)}</td><td>${amount(-a.fees)}</td><td>${amount(a.net)}</td><td>${quantity(a.max_long)}／${quantity(a.max_short)}</td><td>${quantity(a.max_gross)}／${quantity(a.max_net)}</td><td>${amount(-a.drawdown)}</td><td>${amount(a.worst_session)}</td><td>${amount(a.without_best_session)}</td></tr>`;
  }).join(""));
  put("group-results", ["TOPIX", "NK225"].map((symbol) => ["cycle", "leg"].map((unit) => {
    const a = unitAccount(account(id, delay, "対象", symbol), unit);
    return `<tr><th scope="row">${symbolName(symbol)}</th><td>${unit === "cycle" ? "親組" : "決済脚"}</td><td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td><td>${percent(a.share)}</td><td>${quantity(a.count)}</td></tr>`;
  }).join("")).join(""));
  put("logical-results", ["TOPIX", "NK225"].map((symbol) => {
    const a = account(id, delay, "対象", symbol), ideal = DATA.ideal[id].periods["対象"][symbol], idealFee = DATA.ideal_fee[id].periods["対象"][symbol];
    return `<tr><th scope="row">${symbolName(symbol)}</th><td>${amount(ideal.net)}</td><td>${amount(idealFee.net)}</td><td>${amount(a.midpoint_gross)}</td><td>${amount(-a.spread_drag)}</td><td>${amount(-a.fees)}</td><td>${amount(a.net)}</td></tr>`;
  }).join(""));
  const diagnosis = DATA.diagnosis[id];
  put("loss-explanation", diagnosis ? ["TOPIX", "NK225"].map((symbol) => {
    const explanation = diagnosis.symbols[symbol].explanation;
    return `<p><strong>${symbolName(symbol)}</strong>：${escapeHtml(Array.isArray(explanation) ? explanation.join(" ") : explanation)}</p>`;
  }).join("") : "");
}

/**
 * 選択した手法・会計単位の説明と全場を更新する。
 * @returns {void} 引数・返り値なし。
 */
function updateSelected() {
  const id = document.getElementById("method-select").value, delay = 0;
  const unit = document.getElementById("unit-select").value, method = METHODS[id];
  for (const field of ["entry", "during", "exit", "execution"]) document.getElementById(field + "-text").textContent = method[field];
  document.getElementById("size-description").textContent = method.allocation;
  put("period-results", [["前16", "前16場"], ["後14", "後14場"], ["対象", "全30場"]].map(([period, label]) => ["TOPIX", "NK225"].map((symbol) => {
    const base = account(id, delay, period, symbol), a = unitAccount(base, unit);
    return `<tr><th scope="row">${label}</th><td>${symbolName(symbol)}</td><td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td><td>${percent(a.share)}</td><td>${base.winning_sessions}／${base.losing_sessions}／${base.no_trade_sessions}</td></tr>`;
  }).join("")).join(""));
  allSessions(id, delay, unit); renderInventory(id, delay);
}

/**
 * 前半固定代表の全体・後半と無作為20種の感度を表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderOverview() {
  put("overview-results", DATA.methods.map((m) => {
    const top = account(m.id, 0, "対象", "TOPIX"), nk = account(m.id, 0, "対象", "NK225");
    return `<tr><th scope="row"><button class="method-link" data-method="${m.id}">${escapeHtml(m.name)}<br><small>${escapeHtml(m.id)}</small></button><br><small>${escapeHtml(m.criteria.join("・"))}</small></th><td class="wrap">${escapeHtml(m.short)}<br><small class="${m.sufficient ? "" : "warning"}">${escapeHtml(m.status)}</small></td><td>${amount(top.net)}<br><small>親組 ${percent(top.cycle_profit_share)}</small></td><td>${amount(nk.net)}<br><small>親組 ${percent(nk.cycle_profit_share)}</small></td><td>${amount(account(m.id, 0, "後14", "TOPIX").net)}</td><td>${amount(account(m.id, 0, "後14", "NK225").net)}</td></tr>`;
  }).join(""));
  const sensitivity = DATA.sensitivity;
  document.getElementById("randomness-description").textContent = `${sensitivity.config.id}を固定し、乱数種0〜19だけ変更。両商品とも黒字は${sensitivity.both_profitable_seeds}／20種。良い種への差替えはしていません。同じ30場なので、20個の独立した相場ではありません。`;
  put("randomness-results", ["TOPIX", "NK225"].map((symbol) => {
    const a = sensitivity.symbols[symbol];
    return `<tr><th scope="row">${symbolName(symbol)}</th><td>${amount(a.mean_net)}</td><td>${amount(a.median_net)}</td><td>${amount(a.worst_net)}</td><td>${amount(a.best_net)}</td><td>${a.profitable_seeds}／20</td></tr>`;
  }).join(""));
  put("seed-results", sensitivity.rows.map((r) => `<tr><th scope="row">${r.seed}</th><td>${amount(r.metrics.TOPIX.net)}</td><td>${amount(r.metrics.NK225.net)}</td></tr>`).join(""));
}

/**
 * 不成立指値を残す改修の固定3条件を、元の親組会計と併記する。
 * @returns {void} 引数・返り値なし。
 */
function renderPersistentComparison() {
  document.getElementById("persistent-description").textContent = DATA.persistent_description;
  put("persistent-select", DATA.persistent.map((r) => `<option value="${escapeHtml(r.parent_id)}">${escapeHtml(r.config.name + "｜" + r.parent_id)}</option>`).join(""));
  put("persistent-comparison", DATA.persistent.map((r) => ["TOPIX", "NK225"].map((symbol) => {
    const original = r.original.periods["対象"][symbol], changed = r.result.periods["対象"][symbol];
    return `<tr><th scope="row">${escapeHtml(r.parent_id)}</th><td>${symbolName(symbol)}</td><td>${amount(original.cycle_profit)}</td><td>${amount(-original.cycle_loss)}</td><td>${amount(original.net)}</td><td>${amount(changed.cycle_profit)}</td><td>${amount(-changed.cycle_loss)}</td><td>${amount(changed.net)}</td></tr>`;
  }).join("")).join(""));
  document.getElementById("persistent-select").addEventListener("change", renderPersistentSessions);
  renderPersistentSessions();
}

/**
 * 改修条件の全30場と合計を描画する。
 * @returns {void} 引数・返り値なし。
 */
function renderPersistentSessions() {
  const id = document.getElementById("persistent-select").value;
  const result = DATA.persistent.find((r) => r.parent_id === id).result;
  const lookup = Object.fromEntries(result.rows.map((r) => [r.session + "|" + r.symbol, r]));
  let rows = DATA.sessions.map((session) => `<tr data-session="${session}"><th scope="row">${session.replace("_Day", " デイ").replace("_Night", " ナイト")}</th>` + ["TOPIX", "NK225"].map((symbol) => {
    const a = lookup[session + "|" + symbol];
    return `<td>${amount(a.cycle_profit)}</td><td>${amount(-a.cycle_loss)}</td><td>${amount(a.net)}</td>`;
  }).join("") + "</tr>").join("");
  rows += '<tr class="total"><th scope="row">全30場 合計</th>' + ["TOPIX", "NK225"].map((symbol) => {
    const a = result.periods["対象"][symbol];
    return `<td>${amount(a.cycle_profit)}</td><td>${amount(-a.cycle_loss)}</td><td>${amount(a.net)}</td>`;
  }).join("") + "</tr>";
  put("persistent-results", rows);
  document.getElementById("persistent-caption").textContent = `${id} · 指値維持の改修 · 親組単位 · 夜間は開始日に帰属`;
}

/**
 * 操作・説明・初期表示を準備する。
 * @returns {void} 引数・返り値なし。
 */
function initialize() {
  put("conclusion", `<p><strong>${escapeHtml(DATA.conclusion.主文)}</strong></p><p>${escapeHtml(DATA.conclusion.補足)}</p>`);
  for (const [key, text] of Object.entries(DATA.text)) {
    const target = document.getElementById(key);
    if (target) target.textContent = text;
  }
  put("research-sources", DATA.sources.map((s) => `<li><a href="${escapeHtml(s.URL)}" target="_blank" rel="noopener">${escapeHtml(s.著者)}：${escapeHtml(s.名称)}</a> — ${escapeHtml(s.用途)}</li>`).join(""));
  put("method-select", DATA.methods.map((m) => `<option value="${m.id}">${escapeHtml(m.name + "｜" + m.id)}</option>`).join(""));
  for (const key of ["method-select", "unit-select"]) document.getElementById(key).addEventListener("change", updateSelected);
  renderOverview(); updateSelected(); renderPersistentComparison();
  document.querySelectorAll("[data-method]").forEach((button) => button.addEventListener("click", () => {
    document.getElementById("method-select").value = button.dataset.method;
    updateSelected(); document.getElementById("all-sessions").scrollIntoView({behavior: "smooth"});
  }));
  window.reportTest = {data: DATA, account, unitAccount, allSessions, updateSelected, renderPersistentSessions};
}
initialize();
