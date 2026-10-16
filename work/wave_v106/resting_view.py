"""常設利確十二条件の全場会計・同入口二法差を広狭表示で検査する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import resting_report


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
ACCOUNTING_TITLE='常設利確と成行返済の公開会計.json'
SYMBOLS=('TOPIX','NK225')
CONTRIBUTIONS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支','元勝ち親が赤字化')


def expected_values(data: dict) -> dict:
    """
    機能: 十二条件の全33場と合計・同入口二法差・観測呼値・先頭指標を取得する。
    引数: data(dict)は公開小会計。金融台帳や原本は読まない。
    返り値: dictはHTMLの表示検査用値。不明割合は0へ補完しない。
    """
    sessions=data['sessions'];assert len(sessions)==33 and len(set(sessions))==33
    cases=data['cases'];assert len(cases)==12 and data['observed_tick']=={'TOPIX':.5,'NK225':10}
    assert data['actual_product_tick']=={'TOPIXmini':.25,'NK225micro':5}
    tables={};diagnosis={};headers={}
    fields=('profit','loss','net','winning_lots','losing_lots')
    for identifier,case in cases.items():
        assert case['config']['takeprofit_ticks']==1 and case['config']['stop_ticks'] in (4,8,16)
        index={(r['session'],r['symbol']):r for r in case['rows']}
        assert len(index)==66 and len(case['rows'])==66
        tables[identifier]=[[index[session,symbol][field] for symbol in SYMBOLS for field in fields] for session in sessions]
        tables[identifier].append([case['summary'][symbol][field] for symbol in SYMBOLS for field in fields])
        diagnosis[identifier]=[[case['order_comparison'][symbol][field] for field in CONTRIBUTIONS] for symbol in SYMBOLS]
        headers[identifier]=[]
        for symbol in SYMBOLS:
            value=case['summary'][symbol]
            assert abs(value['profit']-value['loss']-value['net'])<1e-4
            headers[identifier].append(dict(net=value['net'],counts=f'{value["positive"]}/{value["negative"]}/{value["no_trade"]}',
                percentage=value['profit_share']*100 if value['profit_share'] is not None else None,top3=value['top3_excluded']))
    return dict(tables=tables,diagnosis=diagnosis,headers=headers,first=next(iter(cases)),
        losses={id:value['config']['stop_ticks'] for id,value in cases.items()})


def run(destination: Path) -> None:
    """
    機能: 十二条件の全数値を1450/520幅の隔離Chromeで照合し、私有proofを保存する。
    引数: destination(Path)は根が生成したHTMLと公開会計の保存先。
    返り値: None。金融・原板・原NPZ・現在APIを実行しない。目視は根が別に行う。
    """
    report=destination/(resting_report.TITLE+'.html');account=destination/ACCOUNTING_TITLE
    if not report.exists() or not account.exists():print('常設利確12の完成公開表示待ち。');return
    saved=report.read_bytes();document=saved.decode('utf8');data=json.loads(account.read_bytes())
    financial=resting_report.SOURCE.read_bytes()
    assert data==resting_report.build(json.loads(financial),hashlib.sha256(financial).hexdigest())
    expected=expected_values(data)
    specification=importlib.util.spec_from_file_location('106常設利確十二条件の隔離Chrome',ROOT/'work/wave_v52/review/verify_report.py')
    renderer=importlib.util.module_from_spec(specification);specification.loader.exec_module(renderer)
    review=HERE/'review/resting';review.mkdir(parents=True,exist_ok=True);renderer.OUT=review;renderer.VISUAL=review/'visual'
    payload=json.dumps(expected,ensure_ascii=False,allow_nan=False).replace('</','<\\/')
    renderer.PROBE='''<script>
/**
 * 機能: 全場合計・二法差・先頭値・観測呼値と損失幅を保存会計へ照合する。
 * @returns {object} 表示件数・照合件数・画面幅・背景。通信と金融は行わない。
 */
function verifyDisplay(){
 const data=__DATA__;let count=0,views=0,diagnosisCount=0,headerCount=0;
 /**
  * 機能: 表示値と保存値を、表示桁の丸め幅以内で照合する。
  * @param {HTMLTableCellElement} cell - 対象セル。
  * @param {number|null} value - 保存値。不明はダッシュ表示を要求する。
  * @param {number} precision - 小数桁数。
  * @returns {undefined} 合格数を更新。不一致は例外で停止する。
  */
 function numeric(cell,value,precision=0){
  if(value===null){if(cell.textContent.trim()!=='—')throw Error('不明値の0補完');return;}
  const text=cell.textContent.trim();if(!text)throw Error('空セル');
  const actual=Number(text.replaceAll(',','').replace('%',''));
  if(!Number.isFinite(actual)||Math.abs(actual-value)>.500001*10**(-precision))throw Error('表示数値差:'+actual+'/'+value);count++;
 }
 if(document.getElementById('case').options.length!==12)throw Error('条件選択数');
 for(const [id,expected] of Object.entries(data.tables)){
  showCase(id);const visible=[...document.querySelectorAll('[data-case]')].filter(n=>!n.hidden);
  if(visible.length!==1||visible[0].dataset.case!==id||document.getElementById('case').value!==id)throw Error('表示切替');
  if(!visible[0].innerText.includes('建値から'+data.losses[id]+'観測呼値'))throw Error('条件別損切り幅');
  if(!visible[0].innerText.includes('ラージ板の観測1呼値（TOPIX 0.5pt／日経10円）'))throw Error('観測一呼値');
  if(!visible[0].innerText.includes('実ミニ／マイクロの2呼値'))throw Error('実商品二呼値');
  const rows=visible[0].querySelector('table.sessions tbody').rows;
  if(rows.length!==34)throw Error('全33場と合計の行数');
  for(let i=0;i<34;i++)for(let j=0;j<10;j++)numeric(rows[i].cells[j+1],expected[i][j]);
  const dr=visible[0].querySelector('details table tbody').rows;
  if(dr.length!==2)throw Error('同入口二法差の両商品行数');
  for(let i=0;i<2;i++)for(let j=0;j<6;j++){numeric(dr[i].cells[j+1],data.diagnosis[id][i][j]);diagnosisCount++;}
  views++;
 }
 const headers=document.querySelector('#comparison tbody').rows;
 if(headers.length!==12)throw Error('先頭十二条件の行数');
 for(const row of headers){
  const id=row.cells[0].textContent.trim(),values=data.headers[id];if(!values)throw Error('先頭条件ID');
  for(let j=0;j<2;j++){
   const item=values[j],base=1+j*4;
   numeric(row.cells[base],item.net);if(row.cells[base+1].textContent!==item.counts)throw Error('黒赤無取引');
   numeric(row.cells[base+2],item.percentage,1);numeric(row.cells[base+3],item.top3);headerCount+=4;
  }
 }
 showCase(data.first);
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面の横溢れ');
 if(/undefined|NaN|Infinity/.test(document.body.innerText))throw Error('未定義表示');
 const background=getComputedStyle(document.body).backgroundColor;
 if(background!=='rgb(11, 17, 32)')throw Error('ダーク背景');
 return {全合格:true,条件表示数:views,全数値照合数:count,全場合計数値:12*34*10,診断照合数:diagnosisCount,先頭指標照合数:headerCount,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:background};
}
try{document.body.dataset.check=JSON.stringify(verifyDisplay());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''.replace('__DATA__',payload)
    values=[]
    for width,height in ((1450,1200),(520,1200)):
        proof=renderer.render(document,'常設利確十二条件'+str(width),width,height);proof['HTML_SHA256']=hashlib.sha256(saved).hexdigest();values.append(proof)
    result=dict(全合格=True,画面=values,金融再生=0,原NPZ読取=0,原板読取=0,API取得=0,目視確認=False,
        source=data['source'],公開会計SHA256=hashlib.sha256(account.read_bytes()).hexdigest(),
        source_SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__).resolve(),HERE/'resting_report.py')})
    (review/'常設利確12の広狭検査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='常設利確十二条件の全場表示検査のみ')
    parser.add_argument('--output-dir',type=Path,default=resting_report.PUBLIC);args=parser.parse_args();run(args.output_dir)
