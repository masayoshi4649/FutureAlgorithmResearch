"use strict";
const SYMBOLS = ["TOPIX", "NK225"];

/**
 * 画面で指定した約定モデルと会計単位を取得する。
 * @returns {{model:string,id:string,cycle:boolean}} 現在の選択。
 */
function selection() {
  return {model: document.getElementById("model-select").value,
    id: document.getElementById("method-select").value,
    cycle: document.getElementById("account-select").value === "cycle"};
}

/**
 * 保存会計から親組又は部分決済の項目を選ぶ。
 * @param {object} row - 場又は期間の保存会計。
 * @param {boolean} cycle - 親組表示を選ぶか。
 * @returns {object} 利益・損失・比率・件数。
 */
function accounting(row, cycle) {
  return cycle ? {profit: row.cycle_profit, loss: row.cycle_loss, share: row.cycle_profit_share,
    payoff: row.cycle_payoff, count: row.cycles, wins: row.cycle_wins, losses: row.cycle_losses} :
    {profit: row.profit, loss: row.loss, share: row.profit_share,
      payoff: row.payoff, count: row.trades, wins: row.wins, losses: row.losses};
}

/**
 * 1件の平均利益と平均損失の比を表示する。
 * @param {number|null} value - 比率。
 * @returns {string} 倍率又は未算出表示。
 */
function ratio(value) {
  return value === null || value === undefined ? "—" : value.toFixed(2) + "倍";
}

/**
 * 保存されたセッション識別子を日本語へ整える。
 * @param {string} name - セッション識別子。
 * @returns {string} 日付とデイ／ナイト。
 */
function sessionName(name) {
  return name.replace("_Day", " デイ").replace("_Night", " ナイト");
}

/**
 * 約定仮定と会計単位の注記・見出しを統一する。
 * @param {object} chosen - 現在の選択。
 * @returns {void} 返り値なし。
 */
function notes(chosen) {
  put("model-note", chosen.model === "observed" ?
    "発動した保存観測の現在値で約定し、建値・返済線・次の注文も作り直した結果です。売買気配での約定ではありません。追加の固定時間遅延は0です。" :
    "以前の検証と同じ指定条件線で約定する仮定です。通過済みの新設条件などは次の観測価格を使います。手数料は今回も差し引いています。");
  put("account-note", chosen.cycle ?
    "親組＝初回新規から全返済まで。金額利益割合＝勝ち組利益÷（勝ち組利益＋負け組損失）。部分利確だけを勝ちと数えません。" :
    "部分決済ごとに料金後の利益・損失を分類しています。部分利確が勝ちでも、同じ親組の残玉を含めると負ける場合があります。主評価は親組へ切り替えて確認してください。");
  put("session-account-note", chosen.cycle ?
    "親組ごとの利益／損失／収支。収支の下に実際の新規枚数と返済枚数を併記します。勝ち・負け決済枚数は上部を「部分決済ごと」へ切り替えて確認できます。" :
    "部分決済ごとの利益／損失／収支。金額の下は勝ち枚数／負け枚数／勝ち−負けの差枚数です。差枚数は保有枚数や金額収支の代わりではありません。");
  document.querySelectorAll(".count-label").forEach((node) => {node.textContent = chosen.cycle ? "親組数" : "決済件数";});
  document.querySelectorAll(".delta-count-label").forEach((node) => {node.textContent = chosen.cycle ? "親組数の増減" : "決済件数の増減";});
  document.querySelectorAll(".average-label").forEach((node) => {node.textContent = chosen.cycle ? "1組平均収支" : "1決済平均収支";});
  document.querySelectorAll(".profit-label").forEach((node) => {node.textContent = chosen.cycle ? "利益／勝ち組数" : "利益／勝ち枚数";});
  document.querySelectorAll(".loss-label").forEach((node) => {node.textContent = chosen.cycle ? "損失／負け組数" : "損失／負け枚数";});
  document.querySelectorAll(".net-label").forEach((node) => {node.textContent = chosen.cycle ? "収支／新規・返済枚数" : "収支／差枚数";});
}

// ----------------------------------------
/**
 * 固定主3条件を同じ全30場・会計単位で表示する。
 * @param {object} chosen - 現在の選択。
 * @returns {void} 返り値なし。
 */
