"""暗色レポートの全選択を実ブラウザーで元会計へ照合する。"""

import json
import subprocess
from bs4 import BeautifulSoup
from common128 import HERE, PUBLIC, read, sha, save


def main():
    """
    機能: 外部通信を遮断したChromeで全表の会計・累計・選択切替を確認する。
    引数: なし。
    返り値: None。検査資料・昼夜の画像を保存し、公表HTMLを変更しない。
    """
    target=PUBLIC/"日中改修と夜間新造の損益.html"
    original=target.read_bytes()
    expected_sha=sha(target)
    soup=BeautifulSoup(original.decode("utf-8"),"html.parser")
    payload=json.loads(soup.find(id="saved-data").string)
    comparison=read(HERE/"round5/前後半と方向別の比較.json")
    original_rows={(r["method"],r["session"],r["symbol"]):r for r in comparison["rows"]}
    for r in payload["rows"]:
        assert all(original_rows[r["method"],r["session"],r["symbol"]][k]==v for k,v in r.items())
    assert len(payload["rows"])==len(original_rows)
    cases=[dict(method=m,kind=c["kind"],
        rows=[{k:r[k] for k in ("session","symbol","profit","loss","net")} for r in comparison["rows"] if r["method"]==m])
        for m,c in payload["methods"].items()]
    probe=r'''<script>
/**
 * 全選択の描画値を元会計の独立埋込みへ照合する。
 * @returns {void} body.dataset.qaへ結果を保存する。
 */
function inspectReport(){try{
 const cases=__CASES__,check=(v,t)=>{if(!v)throw Error(t)},num=e=>Number(e.innerText.replaceAll(",","").trim());
 let cells=0,count=0;
 for(const c of cases){
  let select=document.getElementById(c.kind+"-method");select.value=c.method;select.dispatchEvent(new Event("change"));
  const root=document.getElementById(c.kind),rows=[...root.querySelectorAll(".sessions tbody tr")],dates=[...new Set(c.rows.map(r=>r.session))].sort();
  check(rows.length===dates.length&&dates.length===(c.kind==="Day"?22:21),"場数");
  const running={TOPIX:0,NK225:0},totals={TOPIX:[0,0,0],NK225:[0,0,0]};
  for(let i=0;i<dates.length;i++){
   const td=rows[i].children;check(td[0].innerText===dates[i].slice(0,10),"日付");let col=1;
   for(const symbol of ["TOPIX","NK225"]){
    const r=c.rows.find(x=>x.session===dates[i]&&x.symbol===symbol);running[symbol]+=r.net;
    for(const value of [r.profit,-r.loss,r.net,running[symbol]]){check(num(td[col++])===Math.round(value),c.method+" 行金額");cells++;}
    totals[symbol][0]+=r.profit;totals[symbol][1]-=r.loss;totals[symbol][2]+=r.net;
   }count++;
  }
  const td=root.querySelector(".sessions tfoot tr").children;let col=1;
  for(const symbol of ["TOPIX","NK225"]){for(const value of [...totals[symbol],totals[symbol][2]]){check(num(td[col++])===Math.round(value),"合計");cells++;}}
  check(!root.innerText.includes("NaN")&&!root.innerText.includes("undefined"),"未定義表示");
 }
 render("Day",saved.defaults.Day);render("Night",saved.defaults.Night);
 check(document.documentElement.scrollWidth<=innerWidth+2,"ページ横あふれ");
 document.body.dataset.qa=JSON.stringify({passed:true,choices:cases.length,rows:count,cells,viewport:innerWidth});
}catch(e){document.body.dataset.qa=JSON.stringify({passed:false,error:String(e)})}}
inspectReport();</script>'''.replace("__CASES__",json.dumps(cases,ensure_ascii=False,allow_nan=False))
    output=HERE/"visual_final"
    assert not output.exists()
    output.mkdir()
    results=[]
    for variant,width in (("日中",1450),("夜間",1450),("狭幅",520)):
        injected=output/(variant+"検査用.html")
        extra=probe+('<script>document.getElementById("Day").hidden=true;</script>' if variant=="夜間" else "")
        injected.write_bytes(original.replace(b"</body>",extra.encode("utf-8")+b"</body>"))
        picture=output/(variant+".png")
        command=["C:/Program Files/Google/Chrome/Application/chrome.exe","--headless=new","--disable-gpu",
            "--no-first-run","--disable-background-networking","--disable-component-update","--disable-sync",
            "--proxy-server=http://127.0.0.1:9",f"--window-size={width},1500","--virtual-time-budget=2000",
            "--user-data-dir="+str(output/("profile_"+variant)),"--screenshot="+str(picture),"--dump-dom",injected.as_uri()]
        process=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
        assert process.returncode==0,process.stderr[-1000:]
        rendered=BeautifulSoup(process.stdout.decode("utf-8",errors="replace"),"html.parser")
        result=json.loads(rendered.body["data-qa"])
        assert result["passed"] and result["choices"]==len(cases),result
        assert picture.stat().st_size>10000
        results.append(dict(variant=variant,**result))
    assert sha(target)==expected_sha
    save(output/"全選択と全場累計の実描画照合.json",dict(passed=True,results=results,
        html_sha256=expected_sha,financial_replays=0,root_viewed=False))
    print(json.dumps(results,ensure_ascii=False))


if __name__=="__main__":
    main()
