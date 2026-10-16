/**
 * 前半全条件の親組会計を絞り込んで表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderAll() {
  const family = document.getElementById("family-filter").value, query = document.getElementById("query-filter").value.toUpperCase().trim();
  const sort = document.getElementById("sort-select").value;
  const rows = DATA.rows.filter((r) => (!family || String(r.config.family) === family) && (!query || r.config.id.toUpperCase().includes(query)));
  rows.sort((a, b) => sort === "id" ? a.config.id.localeCompare(b.config.id, "ja", {numeric: true}) : b.metrics[sort].net - a.metrics[sort].net || a.config.id.localeCompare(b.config.id));
  put("all-results", rows.map((r) => `<tr data-id="${escapeHtml(r.config.id)}"><th scope="row" class="wrap">${escapeHtml(r.config.id)}<br><small>${escapeHtml(r.name)}<br>${escapeHtml(r.condition)}</small></th>` + ["TOPIX", "NK225"].map((symbol) => {
    const a = r.metrics[symbol];
    return `<td>${amount(a.cycle_profit)}</td><td>${amount(-a.cycle_loss)}</td><td>${amount(a.cycle_net)}<br><small>${a.cycles}組</small></td><td>${percent(a.cycle_profit_share)}</td>`;
  }).join("") + "</tr>").join(""));
  document.getElementById("result-count").textContent = `${rows.length}／${DATA.rows.length}条件。前半の親組会計だけを表示しています。`;
}

/**
 * 前半全条件の選択肢と操作を準備する。
 * @returns {void} 引数・返り値なし。
 */
function initializeAll() {
  put("family-filter", '<option value="">すべて</option>' + DATA.families.map((f) => `<option value="${f.id}">${escapeHtml(f.name)}</option>`).join(""));
  document.getElementById("all-intro").textContent = DATA.intro;
  for (const key of ["family-filter", "sort-select"]) document.getElementById(key).addEventListener("change", renderAll);
  document.getElementById("query-filter").addEventListener("input", renderAll);
  renderAll(); window.reportTest = {data: DATA, renderAll};
}
initializeAll();
