"use strict";

/**
 * 固定25条件を指定した期間・約定仮定で表示する。
 * @returns {void} 返り値なし。
 */
function renderAll() {
  const model = document.getElementById("model-select").value;
  const period = document.getElementById("period-select").value;
  let profitable = 0;
  const lines = DATA.fixed.catalog.map((config) => {
    const result = DATA.results[model][config.id];
    if (["TOPIX", "NK225"].every((symbol) => result.periods[period][symbol].net > 0)) profitable += 1;
    const link = "__MAIN__#id=" + encodeURIComponent(config.id) + "&model=" + model;
    const primary = DATA.fixed.primary.includes(config.id) ? '<small class="subvalue">事前固定した主比較</small>' : '';
    const cells = ["TOPIX", "NK225"].map((symbol) => {
      const row = result.periods[period][symbol];
      return `<td>${amount(row.cycle_profit)}</td><td>${amount(-row.cycle_loss)}</td><td>${amount(row.net)}</td><td>${percent(row.cycle_profit_share)}</td><td>${row.positive_sessions} / ${row.sessions}</td><td>${row.cycles}</td>`;
    }).join("");
    return `<tr><th scope="row"><a href="${link}">${escapeHtml(config.id)}</a>${primary}</th>${cells}</tr>`;
  });
  put("all-results", lines.join(""));
  put("all-count", `全25条件を固定順で掲載。${period}で両商品とも収支プラス：${profitable}条件。主条件はこの結果で入れ替えていません。`);
}

document.getElementById("model-select").addEventListener("change", renderAll);
document.getElementById("period-select").addEventListener("change", renderAll);
window.reportTest = {renderAll};
renderAll();
