/**
 * 前16場の全条件を商品・売買方向を分けて表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderAll() {
  const family = document.getElementById("family-filter").value, mode = document.getElementById("mode-filter").value;
  const query = document.getElementById("query-filter").value.toUpperCase().trim(), sort = document.getElementById("sort-select").value;
  const rows = DATA.rows.filter((r) => (!family || (family === "solo" ? r.config.solo : !r.config.solo && r.parent_id.startsWith(family))) && (mode === "" || String(r.config.entry_mode) === mode) && (!query || r.parent_id.toUpperCase().includes(query)));
  rows.sort((a, b) => {
    if (sort === "id") return a.parent_id.localeCompare(b.parent_id, "ja", {numeric: true});
    const [v, s] = sort.split("|");
    return b[v][s].net - a[v][s].net || a.parent_id.localeCompare(b.parent_id);
  });
  put("all-results", rows.map((r) => `<tr data-id="${escapeHtml(r.parent_id)}"><th scope="row" class="wrap">${escapeHtml(r.parent_id)}<br><small>${r.config.solo ? "対象外：単独対照" : "選定対象"}</small></th>` + ["TOPIX", "NK225"].map((symbol) => ["original", "reverse"].map((v) => {
    const a = r[v][symbol];
    return `<td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(a.net)}<br><small>${percent(a.profit_share)}／${a.trades}組</small></td>`;
  }).join("")).join("") + "</tr>").join(""));
  document.getElementById("result-count").textContent = `${rows.length}／${DATA.rows.length}条件を表示。前16場だけの比較です。`;
}

/**
 * 全条件表の操作を準備する。
 * @returns {void} 引数・返り値なし。
 */
function initializeAll() {
  for (const id of ["family-filter", "mode-filter", "sort-select"]) document.getElementById(id).addEventListener("change", renderAll);
  document.getElementById("query-filter").addEventListener("input", renderAll);
  renderAll(); window.reportTest = {data: DATA, renderAll};
}
initializeAll();
