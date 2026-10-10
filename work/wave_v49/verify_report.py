"""暗色レポートの方式切替・全数値・画面幅をヘッドレス描画で検証する。"""

from pathlib import Path
import hashlib
import json
import subprocess
from bs4 import BeautifulSoup
from build_report import HERE,OUT

PROBE='''<script>
/**
 * 機能: 全方式の表示と元データの金額・枚数を照合する。
 * @returns {object} 返り値は検算数と画面幅。
 */
function verifyAll(){let checked=0;const select=document.querySelector('#method');for(const option of select.options){select.value=option.value;showMethod();const r=data.方式.find(x=>x.id===option.value);const rows=[...document.querySelector('#sessions tbody').rows];if(rows.length!==32)throw Error('各場行数');rows.forEach((row,i)=>{const v=r.sessions[i];const cells=[...row.cells];if(cells[1].textContent!==money(v.gross_profit)||cells[2].textContent!==money(-v.gross_loss)||cells[3].textContent!==money(v.net))throw Error('金額不一致');if(Number(cells[4].textContent)!==v.win_qty||Number(cells[5].textContent)!==v.loss_qty||Number(cells[6].textContent)!==v.win_qty-v.loss_qty)throw Error('枚数不一致');checked+=6;});const sums=document.querySelector('#sessions tfoot').rows;['TOPIX','NK225'].forEach((s,i)=>{const net=r.sessions.filter(x=>x.symbol===s).reduce((a,v)=>a+v.net,0);if(sums[i].cells[3].textContent!==money(net)||Math.abs(net-r.periods['全16'][s].net)>1e-6)throw Error('合計不一致');});if(document.querySelector('#totals tbody').rows.length!==6)throw Error('集計行数');}select.value='F50_NONE__E11__G00';showMethod();if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面はみ出し');if(document.body.innerText.includes('undefined')||document.body.innerText.includes('NaN'))throw Error('未定義値');return {全合格:true,方式数:select.options.length,照合数:checked,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth};}
try{document.body.dataset.check=JSON.stringify(verifyAll());}catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e)});}
</script>'''


def render(name,source,width,height,extra=''):
    """機能: 公開HTMLの検査用複製を画像化し、実行結果を読む。

    引数: name/source/extra(str)、width/height(int)。返り値: 検査結果(dict)。
    """
    target=HERE/(name+'.html');picture=HERE/(name+'.png')
    body=source.replace('<head>','<head><base href="'+OUT.as_uri()+'/">')
    target.write_text(body.replace('</body>',PROBE+extra+'</body>'),encoding='utf8')
    command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu',
        '--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync',
        '--proxy-server=http://127.0.0.1:9',f'--window-size={width},{height}','--virtual-time-budget=1500',
        '--user-data-dir='+str(HERE/('visual_'+hashlib.sha256(name.encode()).hexdigest()[:8])), '--screenshot='+str(picture),'--dump-dom',target.as_uri()]
    result=subprocess.run(command,capture_output=True,timeout=50,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0 and picture.exists() and picture.stat().st_size>10000, (result.returncode,result.stderr.decode('utf8',errors='replace')[-1800:])
    soup=BeautifulSoup(result.stdout.decode('utf8',errors='replace'),'html.parser')
    proof=json.loads(soup.body['data-check']);assert proof['全合格'],proof
    return dict(名前=name,画像=str(picture),**proof)


def main():
    """機能: 全方式の金額・枚数と通常/狭い画面を検査する。

    引数: なし。返り値: なし(None)。
    """
    path=OUT/'赤字原因と改善案の検証.html';raw=path.read_bytes();source=raw.decode('utf8')
    checks=[render('全体確認',source,1400,1450),render('狭幅確認',source,520,1500),
        render('損益表確認',source,1400,1400,'<script>document.querySelector("#method").value="SR02";showMethod();document.querySelector("#session-detail").open=true;const first=document.querySelector("label[for=method]");while(document.body.firstElementChild!==first)document.body.firstElementChild.remove();</script>')]
    assert path.read_bytes()==raw
    proof=dict(全合格=True,HTML指紋=hashlib.sha256(raw).hexdigest(),結果=checks,目視確認済=False)
    (HERE/'表示確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(全合格=True,画面数=len(checks),方式数=checks[0]['方式数'],照合数=checks[0]['照合数']),ensure_ascii=False))


if __name__=='__main__':main()
