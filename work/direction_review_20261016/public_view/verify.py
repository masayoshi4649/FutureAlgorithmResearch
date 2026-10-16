"""公開後のHTML/JSONだけを各一読し、十八採点・全切替の分子分母と暗色表示を検査する。"""

import argparse
import ast
import hashlib
import html
import json
import math
from pathlib import Path
import re
import subprocess
import traceback
from urllib.parse import unquote,urlsplit

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
PUBLIC=ROOT/'アルゴリズム調査/00117_方向予測の有効幅と探索方針の再点検'
HTML=PUBLIC/'方向予測はできているか.html'
ACCOUNT=PUBLIC/'方向予測の公開採点.json'
PLAN=HERE/'公開前の表示検査計画.json'
PROOF=HERE/'主評価四行と全三十三場全切替及び暗色広狭表示の独立検査.json'
COUNTS=('n','favorable_first','adverse_first','window_end','eof','price_cut','entry_unavailable')
EARLY=r'''<script>
window.__QA_ERRORS=[];window.__QA_CONSOLE=[];
for(const level of ['error','warn']){const original=console[level].bind(console);console[level]=function(...args){window.__QA_CONSOLE.push(level+': '+args.map(String).join(' '));original(...args);};}
window.addEventListener('error',function(e){window.__QA_ERRORS.push(String(e.message||e.error||'不明なJavaScript例外'));});
window.addEventListener('unhandledrejection',function(e){window.__QA_ERRORS.push(String(e.reason));});
</script>'''

