const http = require("http");
const fs = require("fs");
const path = require("path");
const assert = require("assert/strict");
const crypto = require("crypto");
const { chromium } = require("C:/Users/masay/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const assets = path.resolve(__dirname, "../../internal/webui/assets");
const csvPath = path.join(__dirname, "架空_sessionPL.csv");
const products = ["NK225", "NK225mini", "NK225micro", "TOPIX", "TOPIXmini"];
const header = "\ufeff利益,損失,収支,新規建合計qty,セッション,銘柄,モード\n";
const fixtures = ["12000,2000,10000,3,2026-10-26_Day,NK225mini,live", "500,1500,-1000,2,2026-10-26_Day,NK225mini,dryrun", "26000,7000,19000,6,2026-10-27_Night,TOPIXmini,dryrun", "0,0,0,0,2026-10-27_Day,NK225micro,live"];
const settings = {
  revision: "ui-fixture", web: {host:"127.0.0.1",port:18091},
  controller:{base_url:"http://127.0.0.1:1",request_timeout_seconds:5,history_timeout_seconds:60,account_poll_seconds:1,candle_poll_seconds:2,reconnect_seconds:3},
  schedule:{force_close_before_seconds:600,extra_cutoff_seconds:600,day_extra_jst:"13:00",us_open_jst:"23:30",london_extra_jst:"17:30",us_extra_delay_minutes:10},
  runtime:{data_directory:"data",log_directory:"log",quote_max_age_seconds:10,account_max_age_seconds:5,reconnect_grace_seconds:5,checkpoint_seconds:10,status_seconds:10,shutdown_seconds:20,entry_order_timeout_seconds:10},
  instruments:products.map(product=>({product,mode:"off",max_per_side:10,day:product.startsWith("NK225")?"NK225_D164_15":"TOPIX_T06",night:product.startsWith("NK225")?"NK225_U165_03":"TOPIX_T04"}))
};
let readFailure = false;
let saveFailure = "";
let reads = 0;
const writes = [];
const errors = [];
const checks = [];

/**
 * 全商品OFFの人工状態を作ります。実サービスには接続しません。
 * @returns {object} 状態取得APIの人工応答。
 */
function state() {
  return {csrf_token:"local-ui-only",server_time:new Date().toISOString(),settings_revision:settings.revision,controller_url:settings.controller.base_url,report_error:saveFailure,products:settings.instruments.map(v=>({...v,active_mode:"off",pending:false,error:"",settings_editable:true,status:"停止中",day_method:v.day,night_method:v.night}))};
}

/**
 * ローカル試験用JSONを返します。
 * @param {http.ServerResponse} response - 応答先。
 * @param {number} code - HTTPコード。
 * @param {object} body - JSON本体。
 * @returns {void} 返り値はありません。
 */
function json(response, code, body) {response.writeHead(code,{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store"});response.end(JSON.stringify(body));}

/**
 * 静的画面と架空CSVだけを配信し、変更要求は全件記録して拒否します。
 * @param {http.IncomingMessage} request - ローカル要求。
 * @param {http.ServerResponse} response - 応答先。
 * @returns {void} 返り値はありません。
 */
function handle(request,response) {
  if(request.method!=="GET"){writes.push(request.url);return json(response,405,{error:"人工試験では更新不可"});}
  if(request.url==="/api/state")return json(response,200,state());
  if(request.url==="/api/settings")return json(response,200,settings);
  if(request.url==="/api/rules")return json(response,200,{rules:[]});
  if(request.url==="/api/session-pl"){
    reads++;
    if(readFailure)return json(response,500,{error:"人工試験: セッション損益CSVの読取失敗"});
    const rows=fs.existsSync(csvPath)?fs.readFileSync(csvPath,"utf8").trim().split(/\r?\n/).slice(1).map(line=>{const [profit,loss,net,qty,session,product,mode]=line.split(",");return {session,product,mode,profit:Number(profit),loss:Number(loss),net:Number(net),entry_qty:Number(qty)};}):[];
    return json(response,200,{rows});
  }
  const name=request.url==="/"?"index.html":request.url.slice(1);
  if(!["index.html","app.js","style.css"].includes(name)){response.writeHead(404);return response.end();}
  response.writeHead(200,{"Content-Type":name.endsWith(".js")?"text/javascript; charset=utf-8":name.endsWith(".css")?"text/css; charset=utf-8":"text/html; charset=utf-8"});response.end(fs.readFileSync(path.join(assets,name)));
}

/**
 * 一覧・フィルタ・異常・削除・自動更新・モバイルを架空データで確認します。
 * @returns {Promise<void>} ローカル検査の完了。売買操作は行いません。
 */
async function main(){
  fs.writeFileSync(csvPath,header+fixtures.join("\n")+"\n","utf8");
  const server=http.createServer(handle);await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  const browser=await chromium.launch({executablePath:"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:950},locale:"ja-JP"});page.on("pageerror",e=>errors.push(e.message));
    await page.route("**/*",route=>{const url=new URL(route.request().url());if(url.hostname!=="127.0.0.1")throw new Error("ローカル外へ接続しようとしました");return route.continue();});
    await page.goto("http://127.0.0.1:"+server.address().port);
    await page.waitForFunction(()=>document.querySelectorAll('.mode-button[data-mode="off"][aria-pressed="true"]').length===5);
    assert.equal(reads,0);checks.push("全商品OFF・損益タブ以外は未取得");
    await page.locator("#nav-session-pl").click();await page.waitForFunction(()=>document.querySelectorAll("#session-pl-rows tr").length===4);
    assert.match(await page.locator("#session-pl-rows tr").first().textContent(),/2026-10-27 夜間/);
    assert.match(await page.locator("#session-pl-rows").textContent(),/−1,000/);
    assert.equal(await page.locator("#session-pl-rows td").filter({hasText:/^1,500$/}).count(),1);checks.push("日付降順・損失正額・収支符号・無取引0円");
    await page.screenshot({path:path.join(__dirname,"セッション損益_デスクトップ.png"),fullPage:true});
    await page.locator("#session-pl-product").selectOption("NK225mini");assert.equal(await page.locator("#session-pl-rows tr").count(),2);
    await page.locator("#session-pl-mode").selectOption("live");assert.equal(await page.locator("#session-pl-rows tr").count(),1);assert.match(await page.locator("#session-pl-rows").textContent(),/\+10,000/);
    await page.locator("#session-pl-product").selectOption("TOPIXmini");assert.equal(await page.locator("#session-pl-rows tr").count(),0);assert.match(await page.locator("#session-pl-empty-title").textContent(),/この条件に一致/);checks.push("商品と実仮想の複合フィルタ・該当なし");
    await page.locator("#session-pl-product").selectOption("");await page.locator("#session-pl-mode").selectOption("");
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(__dirname,"セッション損益_モバイル.png"),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
    assert.equal(await page.locator("#session-pl-table-wrap").evaluate(n=>n.scrollWidth>n.clientWidth),true);checks.push("モバイルは表内だけ横スクロール");
    await page.setViewportSize({width:1440,height:950});
    readFailure=true;const previous=await page.locator("#session-pl-updated").textContent();await page.locator("#session-pl-refresh").click();await page.waitForSelector("#session-pl-error:not([hidden])");
    assert.equal(await page.locator("#session-pl-rows tr").count(),4);assert.equal(await page.locator("#session-pl-updated").textContent(),previous);assert.match(await page.locator("#session-pl-status").textContent(),/前回取得/);checks.push("読取500は前回表示と成功時刻を維持・失敗を明示");
    await page.screenshot({path:path.join(__dirname,"セッション損益_読取失敗.png"),fullPage:true});
    readFailure=false;fs.unlinkSync(csvPath);await page.locator("#session-pl-refresh").click();await page.waitForFunction(()=>!document.getElementById("session-pl-empty").hidden&&document.getElementById("session-pl-error").hidden);
    assert.equal(await page.locator("#session-pl-rows tr").count(),0);assert.match(await page.locator("#session-pl-empty-title").textContent(),/記録はまだ/);checks.push("CSV削除後は古い表を消し正常な空状態");
    await page.screenshot({path:path.join(__dirname,"セッション損益_記録なし.png"),fullPage:true});
    fs.writeFileSync(csvPath,header+fixtures.slice(0,2).join("\n")+"\n","utf8");await page.waitForFunction(()=>document.querySelectorAll("#session-pl-rows tr").length===2,{},{timeout:9000});checks.push("5秒定期取得でCSV追加を反映");
    await page.locator("#nav-dashboard").click();const count=reads;await page.waitForTimeout(5200);assert.equal(reads,count);checks.push("別タブでは損益定期取得を停止");
    saveFailure="人工試験: 集計ファイルを保存できません";await page.waitForSelector("#report-save-alert:not([hidden])");assert.match(await page.locator("#report-save-alert").textContent(),/セッションレポート保存失敗/);checks.push("保存失敗はCSV欠損と別に全ページ表示");
    assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);checks.push("変更API要求0・ブラウザ例外0");
    const sources=["index.html","app.js","style.css"].map(name=>({path:path.join(assets,name),sha256:crypto.createHash("sha256").update(fs.readFileSync(path.join(assets,name))).digest("hex")}));
    fs.writeFileSync(path.join(__dirname,"画面検査.json"),JSON.stringify({passed:true,checks,source:"全商品OFFの人工APIと架空CSV。実サービス接続0、売買操作0。Go RESTは別のsession_pl_test.goで検査。",sources,screenshots:fs.readdirSync(__dirname).filter(n=>n.endsWith(".png")),errors,writes},null,2)+"\n");
    console.log(JSON.stringify({passed:true,checks:checks.length,reads,errors,writes}));
  }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