function primary(chosen) {
  const lines = [];
  for (const id of DATA.fixed.primary) {
    const result = DATA.results[chosen.model][id];
    for (const symbol of SYMBOLS) {
      const row = result.periods["全30"][symbol], a = accounting(row, chosen.cycle);
      lines.push(`<tr><th scope="row"><button class="method-link" data-method="${id}">${escapeHtml(id)}</button><small class="subvalue">${escapeHtml(result.config.name)}</small></th><td>${symbolName(symbol)}</td><td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(row.net)}</td><td>${percent(a.share)}</td><td>${ratio(a.payoff)}</td><td>${row.positive_sessions} / 30</td><td>${a.count}</td></tr>`);
    }
  }
  put("primary-results", lines.join(""));
  document.querySelectorAll("[data-method]").forEach((button) => button.addEventListener("click", () => {
    document.getElementById("method-select").value = button.dataset.method;
    render();
    document.getElementById("method-select").scrollIntoView({block:"center", behavior:"smooth"});
  }));
}

/**
 * 選択条件の入口・途中・出口と前後期間を表示する。
 * @param {object} chosen - 現在の選択。
 * @returns {void} 返り値なし。
 */
function details(chosen) {
  const description = DATA.descriptions[chosen.id];
  for (const name of ["entry", "during", "exit", "restart"]) put(name + "-description", escapeHtml(description[name]));
  const result = DATA.results[chosen.model][chosen.id], baseline = DATA.results[chosen.model].E01;
  const periods = [], changes = [];
  for (const period of ["前16", "後14", "全30"]) {
    for (const symbol of SYMBOLS) {
      const row = result.periods[period][symbol], a = accounting(row, chosen.cycle);
      const original = baseline.periods[period][symbol], b = accounting(original, chosen.cycle);
      periods.push(`<tr><th scope="row">${period}場</th><td>${symbolName(symbol)}</td><td>${amount(a.profit)}</td><td>${amount(-a.loss)}</td><td>${amount(row.net)}</td><td>${percent(a.share)}</td><td>${row.positive_sessions} / ${row.active_sessions}<small class="subvalue">無取引 ${row.no_trade_sessions}場</small></td><td>${amount(row.best_session_removed)}</td><td>${amount(-row.max_drawdown)}</td></tr>`);
      changes.push(`<tr><th scope="row">${period}場</th><td>${symbolName(symbol)}</td><td>${amount(a.profit - b.profit)}</td><td>${amount(b.loss - a.loss)}</td><td>${amount(row.net - original.net)}</td><td>${NUMBER.format(a.count - b.count)}</td><td>${amount(a.count ? row.net / a.count : null)}</td></tr>`);
    }
  }
  put("period-results", periods.join(""));
  put("change-results", changes.join(""));
}

/**
 * 商品ごとの金額3欄と数量の補助表示を作る。
 * @param {object} row - 場又は期間の会計。
 * @param {boolean} cycle - 親組会計を選ぶか。
 * @returns {string} 3個の表セル。
 */
function sessionCells(row, cycle) {
  const a = accounting(row, cycle);
  const gain = cycle ? `${a.wins}組` : `${row.winning_lots}枚`;
  const loss = cycle ? `${a.losses}組` : `${row.losing_lots}枚`;
  const net = cycle ? `新規${row.new_lots}／返済${row.exit_lots}枚` : `${NUMBER.format(row.winning_lots - row.losing_lots)}枚`;
  return `<td>${amount(a.profit)}<small class="subvalue">${gain}</small></td><td>${amount(-a.loss)}<small class="subvalue">${loss}</small></td><td>${amount(row.net)}<small class="subvalue">${net}</small></td>`;
}

/**
 * 全30場と合計を両商品同時に表示する。
 * @param {object} chosen - 現在の選択。
 * @returns {void} 返り値なし。
 */
function sessions(chosen) {
  const result = DATA.results[chosen.model][chosen.id];
  const lookup = Object.fromEntries(result.rows.map((row) => [row.session + "|" + row.symbol, row]));
  const lines = DATA.fixed["全30"].map((name) => `<tr><th scope="row">${sessionName(name)}</th>${SYMBOLS.map((symbol) => sessionCells(lookup[name + "|" + symbol], chosen.cycle)).join("")}</tr>`);
  lines.push(`<tr class="total"><th scope="row">全30場 合計</th>${SYMBOLS.map((symbol) => sessionCells(result.periods["全30"][symbol], chosen.cycle)).join("")}</tr>`);
  put("session-results", lines.join(""));
  put("quantity-note", SYMBOLS.map((symbol) => {
    const row = result.periods["全30"][symbol];
    return `${symbol === "TOPIX" ? "TOPIX" : "日経"}：新規${row.new_lots}枚／返済${row.exit_lots}枚、損益0の決済${row.flat_lots}枚、実際の同時保有最大は買い${row.max_long}枚・売り${row.max_short}枚`;
  }).join("。 ") + "。");
}

