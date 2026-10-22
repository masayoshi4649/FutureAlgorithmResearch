"""Chrome実描画の全二十四選択・九百八十四行を保存会計へ独立照合する。"""

from pathlib import Path
import argparse
import json
import hashlib
import statistics
import subprocess
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
PUBLIC=ROOT/"アルゴリズム調査/00125_毎日参加と両銘柄の利益率改善/毎日参加する三系統と全セッション損益.html"


def main(expected_sha: str) -> None:
    """
    機能: 通信を遮った実Chromeで表示数値・目標・切替と暗色画面を検査する。
    引数: expected_sha(str)は正式公開HTMLのSHA。
    返り値: None。金融再生0、原本読取0、公開HTMLは変更しない。
    """
    raw=PUBLIC.read_bytes();assert hashlib.sha256(raw).hexdigest()==expected_sha
    d=json.loads((HERE/"十二条件と二商品全四十一場の会計.json").read_text(encoding="utf-8"))
    cases=[]
    for symbol in ("TOPIX","NK225"):
        for spec in d["specs"]:
            rr=sorted([r for r in d["rows"] if r["symbol"]==symbol and r["method"]==spec["id"]],key=lambda r:r["session"])
            cases.append(dict(symbol=symbol,method=spec["id"],rows=rr))
    probe="""<script>
/**
 * 機能: 表示された全場会計を独立射影した期待値へ比較する。
 * 引数: なし。期待値は固定された保存会計。
 * 返り値: body.dataset.qa に合否を記録する。
 */
try{
 const cases=__CASES__;
 const check=(v,t)=>{if(!v)throw Error(t)};
 const num=e=>Number(e.innerText.replaceAll(',','').replaceAll('円','').replaceAll('−','-').trim());
 const choose=(id,v)=>{const e=document.getElementById(id);e.value=v;e.dispatchEvent(new Event('change'));};
 let verified=0;
 check(document.querySelectorAll('#summary-body tr').length===12,'一覧十二行');
 for(const x of cases){
  choose('method',x.method);choose('symbol',x.symbol);
  const rows=Array.from(document.querySelectorAll('#session-body tr'));check(rows.length===41,'全四十一行');
  const sums=[0,0,0,0,0,0,0,0,0,0];
  for(let i=0;i<41;i++){
   const r=x.rows[i],c=rows[i].children;
   check(c[0].innerText===r.session.replace('_Day',' デイ').replace('_Night',' ナイト'),'場名と順');
   check(num(c[1])===r.profit&&num(c[2])===-r.loss&&num(c[3])===r.net,'PL金額');
   const pair=c[4].innerText.split('／');
   const width=r.net/(r.rate_components.capacity_notional/r.rate_components.reference_price);
   check(Math.abs(parseFloat(pair[0])-Number(width.toFixed(2)))<1e-9,'獲得幅');
   check(Math.abs(parseFloat(pair[1])-Number((100*r.net/r.rate_components.capacity_notional).toFixed(3)))<1e-9,'価格比');
   check(c[5].innerText===r.win_quantity.toLocaleString('ja-JP')+'／'+r.loss_quantity.toLocaleString('ja-JP'),'勝負枚数');
   check(num(c[6])===r.entry_quantity,'新規数量');
   check(c[7].innerText===r.signal_groups+'／'+r.forced_groups,'根拠と期限');
   check(c[8].innerText===r.normal_groups+'／'+r.proxy_groups,'通常と代理');
   check(c[9].innerText===r.max_long+'／'+r.max_short,'最大買売');
   [r.profit,-r.loss,r.net,r.win_quantity,r.loss_quantity,r.entry_quantity,r.signal_groups,r.forced_groups,r.normal_groups,r.proxy_groups].forEach((v,j)=>sums[j]+=v);
   verified++;
  }
  const t=document.querySelector('#session-total tr').children;
  check(num(t[1])===sums[0]&&num(t[2])===sums[1]&&num(t[3])===sums[2],'合計PL');
  check(t[5].innerText===sums[3].toLocaleString('ja-JP')+'／'+sums[4].toLocaleString('ja-JP'),'合計勝負枚数');
  check(num(t[6])===sums[5]&&t[7].innerText===sums[6]+'／'+sums[7]&&t[8].innerText===sums[8]+'／'+sums[9],'合計数量と群');
  check(document.getElementById('selected-summary').innerText.includes('参加 41/41場'),'通常数量参加');
  check(document.querySelectorAll('#diagnosis details').length===3,'具体三場');
  check(Array.from(document.querySelectorAll('#diagnosis summary')).every(e=>e.innerText.includes('2026-')),'診断に場日付');
 }
 const json=JSON.parse(document.getElementById('report-data').textContent);
 check(json.rows.length===984,'全984収録');
 check(document.getElementById('goal-outcome').innerText.includes('TOPIX 0/12')&&document.getElementById('goal-outcome').innerText.includes('日経 0/12'),'目標未達を表示');
 check(!document.body.innerText.includes('undefined')&&!document.body.innerText.includes('NaN'),'未定義なし');
 check(document.documentElement.scrollWidth<=innerWidth+2,'文書横溢れ');
 choose('method','A00');choose('symbol','TOPIX');
 document.body.dataset.qa=JSON.stringify({passed:true,choices:24,checked_rows:verified,innerWidth,documentWidth:document.documentElement.scrollWidth,background:getComputedStyle(document.body).backgroundColor});
}catch(e){document.body.dataset.qa=JSON.stringify({passed:false,error:String(e)});}
</script>""".replace("__CASES__",json.dumps(cases,ensure_ascii=False,separators=(",",":")))
    out=HERE/"visual";assert not out.exists();out.mkdir()
    target=out/"描画用.html";target.write_bytes(raw.replace(b"</html>",probe.encode("utf-8")+b"</html>"))
    picture=out/"画面.png"
    command=["C:/Program Files/Google/Chrome/Application/chrome.exe","--headless=new","--disable-gpu","--no-first-run","--disable-background-networking","--disable-component-update","--disable-sync","--proxy-server=http://127.0.0.1:9","--window-size=1420,1500","--virtual-time-budget=1800","--user-data-dir="+str(out/"profile"),"--screenshot="+str(picture),"--dump-dom",target.as_uri()]
    process=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode==0,process.stderr[-1500:]
    soup=BeautifulSoup(process.stdout.decode("utf-8",errors="replace"),"html.parser")
    proof=json.loads(soup.body["data-qa"])
    (out/"実描画確認.json").write_text(json.dumps(dict(proof,root_viewed=False,html_sha256=expected_sha,financial_replay=0),ensure_ascii=False,indent=2),encoding="utf-8")
    assert proof["passed"] and proof["checked_rows"]==984,proof
    assert hashlib.sha256(PUBLIC.read_bytes()).hexdigest()==expected_sha and picture.stat().st_size>10000
    print(json.dumps(proof,ensure_ascii=False))


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--html-sha",required=True);main(p.parse_args().html_sha)
