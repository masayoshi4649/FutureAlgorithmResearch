"""全281選択と暗色の主表を、外部通信しない表示複写で確認する。"""

from pathlib import Path
import hashlib
import json
import subprocess

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00035_同じ価格帯の防御変化と突破'
PAGES=('同じ価格帯の防御変化と突破.html','全条件損益.html')
PROBE='''
/**
 * 機能: 主表又は全281選択を操作し、表示状態と暗色を検査する。
 * 引数: なし。返り値: bodyの診断属性へ結果を保存する。
 */
(()=>{try{
 const bg=getComputedStyle(document.documentElement).backgroundColor;
 if(bg!=='rgb(11, 18, 27)')throw Error('暗色の背景が異なる');
 let count=0;const select=document.getElementById('method');
 if(select){
  if(select.options.length!==281)throw Error('選択肢数');
  for(const item of select.options){
   select.value=item.value;select.dispatchEvent(new Event('change'));
   const shown=Array.from(document.querySelectorAll('[data-method]')).filter(x=>!x.hidden);
   if(shown.length!==1||shown[0].dataset.method!==item.value)throw Error('選択違い '+item.value);
   if(shown[0].querySelectorAll('tr[data-kind="profit"]').length!==32)throw Error('2市場32期間行 '+item.value);
   if(shown[0].textContent.includes('undefined')||shown[0].textContent.includes('NaN'))throw Error('未表示値');
   count++;
  }
  select.value='B00';select.dispatchEvent(new Event('change'));
 }else{
  if(document.querySelectorAll('tr[data-kind="comparison"]').length!==24)throw Error('比較24行');
  if(document.querySelectorAll('[data-verdict]').length!==4)throw Error('採否4条件');
 }
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('全画面の横はみ出し');
 document.body.dataset.probe=JSON.stringify({成功:true,全選択数:count,背景:bg,画面横幅:innerWidth,文書横幅:document.documentElement.scrollWidth});
}catch(error){document.body.dataset.probe=JSON.stringify({成功:false,理由:String(error)})}})();
'''


def main() -> None:
    """機能: 公表資料を変更せず、2画面の描画と全選択の操作を検査する。

    引数: なし。返り値: なし(None)。画像と指紋を作業内へ保存する。
    """
    browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    results=[]
    for i,name in enumerate(PAGES):
        source=OUT/name;before=hashlib.sha256(source.read_bytes()).hexdigest()
        target=HERE/f'report_visual_{i}.html';picture=HERE/f'report_visual_{i}.png'
        target.write_text(source.read_text(encoding='utf-8').replace('</body>','<script>'+PROBE+'</script></body>'),encoding='utf-8')
        command=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
            '--disable-background-networking','--disable-component-update','--disable-sync','--disable-default-apps',
            '--disable-features=MediaRouter,OptimizationHints','--proxy-server=http://127.0.0.1:9',
            '--hide-scrollbars','--window-size=1440,1280','--virtual-time-budget=2500',
            '--user-data-dir='+str(HERE/f'report_browser_{i}'),'--screenshot='+str(picture),'--dump-dom',target.as_uri()]
        run=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
        assert run.returncode==0,run.stderr[-1500:]
        parsed=BeautifulSoup(run.stdout.decode('utf-8',errors='replace'),'html.parser')
        value=json.loads(parsed.body['data-probe']);assert value['成功'],value
        assert value['全選択数']==(281 if i else 0)
        assert before==hashlib.sha256(source.read_bytes()).hexdigest()
        assert picture.stat().st_size>10000
        results.append(dict(画面=name,HTML_SHA256=before,画像=picture.name,
            画像SHA256=hashlib.sha256(picture.read_bytes()).hexdigest(),**value))
    record=dict(全合格=True,全281選択合格=True,暗色2画面=True,結果=results,
        監査実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        外部通信='背景通信無効・不通プロキシ・ローカル内蔵資料のみ',新売買再生=False)
    (HERE/'report_visual_check.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False))


if __name__=='__main__':main()
