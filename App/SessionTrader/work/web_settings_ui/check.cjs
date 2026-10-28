const http = require("http");
const fs = require("fs");
const path = require("path");
const assert = require("assert/strict");
const { chromium } = require("C:/Users/masay/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const root = path.resolve(__dirname, "../../internal/webui/assets");
const products = ["NK225", "NK225mini", "NK225micro", "TOPIX", "TOPIXmini"];
let revision = 1;
let failure = "";
let offline = false;
let pendingProduct = "";
const writes = [];
const errors = [];
let settings = {
  revision: "1",
  web: { host: "127.0.0.1", port: 18090 },
  controller: { base_url: "http://127.0.0.1:18080", request_timeout_seconds: 5, history_timeout_seconds: 60, account_poll_seconds: 1, candle_poll_seconds: 2, reconnect_seconds: 3, future_option: "維持" },
  schedule: { force_close_before_seconds: 30, extra_cutoff_seconds: 60, day_extra_jst: "13:00", us_open_jst: "23:30", london_extra_jst: "17:30", us_extra_delay_minutes: 10 },
  runtime: { data_directory: "data", log_directory: "log", quote_max_age_seconds: 10, account_max_age_seconds: 5, reconnect_grace_seconds: 5, checkpoint_seconds: 10, status_seconds: 10, shutdown_seconds: 20, entry_order_timeout_seconds: 10 },
  instruments: products.map(product => ({ product, mode: "off", max_per_side: 10, day: product.startsWith("NK225") ? "NK225_T06" : "TOPIX_T06", night: product.startsWith("NK225") ? "NK225_U06" : "TOPIX_T04" })),
  future_settings: { preserved: true }
};
const rules = [
  { name: "NK225_T06", reference: "NK225", file: "NK225_T06.toml", day: true, night: false, supported: true, reason: "" },
  { name: "NK225_U06", reference: "NK225", file: "NK225_U06.toml", day: false, night: true, supported: true, reason: "" },
  { name: "NK225_D07", reference: "NK225", file: "NK225_D07.toml", day: true, night: false, supported: true, reason: "" },
  { name: "NK225_TG04", reference: "NK225", file: "NK225_TG04.toml", day: false, night: true, supported: true, reason: "" },
  { name: "NK225_PG04", reference: "NK225", file: "NK225_PG04.toml", day: false, night: true, supported: true, reason: "" },
  { name: "TOPIX_T06", reference: "TOPIX", file: "TOPIX_T06.toml", day: true, night: false, supported: true, reason: "" },
  { name: "TOPIX_T04", reference: "TOPIX", file: "TOPIX_T04.toml", day: false, night: true, supported: true, reason: "" },
  { name: "NK225_未対応", reference: "NK225", file: "NK225_未対応.toml", day: false, night: false, supported: false, reason: "実行方式が未対応です" }
];

/**
 * モック状態を作成します。実際の売買システムには接続しません。
 * @returns {object} モック状態。
 */
function state() {
  return {
    csrf_token: "local-test-only", server_time: new Date().toISOString(), settings_revision: settings.revision,
    controller_url: settings.controller.base_url, restart_required: false, closing: false,
    products: settings.instruments.map(item => ({
      product: item.product, mode: item.mode, active_mode: item.product === pendingProduct ? "dryrun" : item.mode,
      status: item.product === pendingProduct ? "停止処理中" : item.mode === "off" ? "停止・建玉は手動管理" : "運転中",
      max_per_side: item.max_per_side, day_method: item.day, night_method: item.night,
      pending: item.product === pendingProduct, error: "", settings_editable: item.mode === "off" && item.product !== pendingProduct, settings_block_reason: item.mode !== "off" ? "数量・手法はOFFにしてから変更できます" : item.product === pendingProduct ? "注文の取消・照合を待っています" : "",
      snapshot: { buy_quantity: 2, sell_quantity: 0, realized_yen: 12800, unrealized_yen: -900, session_realized_yen: 12800, session: "20261026_Day", received_at: new Date().toISOString(), product_received_at: new Date().toISOString(), decision_at: new Date().toISOString(), pending: false, queued: 0 }
    }))
  };
}

/**
 * JSON形式でモック応答を返します。
 * @param {object} response - HTTP応答。
 * @param {number} status - HTTP状態コード。
 * @param {object} value - 応答内容。
 * @returns {void} 返り値はありません。
 */
function json(response, status, value) {
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(value));
}

/**
 * 静的画面とモックAPIをローカルだけに配信します。
 * @param {object} request - HTTP要求。
 * @param {object} response - HTTP応答。
 * @returns {Promise<void>} 応答処理の完了。
 */
