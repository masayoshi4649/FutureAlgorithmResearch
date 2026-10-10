"""全104画面の切替と、事前に決めた3画面の暗色描画をローカルで確認する。"""

import hashlib
import json
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
OUT=HERE.parents[1]/'アルゴリズム調査/00031_出来高通過と気配維持からの方向判定'
TARGETS=[('Q034__V000','TOPIX','2026-09-22_Night'),
         ('Q034__V000','NK225','2026-09-22_Night'),
         ('H019__V000','TOPIX','2026-09-29_Day')]
PROBE='''
/**
 * 固定4方式の全画面を切り替え、全返済・準備参考・収支・描画を検査する。
 * 引数: なし。
 * 返り値: なし (undefined)。売買再生と外部通信は行わない。
 */
(()=>{try{
 const data=JSON.parse(document.getElementById('chart-data').textContent);
 const method=document.getElementById('method'),symbol=document.getElementById('symbol'),session=document.getElementById('session');
 let count=0;
 for(const id of Object.keys(data.methods))for(const code of ['TOPIX','NK225'])for(const day of data.sessions){
  method.value=id;symbol.value=code;session.value=day;method.dispatchEvent(new Event('change'));
  const key=[id,day,code].join('|'),rows=data.trades[key],net=rows.reduce((v,r)=>v+r[6],0);
  const wanted=(net>0?'+':'')+net.toLocaleString('ja-JP')+'円';
  if(!document.getElementById('chart-summary').textContent.includes(wanted))throw Error('収支不一致 '+key);
  if(document.querySelectorAll('#trade-table tbody tr').length!==rows.length)throw Error('返済欠落 '+key);
  if(document.querySelectorAll('#episode-table tbody tr').length!==data.episodes[key].length)throw Error('価格準備欠落 '+key);
  count++;
 }
 const target=TARGET;
 method.value=target[0];symbol.value=target[1];session.value=target[2];method.dispatchEvent(new Event('change'));
 const key=[method.value,session.value,symbol.value].join('|'),rows=data.trades[key];
 const canvas=document.getElementById('chart'),g=canvas.getContext('2d'),pixels=g.getImageData(0,0,canvas.width,canvas.height).data;
 let markers=0;
 for(let i=0;i<pixels.length;i+=4)if(pixels[i]===255&&pixels[i+1]===223&&pixels[i+2]===124)markers++;
 if(rows.length&&!markers)throw Error('返済マーカーが見えない');
 const bg=Array.from(g.getImageData(0,0,1,1).data);
 if(bg.slice(0,3).join(',')!=='12,21,34')throw Error('暗色背景不一致');
 if(data.entry_episode_attribution!==false)throw Error('初回準備への帰属をしている');
 document.querySelectorAll('details').forEach(e=>e.open=false);
 document.body.dataset.probe=JSON.stringify({成功:true,全選択数:count,手法:method.value,銘柄:symbol.value,
  セッション:session.value,表示収支:document.getElementById('chart-summary').textContent,
  返済件数:rows.length,価格準備件数:data.episodes[key].length,返済描画画素数:markers,暗色背景:bg});
}catch(e){document.body.dataset.probe=JSON.stringify({成功:false,エラー:String(e)})}})();
'''


def main() -> None:
    """機能: 専用ヘッドレス領域で全画面を確認し、3画像と操作証拠を保存する。

    引数: なし。返り値: なし (None)。元HTML・条件・台帳を変更しない。
    """
    path=OUT/'５分足と売買.html';source=path.read_text(encoding='utf-8')
    before=hashlib.sha256(path.read_bytes()).hexdigest();results=[]
    browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    for index,target in enumerate(TARGETS):
        script=PROBE.replace('TARGET',json.dumps(target))
        probe=HERE/f'表示操作_{index}.html'
        probe.write_text(source.replace('</body>','<script>'+script+'</script></body>'),encoding='utf-8')
        image=HERE/f'表示検査_{index}.png'
        command=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
            '--disable-background-networking','--disable-component-update','--disable-sync','--disable-default-apps',
            '--disable-features=MediaRouter,OptimizationHints','--proxy-server=http://127.0.0.1:9',
            '--hide-scrollbars','--window-size=1440,1250','--virtual-time-budget=2500',
            '--user-data-dir='+str(HERE/f'browser_chart_{index}'),'--screenshot='+str(image),'--dump-dom',probe.as_uri()]
        run=subprocess.run(command,capture_output=True,timeout=50,creationflags=subprocess.CREATE_NO_WINDOW)
        assert run.returncode==0,run.stderr[-1500:]
        dom=run.stdout.decode('utf-8',errors='replace')
        (HERE/f'描画後DOM_{index}.html').write_text(dom,encoding='utf-8')
        document=BeautifulSoup(dom,'html.parser');tested=json.loads(document.body['data-probe'])
        assert tested['成功'] and tested['全選択数']==104,tested
        assert [tested['手法'],tested['銘柄'],tested['セッション']]==list(target)
        assert image.exists() and image.stat().st_size>10000
        results.append(dict(**tested,画像=image.name,画像SHA256=hashlib.sha256(image.read_bytes()).hexdigest()))
    assert before==hashlib.sha256(path.read_bytes()).hexdigest()
    value=dict(全操作合格=True,各描画で全104選択=True,事前固定の描画=results,原本HTML不変=True,
        HTML_SHA256=before,監査実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        売買再生=False,現在保存物使用=False,API取得数=0,外部通信='資料内蔵・背景通信無効・不通プロキシ')
    (HERE/'chart_visual_check.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(value,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
