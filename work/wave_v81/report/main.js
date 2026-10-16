const METHOD = Object.fromEntries(DATA.methods.map((m) => [m.id, m]));
const MAIN_IDS = [...new Set([...DATA.initial, ...DATA.repaired])];

/**
 * 保存された期間会計を取得する。
 * @param {string} id - 方法ID。
 * @param {number|string} delay - 注文待ち秒。
 * @param {string} period - 期間キー。
 * @param {string} symbol - 商品キー。
 * @returns {Object} 保存会計。
 */
function account(id, delay, period, symbol) {
  return DATA.final[String(delay)][id].periods[period][symbol];
}

/**
 * 実際の保有時間を読みやすい時間単位へ変換する。
 * @param {number|null} seconds - 実績秒数。
 * @returns {string} 秒・分・時間の表示。目標時間ではない。
 */
function duration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return Number(seconds.toFixed(1)) + "秒";
  if (seconds < 3600) return Number((seconds / 60).toFixed(1)) + "分";
  return Number((seconds / 3600).toFixed(2)) + "時間";
}

/**
 * 両商品の全30セッションを常時表示表へ描画する。
 * @param {string} id - 方法ID。
 * @param {number|string} delay - 注文待ち秒。
 * @returns {void} 返り値なし。
 */
function allSessions(id, delay) {
  const result = DATA.final[String(delay)][id];
  const lookup = Object.fromEntries(result.rows.map((r) => [r.session + "|" + r.symbol, r]));
  let rows = DATA.sessions.map((session) => {
    return `<tr data-session="${session}"><th scope="row">${session.replace("_Day", " デイ").replace("_Night", " ナイト")}</th>` + ["TOPIX", "NK225"].map((symbol) => {
      const a = lookup[session + "|" + symbol];
      return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td>`;
    }).join("") + "</tr>";
  }).join("");
  rows += '<tr class="total"><th scope="row">全30場 合計</th>' + ["TOPIX", "NK225"].map((symbol) => {
    const a = result.periods["対象"][symbol];
    return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td>`;
  }).join("") + "</tr>";
  put("session-results", rows);
  document.getElementById("session-caption").textContent = `${id} · 注文待ち${delay}秒 · 夜間は開始日に帰属`;
}

/**
 * 実保有時間の分布を選択方法へ同期する。
 * @param {string} id - 方法ID。
 * @param {number|string} delay - 注文待ち秒。
 * @returns {void} 返り値なし。
 */
function renderHolding(id, delay) {
  put("holding-results", ["TOPIX", "NK225"].map((symbol) => {
    const a = account(id, delay, "対象", symbol);
    return `<tr><th scope="row">${symbolName(symbol)}</th><td>${duration(a.average_hold_seconds)}</td><td>${duration(a.hold_median)}</td><td>${duration(a.hold_p95)}</td><td>${duration(a.hold_max)}</td><td>${a.trades}組</td></tr>`;
  }).join(""));
  put("holding-bins", ["TOPIX", "NK225"].map((symbol) => {
    const a = account(id, delay, "対象", symbol);
    return `<tr><th scope="row">${symbolName(symbol)}</th>` + a.hold_bins.map((n) => `<td>${n}組<br><small>${a.trades ? percent(n / a.trades) : "—"}</small></td>`).join("") + "</tr>";
  }).join(""));
}

/**
 * 選択された方法の説明・期間集計・全場表・保有分布を更新する。
 * @returns {void} 引数・返り値なし。
 */
function updateSelected() {
  const id = document.getElementById("method-select").value;
  const delay = document.getElementById("delay-select").value;
  const method = METHOD[id];
  for (const field of ["entry", "during", "exit", "execution"]) document.getElementById(field + "-text").textContent = method[field];
  document.getElementById("exact-condition").textContent = method.short + "。" + (method.config.change || method.config.explanation || "") + " 入口と出口の方向が異なる方法は、その違いを上の条件説明にも記載しています。";
  put("period-results", [["前16", "前16場"], ["後14", "後14場"], ["対象", "全30場"]].map(([period, label]) => ["TOPIX", "NK225"].map((symbol) => {
    const a = account(id, delay, period, symbol);
    return `<tr><th scope="row">${label}</th><td>${symbolName(symbol)}</td><td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td><td>${percent(a.profit_share)}</td><td>${a.trades}</td><td>${a.payoff === null ? "—" : a.payoff.toFixed(2) + "倍"}</td><td>${a.winning_sessions}／${a.losing_sessions}／${a.no_trade_sessions}</td></tr>`;
  }).join("")).join(""));
  allSessions(id, delay); renderHolding(id, delay);
}

/**
 * 一覧の手法から詳細表へ移動する。
 * @param {string} id - 選択方法ID。
 * @returns {void} 返り値なし。
 */
function chooseMethod(id) {
  document.getElementById("method-select").value = id;
  document.getElementById("delay-select").value = "5";
  updateSelected();
  document.getElementById("all-sessions").scrollIntoView({behavior: "smooth"});
}

/**
 * 主代表の全体・後半と遅延感度を表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderOverview() {
  put("overview-results", MAIN_IDS.map((id) => {
    const m = METHOD[id], top = account(id, 5, "対象", "TOPIX"), nk = account(id, 5, "対象", "NK225");
    return `<tr><td><span class="pill">${m.group}</span><button type="button" class="method-link" data-method="${id}">${escapeHtml(m.name)}<br><small>${escapeHtml(id)}</small></button><div class="summary">${escapeHtml(m.short)}</div></td><td>${amount(top.net)}<br><small>${percent(top.profit_share)}</small></td><td>${amount(nk.net)}<br><small>${percent(nk.profit_share)}</small></td><td>${amount(account(id, 5, "後14", "TOPIX").net)}</td><td>${amount(account(id, 5, "後14", "NK225").net)}</td></tr>`;
  }).join(""));
  put("latency-results", MAIN_IDS.map((id) => ["TOPIX", "NK225"].map((symbol) => {
    return `<tr><th scope="row">${escapeHtml(id)}</th><td>${symbolName(symbol)}</td>` + [0, 1, 5].map((delay) => `<td>${amount(account(id, delay, "対象", symbol).net)}</td>`).join("") + "</tr>";
  }).join("")).join(""));
}

/**
 * 初回代表と改修代表の利益減・損失減・一組平均の変化を表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderChange() {
  let rows = "";
  for (let i = 0; i < DATA.initial.length; i++) {
    const oldId = DATA.initial[i], newId = DATA.repaired[i];
    for (const symbol of ["TOPIX", "NK225"]) {
      const before = account(oldId, 5, "対象", symbol), after = account(newId, 5, "対象", symbol);
      const profitLost = before.profit - after.profit;
      rows += `<tr><th scope="row">${escapeHtml(oldId)}<br>→ ${escapeHtml(newId)}</th><td>${symbolName(symbol)}</td><td>${amount(before.loss - after.loss)}</td><td class="${profitLost > 0 ? "loss" : profitLost < 0 ? "gain" : "neutral"}">${money(profitLost)}</td><td>${amount(after.net - before.net)}</td><td>${amount(before.average_net)}<br>→ ${amount(after.average_net)}</td><td>${before.trades} → ${after.trades}</td></tr>`;
    }
  }
  put("change-results", rows);
}

/**
 * 厳格鮮度と一次研究を表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderEvidence() {
  const flowId = DATA.repaired.find((id) => id.startsWith("D2_"));
  put("cost-results", ["TOPIX", "NK225"].map((symbol) => {
    const a = account(flowId, 5, "対象", symbol);
    return `<tr><th scope="row">${symbolName(symbol)}</th><td>${amount(a.gross + a.spread_drag)}</td><td>${amount(-a.spread_drag)}</td><td>${amount(-a.fees)}</td><td>${amount(a.net)}</td></tr>`;
  }).join(""));
  put("solo-results", DATA.repaired.map((id, i) => {
    return `<tr><th scope="row">${escapeHtml(id)}</th>` + ["TOPIX", "NK225"].map((symbol) => {
      const common = account(id, 5, "対象", symbol), solo = account(DATA.controls[i], 5, "対象", symbol);
      return `<td>${amount(common.net)}／${amount(solo.net)}<br><small>${common.trades}組／${solo.trades}組</small></td>`;
    }).join("") + "</tr>";
  }).join(""));
  put("strict-results", Object.entries(DATA.strict).map(([id, result]) => {
    const top = result.TOPIX, nk = result.NK225;
    return `<tr><th scope="row">${escapeHtml(id)}</th><td>${amount(top.net)}<br><small>${top.trades}組</small></td><td>${amount(nk.net)}<br><small>${nk.trades}組</small></td></tr>`;
  }).join(""));
  put("research-sources", DATA.sources.map((s) => `<li><a href="${escapeHtml(s.URL)}" target="_blank" rel="noopener">${escapeHtml(s.著者)}：${escapeHtml(s.名称)}</a> — ${escapeHtml(s.限界)}</li>`).join(""));
  document.getElementById("quality-fix").textContent = DATA.quality_fix;
  document.getElementById("pdca-summary").textContent = `初回86条件と追加・改修${DATA.count - 86}条件、合計${DATA.count}条件を前16場で比較。初回の価格方向4尺度、板フロー6尺度、両者一致3尺度へ、大きな価格転換16・32・64呼値と長い板記憶512・2048イベントを含む9尺度を追加しました。時間期限は増やしていません。支持消失／片方反対／双方反対と2注文方式、入口と出口の方向尺度を分ける方法、同方向の再入口を制限する方法を比較。初回代表も再選定の候補に残し、無取引や赤字条件を別HTMLに全件掲載します。`;
}

/**
 * 選択肢・操作・初期表示を準備する。
 * @returns {void} 引数・返り値なし。
 */
function initialize() {
  put("conclusion", `<p><strong>${escapeHtml(DATA.conclusion.主文)}</strong></p><p>${escapeHtml(DATA.conclusion.補足)}</p>`);
  put("method-select", DATA.methods.map((m) => `<option value="${m.id}">${m.group}｜${m.name}｜${m.id}</option>`).join(""));
  document.getElementById("method-select").value = DATA.repaired[0];
  document.getElementById("method-select").addEventListener("change", updateSelected);
  document.getElementById("delay-select").addEventListener("change", updateSelected);
  renderOverview(); renderChange(); renderEvidence(); updateSelected();
  document.querySelectorAll("[data-method]").forEach((b) => b.addEventListener("click", () => chooseMethod(b.dataset.method)));
  window.reportTest = {data: DATA, account, allSessions, updateSelected, renderHolding};
}
initialize();
