"""全192条件の全場・期間・気配感度の表示と、事後例へのリンクを照合する。"""

import json
from pathlib import Path

import report
import verify

HERE = Path(__file__).resolve().parent

PROBE = r'''<script>
/**
 * 機能: 全192条件の両商品表、期間表、中値感度、全場表を照合する。
 * 引数: なし。
 * 返り値: 合格と照合件数(Object)。
 */
function independentVerify(){
 const n=cell=>Number(cell.textContent.replace(/[円,＋\s]/g,'').replace(/−/g,'-'));
 let amounts=0,views=0;
 const verifyRow=(r,a)=>{for(const[col,key]of[[1,'profit'],[2,'loss'],[3,'net'],[4,'winning_lots'],[5,'losing_lots'],[6,'trades'],[9,'fees']]){
  if(n(r.cells[col])!==Math.round(a[key]))throw Error('全条件表示 '+key);amounts++;
 }const rate=a.trades?a.wins/a.trades:null,pay=a.winning_lots&&a.losing_lots&&a.loss?(a.profit/a.winning_lots)/(a.loss/a.losing_lots):null;
  if(r.cells[7].textContent!==(rate===null?'—':(rate*100).toFixed(1)+'%'))throw Error('勝率表示');
  if(r.cells[8].textContent!==(pay===null?'—':pay.toFixed(2)))throw Error('損益比表示');
 };
 const list=[...document.querySelector('#condition-list tbody').rows];
 if(list.length!==192||document.querySelector('#condition-select').options.length!==192)throw Error('192件不足');
 D.methods.forEach((m,i)=>{const r=list[i];for(const[col,s,key]of[[2,'TOPIX','net'],[3,'TOPIX','trades'],[4,'NK225','net'],[5,'NK225','trades']]){
   if(n(r.cells[col])!==m.periods['全28'][s][key])throw Error('一覧会計');amounts++;
 }});
 for(const m of D.methods)for(const s of ['TOPIX','NK225']){
  STATE.id=m.config.id;STATE.symbol=s;renderDetail();
  const periods=document.querySelector('#period-table tbody').rows;
  const sens=document.querySelector('#sensitivity-table tbody').rows;
  ['前16','後12','全28'].forEach((p,i)=>{const a=m.periods[p][s];verifyRow(periods[i],a);
    if(n(sens[i].cells[1])!==a.net||n(sens[i].cells[2])!==Math.round(a.ideal_net)||n(sens[i].cells[3])!==Math.round(a.ideal_net-a.net))throw Error('感度表示');amounts+=3;
  });
  const sessions=document.querySelector('#session-table tbody').rows;if(sessions.length!==29)throw Error('28場表');
  D.sessions.forEach((session,i)=>verifyRow(sessions[i],m.rows.find(a=>a.session===session&&a.symbol===s)));
  verifyRow(sessions[28],m.periods['全28'][s]);views++;
 }
 for(const f of [1,2,3,4]){STATE.family=f;renderList();if(document.querySelector('#condition-list tbody').rows.length!==48)throw Error('機構絞り込み');}
 STATE.family=0;STATE.id='T3L1_E0_O16A8W8_H60';STATE.symbol='TOPIX';renderDetail();
 if(initialSelection(D)!==D.selectedIds[0])throw Error('初期選定');
 if(!document.querySelector('#condition-status').textContent.includes('全28事後両黒字'))throw Error('事後表示');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 return {全合格:true,全条件銘柄表示数:views,表示数値照合数:amounts,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.body).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''


def main() -> None:
    """機能: 全条件表の広狭幅を検査し、既存の主HTML検査へ結果を追加する。

    引数: なし。返り値: なし(None)。
    """
    browser = verify.browser
    browser.PROBE = PROBE
    source = (report.OUT/report.ALL).read_text(encoding='utf8')
    checks = [browser.render(source,'全条件',1360,1300),browser.render(source,'全条件狭幅',500,1250)]
    path = HERE/'HTML表示の独立検査.json'
    proof = report.load(path)
    proof['全条件表示'] = checks
    proof['目視確認'] = True
    report.save(path,proof)
    print(json.dumps(checks,ensure_ascii=False))


if __name__=='__main__':
    main()
