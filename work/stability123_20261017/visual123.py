"""暗色比較表と全十九条件・四十場の実描画を独立に確認する。"""

from datetime import datetime,timedelta,timezone
import argparse
import json
import statistics
import subprocess
from bs4 import BeautifulSoup
from register123 import HERE,ROOT,read,save,sha


def money(value: float,signed: bool=False) -> str:
    """
    機能: 表示照合に使う整数円の期待文字列を独立に作る。
    引数: value(float)は保存済み円額、signed(bool)は正数へ符号を付けるか。
    返り値: strは桁区切りと必要な符号を伴う円額。
    """
    assert int(value)==value
    return '0' if value==0 else format(int(value),'+,d' if signed else ',d')


def main(expected: str) -> None:
    """
    機能: 実Chromeで全十九表の切替と各四十行の金額・枚数・代理時計を確認する。
    引数: expected(str)は根と表示生成者が固定した公開HTMLのSHA256。
    返り値: None。公開源を変えず、私有描画用copyと画像・確認JSONを保存する。
    """
    path=ROOT/'アルゴリズム調査/00123_途中利確なしの新規間隔比較/途中利確なしの新規間隔比較.html'
    assert sha(path)==expected
    resultpath=HERE/'途中利確なしの十九間隔と全四十場.json'
    assert sha(resultpath)=='91475e3757d4a9462f1ecc9405c43e76145967693b0802c56e73068dd0db416c'
    d=read(resultpath);base={r['session']:r for r in d['baseline']['rows']};cases=[];overview=[]
    jst=timezone(timedelta(hours=9));raw=path.read_bytes()
    for spec in d['specs']:
        rows=d['baseline']['rows'] if spec['reused'] else [r for r in d['runs'] if r['method']==spec['id']]
        lookup={r['session']:r for r in rows};rows=[lookup[s] for s in d['sessions']]
        nets=[r['net'] for r in rows];p=sum(v>0 for v in nets);n=sum(v<0 for v in nets);inactive=sum(r['entries']==0 for r in rows)
        flat=sum(r['entries']>0 and r['net']==0 for r in rows)
        count=f'{p}/{n}/{inactive}'+(f'・零{flat}' if flat else '')
        overview.append([spec['id']+('（保存）' if spec['reused'] else ''),f"{spec['initial']:g}",f"{spec['spacing']:g}",count,
            money(sum(nets),True),money(statistics.median(nets),True),money(max(0,-min(nets))),str(int(sum(r['entries'] for r in rows)))])
        daily=[]
        for r in rows:
            c=r['context'];baseline=base[r['session']]['net']
            daily.append([r['session'],money(r['profit']),money(r['loss']),money(r['net'],True),str(int(r['entries'])),
                f"{int(r['wins'])}/{int(r['losses'])}/{int(r['entries']-r['wins']-r['losses'])}",money(baseline,True),money(r['net']-baseline,True),
                datetime.fromtimestamp(c['reference_time'],jst).strftime('%H:%M:%S'),f"{c['age_seconds']:g}"])
        cases.append(dict(id=spec['id'],rows=daily,net=money(sum(nets),True),quantity=str(int(sum(r['entries'] for r in rows)))))
    expectation=json.dumps(dict(overview=overview,cases=cases),ensure_ascii=False,separators=(',',':'))
    probe='''<script>
/**
 * 機能: 全十九条件の静的金額・数量と表示切替を独立期待値へ照合する。
 * 引数: なし。期待値は完成会計から作った固定JSON。
 * 返り値: なし。body属性へ合否を保存する。
 */
try{
 const expected=__EXPECTED__;
 const check=(v,m)=>{if(!v)throw Error(m)};
 const cells=row=>Array.from(row.children,x=>x.innerText.trim());
 const same=(a,b,label)=>check(JSON.stringify(a)===JSON.stringify(b),label);
 const selection=document.querySelector('#condition');
 check(selection.value==='I3_G3','既定条件が基準ではない');
 check(selection.options.length===19,'十九選択肢不足');
 same(Array.from(document.querySelectorAll('#overview tbody tr'),cells),expected.overview,'十九一覧の値');
 let checked=0;
 for(const item of expected.cases){
   selection.value=item.id;selection.dispatchEvent(new Event('change'));
   const visible=Array.from(document.querySelectorAll('.case')).filter(p=>!p.hidden);
   check(visible.length===1&&visible[0].dataset.id===item.id,'選択と表示の不一致 '+item.id);
   const panel=visible[0];
   same(Array.from(panel.querySelectorAll('tbody tr'),cells),item.rows,'四十場の値 '+item.id);
   const total=cells(panel.querySelector('tfoot tr'));
   check(total[3]===item.net&&total[4]===item.quantity,'合計収支又は枚数 '+item.id);
   checked+=item.rows.length;
 }
 selection.value='I3_G3';selection.dispatchEvent(new Event('change'));
 check(document.documentElement.scrollWidth<=innerWidth+2,'文書横溢れ');
 const visibleText=document.body.innerText;
 check(!visibleText.includes('undefined')&&!visibleText.includes('NaN'),'未定義表示');
 for(const word of ['15:45','06:00','代理','1,031,046','318,722'])check(visibleText.includes(word),'主要説明 '+word);
 document.body.dataset.qa=JSON.stringify({passed:true,conditions:19,checked_rows:checked,initial:'I3_G3',innerWidth,documentWidth:document.documentElement.scrollWidth,background:getComputedStyle(document.body).backgroundColor});
}catch(e){document.body.dataset.qa=JSON.stringify({passed:false,error:String(e)});}
</script>'''.replace('__EXPECTED__',expectation)

    # ----------------------------------------
    # 公開HTMLは不変のまま、通信を遮った専用描画copyを実ブラウザで開く。
    out=HERE/'visual';out.mkdir(exist_ok=False)
    target=out/'描画用.html';target.write_bytes(raw.replace(b'</body>',probe.encode('utf-8')+b'</body>'))
    image=out/'画面.png'
    command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu',
        '--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync',
        '--proxy-server=http://127.0.0.1:9','--window-size=1420,1800','--virtual-time-budget=1500',
        '--user-data-dir='+str(out/'profile'),'--screenshot='+str(image),'--dump-dom',target.as_uri()]
    process=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode==0,process.stderr[-1000:]
    soup=BeautifulSoup(process.stdout.decode('utf-8',errors='replace'),'html.parser')
    proof=json.loads(soup.body['data-qa']);assert proof['passed'],proof
    assert sha(path)==expected and image.stat().st_size>10000
    save(out/'十九条件全七百六十行の実描画確認.json',dict(html_sha256=expected,root_viewed=False,financial_replay=0,**proof))
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--html-sha',required=True)
    main(parser.parse_args().html_sha)
