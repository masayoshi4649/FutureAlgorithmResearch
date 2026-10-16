const MAIN_IDS = [...DATA.initial, ...DATA.repaired];
const METHOD = Object.fromEntries(DATA.methods.map((m) => [m.id, m]));

/**
 * 保存された結果から方法・遅延・期間・商品の会計を取得する。
 * @param {string} id - 方法ID。
 * @param {number|string} delay - 注文待ち秒。
 * @param {string} period - 保存期間キー。
 * @param {string} symbol - 商品キー。
 * @returns {Object} 保存会計。
 */
function account(id, delay, period, symbol) {
  return DATA.final[String(delay)][id].periods[period][symbol];
}

/**
 * 全30場を両商品同時の常時表示表へ描画する。
 * @param {string} id - 方法ID。
 * @param {number|string} delay - 注文待ち秒。
 * @returns {void} 返り値なし。
 */
function allSessions(id, delay) {
  const result = DATA.final[String(delay)][id];
  const lookup = Object.fromEntries(result.rows.map((r) => [r.session + "|" + r.symbol, r]));
  let markup = DATA.sessions.map((session) => {
    const cells = ["TOPIX", "NK225"].map((symbol) => {
      const r = lookup[session + "|" + symbol];
      return `<td>${amount(r.profit)}</td><td>${amount(-r.loss)}</td><td>${amount(r.net)}</td>`;
    }).join("");
    return `<tr data-session="${escapeHtml(session)}"><th scope="row">${escapeHtml(session.replace("_Day", " デイ").replace("_Night", " ナイト"))}</th>${cells}</tr>`;
  }).join("");
  markup += '<tr class="total"><th scope="row">全30場 合計</th>' + ["TOPIX", "NK225"].map((symbol) => {
    const r = result.periods["対象"][symbol];
    return `<td>${amount(r.profit)}</td><td>${amount(-r.loss)}</td><td>${amount(r.net)}</td>`;
  }).join("") + "</tr>";
  put("session-results", markup);
  document.getElementById("session-caption").textContent = `${id} · 注文待ち${delay}秒 · 全30場（夜間は開始日の所属）`;
}

/**
 * 期間損益と機械条件を選択した方法へ同期する。
 * @returns {void} 引数・返り値なし。
 */
function updateSelected() {
  const id = document.getElementById("method-select").value;
  const delay = document.getElementById("delay-select").value;
  const method = METHOD[id];
  for (const field of ["entry", "during", "exit"]) document.getElementById(field + "-text").textContent = method[field];
  document.getElementById("execution-text").textContent = method.execution;
  let rows = "";
  for (const [period, label] of [["前16", "前16場"], ["後14", "後14場"], ["対象", "全30場"]]) {
    for (const symbol of ["TOPIX", "NK225"]) {
      const r = account(id, delay, period, symbol);
      const payoff = r.payoff === null ? "—" : r.payoff.toFixed(2) + "倍";
      rows += `<tr><th scope="row">${label}</th><td>${symbolName(symbol)}</td><td>${amount(r.profit)}</td><td>${amount(-r.loss)}</td><td>${amount(r.net)}</td><td>${percent(r.profit_share)}</td><td>${r.trades}</td><td>${payoff}</td><td>${r.winning_sessions}／${r.losing_sessions}／${r.no_trade_sessions}</td></tr>`;
    }
  }
  put("period-results", rows);
  allSessions(id, delay);
}

/**
 * 一覧から該当手法の全セッションへ移動する。
 * @param {string} id - 選択する方法ID。
 * @returns {void} 返り値なし。
 */
function chooseMethod(id) {
  document.getElementById("method-select").value = id;
  document.getElementById("delay-select").value = "5";
  updateSelected();
  document.getElementById("all-sessions").scrollIntoView({behavior: "smooth", block: "start"});
}

