"""売買結果を読まず、人工表示データで全選択と暗色描画を確認する。"""

from pathlib import Path
import hashlib
import json
import subprocess
from bs4 import BeautifulSoup
import chart_report as chart
import chart_visual_check as visual

HERE=Path(__file__).resolve().parent


def main() -> None:
    """機能: 人工だけの156表示を操作して注文・分岐表と損益表示を検査する。

    引数: なし。返り値: なし(None)。実の保存台帳・原本価格は使用しない。
    """
    chart.design.prepare()
    sessions=[f'2026-09-{d:02d}_{kind}' for d in (21,22,23,24,25,28) for kind in ('Day','Night')]+['2026-09-29_Day']
    data=dict(methods=chart.design.METHODS,descriptions=chart.design.DESCRIPTIONS,sessions=sessions,
        candles={},orders={},trades={},tracking={},adjustments={},branches={},
        reason_names={**chart.runner.engine.REASONS,20:'組開始新規',31:'数量復元'},adjustment_names=chart.runner.engine.ADJUSTMENT_NAMES)
    for day in sessions:
        for symbol in ('TOPIX','NK225'):
            data['candles'][day+'|'+symbol]=[[i*300,100+i,103+i,98+i,102+i] for i in range(12)]
            for identifier in chart.design.METHODS:
                key=identifier+'|'+day+'|'+symbol
                data['orders'][key]=[[300,1,0,0,1,5,101,20,1],[600,2,1,0,-1,2,100,30,0],
                    [900,3,2,0,1,2,103,31,1],[1800,6,5,0,-1,5,107,2,0]]
                data['trades'][key]=[[300,600,1,2,101,100,-2000,30,1,2],
                    [300,1800,1,3,101,107,18000,2,1,6],[900,1800,1,2,103,107,8000,2,3,6]]
                data['tracking'][key]=[[i*300,i,0 if i<1 or i>=6 else 3 if i==2 else 5,0 if i<1 or i>=6 else 5] for i in range(12)]
                data['adjustments'][key]=[[300,1,0,1,-1,1,1,2,0,300],[600,2,0,2,-1,1,1,2,0,300],
                    [600,2,0,1,1,2,2,2,0,600],[900,3,0,2,1,2,2,2,0,600]]
                data['branches'][key]=[[600,2,0,1,1,-1,1,1,3,1,-1,300,100]] if 'CHOICE' in identifier or 'INVERT' in identifier else []
    source=chart.html(data);probe=HERE/'chart_synthetic_visual.html';image=HERE/'chart_synthetic_visual.png'
    probe.write_text(source.replace('</body>','<script>'+visual.PROBE.replace('TARGET',json.dumps(chart.design.TARGETS[0]))+'</script></body>'),encoding='utf-8')
    browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    command=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
        '--disable-background-networking','--disable-component-update','--disable-sync','--disable-default-apps',
        '--disable-features=MediaRouter,OptimizationHints','--proxy-server=http://127.0.0.1:9','--hide-scrollbars',
        '--window-size=1440,1250','--virtual-time-budget=2500','--user-data-dir='+str(HERE/'chart_synthetic_browser'),
        '--screenshot='+str(image),'--dump-dom',probe.as_uri()]
    completed=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
    assert completed.returncode==0,completed.stderr[-1500:]
    document=BeautifulSoup(completed.stdout.decode('utf-8',errors='replace'),'html.parser')
    value=json.loads(document.body['data-probe']);assert value['成功'] and value['全選択数']==156,value
    value.update(人工データだけ=True,実損益読取=False,新売買再生=False,
        画像SHA256=hashlib.sha256(image.read_bytes()).hexdigest(),固定SHA256=chart.runner.digest(HERE/'chart_fixed.json'))
    chart.runner.save(HERE/'chart_synthetic_visual.json',value)
    print('PASS',156,flush=True)


if __name__=='__main__':main()
