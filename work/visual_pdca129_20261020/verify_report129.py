"""公開HTMLの全組合せと全セルを隔離したブラウザーで確認する。"""

import html
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import unquote, urlparse
from common129 import HERE, PUBLIC, read, save, reference


JAVASCRIPT = r"""
/**
 * 機能: 保存された全選択の表示値を独立集計と照合する。
 * 引数: なし。公開画面のDOMと保存JSONを読む。
 * 返り値: なし。確認結果を非表示preへ記録する。
 */
function verifyAll(){
 const day=document.getElementById("day-method"), night=document.getElementById("night-method");
 const previous=[day.value,night.value], data=JSON.parse(document.getElementById("saved-data").textContent);
 let checks=0, combinations=0;
 function verify(ok,description){checks++;if(!ok)throw Error(description);}
 function numeric(text){return Number(text.replaceAll(",","").replaceAll("+",""));}
 for(const d of [...day.options])for(const n of [...night.options]){
  day.value=d.value;day.dispatchEvent(new Event("change"));
  night.value=n.value;night.dispatchEvent(new Event("change"));
  const rows=data.rows.filter(r=>r.method===(r.kind==="Day"?d.value:n.value));
  const dates=[...new Set(rows.map(r=>r.session))].sort();
  const shown=[...document.querySelectorAll("#session-body tr")];
  verify(dates.length===43&&shown.length===43,"場の数");
  const sums={TOPIX:[0,0,0],NK225:[0,0,0]};
  dates.forEach((date,i)=>{
   const cells=[...shown[i].cells];
   verify(cells[0].textContent===date.replace("_Day"," デイ").replace("_Night"," ナイト"),"場ラベル");
   ["TOPIX","NK225"].forEach((symbol,k)=>{
    const row=rows.find(r=>r.session===date&&r.symbol===symbol), total=sums[symbol];
    total[0]+=row.profit;total[1]+=row.loss;total[2]+=row.net;
    [row.profit,-row.loss,row.net,total[2]].forEach((v,j)=>verify(numeric(cells[1+k*4+j].textContent)===Math.round(v),"場セル"));
   });
  });
  const totalCells=[...document.querySelector("#session-total tr").cells];
  ["TOPIX","NK225"].forEach((symbol,k)=>{
    const v=sums[symbol];
    [v[0],-v[1],v[2],v[2]].forEach((x,j)=>verify(numeric(totalCells[1+k*4+j].textContent)===Math.round(x),"合計セル"));
  });
  combinations++;
 }
 day.value=previous[0];night.value=previous[1];update();
 const comparison=[...document.querySelectorAll("#all-comparison tbody tr")];
 verify(comparison.length===data.summary.length,"全条件の行数");
 data.summary.forEach((s,i)=>{
  const cells=[...comparison[i].cells];
  verify(cells[0].textContent===s.method&&cells[1].textContent===s.symbol,"全条件の手法商品");
  const r=s.regimes;
  [[2,s.net],[4,s.worst],[5,s.without_top3],[6,r["上昇"]?.net||0],
   [7,r["下落"]?.net||0],[8,r["同値"]?.net||0],[9,s.halves["後半"].net]]
   .forEach(([column,value])=>verify(numeric(cells[column].textContent)===Math.round(value),"全条件セル"));
  verify(Math.abs((r["上昇"]?.net||0)+(r["下落"]?.net||0)+(r["同値"]?.net||0)-s.net)<.01,"方向区分合算");
 });
 verify(document.documentElement.scrollWidth<=innerWidth+1,"画面外への横はみ出し");
 document.getElementById("qa-result").textContent=JSON.stringify({passed:true,checks,combinations,viewport:[innerWidth,innerHeight]});
}
try{verifyAll();}catch(error){document.getElementById("qa-result").textContent=JSON.stringify({passed:false,error:String(error)});}
"""


def main():
    """
    機能: 元集計との完全一致、相対リンク、全表示選択と広狭画面を確認する。
    引数: なし。公開後のHTMLと最終全場比較.jsonを対象にする。
    返り値: None。金融再生なし、ユーザーの通常ブラウザーの状態を変更しない。
    """
    report = PUBLIC / "チャートで検証した改修と全セッション損益.html"
    document = report.read_text(encoding="utf-8")
    embedded = json.loads(re.search(r'<script type="application/json" id="saved-data">(.*?)</script>', document, re.S)[1])
    result = read(HERE / "最終全場比較_確定.json")
    assert embedded["rows"] == result["rows"] and embedded["summary"] == result["summary"]
    checked = []
    for value in re.findall(r'(?:href|src)="([^"]+)"', document):
        parsed = urlparse(value)
        if parsed.scheme or value.startswith("#"):
            continue
        target = PUBLIC / unquote(parsed.path)
        assert target.exists(), target
        checked.append(value)
    folder = HERE / "表示確認_最終"
    folder.mkdir(exist_ok=True)
    records = []
    for name, width, height in (("全体", 1600, 1250), ("損益表", 1600, 1050), ("狭幅", 390, 1000)):
        target = folder / (name + ".html")
        base = '<base href="' + PUBLIC.as_uri() + '/">'
        extra = '<pre id="qa-result" hidden></pre><script>' + JAVASCRIPT
        if name == "損益表":
            extra += '\ndocument.getElementById("selected-summary").scrollIntoView();'
        extra += "</script>"
        target.write_text(document.replace("<title>", base + "<title>", 1).replace("</html>", extra + "</html>"), encoding="utf-8")
        image = folder / (name + ".png")
        profile = folder / ("profile_" + name + "_" + str(time.time_ns()))
        command = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "--headless=new", "--disable-gpu",
                   "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                   "--disable-extensions", "--hide-scrollbars", "--force-device-scale-factor=1",
                   "--window-size=" + str(width) + "," + str(height), "--virtual-time-budget=3000",
                   "--user-data-dir=" + str(profile), "--screenshot=" + str(image), "--dump-dom", target.as_uri()]
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                 timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
        (folder / (name + "_ブラウザー記録.txt")).write_text(process.stderr, encoding="utf-8")
        assert process.returncode == 0
        match = re.search(r'<pre id="qa-result" hidden="">(.*?)</pre>', process.stdout, re.S)
        assert match, process.stderr[-1000:]
        proof = json.loads(html.unescape(match[1]))
        assert proof["passed"], proof
        records.append(dict(name=name, **proof, image=reference(image)))
        print(name, proof["combinations"], "組合せ", proof["checks"], "表示確認", flush=True)
    save(folder / "公開表示の確認.json", dict(passed=True, financial_replays=0, API=0, records=records,
         links=checked, report=reference(report), numerical_source=reference(HERE / "最終全場比較_確定.json")))


if __name__ == "__main__":
    main()
