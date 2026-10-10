"""作業00049の全選択・金額・グラフ・暗色表示を実ブラウザで検査する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import unquote

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT/'アルゴリズム調査/00049_価格形成の観測から新手法を構築'
SOURCE = OUT/'価格形成から組んだ新手法の検証.html'
VISUAL = HERE/'visual'

PROBE = r'''<script>
/**
 * 機能: 全手法・商品・場を表示し、表示値と保存会計を照合する。
 * @returns {object} 検査件数と表示品質。
 */
function independentVerify(){
 let views=0,accounts=0,numbers=0,markers=0;
 const number=(cell)=>Number(cell.textContent.replaceAll(',','').trim());
 for(const method of data.methods){
  byId('method').value=method.id;
  for(const symbol of ['TOPIX','NK225']){
   byId('symbol').value=symbol;render();
   const group=data.results[method.id][symbol];
   const rows=byId('sessions').querySelector('tbody').rows;
   if(rows.length!==23||group.accounts.length!==23)throw Error('場の数:'+method.id+'/'+symbol);
   for(let i=0;i<rows.length;i++){
    const a=group.accounts[i],r=rows[i];
    if(r.cells[0].textContent!==a.session)throw Error('場名');
    for(const [column,field] of [[1,'profit'],[2,'loss'],[3,'net']]){
     if(number(r.cells[column])!==a[field])throw Error('場の表示金額:'+field);numbers++;
    }
    if(r.cells[4].textContent!==`${fmt(a.win_qty)} / ${fmt(a.loss_qty)} / ${fmt(a.flat_qty)}`)throw Error('枚数');
    if(number(r.cells[5])!==a.win_qty-a.loss_qty)throw Error('枚数差');
    const pf=a.loss>0?a.profit/a.loss:null;
    const payoff=a.win_qty>0&&a.loss_qty>0&&a.loss>0?(a.profit/a.win_qty)/(a.loss/a.loss_qty):null;
    if(r.cells[6].textContent!==fmt(pf,2)||r.cells[7].textContent!==fmt(payoff,2))throw Error('場別PF/平均勝負の表示不足');
   }
   const periodRows=byId('periods').querySelector('tbody').rows;
   const expected=[...group.periods,...group.weeks];
   if(periodRows.length!==expected.length)throw Error('期間行数');
   for(let i=0;i<expected.length;i++)for(const [column,field]of[[1,'profit'],[2,'loss'],[3,'net']]){
    if(number(periodRows[i].cells[column])!==expected[i][field])throw Error('期間表示金額');numbers++;
   }
   if(byId('comparison').querySelector('tbody').rows.length!==14)throw Error('比較表行数');
   views++;
   for(const account of group.accounts){
    byId('session').value=account.session;renderSession();
    const rs=byId('intervals').querySelector('tbody').rows;
    if(rs.length!==account.intervals.length)throw Error('区間数');
    for(let j=0;j<rs.length;j++){
     const target=account.intervals[j];
     for(const [column,field]of[[1,'利益円'],[2,'損失円'],[3,'確定収支円'],[4,'終了含み円'],[5,'時価収支円']]){
      if(number(rs[j].cells[column])!==target[field])throw Error('区間表示金額:'+field);numbers++;
     }
    }
    const svg=byId('chart').querySelector('svg');
    if(!svg||svg.querySelectorAll('title').length!==account.orders.length)throw Error('売買マーカー数');
    if(svg.querySelectorAll('circle').length!==account.orders.filter(o=>o[4]===2).length)throw Error('返済点');
    if(/NaN|Infinity|undefined/.test(svg.outerHTML))throw Error('グラフ未定義');
    markers+=account.orders.length;accounts++;
   }
  }
 }
 byId('method').value='P01';byId('symbol').value='TOPIX';byId('session').value=data.sessions.at(-1);render();
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面外への横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,手法商品表示数:views,セッション表示数:accounts,表示金額数:numbers,売買点数:markers,
         文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,
         背景:getComputedStyle(document.documentElement).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''


def render(source: str, name: str, width: int, height: int, extra: str = '') -> dict:
    """機能: 複製HTMLを隔離したheadless Chromeで表示し、数値と画像を保存する。

    引数: source/name/extra(str)、width/height(int)。返り値: ブラウザ検査結果(dict)。
    """
    VISUAL.mkdir(exist_ok=True)
    target, picture = VISUAL/(name+'.html'), VISUAL/(name+'.png')
    source = source.replace('<head>', '<head><base href="'+OUT.as_uri()+'/">')
    target.write_text(source.replace('</body>', PROBE+extra+'</body>'), encoding='utf8')
    cmd = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new', '--disable-gpu',
           '--no-first-run', '--disable-background-networking', '--disable-component-update', '--disable-sync',
           '--run-all-compositor-stages-before-draw', '--disable-features=PaintHolding',
           '--proxy-server=http://127.0.0.1:9', f'--window-size={width},{height}', '--virtual-time-budget=1000',
           '--user-data-dir='+str(VISUAL/('profile_'+name)), '--screenshot='+str(picture), '--dump-dom', target.as_uri()]
    proc = subprocess.run(cmd, capture_output=True, timeout=55, creationflags=subprocess.CREATE_NO_WINDOW)
    assert proc.returncode == 0 and picture.exists()
    soup = BeautifulSoup(proc.stdout.decode('utf8', errors='replace'), 'html.parser')
    if not soup.body or 'data-check' not in soup.body.attrs:
        (VISUAL/(name+'_failed_dom.html')).write_bytes(proc.stdout)
        raise AssertionError('DOM内の検査完了情報がありません')
    proof = json.loads(soup.body['data-check'])
    assert proof['全合格'], proof
    return dict(画面=name, 画像=str(picture), **proof)


def main() -> None:
    """機能: 全表示切替、広狭幅、売買図を検査し、必要に応じローカルリンクも確認する。

    引数: --links指定時だけREADME等のリンク存在も検査。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--links', action='store_true')
    parser.add_argument('--links-only', action='store_true')
    args = parser.parse_args()
    source = SOURCE.read_text(encoding='utf8')
    links = None
    if args.links or args.links_only:
        links = 0
        soup = BeautifulSoup(source, 'html.parser')
        for tag in soup.select('a[href],img[src]'):
            link = tag.get('href', tag.get('src'))
            if link.startswith(('http', '#')):
                continue
            target = OUT/unquote(link.split('#')[0].split('?')[0])
            assert target.exists(), target
            links += 1
    output = HERE/'HTML表示の独立検査.json'
    if args.links_only:
        result = json.loads(output.read_text(encoding='utf8'))
        result['静的リンク数'] = links
    else:
        results = [render(source, '全体', 1500, 1500), render(source, '狭幅', 520, 1350),
                   render(source, '損益', 1500, 1450, '<script>document.querySelector("main").replaceChildren(document.querySelector("#results"));window.scrollTo(0,0);</script>'),
                   render(source, '売買図と区間', 1500, 1400,
                          '<script>const section=document.querySelector("#chart").parentElement;document.querySelector("main").replaceChildren(section);window.scrollTo(0,0);</script>')]
        result = dict(全合格=True, 静的リンク数=links, 目視確認=False, 結果=results)
    result['HTML_SHA256'] = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
