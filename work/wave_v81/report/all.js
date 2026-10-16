/**
 * 実保有秒を前半比較表の表示へ変換する。
 * @param {number|null} seconds - 実保有中央値。
 * @returns {string} 秒又は分又は時間の表示。
 */
function duration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  return seconds < 60 ? Number(seconds.toFixed(1)) + "秒" : seconds < 3600 ? Number((seconds / 60).toFixed(1)) + "分" : Number((seconds / 3600).toFixed(2)) + "時間";
}

/**
 * 条件を絞り込み、全前半損益を表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderAll() {
  const stage = document.getElementById("stage-filter").value, family = document.getElementById("family-filter").value;
  const mode = document.getElementById("mode-filter").value, query = document.getElementById("query-filter").value.toUpperCase().trim();
  const sort = document.getElementById("sort-select").value;
  const rows = DATA.rows.filter((r) => (!stage || r.stage === stage) && (!family || (family === "solo" ? r.config.solo : !r.config.solo && r.description.entry_model.id.startsWith(family))) && (mode === "" || String(r.config.entry_mode) === mode) && (!query || r.config.id.toUpperCase().includes(query)));
  rows.sort((a, b) => sort === "id" ? (a.stage === b.stage ? a.config.id.localeCompare(b.config.id, "ja", {numeric: true}) : a.stage === "初回" ? -1 : 1) : b.metrics[sort].net - a.metrics[sort].net || a.config.id.localeCompare(b.config.id));
  put("all-results", rows.map((r) => `<tr data-id="${escapeHtml(r.config.id)}"><th scope="row" class="wrap"><span class="pill">${r.stage}</span>${escapeHtml(r.config.id)}<br><small>入口${escapeHtml(r.description.entry_model.id)}<br>出口${escapeHtml(r.description.exit_model.id)}／X${r.config.exit_mode}／M${r.config.entry_mode}<br>${escapeHtml(r.config.change || r.config.explanation || "")}</small></th>` + ["TOPIX", "NK225"].map((symbol) => {
    const a = r.metrics[symbol];
    return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td><td>${percent(a.profit_share)}<br><small>${a.trades}組</small></td><td>${duration(a.hold_median)}</td>`;
  }).join("") + "</tr>").join(""));
  document.getElementById("result-count").textContent = `${rows.length}／${DATA.count}条件を表示。前16場だけの比較です。`;
}

/**
 * 全条件の絞り込み操作を初期化する。
 * @returns {void} 引数・返り値なし。
 */
function initializeAll() {
  for (const id of ["stage-filter", "family-filter", "mode-filter", "sort-select"]) document.getElementById(id).addEventListener("change", renderAll);
  document.getElementById("query-filter").addEventListener("input", renderAll);
  renderAll(); window.reportTest = {data: DATA, renderAll};
}
initializeAll();
