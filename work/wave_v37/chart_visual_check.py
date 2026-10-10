"""全156画面の操作と、固定3画面の暗色描画を外部通信なしで確認する。"""

from pathlib import Path
import hashlib
import json
import subprocess

from bs4 import BeautifulSoup

import chart_slot_design as design

HERE = Path(__file__).resolve().parent
TARGETS = [('H019__B06_RB06_F50_N1__V000','TOPIX','2026-09-22_Night'),
           ('H019__B06_T120_F50_N1__V000','NK225','2026-09-24_Day'),
           ('H019__SMALL50__V000','TOPIX','2026-09-29_Day')]
PROBE = '''
/**
 * 固定6方式の全156画面で全注文・返済・根拠・損益と暗色描画を確認する。
 * 引数: なし。
 * 返り値: なし (undefined)。資料内の保存値以外は取得しない。
 */
(()=>{try{
 const data=JSON.parse(document.getElementById('chart-data').textContent);
 const method=document.getElementById('method'),symbol=document.getElementById('symbol'),session=document.getElementById('session');
 let count=0;
 for(const id of Object.keys(data.methods))for(const code of ['TOPIX','NK225'])for(const day of data.sessions){
  method.value=id;symbol.value=code;session.value=day;method.dispatchEvent(new Event('change'));
  const key=[id,day,code].join('|'),trades=data.trades[key],orders=data.orders[key],adjustments=data.adjustments[key];
  const net=trades.reduce((v,r)=>v+r[6],0),wanted=(net>0?'+':'')+net.toLocaleString('ja-JP',{maximumFractionDigits:2})+'円';
  if(!document.getElementById('chart-summary').textContent.includes(wanted))throw Error('収支 '+key);
  if(document.querySelectorAll('#trade-table tbody tr').length!==trades.length)throw Error('返済 '+key);
  if(document.querySelectorAll('#order-table tbody tr').length!==orders.length)throw Error('注文 '+key);
  if(document.querySelectorAll('#adjustment-table tbody tr').length!==adjustments.length)throw Error('操作 '+key);
  if(!window.chartViewReady||window.chartRenderedKey!==key)throw Error('表示更新 '+key);
  for(const id of ['order-table','trade-table','adjustment-table'])if(document.getElementById(id).textContent.includes('undefined'))throw Error('名称欠落 '+key);
  count++;
 }
 const target=TARGET;method.value=target[0];symbol.value=target[1];session.value=target[2];method.dispatchEvent(new Event('change'));
 const canvas=document.getElementById('chart'),g=canvas.getContext('2d'),bg=Array.from(g.getImageData(0,0,1,1).data);
 if(bg.slice(0,3).join(',')!=='12,21,34')throw Error('暗色背景');
 const pixels=g.getImageData(0,0,canvas.width,canvas.height).data;let markerPixels=0;
 for(let i=0;i<pixels.length;i+=4)if((pixels[i]===255&&pixels[i+1]===224&&pixels[i+2]===128)||(pixels[i]===99&&pixels[i+1]===220&&pixels[i+2]===255)||(pixels[i]===255&&pixels[i+1]===172&&pixels[i+2]===102))markerPixels++;
 if(!markerPixels)throw Error('売買マーカーなし');
 document.querySelectorAll('details').forEach(e=>e.open=false);
 document.body.dataset.probe=JSON.stringify({成功:true,全選択数:count,対象:target,表示収支:document.getElementById('chart-summary').textContent,売買画素数:markerPixels,暗色背景:bg});
}catch(e){document.body.dataset.probe=JSON.stringify({成功:false,エラー:String(e)})}})();
'''


def main() -> None:
    """機能: 専用ヘッドレス領域で全画面を操作し3画像と証拠を保存する。

    引数: なし。返り値: なし(None)。元資料と台帳は変更しない。
    """
    path=design.OUT/'５分足と売買.html'; source=path.read_text(encoding='utf-8')
    before=hashlib.sha256(path.read_bytes()).hexdigest(); results=[]
    browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    for index,target in enumerate(TARGETS):
        probe=HERE/f'表示操作_{index}.html'; image=HERE/f'表示検査_{index}.png'
        probe.write_text(source.replace('</body>','<script>'+PROBE.replace('TARGET',json.dumps(target))+'</script></body>'),encoding='utf-8')
        command=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
            '--disable-background-networking','--disable-component-update','--disable-sync','--disable-default-apps',
            '--disable-features=MediaRouter,OptimizationHints','--proxy-server=http://127.0.0.1:9',
            '--hide-scrollbars','--window-size=1440,1250','--virtual-time-budget=2500',
            '--user-data-dir='+str(HERE/f'browser_chart_{index}'),'--screenshot='+str(image),'--dump-dom',probe.as_uri()]
        result=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,result.stderr[-1500:]
        document=BeautifulSoup(result.stdout.decode('utf-8',errors='replace'),'html.parser')
        value=json.loads(document.body['data-probe']);assert value['成功'] and value['全選択数']==156,value
        assert value['対象']==list(target) and image.exists() and image.stat().st_size>10000
        results.append(dict(**value,画像=image.name,画像SHA256=hashlib.sha256(image.read_bytes()).hexdigest()))
    assert before==hashlib.sha256(path.read_bytes()).hexdigest()
    value=dict(全操作合格=True,各描画で全156選択=True,固定描画例=results,HTML_SHA256=before,
        監査実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),API取得数=0,新売買再生=False,
        外部通信='内蔵資料のみ。背景通信無効・不通プロキシ。')
    (HERE/'chart_visual_check.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
