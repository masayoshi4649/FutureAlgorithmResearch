"""公開二本文と固定時刻反転の参考各一読だけで、十二条件と反転比較を検査する。"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import traceback
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
PUBLIC=ROOT/'アルゴリズム調査/00116_全赤字手法の売買反転を同条件で検証'
HTML=PUBLIC/'売買反転した十二手法と全セッション損益.html'
ACCOUNT=PUBLIC/'売買反転の公開会計.json'
MIRROR=WORK/'mirror/固定時刻で買売を反転した十二条件の参考会計.json'
PROOF=HERE/'反転十二条件全場と固定時刻比較及び暗色広狭表示の独立検査.json'
EXPECTED_MIRROR_SHA='3285da706460752211c1583d1219c2098816a86e2236e88cc7a8f5434ae0765a'
LINKS=('手法の簡単な説明.md','反転しても残った損失の具体例.md','売買反転の公開会計.json','README.md')

EARLY=r'''<script>
window.__QA_ERRORS=[];
window.__QA_CONSOLE=[];
const independentConsoleError=console.error.bind(console);
console.error=function(...args){window.__QA_CONSOLE.push(args.map(String).join(' '));independentConsoleError(...args);};
window.addEventListener('error',function(e){window.__QA_ERRORS.push(String(e.message||e.error||'不明なJavaScript例外'));});
window.addEventListener('unhandledrejection',function(e){window.__QA_ERRORS.push(String(e.reason));});
</script>'''

PROBE=r'''<script>
/**
 * 機能: 全十二条件を実際の選択イベントで表示し、公開会計へ全数照合する。
 * @param {object} expected - 同目的で一読した公開会計。
 * @param {object} reference - 同時刻逆売買の一読参考から組んだ主候補比較。
 * @returns {object} 比較数、暗色、例外、画面幅と初期条件。
 */
function independentVerify(expected,reference){
 const fail=(ok,why)=>{if(!ok)throw Error(why);};
 const number=(cell)=>Number(cell.textContent.replaceAll(',','').trim());
 const stable=(v)=>v&&typeof v==='object'?(Array.isArray(v)?v.map(stable):Object.fromEntries(Object.keys(v).sort().map(k=>[k,stable(v[k])]))):v;
 fail(JSON.stringify(stable(D))===JSON.stringify(stable(expected)),'HTML内会計と公開JSONの相違');
 const selector=document.getElementById('case'),initial=selector.value;
 fail(initial==='QREVERSE_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1','反転版の事前主候補ID');
 fail(initial===expected.主候補,'初期の主候補');
 fail(selector.options.length===12&&expected.configs.length===12,'十二条件数');
 fail(expected.sessions.length===33&&expected.rows.length===792,'全場数');
 fail(new Set(Array.from(selector.options,o=>o.value)).size===12,'選択ID重複');
 let fields=['利益','損失','収支','勝ち枚数','負け枚数'];
 let cellcount=0,footercount=0,rowcount=0,cardcount=0;
 for(const conf of expected.configs){
  selector.value=conf.id;selector.dispatchEvent(new Event('change',{bubbles:true}));
  fail(selector.value===conf.id&&document.getElementById('choice').textContent.includes(conf.id),'選択表示');
  const rows=document.querySelector('#sessions tbody').rows,total=Array(10).fill(0);
  fail(rows.length===33,'三十三場行');
  expected.sessions.forEach((session,i)=>{
   fail(rows[i].cells.length===11,'商品別五項目');
   fail(rows[i].cells[0].textContent===session.replace('_Day',' デイ').replace('_Night',' ナイト'),'場名順序');
   ['TOPIX','NK225'].forEach((symbol,j)=>{
    const rr=expected.rows.filter(r=>r.case===conf.id&&r.session===session&&r.symbol===symbol);
    fail(rr.length===1,'会計の重複又は欠落');
    fields.forEach((field,k)=>{
     const value=rr[0][field],column=j*5+k;
     fail(Number.isFinite(value)&&Number.isInteger(value),'整数金額枚数');
     fail(number(rows[i].cells[column+1])===value,'全場セル:'+conf.id+'/'+session+'/'+symbol+'/'+field);
     total[column]+=value;cellcount++;
    });rowcount++;
   });
  });
  const foot=document.querySelector('#sessions tfoot').rows;
  fail(foot.length===1&&foot[0].cells[0].textContent==='全33場合計','合計行');
  total.forEach((value,i)=>{fail(number(foot[0].cells[i+1])===value,'合計セル');footercount++;});
  const cards=Array.from(document.querySelectorAll('#cards .card'));
  fail(cards.length===2,'商品カード数');
  ['TOPIX','NK225'].forEach((symbol,j)=>{
   const a=expected.aggregate[conf.id][symbol],m=a.全場;
   const fmt=(x)=>x===null?'—':Math.round(x).toLocaleString('ja-JP');
   const share=m.aggregate.利益割合===null?'—':(100*m.aggregate.利益割合).toFixed(1)+'%';
   for(const text of ['平均 '+fmt(m.mean_session_net_yen)+'円／場','利益割合 '+share,'赤字 '+m.losing_sessions+'/33場',
    '平均黒字 '+fmt(m.mean_positive_session_net_yen)+'円','最大赤字 '+fmt(m.worst_negative_session_abs_yen)+'円',
    '上位3黒字場を除く平均 '+fmt(a.上位3黒字場除外.mean_session_net_yen)+'円']){
    fail(cards[j].innerText.includes(text),'主カードの表示値');cardcount++;
   }
  });
 }
 const comparison=document.querySelector('#comparison tbody').rows;
 fail(comparison.length===12,'比較表条件数');
 let comparisons=0;
 expected.configs.forEach((conf,i)=>{
  fail(comparison[i].cells[0].textContent===selector.options[i].textContent,'比較ラベル');
  ['TOPIX','NK225'].forEach((symbol,j)=>{
   const m=expected.aggregate[conf.id][symbol].全場;
   fail(number(comparison[i].cells[1+j*3])===Math.round(m.mean_session_net_yen),'比較平均');
   fail(comparison[i].cells[2+j*3].textContent===(m.aggregate.利益割合===null?'—':(100*m.aggregate.利益割合).toFixed(1)+'%'),'比較割合');
   fail(comparison[i].cells[3+j*3].textContent===m.losing_sessions+'/33','比較赤字');comparisons+=3;
  });
 });
 const referenceTables=Array.from(document.querySelectorAll('main table')).filter(t=>!['sessions','comparison'].includes(t.id));
 fail(referenceTables.length===1,'主候補反転比較表は一つ');
 const referenceRows=referenceTables[0].tBodies[0].rows;
 fail(referenceRows.length===2,'反転比較の二商品');
 let referenceCells=0;
 ['TOPIX','NK225'].forEach((symbol,j)=>{
  const r=referenceRows[j],v=reference[symbol];
  fail(r.cells.length===5,'反転比較の五列');
  fail(r.cells[0].textContent===(symbol==='TOPIX'?'TOPIXミニ10枚':'日経マイクロ20枚'),'反転比較の商品順');
  ['original','mirror','replayed'].forEach((name,k)=>{fail(number(r.cells[k+1])===v[name],'反転比較の数値:'+symbol+'/'+name);referenceCells++;});
  fail(r.cells[4].textContent===v.red+'/33','新出口再判定の赤字場数');referenceCells++;
 });
 fail(document.body.innerText.includes('新方向で出口を再判定する列')&&document.body.innerText.includes('独立した影モデルの再生を追加した結果ではありません'),'固定時刻と新運転の留保');
 document.getElementById('reset').click();fail(selector.value===expected.主候補,'主候補ボタン');
 fail(window.__QA_ERRORS.length===0,'JavaScript例外:'+window.__QA_ERRORS.join('/'));
 fail(window.__QA_CONSOLE.length===0,'console.error:'+window.__QA_CONSOLE.join('/'));
 fail(!/NaN|Infinity|undefined|__DATA__|__CONCLUSION__/.test(document.body.innerText),'未定義表示');
 const width=document.documentElement.scrollWidth;
 fail(width<=innerWidth+2,'文書横溢れ');
 const background=getComputedStyle(document.body).backgroundColor;
 const rgb=background.match(/\d+/g).slice(0,3).map(Number);
 fail(Math.max(...rgb)<80&&getComputedStyle(document.documentElement).colorScheme.includes('dark'),'暗色表示');
 fail(document.body.innerText.includes('無取引は勝ちに含めません'),'無取引の扱い');
 return {全合格:true,初期主候補:initial,全場商品数:rowcount,全場数値セル:cellcount,合計セル:footercount,
  カード項目:cardcount,比較セル:comparisons,反転参考比較セル:referenceCells,JS例外数:window.__QA_ERRORS.length,consoleエラー数:window.__QA_CONSOLE.length,文書幅:width,画面幅:innerWidth,背景:background};
}
try{document.body.dataset.check=JSON.stringify(independentVerify(JSON.parse(document.getElementById('qa_expected').textContent),JSON.parse(document.getElementById('qa_reference').textContent)));}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''


def sha(raw: bytes) -> str:
    """
    機能: 一読済みbytes又は所有sourceの指紋を求める。
    引数: raw(bytes) は既読内容。
    返り値: str はSHA256。元公開ファイルを再読しない。
    """
    return hashlib.sha256(raw).hexdigest()


def write(path: Path,value: dict) -> None:
    """
    機能: 所有域へ成功又は失敗の新証跡を保存する。
    引数: path(Path)、value(dict) は新規出力。
    返り値: None。公開ファイルや旧成功は上書きしない。
    """
    assert path.parent==HERE and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def render(source: str,expected: dict,reference: dict,name: str,width: int,height: int) -> dict:
    """
    機能: 所有複製だけを固有の隔離headless Chromeで表示・検査する。
    引数: source(str)、expected/reference(dict)、name(str)、width/height(int) は表示条件。
    返り値: dict はDOM検算とPNG。通常ブラウザのプロファイルを利用しない。
    """
    visual=HERE/'visual';visual.mkdir(exist_ok=True)
    target=visual/(name+'.html');picture=visual/(name+'.png');profile=visual/('profile_'+name)
    assert not target.exists() and not picture.exists() and not profile.exists()
    assert source.count('</body>')==1 and source.count('<head>')==1
    data=json.dumps(expected,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<',chr(92)+'u003c')
    ref_data=json.dumps(reference,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<',chr(92)+'u003c')
    copied=source.replace('<head>','<head><base href="'+PUBLIC.as_uri()+'/">'+EARLY,1)
    copied=copied.replace('</body>','<script id="qa_expected" type="application/json">'+data+'</script><script id="qa_reference" type="application/json">'+ref_data+'</script>'+PROBE+'</body>',1)
    target.write_text(copied,encoding='utf-8')
    command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu','--no-first-run',
        '--disable-background-networking','--disable-component-update','--disable-sync','--run-all-compositor-stages-before-draw',
        '--disable-features=PaintHolding','--proxy-server=http://127.0.0.1:9',f'--window-size={width},{height}',
        '--virtual-time-budget=1500','--user-data-dir='+str(profile),'--screenshot='+str(picture),'--dump-dom',target.as_uri()]
    proc=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
    (visual/(name+'_stderr.txt')).write_bytes(proc.stderr)
    assert proc.returncode==0 and picture.exists(),'隔離Chrome終了又はPNG'
    soup=BeautifulSoup(proc.stdout.decode('utf-8',errors='replace'),'html.parser')
    if not soup.body or 'data-check' not in soup.body.attrs:
        (visual/(name+'_False_DOM.html')).write_bytes(proc.stdout)
        raise AssertionError('独立検査の完了属性なし')
    result=json.loads(soup.body['data-check']);assert result['全合格'],result
    return dict(画面=name,画像=picture.relative_to(ROOT).as_posix(),画像SHA256=sha(picture.read_bytes()),
        隔離profile=profile.relative_to(ROOT).as_posix(),**result)


def main() -> None:
    """
    機能: 根のリンク完成後だけ公開二本文と固定時刻参考を各一読し、全セルと二画面を照合する。
    引数: CLI --links-ready と --result-sha256(str) は完成通知と元金融の根指定指紋。
    返り値: None。金融結果・NPZ・実台帳・APIは開かない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--links-ready',action='store_true',required=True)
    parser.add_argument('--result-sha256',required=True);args=parser.parse_args()
    assert len(args.result_sha256)==64 and all(c in '0123456789abcdef' for c in args.result_sha256)
    assert not any(p.exists() for p in (HERE/'開始.json',HERE/'False.json',PROOF))
    assert all((PUBLIC/name).is_file() for name in LINKS),'根の説明MD/READMEの完成前'
    count=dict(公開HTML=0,公開JSON=0,同時刻反転参考JSON=0,金融結果=0,NPZ=0,実台帳=0,cache=0,API=0,金融再生=0)
    write(HERE/'開始.json',dict(目的='十二条件の全33場表と公開会計及び主候補の反転比較の独立表示QA',予定=dict(公開HTML=1,公開JSON=1,同時刻反転参考JSON=1),
        HTML=HTML.relative_to(ROOT).as_posix(),会計=ACCOUNT.relative_to(ROOT).as_posix(),
        source_SHA256=sha(Path(__file__).read_bytes()),予定幅=[1450,520],読取計数=count.copy()))
    try:
        owned=HERE/'owned';owned.mkdir()
        count['公開HTML']+=1;html_bytes=HTML.read_bytes();(owned/'公開HTML同bytes.html').write_bytes(html_bytes)
        count['公開JSON']+=1;account_bytes=ACCOUNT.read_bytes();(owned/'公開会計同bytes.json').write_bytes(account_bytes)
        count['同時刻反転参考JSON']+=1;mirror_bytes=MIRROR.read_bytes();(owned/'同時刻反転参考同bytes.json').write_bytes(mirror_bytes)
        text=html_bytes.decode('utf-8');expected=json.loads(account_bytes)
        assert expected['全合格'] and len(expected['configs'])==12 and len(expected['sessions'])==33
        assert expected['元結果SHA256']==args.result_sha256
        assert expected['主候補']=='QREVERSE_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1'
        assert sha(mirror_bytes)==EXPECTED_MIRROR_SHA
        mirror=json.loads(mirror_bytes);assert mirror['全合格'] and mirror['新金融']==0 and mirror['sessions']==expected['sessions']
        original_id='QEXEC_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1';reference={}
        for symbol in ('TOPIX','NK225'):
            saved=mirror['aggregate'][original_id]['symbols'][symbol]
            rows=[r for r in mirror['rows'] if r['case']==original_id and r['symbol']==symbol]
            assert len(rows)==33 and {r['session'] for r in rows}==set(expected['sessions'])
            for group in ('元会計','固定時刻反転'):
                for field in ('利益','損失','収支'):
                    assert sum(r[group][field] for r in rows)==saved[group][field]
            live=expected['aggregate'][expected['主候補']][symbol]['全場']
            assert sum(r['収支'] for r in expected['rows'] if r['case']==expected['主候補'] and r['symbol']==symbol)==live['aggregate']['収支']
            reference[symbol]=dict(original=saved['元会計']['収支'],mirror=saved['固定時刻反転']['収支'],replayed=live['aggregate']['収支'],red=live['losing_sessions'])
        soup=BeautifulSoup(text,'html.parser');links=[]
        for tag in soup.select('a[href],img[src]'):
            href=tag.get('href',tag.get('src'));parts=urlsplit(href)
            assert not parts.scheme and not parts.netloc,'この公開物のリンクはローカル資料のみ'
            target=(PUBLIC/unquote(parts.path)).resolve();assert target.is_relative_to(PUBLIC) and target.is_file(),str(target)
            links.append(dict(href=href,path=target.relative_to(ROOT).as_posix()))
        assert {item['href'] for item in links}==set(LINKS)
        result=[render(text,expected,reference,'PC1450',1450,3200),render(text,expected,reference,'モバイル520',520,4000)]
        assert count['公開HTML']==count['公開JSON']==count['同時刻反転参考JSON']==1
        write(PROOF,dict(全合格=True,HTML_SHA256=sha(html_bytes),公開会計_SHA256=sha(account_bytes),
            元結果SHA256の引用=expected['元結果SHA256'],source_SHA256=sha(Path(__file__).read_bytes()),
            同時刻反転参考_SHA256=sha(mirror_bytes),事前主候補の比較=reference,
            目視確認=False,結果=result,リンク=links,読取計数=count,
            複製='公開二本文と同時刻参考各一読から同bytesownedを保存。検査script/baseのみ隔離複製へ注入。公開物変更0。',
            制約='表示QAであり会計監査や売買の有用性を追加証明しない。画像の実目視はroot担当。'))
        print(json.dumps(dict(全合格=True,SHA256=sha(PROOF.read_bytes()),読取計数=count,目視確認=False,
            画像=[r['画像'] for r in result],全場数値セル各画面=result[0]['全場数値セル'],合計セル各画面=result[0]['合計セル']),ensure_ascii=False))
    except BaseException:
        write(HERE/'False.json',dict(全合格=False,読取計数=count,原因=traceback.format_exc(),公開変更=0,自動再実行=False))
        raise


if __name__=='__main__':
    main()
