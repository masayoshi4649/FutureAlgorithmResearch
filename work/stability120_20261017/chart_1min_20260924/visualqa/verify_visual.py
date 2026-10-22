"""公開HTMLの埋込データだけで、二画面のCanvasと表示操作を隔離描画する。"""

import hashlib
import html
import json
from pathlib import Path
import re
import subprocess

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
SOURCE=ROOT/'アルゴリズム調査/00120_段階トレーリング新規と利益玉の部分回転/2026-09-24_Dayの1分足と売買.html'
EXPECTED='1a8174b4fe4e157b68877621c1f982f771b55e1c7a76c702f3deda699a402312'
CHROME=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


def digest(value: bytes) -> str:
    """
    機能: 公開画面・所有コピー・画像を同じ内容指紋へ結び付ける。
    引数: value(bytes)は既に読んだファイル内容。
    返り値: strはSHA256。市場資料や金融結果は読まない。
    """
    return hashlib.sha256(value).hexdigest()


def probe() -> tuple[str,str]:
    """
    機能: 例外捕捉と全表示操作を、所有HTMLだけに追加する。
    引数: なし。
    返り値: tuple[str,str]はhead先頭とbody末尾へ追加する純表示検査。
    """
    capture='''<script>
/**
 * 機能: JavaScript例外とconsole.errorを検査画面内だけに記録する。
 * 引数: event(ErrorEvent|PromiseRejectionEvent)はブラウザ通知。
 * 返り値: なし。外部送信せず所有配列へ保存する。
 */
window.visualErrors=[];
window.addEventListener('error',event=>visualErrors.push(String(event.message)));
window.addEventListener('unhandledrejection',event=>visualErrors.push(String(event.reason)));
console.error=(...args)=>visualErrors.push(args.map(String).join(' '));
</script>'''
    script='''<script>
/**
 * 機能: Canvasが空でなく、足・約定・在庫の色が描かれたことを調べる。
 * 引数: id(string)はCanvasの要素ID。
 * 返り値: Objectは寸法、色数、価格及び約定用の着色画素数。
 */
function canvasEvidence(id){
 const canvas=document.getElementById(id),ctx=canvas.getContext('2d');
 const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;
 const colors=new Set();let pricePixels=0,exitPixels=0;
 for(let i=0;i<pixels.length;i+=4){
  const r=pixels[i],g=pixels[i+1],b=pixels[i+2];colors.add((r<<16)|(g<<8)|b);
  if((Math.abs(r-75)<10&&Math.abs(g-211)<10&&Math.abs(b-170)<10)||(Math.abs(r-255)<10&&Math.abs(g-125)<10&&Math.abs(b-137)<10))pricePixels++;
  if((Math.abs(r-139)<10&&Math.abs(g-200)<10&&Math.abs(b-255)<10)||(Math.abs(r-240)<10&&Math.abs(g-201)<10&&Math.abs(b-126)<10))exitPixels++;
 }
 return {width:canvas.width,height:canvas.height,colors:colors.size,pricePixels,exitPixels};
}
/**
 * 機能: 両銘柄・全範囲・各トグル・玉選択・ズームを実DOMで検査する。
 * 引数: なし。公開HTMLに埋め込まれた値とその描画操作だけを使う。
 * 返り値: なし。結果をbody属性へ保存し、最後はTOPIXのUID1全体へ戻す。
 */
window.addEventListener('load',()=>{
 const checks=[],bySymbol={};
 const verify=(value,label)=>{if(!value)throw new Error(label);checks.push(label);};
 try{
  verify(window.chartViewReady===true,'初回Canvas描画終端');
  verify(document.getElementById('symbol').value==='TOPIX'&&groups[selected].uids.includes(1),'初期TOPIX選択UID1');
  verify(document.querySelectorAll('[data-view]').length===5,'五つの範囲ボタン');
  verify(document.querySelectorAll('[data-kind]').length===4,'新規返済と買売の四トグル');
  let weightedFills=0;
  for(const [key,candles,markers] of [['TOPIX',415,252],['NK225',413,278]]){
   const selector=document.getElementById('symbol');selector.value=key;selector.dispatchEvent(new Event('change'));
   verify(window.chartRenderedKey===key&&current===DATA.symbols[key],key+'銘柄切替');
   verify(current.candles.length===candles&&window.chartShownCandles===candles,key+'全体の足数');
   verify(current.groups.length*2===markers&&window.chartShownMarkers===markers,key+'全体の集約マーカー数');
   verify(document.getElementById('lot').options.length===current.groups.length,key+'全玉選択肢');
   const fills=current.groups.reduce((n,r)=>n+2*r.quantity,0);weightedFills+=fills;
   verify(fills===current.lot_count*2,key+'集約枚数と実約定数');
   const price=canvasEvidence('price'),inventory=canvasEvidence('inventory');
   verify(price.width>100&&price.height>100&&price.colors>30&&price.pricePixels>20&&price.exitPixels>10,key+'足と約定Canvasは空でない');
   verify(inventory.width>100&&inventory.height>50&&inventory.colors>20&&inventory.pricePixels>20,key+'両在庫Canvasは空でない');
   const ranges=[];
   for(const button of document.querySelectorAll('[data-view]')){
    button.click();
    verify(button.classList.contains('active')&&document.querySelectorAll('[data-view].active').length===1,key+'範囲選択 '+button.dataset.view);
    verify(Number.isFinite(start)&&Number.isFinite(end)&&end>start&&window.chartShownCandles>0,key+'範囲に足が残る '+button.dataset.view);
    ranges.push({mode:button.dataset.view,candles:window.chartShownCandles,markers:window.chartShownMarkers,start,end});
   }
   document.querySelector('[data-view="all"]').click();
   const toggles=[];
   for(const input of document.querySelectorAll('[data-kind]')){
    const side=input.dataset.kind.endsWith('long')?1:-1;
    const hidden=current.groups.filter(r=>r.side===side).length;
    input.checked=false;input.dispatchEvent(new Event('change'));
    verify(window.chartShownMarkers===markers-hidden&&points.every(p=>p.kind!==input.dataset.kind),key+'表示を外す '+input.dataset.kind);
    toggles.push({kind:input.dataset.kind,hidden,shown:window.chartShownMarkers});
    input.checked=true;input.dispatchEvent(new Event('change'));
    verify(window.chartShownMarkers===markers,key+'表示を復帰 '+input.dataset.kind);
   }
   for(const input of document.querySelectorAll('[data-kind]')){input.checked=false;input.dispatchEvent(new Event('change'));}
   verify(window.chartShownMarkers===0&&canvasEvidence('price').pricePixels>20,key+'全約定非表示でも足は残る');
   for(const input of document.querySelectorAll('[data-kind]')){input.checked=true;input.dispatchEvent(new Event('change'));}
   const lot=document.getElementById('lot'),previous=selected;
   lot.value=(selected+1)%current.groups.length;lot.dispatchEvent(new Event('change'));
   const chosen=groups[selected],description=document.getElementById('selected').textContent;
   verify(selected!==previous&&selected===Number(lot.value),key+'別の完結玉を選択');
   verify(description.includes(chosen.entry_time)&&description.includes(chosen.exit_time)&&description.includes(num(chosen.net,true)),key+'選択玉の時刻純損益を表示');
   document.querySelector('[data-view="selected"]').click();
   verify(chosen.entry_epoch>=start&&chosen.exit_epoch<=end,key+'選択玉の新規返済が範囲内');
   document.querySelector('[data-view="all"]').click();
   const before=end-start,box=document.getElementById('price').getBoundingClientRect();
   document.getElementById('price').dispatchEvent(new WheelEvent('wheel',{deltaY:-100,clientX:box.left+box.width/2,clientY:box.top+box.height/2,bubbles:true,cancelable:true}));
   verify(end-start<before&&end-start>=600,key+'ホイールで拡大');
   const zoomed=end-start;
   document.getElementById('price').dispatchEvent(new WheelEvent('wheel',{deltaY:100,clientX:box.left+box.width/2,clientY:box.top+box.height/2,bubbles:true,cancelable:true}));
   verify(end-start>zoomed&&end-start<=before+0.001,key+'ホイールで縮小');
   bySymbol[key]={candles,markers,weightedFills:fills,price,inventory,ranges,toggles,zoom:{before,zoomed,after:end-start}};
  }
  verify(weightedFills===630,'二商品の実約定630');
  const selector=document.getElementById('symbol');selector.value='TOPIX';selector.dispatchEvent(new Event('change'));
  document.querySelector('[data-view="all"]').click();window.scrollTo(0,0);
  verify(groups[selected].uids.includes(1)&&window.chartShownCandles===415&&window.chartShownMarkers===252,'撮影前TOPIX_UID1全体へ復帰');
  verify(getComputedStyle(document.documentElement).backgroundColor==='rgb(11, 19, 32)','暗色背景');
  verify(document.documentElement.scrollWidth<=innerWidth+1,'画面の横はみ出しなし');
  verify(visualErrors.length===0,'JS例外とconsoleErrorなし');
  document.body.dataset.visualQa=JSON.stringify({passed:true,checks,bySymbol,weightedFills,selectedUIDs:groups[selected].uids,viewport:{width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth},errors:visualErrors});
 }catch(error){
  document.body.dataset.visualQa=JSON.stringify({passed:false,checks,error:String(error),stack:error.stack,errors:visualErrors});
 }
});
</script>'''
    return capture,script


