"""全場会計・注文図・少数黒字例の表示を、通信なしのChromeで照合する。"""

import hashlib
import importlib.util
import json
from pathlib import Path

import report

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('browser_review',report.ROOT/'work/wave_v52/review/verify_report.py')
browser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser)
browser.OUT = report.OUT
browser.VISUAL = HERE/'review/visual'

MAIN_PROBE = r'''<script>
/**
 * 機能: 四章の全商品・全場の金額、枚数、返済収支、売買点を照合する。
 * 引数: なし。
 * 返り値: 合格と照合件数(Object)。
 */
function independentVerify(){
 const n=cell=>Number(cell.textContent.replace(/[円,＋\s]/g,'').replace(/−/g,'-'));
 let amounts=0,views=0,points=0;
 const verifyRow=(tr,a)=>{for(const [col,key] of [[1,'profit'],[2,'loss'],[3,'net'],[4,'winning_lots'],[5,'losing_lots'],[6,'fees']]){
   if(n(tr.cells[col])!==Math.round(a[key]))throw Error('表示不一致 '+key);amounts++;
 }};
 for(const method of D.methods){
  const id=method.family,root=document.querySelector('#family-'+id);
  if(!root)throw Error('章不足');
  for(const symbol of ['TOPIX','NK225']){
   STATE.get(id).symbol=symbol;renderFamily(id);
   const periods=root.querySelector('[data-role=period] tbody').rows;
   ['前16','後12','全28'].forEach((p,i)=>verifyRow(periods[i],method.periods[p][symbol]));
   const tables=root.querySelector('[data-role=sessions] tbody').rows;
   if(tables.length!==29)throw Error('全場数');
   D.sessions.forEach((session,i)=>{
    const row=method.rows.find(r=>r.session===session&&r.symbol===symbol);verifyRow(tables[i],row);
   });
   verifyRow(tables[28],method.periods['全28'][symbol]);
   const weeks=root.querySelector('[data-role=weeks] tbody').rows;
   if(weeks.length!==3)throw Error('週数');method.weeks[symbol].forEach((a,i)=>verifyRow(weeks[i],a));
   for(const session of D.sessions){
    STATE.get(id).session=session;renderFamily(id);
    const orders=method.orders[session+'|'+symbol];
    const svg=root.querySelector('[data-role=chart] svg');
    if(!svg||svg.querySelectorAll('.order-marker').length!==orders.length)throw Error('注文点数');
    if(svg.querySelectorAll('.entry-marker circle').length!==orders.filter(o=>o[7]===1).length)throw Error('新規丸');
    if(svg.querySelectorAll('.exit-marker path').length!==orders.filter(o=>o[7]===0).length)throw Error('返済菱形');
    if(/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('不正グラフ');
    const expected=method.rows.find(r=>r.session===session&&r.symbol===symbol);
    if(orders.length){
      const rows=root.querySelector('[data-role=history] tbody').rows;
      if(rows.length!==orders.length)throw Error('履歴数');
      const sum=[...rows].reduce((a,r)=>a+(r.cells[1].textContent==='返済'?n(r.cells[5]):0),0);
      if(sum!==expected.net)throw Error('表示返済損益');
    }else if(!root.querySelector('[data-role=history]').textContent.includes('勝ちには数えていません'))throw Error('無取引勝ち');
    views++;points+=orders.length;
   }
  }
  STATE.set(id,{symbol:'TOPIX',session:D.sessions.at(-1)});renderFamily(id);
 }
 const examples=document.querySelector('#exploratory tbody').rows;
 ['TOPIX','NK225'].forEach((s,i)=>{for(const[col,key]of[[1,'profit'],[2,'loss'],[3,'net'],[4,'trades']]){
  if(n(examples[i].cells[col])!==D.exploratory.periods['全28'][s][key])throw Error('事後例会計');amounts++;
 }});
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/NaN|undefined|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,場チャート照合数:views,表示数値照合数:amounts,注文点照合数:points,
  文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.body).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''


def main() -> None:
    """機能: 主HTMLの全選択を検査し、広幅・狭幅・売買図を保存する。

    引数: なし。返り値: なし(None)。
    """
    browser.VISUAL.mkdir(parents=True,exist_ok=True)
    browser.PROBE = MAIN_PROBE
    source = (report.OUT/report.MAIN).read_text(encoding='utf8')
    checks = [browser.render(source,'全体',1360,1450),browser.render(source,'狭幅',500,1250),
        browser.render(source,'売買図',1360,1080,
          '<script>STATE.set(1,{symbol:"NK225",session:"2026-09-23_Day"});renderFamily(1);'
          'const sec=document.getElementById("family-1");sec.querySelectorAll("details").forEach(x=>x.open=true);'
          'const keep=[...sec.children].filter(x=>x.classList.contains("chart-box")||x.textContent.startsWith("表示中のセッション"));'
          'document.querySelector("main").replaceChildren(...keep);window.scrollTo(0,0);</script>')]
    result = dict(全合格=True,目視確認=False,結果=checks,
        主HTML_SHA256=hashlib.sha256((report.OUT/report.MAIN).read_bytes()).hexdigest(),
        全条件HTML_SHA256=hashlib.sha256((report.OUT/report.ALL).read_bytes()).hexdigest())
    report.save(HERE/'HTML表示の独立検査.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
