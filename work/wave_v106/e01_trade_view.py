"""完成E0146表示の全場数値と暗背景を、金融再生なしで広狭確認する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import e01_trade_report


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def run(destination: Path) -> None:
    """
    機能: 隔離Chromeで全46表の金額/枚数/合計とheadの代表指標を1450/520幅で確認する。
    引数: destination(Path)は根が生成したHTML/公開会計の位置。
    返り値: None。元結果・金融・板・APIは再実行しない。目視は根が別に行う。
    """
    specification=importlib.util.spec_from_file_location('E01表示の隔離Chrome確認',ROOT/'work/wave_v52/review/verify_report.py')
    renderer=importlib.util.module_from_spec(specification);specification.loader.exec_module(renderer)
    review=HERE/'review/e01_trade';review.mkdir(parents=True,exist_ok=True);renderer.OUT=review;renderer.VISUAL=review/'visual'
    source=(destination/(e01_trade_report.TITLE+'.html')).read_text(encoding='utf8')
    data=json.loads((destination/e01_trade_report.ACCOUNTING_TITLE).read_text(encoding='utf8'));assert len(data['cases'])==46
    expected={};fields=('profit','loss','net','winning_lots','losing_lots')
    for identifier,case in data['cases'].items():
        index={(r['session'],r['symbol']):r for r in case['rows']};assert len(index)==66
        expected[identifier]=[[index[s,m][f] for m in ('TOPIX','NK225') for f in fields] for s in data['sessions']]
        expected[identifier].append([case['summary'][m][f] for m in ('TOPIX','NK225') for f in fields])
    heads=[];diagnoses={}
    for identifier,label in data['head']:
        for symbol in ('TOPIX','NK225'):
            v=data['cases'][identifier]['summary'][symbol]
            heads.append(dict(net=v['net'],counts=f'{v["positive"]}/{v["negative"]}/{v["no_trade"]}',
                pct=v['profit_share']*100 if v['profit_share'] is not None else None,pf=v['pf'],median=v['active_median'],top3=v['top3_excluded'],worst=v['worst']))
    for identifier,case in data['cases'].items():
        if case['diagnosis']:
            diagnoses[identifier]=[[case['diagnosis'][s][k] for k in ('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')]+[case['diagnosis'][s].get('元勝ち親が赤字化')] for s in ('TOPIX','NK225')]
    payload=json.dumps(dict(tables=expected,heads=heads,diagnoses=diagnoses),ensure_ascii=False,allow_nan=False).replace('</','<\\/')
    renderer.PROBE='''<script>
/**
 * 機能: E01全46選択肢・全33場と合計の数値/切替/暗背景を確認する。
 * @returns {object} 表示検査結果。金融やAPIは実行しない。
 */
function verifyDisplay(){
 const data=__DATA__,all=data.tables;let count=0,views=0;
 /**
  * 機能: 保存会計と表示値を、表示桁の丸め誤差以内で照合する。
  * @param {HTMLTableCellElement} cell - 対象の表示セル。
  * @param {number|null} value - 元会計の値。不明値は数値へ補完しない。
  * @param {number} precision - 表示する小数桁数。
  * @returns {undefined} 合格件数を更新し、不一致なら例外を出す。
  */
 function numeric(cell,value,precision=0){
  if(value===null){if(cell.textContent.trim()!=='—')throw Error('不明を数値に補完');return;}
  const v=Number(cell.textContent.replaceAll(',','').replace('%',''));
  if(Math.abs(v-value)>.500001*10**(-precision))throw Error('数値差:'+v+'/'+value);count++;
 }
 for(const [id,expected] of Object.entries(all)){
  showCase(id);const visible=[...document.querySelectorAll('[data-case]')].filter(n=>!n.hidden);
  if(visible.length!==1||visible[0].dataset.case!==id)throw Error('切替:'+id);
  const rows=visible[0].querySelector('table.sessions tbody').rows;if(rows.length!==34)throw Error('全33と合計:'+id);
  for(let i=0;i<34;i++)for(let j=0;j<10;j++)numeric(rows[i].cells[j+1],expected[i][j]);
  if(data.diagnoses[id]){
   const dr=visible[0].querySelector('details table tbody').rows;
   for(let i=0;i<2;i++)for(let j=0;j<6;j++)numeric(dr[i].cells[j+1],data.diagnoses[id][i][j]);
  }views++;
 }
 const head=document.querySelector('#comparison tbody').rows;
 if(head.length!==data.heads.length)throw Error('先頭比較行数');
 for(let i=0;i<head.length;i++){
  const h=data.heads[i],cells=head[i].cells;
  numeric(cells[2],h.net);if(cells[3].textContent!==h.counts)throw Error('黒赤無取引');
  numeric(cells[4],h.pct,1);numeric(cells[5],h.pf,2);numeric(cells[6],h.median);numeric(cells[7],h.top3);numeric(cells[8],h.worst);
 }
 showCase('E01_TRADE_W60_VETO_D0_P1L8');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面の横溢れ');
 if(/undefined|NaN|Infinity/.test(document.body.innerText))throw Error('未定義表示');
 const background=getComputedStyle(document.body).backgroundColor;
 if(background!=='rgb(11, 17, 32)')throw Error('ダーク背景:'+background);
 return {全合格:true,条件表示数:views,数値照合数:count,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:background};
}
try{document.body.dataset.check=JSON.stringify(verifyDisplay());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''.replace('__DATA__',payload)
    values=[]
    for width,height in ((1450,1200),(520,1200)):
        value=renderer.render(source,'E01取引更新'+str(width),width,height);value['HTML_SHA256']=hashlib.sha256(source.encode()).hexdigest();values.append(value)
    proof=dict(全合格=True,画面=values,金融再生=0,巨大ledger読取=0,原NPZ読取=0,API取得=0,目視確認=False)
    (review/'E01全46表示の広狭検査.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,default=e01_trade_report.PUBLIC);args=parser.parse_args();run(args.output_dir)
