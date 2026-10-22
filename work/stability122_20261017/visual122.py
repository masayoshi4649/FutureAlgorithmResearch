"""通常と代理を分けた比較HTMLを実ブラウザで表示確認する。"""

import json
from pathlib import Path
import subprocess
from bs4 import BeautifulSoup
from register122 import HERE,ROOT,sha,save


def main() -> None:
    """
    機能: 全40場の行数・主要金額・暗色表示を確認し画像を保存する。
    引数: なし。完成した公開HTMLのみを読む。
    返り値: None。市場読取と売買再生は行わない。
    """
    path=ROOT/'アルゴリズム調査/00122_途中利確なしと引け一括精算/途中利確なしと引け一括の比較.html'
    raw=path.read_bytes();out=HERE/'visual';out.mkdir(exist_ok=False)
    probe='''<script>
/**
 * 機能: 固定比較表と主要な金額の描画を検査する。
 * 引数: なし。
 * 返り値: body属性へ確認結果を保存する。
 */
try{
 const t=Array.from(document.querySelectorAll('table'));
 const rows=t.map(x=>x.querySelectorAll('tbody tr').length);
 if(!rows.includes(40))throw Error('全40場の行不足');
 const text=document.body.innerText;
 for(const v of ['91,188','1,031,046','287,546','15:45','06:00'])if(!text.includes(v))throw Error('表示金額又は時刻 '+v);
 if(!text.includes('代用')&&!text.includes('代理'))throw Error('終値仮定の注記なし');
 if(text.includes('undefined')||text.includes('NaN'))throw Error('未定義表示');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('文書横溢れ');
 document.body.dataset.qa=JSON.stringify({passed:true,table_rows:rows,innerWidth,documentWidth:document.documentElement.scrollWidth,background:getComputedStyle(document.body).backgroundColor});
}catch(e){document.body.dataset.qa=JSON.stringify({passed:false,error:String(e)});}
</script>'''
    target=out/'描画用.html';target.write_bytes(raw.replace(b'</body>',probe.encode('utf-8')+b'</body>'))
    image=out/'画面.png'
    command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu',
        '--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync',
        '--proxy-server=http://127.0.0.1:9','--window-size=1420,1200','--virtual-time-budget=1500',
        '--user-data-dir='+str(out/'profile'),'--screenshot='+str(image),'--dump-dom',target.as_uri()]
    process=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode==0,process.stderr[-1000:]
    soup=BeautifulSoup(process.stdout.decode('utf-8',errors='replace'),'html.parser')
    proof=json.loads(soup.body['data-qa']);assert proof['passed'],proof
    assert path.read_bytes()==raw and image.stat().st_size>10000
    save(out/'比較表と全四十場の実描画.json',dict(html_sha256=sha(path),root_viewed=False,
        financial_replay=0,**proof))
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    main()
