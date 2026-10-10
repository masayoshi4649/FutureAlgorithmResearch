"""四方式の画面切替・数値列・暗色表示を実ブラウザで確認する。"""

import hashlib
import json
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup

from build_report import OUT,HERE

PROBE='''
<script>
/**
 * 機能: 四方式を切り替え、選択状態と損益行数を確認する。
 * @returns {undefined} 返り値はなく診断属性へ保存する。
 */
function checkPanels(){const counts=[];for(let n=1;n<=4;n++){document.querySelector('[data-tab="'+n+'"]').click();const visible=Array.from(document.querySelectorAll('.panel')).filter(p=>!p.hidden);if(visible.length!==1||visible[0].id!=='method-'+n)throw Error('方式の表示');const money=visible[0].querySelector('[data-kind="money"] tbody');if(money.rows.length!==17)throw Error('損益行数');counts.push(money.rows.length);}selectMethod(1);if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面はみ出し');if(document.body.innerText.includes('undefined')||document.body.innerText.includes('NaN'))throw Error('未定義表示');return counts;}
try{const counts=checkPanels();document.body.dataset.check=JSON.stringify({全合格:true,方式数:counts.length,金額行数:counts,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor});}catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e)});}
</script>
'''


def render(name: str, html: str, width: int, height: int) -> dict:
    """機能: 検査用複製を暗色画面として描画し、画像と操作結果を得る。

    引数: name(str)、html(str)、width/height(int)。返り値: 描画記録(dict)。
    """
    target=HERE/(name+'.html');picture=HERE/(name+'.png')
    target.write_text(html,encoding='utf-8')
    command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu',
        '--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync',
        '--run-all-compositor-stages-before-draw','--disable-features=PaintHolding',
        '--proxy-server=http://127.0.0.1:9',f'--window-size={width},{height}','--virtual-time-budget=1400',
        '--user-data-dir='+str(HERE/('visual_profile_'+hashlib.sha256(name.encode('utf-8')).hexdigest()[:8])),
        '--screenshot='+str(picture),'--dump-dom',target.as_uri()]
    result=subprocess.run(command,capture_output=True,timeout=50,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0 and picture.stat().st_size>10000
    soup=BeautifulSoup(result.stdout.decode('utf-8',errors='replace'),'html.parser')
    proof=json.loads(soup.body['data-check']);assert proof['全合格'],proof
    return dict(名前=name,画像=picture.name,画像SHA256=hashlib.sha256(picture.read_bytes()).hexdigest(),**proof)


def main() -> None:
    """機能: 通常・各章・狭い画面の表示を保存し、元HTMLの不変を確認する。

    引数: なし。返り値: なし(None)。原本データと公表HTMLを変更しない。
    """
    source=OUT/'有望4手法の説明と損益.html';raw=source.read_bytes();html=raw.decode('utf-8')
    soup=BeautifulSoup(html,'html.parser')
    assert len(soup.select('.panel'))==4 and len(soup.select('[data-tab]'))==4
    assert len(soup.select('table[data-kind="money"] tbody tr'))==68
    assert len(soup.select('table[data-kind="units"] tbody tr'))==68
    results=[render('全体の表示',html.replace('</body>',PROBE+'</body>'),1400,1500)]
    for number in range(1,5):
        partial=BeautifulSoup(html,'html.parser');panel=partial.find(id=f'method-{number}')
        panel.extract();partial.body.clear();partial.body.append(panel)
        simple='''<script>
/**
 * 機能: 一章を静的に表示した数値表と幅を確認する。
 * @returns {undefined} 返り値なし。
 */
const rows=document.querySelector('[data-kind="money"] tbody').rows.length;document.body.dataset.check=JSON.stringify({全合格:rows===17&&document.documentElement.scrollWidth<=innerWidth+2,金額行数:rows,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth});
</script>'''
        results.append(render(f'候補{number}の表示',str(partial).replace('</body>',simple+'</body>'),1400,1350))
    results.append(render('狭い画面の表示',html.replace('</body>',PROBE+'</body>'),520,1450))
    assert source.read_bytes()==raw
    output=dict(全合格=True,HTML_SHA256=hashlib.sha256(raw).hexdigest(),結果=results,目視確認済=False)
    (HERE/'表示確認.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(全合格=True,描画数=len(results),全方式切替=True,金額行数=68,枚数行数=68),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
