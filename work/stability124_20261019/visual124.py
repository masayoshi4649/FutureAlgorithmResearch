"""実ブラウザで全45選択・全1845場行を完成会計へ独立照合する。"""

import argparse
import json
import statistics
import subprocess
from bs4 import BeautifulSoup
from common124 import HERE,ROOT,NAME,SCENE,read,save,sha


def expected_rows(rows: list[dict],sessions: list[str]) -> list:
    """
    機能: 保存会計から表示に必要な金額と勝負枚数だけを独立に選ぶ。
    引数: rows(list[dict])は同じ手法・商品、sessions(list[str])は固定場順。
    返り値: listは場名・P/L/net・勝負枚数とIV既知状態。
    """
    lookup={r['session']:r for r in rows};assert len(lookup)==41
    return [[s,lookup[s]['profit'],lookup[s]['loss'],lookup[s]['net'],
        lookup[s].get('winning_lots',lookup[s].get('wins')),lookup[s].get('losing_lots',lookup[s].get('losses'))] for s in sessions]


def main(html_sha: str) -> None:
    """
    機能: 通信を遮ったChromeで追加一場・十二条件・全41行の切替を検査する。
    引数: html_sha(str)は独立監査後の正式公開HTMLの指紋。
    返り値: None。公開源を変えず私有画像と検査証跡を保存する。
    """
    path=ROOT/'アルゴリズム調査'/NAME/'追加セッションとオプションの検証.html';assert sha(path)==html_sha
    g=read(HERE/'grid/十二IV条件の全四十一場と旧十九条件の追加一場.json')
    e=read(HERE/'e01c/追加一場の固定少額E01二商品.json')
    old=read(ROOT/'work/stability119_20261017/v6_resume/measurement/少額E01固定二設定の追加七場と全四十場.json')
    oldgap=read(ROOT/'work/stability123_20261017/途中利確なしの十九間隔と全四十場.json')
    cases=[];summaries={};sessions=g['sessions']
    for sym in ('TOPIX','NK225'):
        summaries[sym]=[]
        for spec in g['specs']:
            rows=[r for r in g['rows'] if r['symbol']==sym and r['method']==spec['id']]
            cases.append(dict(symbol=sym,method=spec['id'],rows=expected_rows(rows,sessions)))
            nets=[r['net'] for r in rows]
            summaries[sym].append(dict(method=spec['id'],net=sum(nets),counts=[sum(v>0 for v in nets),sum(v<0 for v in nets),sum(r['entries']==0 for r in rows)],
                median=statistics.median(nets),worst=max(0,-min(nets)),quantity=sum(r['entries'] for r in rows),changed=sum(r['option_effective_changed'] for r in rows)))
        cases.append(dict(symbol=sym,method='E01',rows=expected_rows([r for r in old['rows']+e['rows'] if r['symbol']==sym],sessions)))
    gapcases=[]
    for spec in oldgap['specs']:
        initial=oldgap['baseline']['rows'] if spec['reused'] else [r for r in oldgap['runs'] if r['method']==spec['id']]
        rows=initial+[r for r in g['latest_rows'] if r['method']==spec['id']]
        gapcases.append(dict(method=spec['id'],rows=expected_rows(rows,sessions)))
    expected=dict(cases=cases,gaps=gapcases,summaries=summaries)
    probe='''<script>
/**
 * 機能: 実描画の全45選択を完成会計の金額と枚数へ照合する。
 * 引数: なし。期待値は独立に射影した固定JSON。
 * 返り値: body属性に合否を保存する。
 */
try{
const expected=__EXPECTED__;
const check=(value,label)=>{if(!value)throw Error(label)};
const val=cell=>Number(cell.innerText.trim().replaceAll(',',''));
const choose=(id,value)=>{const element=document.getElementById(id);element.value=value;element.dispatchEvent(new Event('change'));};
let rowsChecked=0;
const verifyRows=(prefix,wanted)=>{
 const rows=Array.from(document.querySelectorAll('#'+prefix+'-body tr'));
 check(rows.length===41,'全41行不足 '+prefix);
 let sums=[0,0,0,0,0];
 for(let i=0;i<41;i++){
  const r=wanted[i],cells=rows[i].children;
  const label=r[0].replace('_Day',' デイ').replace('_Night',' ナイト');
  check(cells[0].innerText.startsWith(label),'場順 '+prefix+' '+i);
  for(let j=1;j<=5;j++){check(val(cells[j])===r[j],'金額又は枚数 '+prefix+' '+i+' '+j);sums[j-1]+=r[j];}
  check(rows[i].classList.contains('new')===(i===40),'追加場の識別 '+prefix+' '+i);
 }
 const total=document.getElementById(prefix+'-total').children;
 for(let j=1;j<=5;j++)check(val(total[j])===sums[j-1],'合計 '+prefix+' '+j);
 rowsChecked+=41;
};
check(document.body.dataset.ready==='true','初期化未完了');
for(const [symbol,summary] of Object.entries(expected.summaries)){
 choose('summary-symbol',symbol);
 const rows=Array.from(document.querySelectorAll('#summary-body tr'));check(rows.length===12,'十二一覧');
 summary.forEach((r,i)=>{const c=rows[i].children;check(c[0].innerText.startsWith(r.method),'一覧順');check(val(c[1])===r.net,'累計');check(c[2].innerText.split('／').map(Number).join(',')===r.counts.join(','),'黒赤無');check(val(c[3])===r.median&&val(c[4])===r.worst&&val(c[5])===r.quantity,'中央値最悪枚数');check(parseInt(c[6].innerText)===r.changed,'経済差の分母');});
}
for(const item of expected.cases){choose('session-symbol',item.symbol);choose('session-method',item.method);verifyRows('session',item.rows);}
document.getElementById('gap-method').closest('details').open=true;
for(const item of expected.gaps){choose('gap-method',item.method);verifyRows('gap',item.rows);}
document.getElementById('gap-method').closest('details').open=false;
check(document.querySelectorAll('#latest-body tr').length===5,'追加一場の固定比較5行');
choose('summary-symbol','TOPIX');choose('session-symbol','TOPIX');choose('session-method','O00');choose('gap-method','I3_G3');
check(document.documentElement.scrollWidth<=innerWidth+2,'文書横溢れ');
check(!document.body.innerText.includes('undefined')&&!document.body.innerText.includes('NaN'),'未定義表示');
document.body.dataset.qa=JSON.stringify({passed:true,choices:45,checked_rows:rowsChecked,innerWidth,documentWidth:document.documentElement.scrollWidth,background:getComputedStyle(document.body).backgroundColor});
}catch(e){document.body.dataset.qa=JSON.stringify({passed:false,error:String(e)});}
</script>'''.replace('__EXPECTED__',json.dumps(expected,ensure_ascii=False,separators=(',',':')))

    # ----------------------------------------
    # 元HTMLは保ち、専用copyだけへ検査コードを加えて実表示する。
    raw=path.read_bytes();out=HERE/'visual';out.mkdir(exist_ok=False)
    target=out/'描画用.html';target.write_bytes(raw.replace(b'</body>',probe.encode('utf-8')+b'</body>'))
    image=out/'画面.png';chrome='C:/Program Files/Google/Chrome/Application/chrome.exe'
    command=[chrome,'--headless=new','--disable-gpu','--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync',
        '--proxy-server=http://127.0.0.1:9','--window-size=1420,1500','--virtual-time-budget=1800',
        '--user-data-dir='+str(out/'profile'),'--screenshot='+str(image),'--dump-dom',target.as_uri()]
    p=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW);assert p.returncode==0,p.stderr[-1000:]
    soup=BeautifulSoup(p.stdout.decode('utf-8',errors='replace'),'html.parser');proof=json.loads(soup.body['data-qa']);assert proof['passed'],proof
    assert proof['checked_rows']==1845 and sha(path)==html_sha and image.stat().st_size>10000
    save(out/'実描画確認.json',dict(proof,root_viewed=False,html_sha256=html_sha,financial_replay=0))
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--html-sha',required=True)
    main(parser.parse_args().html_sha)
