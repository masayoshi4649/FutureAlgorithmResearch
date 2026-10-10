"""主の二試行突破と、試行を待たない価格対照を暗色の図で確認する。"""

from pathlib import Path
import hashlib
import json
import subprocess

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PAGE=ROOT/'アルゴリズム調査/00035_同じ価格帯の防御変化と突破/５分足と売買.html'
CASES=(('B00','2026-09-25_Night'),('B11','2026-09-22_Day'))
PROBE='''
/**
 * 機能: 二試行突破と先行突破の指定2例を表示し、全台帳と帯の表を確認する。
 * 引数: 埋込の手法とセッション名(str)。返り値: body診断属性へ確認結果を保存する。
 */
(()=>{try{
 const method=METHOD,session=SESSION;window.chartSelect(method,'TOPIX',session);
 const key=method+'|'+session+'|TOPIX';
 const data=JSON.parse(document.getElementById('chart-data').textContent),r=data.records[key];
 if(window.chartRenderedKey!==key||!window.chartViewReady)throw Error('描画が未完了');
 const summary=document.getElementById('chart-summary').textContent;
 if(r.training||summary.includes('学習専用'))throw Error('学習除外を誤表示');
 if(!r.bands.length||!r.trades.length)throw Error('指定例に帯又は返済がない');
 for(const [id,rows] of [['order-table',r.orders],['trade-table',r.trades],['band-table',r.bands]]){
  if(document.querySelectorAll('#'+id+' tbody tr').length!==rows.length)throw Error('表の全件 '+id);
 }
 const complete=r.bands.filter(b=>b.trials.length===2&&b.trials.every(t=>t.complete)).length;
 const incomplete=r.bands.filter(b=>b.trials.length<2||b.trials.some(t=>!t.complete)).length;
 if(method==='B00'&&complete!==r.bands.length)throw Error('主の確定試行が欠落');
 if(method==='B11'&&!incomplete)throw Error('価格対照の未完試行例がない');
 const canvas=document.getElementById('chart'),ctx=canvas.getContext('2d');
 const pixel=Array.from(ctx.getImageData(0,0,1,1).data);
 if(pixel.slice(0,3).join(',')!=='13,24,39')throw Error('図の暗色');
 document.body.dataset.probe=JSON.stringify({成功:true,手法:method,セッション:session,帯数:r.bands.length,
  二試行完了帯数:complete,未完試行帯数:incomplete,注文数:r.orders.length,返済数:r.trades.length,
  収支円:r.totals.net_yen,表示:summary,図背景:pixel});
}catch(error){document.body.dataset.probe=JSON.stringify({成功:false,理由:String(error)})}})();
'''


def main() -> None:
    """機能: 正式HTMLを変更せず、2例の画像と全表示状態を保存する。

    引数: なし。返り値: なし(None)。外部通信と取引再生は行わない。
    """
    browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    before=hashlib.sha256(PAGE.read_bytes()).hexdigest();source=PAGE.read_text(encoding='utf-8');items=[]
    for i,(method,session) in enumerate(CASES):
        probe=HERE/f'report_chart_{i}.html';picture=HERE/f'report_chart_{i}.png'
        script=PROBE.replace('METHOD',json.dumps(method)).replace('SESSION',json.dumps(session))
        probe.write_text(source.replace('</body>','<script>'+script+'</script></body>'),encoding='utf-8')
        command=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
            '--disable-background-networking','--disable-component-update','--disable-sync','--disable-default-apps',
            '--disable-features=MediaRouter,OptimizationHints','--proxy-server=http://127.0.0.1:9',
            '--hide-scrollbars','--window-size=1440,1400','--virtual-time-budget=2500',
            '--user-data-dir='+str(HERE/f'report_chart_browser_{i}'),'--screenshot='+str(picture),'--dump-dom',probe.as_uri()]
        result=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,result.stderr[-1500:]
        document=BeautifulSoup(result.stdout.decode('utf-8',errors='replace'),'html.parser')
        value=json.loads(document.body['data-probe']);assert value['成功'],value
        assert picture.is_file() and picture.stat().st_size>10000
        items.append(dict(**value,画像=picture.name,path=picture.relative_to(ROOT).as_posix(),画像SHA256=hashlib.sha256(picture.read_bytes()).hexdigest()))
    assert before==hashlib.sha256(PAGE.read_bytes()).hexdigest()
    evidence=dict(全合格=True,画像=items,正式HTML不変=True,HTML_SHA256=before,
        監査実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),新売買再生=False,
        外部通信='ローカル内蔵データのみ・背景通信無効・不通プロキシ')
    (HERE/'chart_visual_check.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':main()
