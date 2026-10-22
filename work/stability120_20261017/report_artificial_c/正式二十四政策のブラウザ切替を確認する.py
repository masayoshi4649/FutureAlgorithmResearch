"""正式生成HTMLだけを隔離Chromeで開き、全政策の切替と狭幅を調べる。"""

import hashlib
import html
import json
from pathlib import Path
import re
import subprocess


HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 正式24政策を順に選び、一件だけの40場表が見えることを確認する。
    引数: なし。入力は完成済み私有cのpublic HTMLのみ。
    返り値: None。実測・市場・金融・ユーザーのブラウザ状態を利用しない。
    """
    public=HERE.parent/'private_c/public';paths=list(public.glob('*.html'));assert len(paths)==1
    raw=paths[0].read_bytes();assert hashlib.sha256(raw).hexdigest()=='23cd4d02692a825e2b0d070d9c7b7fe4b917f88bfef486c868da08f1033b4954';folder=HERE/'正式24政策切替';assert not folder.exists();folder.mkdir()
    script='''<script>
/**
 * 機能: 正式全選択肢を走査し、表示表と選択値の一致を記録する。
 * 引数: なし。#policy及び保存済み.case-panelだけが対象。
 * 返り値: なし。検査値をbody属性へ保存する。
 */
window.addEventListener('load',()=>{
  const select=document.querySelector('#policy');const results=[];
  for(const option of select.options){
    select.value=option.value;select.dispatchEvent(new Event('change'));
    const visible=[...document.querySelectorAll('.case-panel')].filter(p=>!p.hidden);
    results.push({id:option.value,one:visible.length===1,match:visible.length===1&&visible[0].dataset.method===option.value,rows:visible.length===1?visible[0].querySelectorAll('tbody tr').length:-1});
  }
  const dark=getComputedStyle(document.body).backgroundColor==='rgb(11, 17, 32)';
  const links=[...document.querySelectorAll('[data-open]')];
  for(const link of links){link.click();const visible=[...document.querySelectorAll('.case-panel')].filter(p=>!p.hidden);if(visible.length!==1||visible[0].dataset.method!==link.dataset.open)throw new Error('候補リンクの表示先不一致');}
  select.value=select.options[select.options.length-1].value;select.dispatchEvent(new Event('change'));
  document.body.dataset.fixtureCheck=JSON.stringify({policies:results.length,all:results.every(r=>r.one&&r.match&&r.rows===40),results,mainLinks:links.length,dark,viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,overflow:document.documentElement.scrollWidth>innerWidth+1});
});
</script>'''
    source=raw.decode('utf8');assert source.count('</body>')==1
    target=folder/'正式検査画面.html';target.write_text(source.replace('</body>',script+'</body>'),encoding='utf8')
    picture=folder/'画面.png'
    command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu','--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync','--proxy-server=http://127.0.0.1:9','--window-size=500,1800','--virtual-time-budget=1800','--user-data-dir='+str((folder/'profile').resolve()),'--screenshot='+str(picture.resolve()),'--dump-dom',target.resolve().as_uri()]
    proc=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
    (folder/'描画stderr.txt').write_bytes(proc.stderr);assert proc.returncode==0 and picture.exists()
    found=re.search(r'<body\b[^>]*\bdata-fixture-check="([^"]*)"',proc.stdout.decode('utf8',errors='replace'));assert found
    result=json.loads(html.unescape(found.group(1)));assert result['policies']==24 and result['all'] and result['mainLinks']==3 and result['dark'] and not result['overflow']
    result.update(passed=True,fixture=False,source_SHA256=hashlib.sha256(raw).hexdigest(),image_SHA256=hashlib.sha256(picture.read_bytes()).hexdigest(),actual_result_reads=0,NPZ_reads=0,market_reads=0,financial_replay=0,API=0)
    proof=folder/'正式全政策切替と狭幅の表示検査.json';proof.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,policies=24,source_sha256=result['source_SHA256'],proof_sha256=hashlib.sha256(proof.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