def main() -> None:
    """
    機能: 指定公開HTMLを保全し、1400×1100と440×1000で実表示検査する。
    引数: なし。
    返り値: None。所有スクリーンショットと証跡だけ保存し公開内容は変更しない。
    """
    assert not (HERE/'二銘柄五範囲と玉切替及びズームの表示確認.json').exists()
    raw=SOURCE.read_bytes();assert digest(raw)==EXPECTED
    owned=HERE/'公開HTMLの同bytes保全.html';assert not owned.exists();owned.write_bytes(raw)
    document=BeautifulSoup(raw.decode('utf8'),'html.parser')
    for tag in document.select('[src],[href]'):
        value=tag.get('src',tag.get('href'))
        assert ':' not in value and (SOURCE.parent/value).is_file()
    capture,script=probe();source=raw.decode('utf8')
    assert source.count('</head>')==source.count('</body>')==1
    wrapped=source.replace('<head>','<head>'+capture,1).replace('</body>',script+'</body>',1)
    screens={}
    for label,width,height in (('desktop',1400,1100),('mobile',440,1000)):
        folder=HERE/label;assert not folder.exists();folder.mkdir()
        target=folder/'所有検査画面.html';target.write_text(wrapped,encoding='utf8')
        image=folder/'画面.png'
        command=[str(CHROME),'--headless=new','--disable-gpu','--no-first-run','--disable-background-networking',
            '--disable-component-update','--disable-sync','--proxy-server=http://127.0.0.1:9',
            '--force-device-scale-factor=1',f'--window-size={width},{height}','--virtual-time-budget=2500',
            '--user-data-dir='+str((folder/'profile').resolve()),'--screenshot='+str(image.resolve()),
            '--dump-dom',target.resolve().as_uri()]
        result=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
        (folder/'描画stderr.txt').write_bytes(result.stderr)
        assert result.returncode==0 and image.exists()
        found=re.search(r'<body\b[^>]*\bdata-visual-qa="([^"]*)"',result.stdout.decode('utf8',errors='replace'))
        assert found,'JS検査の終端なし'
        value=json.loads(html.unescape(found.group(1)))
        (folder/'DOM検査.json').write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
        assert value['passed'],value
        value.update(image_path=image.relative_to(ROOT).as_posix(),image_SHA256=digest(image.read_bytes()),requested_size=[width,height])
        screens[label]=value
    proof=dict(passed=True,source_path=SOURCE.relative_to(ROOT).as_posix(),source_SHA256=EXPECTED,
        source_unchanged=digest(SOURCE.read_bytes())==EXPECTED,screens=screens,
        script_SHA256=digest(Path(__file__).read_bytes()),HTML_only=True,market_reads=0,financial_result_reads=0,NPZ_reads=0,
        financial_replay=0,API=0,担当画像目視=False,根画像目視=False,
        留保='画面操作と埋込データの対応だけ。元市場や金融会計の再監査ではない。530集約マーカーと630実約定を区別する。')
    path=HERE/'二銘柄五範囲と玉切替及びズームの表示確認.json'
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,path=str(path),SHA256=digest(path.read_bytes()),checks={k:len(v['checks']) for k,v in screens.items()},images={k:v['image_path'] for k,v in screens.items()}),ensure_ascii=False))


# ----------------------------------------


if __name__=='__main__':
    main()
