"""人工会計のHTMLを実Chromeで描画し、全選択肢と合計の検査を回収する。"""

import hashlib
import html
import json
from pathlib import Path
import re
import subprocess


def main() -> None:
    """
    機能: 人工表示だけを通信禁止のheadlessChromeで描画し、DOM証跡を保全する。
    引数: なし。
    返り値: None。金融結果や市場を使用しない。
    """
    folder=Path(__file__).resolve().parent/'artificial'
    target=folder/'人工会計だけの表示確認.html'
    chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    run=subprocess.run([str(chrome),'--headless','--disable-gpu','--no-first-run','--no-default-browser-check',
        '--disable-background-networking','--proxy-server=http://127.0.0.1:9',
        '--user-data-dir='+str(folder/'profile2'),'--window-size=1420,1200','--virtual-time-budget=1500',
        '--dump-dom',target.as_uri()],capture_output=True,timeout=45)
    (folder/'描画後DOM.html').write_bytes(run.stdout)
    (folder/'ブラウザ実行.log').write_bytes(run.stderr)
    assert run.returncode==0,run.returncode
    match=re.search(r'<pre id="artificial-proof">(.*?)</pre>',run.stdout.decode('utf8'))
    assert match,'人工会計の全選択DOM証跡なし'
    proof=json.loads(html.unescape(match.group(1)))
    assert proof['passed'] and proof['checks']>=150
    proof['html_sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
    proof['browser_returncode']=run.returncode
    path=folder/'全選択と全四十一行の人工DOM確認.json'
    assert not path.exists();path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    main()
