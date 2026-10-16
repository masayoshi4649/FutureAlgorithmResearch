"""全方法の表示切替と全場の円額を検算し、隔離ブラウザで描画する。"""

import importlib.util
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
import analyze
import build

HERE = Path(__file__).resolve().parent


def main():
    """
    機能: 元会計と埋込値の一致、全選択肢の描画、狭画面と全場表を確認する。
    引数: なし。
    返り値: None。描画画像と照合証拠を保存する。
    """
    path = build.PUBLIC / build.MAIN
    source = path.read_text(encoding='utf-8')
    digest = analyze.sha(path)
    soup = BeautifulSoup(source, 'html.parser')
    data = json.loads(soup.select_one('#accounting').string)
    results, _, _, _ = analyze.collect()
    assert set(data) == set(results['observed'])
    for identifier, value in data.items():
        assert value['rows'] == results['observed'][identifier]['rows']
        assert value['total'] == results['observed'][identifier]['periods']['全30']
    for item in soup.select('[href],img[src]'):
        name = item.get('href', item.get('src'))
        assert (build.PUBLIC / name).is_file(), name
    spec = importlib.util.spec_from_file_location('隔離表示87', build.ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = build.PUBLIC
    renderer.VISUAL = HERE / 'visual'
    renderer.PROBE = '''<script>
/**
 * 機能: 全方法の選択で全30場と合計が元会計通り表示されることを確認する。
 * 引数: なし。
 * 返り値: objectの照合件数。
 */
function inspectReport(){
 let count=0;const select=document.getElementById('method'),defaultChoice=select.value;
 for(const identifier of Object.keys(accounting)){
  select.value=identifier;renderSessions();
  const target=accounting[identifier],names=[...new Set(target.rows.map(r=>r.session))].sort();
  const rows=document.querySelectorAll('#session-table tbody tr');
  if(rows.length!==31)throw Error('全場行数');
  names.push('全30合計');
  for(let j=0;j<31;j++)for(let s=0;s<2;s++){
   const symbol=['TOPIX','NK225'][s],v=j===30?target.total[symbol]:target.rows.find(r=>r.session===names[j]&&r.symbol===symbol);
   const expected=[v.campaign_profit,-v.campaign_loss,v.net];
   for(let k=0;k<3;k++){const shown=Number(rows[j].children[1+s*3+k].textContent.replace(/[円,]/g,''));if(shown!==Math.round(expected[k]))throw Error(identifier+'の金額差');count++;}
  }
 }
 select.value=defaultChoice;renderSessions();
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面横溢れ');
 return {全合格:true,照合金額数:count,条件数:Object.keys(accounting).length,画面幅:innerWidth,背景:getComputedStyle(document.body).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(inspectReport());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''
    for name in ('case_topix_20260925.svg', 'case_nk225_20260922.svg',
                 'case_allocation_topix_20260928.svg', 'case_allocation_nk225_20260928.svg'):
        source = re.sub(r'<img src="'+re.escape(name)+r'"[^>]*>', lambda _: (build.PUBLIC / name).read_text(encoding='utf-8'), source)
    csp = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    source = source.replace('<head>', '<head>'+csp)
    views = [renderer.render(source, '原因と改修比較', 1450, 1300),
             renderer.render(source, '狭い画面', 520, 1400),
             renderer.render(source, '全セッション表', 1450, 2400,
                 '<script>const d=document.getElementById("sessions");d.open=true;document.querySelector("main").replaceChildren(d);</script>')]
    assert analyze.sha(path) == digest
    proof = dict(全合格=True, 画面=views, 公開SHA256=digest, 目視確認=False)
    (HERE / '表示の独立検査.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
