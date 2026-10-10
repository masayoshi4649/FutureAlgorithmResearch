"""作業00051の全金額・R表示・売買図を実Chromeで独立確認する。"""

from pathlib import Path
import importlib.util


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00051_銘柄共通の境界反応とリスク効率'
SPEC=importlib.util.spec_from_file_location('previous_browser_audit',HERE.parent.parent/'wave_v53/review/verify_report.py')
AUDIT=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
AUDIT.HERE=HERE
AUDIT.OUT=OUT
AUDIT.SOURCE=OUT/'共通原理とリスク効率の検証.html'
AUDIT.BROWSER.OUT=OUT
AUDIT.BROWSER.VISUAL=HERE/'visual'

AUDIT.PROBE=r'''<script>
/**
 * 機能: 全手法・銘柄・場の金額、R、注文点を保存値に照合する。
 * @returns {object} 検査件数と画面品質。
 */
function verifyAll(){
 let views=0,accounts=0,numbers=0,markers=0,rnumbers=0;
 const number=c=>Number(c.textContent.replaceAll(',','').trim());
 const check=(r,a)=>{
  for(const [i,k]of [[1,'profit'],[2,'loss'],[3,'net']]){if(number(r.cells[i])!==a[k])throw Error('金額');numbers++;}
  if(r.cells[4].textContent!==`${fmt(a.win_qty)} / ${fmt(a.loss_qty)} / ${fmt(a.flat_qty)}`)throw Error('枚数');
  if(number(r.cells[5])!==a.win_qty-a.loss_qty)throw Error('枚数差');
  for(const [i,k]of [[6,'r_profit'],[7,'r_loss'],[8,'r_net']]){if(r.cells[i].textContent.replace('+','')!==fmt(a[k],2))throw Error('場R:'+k);rnumbers++;}
  for(const [i,plan]of [[9,false],[10,true]]){if(r.cells[i].textContent.replace('+','')!==fmt(meanR(a,plan),3))throw Error('平均R');rnumbers++;}
  if(r.cells[11].textContent!==`${fmt(a.wins)} / ${fmt(a.cycles)}`)throw Error('組勝数');
 };
 for(const m of RESULT.methods){
  el('method').value=m.id;
  for(const symbol of ['TOPIX','NK225']){
   el('symbol').value=symbol;render();
   const group=m.accounts.filter(a=>a.symbol===symbol).sort((a,b)=>a.session.localeCompare(b.session));
   const rs=el('sessions').querySelector('tbody').rows;
   if(rs.length!==23)throw Error('場数');
   for(let i=0;i<rs.length;i++){if(rs[i].cells[0].textContent!==group[i].session)throw Error('場名');check(rs[i],group[i]);}
   const pr=el('periods').querySelector('tbody').rows,expected=[...Object.values(m.periods[symbol]),...Object.values(m.weeks[symbol])];
   if(pr.length!==expected.length)throw Error('期間数');
   expected.forEach((a,i)=>check(pr[i],a));
   if(el('all-methods').querySelector('tbody').rows.length!==14)throw Error('比較数');
   views++;
   for(const a of group){
    el('session').value=a.session;renderSession();
    const ir=el('intervals').querySelector('tbody').rows;
    if(ir.length!==a.intervals.length)throw Error('区間数');
    for(let i=0;i<ir.length;i++)for(const [j,k]of [[1,'利益円'],[2,'損失円'],[3,'確定収支円'],[4,'開始含み円'],[5,'終了含み円'],[6,'時価収支円']]){
     if(number(ir[i].cells[j])!==a.intervals[i][k])throw Error('区間金額');numbers++;
    }
    const svg=el('chart').querySelector('svg');
    if(!svg||svg.querySelectorAll('path title,circle title').length!==a.orders.length)throw Error('売買点数');
    if(svg.querySelectorAll('circle').length!==a.orders.filter(o=>o[4]===2).length)throw Error('返済点');
    if(/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('未定義の図');
    const os=el('orders').querySelector('tbody').rows;
    if(os.length!==a.orders.length)throw Error('注文数');
    a.orders.forEach((o,i)=>{
     const r=os[i];
     if(number(r.cells[2])!==o[6]||number(r.cells[3])!==o[7]||r.cells[6].textContent!==fmt(o[12],3)||number(r.cells[7])!==o[11]||number(r.cells[8])!==o[10]+1||number(r.cells[9])!==o[3])throw Error('注文値');
     if(o[4]===2&&number(r.cells[4])!==o[8])throw Error('返済金額');
    });
    const gs=el('risk-groups').querySelector('tbody').rows;
    if(gs.length!==a.risk_groups.length)throw Error('R組数');
    a.risk_groups.forEach((g,i)=>{
     const r=gs[i];
     if(number(r.cells[0])!==g[0]+1||number(r.cells[2])!==g[2]||number(r.cells[4])!==g[8])throw Error('R識別');
     for(const [j,value]of [[5,g[9]],[6,g[3]],[7,g[4]],[8,g[4]*g[3]/g[9]]]){if(r.cells[j].textContent.replace('+','')!==fmt(value,3))throw Error('R組数値');rnumbers++;}
    });
    markers+=a.orders.length;accounts++;
   }
  }
 }
 el('method').value='S3_T';el('symbol').value='TOPIX';el('session').value=RESULT.sessions.at(-1);render();
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義');
 return {全合格:true,手法商品表示数:views,セッション表示数:accounts,金額照合数:numbers,R照合数:rnumbers,売買点数:markers,
         文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(verifyAll());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''


if __name__=='__main__':
    AUDIT.main()
