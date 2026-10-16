"""保全HTMLの隔離複製だけを既存headless Chrome方式で広狭表示検査する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import traceback

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
VISUAL = HERE / 'visual_v2'
PROOF = HERE / '公開十手法の全選択と広狭DOM及びJS例外確認_v2.json'
CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
ERROR_CAPTURE = r'''<script>
/**
 * 機能: 後続表示scriptの例外とconsole.errorを記録する。
 * 引数: なし。
 * 返り値: void。金融や外部通信を行わない。
 */
window.__reportAuditErrors=[];
window.addEventListener('error',event=>window.__reportAuditErrors.push({種類:'error',内容:event.message}));
window.addEventListener('unhandledrejection',event=>window.__reportAuditErrors.push({種類:'promise',内容:String(event.reason)}));
const originalConsoleError=console.error.bind(console);
console.error=(...args)=>{window.__reportAuditErrors.push({種類:'console.error',内容:args.map(String).join(' ')});originalConsoleError(...args);};
</script>'''


def probe(expected: dict) -> str:
    """
    機能: 独立算術から作った全セル期待値をブラウザで照合するscriptを作る。
    引数: expected(dict)は保全公開会計由来の期待値。
    返り値: strは副作用を表示選択と検査記録だけに限定したscript。
    """
    values = json.dumps(expected, ensure_ascii=False).replace('</', '<\\/')
    return '<script>const independentExpected=' + values + r''';
/**
 * 機能: 全十手法の選択と33行及び全セルをブラウザで検査する。
 * 引数: なし。
 * 返り値: objectは検査件数と表示品質。
 */
function verifyIndependentDOM(){
 let checks=0,cells=0,views=0;
 const ensure=(value,detail)=>{checks++;if(!value)throw Error(detail);};
 const text=cell=>cell.textContent.trim();
 const same=(a,b,detail)=>ensure(JSON.stringify(a)===JSON.stringify(b),detail);
 const selector=document.querySelector('#method');
 ensure(Boolean(selector),'selector不在');
 same(Array.from(selector.options,o=>o.value),Object.keys(independentExpected.sections),'全十選択肢');
 const overview=document.querySelector('details');
 const rows=Array.from(overview.querySelectorAll('tbody tr'),tr=>Array.from(tr.cells,text));
 same(rows,independentExpected.overview,'全20商品比較行');
 cells+=rows.reduce((n,row)=>n+row.length,0);
 for(const [id,value] of Object.entries(independentExpected.sections)){
  selector.value=id;selector.dispatchEvent(new Event('change',{bubbles:true}));
  const visible=Array.from(document.querySelectorAll('.method')).filter(s=>getComputedStyle(s).display!=='none');
  same(visible.map(s=>s.id),[id],'選択一章だけ表示:'+id);
  const section=visible[0];
  same(text(section.querySelector('h2')),value.name,'章名:'+id);
  const body=Array.from(section.querySelectorAll('tbody tr'),tr=>Array.from(tr.cells,text));
  ensure(body.length===33,'33行:'+id);
  same(body,value.body,'全場660会計の表示:'+id);
  const foot=Array.from(section.querySelectorAll('tfoot th'),text);
  same(foot,value.footer,'合計表示:'+id);
  ensure(section.textContent.includes(value.trim),'trim表示:'+id);
  cells+=body.reduce((n,row)=>n+row.length,0)+foot.length;views++;
 }
 selector.value=independentExpected.initial;selector.dispatchEvent(new Event('change',{bubbles:true}));
 for(const phrase of independentExpected.required)ensure(document.body.textContent.includes(phrase),'留保:'+phrase);
 ensure(document.documentElement.scrollWidth<=innerWidth+2,'文書の横溢れ');
 ensure(!/NaN|Infinity|undefined|__DATA__/.test(document.body.innerText),'表示に未定義script文字');
 ensure(window.__reportAuditErrors.length===0,'JS又はconsole不具合:'+JSON.stringify(window.__reportAuditErrors));
 const bg=getComputedStyle(document.documentElement).backgroundColor;
 const rgb=bg.match(/\d+/g).map(Number);
 ensure(rgb.slice(0,3).every(v=>v<60),'暗色背景:'+bg);
 return {全合格:true,検査数:checks,選択数:views,全セル:cells,初期表示:independentExpected.initial,
  画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:bg,JS例外又はconsole不具合:window.__reportAuditErrors};
}
try{document.body.dataset.independentCheck=JSON.stringify(verifyIndependentDOM());}
catch(error){document.body.dataset.independentCheck=JSON.stringify({全合格:false,理由:String(error),stack:error.stack,errors:window.__reportAuditErrors});}
</script>'''


def render(source: str, script: str, name: str, width: int, height: int, extra: str = '') -> dict:
    """
    機能: 既存ローカルrepo方式の隔離Chromeで複製HTMLを表示し、DOMと画像を保存する。
    引数: source/script/name/extra(str)は複製と検査、width/height(int)は画面寸法。
    返り値: dictは表示検査結果。元公開資料を追加で読み取らない。
    """
    VISUAL.mkdir(exist_ok=True)
    target, image = VISUAL / (name + '.html'), VISUAL / (name + '.png')
    assert not target.exists() and not image.exists()
    copied = source.replace('<head>', '<head>' + ERROR_CAPTURE, 1)
    target.write_text(copied.replace('</body>', script + extra + '</body>', 1), encoding='utf-8')
    command = [str(CHROME), '--headless=new', '--disable-gpu', '--no-first-run', '--disable-background-networking',
        '--disable-component-update', '--disable-sync', '--run-all-compositor-stages-before-draw', '--disable-features=PaintHolding',
        '--proxy-server=http://127.0.0.1:9', f'--window-size={width},{height}', '--virtual-time-budget=1000',
        '--user-data-dir=' + str(VISUAL / ('profile_' + name)), '--screenshot=' + str(image), '--dump-dom', target.as_uri()]
    process = subprocess.run(command, capture_output=True, timeout=55, creationflags=subprocess.CREATE_NO_WINDOW)
    (VISUAL / (name + '_DOM.html')).write_bytes(process.stdout)
    (VISUAL / (name + '_Chrome標準エラー.txt')).write_bytes(process.stderr)
    assert process.returncode == 0 and image.exists(), (name, process.returncode)
    soup = BeautifulSoup(process.stdout.decode('utf-8', errors='replace'), 'html.parser')
    assert soup.body is not None and 'data-independent-check' in soup.body.attrs, 'DOM検査結果なし'
    result = json.loads(soup.body['data-independent-check'])
    assert result['全合格'], result
    return dict(画面=name, 画像=image.relative_to(ROOT).as_posix(), 画像SHA256=hashlib.sha256(image.read_bytes()).hexdigest(), **result)


def main() -> None:
    """
    機能: 広幅と狭幅で全十選択を検査し、別に比較一覧の画像を保存する。
    引数: なし。
    返り値: None。人による目視とは別のDOM合格を記録する。
    """
    assert not PROOF.exists()
    try:
        expected = json.loads((HERE / '独立DOM期待値.json').read_text(encoding='utf-8'))
        source = (HERE / '公開同bytes保全/現在の活動と再進行から参加する手法と全セッション損益.html').read_text(encoding='utf-8')
        script = probe(expected)
        views = [render(source, script, 'PC全33場', 1450, 1500),
                 render(source, script, 'mobile全33場', 520, 1350),
                 render(source, script, 'PC比較一覧', 1450, 1500,
                        '<script>document.querySelector("details").open=true;window.scrollTo(0,0);</script>')]
        result = dict(全合格=True, 全10切替広狭=True, 全33場各10=True, 結果=views,
            検査数=sum(view['検査数'] for view in views), 全セル=sum(view['全セル'] for view in views),
            初版訂正='textContentは監査script本文まで含むためNaN文字列を誤検知。表示されたinnerTextだけに限定し、初版False/source/DOMを保持。公開及び経済source変更なし。',
            方法='既存repo verify_report.py同型の隔離headless Chrome。Python Playwright未導入のため依存追加なし。',
            元公開追加読取=0, 元金融=0, 入力cache=0, 実台帳=0, 新金融=0, API=0,
            人目視=False, 根目視=False, 監査sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    except Exception as error:
        result = dict(全合格=False, 理由=str(error), traceback=traceback.format_exc(),
            元公開追加読取=0, 元金融=0, 入力cache=0, 実台帳=0, 新金融=0, API=0)
        PROOF.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
    PROOF.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=result['検査数'], 全セル=result['全セル'], 証跡=str(PROOF),
                         SHA256=hashlib.sha256(PROOF.read_bytes()).hexdigest(), 画像=[view['画像'] for view in views]), ensure_ascii=False))


if __name__ == '__main__':
    main()
