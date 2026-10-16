/**
 * 保存済みの管理条件を短い文字列にする。
 * @param {Object} c - 固定条件。
 * @returns {string} 管理・休止・変更内容の説明。
 */
function management(c) {
  const trail = c.trail ? "・追跡" : "";
  const explanation = c.explanation ? `<div class="summary">${escapeHtml(c.explanation)}</div>` : "";
  return `${escapeHtml(c.profile)}｜利確${c.target}／損切${c.stop}${trail}<br>${c.hold}秒・休止${c.cooldown}秒${explanation}`;
}

/**
 * 段階・系統・方式・検索語に合う全条件を再表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderAll() {
  const stage = document.getElementById("stage-filter").value;
  const family = document.getElementById("family-filter").value;
  const mode = document.getElementById("mode-filter").value;
  const query = document.getElementById("query-filter").value.toUpperCase().trim();
  const sort = document.getElementById("sort-select").value;
  const rows = DATA.rows.filter((r) => (!stage || r.stage === stage) && (!family || r.family === family) && (mode === "" || String(r.config.entry_mode) === mode) && (!query || r.config.id.toUpperCase().includes(query)));
  rows.sort((a, b) => sort === "id" ? (a.stage === b.stage ? a.config.id.localeCompare(b.config.id, "ja", {numeric: true}) : a.stage === "初回" ? -1 : 1) : b.metrics[sort].net - a.metrics[sort].net || a.config.id.localeCompare(b.config.id));
  put("all-results", rows.map((r) => {
    return `<tr data-id="${r.config.id}"><th scope="row"><span class="pill">${r.stage}</span>${escapeHtml(r.config.id)}<br><small>${escapeHtml(r.family)}</small></th><td class="wrap">${escapeHtml(r.mode)}<br>${management(r.config)}</td>` + ["TOPIX", "NK225"].map((symbol) => {
      const a = r.metrics[symbol];
      return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}</td><td>${percent(a.profit_share)}<br><small>${a.trades}組</small></td>`;
    }).join("") + "</tr>";
  }).join(""));
  document.getElementById("result-count").textContent = `${rows.length}／330条件を表示。商品間の金額は合算せず、各商品内で評価します。`;
}

/**
 * 絞り込みを準備し、全330条件を初期表示する。
 * @returns {void} 引数・返り値なし。
 */
function initializeAll() {
  document.getElementById("family-filter").insertAdjacentHTML("beforeend", DATA.families.map((f) => `<option>${escapeHtml(f)}</option>`).join(""));
  for (const id of ["stage-filter", "family-filter", "mode-filter", "sort-select"]) document.getElementById(id).addEventListener("change", renderAll);
  document.getElementById("query-filter").addEventListener("input", renderAll);
  renderAll();
  window.reportTest = {data: DATA, renderAll};
}
initializeAll();
