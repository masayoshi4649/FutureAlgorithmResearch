"use strict";
const DATA = JSON.parse(document.getElementById("report-data").textContent);
const NUMBER = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 0 });

/**
 * 数値を円表示にする。
 * @param {number|null} value - 金額。
 * @returns {string} ＋符号を付けず、負のゼロを正規化した表示。
 */
function money(value) {
  if (value === null || value === undefined) return "—";
  return NUMBER.format(value === 0 ? 0 : value) + "円";
}

/**
 * 比率を百分率で表示する。
 * @param {number|null} value - 比率。
 * @returns {string} 小数第一位までの割合。
 */
function percent(value) {
  return value === null || value === undefined ? "—" : (value * 100).toFixed(1) + "%";
}

/**
 * 表示文字をHTMLに安全に埋め込む。
 * @param {unknown} value - 文字列へ変換する値。
 * @returns {string} 特殊文字を置換した値。
 */
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

/**
 * 金額に応じた色付き要素を作る。
 * @param {number} value - 符号付き金額。
 * @returns {string} 正負を色分けしたHTML。
 */
function amount(value) {
  const type = value < 0 ? "loss" : value > 0 ? "gain" : "neutral";
  return `<span class="number ${type}">${money(value)}</span>`;
}

/**
 * 商品名を表示用へ変換する。
 * @param {string} symbol - 保存された商品キー。
 * @returns {string} 枚数も含めた商品名。
 */
function symbolName(symbol) {
  return symbol === "TOPIX" ? "TOPIXミニ（片方向上限10枚）" : "日経マイクロ（片方向上限20枚）";
}

/**
 * 要素へHTMLを設定する。
 * @param {string} id - 対象要素ID。
 * @param {string} markup - HTML文字列。
 * @returns {void} 返り値なし。
 */
function put(id, markup) {
  document.getElementById(id).innerHTML = markup;
}
