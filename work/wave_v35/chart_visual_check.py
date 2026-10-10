"""全104表示の操作と、選択運用の両銘柄の暗色描画を通信なしで確認する。"""

import hashlib
import json
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / 'アルゴリズム調査/00030_板と両市場による条件付き追跡短縮'

PROBE = '''
/**
 * 全表示枠の参照先・収支・明細を検査し、最後に機械選択運用を描く。
 * 引数: なし。
 * 返り値: なし (undefined)。外部通信・売買再生は行わない。
 */
(()=>{try{
  const data=JSON.parse(document.getElementById('chart-data').textContent);
  const method=document.getElementById('method'),symbol=document.getElementById('symbol'),session=document.getElementById('session');
  let count=0;
  for(const id of Object.keys(data.methods))for(const code of ['TOPIX','NK225'])for(const day of data.sessions){
    method.value=id;symbol.value=code;session.value=day;method.dispatchEvent(new Event('change'));
    const key=[id,day,code].join('|'),item=data.cases[data.views[key]],net=item.trades.reduce((v,r)=>v+r[6],0);
    const wanted=(net>0?'+':'')+net.toLocaleString('ja-JP')+'円',text=document.getElementById('chart-summary').textContent;
    if(!text.includes(wanted)||!text.includes(item.method))throw Error('収支又は実参照の不一致 '+key);
    if(document.querySelectorAll('#trade-table tbody tr').length!==item.trades.length)throw Error('返済欠落 '+key);
    if(document.querySelectorAll('#preparation-table tbody tr').length!==item.preparations.actual.length)throw Error('準備欠落 '+key);
    if(document.querySelectorAll('#event-table tbody tr').length!==item.events.length)throw Error('追跡根拠欠落 '+key);
    if((id==='SELECTED')!==text.includes('運用ではない'))throw Error('固定診断の注記不一致 '+key);
    count++;
  }
  method.value='POLICY';symbol.value=TARGET_SYMBOL;session.value='2026-09-29_Day';method.dispatchEvent(new Event('change'));
  const key=[method.value,session.value,symbol.value].join('|'),item=data.cases[data.views[key]];
  const canvas=document.getElementById('chart'),g=canvas.getContext('2d');
  const pixels=g.getImageData(0,0,canvas.width,canvas.height).data;let exits=0;
  for(let i=0;i<pixels.length;i+=4)if(pixels[i]===255&&pixels[i+1]===223&&pixels[i+2]===124)exits++;
  if(item.trades.length&&!exits)throw Error('返済マーカーが見えない');
  const background=Array.from(g.getImageData(0,0,1,1).data);
  if(background.slice(0,3).join(',')!=='12,21,34')throw Error('暗色背景の不一致');
  document.querySelectorAll('details').forEach(e=>e.open=false);
  document.body.dataset.probe=JSON.stringify({成功:true,全選択数:count,表示枠:method.value,実参照方式:item.method,
    銘柄:symbol.value,セッション:session.value,表示収支:document.getElementById('chart-summary').textContent,
    収支円:item.net_yen,返済件数:item.trades.length,準備件数:item.preparations.actual.length,
    追跡進行件数:item.events.length,返済描画画素数:exits,暗色背景:background});
}catch(e){document.body.dataset.probe=JSON.stringify({成功:false,エラー:String(e)})}})();
'''


def main() -> None:
    """機能: 専用ヘッドレス領域で全表示を操作し、運用図2枚と検査証跡を保存する。

    引数: なし。返り値: なし (None)。元HTMLと売買結果は変更しない。
    """
    path = OUT / '５分足と売買.html'; source = path.read_text(encoding='utf-8')
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    browser = Path('C:/Program Files/Google/Chrome/Application/chrome.exe'); results = []
    for symbol in ('TOPIX', 'NK225'):
        script = PROBE.replace('TARGET_SYMBOL', json.dumps(symbol))
        probe = HERE / ('表示操作_選択運用_' + symbol + '.html')
        probe.write_text(source.replace('</body>', '<script>' + script + '</script></body>'), encoding='utf-8')
        image = HERE / ('表示検査_選択運用_' + symbol + '.png')
        command = [str(browser), '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-default-apps',
            '--disable-features=MediaRouter,OptimizationHints', '--proxy-server=http://127.0.0.1:9',
            '--hide-scrollbars', '--window-size=1440,1250', '--virtual-time-budget=2500',
            '--user-data-dir=' + str(HERE / ('browser_chart_policy_' + symbol)),
            '--screenshot=' + str(image), '--dump-dom', probe.as_uri()]
        run = subprocess.run(command, capture_output=True, timeout=50, creationflags=subprocess.CREATE_NO_WINDOW)
        assert run.returncode == 0, run.stderr[-1500:]
        dom = run.stdout.decode('utf-8', errors='replace')
        (HERE / ('描画後DOM_選択運用_' + symbol + '.html')).write_text(dom, encoding='utf-8')
        document = BeautifulSoup(dom, 'html.parser'); tested = json.loads(document.body['data-probe'])
        assert tested['成功'] and tested['全選択数'] == 104, tested
        assert tested['表示枠'] == 'POLICY' and tested['銘柄'] == symbol
        assert image.exists() and image.stat().st_size > 10000
        results.append({**tested, '画像': image.name, '画像SHA256': hashlib.sha256(image.read_bytes()).hexdigest()})
    assert before == hashlib.sha256(path.read_bytes()).hexdigest()
    value = {'全操作合格': True, '各描画で全104選択': True, '選択運用の両銘柄描画': results,
        '原本HTML不変': True, 'HTML_SHA256': before, '売買再生': False,
        '現在保存物使用': False, 'API取得数': 0, '外部通信': '資料内蔵・背景通信無効・不通プロキシ'}
    (HERE / 'chart_visual_check.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(value, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
