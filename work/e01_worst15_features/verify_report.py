"""補足HTMLの暗色描画・数値・横幅・参照先を検査する。"""

import hashlib
import json
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup
from build_report import HERE, OUT, TITLE


def main() -> None:
    """機能: 広い画面と狭い画面を描画し、数値とリンクを検証する。

    引数: なし。返り値: なし(None)。ネットワーク通信を使わない。
    """
    source=(OUT/TITLE).read_text(encoding='utf-8')
    soup=BeautifulSoup(source,'html.parser')
    for link in soup.select('a[href]'):
        assert (OUT/link['href']).exists(),link['href']
    probe='''<script>
/**
 * 機能: 数値表示と文書幅を検証する。
 * @returns {object} 返り値は検査記録。
 */
function verify(){let n=0;for(const node of document.querySelectorAll('[data-value]')){if(Number(node.dataset.value)!==Number(node.textContent.replaceAll(',','')))throw Error('数値不一致');n++;}if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面はみ出し');return {全合格:true,数値数:n,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth};}
try{document.body.dataset.check=JSON.stringify(verify());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''
    results=[]
    for name,width,height in [('特徴全体',1400,1850),('特徴狭幅',520,1900)]:
        sample=HERE/(name+'.html'); picture=HERE/(name+'.png')
        sample.write_text(source.replace('</body>',probe+'</body>'),encoding='utf-8')
        command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu',
                 '--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync',
                 '--run-all-compositor-stages-before-draw','--disable-features=PaintHolding',
                 '--proxy-server=http://127.0.0.1:9',f'--window-size={width},{height}',
                 '--virtual-time-budget=1000','--user-data-dir='+str(HERE/(name+'_profile')),
                 '--screenshot='+str(picture),'--dump-dom',sample.as_uri()]
        result=subprocess.run(command,capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0 and picture.exists()
        dom=BeautifulSoup(result.stdout.decode('utf-8',errors='replace'),'html.parser')
        check=json.loads(dom.body['data-check'])
        assert check['全合格'],check
        results.append(dict(名前=name,画像=str(picture),**check))
    proof=dict(全合格=True,HTML_SHA256=hashlib.sha256((OUT/TITLE).read_bytes()).hexdigest(),
               目視確認済=False,結果=results)
    (OUT/'特徴分析/表示検証.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
