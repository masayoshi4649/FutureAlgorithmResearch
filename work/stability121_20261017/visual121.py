"""新比較と当日一分足を通信なしChromeで実描画する。"""

import json
from pathlib import Path
import subprocess
from bs4 import BeautifulSoup
from register121 import HERE,ROOT,sha,save


def main() -> None:
    """
    機能: 表示行・選択玉・Canvasの非空を確認しPC画像を保存する。
    引数: なし。完成した公開HTML二本だけを読む。
    返り値: None。売買の再実行と外部通信を行わない。
    """
    public=ROOT/'アルゴリズム調査/00121_三ポイント間隔と五ポイント追尾'
    out=HERE/'visual';out.mkdir(exist_ok=False)
    result=[]
    for kind,name in [('report','三ポイント間隔と五ポイント追尾の比較.html'),('chart','2026-09-24_Dayの1分足と売買.html')]:
        path=public/name;raw=path.read_bytes();folder=out/kind;folder.mkdir()
        probe='''<script>
/**
 * 機能: 描画済み画面の行数と一分足の約定表示を確認する。
 * 引数: なし。
 * 返り値: body属性のJSONへ確認結果を残す。
 */
try{
 let detail={};
 if(document.getElementById('chart-data')){
  const d=JSON.parse(document.getElementById('chart-data').textContent).symbols.TOPIX;
  if(!window.chartViewReady||window.chartRenderedKey!=='TOPIX')throw Error('描画未完了');
  if(window.chartShownCandles!==415||window.chartShownMarkers!==2*d.groups.length)throw Error('足又は約定数');
  if(!document.getElementById('selected').textContent.includes('-91,002')&& !document.getElementById('summary').textContent.includes('-91,002'))throw Error('当日収支');
  const i=Number(document.getElementById('lot').value);if(!d.groups[i].uids.includes(1))throw Error('初回玉');
  const c=document.getElementById('price'),a=c.getContext('2d').getImageData(0,0,c.width,c.height).data,s=new Set();
  for(let i=0;i<a.length;i+=400)s.add(a[i]+','+a[i+1]+','+a[i+2]);if(s.size<5)throw Error('空Canvas');
  detail={candles:window.chartShownCandles,markers:window.chartShownMarkers,lots:d.lot_count,selected:d.groups[i].uids};
 }else{
  const t=document.querySelectorAll('table');if(t.length!==3||t[2].querySelectorAll('tbody tr').length!==40)throw Error('比較表行数');
  if(!document.body.innerText.includes('-91,002')||!document.body.innerText.includes('-2,531,804'))throw Error('表示円');
  detail={tables:t.length,sessions:t[2].querySelectorAll('tbody tr').length};
 }
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('文書横溢れ');
 if(document.body.innerText.includes('undefined')||document.body.innerText.includes('NaN'))throw Error('未定義表示');
 document.body.dataset.qa=JSON.stringify({passed:true,innerWidth,documentWidth:document.documentElement.scrollWidth,detail});
}catch(e){document.body.dataset.qa=JSON.stringify({passed:false,error:String(e)});}
</script>'''
        target=folder/'描画用.html';target.write_bytes(raw.replace(b'</body>',probe.encode('utf-8')+b'</body>'))
        image=folder/'画面.png'
        command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu',
            '--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync',
            '--proxy-server=http://127.0.0.1:9','--window-size=1420,1200','--virtual-time-budget=1500',
            '--user-data-dir='+str(folder/'profile'),'--screenshot='+str(image),'--dump-dom',target.as_uri()]
        process=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
        assert process.returncode==0,process.stderr[-1000:]
        soup=BeautifulSoup(process.stdout.decode('utf-8',errors='replace'),'html.parser')
        check=json.loads(soup.body['data-qa']);assert check['passed'],check
        assert path.read_bytes()==raw and image.stat().st_size>10000
        result.append(dict(kind=kind,html_sha256=sha(path),image=str(image.relative_to(ROOT)),**check))
    save(out/'PC二画面の描画確認.json',dict(passed=True,result=result,root_viewed=False,financial_replay=0))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