/**
 * 主6方法と遅延比較を初期表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderOverview() {
  put("overview-results", MAIN_IDS.map((id) => {
    const method = METHOD[id], top = account(id, 5, "対象", "TOPIX"), nk = account(id, 5, "対象", "NK225");
    return `<tr><td><span class="pill">${method.group}</span><button type="button" class="method-link" data-method="${id}">${escapeHtml(method.name)}<br><small>${id}</small></button><div class="summary">${escapeHtml(method.entry)}</div></td><td>${amount(top.net)}<br><small>${percent(top.profit_share)}</small></td><td>${amount(nk.net)}<br><small>${percent(nk.profit_share)}</small></td><td>${amount(account(id, 5, "後14", "TOPIX").net)}</td><td>${amount(account(id, 5, "後14", "NK225").net)}</td></tr>`;
  }).join(""));
  put("latency-results", MAIN_IDS.map((id) => ["TOPIX", "NK225"].map((symbol) => {
    return `<tr><th scope="row">${escapeHtml(id)}</th><td>${symbolName(symbol)}</td>` + [0, 1, 5].map((delay) => `<td>${amount(account(id, delay, "対象", symbol).net)}</td>`).join("") + "</tr>";
  }).join("")).join(""));
}

/**
 * 初回代表と改修代表の利益減・損失減を両方表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderChange() {
  let rows = "";
  for (let mode = 0; mode < 3; mode++) {
    const oldId = DATA.initial[mode], newId = DATA.repaired[mode];
    for (const symbol of ["TOPIX", "NK225"]) {
      const before = account(oldId, 5, "対象", symbol), after = account(newId, 5, "対象", symbol);
      const lossSaved = before.loss - after.loss, profitLost = before.profit - after.profit;
      rows += `<tr><th scope="row">${oldId}<br>→ ${newId}</th><td>${symbolName(symbol)}</td><td>${amount(lossSaved)}</td><td class="${profitLost > 0 ? "loss" : profitLost < 0 ? "gain" : "neutral"}">${money(profitLost)}</td><td>${amount(after.net - before.net)}</td><td>${before.trades} → ${after.trades}</td><td>${amount(before.average_net)}<br>→ ${amount(after.average_net)}</td></tr>`;
    }
  }
  put("change-results", rows);
  const checked = "S6_P6_M0_C30", immediate = "A6_P6_M0";
  const comparisons = ["TOPIX", "NK225"].map((symbol) => {
    const before = account(checked, 5, "対象", symbol), after = account(immediate, 5, "対象", symbol);
    return `${symbolName(symbol)} ${before.trades}組・${amount(before.net)} → ${after.trades}組・${amount(after.net)}`;
  });
  put("confirmation-comparison", `3秒確認の有無だけを比べる成行対照（${checked} → ${immediate}）も、${comparisons.join("、")}。即時化で機会は増えましたが、共通の利益優位は確認できません。`);
}

/**
 * 少数の黒字条件と無方向対照を主代表と区別して表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderSparse() {
  put("sparse-results", DATA.sparse.map((id) => ["TOPIX", "NK225"].map((symbol) => {
    return `<tr><th scope="row"><button type="button" class="method-link" data-method="${id}">${id}</button></th><td>${symbolName(symbol)}</td>` + ["前16", "後14", "対象"].map((period) => {
      const r = account(id, 5, period, symbol);
      return `<td>${amount(r.net)}<br><small>${r.trades}組</small></td>`;
    }).join("") + "</tr>";
  }).join("")).join(""));
  const id = DATA.control[0];
  put("control-result", `無方向交互の対照 ${id}（全30場・5秒）：TOPIX ${amount(account(id, 5, "対象", "TOPIX").net)}／日経 ${amount(account(id, 5, "対象", "NK225").net)}。上の手法選択から全場を確認できます。`);
}

/**
 * 損失分解と原著リンクを表示する。
 * @returns {void} 引数・返り値なし。
 */
function renderEvidence() {
  put("cost-results", DATA.loss_basis.map((r) => `<tr><th scope="row">${symbolName(r["商品"])}</th><td>${amount(r["同一経路の中値進行"])}</td><td>${amount(-r["同約定行の中値からの約定差"])}</td><td>${amount(-r["手数料"])}</td><td>${amount(r["収支"])}</td></tr>`).join(""));
  put("research-sources", DATA.sources.slice(0, 5).map((s) => `<li><a href="${escapeHtml(s.URL)}" target="_blank" rel="noopener">${escapeHtml(s.著者)}：${escapeHtml(s.名称)}</a> — ${escapeHtml(s.限界)}</li>`).join(""));
  put("strict-results", DATA.methods.map((m) => {
    const top = DATA.strict[m.id].TOPIX, nk = DATA.strict[m.id].NK225;
    return `<tr><th scope="row">${m.id}</th><td>${amount(top.net)}</td><td>${top.trades}</td><td>${amount(nk.net)}</td><td>${nk.trades}</td></tr>`;
  }).join(""));
  const c = DATA.loss_case, opening = c["注文時計"]["新規"], closing = c["注文時計"]["返済"];
  const clock = (value) => value.slice(11, 19);
  put("loss-case", `<p>${escapeHtml(c["セッション"].replace("_Day", " デイ"))}・${escapeHtml(c["手法"])}・TOPIXミニ10枚：${clock(opening["判断"])} 買い判断 → ${clock(opening["約定"])} ${NUMBER.format(c["新規価格"])} 約定 → ${clock(closing["判断"])} 買気配${NUMBER.format(c["実際返済判断bid"])}で損切り判断 → ${clock(closing["約定"])} ${NUMBER.format(c["返済価格"])}で返済。収支 ${amount(c["収支円"])}。</p><p>内訳は設定した損切り幅 ${money(c["設定幅による価格損失円"])} ＋ 発動を観測するまでの超過 ${money(c["発動観測時点までの追加価格損失円"])} ＋ 返済待ち中の追加損失 ${money(c["返済判断後の追加価格損失円"])} ＋ 手数料 ${money(c["手数料円"])}。損切り幅は最大損失を保証しません。</p>`);
  const waits = ["TOPIX", "NK225"].map((symbol) => {
    const r = DATA.waits[symbol];
    return `${symbolName(symbol)} ${Number(r["新規"]["百分位95秒"].toFixed(2))}／${Number(r["返済"]["百分位95秒"].toFixed(2))}秒`;
  });
  put("actual-waits", `A6_P6_M0の再生上の注文待ち95%点（新規／返済）は ${waits.join("、")}。指定5秒の後も次の有効観測を待つため、5秒は上限ではありません。`);
}

/**
 * 全構成要素を初期化し、表示検査用の読取APIを公開する。
 * @returns {void} 引数・返り値なし。
 */
function initialize() {
  put("conclusion", `<p><strong>${escapeHtml(DATA.conclusion.主文)}</strong></p><p>${escapeHtml(DATA.conclusion.補足)}</p>`);
  put("method-select", DATA.methods.map((m) => `<option value="${m.id}">${m.group}｜${m.name}｜${m.id}</option>`).join(""));
  document.getElementById("method-select").value = DATA.repaired[0];
  document.getElementById("method-select").addEventListener("change", updateSelected);
  document.getElementById("delay-select").addEventListener("change", updateSelected);
  renderOverview(); renderChange(); renderSparse(); renderEvidence(); updateSelected();
  document.querySelectorAll("[data-method]").forEach((button) => button.addEventListener("click", () => chooseMethod(button.dataset.method)));
  window.reportTest = {data: DATA, account, allSessions, updateSelected};
}
initialize();
