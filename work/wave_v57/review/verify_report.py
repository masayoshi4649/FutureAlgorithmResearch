"""補充3手法の全条件・三価格評価を実Chromeで照合する。"""

from pathlib import Path
import hashlib
import importlib.util
import json
from urllib.parse import unquote

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00054_補充監視3手法の実装とセッション損益'
SOURCE=OUT/'補充監視3手法の説明と損益.html'
SPEC=importlib.util.spec_from_file_location('replenishment_browser',ROOT/'work/wave_v52/review/verify_report.py')
BROWSER=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROWSER)
BROWSER.OUT=OUT
BROWSER.VISUAL=HERE/'visual'

PROBE=r'''<script>
/**
 * 機能: 全条件・商品・価格評価・セッションの会計表示を照合する。
 * @returns {object} 検査件数と画面品質。
 */
function verifyAll(){
 let views=0,accounts=0,numbers=0,orders=0;
 const number=c=>Number(c.textContent.replaceAll(',','').trim());
 const check=(r,a)=>{
  const expected=[a.profit,a.loss,a.net,a.win_qty,a.loss_qty,a.flat_qty,a.win_qty-a.loss_qty,a.cycles];
  expected.forEach((v,j)=>{if(number(r.cells[j+1])!==v)throw Error('会計表示:'+j);numbers++;});
 };
 const primary=new Map();
 for(const f of DATA.families){
  const m=RESULT.methods.find(m=>m.family===f.id&&m.main),rows=el(`primary-sessions-${f.id}`).querySelector('tbody').rows;
  if(el(`condition-${f.id}`).value!==m.id||el(`price-${f.id}`).value!=='中値')throw Error('初期表示');
  if(rows.length!==23)throw Error('主条件場数');
  RESULT.sessions.forEach((session,i)=>['TOPIX','NK225'].forEach((symbol,j)=>{
   const a=m.accounts.find(a=>a.session===session&&a.symbol===symbol);
   if(rows[i].cells[0].textContent!==session||number(rows[i].cells[j*2+1])!==a.net||number(rows[i].cells[j*2+2])!==a.sensitivity['中値'].net)throw Error('主条件場収支');
   numbers+=2;
  }));
  primary.set(f.id,el(`primary-sessions-${f.id}`).innerHTML);
 }
 for(const m of RESULT.methods){
  const family=m.family;el(`condition-${family}`).value=m.id;
  for(const symbol of ['TOPIX','NK225'])for(const mode of ['最後値','中値','売買気配']){
   el(`symbol-${family}`).value=symbol;el(`price-${family}`).value=mode;render(family);
   if(el(`primary-sessions-${family}`).innerHTML!==primary.get(family))throw Error('主条件を書換え');
   const group=m.accounts.filter(a=>a.symbol===symbol),rs=el(`sessions-${family}`).querySelector('tbody').rows;
   if(rs.length!==23)throw Error('場数');
   group.forEach((a,i)=>{if(rs[i].cells[0].textContent!==a.session)throw Error('場名');check(rs[i],mode==='最後値'?a:a.sensitivity[mode]);});
   const periods=DATA.periods[m.id][symbol][mode],pr=el(`periods-${family}`).querySelector('tbody').rows;
   if(pr.length!==periods.length)throw Error('期間数');periods.forEach((a,i)=>check(pr[i],a));
   const comparison=el(`comparison-${family}`).querySelector('tbody').rows,list=RESULT.methods.filter(x=>x.family===family);
   if(comparison.length!==4)throw Error('条件数');
   list.forEach((x,i)=>['TOPIX','NK225'].forEach((sym,j)=>{
    const s=x.summary[sym],expected=[s.net,s.sensitivity['中値'].net,s.sensitivity['売買気配'].net];
    expected.forEach((v,k)=>{if(number(comparison[i].cells[j*3+k+1])!==v)throw Error('比較値');numbers++;});
   }));
   const s=mode==='最後値'?m.summary[symbol]:m.summary[symbol].sensitivity[mode],metrics=el(`summary-${family}`).querySelectorAll('.metric');
   if(metrics[0].textContent.replaceAll(',','').replace('円','')!==`${s.net>0?'+':''}${s.net}`)throw Error('大表示収支');
   if(metrics[1].textContent!==fmt(s.payoff,2)+'倍'||metrics[2].textContent!==`${s.positive_sessions} / ${s.sessions}`)throw Error('大表示比率');
   if(mode!=='最後値'&&!el(`summary-${family}`).textContent.includes('未算出'))throw Error('未算出DD');
   const sr=el(`sensitivity-${family}`).querySelector('tbody').rows;
   DATA.sensitivity[m.id][symbol].forEach((a,i)=>['profit','loss','net'].forEach((key,j)=>{
    if(number(sr[i].cells[j+1])!==a[key])throw Error('感度表');numbers++;
   }));
   if(!el(`sensitivity-${family}`).closest('details').open)throw Error('感度が隠れている');
   views++;
   for(const a of group){
    el(`session-${family}`).value=a.session;renderOrders(family);
    const rows=el(`orders-${family}`).querySelector('tbody').rows;
    if(rows.length!==a.orders.length)throw Error('注文数');
    a.orders.forEach((o,i)=>{
     const r=rows[i];
     if(number(r.cells[2])!==o[6]||number(r.cells[3])!==o[7]||number(r.cells[6])!==o[10]+1)throw Error('注文値');
     if(o[4]===2&&number(r.cells[4])!==o[8])throw Error('返済額');
    });
    orders+=a.orders.length;accounts++;
   }
  }
 }
 for(const f of DATA.families){el(`condition-${f.id}`).value=RESULT.methods.find(m=>m.family===f.id&&m.main).id;el(`symbol-${f.id}`).value='TOPIX';el(`price-${f.id}`).value='中値';el(`session-${f.id}`).value=RESULT.sessions.at(-1);render(f.id);}
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義');
 return {全合格:true,条件商品価格表示数:views,セッション表示数:accounts,数値照合数:numbers,注文表示照合数:orders,
         文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(verifyAll());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''

SMALL=r'''<script>
try{
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 document.body.dataset.check=JSON.stringify({全合格:true,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth});
}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''


