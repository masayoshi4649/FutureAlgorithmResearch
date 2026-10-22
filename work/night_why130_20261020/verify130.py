"""公開HTMLの全条件・全場・累計と暗色画面を独立照合する。"""

import base64
import json
import re
import socket
import subprocess
import time
import urllib.request
from urllib.parse import unquote, urlparse
import websocket
from common130 import HERE, PUBLIC, read, save, reference


JAVASCRIPT = r"""
/**
 * 保存JSONと画面の全選択・全場・合計を照合する。
 * 引数: なし。画面のDOMを参照する。
 * 返り値: objectは合否・検査数・画面寸法。
 */
function verifyAll(){
 const day=document.getElementById("day-method"),night=document.getElementById("night-method");
 const prev=[day.value,night.value],data=JSON.parse(document.getElementById("saved-data").textContent);
 let checks=0,combinations=0;
 function check(ok,label){checks++;if(!ok)throw Error(label);}
 function number(s){return Number(s.replaceAll(",","").replaceAll("+",""));}
 for(const d of [...day.options])for(const n of [...night.options]){
  day.value=d.value;night.value=n.value;update();
  const selected=data.rows.filter(r=>{
   const m=r.kind==="Night"?n.value:d.value==="別"?(r.symbol==="TOPIX"?"DV07":"DV05"):d.value;
   return r.method===m;
  });
  const dates=[...new Set(selected.map(r=>r.session))].sort(),shown=[...document.querySelectorAll("#session-body tr")];
  check(dates.length===43&&shown.length===43,"全43場");
  const totals={TOPIX:[0,0,0],NK225:[0,0,0]};
  dates.forEach((date,i)=>{
   const cells=[...shown[i].cells];
   check(cells[0].textContent===date.replace("_Day"," デイ").replace("_Night"," ナイト"),"日付");
   ["TOPIX","NK225"].forEach((symbol,k)=>{
    const r=selected.find(r=>r.session===date&&r.symbol===symbol),t=totals[symbol];
    [r.profit,r.loss,r.net].forEach((v,j)=>t[j]+=v);
    [r.profit,-r.loss,r.net,t[2]].forEach((v,j)=>check(number(cells[1+4*k+j].textContent)===Math.round(v),"場セル"));
   });
  });
  const cells=[...document.querySelector("#session-total tr").cells];
  ["TOPIX","NK225"].forEach((symbol,k)=>{
   const t=totals[symbol];
   [t[0],-t[1],t[2],t[2]].forEach((v,j)=>check(number(cells[1+4*k+j].textContent)===Math.round(v),"合計"));
  });
  check(document.querySelectorAll("#selected-summary article").length===4,"概要4組");
  combinations++;
 }
 day.value=prev[0];night.value=prev[1];update();
 const shown=[...document.querySelectorAll("#all-comparison tbody tr")];
 check(shown.length===data.summary.length,"全条件数");
 data.summary.forEach((s,i)=>{
  const cells=[...shown[i].cells],r=s.regimes;
  check(cells[0].textContent===s.method&&cells[1].textContent===s.symbol,"手法商品");
  [[2,s.net],[4,s.worst],[5,s.without_top3],[6,r["上昇"]?.net||0],
   [7,r["下落"]?.net||0],[8,r["同値"]?.net||0],[9,s.halves["後半"].net]]
   .forEach(([j,v])=>check(number(cells[j].textContent)===Math.round(v),"比較値"));
  check(s.black+s.red+s.flat+s.breakeven===s.sessions,"分母");
 });
 check(document.documentElement.scrollWidth<=innerWidth+1,"横はみ出し");
 return {passed:true,checks,combinations,viewport:[innerWidth,innerHeight]};
}
verifyAll();
"""


