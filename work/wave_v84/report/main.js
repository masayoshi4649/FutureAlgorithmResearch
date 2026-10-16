const METHODS = Object.fromEntries(DATA.methods.map((method) => [method.id, method]));

/**
 * 選択された約定モデルと手法の会計を取得する。
 * @param {string} model - main又はideal。
 * @param {string} id - 固定した手法ID。
 * @param {string} period - 前16、後14又は対象。
 * @param {string} symbol - TOPIX又はNK225。
 * @returns {Object} 保存会計。
 */
function account(model, id, period, symbol) {
  return DATA.results[model][id].periods[period][symbol];
}

/**
 * 平均勝ち対平均負けを、保存値がある場合に限って表示する。
 * @param {number|null} value - 損益倍率。
 * @returns {string} 小数第二位までの倍率又は未計算の印。
 */
function ratio(value) {
  return value === null || value === undefined ? "—" : value.toFixed(2) + "倍";
}

/**
 * 全30場の両商品損益と期間合計を描画する。
 * @param {string} model - 約定モデル。
 * @param {string} id - 手法ID。
 * @returns {void} 返り値なし。
 */
function allSessions(model, id) {
  const result = DATA.results[model][id];
  const lookup = Object.fromEntries(result.rows.map((row) => [row.session + "|" + row.symbol, row]));
  let markup = DATA.sessions.map((session) => `<tr data-session="${session}"><th scope="row">${session.replace("_Day", " デイ").replace("_Night", " ナイト")}</th>` + ["TOPIX", "NK225"].map((symbol) => {
    const a = lookup[session + "|" + symbol];
    return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td>`;
  }).join("") + "</tr>").join("");
  markup += '<tr class="total"><th scope="row">全30場 合計</th>' + ["TOPIX", "NK225"].map((symbol) => {
    const a = result.periods["対象"][symbol];
    return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td>`;
  }).join("") + "</tr>";
  put("session-results", markup);
  document.getElementById("session-caption").textContent = `${id} · ${model === "main" ? "売買気配＋手数料" : "現在値必約定＋手数料の理論対照"}`;
}

/**
 * 同一の幅と出口を保った入口・再入口の対照を表示する。
 * @param {string} model - 選択した約定モデル。
 * @returns {void} 返り値なし。
 */
function renderComparisons(model) {
  put("direction-comparison", DATA.comparisons.direction.map((pair) => ["TOPIX", "NK225"].map((symbol) => {
    const first = account(model, pair.first, "対象", symbol), second = account(model, pair.second, "対象", symbol);
    return `<tr><th scope="row">${escapeHtml(pair.label)}</th><td>${symbolName(symbol)}</td><td>${amount(first.net)}</td><td>${amount(second.net)}</td><td>${amount(second.net - first.net)}</td></tr>`;
  }).join("")).join(""));
  put("turn-comparison", DATA.comparisons.turn.map((pair) => ["TOPIX", "NK225"].map((symbol) => {
    const first = account(model, pair.first, "対象", symbol), second = account(model, pair.second, "対象", symbol);
    return `<tr><th scope="row">${escapeHtml(pair.label)}</th><td>${symbolName(symbol)}</td><td>${amount(first.net)}</td><td>${escapeHtml(pair.description)}</td><td>${amount(second.net)}</td><td>${amount(second.net - first.net)}</td></tr>`;
  }).join("")).join(""));
  document.getElementById("comparison-description").textContent = DATA.text["comparison-description"] + (model === "main" ? " 現在は主条件の売買気配＋手数料を表示。" : " 現在は現在値必約定＋手数料の理論対照を表示。");
}

/**
 * 選択条件の説明・期間・全場・費用をまとめて同期する。
 * @returns {void} 引数・返り値なし。
 */
function updateSelected() {
  const id = document.getElementById("method-select").value;
  const model = document.getElementById("model-select").value, method = METHODS[id];
  for (const field of ["entry", "during", "exit", "condition"]) document.getElementById(field + "-text").textContent = method[field];
  document.getElementById("model-description").textContent = DATA.model_descriptions[model];
  put("period-results", [["前16", "前16場"], ["後14", "後14場"], ["対象", "全30場"]].map(([period, label]) => ["TOPIX", "NK225"].map((symbol) => {
    const a = account(model, id, period, symbol);
    return `<tr><th scope="row">${label}</th><td>${symbolName(symbol)}</td><td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td><td>${percent(a.profit_share)}</td><td>${ratio(a.payoff)}</td><td>${a.winning_sessions}／${a.losing_sessions}／${a.no_trade_sessions}</td></tr>`;
  }).join("")).join(""));
  put("cost-results", ["TOPIX", "NK225"].map((symbol) => {
    const a = account(model, id, "対象", symbol);
    return `<tr><th scope="row">${symbolName(symbol)}</th><td>${amount(a.midpoint_gross)}</td><td>${amount(-a.spread_drag)}</td><td>${amount(-a.fees)}</td><td>${amount(a.net)}</td><td>${amount(-a.drawdown)}</td><td>${amount(a.worst_session)}</td><td>${amount(a.without_best_session)}</td></tr>`;
  }).join(""));
  allSessions(model, id); renderComparisons(model);
}

/**
 * 前半固定代表の主成績を表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderOverview() {
  put("overview-results", DATA.methods.filter((method) => method.overview).map((method) => `<tr><th scope="row"><button class="method-link" data-method="${method.id}">${escapeHtml(method.name)}<br><small>${escapeHtml(method.id)}</small></button></th><td class="wrap">${escapeHtml(method.short)}<br><small>${escapeHtml(method.status)}</small></td>` + ["対象", "後14"].map((period) => ["TOPIX", "NK225"].map((symbol) => `<td>${amount(account("main", method.id, period, symbol).net)}</td>`).join("")).join("") + "</tr>").join(""));
}

/**
 * 主選定後に追加した少数取引の参考条件を、独立した会計で表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderSupplement() {
  const model = document.getElementById("supplement-model-select").value;
  const result = DATA.supplement.results[model];
  document.getElementById("supplement-description").textContent = DATA.supplement.description;
  document.getElementById("supplement-condition").textContent = DATA.supplement.method.condition;
  put("supplement-periods", [["前16", "前16場"], ["後14", "後14場"], ["対象", "全30場"]].map(([period, label]) => ["TOPIX", "NK225"].map((symbol) => {
    const a = result.periods[period][symbol];
    return `<tr><th scope="row">${label}</th><td>${symbolName(symbol)}</td><td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td><td>${a.trades}</td><td>${percent(a.profit_share)}</td></tr>`;
  }).join("")).join(""));
  const lookup = Object.fromEntries(result.rows.map((row) => [row.session + "|" + row.symbol, row]));
  let markup = DATA.sessions.map((session) => `<tr data-session="${session}"><th scope="row">${session.replace("_Day", " デイ").replace("_Night", " ナイト")}</th>` + ["TOPIX", "NK225"].map((symbol) => {
    const a = lookup[session + "|" + symbol];
    return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td>`;
  }).join("") + "</tr>").join("");
  markup += '<tr class="total"><th scope="row">全30場 合計</th>' + ["TOPIX", "NK225"].map((symbol) => {
    const a = result.periods["対象"][symbol];
    return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td>`;
  }).join("") + "</tr>";
  put("supplement-results", markup);
  document.getElementById("supplement-caption").textContent = `${result.config.id} · 追加の探索的参考 · ${model === "main" ? "売買気配＋手数料" : "現在値必約定＋手数料"}`;
}

/**
 * 固定資料と操作を接続し、初期条件の全場を表示する。
 * @returns {void} 引数・返り値なし。
 */
function initialize() {
  put("conclusion", `<p><strong>${escapeHtml(DATA.conclusion.主文)}</strong></p><p>${escapeHtml(DATA.conclusion.補足)}</p>`);
  for (const [id, text] of Object.entries(DATA.text)) {
    const target = document.getElementById(id);
    if (target) target.textContent = text;
  }
  put("method-select", DATA.methods.map((method) => `<option value="${method.id}">${escapeHtml(method.name + "｜" + method.id)}</option>`).join(""));
  for (const id of ["method-select", "model-select"]) document.getElementById(id).addEventListener("change", updateSelected);
  document.getElementById("supplement-model-select").addEventListener("change", renderSupplement);
  renderOverview(); updateSelected(); renderSupplement();
  document.querySelectorAll("[data-method]").forEach((button) => button.addEventListener("click", () => {
    document.getElementById("method-select").value = button.dataset.method;
    updateSelected(); document.getElementById("all-sessions").scrollIntoView({behavior: "smooth"});
  }));
  window.reportTest = {data: DATA, account, allSessions, updateSelected, renderComparisons, renderSupplement};
}
initialize();