/**
 * 旧28場との接続と追加2場を表示する。
 * @param {object} chosen - 現在の選択。
 * @returns {void} 返り値なし。
 */
function previous(chosen) {
  put("old-results", DATA.old_comparison.filter((row) => row.model === chosen.model).map((row) =>
    `<tr><th scope="row">${row.id}</th><td>${symbolName(row.symbol)}</td><td>${amount(row.previous)}</td><td>${amount(row.same28)}</td><td>${amount(row.added2)}</td><td>${amount(row.total)}</td></tr>`).join(""));
}

/**
 * 主3手法に時間制御を加えた12条件を固定順で比較する。
 * @param {object} chosen - 現在の約定仮定と会計単位。
 * @returns {void} 返り値なし。
 */
function timeComparison(chosen) {
  const labels = {"": "なし", "_J": "日本開始後", "_U": "米国開始前後", "_JU": "両方"};
  const lines = [];
  for (const id of DATA.fixed.primary) {
    for (const suffix of ["", "_J", "_U", "_JU"]) {
      const result = DATA.results[chosen.model][id + suffix];
      const baseline = DATA.results[chosen.model][id];
      const cells = SYMBOLS.map((symbol) => {
        const row = result.periods["全30"][symbol], before = baseline.periods["全30"][symbol];
        const a = accounting(row, chosen.cycle);
        return `<td>${amount(row.net)}<small class="subvalue">時間返済${row.time_forced_exits}回</small></td><td>${amount(row.net - before.net)}</td><td>${percent(a.share)}</td><td>${amount(-row.max_drawdown)}</td>`;
      }).join("");
      lines.push(`<tr><th scope="row">${id}</th><td><a class="time-link" href="#sessions" data-time-method="${id + suffix}">${labels[suffix]}</a></td>${cells}</tr>`);
    }
  }
  put("time-results", lines.join(""));
  const original = DATA.results[chosen.model].E01.periods["全30"];
  const morning = DATA.results[chosen.model].E01_J.periods["全30"];
  const unchanged = SYMBOLS.every((symbol) => Math.abs(original[symbol].net - morning[symbol].net) < 0.00001 &&
    morning[symbol].time_forced_exits === 0 && morning[symbol].time_rejected_preparations === 0);
  put("time-insight", unchanged ? "原E01の朝見送りJは、両商品とも時間返済・準備見送り0件で収支不変でした。元から必要なEMAが揃うまで入らないため、今回の08:45〜09:15の制限は追加の効果を持ちませんでした。" : "時間帯の見送りは、回避する損失だけでなく、途中で確定する損益と逃す利益も含む比較です。");
  document.querySelectorAll("[data-time-method]").forEach((node) => node.addEventListener("click", () => {
    document.getElementById("method-select").value = node.dataset.timeMethod;
    render();
  }));
}

/**
 * 全表示を選択に合わせて更新する。
 * @returns {void} 返り値なし。
 */
function render() {
  const chosen = selection();
  notes(chosen); primary(chosen); details(chosen); sessions(chosen); previous(chosen); timeComparison(chosen);
}

// ----------------------------------------
document.getElementById("method-select").innerHTML = DATA.fixed.catalog.map((c) => `<option value="${c.id}">${c.id} · ${escapeHtml(c.name)}</option>`).join("");
const parameters = new URLSearchParams(location.hash.slice(1));
const requested = parameters.get("id");
document.getElementById("method-select").value = DATA.fixed.catalog.some((c) => c.id === requested) ? requested : "E01";
if (["observed", "specified"].includes(parameters.get("model"))) document.getElementById("model-select").value = parameters.get("model");
put("headline", escapeHtml(DATA.conclusion["要旨"]));
put("conclusion-note", escapeHtml(DATA.conclusion["補足"]));
for (const name of ["method-select", "model-select", "account-select"]) document.getElementById(name).addEventListener("change", render);
window.reportTest = {render, selection, accounting, sessions, sessionCells, timeComparison};
render();
