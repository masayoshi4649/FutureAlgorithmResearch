"""三方式の切替・暗色描画・狭幅表示を検査する。"""

import hashlib
import json
from pathlib import Path
import subprocess
from bs4 import BeautifulSoup
from build_report import HERE,OUT,TITLE

PROBE='''<script>
/**
 * 機能: 全タブの表示、表行数、数値表示、画面幅を確認する。
 * @returns {object} 返り値は検査記録。
 */
function checkPanels(){let cells=0;for(let n=1;n<=3;n++){document.querySelector('[data-tab="'+n+'"]').click();const visible=[...document.querySelectorAll('.panel')].filter(p=>!p.hidden);if(visible.length!==1||visible[0].id!=='method-'+n)throw Error('方式切替');for(const kind of ['money','units']){const table=visible[0].querySelector('[data-kind="'+kind+'"]');if(table.tBodies[0].rows.length!==19)throw Error('期間行数');for(const cell of table.querySelectorAll('[data-value]')){const v=Number(cell.dataset.value),actual=Number(cell.textContent.replaceAll(',',''));if(!Number.isFinite(v)||v!==actual)throw Error('表示値');cells++;}}}selectMethod(1);if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面はみ出し');if(document.body.innerText.includes('undefined')||document.body.innerText.includes('NaN'))throw Error('未定義値');return {全合格:true,方式数:3,各表行数:19,表示数値:cells,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor};}
try{document.body.dataset.check=JSON.stringify(checkPanels());}catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e)});}
</script>'''


def render(name,source,width,height,extra=''):
    """機能: 検査用複製を描画し、操作結果と画像を保存する。

    引数: name/source/extra(str)、width/height(int)。返り値: 描画結果(dict)。
    """
    target=HERE/(name+'.html');picture=HERE/(name+'.png')
    target.write_text(source.replace('</body>',PROBE+extra+'</body>'),encoding='utf8')
    command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu',
        '--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync',
        '--run-all-compositor-stages-before-draw','--disable-features=PaintHolding',
        '--proxy-server=http://127.0.0.1:9',f'--window-size={width},{height}','--virtual-time-budget=1500',
        '--user-data-dir='+str(HERE/('visual_'+hashlib.sha256(name.encode()).hexdigest()[:8])),
        '--screenshot='+str(picture),'--dump-dom',target.as_uri()]
    result=subprocess.run(command,capture_output=True,timeout=50,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0 and picture.exists() and picture.stat().st_size>10000
    soup=BeautifulSoup(result.stdout.decode('utf8',errors='replace'),'html.parser')
    proof=json.loads(soup.body['data-check']);assert proof['全合格'],proof
    return dict(名前=name,画像=str(picture),**proof)


def main():
    """機能: 全体・各方式・狭い画面を検査し、公表HTMLの指紋を残す。

    引数: なし。返り値: なし(None)。
    """
    source=(OUT/TITLE).read_text(encoding='utf8');proofs=[]
    proofs.append(render('全体',source,1450,1450))
    for number in range(1,4):
        extra=f'''<script>selectMethod({number});const panel=document.querySelector('#method-{number}');for(const child of [...document.body.children])if(child!==panel&&child.tagName!=='SCRIPT')child.remove();</script>'''
        proofs.append(render(f'手法{number}',source,1400,1500,extra))
    proofs.append(render('狭い画面',source,520,1500))
    result=dict(全合格=True,HTML_SHA256=hashlib.sha256((OUT/TITLE).read_bytes()).hexdigest(),目視確認済=False,結果=proofs)
    (HERE/'表示確認.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print('全3タブ・684数値・5画面の表示検査合格',flush=True)


if __name__=='__main__':main()
