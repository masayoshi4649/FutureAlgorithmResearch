"""全38条件の表示金額・枚数・売買図を隔離ブラウザで照合する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import report

HERE = Path(__file__).resolve().parent
PROBE = r'''<script>
/**
 * 機能: 全手法・商品・セッションの画面を保存会計と照合する。
 * @returns {object} 件数と表示品質。
 */
function independentVerify(){
 let views=0,accounts=0,numbers=0,markers=0;
 const number=cell=>Number(cell.textContent.replaceAll(',','').replaceAll('円',''));
 const equal=(actual,expected,label)=>{if(actual!==expected)throw Error(label+': '+actual+' / '+expected);};
 for(const [id,result] of Object.entries(D.methods)){
  $('method').value=id;
  for(const symbol of ['TOPIX','NK225']){
   $('symbol').value=symbol;render();
   const rows=$('sessions').querySelector('tbody').rows,expected=result.rows.filter(r=>r.symbol===symbol);
   equal(rows.length,29,'場行数');equal(expected.length,28,'会計場数');
   for(let i=0;i<28;i++){
    equal(rows[i].cells[0].textContent,expected[i].session,'場名');
    for(const [column,field,sign]of [[1,'profit',1],[2,'loss',-1],[3,'net',1],[4,'fees',1]]){
     equal(number(rows[i].cells[column]),Math.round(sign*expected[i][field]),'場金額 '+id+' '+field);numbers++;
    }
    equal(rows[i].cells[5].textContent,`${expected[i].winning_lots} / ${expected[i].losing_lots} / ${expected[i].winning_lots-expected[i].losing_lots}`,'枚数');
   }
   const periods=$('periods').querySelector('tbody').rows,targets=[...['前16','後12','全28'].map(p=>result.periods[p][symbol]),...result.weeks[symbol]];
   equal(periods.length,targets.length,'期間行数');
   for(let i=0;i<targets.length;i++)for(const [column,field,sign]of [[1,'profit',1],[2,'loss',-1],[3,'net',1],[4,'fees',1]]){
    equal(number(periods[i].cells[column]),Math.round(sign*targets[i][field]),'期間金額');numbers++;
   }
   const quoteRows=$('quotes').querySelector('tbody').rows,ids=[result.variant.base,id].filter((v,i,a)=>a.indexOf(v)===i);
   let ri=0;for(const variant of ids)for(const p of ['全28','後12'])for(const s of ['TOPIX','NK225']){
    const q=D.methods[variant].quote[p][s],a=D.methods[variant].periods[p][s];equal(q.complete,true,'気配欠測');
    equal(number(quoteRows[ri].cells[1]),Math.round(a.net),'主評価');equal(number(quoteRows[ri].cells[2]),Math.round(q.net),'気配');ri++;numbers+=2;
   }
   views++;
   for(const account of expected){
    $('session').value=account.session;draw();const key=account.session+'|'+symbol,orders=result.orders[key],svg=$('chart').querySelector('svg');
    if(!svg)throw Error('グラフなし');equal(svg.querySelectorAll('title').length,orders.length,'売買マーカー数');
    equal(svg.querySelectorAll('circle').length,orders.filter(o=>o[7]===1).length,'新規マーカー');
    equal($('orders').querySelector('tbody').rows.length,orders.length,'売買表');
    if(/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('描画未定義');
    for(const point of svg.querySelectorAll('circle')){
     const x=Number(point.getAttribute('cx')),y=Number(point.getAttribute('cy'));if(x<0||x>1120||y<0||y>400)throw Error('新規位置が画外');
    }
    markers+=orders.length;accounts++;
   }
  }
 }
 $('method').value=D.initial;$('symbol').value='TOPIX';$('session').value=D.fixed.全セッション.at(-1);render();
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('本文未定義');
 equal(document.querySelectorAll('#comparison tbody tr').length,D.primary.length*2,'比較行数');
 return {全合格:true,手法商品表示数:views,セッション売買図数:accounts,表示金額数:numbers,売買点数:markers,
  文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''


def main() -> None:
    """機能: 広い画面・狭い画面・売買図を検査して証跡を保存する。

    引数: --narrow-only(bool)。返り値: なし(None)。
    """
    spec = importlib.util.spec_from_file_location('legacy_visual',report.ROOT/'work/wave_v52/review/verify_report.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.OUT = report.OUT
    helper.VISUAL = HERE/'visual'
    helper.PROBE = PROBE
    parser = argparse.ArgumentParser()
    parser.add_argument('--narrow-only',action='store_true')
    args = parser.parse_args()
    source = (report.OUT/'損失を減らす改修と全セッション損益.html').read_text(encoding='utf8')
    if args.narrow_only:
        old = json.loads((HERE/'HTML表示の独立検査.json').read_text(encoding='utf8'))
        assert old['主HTML_SHA256'] == hashlib.sha256((report.OUT/'損失を減らす改修と全セッション損益.html').read_bytes()).hexdigest()
        old['画面'][1] = helper.render(source,'狭幅',500,1250)
        (HERE/'HTML表示の独立検査.json').write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf8')
        print('Chrome最小幅500で狭幅画像を確認しました')
        return
    proof = [helper.render(source,'広幅',1360,1450),helper.render(source,'狭幅',500,1250)]
    extra = '''<script>
/**
 * 機能: 売買図の章を画像検査用に表示する。
 * @returns {undefined} 表示変更のみ。
 */
function showChart(){for(const child of document.querySelector('main').children)child.style.display='none';$('chart').closest('section').style.display='block';}
showChart();</script>'''
    proof.append(helper.render(source,'売買図',1220,730,extra))
    output = dict(全合格=True,主HTML_SHA256=hashlib.sha256((report.OUT/'損失を減らす改修と全セッション損益.html').read_bytes()).hexdigest(),画面=proof)
    (HERE/'HTML表示の独立検査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print('全38手法・76表示・2128売買図の表示を照合しました')


if __name__ == '__main__':
    main()
