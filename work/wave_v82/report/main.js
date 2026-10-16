const PAIRS = Object.fromEntries(DATA.pairs.map((p) => [p.label, p]));

/**
 * 選択した元・反転の期間会計を取得する。
 * @param {Object} pair - 比較する手法の組。
 * @param {string} variant - original 又は reverse。
 * @param {number|string} delay - 発注待ち秒。
 * @param {string} period - 対象、前16又は後14。
 * @param {string} symbol - 商品キー。
 * @returns {Object} 保存済み会計。
 */
function account(pair, variant, delay, period, symbol) {
  return DATA.final[String(delay)][pair[variant].id].periods[period][symbol];
}

/**
 * 黒字・赤字・無取引の場数を表示する。
 * @param {Object} a - 保存済み会計。
 * @returns {string} 黒字／赤字／休止場の表示。
 */
function sessionCounts(a) {
  return `${a.winning_sessions}／${a.losing_sessions}／${a.no_trade_sessions}`;
}

/**
 * 全30場の両商品・元反転を一つの表へ表示する。
 * @param {Object} pair - 手法の組。
 * @param {number|string} delay - 発注待ち秒。
 * @returns {void} 返り値なし。
 */
function allSessions(pair, delay) {
  const maps = Object.fromEntries(["original", "reverse"].map((v) => [v, Object.fromEntries(DATA.final[String(delay)][pair[v].id].rows.map((r) => [r.session + "|" + r.symbol, r]))]));
  let rows = DATA.sessions.map((session) => {
    return `<tr data-session="${session}"><th scope="row">${session.replace("_Day", " デイ").replace("_Night", " ナイト")}</th>` + ["TOPIX", "NK225"].map((symbol) => ["original", "reverse"].map((v) => {
      const a = maps[v][session + "|" + symbol];
      return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td>`;
    }).join("")).join("") + "</tr>";
  }).join("");
  rows += '<tr class="total"><th scope="row">全30場 合計</th>' + ["TOPIX", "NK225"].map((symbol) => ["original", "reverse"].map((v) => {
    const a = account(pair, v, delay, "対象", symbol);
    return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td>`;
  }).join("")).join("") + "</tr>";
  put("session-results", rows);
  document.getElementById("session-caption").textContent = `${pair.label} ${pair.parent_id} · 元／反転 · 発注待ち${delay}秒`;
}

/**
 * 選んだ手法組の条件・期間・全場・事後分類を同期する。
 * @returns {void} 引数・返り値なし。
 */
function updateSelected() {
  const pair = PAIRS[document.getElementById("pair-select").value], delay = document.getElementById("delay-select").value;
  for (const field of ["entry", "during", "exit", "execution"]) document.getElementById(field + "-text").textContent = pair.description[field];
  put("period-results", [["前16", "前16場"], ["後14", "後14場"], ["対象", "全30場"]].map(([period, label]) => ["TOPIX", "NK225"].map((symbol) => ["original", "reverse"].map((v) => {
    const a = account(pair, v, delay, period, symbol);
    return `<tr><th scope="row">${label}</th><td>${symbolName(symbol)}</td><td>${v === "original" ? "元" : "反転"}</td><td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td><td>${percent(a.profit_share)}</td><td>${a.trades}</td><td>${sessionCounts(a)}</td></tr>`;
  }).join("")).join("")).join(""));
  allSessions(pair, delay);
  put("regime-results", DATA.regimes[pair.label].map((r) => `<tr><th scope="row">${escapeHtml(r.regime)}</th><td>${symbolName(r.symbol)}</td><td>${r.sessions}</td><td>${amount(r.original.net)}</td><td>${amount(r.reverse.net)}</td><td>${sessionCounts(r.reverse)}</td></tr>`).join(""));
}

/**
 * 全体の比較表と遅延感度を表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderOverview() {
  put("cost-results", DATA.pairs.map((p) => ["TOPIX", "NK225"].map((symbol) => {
    return `<tr><th scope="row">${escapeHtml(p.label)}</th><td>${symbolName(symbol)}</td>` + ["original", "reverse"].map((v) => {
      const a = account(p, v, 5, "対象", symbol);
      return `<td>${amount(a.gross + a.spread_drag)}</td><td>${amount(-(a.spread_drag + a.fees))}</td><td>${amount(a.net)}</td>`;
    }).join("") + "</tr>";
  }).join("")).join(""));
  put("overview-results", DATA.pairs.map((p) => {
    const ot = account(p, "original", 5, "対象", "TOPIX"), rt = account(p, "reverse", 5, "対象", "TOPIX");
    const on = account(p, "original", 5, "対象", "NK225"), rn = account(p, "reverse", 5, "対象", "NK225");
    return `<tr><th scope="row"><button class="method-link" data-pair="${p.label}">${escapeHtml(p.label + " " + p.name)}<br><small>${escapeHtml(p.parent_id)}</small></button></th><td>${amount(ot.net)}</td><td>${amount(rt.net)}<br><small>${percent(rt.profit_share)}</small></td><td>${amount(on.net)}</td><td>${amount(rn.net)}<br><small>${percent(rn.profit_share)}</small></td><td>${sessionCounts(rt)}<br>${sessionCounts(rn)}</td></tr>`;
  }).join(""));
  put("latency-results", DATA.pairs.map((p) => ["TOPIX", "NK225"].map((symbol) => `<tr><th scope="row">${escapeHtml(p.label + " " + p.parent_id)}</th><td>${symbolName(symbol)}</td>` + [0, 1, 5].map((d) => `<td>${amount(account(p, "reverse", d, "対象", symbol).net)}</td>`).join("") + "</tr>").join("")).join(""));
  put("stability-results", DATA.pairs.map((p) => ["TOPIX", "NK225"].map((symbol) => {
    const a = account(p, "reverse", 5, "対象", symbol), strict = DATA.strict[p.reverse.id][symbol];
    return `<tr><th scope="row">${escapeHtml(p.label + " " + p.parent_id)}</th><td>${symbolName(symbol)}</td><td>${amount(a.net)}</td><td>${amount(a.without_best_session)}</td><td>${amount(a.worst_session)}</td><td>${amount(strict.net)}<br><small>${strict.trades}組</small></td></tr>`;
  }).join("")).join(""));
}

/**
 * 手法選択と比較画面を初期化する。
 * @returns {void} 引数・返り値なし。
 */
function initialize() {
  put("conclusion", `<p><strong>${escapeHtml(DATA.conclusion.主文)}</strong></p><p>${escapeHtml(DATA.conclusion.補足)}</p>`);
  const stable = DATA.front_diagnosis["元が両商品全16場赤字の66条件"], all = DATA.front_diagnosis["逆188全条件"];
  document.getElementById("front-result-description").textContent = `前半で両商品全16場赤字だった${stable.条件数}条件は、実際に反転しても${stable["逆が両商品合計赤字"]}条件すべて両商品合計赤字（${stable["逆も両商品全16場赤字"]}条件は反転も全16場赤字）。一方、全188条件では粗い32・64呼値の価格型${all["逆が両商品合計黒字"]}条件が反転後の前半合計で両商品黒字でした。ただし似た条件群であり、20個の独立した成功証拠ではありません。全条件表にも掲載しています。`;
  for (const key of ["selection-description", "regime-description", "audit-description", "limitations"]) document.getElementById(key).textContent = DATA.text[key];
  put("pair-select", DATA.pairs.map((p) => `<option value="${p.label}">${escapeHtml(p.label + "｜" + p.name + "｜" + p.parent_id)}</option>`).join(""));
  document.getElementById("pair-select").addEventListener("change", updateSelected);
  document.getElementById("delay-select").addEventListener("change", updateSelected);
  renderOverview(); updateSelected();
  document.querySelectorAll("[data-pair]").forEach((button) => button.addEventListener("click", () => {
    document.getElementById("pair-select").value = button.dataset.pair;
    document.getElementById("delay-select").value = "5";
    updateSelected(); document.getElementById("all-sessions").scrollIntoView({behavior: "smooth"});
  }));
  window.reportTest = {data: DATA, account, allSessions, updateSelected};
}
initialize();
