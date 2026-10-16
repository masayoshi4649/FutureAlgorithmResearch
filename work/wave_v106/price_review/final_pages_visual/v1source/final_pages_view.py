"""公開された短い結論と現在入力失敗の二表示を、保存小根拠と隔離Chromeで検査する。"""

import hashlib
import importlib.util
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PUBLIC=ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'
GROUND=PUBLIC/'今回の結論の表示根拠.json'
TITLES=('今回の結論と残す候補','現在ナイト一回照合の入力検査')


def browser_copy(document: str) -> str:
    """
    機能: 公開HTMLの省略されたhead/bodyを、隔離コピーだけで明示して検査scriptを挿入可能にする。
    引数: document(str)は元公開HTML。
    返り値: strは同じ本文/スタイルを持つ検査用コピー。公開ファイルを変更しない。
    """
    if '</body>' in document:return document
    assert document.count('<html lang="ja">')==document.count('</style>')==document.count('</html>')==1
    return document.replace('<html lang="ja">','<html lang="ja"><head>',1).replace('</style>','</style></head><body>',1).replace('</html>','</body></html>',1)


def probe(ground: dict, kind: str) -> str:
    """
    機能: 保存根拠から全セル・未測定文言・暗背景/横溢れを照合するJSを作成する。
    引数: ground(dict)、kind(str)は表示根拠と既知/現在の対象。
    返り値: strは通信や金融を含まない検査script。
    """
    payload=json.dumps(dict(ground=ground,kind=kind),ensure_ascii=False,allow_nan=False).replace('</','<\\/')
    return '''<script>
/**
 * 機能: 保存根拠の二行全セルと未測定の扱いを広狭画面で確認する。
 * @returns {object} 照合数・画面・表示品質。金融と通信は行わない。
 */
function verifyDisplay(){
 const payload=__PAYLOAD__,data=payload.ground,kind=payload.kind;
 let cells=0,numbers=0,asof=0,sequences=0;
 /**
  * 機能: セルの整数又は割合を表示桁の丸め以内で照合する。
  * @param {HTMLTableCellElement} cell - 表示セル。
  * @param {number} value - 保存有限値。
  * @param {number} precision - 表示小数桁。
  * @returns {undefined} 照合件数を加算する。不一致は例外。
  */
 function numeric(cell,value,precision=0){
  if(!Number.isFinite(value))throw Error('保存根拠未定義');
  const actual=Number(cell.textContent.trim().replaceAll(',','').replace('%',''));
  if(!Number.isFinite(actual)||Math.abs(actual-value)>.500001*10**(-precision))throw Error('数値差:'+actual+'/'+value);
  numbers++;cells++;
 }
 /**
  * 機能: セルの文字列を完全一致で確認する。
  * @param {HTMLTableCellElement} cell - 表示セル。
  * @param {string} value - 保存文字。
  * @returns {undefined} 照合件数を加算する。
  */
 function exact(cell,value){if(cell.textContent.trim()!==value)throw Error('文字差:'+cell.textContent+'/'+value);cells++;}
 const body=document.body.innerText;
 if(kind==='既知'){
  const rows=document.querySelector('#summary tbody').rows;
  if(rows.length!==2||data.rows.length!==2)throw Error('既知二行');
  for(let i=0;i<2;i++){
   const r=rows[i],v=data.rows[i];if(r.cells.length!==8)throw Error('既知八列');
   exact(r.cells[0],v.label);numeric(r.cells[1],v.profit);numeric(r.cells[2],v.loss);numeric(r.cells[3],v.net);
   exact(r.cells[4],v.positive+'/'+v.negative+'/'+v.no_trade);numeric(r.cells[5],v.profit_share*100,1);
   numeric(r.cells[6],v.top3_excluded);numeric(r.cells[7],v.worst);
   if(v.positive+v.negative+v.no_trade!==33||Math.abs(v.profit-v.loss-v.net)>1e-5)throw Error('根拠金額/場分母');
  }
  for(const text of ['金額利益80%を満たす手法は未発見','日経の8無取引場を勝ちには数えていません','未知セッションの成績は未測定'])if(!body.includes(text))throw Error('結論制約:'+text);
 }else{
  const rows=document.querySelector('#current tbody').rows;
  if(rows.length!==2||data.current.length!==2)throw Error('現在二行');
  for(let i=0;i<2;i++){
   const r=rows[i],v=data.current[i];if(r.cells.length!==6)throw Error('現在六列');
   exact(r.cells[0],v.symbol);
   for(let j=0;j<4;j++)numeric(r.cells[j+1],[v.count,v.reversals,v.older,v.missing][j]);
   exact(r.cells[5],v.as_of);asof++;
   const before=v.first['直前'],after=v.first['逆行行'];
   const expected=v.symbol+'：原連番'+before['原連番0起点'].toLocaleString('en-US')+'の'+before['価格時刻']+'から、次行'+after['原連番0起点'].toLocaleString('en-US')+'では'+after['価格時刻']+'へ戻りました。';
   if(!body.includes(expected))throw Error('原seqと具体価格時計');sequences+=2;
  }
  for(const text of ['取得は成功、損益は未測定','無取引、利益0、赤字という結果ではありません','E01新候補の未知成績も未測定','未測定を成功例へ置き換えない'])if(!body.includes(text))throw Error('未測定制約:'+text);
 }
 if(data['現在金融']!=='未測定'||data['新金融再生']!==0||data['API取得']!==0)throw Error('保存境界');
 if(/undefined|NaN|Infinity|__DATA__/.test(body))throw Error('未定義表示');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面横溢れ');
 const background=getComputedStyle(document.body).backgroundColor;
 if(background!=='rgb(11, 17, 32)')throw Error('ダーク背景');
 return {全合格:true,対象:kind,全セル照合:cells,表数値照合:numbers,AsOf文字一致:asof,具体例原seq照合:sequences,
  未測定と勝ち扱い禁止確認:true,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:background};
}
try{document.body.dataset.check=JSON.stringify(verifyDisplay());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''.replace('__PAYLOAD__',payload)


def main() -> None:
    """
    機能: 二HTMLを1450/520幅の隔離Chromeで検査し、四PNGと根目視前proofを私有保存する。
    引数: なし。公開2HTMLと表示根拠の小JSONだけを読む。
    返り値: None。公開修正・原板/台帳/金融・APIは行わない。
    """
    saved=GROUND.read_bytes();ground=json.loads(saved);assert ground['既知場数']==33 and ground['現在金融']=='未測定'
    path=ROOT/'work/wave_v52/review/verify_report.py'
    spec=importlib.util.spec_from_file_location('106短結論二表示の隔離Chrome',path)
    renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
    review=HERE/'final_pages_visual';review.mkdir(parents=True,exist_ok=True)
    renderer.OUT=PUBLIC;renderer.VISUAL=review
    sources={GROUND.relative_to(ROOT).as_posix():hashlib.sha256(saved).hexdigest()};screens=[]
    for title,kind in zip(TITLES,('既知','現在')):
        public=PUBLIC/(title+'.html');html=public.read_bytes();sha=hashlib.sha256(html).hexdigest()
        sources[public.relative_to(ROOT).as_posix()]=sha;document=browser_copy(html.decode('utf8'))
        renderer.PROBE=probe(ground,kind)
        for width,height in ((1450,1400),(520,1500)):
            record=renderer.render(document,title+str(width),width,height)
            record['公開HTML_SHA256']=sha;record['PNG_SHA256']=hashlib.sha256(Path(record['画像']).read_bytes()).hexdigest()
            screens.append(record)
            print(kind,str(width)+'幅合格',record['画像'],flush=True)
    result=dict(全合格=True,scope='公開された短い既知結論と入力失敗表示のDOM数値/文言/geometryのみ。',
        画面=screens,資料SHA256=sources,source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        レンダラーsource_SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
        既知表全セル=16,現在表全セル=12,現在表数値=8,現在具体例原seq=4,現在AsOf=2,
        公共ファイル変更=0,原板読取=0,台帳読取=0,金融再生=0,API取得=0,目視確認=False,
        私有HTMLの整形='公開の省略head/bodyを隔離コピーだけで明示した。同じ本文・style。元ファイルは不変更。')
    output=HERE/'current_短結論と入力失敗表示の広狭検査.json';assert not output.exists()
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    print(hashlib.sha256(output.read_bytes()).hexdigest(),flush=True)


if __name__=='__main__':main()
