"""図の最新区間と学習専用区間を表示し、注文と数量の見え方を確認する。"""

from pathlib import Path
import hashlib
import json
import subprocess

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PAGE=ROOT/'アルゴリズム調査/00034_予想外の板圧力と独立価格対照/５分足と売買.html'
SESSIONS=('2026-09-29_Day','2026-09-21_Day')
PROBE='''
/**
 * 機能: 事前指定の最新日中と学習専用区間を切り替えて確認する。
 * 引数: 埋込セッション名(str)。返り値: bodyの診断属性へ確認結果を保存する。
 */
(()=>{try{
 const session=SESSION;window.chartSelect('I00','TOPIX',session);
 const key='I00|'+session+'|TOPIX',data=JSON.parse(document.getElementById('chart-data').textContent),r=data.records[key];
 if(window.chartRenderedKey!==key||!window.chartViewReady)throw Error('描画が未完了');
 const summary=document.getElementById('chart-summary').textContent;
 if(summary.includes('学習専用・取引0')!==r.training)throw Error('学習表示');
 if(r.training&&(r.orders.length||r.trades.length||r.totals.net_yen))throw Error('学習に取引');
 for(const [id,rows] of [['order-table',r.orders],['trade-table',r.trades]]){
  const shown=document.querySelectorAll('#'+id+' tbody tr').length;
  if(shown!==rows.length)throw Error('台帳数 '+id);
 }
 const canvas=document.getElementById('chart'),ctx=canvas.getContext('2d'),pixel=Array.from(ctx.getImageData(0,0,1,1).data);
 if(pixel.slice(0,3).join(',')!=='13,24,39')throw Error('図の暗色');
 document.body.dataset.probe=JSON.stringify({成功:true,対象:session,学習専用:r.training,注文数:r.orders.length,返済数:r.trades.length,収支円:r.totals.net_yen,表示:summary,図背景:pixel});
}catch(error){document.body.dataset.probe=JSON.stringify({成功:false,理由:String(error)})}})();
'''


def main() -> None:
    """機能: 正式HTMLを変更せず、2つの暗色画像と状態証拠を保存する。

    引数: なし。返り値: なし(None)。取引再生・外部データ取得はしない。
    """
    browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    before=hashlib.sha256(PAGE.read_bytes()).hexdigest();source=PAGE.read_text(encoding='utf-8');items=[]
    for i,session in enumerate(SESSIONS):
        probe=HERE/f'report_chart_{i}.html';picture=HERE/f'report_chart_{i}.png'
        probe.write_text(source.replace('</body>','<script>'+PROBE.replace('SESSION',json.dumps(session))+'</script></body>'),encoding='utf-8')
        command=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
            '--disable-background-networking','--disable-component-update','--disable-sync','--disable-default-apps',
            '--disable-features=MediaRouter,OptimizationHints','--proxy-server=http://127.0.0.1:9',
            '--hide-scrollbars','--window-size=1440,1400','--virtual-time-budget=2500',
            '--user-data-dir='+str(HERE/f'report_chart_browser_{i}'),'--screenshot='+str(picture),'--dump-dom',probe.as_uri()]
        result=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,result.stderr[-1500:]
        document=BeautifulSoup(result.stdout.decode('utf-8',errors='replace'),'html.parser')
        value=json.loads(document.body['data-probe']);assert value['成功'],value
        assert value['学習専用']==(i==1)
        assert picture.is_file() and picture.stat().st_size>10000
        items.append(dict(**value,画像=picture.name,画像SHA256=hashlib.sha256(picture.read_bytes()).hexdigest()))
    assert before==hashlib.sha256(PAGE.read_bytes()).hexdigest()
    evidence=dict(全合格=True,表示2例=items,正式HTML不変=True,HTML_SHA256=before,
        監査実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),新売買再生=False,
        外部通信='ローカル内蔵データのみ・背景通信無効・不通プロキシ')
    (HERE/'report_chart_visual.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':main()
