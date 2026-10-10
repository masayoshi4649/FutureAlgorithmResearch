"""作業00052の全条件・全口座・固定幅表示を実Chromeで独立照合する。"""

from pathlib import Path
import importlib.util

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00052_ATRを使わない単純手法'
SPEC=importlib.util.spec_from_file_location('previous_browser_audit',HERE.parent.parent/'wave_v53/review/verify_report.py')
AUDIT=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
AUDIT.HERE=HERE
AUDIT.OUT=OUT
AUDIT.SOURCE=OUT/'ATRなし20条件の説明と損益.html'
AUDIT.BROWSER.OUT=OUT
AUDIT.BROWSER.VISUAL=HERE/'visual'

AUDIT.PROBE=r'''<script>
/**
 * 機能: 全手法・商品・場の金額、幅単位、注文点を保存台帳へ照合する。
 * @returns {object} 検査件数と画面品質。
 */
function verifyAll(){
 let views=0,accounts=0,numbers=0,markers=0,wnumbers=0;
 const number=c=>Number(c.textContent.replaceAll(',','').trim());
 const check=(r,a)=>{
  for(const [i,k]of [[1,'profit'],[2,'loss'],[3,'net']]){if(number(r.cells[i])!==a[k])throw Error('金額');numbers++;}
  if(r.cells[4].textContent!==`${fmt(a.win_qty)} / ${fmt(a.loss_qty)} / ${fmt(a.flat_qty)}`)throw Error('枚数');
  if(number(r.cells[5])!==a.win_qty-a.loss_qty)throw Error('枚数差');
  const pf=a.loss?a.profit/a.loss:null,payoff=a.win_qty&&a.loss_qty&&a.loss?(a.profit/a.win_qty)/(a.loss/a.loss_qty):null;
  if(r.cells[6].textContent!==fmt(pf,2)||r.cells[7].textContent!==fmt(payoff,2))throw Error('場のPF/平均勝負');
  if(r.cells[8].textContent!==`${fmt(a.wins)} / ${fmt(a.cycles)}`)throw Error('組数');
  if(r.cells[9].textContent.replace('+','')!==fmt(a.w_net,2))throw Error('場W');wnumbers++;
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
   if(pr.length!==expected.length)throw Error('期間数');expected.forEach((a,i)=>check(pr[i],a));
   if(el('all-methods').querySelector('tbody').rows.length!==20)throw Error('比較数');
   if(el('width-comparison').querySelector('tbody').rows.length!==4)throw Error('幅比較数');
   for(const [id,list] of [['all-methods',RESULT.methods],['width-comparison',RESULT.methods.filter(x=>x.family===m.family)]]){
    const rows=el(id).querySelector('tbody').rows;
    list.forEach((method,i)=>['TOPIX','NK225'].forEach((sym,j)=>{
     const a=method.summary[sym],r=rows[i],base=1+j*4;
     if(number(r.cells[base])!==a.net||r.cells[base+1].textContent!==fmt(a.payoff,2)||r.cells[base+2].textContent!==`${a.positive_sessions}/${a.sessions}`||number(r.cells[base+3])!==a.without_best)throw Error('比較値');
     numbers+=2;
    }));
   }
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
     if(number(r.cells[2])!==o[6]||number(r.cells[3])!==o[7]||r.cells[6].textContent!==fmt(o[12],2)||number(r.cells[7])!==o[10]+1||number(r.cells[8])!==o[3])throw Error('注文値');
     if(o[4]===2&&number(r.cells[4])!==o[8])throw Error('返済金額');
    });
    const gs=el('width-groups').querySelector('tbody').rows;
    if(gs.length!==a.width_groups.length)throw Error('W組数');
    a.width_groups.forEach((g,i)=>{
     const r=gs[i];
     if(number(r.cells[0])!==g[0]+1||number(r.cells[2])!==g[6]||r.cells[1].textContent!==(g[5]>0?'買い':'売り'))throw Error('W識別');
     for(const [j,value,digits]of [[3,g[1],2],[4,g[2],3],[5,g[7],3],[6,g[8],3]]){if(r.cells[j].textContent.replace('+','')!==fmt(value,digits))throw Error('W組数値');wnumbers++;}
    });
    markers+=a.orders.length;accounts++;
   }
  }
 }
 el('method').value=DATA.defaultMethod;el('symbol').value='TOPIX';el('session').value=RESULT.sessions.at(-1);render();
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義');
 return {全合格:true,手法商品表示数:views,セッション表示数:accounts,金額照合数:numbers,W照合数:wnumbers,売買点数:markers,
         文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(verifyAll());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''


if __name__=='__main__':
    AUDIT.main()
