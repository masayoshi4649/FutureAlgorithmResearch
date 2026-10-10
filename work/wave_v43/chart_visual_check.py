"""単一中央と3窓合議の2例を実Chromeで表示し、目視用画像を保存する。"""

from pathlib import Path
import hashlib
import json
import subprocess

from bs4 import BeautifulSoup

import chart_report as report

HERE,ROOT=report.HERE,report.ROOT
CASES=(('S100__A0__V000','2026-09-29_Day'),('M2_100__B00_RB00_F25_N1__V000','2026-09-29_Day'))
PROBE='''
/**
 * 機能: 固定した単独/合議の画面と4方向帯・全注文表を確認する。
 * 引数: 埋込手法・セッション名(string)。
 * 返り値: body診断属性へ結果(JSON)を保存する。
 */
(()=>{try{
 const method=METHOD,session=SESSION;window.chartSelect(method,'TOPIX',session);
 const d=JSON.parse(document.getElementById('chart-data').textContent),key=method+'|'+session+'|TOPIX',r=d.records[key];
 if(window.chartRenderedKey!==key||!window.chartViewReady)throw Error('描画が未完了');
 for(const [id,rows] of [['order-table',r.orders],['trade-table',r.trades]])if(document.querySelectorAll('#'+id+' tbody tr').length!==rows.length)throw Error('表の全件');
 if(!r.votes.length||!r.votes.every(v=>v.length===6))throw Error('4方向帯');
 const description=document.getElementById('method-description').textContent;
 if(r.signal==='S100'&&!description.includes('中央1.0倍だけ'))throw Error('中央単一');
 if(r.signal==='M2_100'&&!description.includes('同方向2票以上'))throw Error('3窓合議');
 const canvas=document.getElementById('chart'),ctx=canvas.getContext('2d'),pixel=Array.from(ctx.getImageData(0,0,1,1).data);
 if(pixel.join(',')!=='13,24,39,255')throw Error('暗色背景');
 for(const details of document.querySelectorAll('details'))details.open=false;
 document.body.dataset.probe=JSON.stringify({全合格:true,手法:method,セッション:session,銘柄:'TOPIX',
  注文数:r.orders.length,返済数:r.trades.length,減量数:r.orders.filter(o=>o[7]===30).length,
  復元数:r.orders.filter(o=>o[7]===31).length,方向帯数:4,票変更記録数:r.votes.length,
  説明:description,表示:document.getElementById('chart-summary').textContent,図背景:pixel});
}catch(error){document.body.dataset.probe=JSON.stringify({全合格:false,理由:String(error)})}})();
'''


def main() -> None:
    """機能: 正式104図の完備後、2例画像を生成する。目視フラグは後で追記する。

    引数: なし。返り値: なし (None)。正式HTML・売買規則は変更しない。
    """
    complete=report.read(HERE/'完備監査.json');assert complete['全合格']
    audited=report.read(HERE/'chart_browser_audit.json');assert audited['全合格'] and audited['全画面数']==104
    page=report.OUT/'５分足と売買.html';before=report.digest(page);assert before==audited['HTML_SHA256']
    source=page.read_text(encoding='utf-8');items=[]
    browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    for number,(method,session) in enumerate(CASES):
        probe=HERE/f'chart_visual_{number}.html';picture=HERE/f'chart_visual_{number}.png'
        script=PROBE.replace('METHOD',json.dumps(method)).replace('SESSION',json.dumps(session))
        probe.write_text(source.replace('</body>','<script>'+script+'</script></body>'),encoding='utf-8')
        command=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
            '--disable-background-networking','--disable-component-update','--disable-sync','--disable-default-apps',
            '--disable-features=MediaRouter,OptimizationHints','--proxy-server=http://127.0.0.1:9',
            '--hide-scrollbars','--window-size=1440,1700','--virtual-time-budget=2500',
            '--user-data-dir='+str(HERE/f'chart_visual_browser_{number}'),'--screenshot='+str(picture),'--dump-dom',probe.as_uri()]
        result=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,result.stderr[-1500:]
        document=BeautifulSoup(result.stdout.decode('utf-8',errors='replace'),'html.parser')
        value=json.loads(document.body['data-probe']);assert value['全合格'],value
        assert picture.exists() and picture.stat().st_size>10000
        items.append(dict(**value,path=picture.relative_to(ROOT).as_posix(),画像=picture.name,画像SHA256=report.digest(picture)))
    assert report.digest(page)==before
    report.save(HERE/'chart_visual_check.json',dict(全合格=True,画像=items,正式HTML不変=True,HTML_SHA256=before,
        監査実装SHA256=report.digest(Path(__file__)),新売買再生=False,API取得数=0,
        外部通信='背景通信無効・不通ローカルプロキシ・内蔵データだけ'))
    print('2例の実ブラウザ画像を保存。目視確認は別途必要。',flush=True)


if __name__=='__main__':main()
