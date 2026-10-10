"""正式HTMLを変えず、実Chromeの描画と全32選択を検査する。"""

from pathlib import Path
import hashlib
import json
import subprocess

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00038_時間窓合議と入口の安定性'
PAGES=('時間窓合議と入口の安定性.html','全条件の損益.html')
PROBE='''
/**
 * 機能: 主表又は全32選択を実際のchangeイベントで操作する。
 * 引数: なし。返り値: bodyの診断属性へ結果を保存する。
 */
(()=>{try{
 const bg=getComputedStyle(document.documentElement).backgroundColor;
 if(bg!=='rgb(11, 18, 27)')throw Error('暗色背景が異なる');
 let count=0;const select=document.getElementById('method');const records=[];
 if(select){
  if(select.options.length!==32)throw Error('選択肢32件');
  for(const item of select.options){
   select.value=item.value;select.dispatchEvent(new Event('change'));
   const shown=Array.from(document.querySelectorAll('[data-method]')).filter(x=>!x.hidden);
   if(shown.length!==1||shown[0].dataset.method!==item.value)throw Error('選択違い '+item.value);
   const rows=Array.from(shown[0].querySelectorAll('tr[data-kind="profit"]'));
   if(rows.length!==32)throw Error('2市場32期間行 '+item.value);
   for(const symbol of ['TOPIX','NK225'])if(rows.filter(x=>x.dataset.symbol===symbol).length!==16)throw Error('各市場16行 '+item.value);
   if(rows.some(x=>x.dataset.id!==item.value))throw Error('別方式の表 '+item.value);
   if(shown[0].textContent.includes('undefined')||shown[0].textContent.includes('NaN'))throw Error('未表示値');
   records.push({id:item.value,行数:rows.length,成功:true});count++;
  }
  select.value='M2_100__A0__V000';select.dispatchEvent(new Event('change'));
 }else{
  if(document.querySelectorAll('tr[data-kind="comparison"]').length!==48)throw Error('比較48行');
  if(document.querySelectorAll('tr[data-kind="difference"]').length!==8)throw Error('差8行');
  if(document.querySelectorAll('tr[data-kind="robustness"]').length!==48)throw Error('集中48行');
  if(document.querySelectorAll('[data-verdict]').length!==10)throw Error('二出口10判定');
 }
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('全画面の横はみ出し');
 document.body.dataset.probe=JSON.stringify({成功:true,全選択数:count,背景:bg,画面横幅:innerWidth,
  文書横幅:document.documentElement.scrollWidth,全操作:records});
}catch(error){document.body.dataset.probe=JSON.stringify({成功:false,理由:String(error)})}})();
'''


def sha(path: Path) -> str:
    """機能: 公表資料・画像の不変性を内容指紋で確認する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: 外部通信しない実Chromeで2画面を描画し、全切替と画像を保存する。

    引数: なし。返り値: なし(None)。目視完了フラグは画像を実際に確認した後だけ付ける。
    """
    browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    assert browser.is_file()
    results=[]
    for i,name in enumerate(PAGES):
        source=OUT/name;before=sha(source)
        target=HERE/f'report_visual_{i}.html';picture=HERE/f'report_visual_{i}.png'
        target.write_text(source.read_text(encoding='utf-8').replace('</body>','<script>'+PROBE+'</script></body>'),encoding='utf-8')
        command=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
            '--disable-background-networking','--disable-component-update','--disable-sync','--disable-default-apps',
            '--disable-features=MediaRouter,OptimizationHints','--proxy-server=http://127.0.0.1:9',
            '--hide-scrollbars','--window-size=1440,1280','--virtual-time-budget=2500',
            '--user-data-dir='+str(HERE/f'report_browser_{i}'),'--screenshot='+str(picture),'--dump-dom',target.as_uri()]
        result=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,result.stderr[-1500:]
        parsed=BeautifulSoup(result.stdout.decode('utf-8',errors='replace'),'html.parser')
        value=json.loads(parsed.body['data-probe']);assert value['成功'],value
        assert value['全選択数']==(32 if i else 0)
        assert before==sha(source) and picture.stat().st_size>10000
        results.append(dict(画面=name,HTML_SHA256=before,画像=picture.name,画像SHA256=sha(picture),**value))
    record=dict(全合格=True,全32選択合格=True,各方式32行一致=True,暗色2画面=True,結果=results,
        目視確認済=False,監査実装SHA256=sha(Path(__file__)),正式HTML不変=True,
        外部通信='背景通信無効・不通プロキシ・ローカル内蔵資料のみ',新売買再生=False)
    (HERE/'report_visual_check.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k!='結果'},ensure_ascii=False))


if __name__=='__main__':main()
