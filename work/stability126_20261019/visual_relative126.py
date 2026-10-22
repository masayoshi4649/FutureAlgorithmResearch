"""暗色主表の全選択と全場金額を、実ブラウザーで元会計へ照合する。"""

import argparse
import json
import subprocess
from bs4 import BeautifulSoup
from common126 import ROOT, HERE, PUBLIC, read, sha, save


def execute(expected: str) -> None:
    """
    機能: 外部通信を遮った実Ｃｈｒｏｍｅで利益・損失・各行累計と全体累計を確認する。
    引数: expected(str)は公開ＨＴＭＬの固定ＳＨＡ２５６。
    返り値: None。主表を変更せず、描画画像と比較証跡を保存する。
    """
    target = PUBLIC / "E01改修のセッション損益.html"
    assert sha(target) == expected
    raw = target.read_bytes()
    soup = BeautifulSoup(raw.decode("utf-8"), "html.parser")
    payload = json.loads(soup.find(id="accounts").string)
    cases = []
    for model in payload["models"]:
        originals = []
        for reference in model["sources"]:
            path = ROOT / reference["path"]
            assert sha(path) == reference["sha256"]
            originals += read(path)["rows"]
        for method in model["methods"]:
            selected = [r for r in originals if r["method"] == method["id"]]
            assert len(selected) == 82
            cases.append(dict(model=model["id"], method=method["id"],
                rows=[{k: r[k] for k in ("method", "session", "symbol", "profit", "loss", "net")} for r in selected]))
    probe = r'''<script>
/**
 * 元の完成会計と実表示の全セルを比較します。
 * @returns {void} body.dataset.qa に検査結果を保存します。
 */
function verifyReport(){try{const cases=__CASES__,check=(v,t)=>{if(!v)throw Error(t)},num=e=>Number(e.innerText.replaceAll(',','').replaceAll('円','').trim()),choose=(id,v)=>{const e=document.getElementById(id);e.value=v;e.dispatchEvent(new Event('change'))};let cells=0,rowsChecked=0;
for(const c of cases){choose('model',c.model);choose('method',c.method);const rows=[...document.querySelectorAll('#sessions tbody tr')];check(rows.length===41,'全四十一行');const original=new Map(c.rows.map(r=>[r.session+'|'+r.symbol,r])),total={TOPIX:[0,0,0],NK225:[0,0,0]},running={TOPIX:0,NK225:0};
for(let i=0;i<rows.length;i++){const s=data.sessions[i],td=rows[i].children;check(td[0].innerText===s.replace('_Day',' 日中').replace('_Night',' 夜間'),'日付順');let column=1;for(const symbol of ['TOPIX','NK225']){const r=original.get(s+'|'+symbol);running[symbol]+=r.net;const values=[r.profit,r.loss,r.net,running[symbol]];for(const value of values){check(num(td[column++])===Math.round(value),'原会計金額');cells++;}total[symbol][0]+=r.profit;total[symbol][1]+=r.loss;total[symbol][2]+=r.net;}rowsChecked++;}
const footer=document.querySelector('#sessions tfoot tr').children;let column=1;for(const symbol of ['TOPIX','NK225']){for(const value of [...total[symbol],total[symbol][2]]){check(num(footer[column++])===Math.round(value),'全体累計');cells++;}}
const cards=[...document.querySelectorAll('#totals .card')];check(cards.length===2,'商品別累計');for(let i=0;i<cards.length;i++){const symbol=i===0?'TOPIX':'NK225',values=[...cards[i].querySelectorAll('strong')];for(let k=0;k<3;k++){check(num(values[k])===Math.round(total[symbol][k]),'累計カード');cells++;}}
}
check(!document.body.innerText.includes('NaN')&&!document.body.innerText.includes('undefined'),'未定義金額なし');check(document.documentElement.scrollWidth<=innerWidth+2,'文書横あふれなし');choose('model',data.models[0].id);document.body.dataset.qa=JSON.stringify({passed:true,choices:cases.length,rows:rowsChecked,cells,viewport:innerWidth,documentWidth:document.documentElement.scrollWidth});
}catch(e){document.body.dataset.qa=JSON.stringify({passed:false,error:String(e)})}}
verifyReport();</script>'''.replace("__CASES__", json.dumps(cases, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    output = HERE / "relative_visual"
    assert not output.exists()
    output.mkdir()
    injected = output / "描画検査用.html"
    injected.write_bytes(raw.replace(b"</html>", probe.encode("utf-8")+b"</html>"))
    picture = output / "セッション損益の画面.png"
    command = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "--headless=new", "--disable-gpu",
        "--no-first-run", "--disable-background-networking", "--disable-component-update", "--disable-sync",
        "--proxy-server=http://127.0.0.1:9", "--window-size=1450,1500", "--virtual-time-budget=2000",
        "--user-data-dir="+str(output / "profile"), "--screenshot="+str(picture), "--dump-dom", injected.as_uri()]
    process = subprocess.run(command, capture_output=True, timeout=55, creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode == 0, process.stderr[-1000:]
    rendered = BeautifulSoup(process.stdout.decode("utf-8", errors="replace"), "html.parser")
    result = json.loads(rendered.body["data-qa"])
    assert result["passed"] and result["rows"] == len(cases)*41, result
    assert sha(target) == expected and picture.stat().st_size > 10000
    save(output / "全選択と全場会計の実描画確認.json", dict(result, html_sha256=expected,
        source_bound=True, financial_replays=0, original_market_reads=0, root_viewed=False))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--html-sha", required=True)
    execute(parser.parse_args().html_sha)
