"""最終文言修正後に会計・構造の同一性を確かめ、画像とSHAだけを更新する。"""
from pathlib import Path
import hashlib
import importlib.util
import json
from bs4 import BeautifulSoup
import verify_browser as verify


HERE = Path(__file__).resolve().parent
PROBE = r'''<script>
/**
 * 機能: 文面だけ変更された最終版を描画し、追加の内訳表も照合する。
 * @returns {Object} 引数なし。返り値は描画・内訳照合の結果。
 */
function finalWordsVerify(){
 const d=window.reportTest.data,ok=(v,t)=>{if(!v)throw Error(t);};
 const read=e=>Number(e.textContent.replaceAll(',','').replaceAll('円','').trim());
 let n=0;
 if(d.final){
  const rows=document.getElementById('cost-results').rows;
  ok(rows.length===2,'内訳2商品');
  ['TOPIX','NK225'].forEach((s,i)=>{const a=d.final[5][d.repaired[1]].periods['対象'][s];
   [a.net+a.fees+a.spread_drag,-a.spread_drag,-a.fees,a.net].forEach((v,j)=>{ok(read(rows[i].cells[j+1])===v,'気配差・料金分解');n++;});});
  const solo=document.getElementById('solo-results').rows;ok(solo.length===3,'単独対照3行');
  d.repaired.forEach((id,i)=>['TOPIX','NK225'].forEach((s,j)=>{const a=d.final[5][id].periods['対象'][s],b=d.final[5][d.controls[i]].periods['対象'][s],cell=solo[i].cells[j+1],values=cell.querySelectorAll('.number');
   ok(values.length===2&&read(values[0])===a.net&&read(values[1])===b.net,'単独と共通の収支');ok(cell.querySelector('small').textContent===a.trades+'組／'+b.trades+'組','単独と共通の組数');n+=4;}));
  ok(document.getElementById('session-results').rows.length===31,'全場表');
 }else ok(document.getElementById('all-results').rows.length===188,'全条件表');
 for(const e of document.querySelectorAll('details'))e.open=true;
 ok(document.documentElement.scrollWidth<=innerWidth+2,'文書横溢れ');
 for(const e of document.querySelectorAll('details'))e.open=false;
 ok(window.browserErrors.length===0,'JS例外');ok(getComputedStyle(document.body).backgroundColor==='rgb(16, 21, 30)','暗色');
 return {全合格:true,文面更新後確認:true,追加内訳数値照合数:n,JS例外数:window.browserErrors.length,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth};
}
try{document.body.dataset.check=JSON.stringify(finalWordsVerify());}catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e),stack:e.stack});}
</script>'''


def compare_data(a, b, path=''):
    """
    機能: JSONの全数値・配列順・型を照合し、文言変更だけを許す。
    引数: a/b (dict/list/scalar)、path (str)。
    返り値: int の照合した非文字列末端数。
    """
    assert type(a) is type(b), path
    if isinstance(a, dict):
        assert a.keys() == b.keys(), path
        return sum(compare_data(a[k], b[k], path + '/' + str(k)) for k in a)
    if isinstance(a, list):
        assert len(a) == len(b), path
        return sum(compare_data(x, y, path + '/' + str(i)) for i, (x, y) in enumerate(zip(a, b)))
    if isinstance(a, str):
        return 0
    assert a == b, path
    return 1


# ----------------------------------------
def skeleton(source):
    """
    機能: 検査用注入要素を除き、HTMLの構造・属性と表示JavaScriptを返す。
    引数: source (str) のHTML。
    返り値: tuple の構造列、主要スクリプト、CSS。
    """
    soup = BeautifulSoup(source, 'html.parser')
    scripts = [tag.get_text() for tag in soup.select('script') if tag.get_text().startswith(('"use strict";', 'const METHOD =', '/**\n * 実保有秒'))]
    assert len(scripts) == 2
    styles = [tag.get_text() for tag in soup.select('style')]
    for tag in soup.select('script,base,meta[http-equiv="Content-Security-Policy"]'):
        tag.decompose()
    return [(tag.name, tag.attrs) for tag in soup.find_all()], scripts, styles


# ----------------------------------------
def main():
    """
    機能: 全数値再走査済みの版から文言だけ変わったことを確かめ、最終画像を再描画する。
    引数: なし。
    返り値: None。元HTMLや研究結果は変更しない。
    """
    target = HERE / 'HTML表示の独立検査.json'
    proof = json.loads(target.read_text(encoding='utf-8'))
    frozen = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (verify.MAIN, verify.ALL)}
    checks, sources = [], []
    for path, previous in ((verify.MAIN, '主全体広幅'), (verify.ALL, '全188広幅')):
        old = (HERE / 'visual' / (previous + '.html')).read_text(encoding='utf-8')
        current, data = verify.embedded(path)
        old_data = json.loads(BeautifulSoup(old, 'html.parser').select_one('#report-data').string)
        count = compare_data(old_data, data)
        assert skeleton(old) == skeleton(current), '構造・主要JS・CSS変更'
        checks.append(dict(ファイル=path.name, 非文字列末端一致数=count, DOM主要JSとCSS一致=True))
        sources.append(current)
    spec = importlib.util.spec_from_file_location('旧隔離描画最終文面81', verify.ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = verify.OUT; renderer.VISUAL = HERE / 'visual'; renderer.PROBE = PROBE
    policy = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    errors = '<script>window.browserErrors=[];window.addEventListener("error",e=>window.browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>window.browserErrors.push(String(e.reason)));</script>'
    main_source, all_source = [source.replace('<head>', '<head>' + policy + errors) for source in sources]
    views = [(main_source, '主全体広幅', 1500, 1500, ''), (main_source, '主全体狭幅', 520, 1600, ''),
             (main_source, '全セッション損益', 1500, 2350, '<script>document.querySelector("main").replaceChildren(document.getElementById("all-sessions"));window.scrollTo(0,0);</script>'),
             (main_source, '実保有と損失原因', 1500, 2200, '<script>const main=document.querySelector("main"),hold=document.getElementById("holding"),change=document.getElementById("change-results").closest("section"),detail=[...document.querySelectorAll("details")].find(d=>d.querySelector("summary").textContent.includes("赤字が"));detail.open=true;main.replaceChildren(hold,change,detail);window.scrollTo(0,0);</script>'),
             (all_source, '全188広幅', 1500, 1450, ''), (all_source, '全188狭幅', 520, 1450, '')]
    pictures = [renderer.render(*view) for view in views]
    assert frozen == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (verify.MAIN, verify.ALL)}
    proof['全数値操作検査時SHA256'] = proof['HTML_SHA256']
    proof['HTML_SHA256'] = frozen
    proof['文面だけの更新確認'] = checks
    proof['最終文面の再描画'] = pictures
    proof['目視確認'] = False
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(最終SHA=frozen, 同一性確認=checks, 最終描画=pictures), ensure_ascii=False))


if __name__ == '__main__':
    main()
