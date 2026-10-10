"""ダークHTMLの全選択・数値・リンク・画面幅を検査する。"""

import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import unquote

from bs4 import BeautifulSoup
from build_report import HERE, OUT, TITLE, save


PROBE = r'''<script>
/**
 * 機能: 全手法・全商品・全区間表示を実際に切り替えて検算する。
 * @returns {object} 返り値は検査結果。
 */
function verifyAll(){let cells=0,views=0;
 for(const m of DATA.methods){$('method').value=m.id;for(const s of ['TOPIX','NK225']){$('symbol').value=s;renderMethod();if($('sessionTable').tBodies[0].rows.length!==27)throw Error('場と週の行数');if($('periodTable').tBodies[0].rows.length!==4)throw Error('期間行数');views++;}}
 for(const a of DATA.intervals){$('intervalMethod').value=a['手法'];$('intervalSession').value=a['セッション'];$('intervalSymbol').value=a['銘柄'];renderIntervals();if($('intervalTable').tBodies[0].rows.length!==a['区間'].length)throw Error('区間行数');for(const c of $('intervalTable').querySelectorAll('[data-value]')){if(Number(c.textContent.replaceAll(',',''))!==Number(c.dataset.value))throw Error('表示数値');cells++;}}
 let candidates=0;for(const f of $('family').options){$('family').value=f.value;renderCandidates();candidates+=$('candidateTable').querySelectorAll('tbody tr').length;}if(candidates!==269)throw Error('候補数');
 $('method').value='E01';$('symbol').value='TOPIX';renderMethod();$('intervalMethod').value='O03';$('intervalSession').value='2026-10-05_Night';$('intervalSymbol').value='TOPIX';renderIntervals();
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面幅');if(document.body.innerText.includes('undefined')||document.body.innerText.includes('NaN')||document.body.innerText.includes('@@'))throw Error('未定義値');
 return {全合格:true,手法表示数:views,区間口座数:DATA.intervals.length,表示数値:cells,探索設定数:candidates,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor};}
try{document.body.dataset.check=JSON.stringify(verifyAll());}catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e)});}
</script>'''


def render(source: str, name: str, width: int, height: int, extra: str = '') -> dict:
    """機能: 検査用複製をChromeで描画し、DOMと画像を確認する。

    引数: source/name/extra(str)、width/height(int)。返り値: 描画結果(dict)。
    """
    folder = HERE / 'visual'
    folder.mkdir(exist_ok=True)
    target, picture = folder / (name + '.html'), folder / (name + '.png')
    source = source.replace('<head>', '<head><base href="' + OUT.as_uri() + '/">')
    target.write_text(source.replace('</body>', PROBE + extra + '</body>'), encoding='utf8')
    command = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new', '--disable-gpu',
               '--no-first-run', '--disable-background-networking', '--disable-component-update', '--disable-sync',
               '--run-all-compositor-stages-before-draw', '--disable-features=PaintHolding',
               '--proxy-server=http://127.0.0.1:9', f'--window-size={width},{height}', '--virtual-time-budget=1000',
               '--user-data-dir=' + str(folder / ('profile_' + name)), '--screenshot=' + str(picture),
               '--dump-dom', target.as_uri()]
    result = subprocess.run(command, capture_output=True, timeout=55, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0 and picture.exists()
    soup = BeautifulSoup(result.stdout.decode('utf8', errors='replace'), 'html.parser')
    proof = json.loads(soup.body['data-check'])
    assert proof['全合格'], proof
    return dict(名前=name, 画像=str(picture), **proof)


def main() -> None:
    """機能: 静的リンクと画面操作を検査して証拠を保存する。

    引数: なし。返り値: なし(None)。
    """
    source = (OUT / TITLE).read_text(encoding='utf8')
    soup = BeautifulSoup(source, 'html.parser')
    checked = 0
    for tag in soup.select('a[href], img[src]'):
        link = tag.get('href', tag.get('src'))
        if link.startswith(('http', '#')):
            continue
        target = OUT / unquote(link.split('#')[0].split('?')[0])
        assert target.exists(), target
        checked += 1
    results = [render(source, '全体', 1450, 1450), render(source, '狭幅', 520, 1350),
               render(source, '時間区間', 1450, 1450, '<script>document.querySelector("main").replaceChildren(document.querySelector("#intervals"));window.scrollTo(0,0);</script>')]
    save(OUT / '表示確認.json', dict(全合格=True, HTML_SHA256=hashlib.sha256((OUT / TITLE).read_bytes()).hexdigest(),
                                   静的リンク数=checked, 目視確認=False, 結果=results))
    print('全選択・数値・リンク・3画面の検査合格')


if __name__ == '__main__':
    main()
