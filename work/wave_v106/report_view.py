"""完成会計の表示を隔離Chromeで検査する。金融・原板・APIは再実行しない。"""

import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'


def main() -> None:
    """
    機能: 二つのHTMLの全条件33場表示と広狭画面を検査し画像を保存する。
    引数: なし。公開HTMLと公開会計JSONを読み取る。
    返り値: None。過去の隔離描画関数を再利用し、通常ブラウザを操作しない。
    """
    spec = importlib.util.spec_from_file_location('保存済み隔離描画',ROOT/'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = PUBLIC
    renderer.VISUAL = HERE/'review/visual'
    renderer.VISUAL.parent.mkdir(parents=True,exist_ok=True)
    result = []
    for title, filename, e01 in (
        ('板入口','改善手法と全セッション損益.html',False),
        ('E01','E01の改善比較と全セッション損益.html',True),
    ):
        source = (PUBLIC/filename).read_text(encoding='utf-8')
        data = json.loads((PUBLIC/('E01公開会計.json' if e01 else '公開会計.json')).read_text(encoding='utf-8'))
        cases = data['results'] if e01 else data['cases']
        fields = ('利益','損失','収支','勝ち枚数','負け枚数') if e01 else ('profit','loss','net','winning_lots','losing_lots')
        expected = {}
        for ident,case in cases.items():
            index = {(r['session'],r['symbol']):r for r in case['rows']}
            expected[ident] = [[value for symbol in ('TOPIX','NK225') for value in
                (index[session,symbol][key] for key in fields)] for session in data['sessions']]
        payload = json.dumps(expected,ensure_ascii=False,allow_nan=False).replace('</','<\\/')
        renderer.PROBE = '''<script>
/**
 * 保存会計と全切替画面の金額・枚数を照合する。
 * @returns {object} 検査件数・横溢れ・背景色を返す。通信・売買は行わない。
 */
function verifyDisplay(){
 const expected=__EXPECTED__;let numbers=0,views=0;
 for(const [id,rows] of Object.entries(expected)){
  showCase(id);
  const visible=[...document.querySelectorAll('[data-case]')].filter(n=>!n.hidden);
  if(visible.length!==1||visible[0].dataset.case!==id)throw Error('切替:'+id);
  const cells=visible[0].querySelector('table tbody').rows;
  if(cells.length!==33)throw Error('全33場:'+id);
  for(let i=0;i<33;i++)for(let j=0;j<10;j++){
   const actual=Number(cells[i].cells[j+1].textContent.replaceAll(',',''));
   if(Math.abs(actual-rows[i][j])>=.5)throw Error('会計表示:'+id+'/'+i+'/'+j);
   numbers++;
  }
  views++;
 }
 showCase(Object.keys(expected)[0]);
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面横溢れ');
 if(/undefined|NaN|Infinity/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,条件表示数:views,数値照合数:numbers,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:getComputedStyle(document.body).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(verifyDisplay());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''.replace('__EXPECTED__',payload)
        for width,height in ((1450,1200),(520,1200)):
            item = renderer.render(source,title+str(width),width,height)
            item['HTML_SHA256'] = hashlib.sha256(source.encode('utf-8')).hexdigest()
            result.append(item)
    proof = dict(全合格=True,金融再生=0,API取得=0,目視確認=False,画面=result)
    (HERE/'review/表示検査.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    main()