def main() -> None:
    """機能: 埋込値と保存結果を照合し、全操作と広狭画面を保存する。

    引数: なし。返り値: なし(None)。HTML原本は変更せず複製を表示する。
    """
    original=SOURCE.read_bytes();source=original.decode('utf8').replace('\r\n','\n');digest=hashlib.sha256(original).hexdigest()
    soup=BeautifulSoup(source,'html.parser');links=0
    for tag in soup.select('a[href],img[src]'):
        link=tag.get('href',tag.get('src'))
        if link.startswith(('http','#')):
            continue
        assert (OUT/unquote(link.split('#')[0].split('?')[0])).exists(),link
        links+=1
    payload=json.loads(soup.select_one('script#data').string)
    saved=json.loads((HERE.parent/'売買結果.json').read_text(encoding='utf8'))
    for actual,expected in zip(payload['results']['methods'],saved['methods']):
        assert actual['id']==expected['id']
        for a,b in zip(actual['accounts'],expected['accounts']):
            assert a=={k:v for k,v in b.items() if k!='trades'}
        for symbol in ('TOPIX','NK225'):
            for mode,rows in payload['periods'][actual['id']][symbol].items():
                for row in rows:
                    name=row['name']
                    if name=='前10場':
                        sessions=saved['sessions'][:10]
                    elif name=='次9場':
                        sessions=saved['sessions'][10:19]
                    elif name=='後4場':
                        sessions=saved['sessions'][19:]
                    else:
                        from datetime import date
                        start=date.fromisoformat(name[:10])
                        sessions=[x for x in saved['sessions'] if 0<=(date.fromisoformat(x[:10])-start).days<7]
                    accounts=[a if mode=='最後値' else a['sensitivity'][mode] for a in expected['accounts'] if a['symbol']==symbol and a['session'] in sessions]
                    for key in ('profit','loss','net','win_qty','loss_qty','flat_qty','cycles','wins','losses'):
                        assert row[key]==sum(a[key] for a in accounts), (actual['id'],symbol,mode,name,key)
    BROWSER.PROBE=PROBE
    screens=[BROWSER.render(source,'全体と全選択',1500,1500)]
    BROWSER.PROBE=SMALL
    screens.append(BROWSER.render(source,'狭幅',520,1500))
    screens.append(BROWSER.render(source,'手法章',1500,1500,'<script>document.querySelector("main").replaceChildren(document.querySelector("#R1"));window.scrollTo(0,0);</script>'))
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==digest,'検査中に原本HTMLが変更された'
    result=dict(全合格=True,静的リンク数=links,埋込552口座と保存結果一致=True,期間再集計一致=True,
                HTML_SHA256=digest,目視確認=False,画面=screens)
    (HERE/'HTML表示の独立検査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