PROBE=r'''<script>
/**
 * 機能: 全表示切替の六状態・分子分母・null率を独立に再計算する。
 * @param {Array<Array<string>>} primaryExpected - 同bytes公開JSONから作った主四行。
 * @returns {object} 全セル・例外・暗色・表スクロールの検査結果。
 */
function independentVerify(primaryExpected){
 const fail=(v,why)=>{if(!v)throw Error(why);};
 const fields=['n','favorable_first','adverse_first','window_end','eof','price_cut','entry_unavailable'];
 const rate=(v)=>v===null?'—':(100*v).toFixed(1)+'%';
 const eqRate=(a,b)=>a===null||b===null?a===b:Math.abs(a-b)<=1e-12;
 const key=(c)=>JSON.stringify([c.rule,c.width_fraction,c.origin,c.group,c.direction]);
 const controls={};for(const id of ['symbol','rule','width','origin','group','direction'])controls[id]=document.getElementById(id);
 const initial=Object.fromEntries(Object.entries(controls).map(([k,v])=>[k,v.value]));
 fail(JSON.stringify(initial)===JSON.stringify({symbol:'TOPIX',rule:'C',width:'0.001',origin:'公開mid',group:'非重複',direction:'全体'}),'初期の事前主評価');
 fail(data.sessions.length===33&&data.accounts.length===66,'公開の33場66商品');
 let countChecks=0,rateChecks=0,nullRates=0,sessionCells=0,footerCells=0,views=0,primaryCells=0,comparisonCells=0;
 /**
  * 機能: 六状態の総数と率を分子分母から再計算し、保存率との一致を確認する。
  * @param {object} c - 公開の一セル。
  * @returns {Array<string>} 表示する十一項目の独立期待。
  */
 function independentValues(c){
  for(const f of fields)fail(Number.isSafeInteger(c[f])&&c[f]>=0,'非負整数の件数:'+f);
  fail(c.n===fields.slice(1).reduce((n,f)=>n+c[f],0),'六状態の全分母');
  const resolved=c.favorable_first+c.adverse_first;
  fail(c.resolved===resolved,'解決分母');countChecks+=8;
  const expected={favorable_rate_all:c.n?c.favorable_first/c.n:null,
   favorable_rate_resolved:resolved?c.favorable_first/resolved:null,resolution_rate:c.n?resolved/c.n:null};
  for(const [name,value] of Object.entries(expected)){fail(eqRate(c[name],value),'保存率の分子分母:'+name);rateChecks++;}
  let result=fields.map(f=>String(c[f]));result.push(rate(expected.favorable_rate_resolved),rate(expected.resolution_rate));
  for(const name of ['常時買い','常時売り']){
   let value=null;
   if(c.origin==='公開mid'){
    fail(c.baseline!==null,'mid固定方向対照');const b=c.baseline[name];
    fail(b.n===c.n&&b.resolved===resolved,'固定方向と同じ候補/解決分母');
    fail(b.favorable_first+b.adverse_first===resolved,'固定方向分子');
    value=resolved?b.favorable_first/resolved:null;fail(eqRate(b.favorable_rate_resolved,value),'固定方向率');
   }else fail(c.baseline===null,'気配評価の固定方向を補完しない');
   result.push(rate(value));
  }
  for(const value of result.slice(7)){if(value==='—')nullRates++;}
  return result;
 }
 const accounts=new Map();for(const a of data.accounts){const k=a.symbol+'|'+a.session;fail(!accounts.has(k),'口座重複');accounts.set(k,new Map(a.cells.map(c=>[key(c),c])));}
 const primary=document.querySelector('#primary tbody').rows;fail(primary.length===4,'主四行数');
 primaryExpected.forEach((values,i)=>{fail(primary[i].cells.length===11,'主四行列');values.forEach((v,j)=>{fail(primary[i].cells[j].textContent===v,'主四行:'+i+'/'+j);primaryCells++;});});
 for(const symbol of ['TOPIX','NK225'])for(const rule of ['A','B','C'])for(const width of ['0.0005','0.001','0.002'])
 for(const origin of ['公開mid','次行新規・費用後気配'])for(const group of ['非重複','全候補'])for(const direction of ['全体','買い','売り']){
  const state={symbol,rule,width,origin,group,direction};for(const [id,v] of Object.entries(state))controls[id].value=v;
  controls.direction.dispatchEvent(new Event('change',{bubbles:true}));
  const criterion={rule,width_fraction:Number(width),origin,group,direction},which=key(criterion);
  const rows=document.querySelector('#session-rows').rows;fail(rows.length===33,'全33場行数');
  const sums=Object.fromEntries(fields.map(f=>[f,0]));
  data.sessions.forEach((session,i)=>{
   const c=accounts.get(symbol+'|'+session).get(which);fail(c!==undefined,'公開対象セルなし');
   fail(rows[i].cells.length===12&&rows[i].cells[0].textContent===session.replace('_Day',' デイ').replace('_Night',' ナイト'),'場名/列');
   independentValues(c).forEach((v,j)=>{fail(rows[i].cells[j+1].textContent===v,'全場値:'+symbol+'/'+session+'/'+which+'/'+j);sessionCells++;});
   for(const f of fields)sums[f]+=c[f];
  });
  const all=data.combined.symbols[symbol].periods['全33'].cells.filter(c=>key(c)===which);fail(all.length===1,'全場合計セル一意');
  const c=all[0];for(const f of fields){fail(c[f]===sums[f],'全33場から合計:'+f);countChecks++;}
  const total=document.querySelector('#totals').rows;fail(total.length===1&&total[0].cells[0].textContent==='合計','合計行');
  independentValues(c).forEach((v,j)=>{fail(total[0].cells[j+1].textContent===v,'合計表示');footerCells++;});
  const status=document.getElementById('selection-status').textContent;
  fail(status.includes(symbol+'／'+rule+'／')&&status.includes(origin),'条件表示');
  fail(status.includes('解決内順先率 '+rate(c.favorable_rate_resolved))&&status.includes('解決率 '+rate(c.resolution_rate)),'状態率表示');views++;
 }
 // ----------------------------------------
 // 折畳みの全期間十八条件も、表示される全数値と未定義分母を検査する。
 const comparison=document.querySelector('#comparison').rows;let at=0;
 for(const symbol of ['TOPIX','NK225'])for(const [period,p] of Object.entries(data.combined.symbols[symbol].periods))
 for(const c of p.cells.filter(c=>c.group==='非重複'&&c.direction==='全体')){
  const r=comparison[at++];fail(r!==undefined&&r.cells.length===13,'期間比較行');
  const v=independentValues(c);
  const expected=[symbol,period,c.rule,(100*c.width_fraction).toFixed(2)+'%',c.origin,v[0],v[1],v[2],String(c.n-c.resolved),v[7],v[8],v[9],v[10]];
  expected.forEach((s,i)=>{fail(r.cells[i].textContent===s,'期間比較値:'+at+'/'+i);comparisonCells++;});
 }
 fail(at===comparison.length,'余分な比較行');
 for(const [id,v] of Object.entries(initial))controls[id].value=v;
 controls.direction.dispatchEvent(new Event('change',{bubbles:true}));
 // ----------------------------------------
 // 文書は横へ溢れず、長い表だけを独立して左右スクロールできることを確認する。
 const details=Array.from(document.querySelectorAll('details')),opened=details.map(d=>d.open);details.forEach(d=>d.open=true);
 let scrollable=0;for(const wrap of document.querySelectorAll('.wrap')){
  const overflow=getComputedStyle(wrap).overflowX;fail(['auto','scroll'].includes(overflow),'表の横スクロール指定');
  if(wrap.scrollWidth>wrap.clientWidth+1){wrap.scrollLeft=wrap.scrollWidth;fail(wrap.scrollLeft>0,'表横移動');wrap.scrollLeft=0;scrollable++;}
 }
 details.forEach((d,i)=>d.open=opened[i]);if(innerWidth<600)fail(scrollable>0,'狭幅の表スクロール');
 fail(document.documentElement.scrollWidth<=innerWidth+2,'文書横溢れ');
 const rgb=getComputedStyle(document.documentElement).backgroundColor.match(/\d+/g).slice(0,3).map(Number);
 fail(Math.max(...rgb)<80&&getComputedStyle(document.documentElement).colorScheme.includes('dark'),'暗色');
 fail(!/NaN|Infinity|undefined|__DATA__|__MAIN__/.test(document.body.innerText),'未定義表示');
 fail(window.__QA_ERRORS.length===0&&window.__QA_CONSOLE.length===0,'JavaScript又はconsole例外');
 fail(document.body.innerText.includes('未決・切断を勝ちに含めません')&&document.body.innerText.includes('実約定・実決済勝率・収支ではありません'),'非金融の留保');
 return {全合格:true,初期条件:initial,主評価セル:primaryCells,表示切替:views,全場表示セル:sessionCells,合計セル:footerCells,
  期間比較セル:comparisonCells,分母件数照合:countChecks,保存率照合:rateChecks,null長線表示:nullRates,
  横スクロール表:scrollable,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,JS例外:window.__QA_ERRORS.length,console例外:window.__QA_CONSOLE.length};
}
try{document.body.dataset.check=JSON.stringify(independentVerify(JSON.parse(document.getElementById('qa_primary').textContent)));}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''


def sha(raw: bytes) -> str:
    """
    機能: 読取済みbytesのSHA256を得る。
    引数: raw(bytes) は小源又は一読済み公開本文。
    返り値: str は指紋。原測定結果・入力本体を開かない。
    """
    return hashlib.sha256(raw).hexdigest()


def sources() -> dict:
    """
    機能: 所有検査源と、変更不可の八実装源の現指紋を得る。
    引数: なし。
    返り値: dict は指紋。root moduleをimport又は実行しない。
    """
    tree=ast.parse((WORK/'plan.py').read_text(encoding='utf-8'))
    names=[ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOURCE_NAMES' for t in node.targets)]
    assert len(names)==1 and len(names[0])==8
    return dict(表示検査=sha(Path(__file__).read_bytes()),不変実装源={name:sha((WORK/name).read_bytes()) for name in names[0]})


def write(path: Path,value: dict) -> None:
    """
    機能: 所有領域へ新規の有限JSON証跡を保存する。
    引数: path(Path)、value(dict) は新規証跡。
    返り値: None。旧成功・False・公開物を上書きしない。
    """
    assert path.parent==HERE and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def primary_rows(data: dict) -> list[list[str]]:
    """
    機能: 公開JSONだけから、主四行の件数と率表示を独立に組み立てる。
    引数: data(dict) は一読済み公開採点。
    返り値: list[list[str]] は主評価の十一列。Python生成側の百分率丸めで比較する。
    """
    result=[]
    for symbol in ('TOPIX','NK225'):
        for origin in ('公開mid','次行新規・費用後気配'):
            cells=[c for c in data['combined']['symbols'][symbol]['periods']['全33']['cells']
                if c['rule']=='C' and c['group']=='非重複' and c['direction']=='全体' and c['width_fraction']==.001 and c['origin']==origin]
            assert len(cells)==1;c=cells[0]
            assert c['n']==sum(c[f] for f in COUNTS[1:]) and c['resolved']==c['favorable_first']+c['adverse_first']
            values=[symbol,origin,*[str(c[f]) for f in COUNTS]]
            for name,num,den in (('favorable_rate_resolved',c['favorable_first'],c['resolved']),('resolution_rate',c['resolved'],c['n'])):
                expected=num/den if den else None
                assert c[name] is None if expected is None else c[name] is not None and math.isclose(c[name],expected,abs_tol=1e-12)
                values.append('—' if expected is None else f'{100*expected:.1f}%')
            result.append(values)
    return result


def render(source: str,primary: list[list[str]],name: str,width: int,height: int) -> dict:
    """
    機能: 固有の隔離Chromeで私有複製を表示し、全切替とPNGを保存する。
    引数: source(str)、primary(list)、name(str)、width/height(int) は表示条件。
    返り値: dict はDOM検査値とPNG位置。通常ブラウザprofileを利用しない。
    """
    visual=HERE/'visual';visual.mkdir(exist_ok=True)
    target=visual/(name+'.html');picture=visual/(name+'.png');profile=visual/('profile_'+name)
    assert not any(p.exists() for p in (target,picture,profile))
    assert source.count('<head>')==1 and source.count('</body>')==1
    values=json.dumps(primary,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<',chr(92)+'u003c')
    copied=source.replace('<head>','<head><base href="'+PUBLIC.as_uri()+'/">'+EARLY,1)
    copied=copied.replace('</body>','<script id="qa_primary" type="application/json">'+values+'</script>'+PROBE+'</body>',1)
    target.write_text(copied,encoding='utf-8')
    command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu','--no-first-run',
        '--disable-background-networking','--disable-component-update','--disable-sync','--run-all-compositor-stages-before-draw',
        '--disable-features=PaintHolding','--proxy-server=http://127.0.0.1:9',f'--window-size={width},{height}',
        '--virtual-time-budget=1500','--user-data-dir='+str(profile),'--screenshot='+str(picture),'--dump-dom',target.as_uri()]
    proc=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
    (visual/(name+'_stderr.txt')).write_bytes(proc.stderr)
    assert proc.returncode==0 and picture.exists(),'隔離Chromeの終了又はPNG'
    dom=proc.stdout.decode('utf-8',errors='replace');found=re.search(r'<body\b[^>]*\bdata-check="([^"]*)"',dom)
    if found is None:
        (visual/(name+'_False_DOM.html')).write_bytes(proc.stdout)
        raise AssertionError('独立DOM検査の完了属性なし')
    proof=json.loads(html.unescape(found.group(1)));assert proof['全合格'],proof
    return dict(画面=name,画像=picture.relative_to(ROOT).as_posix(),画像SHA256=sha(picture.read_bytes()),
        隔離profile=profile.relative_to(ROOT).as_posix(),**proof)


def prepare() -> None:
    """
    機能: 公開の存在確認も行わず、未来の表示QA目的・回数・条件を固定する。
    引数: なし。
    返り値: None。公開本文・原入力・測定結果は未読のまま。
    """
    write(PLAN,dict(全合格=True,段階='公開完成通知待ち',source_SHA256=sources(),
        目的='主四行と全33場×216切替の分子分母・null率・合計・全期間表、暗色・横スクロール・例外・リンク',
        公開HTML=HTML.relative_to(ROOT).as_posix(),公開JSON=ACCOUNT.relative_to(ROOT).as_posix(),
        予定=dict(公開HTML=1,公開JSON=1,原NPZ=0,保存event=0,実測生NPZ=0,測定結果本文=0,金融=0,API=0),
        予定画像幅=[1450,520],主評価=dict(rule='C',width_fraction=.001,group='非重複',direction='全体'),
        複製='公開2本文の同bytesownedのみを再利用。検査script/baseを私有HTMLへ注入。',
        目視確認=False,停止='不一致はFalse保存し、公開や実装源を直さずrootへ報告する。'))
    print(json.dumps(dict(準備完了=True,計画SHA256=sha(PLAN.read_bytes()),公開本文読=0),ensure_ascii=False))


def run(expected: str) -> None:
    """
    機能: 根の公開完了通知後だけ公開二本文を各一読し、独立表示検査を実行する。
    引数: expected(str) は根通知の元測定結果SHA256。
    返り値: None。金融・原入力・実測生NPZ・元測定結果本文を開かない。
    """
    assert len(expected)==64 and all(c in '0123456789abcdef' for c in expected)
    assert not any(p.exists() for p in (HERE/'開始.json',HERE/'False.json',PROOF))
    plan=json.loads(PLAN.read_text(encoding='utf-8'));source=sources();assert source==plan['source_SHA256']
    count=dict(公開HTML=0,公開JSON=0,原NPZ=0,保存event=0,実測生NPZ=0,測定結果本文=0,金融=0,API=0)
    write(HERE/'開始.json',dict(目的=plan['目的'],計画SHA256=sha(PLAN.read_bytes()),期待元結果SHA256=expected,source_SHA256=source,読取計数=count.copy()))
    try:
        owned=HERE/'owned';owned.mkdir()
        count['公開HTML']+=1;raw_html=HTML.read_bytes();(owned/'公開HTML同bytes.html').write_bytes(raw_html)
        count['公開JSON']+=1;raw_json=ACCOUNT.read_bytes();(owned/'公開JSON同bytes.json').write_bytes(raw_json)
        text=raw_html.decode('utf-8');data=json.loads(raw_json)
        assert data['全合格'] and data['金融'] is False and data['結果SHA256']==expected
        assert len(data['sessions'])==33 and len(set(data['sessions']))==33 and len(data['accounts'])==66
        soup=BeautifulSoup(text,'html.parser');embedded=soup.find('script',id='saved-data');assert embedded is not None
        assert json.loads(embedded.get_text())==data,'HTML内保存JSONと公開JSONの同値'
        links=[]
        for tag in soup.select('a[href],img[src]'):
            href=tag.get('href',tag.get('src'));parts=urlsplit(href)
            assert not parts.scheme and not parts.netloc,'ローカル資料外のリンクは別確認'
            target=(PUBLIC/unquote(parts.path)).resolve() if parts.path else HTML
            assert target.is_relative_to(ROOT) and target.is_file(),str(target)
            if parts.fragment and target==HTML:assert soup.find(id=unquote(parts.fragment)) is not None
            links.append(dict(href=href,path=target.relative_to(ROOT).as_posix()))
        primary=primary_rows(data)
        results=[render(text,primary,'PC1450',1450,2400),render(text,primary,'モバイル520',520,2400)]
        assert source==sources() and count['公開HTML']==count['公開JSON']==1
        write(PROOF,dict(全合格=True,目視確認=False,元結果SHA256=expected,HTML_SHA256=sha(raw_html),公開JSON_SHA256=sha(raw_json),
            source_SHA256=source,source開始終端一致=True,主評価=primary,結果=results,リンク=links,読取計数=count,
            制約='非金融採点の表示QA。原測定の再演算・金融・有効性の追加標本ではない。rootの実画像目視は別工程。',公開変更=0))
        print(json.dumps(dict(全合格=True,SHA256=sha(PROOF.read_bytes()),目視確認=False,読取計数=count,画像=[v['画像'] for v in results],表示切替各画面=results[0]['表示切替']),ensure_ascii=False))
    except BaseException:
        write(HERE/'False.json',dict(全合格=False,読取計数=count,原因=traceback.format_exc(),公開変更=0,自動再実行=False))
        raise


def main() -> None:
    """
    機能: 公開前準備と、根の公開SHA解除後の実画像検査を分離する。
    引数: CLI --prepare又は--published、--result-sha(str)。
    返り値: None。準備段階では公開の存在確認・本文探索も行わない。
    """
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare',action='store_true');mode.add_argument('--published',action='store_true');parser.add_argument('--result-sha')
    args=parser.parse_args()
    if args.prepare:prepare()
    else:run(args.result_sha)


if __name__=='__main__':
    main()
