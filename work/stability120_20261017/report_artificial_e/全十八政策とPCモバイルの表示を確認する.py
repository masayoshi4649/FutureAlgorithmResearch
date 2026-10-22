"""完成SHAで固定した私有HTMLだけを、隔離Chromeの二画面幅で検査する。"""

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess


HERE=Path(__file__).resolve().parent
CHROME=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


def main(public: Path, expected: str, output: Path, fixture: bool) -> None:
    """
    機能: 十八切替・全四十場・暗色・画面幅・JS例外を二画面で検査する。
    引数: public(Path)は生成済み表示、expected(str)はHTML指定SHA、
          output(Path)は新規保存先、fixture(bool)は完全合成かどうか。
    返り値: None。HTML一読だけで描画し、金融結果・NPZ・原市場は読まない。
    """
    paths=list(public.glob('*.html'));assert len(paths)==1 and not output.exists()
    raw=paths[0].read_bytes();expected=expected.lower()
    assert hashlib.sha256(raw).hexdigest()==expected and len(expected)==64
    output.mkdir(parents=True)
    capture='''<script>
/**
 * 機能: 描画中の例外とconsole.errorを外部通信なしで記録する。
 * 引数: event(ErrorEvent)等はブラウザから通知されるエラー。
 * 返り値: なし。所有検査画面内の配列だけを更新する。
 */
window.qaErrors=[];
window.addEventListener('error',event=>qaErrors.push(String(event.message)));
window.addEventListener('unhandledrejection',event=>qaErrors.push(String(event.reason)));
console.error=(...args)=>qaErrors.push(args.map(String).join(' '));
</script>'''
    probe='''<script>
/**
 * 機能: 全政策の選択と主表リンクを走査し、表示先と全場数を記録する。
 * 引数: なし。保存済みDOMと選択イベントだけを使用する。
 * 返り値: なし。JSONをbody属性へ保存し、約定や集計は再計算しない。
 */
window.addEventListener('load',()=>{
  const selector=document.querySelector('#policy'),results=[];
  for(const option of selector.options){
    selector.value=option.value;selector.dispatchEvent(new Event('change'));
    const panels=[...document.querySelectorAll('.case-panel')].filter(p=>!p.hidden);
    results.push({id:option.value,one:panels.length===1,match:panels.length===1&&panels[0].dataset.method===option.value,rows:panels.length===1?panels[0].querySelectorAll('tbody tr').length:-1});
  }
  const links=[...document.querySelectorAll('[data-open]')];
  for(const link of links){
    link.click();const panels=[...document.querySelectorAll('.case-panel')].filter(p=>!p.hidden);
    if(panels.length!==1||panels[0].dataset.method!==link.dataset.open)qaErrors.push('主表リンク先不一致');
  }
  selector.value=selector.options[0].value;selector.dispatchEvent(new Event('change'));
  document.body.dataset.displayCheck=JSON.stringify({policies:results.length,all:results.every(r=>r.one&&r.match&&r.rows===40),results,mainLinks:links.length,errors:qaErrors,dark:getComputedStyle(document.body).backgroundColor==='rgb(11, 17, 32)',viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,overflow:document.documentElement.scrollWidth>innerWidth+1});
});
</script>'''
    source=raw.decode('utf8');assert source.count('</head>')==source.count('</body>')==1
    instrumented=source.replace('</head>',capture+'</head>').replace('</body>',probe+'</body>')
    screens={}
    for label,width in (('PC',1450),('モバイル',520)):
        folder=output/label;folder.mkdir()
        target=folder/'所有検査画面.html';target.write_text(instrumented,encoding='utf8')
        picture=folder/'画面.png'
        command=[str(CHROME),'--headless=new','--disable-gpu','--no-first-run',
            '--disable-background-networking','--disable-component-update','--disable-sync',
            '--proxy-server=http://127.0.0.1:9',f'--window-size={width},1900',
            '--virtual-time-budget=1500','--user-data-dir='+str((folder/'profile').resolve()),
            '--screenshot='+str(picture.resolve()),'--dump-dom',target.resolve().as_uri()]
        process=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
        (folder/'描画stderr.txt').write_bytes(process.stderr)
        assert process.returncode==0 and picture.exists()
        found=re.search(r'<body\b[^>]*\bdata-display-check="([^"]*)"',process.stdout.decode('utf8',errors='replace'))
        assert found,'検査scriptの終端なし'
        result=json.loads(html.unescape(found.group(1)))
        assert result['policies']==18 and result['all'] and result['mainLinks']==3
        assert result['dark'] and not result['overflow'] and result['errors']==[]
        result.update(image_path=str(picture.resolve()),image_SHA256=hashlib.sha256(picture.read_bytes()).hexdigest())
        screens[label]=result
    proof=dict(passed=True,fixture=fixture,HTML_SHA256=expected,screens=screens,
        script_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        HTML_reads=1,financial_result_reads=0,NPZ_reads=0,market_reads=0,financial_replay=0,API=0,
        担当画像目視=False,根画像目視=False)
    path=output/'全十八切替と二画面の表示確認.json'
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,fixture=fixture,proof_path=str(path),proof_SHA256=hashlib.sha256(path.read_bytes()).hexdigest()),ensure_ascii=False))


# ----------------------------------------


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--public',type=Path,default=HERE.parent/'private_e/public')
    parser.add_argument('--expected-html-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fixture',action='store_true')
    args=parser.parse_args()
    main(args.public,args.expected_html_sha256,args.output,args.fixture)