def main():
    """
    機能: 保存値・リンクを確認し、隔離Chromeで全選択と実幅390/1600を検査する。
    引数: なし。公開HTMLと最終会計を参照する。
    返り値: None。スクリーンショットと証跡を保存する。
    """
    report = PUBLIC / "夜間のなぜ三段階と改善後の損益.html"
    document = report.read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script type="application/json" id="saved-data">(.*?)</script>',
                               document, re.S)[1])
    source = read(HERE / "最終全場比較_確定.json")
    assert data["rows"] == source["rows"] and data["summary"] == source["summary"]
    links = []
    for value in re.findall(r'(?:href|src)="([^"]+)"', document):
        parsed = urlparse(value)
        if parsed.scheme or value.startswith("#"):
            continue
        assert (PUBLIC / unquote(parsed.path)).exists(), value
        links.append(value)
    folder = HERE / "表示確認"
    folder.mkdir(exist_ok=True)
    target = folder / "確認画面.html"
    target.write_text(document.replace("<title>", f'<base href="{PUBLIC.as_uri()}/"><title>', 1)
                      .replace("</body>", "<script>" + JAVASCRIPT + "</script></body>"), encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    command = ["C:/Program Files/Google/Chrome/Application/chrome.exe",
               "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               "--disable-background-networking", "--disable-extensions", "--hide-scrollbars",
               "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}",
               f"--remote-allow-origins=http://127.0.0.1:{port}",
               "--user-data-dir=" + str(folder / f"profile_{time.time_ns()}"), target.as_uri()]
    records = []
    connection = None
    with (folder / "ブラウザー記録.txt").open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            address = None
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as reply:
                        tabs = json.load(reply)
                    address = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
                    break
                except (OSError, StopIteration):
                    time.sleep(.1)
            assert address
            connection = websocket.create_connection(address, origin=f"http://127.0.0.1:{port}", timeout=30)
            sequence = 0

            def call(method, parameters=None):
                """
                機能: 隔離したブラウザーへ検査要求を送る。
                引数: method(str)、parameters(dict又はNone)は操作。
                返り値: dictは処理結果。
                """
                nonlocal sequence
                sequence += 1
                connection.send(json.dumps(dict(id=sequence, method=method, params=parameters or {})))
                while True:
                    answer = json.loads(connection.recv())
                    if answer.get("id") == sequence:
                        assert "error" not in answer, answer
                        return answer["result"]

            def evaluate(expression):
                """
                機能: 画面の検査式を実行する。
                引数: expression(str)は検査式。
                返り値: objectは式の値。
                """
                answer = call("Runtime.evaluate", dict(expression=expression, awaitPromise=True, returnByValue=True))
                assert "exceptionDetails" not in answer, answer
                return answer["result"].get("value")

            for _ in range(100):
                if evaluate('document.readyState==="complete" && typeof verifyAll==="function"'):
                    break
                time.sleep(.1)
            else:
                raise AssertionError("画面未完成")
            # ----------------------------------------
            # 見かけのウィンドウ指定ではなくCSSの実表示幅を固定する。
            for name, width, height, scroll in (
                    ("全体", 1600, 1250, False), ("全場表", 1600, 1050, True), ("狭幅", 390, 1000, False)):
                call("Emulation.setDeviceMetricsOverride", dict(width=width, height=height, deviceScaleFactor=1, mobile=False))
                proof = evaluate("verifyAll()")
                assert proof["passed"] and proof["viewport"] == [width, height]
                evaluate("document.getElementById('selected-summary').scrollIntoView()" if scroll else "window.scrollTo(0,0)")
                evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))")
                time.sleep(.2)
                encoded = call("Page.captureScreenshot", dict(format="png", fromSurface=True, captureBeyondViewport=False))["data"]
                image = folder / (name + ".png")
                image.write_bytes(base64.b64decode(encoded))
                records.append(dict(name=name, **proof, image=reference(image)))
                print(name, proof["combinations"], "組合せ", proof["checks"], "確認", flush=True)
        finally:
            if connection:
                connection.close()
            process.terminate()
            process.wait(timeout=10)
    save(folder / "公開表示の確認.json", dict(passed=True, records=records, links=links,
         report=reference(report), numerical=reference(HERE / "最終全場比較_確定.json"),
         financial_replays=0, market_API=0))


if __name__ == "__main__":
    main()