async function handle(request, response) {
  if (request.method === "PUT") {
    let body = "";
    for await (const chunk of request) body += chunk;
    const value = JSON.parse(body);
    writes.push({ path: request.url, value, csrf: request.headers["x-csrf-token"] });
    await new Promise(resolve => setTimeout(resolve, 400));
    if (failure === "server") { failure = ""; return json(response, 500, { error: "検証用: 保存に失敗しました" }); }
    if (failure === "conflict") { failure = ""; settings.revision = String(++revision); return json(response, 409, { error: "設定が変更されています。最新設定を読み込んでください。" }); }
    if (value.revision !== settings.revision) return json(response, 409, { error: "設定の版が異なります" });
    if (request.url === "/api/settings") settings = value;
    else {
      const product = decodeURIComponent(request.url.split("/")[3]);
      const item = settings.instruments.find(entry => entry.product === product);
      if (request.url.endsWith("/mode")) item.mode = value.mode;
      else Object.assign(item, { max_per_side: value.max_per_side, day: value.day, night: value.night });
    }
    settings.revision = String(++revision);
    return json(response, 200, { settings, state: state(), message: "検証用: 設定を保存しました", restart_required: request.url === "/api/settings" });
  }
  if (request.url === "/api/state") return json(response, offline ? 503 : 200, offline ? { error: "検証用: 通信停止" } : state());
  if (request.url === "/api/settings") return json(response, 200, settings);
  if (request.url === "/api/rules") return json(response, 200, { rules });
  const name = request.url === "/" ? "index.html" : request.url.slice(1);
  if (!["index.html", "app.js", "style.css"].includes(name)) { response.writeHead(404); return response.end(); }
  response.writeHead(200, { "Content-Type": name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : "text/html; charset=utf-8" });
  response.end(fs.readFileSync(path.join(root, name)));
}

/**
 * デスクトップとモバイルでフォーム、競合、操作制限を検証します。
 * @returns {Promise<void>} 検証処理の完了。
 */
