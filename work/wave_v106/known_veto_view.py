"""新二入口出口と保存二対照の全33場表を、広狭画面で数値・切替・暗色確認する。"""

import hashlib
import importlib.util
import json
from pathlib import Path

import known_veto_report


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main() -> None:
    """
    機能: 公開四比較の1360場表セル・代表24数値・20寄与を1450/520幅で確認する。
    引数: なし。保存済みHTMLと公開会計だけを利用する。
    返り値: None。金融・原板・APIは使わず、根の後続目視とは別に証跡を保存する。
    """
    source = (known_veto_report.PUBLIC/(known_veto_report.TITLE+'.html')).read_text(encoding='utf8')
    data = json.loads((known_veto_report.PUBLIC/'情報不足見送りの公開会計.json').read_text(encoding='utf8'))
    assert len(data['cases']) == 4 and len(data['sessions']) == 33
    tables, heads, differences = {}, [], {}
    fields = ('profit','loss','net','winning_lots','losing_lots')
    for identifier, case in data['cases'].items():
        index = {(r['session'],r['symbol']):r for r in case['rows']}
        assert len(index) == 66
        tables[identifier] = [[index[session,symbol][key] for symbol in ('TOPIX','NK225') for key in fields] for session in data['sessions']]
        tables[identifier].append([case['summary'][symbol][key] for symbol in ('TOPIX','NK225') for key in fields])
        heads.append([v for symbol in ('TOPIX','NK225') for v in (case['summary'][symbol]['net'],
                      f"{case['summary'][symbol]['positive']}/{case['summary'][symbol]['negative']}/{case['summary'][symbol]['no_trade']}",
                      case['summary'][symbol]['profit_share']*100,case['summary'][symbol]['top3_excluded'])])
        if case['diagnosis'] is not None:
            differences[identifier] = [[case['diagnosis'][symbol][key] for key in ('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')] for symbol in ('TOPIX','NK225')]
    # ----------------------------------------
    # 既存の隔離Chromeだけを利用し、表示実値と元会計を照合する。
    spec = importlib.util.spec_from_file_location('情報資格の表示だけの隔離Chrome',ROOT/'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    review = HERE/'review/known_veto'
    review.mkdir(parents=True,exist_ok=True)
    renderer.OUT = review
    renderer.VISUAL = review/'visual'
    payload = json.dumps(dict(tables=tables,heads=heads,differences=differences),ensure_ascii=False).replace('</','<\\/')
    renderer.PROBE = '''<script>
/**
 * 機能: 全四比較の場表・代表・寄与を元会計へ照合する。
 * @returns {object} 数値件数・切替件数・画面幅と背景。金融・通信は行わない。
 */
function verifyDisplay(){
 const data=__PAYLOAD__,first=document.getElementById('case').value;let count=0;
 /**
  * 機能: 円額・枚数・割合の表示丸めを元会計と比較する。
  * @param {HTMLTableCellElement} cell - 表示セル。
  * @param {number} value - 元会計の値。
  * @param {number} precision - 表示小数桁数。
  * @returns {undefined} 数値照合を加算し、不一致なら例外を出す。
  */
 function numeric(cell,value,precision=0){const v=Number(cell.textContent.replaceAll(',','').replace('%',''));if(Math.abs(v-value)>.500001*10**(-precision))throw Error('数値差:'+v+'/'+value);count++;}
 for(const [id,expected] of Object.entries(data.tables)){
  showCase(id);const visible=[...document.querySelectorAll('[data-case]')].filter(n=>!n.hidden);
  if(visible.length!==1||visible[0].dataset.case!==id)throw Error('切替差');
  const rows=visible[0].querySelector('table.sessions tbody').rows;if(rows.length!==34)throw Error('全33場と合計');
  for(let i=0;i<34;i++)for(let j=0;j<10;j++)numeric(rows[i].cells[j+1],expected[i][j]);
  if(data.differences[id]){const ds=visible[0].querySelector('details tbody').rows;if(ds.length!==2)throw Error('寄与行');for(let i=0;i<2;i++)for(let j=0;j<5;j++)numeric(ds[i].cells[j+1],data.differences[id][i][j]);}
 }
 const hs=document.querySelector('#comparison tbody').rows;if(hs.length!==4)throw Error('代表行');
 for(let i=0;i<4;i++)for(let j=0;j<8;j++){if(j%4===1){if(hs[i].cells[j+1].textContent!==data.heads[i][j])throw Error('場数差');}else numeric(hs[i].cells[j+1],data.heads[i][j],j%4===2?1:0);}
 showCase(first);if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 if(getComputedStyle(document.body).backgroundColor!=='rgb(11, 17, 32)')throw Error('背景');
 if(/undefined|NaN|Infinity/.test(document.body.innerText))throw Error('未知の数値化');
 return {全合格:true,比較数:4,数値照合:count,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,金融再生:0};
}
try{document.body.dataset.check=JSON.stringify(verifyDisplay());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''.replace('__PAYLOAD__',payload)
    screens = []
    for width in (1450,520):
        result = renderer.render(source,'情報資格四比較'+str(width),width,1200)
        result['HTML_SHA256'] = hashlib.sha256(source.encode()).hexdigest()
        screens.append(result)
    proof = dict(全合格=True,画面=screens,金融再生=0,API取得=0,目視確認=False)
    (review/'情報資格四比較の広狭確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__ == '__main__':
    main()
