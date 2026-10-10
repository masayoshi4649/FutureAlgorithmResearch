"""正式図を実Chromeで全104選択し、表示根拠と暗色描画を検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PAGE = ROOT/'アルゴリズム調査/00040_50パーセント減量版の反証/５分足と売買.html'
PROBE = '''
/**
 * 機能: 実DOMの選択変更イベントを発生させ、全104画面を検査する。
 * 引数: なし。
 * 返り値: body診断属性のJSON。正式HTMLは編集しない。
 */
(() => {try {
 const d=JSON.parse(document.getElementById('chart-data').textContent),results=[];
 const method=document.getElementById('method'),symbol=document.getElementById('symbol'),session=document.getElementById('session');
 if(Object.keys(d.methods).length!==3||d.sessions.length!==13)throw Error('方式又はセッション数');
 const change=(element,value)=>{element.value=value;element.dispatchEvent(new Event('change',{bubbles:true}));};
 for(const m of Object.keys(d.methods))for(const k of d.sessions)for(const s of ['TOPIX','NK225']){
   change(method,m);change(session,k);change(symbol,s);
   const key=m+'|'+k+'|'+s,r=d.records[key];
   if(window.chartRenderedKey!==key||!window.chartViewReady)throw Error('選択又は描画未完');
   for(const [id,rows] of [['order-table',r.orders],['trade-table',r.trades],['arm-table',r.arms]]){
     if(document.querySelectorAll('#'+id+' tbody tr').length!==rows.length)throw Error('表行数不一致 '+id);
   }
   const summary=document.getElementById('chart-summary').textContent;
   if(summary.includes('学習専用')||summary.includes('暫定'))throw Error('正式化又は学習除外');
   if(!summary.includes(d.methods[m])||!summary.includes(r.totals.net_yen.toLocaleString('ja-JP')+'円'))throw Error('円収支表示');
   const description=document.getElementById('method-description').textContent;
   if(m.startsWith('G150_')&&!description.includes('さらに新しいB00'))throw Error('到達と約定の区別');
 if(m.includes('F50')&&!description.includes('残存枠50%'))throw Error('50%の方式説明');
 if(m.includes('F25')&&!description.includes('残存枠25%'))throw Error('25%の方式説明');
   const c=document.getElementById('chart'),ctx=c.getContext('2d'),pixel=Array.from(ctx.getImageData(0,0,1,1).data);
   if(pixel.join(',')!=='13,24,39,255')throw Error('図背景不正');
   const image=ctx.getImageData(0,0,c.width,c.height).data,colors=new Set();
   for(let i=0;i<image.length;i+=160)colors.add([image[i],image[i+1],image[i+2]].join(','));
   if(colors.size<5)throw Error('描画が空');
   results.push({id:m,session:k,symbol:s,全合格:true,orders:r.orders.length,trades:r.trades.length,到達数:r.arms.length,基準線数:r.levels.length,収支円:r.totals.net_yen});
 }
 document.body.dataset.probe=JSON.stringify({全合格:true,全画面数:results.length,結果:results});
}catch(error){document.body.dataset.probe=JSON.stringify({全合格:false,理由:String(error)})}})();
'''


def sha(path: Path) -> str:
    """機能: 表示資料が変わっていないことを検査する指紋を作る。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: 通信を無効にした実ブラウザで全選択を行い証跡を保存する。

    引数: なし。返り値: なし (None)。売買・新データ取得は実行しない。
    """
    complete=json.loads((HERE/'完備監査.json').read_text(encoding='utf-8'))
    assert complete['全合格']
    audit=json.loads((HERE/'chart_audit.json').read_text(encoding='utf-8'))
    assert audit['全合格'] and audit['全図示数']==104
    before=sha(PAGE);assert before==audit['HTML_SHA256']
    probe=HERE/'chart_browser_probe.html'
    probe.write_text(PAGE.read_text(encoding='utf-8').replace('</body>','<script>'+PROBE+'</script></body>'),encoding='utf-8')
    browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    command=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
        '--disable-background-networking','--disable-component-update','--disable-sync','--disable-default-apps',
        '--disable-features=MediaRouter,OptimizationHints','--proxy-server=http://127.0.0.1:9',
        '--window-size=1440,1400','--virtual-time-budget=5000',
        '--user-data-dir='+str(HERE/'chart_browser_profile'),'--dump-dom',probe.as_uri()]
    result=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stderr[-1500:]
    parsed=BeautifulSoup(result.stdout.decode('utf-8',errors='replace'),'html.parser')
    evidence=json.loads(parsed.body['data-probe'])
    assert evidence['全合格'] and evidence['全画面数']==104,evidence
    assert before==sha(PAGE)
    evidence.update(正式HTML不変=True,HTML_SHA256=before,表示監査SHA256=sha(HERE/'chart_audit.json'),
        実装SHA256=sha(Path(__file__)),新売買再生=False,API取得数=0,現在保存物使用=False,
        ブラウザ='Chrome headlessの実canvas/DOM。select changeイベントを全104組合せへ発行',
        外部通信='背景通信無効・不通ローカルプロキシ・内蔵データのみ',画像の目視='別の2例画像監査で実施')
    (HERE/'chart_browser_audit.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(dict(全合格=True,全画面数=104,正式HTML不変=True),flush=True)


if __name__=='__main__':
    main()
