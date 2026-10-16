"""現在ナイト途中表示の六口座と時計を、隔離Chromeの広狭画面で検算する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import current_report


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def verify_data(data: dict) -> dict:
    """
    機能: 表示会計の固定三条件と実現/未返済の二恒等式を検査する。
    引数: data(dict)は根が公開した小さい表示会計。
    返り値: dictはブラウザーへ渡す数値と商品時計。
    """
    assert data['session']==current_report.SESSION and data['途中終端']
    assert len(data['rows'])==6 and data['E01の未見検証']=='未測定'
    assert [(r['id'],r['symbol']) for r in data['rows']]==[(i,s) for i in current_report.IDENTIFIERS for s in current_report.SYMBOLS]
    values=[]
    for row in data['rows']:
        assert abs(row['realized_profit']-row['realized_loss']-row['realized_net'])<1e-4
        assert abs(row['realized_net']+row['open_mark_net']-row['actual_liquidation_value'])<1e-4
        values.append([row[k] for k in current_report.FIELDS])
    clocks=[[current_report.clock_text(data['clocks'][s][k]) for k in ('as_of','capture_start','capture_end','last_price_clock')] for s in current_report.SYMBOLS]
    return dict(numbers=values,clocks=clocks)


def run(destination: Path) -> None:
    """
    機能: 六口座の全値・二商品の全時計・暗色/横溢れを1450と520幅で確認する。
    引数: destination(Path)は根が生成したHTMLと表示会計の位置。
    返り値: None。現在入力・台帳・金融・APIは読まず、私有reviewだけへ保存する。
    """
    report=destination/(current_report.TITLE+'.html');account=destination/current_report.ACCOUNTING_TITLE
    if not report.exists() or not account.exists():print('現在ナイトの公開表示待ち。');return
    source=report.read_text(encoding='utf8');data=json.loads(account.read_text(encoding='utf8'));expected=verify_data(data)
    specification=importlib.util.spec_from_file_location('106現在ナイト表示の隔離Chrome',ROOT/'work/wave_v52/review/verify_report.py')
    renderer=importlib.util.module_from_spec(specification);specification.loader.exec_module(renderer)
    review=HERE/'review/current';review.mkdir(parents=True,exist_ok=True);renderer.OUT=review;renderer.VISUAL=review/'visual'
    payload=json.dumps(expected,ensure_ascii=False,allow_nan=False).replace('</','<\\/')
    renderer.PROBE='''<script>
/**
 * 機能: 保存された接頭会計とHTMLの全値・時計を照合する。
 * @returns {object} 数値照合件数・画面幅・暗色背景。売買と通信は実行しない。
 */
function verifyDisplay(){
 const expected=__DATA__,rows=document.querySelector('#accounts tbody').rows;let count=0;
 if(rows.length!==6)throw Error('固定六口座ではない');
 for(let i=0;i<6;i++)for(let j=0;j<11;j++){
  const v=Number(rows[i].cells[j+2].textContent.replaceAll(',',''));
  if(Math.abs(v-expected.numbers[i][j])>.500001)throw Error('途中会計の表示差');count++;
 }
 const clocks=document.querySelector('#clocks tbody').rows;
 if(clocks.length!==2)throw Error('商品時計の行数');
 for(let i=0;i<2;i++)for(let j=0;j<4;j++)if(clocks[i].cells[j+1].textContent!==expected.clocks[i][j])throw Error('時計の表示差');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面の横溢れ');
 if(/undefined|NaN|Infinity/.test(document.body.innerText))throw Error('未知表示を補完');
 if(!document.body.innerText.includes('E01新候補の未見試験は行っていません'))throw Error('未測定を省略');
 const background=getComputedStyle(document.body).backgroundColor;
 if(background!=='rgb(11, 17, 32)')throw Error('ダーク背景');
 return {全合格:true,口座数:6,数値照合数:count,時計照合数:8,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:background};
}
try{document.body.dataset.check=JSON.stringify(verifyDisplay());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''.replace('__DATA__',payload)
    values=[]
    for width,height in ((1450,1200),(520,1200)):
        result=renderer.render(source,'現在ナイト途中'+str(width),width,height)
        result['HTML_SHA256']=hashlib.sha256(source.encode()).hexdigest();values.append(result)
    proof=dict(全合格=True,画面=values,金融再生=0,台帳読取=0,原NPZ読取=0,API取得=0,目視確認=False)
    (review/'現在ナイト途中の広狭表示検査.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='途中六口座の表示だけを広狭確認')
    parser.add_argument('--output-dir',type=Path,default=current_report.PUBLIC);args=parser.parse_args();run(args.output_dir)
