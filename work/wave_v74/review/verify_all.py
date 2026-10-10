"""全条件一覧の各商品・各期間・全保存場の金額を独立照合する。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00070_始値と前終値の方向制限と連敗休止'
VISUAL=HERE/'visual'

PROBE=r'''<script>
/**
 * 機能: 各条件の全金額と商品切替、一覧の比較指標を照合する。
 * @returns {object} 照合件数と表示品質。
 */
function independentVerify(){
 const {D,STATE,condition,filtered}=window.reportTest;
 const el=id=>document.getElementById(id),num=e=>Number(e.textContent.replace(/[,\s円＋+]/g,'')),pct=v=>v===null?'—':(v*100).toFixed(1)+'%';
 let views=0,numbers=0,rankings=0;
 const near=(a,b,key)=>{if(!Number.isFinite(a)||Math.abs(a-b)>1e-5)throw Error(key+':'+a+'/'+b);};
 const moneyRow=(tr,a)=>{
  for(const [j,k]of[[1,'profit'],[2,'loss'],[3,'net'],[5,'trades'],[7,'fees'],[8,'pause_count']]){near(num(tr.cells[j]),a[k],k);numbers++;}
  near(a.profit-a.loss,a.net,'利益損失差');
  const rate=a.profit+a.loss?a.loss/(a.profit+a.loss):null;
  if(tr.cells[4].textContent!==pct(rate)||a.money_loss_share!==rate)throw Error('金額損失割合');
  if(tr.cells[6].textContent!==`${a.winning_lots}／${a.losing_lots}`)throw Error('勝負枚数');
 };
 for(const symbol of ['TOPIX','NK225']){
  el('symbol').value=symbol;el('symbol').dispatchEvent(new Event('change'));
  if(STATE.symbol!==symbol)throw Error('商品切替');
  for(const period of ['前16','後13','全29']){
   el('period').value=period;el('period').dispatchEvent(new Event('change'));
   const rows=el('ranking').querySelector('tbody').rows,sorted=filtered();
   if(rows.length!==D.methods.length||sorted.length!==D.methods.length)throw Error('全条件数');
   sorted.forEach((m,j)=>{const a=m.periods[period][symbol],tr=rows[j];if(tr.querySelector('button').dataset.id!==m.id)throw Error('ID順');for(const [k,f]of[[2,'profit'],[3,'loss'],[4,'net'],[6,'trades']])near(num(tr.cells[k]),a[f],f);if(tr.cells[5].textContent!==pct(a.money_loss_share))throw Error('一覧割合');});
   rankings++;
  }
  for(const m of D.methods){
   STATE.id=m.id;condition();
   const rows=el('sessions').querySelector('tbody').rows;
   if(rows.length!==30)throw Error('全場数');
   D.sessions.forEach((s,j)=>moneyRow(rows[j],m.rows.find(r=>r.session===s&&r.symbol===symbol)));
   moneyRow(rows[29],m.periods.全29[symbol]);
   const prs=el('period-table').querySelector('tbody').rows;
   ['前16','後13','全29'].forEach((p,j)=>moneyRow(prs[j],m.periods[p][symbol]));
   views++;
  }
 }
 for(const group of ['all',...new Set(D.methods.map(m=>m.config.group))]){
  el('group').value=group;el('group').dispatchEvent(new Event('change'));
  if(el('ranking').querySelector('tbody').rows.length!==D.methods.filter(m=>group==='all'||m.config.group===group).length)throw Error('群選択');
 }
 el('group').value='all';el('symbol').value='TOPIX';el('period').value='全29';window.reportTest.render();
 const ident=D.selectedIds.find(id=>D.methods.some(m=>m.id===id))??D.methods[0].id;
 el('method').value=ident;el('method').dispatchEvent(new Event('change'));
 if(STATE.id!==ident)throw Error('条件選択');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');
 if(getComputedStyle(document.documentElement).colorScheme!=='dark')throw Error('暗色');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('表示未定義');
 return {全合格:true,条件数:D.methods.length,商品別全場表示数:views,金額照合数:numbers,一覧照合数:rankings,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e),stack:e.stack});}
</script>'''


def main() -> None:
    """機能: 独立したブラウザで全条件表の金額・操作を確認する。

    引数: --extra(bool)。返り値: なし(None)。公開物は変更しない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--extra',action='store_true')
    args=parser.parse_args()
    source=OUT/('追加240条件の比較とセッション損益.html' if args.extra else '全480条件の比較とセッション損益.html')
    prefix='追加一覧' if args.extra else '全一覧'
    VISUAL.mkdir(parents=True,exist_ok=True)
    sys.dont_write_bytecode=True
    spec=importlib.util.spec_from_file_location('隔離表示',ROOT/'work/wave_v52/review/verify_report.py')
    helper=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.OUT,helper.VISUAL,helper.PROBE=OUT,VISUAL,PROBE
    text=source.read_text(encoding='utf8')
    results=[helper.render(text,prefix,1450,1300),helper.render(text,prefix+'_狭幅',520,1300)]
    proof=dict(全合格=True,目視確認=False,HTML_SHA256=hashlib.sha256(source.read_bytes()).hexdigest(),結果=results)
    (HERE/(prefix+'表示の独立検査.json')).write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    main()
