"""前版の全数QAを保全し、率差単位とS03反証説明の公開差分だけを確認する。"""

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import traceback
from urllib.parse import unquote,urlsplit

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
PREVIOUS=HERE.parent
WORK=PREVIOUS.parent
ROOT=WORK.parents[1]
PUBLIC=ROOT/'アルゴリズム調査/00118_TOPIX十ポイントの予兆と多尺度方向予測'
HTML_NAME='十ポイント方向予兆の候補と全セッション結果.html'
JSON_NAME='十ポイント予兆の公開採点.json'
MD_NAME='事後に残った予兆候補S03.md'
OLD_HTML='76d3909975ab968547d6849f2de47af00b58ee086cc557aec75a737e63438e0b'
OLD_JSON='d2236e18866d94ce1872f3b0aca079297f3af8a98c770565727b91016471e3c2'
OLD_PROOF='ef9f3ac8113ea2a4e19a95024a0ea79d083f63cfb4712dc3b7d58dc8b4e5e0d6'
SOURCES=('plan.py','input.py','artificial_input.py','features.py','artificial_features.py',
    'targets.py','artificial_targets.py','learner.py','artificial_learner.py','run.py')
EARLY='''<script>
window.__QA_ERRORS=[];window.__QA_CONSOLE=[];
for(const level of ['error','warn']){const original=console[level].bind(console);console[level]=function(...args){window.__QA_CONSOLE.push(level+': '+args.map(String).join(' '));original(...args);};}
window.addEventListener('error',e=>window.__QA_ERRORS.push(String(e.message||e.error)));
window.addEventListener('unhandledrejection',e=>window.__QA_ERRORS.push(String(e.reason)));
</script>'''
PROBE=r'''<script>
/**
 * 機能: 修正単位・追加説明・初期viewと全37行を公開JSONへ照合する。
 * @param {object} expected - 前版同値の公開会計と差分期待。
 * @returns {object} 広狭表示と変更箇所の確認数。
 */
function verifyDelta(expected){
 const fail=(x,s)=>{if(!x)throw Error(s);};const Q=JSON.parse(document.getElementById('report-data').textContent);
 fail(Q.view_initial_id==='S03'&&document.body.dataset.method==='S03','初期S03不変');
 fail(JSON.stringify(Q.selection['正式候補'])===JSON.stringify(expected.official),'正式3不変');
 const unitNodes=[...document.querySelectorAll('#primary-table tbody tr td:nth-child(7),#posthoc-comparison-table tbody tr td:last-child')];
 fail(unitNodes.length===5,'率差五セル');unitNodes.forEach((x,i)=>fail(x.textContent===expected.units[i],'％ポイント単位 '+i));
 fail(!/[+−-]\d+(?:\.\d+)?pt/.test(document.body.innerText),'率差のpt残り');
 fail(!document.querySelector('#posthoc-s03').textContent.includes('除く確認は未実施'),'完了済み除外確認を未実施と表示しない');
 fail(document.querySelector('#posthoc-s03 a[href="'+expected.added_link+'"]').textContent.length>0,'反証MDリンク');
 const selector=document.getElementById('method-select');let cells=0;
 for(const identity of ['S03',...expected.official]){
  selector.value=identity;selector.dispatchEvent(new Event('change',{bubbles:true}));
  const rows=document.querySelector('#session-body').rows,saved=Q.rows.filter(x=>x.id===identity);fail(rows.length===37,'37行');
  saved.forEach((r,i)=>{const c=r.risks[1],rate=c.n?(100*c['順先']/c.n).toFixed(1)+'%':'—';
   const want=[r.session,Q.splits['学習'].includes(r.session)?'学習内':Q.splits['選択'].includes(r.session)?'選択':Q.splits['時系列別枠'].includes(r.session)?'既知の後6':'追加4',c['順先']+'/'+c.n+'（'+rate+'）',String(c['逆先']),String(c['窓末未決']),String(c['EOF未決']),String(c['基準不可']),r['買い数']+'/'+r['売り数']];
   want.forEach((v,j)=>{fail(rows[i].cells[j].textContent===v,'初期/正式3の場表示');cells++;});
  });
 }
 document.getElementById('reset').click();fail(selector.value==='S03','reset不変');
 const details=[...document.querySelectorAll('details')],before=details.map(x=>x.open);details.forEach(x=>x.open=true);
 let scrolling=0;for(const wrap of document.querySelectorAll('.scroll')){
  fail(['auto','scroll'].includes(getComputedStyle(wrap).overflowX),'表スクロールCSS');
  if(wrap.scrollWidth>wrap.clientWidth+1){wrap.scrollLeft=wrap.scrollWidth;fail(wrap.scrollLeft>0,'表横移動');wrap.scrollLeft=0;scrolling++;}
 }
 fail(innerWidth>=600||scrolling>0,'狭幅表');fail(document.documentElement.scrollWidth<=innerWidth+2,'横溢れ');
 details.forEach((x,i)=>x.open=before[i]);
 const background=getComputedStyle(document.body).backgroundColor.match(/\d+/g).slice(0,3).map(Number);
 fail(Math.max(...background)<80&&getComputedStyle(document.documentElement).colorScheme.includes('dark'),'暗色');
 fail(window.__QA_ERRORS.length===0&&window.__QA_CONSOLE.length===0,'JS/console例外');
 fail(!/NaN|undefined|Infinity/.test(document.body.innerText),'非数表示');
 return {全合格:true,初期及び正式3の場セル:cells,率差単位セル:unitNodes.length,横スクロール表:scrolling,
  画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,JS例外:window.__QA_ERRORS.length,console例外:window.__QA_CONSOLE.length};
}
try{document.body.dataset.delta=JSON.stringify(verifyDelta(JSON.parse(document.getElementById('qa-delta').textContent)));}
catch(error){document.body.dataset.delta=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''


def sha(body: bytes) -> str:
    """
    機能: 読取済みbytesを指紋化する。
    引数: body(bytes) は公開又はsource。
    返り値: str はSHA256。
    """
    return hashlib.sha256(body).hexdigest()


def sources() -> dict:
    """
    機能: この差分検査器と不変source10の指紋を得る。
    引数: なし。
    返り値: dict。市場結果・入力は開かない。
    """
    return dict(検査源=sha(Path(__file__).read_bytes()),不変実装10={name:sha((WORK/name).read_bytes()) for name in SOURCES})


def write(name: str,value: dict) -> None:
    """
    機能: 新規の差分証跡を保存する。
    引数: name(str)、value(dict) は所有ファイル名と内容。
    返り値: None。前版と公開物を変更しない。
    """
    path=HERE/name;assert not path.exists();path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def tables(soup) -> dict:
    """
    機能: 静的表の全セルを位置を含めて取得する。
    引数: soup(BeautifulSoup) は同bytes公開HTML。
    返り値: dict[str,list] はtableのid又は固定順と全行セル。
    """
    result={}
    for index,table in enumerate(soup.find_all('table')):
        key=table.get('id','table_'+str(index));assert key not in result
        result[key]=[[cell.get_text() for cell in row.find_all(['td','th'],recursive=False)] for row in table.find_all('tr')]
    return result


def render(text: str,expected: dict,name: str,width: int) -> dict:
    """
    機能: 新規隔離Chromeで修正画面と差分DOMを確認する。
    引数: text(str)、expected(dict)、name(str)、width(int)。
    返り値: dict は結果とPNGパス。元ブラウザprofileを使用しない。
    """
    visual=HERE/'visual';visual.mkdir(exist_ok=True);target=visual/(name+'.html');image=visual/(name+'.png');profile=visual/('profile_'+name)
    assert not any(p.exists() for p in (target,image,profile))
    payload=json.dumps(expected,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    private=text.replace('<head>','<head><base href="'+PUBLIC.as_uri()+'/">'+EARLY,1)
    private=private.replace('</body>','<script id="qa-delta" type="application/json">'+payload+'</script>'+PROBE+'</body>',1);target.write_text(private,encoding='utf-8')
    command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu','--no-first-run',
        '--disable-background-networking','--disable-component-update','--disable-sync','--run-all-compositor-stages-before-draw',
        '--disable-features=PaintHolding','--proxy-server=http://127.0.0.1:9',f'--window-size={width},2400','--virtual-time-budget=1800',
        '--user-data-dir='+str(profile),'--screenshot='+str(image),'--dump-dom',target.as_uri()]
    proc=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
    (visual/(name+'_stderr.txt')).write_bytes(proc.stderr);assert proc.returncode==0 and image.exists()
    found=re.search(r'<body\b[^>]*\bdata-delta="([^"]*)"',proc.stdout.decode('utf-8',errors='replace'))
    if found is None:(visual/(name+'_False_DOM.html')).write_bytes(proc.stdout);raise AssertionError('差分DOM完了なし')
    result=json.loads(html.unescape(found.group(1)))
    if not result['全合格']:(visual/(name+'_False_DOM.html')).write_bytes(proc.stdout)
    assert result['全合格'],result
    return dict(画像=image.relative_to(ROOT).as_posix(),画像_SHA256=sha(image.read_bytes()),隔離profile=profile.relative_to(ROOT).as_posix(),**result)


def prepare() -> None:
    """
    機能: 新公開を確認せず、差分QAの目的と前版同値範囲を先に固定する。
    引数: なし。
    返り値: None。公開本文の読取0。
    """
    write('差分表示検査の事前計画.json',dict(全合格=True,source_SHA256=sources(),前QA_SHA256=OLD_PROOF,
        前HTML_SHA256=OLD_HTML,前JSON_SHA256=OLD_JSON,
        予定読取=dict(新公開HTML=1,新公開JSON=1,新追補MD=1,前版私有HTML=1,前版私有JSON=1,前QA証跡=1,市場結果=0,prepared=0,金融=0,API=0),
        検査='公開JSON全項目同値/selection不変、静的表は率差単位のみ置換して全セル同値、新反証リンクと文言、1450/520隔離Chrome画像。',
        再利用='前QAの44切替×37場全数検査を再利用。差分で同数値を新有効性証拠としない。',目視確認=False))
    print('revision4差分検査の準備完了。公開本文0。')


def execute(args) -> None:
    """
    機能: writer完成SHA解除後に新三公開物を各一読し差分を確認する。
    引数: args(Namespace) は完成SHAと追加MDリンク名。
    返り値: None。不一致はFalse保存し公開を修正しない。
    """
    assert args.root_revision_complete and all(len(v)==64 for v in (args.html_sha,args.json_sha,args.md_sha))
    plan=json.loads((HERE/'差分表示検査の事前計画.json').read_bytes());initial=sources();assert initial==plan['source_SHA256']
    assert not (HERE/'開始.json').exists();write('開始.json',dict(source_SHA256=initial,予定=plan['予定読取'],自動再実行=False))
    count={k:0 for k in plan['予定読取']}
    try:
        count['前QA証跡']+=1;old_proof=(PREVIOUS/'正式三候補と事後追補及び四十四条件全場表の独立表示検査.json').read_bytes()
        assert sha(old_proof)==OLD_PROOF and json.loads(old_proof)['全合格']
        count['前版私有HTML']+=1;old_html=(PREVIOUS/'owned'/('同bytes_'+HTML_NAME)).read_bytes();assert sha(old_html)==OLD_HTML
        count['前版私有JSON']+=1;old_json=(PREVIOUS/'owned'/('同bytes_'+JSON_NAME)).read_bytes();assert sha(old_json)==OLD_JSON
        owned=HERE/'owned';owned.mkdir();new={}
        for kind,name,expected in (('新公開HTML',HTML_NAME,args.html_sha),('新公開JSON',JSON_NAME,args.json_sha),('新追補MD',MD_NAME,args.md_sha)):
            count[kind]+=1;body=(PUBLIC/name).read_bytes();assert sha(body)==expected,(kind,sha(body));new[kind]=body
            (owned/name).write_bytes(body)
        data=json.loads(new['新公開JSON']);assert data==json.loads(old_json)
        old=BeautifulSoup(old_html.decode('utf-8'),'html.parser');current=BeautifulSoup(new['新公開HTML'].decode('utf-8'),'html.parser')
        assert json.loads(current.find('script',id='report-data').get_text())==data
        before=tables(old);after=tables(current);assert set(before)==set(after)
        changed=0;headers=0;cell_count=0
        for name,rows in before.items():
            assert len(rows)==len(after[name])
            for row_index,(a,b) in enumerate(zip(rows,after[name])):
                assert len(a)==len(b)
                for col,(x,y) in enumerate(zip(a,b)):
                    wanted='良い方との差（率）' if x=='良い方との差' else re.sub(r'([+−-]\d+(?:\.\d+)?)pt$',r'\1％ポイント',x)
                    assert y==wanted,(name,row_index,col,x,y);cell_count+=1
                    if x=='良い方との差':headers+=x!=y
                    else:changed+=x!=y
        assert changed==5 and headers==2
        unit_nodes=current.select('#primary-table tbody tr td:nth-child(7),#posthoc-comparison-table tbody tr td:last-child')
        expected=dict(official=data['selection']['正式候補'],units=[x.get_text() for x in unit_nodes],added_link=args.added_link)
        assert current.select_one('#posthoc-s03 a[href="'+args.added_link+'"]') is not None
        assert '除く確認は未実施' not in current.select_one('#posthoc-s03').get_text()
        links=[]
        for soup_text,is_md in ((new['新公開HTML'].decode('utf-8'),False),(new['新追補MD'].decode('utf-8'),True)):
            hrefs=re.findall(r'\[[^\]]*\]\(([^)]+)\)',soup_text) if is_md else [a['href'] for a in current.select('a[href]')]
            for href in hrefs:
                parsed=urlsplit(href);assert not parsed.scheme and not parsed.netloc
                target=(PUBLIC/unquote(parsed.path)).resolve() if parsed.path else PUBLIC/HTML_NAME
                assert target.is_relative_to(ROOT) and target.is_file(),str(target)
                if parsed.fragment and target==PUBLIC/HTML_NAME:assert current.find(id=unquote(parsed.fragment)) is not None
                links.append(dict(source='MD' if is_md else 'HTML',href=href,path=target.relative_to(ROOT).as_posix()))
        assert any(v['href']==args.added_link for v in links)
        results=[render(new['新公開HTML'].decode('utf-8'),expected,'PC1450',1450),render(new['新公開HTML'].decode('utf-8'),expected,'モバイル520',520)]
        assert sources()==initial and count==plan['予定読取']
        write('率差単位とS03反証追補の独立差分表示検査.json',dict(全合格=True,目視確認=False,前QA_SHA256=OLD_PROOF,
            新公開_SHA256={k:sha(v) for k,v in new.items()},公開JSON全項目同値=True,正式選択不変=True,
            静的表比較セル=cell_count,単位のみ変更セル=changed,対応見出し変更セル=headers,画面=results,リンク=links,読取計数=count,source_SHA256=initial,source始終一致=True))
        print(json.dumps(dict(全合格=True,静的セル=cell_count,単位変更=changed,証跡_SHA256=sha((HERE/'率差単位とS03反証追補の独立差分表示検査.json').read_bytes())),ensure_ascii=False))
    except BaseException as exc:
        write('False.json',dict(全合格=False,例外=repr(exc),trace=traceback.format_exc(),読取計数=count,source_SHA256=initial));raise


def main() -> None:
    """
    機能: 未公開準備と完成SHA指定の差分QAを分ける。
    引数: CLI --prepare/--run、root解除、各公開SHA、--added-link。
    返り値: None。
    """
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--prepare',action='store_true');mode.add_argument('--run',action='store_true')
    parser.add_argument('--root-revision-complete',action='store_true')
    for name in ('html-sha','json-sha','md-sha','added-link'):parser.add_argument('--'+name,default='')
    args=parser.parse_args();prepare() if args.prepare else execute(args)


if __name__=='__main__':main()
