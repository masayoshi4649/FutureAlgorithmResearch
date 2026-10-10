"""暗色の比較表と全20個の折り畳み表を実ブラウザで確認する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup
import report

HERE = Path(__file__).resolve().parent
PROBE = '''
/**
 * 機能: 全市場表の開閉・列数・背景・横はみ出しを実描画で確認する。
 * 引数: mode (number) は撮影対象。返り値: bodyの診断属性へ結果を保存する。
 */
function inspect(mode) {
 try {
  const panels=[...document.querySelectorAll('details')];
  if(panels.length!==20) throw Error('市場表の数');
  for(const panel of panels) {
   panel.open=true;
   if(panel.querySelectorAll('tr[data-key]').length!==16) throw Error('全期間行数');
   for(const row of panel.querySelectorAll('tr[data-key]')) {
    if(row.children.length!==8) throw Error('金額と枚数の列数');
    if(row.textContent.includes('NaN')||row.textContent.includes('undefined')) throw Error('未表示');
   }
   if(panel.querySelector('table').getBoundingClientRect().height<=100) throw Error('展開不可');
   panel.open=false;
  }
  if(getComputedStyle(document.body).backgroundColor!=='rgb(16, 21, 30)') throw Error('暗色');
  if(mode===1) {
   const chapter=document.querySelector('#C03');
   chapter.querySelector('details').open=true;
   // 撮影用複写だけで対象章を先頭へ移し、実表の配色と全列を確認する。
   document.querySelector('main').prepend(chapter);
   scrollTo(0,0);
  }
  if(document.documentElement.scrollWidth>innerWidth+2) throw Error('全画面の横はみ出し');
  document.body.dataset.probe=JSON.stringify({成功:true,全市場開閉数:20,全損益行数:320,暗色:true});
 } catch(error) {document.body.dataset.probe=JSON.stringify({成功:false,理由:String(error)});}
}
'''


def main() -> None:
    """機能: 元HTMLを変更せず2表示を撮影し、全折り畳み操作を検査する。

    引数: なし。返り値: なし (None)。画像と実行証跡を作業内へ保存する。
    """
    source = report.OUT / (report.TITLE + '.html')
    before = report.digest(source)
    browser = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    rows = []
    for mode in (0, 1):
        target, picture = HERE / f'表示確認{mode}.html', HERE / f'表示確認{mode}.png'
        target.write_text(source.read_text(encoding='utf-8').replace('</html>', '<script>' + PROBE +
                          f'inspect({mode});</script></html>'), encoding='utf-8')
        command = [str(browser), '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                   '--disable-background-networking', '--disable-component-update', '--disable-sync',
                   '--disable-default-apps', '--disable-features=MediaRouter,OptimizationHints',
                   '--proxy-server=http://127.0.0.1:9', '--hide-scrollbars', '--window-size=1440,1280',
                   '--virtual-time-budget=2500', '--user-data-dir=' + str(HERE / f'表示ブラウザ{mode}'),
                   '--screenshot=' + str(picture), '--dump-dom', target.as_uri()]
        run = subprocess.run(command, capture_output=True, timeout=55, creationflags=subprocess.CREATE_NO_WINDOW)
        assert run.returncode == 0, run.stderr[-1500:]
        parsed = BeautifulSoup(run.stdout.decode('utf-8', errors='replace'), 'html.parser')
        value = json.loads(parsed.body['data-probe'])
        assert value['成功'] and picture.stat().st_size > 10000, value
        assert report.digest(source) == before
        rows.append(dict(**value, 画像=picture.name,画像SHA256=report.digest(picture)))
    record = dict(全合格=True,HTML_SHA256=before,結果=rows,
                  監査実装SHA256=report.digest(Path(__file__)),現在API取得数=0)
    (HERE / 'report_visual_check.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print('暗色2画面・全20市場表の開閉と320行を確認。', flush=True)


if __name__ == '__main__':
    main()
