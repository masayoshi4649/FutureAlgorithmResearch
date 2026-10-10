"""公表HTMLを実Chromeで描画し、内蔵選択肢と表示を検査する。"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00041_入口途中出口の分解検証'
PROBE='''<script>
/**
 * 機能: 各選択肢で注文表又は損益表が描画されることを検査する。
 * @returns {undefined} 返り値はなく診断属性に記録する。
 */
try{
 const s=document.getElementById('method');let count=0;
 if(s){const initial=s.value;if(!s.options.length)throw Error('選択肢なし');
  for(const item of s.options){s.value=item.value;s.dispatchEvent(new Event('change'));count++;
   if(document.getElementById('chart')){const d=JSON.parse(document.getElementById('chart-data').textContent)[Number(item.value)];if(document.getElementById('orders').children.length!==d.orders.length)throw Error('注文数');}
   if(document.getElementById('profits')&&!document.getElementById('profits').children.length)throw Error('損益表なし');
  }s.value=initial;s.dispatchEvent(new Event('change'));
 }
 const w=document.documentElement.scrollWidth;
 if(w>innerWidth+3)throw Error('横はみ出し '+w);
 if(document.body.innerText.includes('undefined')||document.body.innerText.includes('NaN'))throw Error('未定義表示');
 document.body.dataset.check=JSON.stringify({成功:true,全選択数:count,文書幅:w,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor});
}catch(e){document.body.dataset.check=JSON.stringify({成功:false,理由:String(e)});}
</script>'''


def main() -> None:
    """機能: 指定した既存HTMLの画像と操作検査を保存する。

    引数: コマンドラインpages(list[str])。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('pages',nargs='+');args=parser.parse_args()
    results=[]
    for i,name in enumerate(args.pages):
        source=OUT/name;raw=source.read_bytes();label=source.stem
        target=HERE/(label+'_表示検査.html');picture=HERE/(label+'_表示検査.png')
        target.write_text(raw.decode('utf-8').replace('</body>',PROBE+'</body>'),encoding='utf-8')
        command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu',
            '--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync',
            '--proxy-server=http://127.0.0.1:9','--window-size=1400,1200','--virtual-time-budget=2000',
            '--user-data-dir='+str(HERE/f'visual_profile_{i}'),'--screenshot='+str(picture),'--dump-dom',target.as_uri()]
        completed=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
        assert completed.returncode==0,completed.stderr[-1000:]
        soup=BeautifulSoup(completed.stdout.decode('utf-8',errors='replace'),'html.parser')
        proof=json.loads(soup.body['data-check']);assert proof['成功'],(name,proof)
        assert source.read_bytes()==raw and picture.stat().st_size>10000
        results.append(dict(ファイル=name,HTML_SHA256=hashlib.sha256(raw).hexdigest(),画像=picture.name,**proof))
    destination=HERE/('表示検査_'+str(len(args.pages))+'画面.json')
    destination.write_text(json.dumps(dict(全合格=True,結果=results,目視確認済=False),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
