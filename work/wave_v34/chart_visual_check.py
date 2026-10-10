"""独立ヘッドレス領域で全78選択を操作し、制御方式の両銘柄の描画を保存する。"""

import hashlib
import json
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / 'アルゴリズム調査/00029_仮想建玉による再エントリー制御'

PROBE = '''
/**
 * 全図の選択操作と明細件数を照合し、最後に固定の制御方式を表示する。
 * 引数: なし。返り値: なし (undefined)。売買再生や外部接続を行わない。
 */
(()=>{try{
  const data=JSON.parse(document.getElementById('chart-data').textContent);
  const method=document.getElementById('method'),symbol=document.getElementById('symbol'),session=document.getElementById('session');
  let count=0;
  for(const id of Object.keys(data.methods))for(const code of ['TOPIX','NK225'])for(const day of data.sessions){
    method.value=id;symbol.value=code;session.value=day;method.dispatchEvent(new Event('change'));
    const key=[id,day,code].join('|'),trades=data.trades[key],prepared=data.preparations[key];
    const net=trades.reduce((n,r)=>n+r[6],0),wanted=(net>0?'+':'')+net.toLocaleString('ja-JP')+'円';
    if(!document.getElementById('chart-summary').textContent.includes(wanted))throw Error('収支表示不一致 '+key);
    if(document.querySelectorAll('#trade-table tbody tr').length!==trades.length)throw Error('返済明細欠落 '+key);
    if(document.querySelectorAll('#preparation-table tbody tr').length!==prepared.shadow.length+prepared.actual.length)throw Error('準備明細欠落 '+key);
    count++;
  }
  method.value='H019__AT__SHADOW__V000';symbol.value=TARGET_SYMBOL;session.value='2026-09-29_Day';method.dispatchEvent(new Event('change'));
  const key=[method.value,session.value,symbol.value].join('|'),prepared=data.preparations[key],trades=data.trades[key];
  const canvas=document.getElementById('chart'),g=canvas.getContext('2d'),scale=canvas.height/canvas.getBoundingClientRect().height;
  const pixels=g.getImageData(0,Math.floor((canvas.getBoundingClientRect().height-96)*scale),canvas.width,Math.floor(58*scale)).data;
  let purple=0,cyan=0;
  for(let i=0;i<pixels.length;i+=4){
    if(pixels[i]===180&&pixels[i+1]===146&&pixels[i+2]===241)purple++;
    if(pixels[i]===97&&pixels[i+1]===199&&pixels[i+2]===226)cyan++;
  }
  if(prepared.shadow.length&&!purple)throw Error('影の準備マーカーを描画していない');
  if(prepared.actual.length&&!cyan)throw Error('実の準備マーカーを描画していない');
  const background=Array.from(g.getImageData(0,0,1,1).data);
  if(background.slice(0,3).join(',')!=='12,21,34')throw Error('暗色背景の不一致');
  document.querySelectorAll('details').forEach(e=>e.open=false);
  document.body.dataset.probe=JSON.stringify({成功:true,全選択数:count,手法:method.value,銘柄:symbol.value,セッション:session.value,
    表示収支:document.getElementById('chart-summary').textContent,収支円:trades.reduce((n,r)=>n+r[6],0),
    返済件数:trades.length,影準備件数:prepared.shadow.length,実準備件数:prepared.actual.length,
    紫描画画素数:purple,水色描画画素数:cyan,暗色背景:background});
}catch(e){document.body.dataset.probe=JSON.stringify({成功:false,エラー:String(e)})}})();
'''


def main() -> None:
    """機能: 図示だけのブラウザ操作と画像を新作業フォルダに保存する。

    引数: なし。返り値: なし (None)。原本HTML/売買結果/旧ファイルを変更しない。
    """
    path = OUT / '５分足と売買.html'
    source = path.read_text(encoding='utf-8')
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    browser = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    results = []
    for symbol in ('TOPIX', 'NK225'):
        script = PROBE.replace('TARGET_SYMBOL', json.dumps(symbol))
        probe = HERE / ('表示操作_制御_' + symbol + '.html')
        probe.write_text(source.replace('</body>', '<script>' + script + '</script></body>'), encoding='utf-8')
        image = HERE / ('表示検査_制御_' + symbol + '.png')
        command = [str(browser), '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-default-apps',
            '--disable-features=MediaRouter,OptimizationHints', '--proxy-server=http://127.0.0.1:9',
            '--hide-scrollbars', '--window-size=1440,1500', '--virtual-time-budget=2000',
            '--user-data-dir=' + str(HERE / ('browser_chart_control_' + symbol)),
            '--screenshot=' + str(image), '--dump-dom', probe.as_uri()]
        finished = subprocess.run(command, capture_output=True, timeout=50, creationflags=subprocess.CREATE_NO_WINDOW)
        assert finished.returncode == 0, finished.stderr[-1500:]
        dom = finished.stdout.decode('utf-8', errors='replace')
        (HERE / ('描画後DOM_制御_' + symbol + '.html')).write_text(dom, encoding='utf-8')
        parsed = BeautifulSoup(dom, 'html.parser')
        tested = json.loads(parsed.body['data-probe'])
        assert tested['成功'] and tested['全選択数'] == 78, tested
        assert tested['手法'] == 'H019__AT__SHADOW__V000' and tested['銘柄'] == symbol
        assert image.exists() and image.stat().st_size > 10000
        results.append({**tested, '画像': image.name, '画像SHA256': hashlib.sha256(image.read_bytes()).hexdigest()})
    assert before == hashlib.sha256(path.read_bytes()).hexdigest()
    value = {'全操作合格': True, '各銘柄全78選択': True, '制御方式の両銘柄描画': results,
             '原本HTML不変': True, 'HTML_SHA256': before, '売買再生': False,
             '現在保存物使用': False, 'API取得数': 0, '外部通信': '全資料内蔵・背景通信無効・不通プロキシ指定'}
    (HERE / 'chart_visual_check.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(value, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
