"""直近位相の全18表示と33場合計を、売買再生なしで検査する。"""

import hashlib
import importlib.util
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PUBLIC=ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'


def run() -> None:
    """
    機能: 隔離Chromeで全条件の金額・枚数・全場合計と暗背景を広狭画面へ照合する。
    引数: なし。完成HTMLと公開会計のみを読む。
    返り値: None。原板、金融、APIを再実行しない。
    """
    spec=importlib.util.spec_from_file_location('直近位相表示の不変隔離描画',ROOT/'work/wave_v52/review/verify_report.py')
    renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
    renderer.OUT=PUBLIC;renderer.VISUAL=HERE/'review/visual'
    source=(PUBLIC/'直近の進行を分ける改善と全セッション損益.html').read_text(encoding='utf8')
    data=json.loads((PUBLIC/'直近位相の公開会計.json').read_text(encoding='utf8'));expected={}
    fields=('profit','loss','net','winning_lots','losing_lots')
    for ident,case in data['cases'].items():
        index={(row['session'],row['symbol']):row for row in case['rows']}
        rows=[[index[session,symbol][field] for symbol in ('TOPIX','NK225') for field in fields] for session in data['sessions']]
        rows.append([case['summary'][symbol][field] for symbol in ('TOPIX','NK225') for field in fields])
        expected[ident]=rows
    payload=json.dumps(expected,ensure_ascii=False,allow_nan=False).replace('</','<\\/')
    renderer.PROBE='''<script>
/**
 * 機能: 公開会計と18条件の33場及び合計の全数値を照合する。
 * @returns {object} 切替・数値・画面幅・暗背景の結果。通信や金融を行わない。
 */
function verifyDisplay(){
 const all=__DATA__;let count=0,views=0;
 for(const [id,expected] of Object.entries(all)){
  showCase(id);const visible=[...document.querySelectorAll('[data-case]')].filter(n=>!n.hidden);
  if(visible.length!==1||visible[0].dataset.case!==id)throw Error('切替:'+id);
  const rows=visible[0].querySelector('table.sessions tbody').rows;if(rows.length!==34)throw Error('場数と合計:'+id);
  for(let i=0;i<34;i++)for(let j=0;j<10;j++){
   const actual=Number(rows[i].cells[j+1].textContent.replaceAll(',',''));
   if(Math.abs(actual-expected[i][j])>=.5)throw Error('金額枚数:'+id+'/'+i+'/'+j);count++;
  }views++;
 }
 showCase('AUTO_ER40_M2_LIMIT_OWN_VETO');if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面の横溢れ');
 if(/undefined|NaN|Infinity/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,条件表示数:views,数値照合数:count,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:getComputedStyle(document.body).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(verifyDisplay());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''.replace('__DATA__',payload)
    values=[]
    for width,height in ((1450,1200),(520,1200)):
        value=renderer.render(source,'直近位相'+str(width),width,height)
        value['HTML_SHA256']=hashlib.sha256(source.encode('utf8')).hexdigest();values.append(value)
    proof=dict(全合格=True,画面=values,金融再生=0,API取得=0,目視確認=False)
    (HERE/'review/直近位相の表示検査.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':run()
