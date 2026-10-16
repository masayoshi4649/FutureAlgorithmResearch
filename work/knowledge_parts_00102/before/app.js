"use strict";

/**
 * データを表示するDOM要素を作ります。文字列をHTMLとして実行しません。
 * @param {string} tag - 要素名。
 * @param {string} text - 表示する文字列。
 * @param {string} className - 任意のCSSクラス。
 * @returns {HTMLElement} 作成した要素。
 */
function element(tag, text = "", className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

/**
 * プロジェクト内の根拠への相対リンクを作ります。
 * @param {string} path - ルートからの相対パス。
 * @param {string} label - 表示名。
 * @returns {HTMLElement} 有効なリンク又は不正パスを示す文字。
 */
function sourceLink(path, label) {
  const parts = String(path).replaceAll("\\", "/").split("/");
  if (parts.some(part => !part || part === ".." || part.includes(":"))) return element("span", "不正な根拠パス");
  const link = element("a", label);
  link.href = "../../../" + parts.map(encodeURIComponent).join("/");
  return link;
}

/**
 * 名称と内容の対応を並べます。
 * @param {Array<Array<string>>} pairs - 表示する名称と内容。
 * @returns {HTMLElement} 説明リスト。
 */
function description(pairs) {
  const list = element("dl");
  for (const [label, value] of pairs) {
    if (!value) continue;
    list.append(element("dt", label), element("dd", typeof value === "string" ? value : JSON.stringify(value, null, 2)));
  }
  return list;
}

/**
 * 知見・試行・監査・資料に共通するカードを作ります。
 * @param {object} row - JSONの登録内容。
 * @param {string} tab - 表示種別。
 * @returns {HTMLElement} 根拠付きの閲覧カード。
 */
function card(row, tab) {
  const box = element("article", "", "record");
  box.dataset.id = row.id;
  const meta = element("div", "", "meta");
  meta.append(element("span", row.id), element("span", row.status || "索引のみ", "badge" + (/未|失敗|不足|仮説/.test(row.status || "") ? " pending" : "")));
  box.append(meta, element("h2", row.title || row.name));
  if (tab === "findings") box.append(element("p", row.claim), description([["適用範囲", row.scope], ["次の判断", row.action]]));
  if (tab === "trials") {
    box.append(description([["確かめること", row.question], ["前回との差", row.change], ["結果", row.result], ["再検証の理由", row.repeat_reason], ["比較上の注意", row.limitations]]));
    if (row.spec || row.parameters || row.parts) {
      const details = element("details");
      details.append(element("summary", row.spec ? "機械照合用の条件" : "保存された条件・入口／途中／出口"), element("pre", JSON.stringify(row.spec || row.parameters || row.parts, null, 2)));
      box.append(details);
    }
  }
  if (tab === "repetition") box.append(description([["確認内容", row.finding], ["扱い", row.action], ["範囲", row.scope]]));
  if (tab === "studies") box.append(element("p", row.summary || "内容の詳細な登録は未完了です。"), element("p", "資料の存在を登録した索引です。結論の再監査完了を意味しません。", "muted"));
  const links = element("div", "", "sources");
  for (const [index, source] of (row.evidence || []).entries()) links.append(sourceLink(source.path, source.label || "根拠 " + (index + 1)));
  if (row.readme) links.append(sourceLink(row.readme, "読む順序"));
  if (row.report) links.append(sourceLink(row.report, "レポート"));
  box.append(links);
  return box;
}

// ----------------------------------------
// 検索と表示状態はビューだけが管理し、正本のデータは書き換えません。

/**
 * JSONから生成したローカル用データを接続し、検索・タブを有効にします。
 * @returns {void} 表示を初期化します。データ不足はエラー表示にします。
 */
function start() {
  const data = window.KNOWLEDGE_DATA;
  if (!data || !data.knowledge || !data.trials || !data.studies) {
    document.getElementById("load-error").hidden = false;
    document.getElementById("coverage").textContent = "読み込み失敗。結論は表示していません。";
    return;
  }
  const records = {findings: data.knowledge.findings, trials: data.trials.trials, repetition: data.trials.repetition_audit, studies: data.studies.studies};
  let tab = "findings";
  const query = document.getElementById("query"), state = document.getElementById("state");
  const target = document.getElementById("records");
  document.getElementById("coverage").textContent = data.knowledge.coverage;
  const updated = [data.knowledge.updated_at, data.trials.updated_at, data.studies.updated_at].sort().at(-1);
  document.getElementById("updated").textContent = "更新：" + updated + " ／ 正本：data/*.json ／ この画面はローカルファイルのまま開けます。";

  /**
   * 現在の検索条件に一致する登録を描画します。
   * @returns {void} 表示件数とカードを更新します。
   */
  function render() {
    const words = query.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    const selected = records[tab].filter(row => (!state.value || (row.status || "索引のみ") === state.value) && words.every(word => JSON.stringify(row).toLocaleLowerCase().includes(word)));
    target.replaceChildren(...selected.map(row => card(row, tab)));
    if (!selected.length) target.append(element("p", "該当する登録はありません。未登録・未整理の試行がないことを意味しません。", "empty"));
    document.getElementById("count").textContent = selected.length + " / " + records[tab].length + " 件";
  }

  /**
   * タブを切り替え、選択できる状態を当該資料から作ります。
   * @param {string} name - 切替先の種別。
   * @returns {void} タブ・状態選択・検索結果を更新します。
   */
  function switchTab(name) {
    if (!records[name]) return;
    tab = name;
    const states = [...new Set(records[tab].map(row => row.status || "索引のみ"))].sort();
    state.replaceChildren(new Option("すべて", ""), ...states.map(value => new Option(value, value)));
    document.querySelectorAll("[data-tab]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.tab === tab)));
    render();
  }
  document.querySelectorAll("[data-tab]").forEach(button => button.addEventListener("click", () => switchTab(button.dataset.tab)));
  document.getElementById("search-form").addEventListener("submit", event => event.preventDefault());
  query.addEventListener("input", render);
  state.addEventListener("change", render);
  const requested = new URLSearchParams(location.search).get("tab");
  switchTab(records[requested] ? requested : "findings");
}

start();