async function main() {
  const server = http.createServer(handle);
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({ executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, locale: "ja-JP" });
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("http://127.0.0.1:" + server.address().port);
    const card = page.locator('[data-product="NK225mini"]');
    const gear = card.locator(".settings-button");
    await gear.waitFor({ state: "visible" });
    await page.waitForFunction(() => !document.querySelector('[data-product="NK225mini"] .settings-button').disabled);
    assert.equal(await card.locator(".position b").first().textContent(), "0", "OFF後の旧玉を担当保有へ合算しません");
    await gear.click();
    assert.equal(await page.locator("#product-quantity").inputValue(), "10");
    assert.equal(await page.locator("#product-day option").count(), 3);
    assert.equal(await page.locator("#product-night option").count(), 4);
    assert.equal(await page.locator('#product-day option[value="TOPIX_T06"]').count(), 0, "別市場の手法を候補に含めません");
    assert.equal(await page.locator('#product-day option[value="NK225_未対応"]').isDisabled(), true);
    for (let index = 0; index < 12; index++) {
      await page.keyboard.press("Tab");
      assert.equal(await page.evaluate(() => document.activeElement.closest("dialog") !== null), true, "フォーカスがモーダル内に留まります");
    }
    await page.locator("#product-quantity").fill("12");
    await page.keyboard.press("Escape");
    assert.equal(writes.length, 0, "閉じるだけでは保存しません");
    assert.equal(await gear.evaluate(node => node === document.activeElement), true);

    // ----------------------------------------
    await gear.click();
    assert.equal(await page.locator("#product-quantity").inputValue(), "10");
    await page.locator("#product-quantity").fill("12");
    failure = "server";
    await page.locator("#product-save").click();
    assert.equal(await page.locator("#product-cancel").isDisabled(), true, "保存中は重複操作を止めます " + JSON.stringify({ errors, writes }));
    await page.waitForSelector("#product-error:not([hidden])");
    assert.equal(await page.locator("#product-quantity").inputValue(), "12");
    await page.waitForFunction(() => !document.getElementById("product-save").disabled);
    await page.locator("#product-save").click();
    await page.waitForSelector("#product-dialog:not([open])", { state: "attached" });
    assert.equal(settings.instruments[1].max_per_side, 12);
    assert.equal(writes[0].csrf, "local-test-only");
    await gear.click();
    await page.locator("#product-quantity").fill("13");
    failure = "conflict";
    await page.locator("#product-save").click();
    await page.waitForSelector("#product-error:not([hidden])");
    await page.waitForFunction(() => document.getElementById("product-save-status").textContent.includes("開き直し"));
    assert.equal(await page.locator("#product-quantity").inputValue(), "13");
    assert.equal(await page.locator("#product-save").isDisabled(), true);
    await page.locator("#product-cancel").click();

    // ----------------------------------------
    await card.locator('[data-mode="dryrun"]').click();
    assert.equal(await card.locator('[data-mode="off"]').getAttribute("aria-pressed"), "true", "保存前は選択状態を変えません");
    await page.waitForFunction(() => document.querySelector('[data-product="NK225mini"] [data-mode="dryrun"]').getAttribute("aria-pressed") === "true");
    assert.equal(await gear.isDisabled(), true, "運転中の商品設定を無効化します");
    await page.waitForFunction(() => !document.querySelector('[data-product="NK225mini"] [data-mode="off"]').disabled);
    await card.locator('[data-mode="off"]').click();
    await page.waitForFunction(() => !document.querySelector('[data-product="NK225mini"] .settings-button').disabled);
    const beforeLive = writes.length;
    await card.locator('[data-mode="live"]').click();
    assert.equal(await card.locator(".confirm-panel").isVisible(), true);
    await card.locator(".confirm-actions .secondary").click();
    assert.equal(writes.length, beforeLive, "実取引は確認前に送信しません");
    pendingProduct = "NK225mini";
    await page.waitForFunction(() => !document.querySelector('[data-product="NK225mini"] .settings-pending').hidden);
    assert.equal(await gear.isDisabled(), true, "停止の照合中は商品設定を変更できません");
    pendingProduct = "";
    await page.waitForFunction(() => !document.querySelector('[data-product="NK225mini"] .settings-button').disabled);

    // ----------------------------------------
    await page.locator("#nav-settings").click();
    await page.locator("#schedule-us_open_jst").fill("23:45");
    await page.waitForTimeout(2200);
    assert.equal(await page.locator("#schedule-us_open_jst").inputValue(), "23:45", "定期更新は未保存入力を上書きしません");
    settings.revision = String(++revision);
    settings.schedule.us_open_jst = "23:10";
    await page.waitForSelector("#settings-conflict:not([hidden])");
    assert.equal(await page.locator("#schedule-us_open_jst").inputValue(), "23:45");
    assert.equal(await page.locator("#global-save").isDisabled(), true);
    await page.locator("#global-reset").click();
    assert.equal(await page.locator("#schedule-us_open_jst").inputValue(), "23:10");
    await page.locator("#schedule-us_open_jst").fill("23:30");
    await page.locator("#web-port").fill("18091");
    await page.locator("#global-save").click();
    await page.waitForFunction(() => document.getElementById("settings-status").textContent === "すべて保存済み");
    assert.equal(settings.schedule.us_open_jst, "23:30");
    assert.equal(settings.controller.future_option, "維持", "未編集の追加項目を保持します");
    assert.equal(settings.future_settings.preserved, true);
    assert.equal(settings.instruments[1].max_per_side, 12);
    assert.equal(await page.locator("#restart-alert").isVisible(), true);
    await page.screenshot({ path: path.join(__dirname, "desktop-settings.png"), fullPage: true });

    // ----------------------------------------
    settings.instruments[0].mode = "dryrun";
    settings.instruments[2].mode = "live";
    settings.revision = String(++revision);
    await page.waitForSelector("#settings-lock:not([hidden])");
    await page.locator("#schedule-us_open_jst").fill("22:45");
    assert.equal(await page.locator("#global-save").isDisabled(), true, "商品運転中は全般設定を保存できません");
    await page.locator("#global-reset").click();
    await page.locator("#nav-dashboard").click();
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(__dirname, "desktop-dashboard.png"), fullPage: true });
    await gear.click();
    await page.screenshot({ path: path.join(__dirname, "desktop-modal.png") });
    await page.locator("#product-cancel").click();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(__dirname, "mobile-dashboard.png"), fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "モバイル画面で横にはみ出しません");
    await gear.click();
    await page.screenshot({ path: path.join(__dirname, "mobile-modal.png") });
    assert.equal(await page.locator("#product-dialog").evaluate(node => node.scrollWidth <= node.clientWidth), true, "商品モーダルは横にはみ出しません");
    await page.locator("#product-cancel").click();
    await page.locator("#nav-settings").click();
    await page.screenshot({ path: path.join(__dirname, "mobile-settings.png"), fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "全般設定は横にはみ出しません");
    offline = true;
    await page.waitForSelector("#connection-alert:not([hidden])");
    assert.equal(await page.locator("#schedule-us_open_jst").isDisabled(), true);
    assert.equal(writes.some(write => write.value.mode === "live"), false, "実取引への保存要求は一切実行していません");
    assert.deepEqual(errors, [], "ブラウザ実行エラーがありません");
    console.log(JSON.stringify({ result: "成功", checks: "商品保存・エラー・版競合・入力保持・候補適合・モード保存・停止待ち・運転中編集拒否・全般保存・追加項目保持・通信失敗・モバイル・フォーカス", writes: writes.length, liveRequests: 0, screenshots: 6 }));
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
