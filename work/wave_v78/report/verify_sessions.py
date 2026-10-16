"""追加した常時表示の全セッション表を、保存損益と実ブラウザーへ独立照合する。"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
OUT = ROOT / 'アルゴリズム調査/00074_歴代手法の再評価と二市場統合'
SOURCE = OUT / '過去の知見を統合した手法と全セッション損益.html'
SYMBOLS = ('TOPIX', 'NK225')
FIELDS = ('profit', 'loss', 'net')


def load(path: Path) -> dict:
    """機能: 保存JSONだけを読み込む。

    引数: path(Path)。返り値: 保存内容(dict)。
    """
    return json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 数値の参照元又は今回のHTMLの内容指紋を求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expectations() -> dict:
    """機能: HTMLから独立した保存売買結果で四手法・全三十場の期待値を作る。

    引数: なし。返り値: 期待する場別額・全体額・入力指紋(dict)。
    """
    fixed = load(WORK / '事前固定.json')
    selection = load(WORK / '前半選定.json')
    identifiers = list(dict.fromkeys([selection['基準'], *[r['id'] for r in selection['代表']]]))
    assert len(identifiers) == 4 and len(fixed['全30']) == 30
    methods = {}
    hashes = {}
    for identifier in identifiers:
        path = WORK / 'results' / (identifier + '.json')
        result = load(path)
        rows = {}
        for session in fixed['全30']:
            rows[session] = {}
            for symbol in SYMBOLS:
                found = [r for r in result['rows'] if r['session'] == session and r['symbol'] == symbol]
                assert len(found) == 1
                row = found[0]
                assert abs(row['profit'] - row['loss'] - row['net']) < 1e-7
                rows[session][symbol] = {field: row[field] for field in FIELDS}
        total = {symbol: {field: result['periods']['全30'][symbol][field] for field in FIELDS} for symbol in SYMBOLS}
        for symbol in SYMBOLS:
            for field in FIELDS:
                assert abs(sum(rows[s][symbol][field] for s in fixed['全30']) - total[symbol][field]) < 1e-7
        methods[identifier] = dict(rows=rows, total=total)
        hashes[str(path.relative_to(ROOT))] = digest(path)
    return dict(sessions=fixed['全30'], baseline=selection['基準'], methods=methods, hashes=hashes)


PROBE = r'''
/**
 * 機能: 常時表示の新表を保存結果由来の期待値へ照合し、既存UIと狭幅動作を確認する。
 * @returns {object} 照合件数と表示状態。
 */
function verifyVisibleSessions(){
 const expected=SESSION_EXPECTED,panel=document.getElementById('all-sessions-panel'),selector=document.getElementById('session-method'),target=document.getElementById('all-session-results');
 if(!panel||!selector||!target)throw Error('全セッションの新UIがありません');
 if(panel.closest('details')||target.closest('details'))throw Error('全セッション表が折畳の中です');
 for(let p=target;p&&p!==document.documentElement;p=p.parentElement){const st=getComputedStyle(p);if(st.display==='none'||st.visibility==='hidden'||p.hidden)throw Error('全セッション表が非表示です');}
 if(selector.value!==expected.baseline)throw Error('初期選択が従来J2ではありません');
 const options=[...selector.options].map(o=>o.value),ids=Object.keys(expected.methods);
 if(options.length!==4||options.some(id=>!ids.includes(id)))throw Error('選択できる四手法が違います');
 let views=0,amounts=0,totals=0;
 const numeric=cell=>Number(cell.textContent.replaceAll('−','-').replace(/[^\d.+-]/g,''));
 for(const id of ids){
  selector.value=id;selector.dispatchEvent(new Event('change',{bubbles:true}));
  const table=target.querySelector('table'),body=table?.querySelector('tbody');
  if(!body||body.rows.length!==31)throw Error('三十場と合計の31行ではありません');
  for(let i=0;i<30;i++){
   const row=body.rows[i],session=expected.sessions[i];
   if(row.cells.length!==7)throw Error('両商品併記の7列ではありません');
   if(!row.cells[0].textContent.includes(session.slice(0,10)))throw Error('セッション日付順');
   const label=session.endsWith('_Day')?'デイ':'ナイト';
   if(!row.cells[0].textContent.includes(label))throw Error('昼夜の表示');
   for(const [symbol,offset] of [['TOPIX',1],['NK225',4]])for(const [k,field] of ['profit','loss','net'].entries()){
    if(numeric(row.cells[offset+k])!==Math.round(expected.methods[id].rows[session][symbol][field]))throw Error('場別額不一致 '+id+' '+session+' '+symbol+' '+field);
    amounts++;
   }
   views++;
  }
  const total=body.rows[30];if(!total.cells[0].textContent.includes('合計'))throw Error('合計の表示');
  for(const [symbol,offset] of [['TOPIX',1],['NK225',4]])for(const [k,field] of ['profit','loss','net'].entries()){
   if(numeric(total.cells[offset+k])!==Math.round(expected.methods[id].total[symbol][field]))throw Error('全体合計不一致');totals++;
  }
 }
 // ----------------------------------------
 // 旧比較表、三段階説明、商品切替、売買図及び詳細表が残っていることを確認する。
 for(const id of ['comparison','methods','detail-method','detail-symbol','detail-session','chart','orders'])if(!document.getElementById(id))throw Error('既存UIの欠落 '+id);
 if(!window.reportTest||window.reportTest.METHODS.length!==4)throw Error('既存の四手法UIが欠落');
 if(!document.querySelector('#chart svg')||document.querySelectorAll('.method').length!==4)throw Error('既存図解や説明章が欠落');
 selector.value=expected.baseline;selector.dispatchEvent(new Event('change',{bubbles:true}));
 let scroll=target.querySelector('table').parentElement,found=null;
 while(scroll&&panel.contains(scroll)){const style=getComputedStyle(scroll);if(['auto','scroll'].includes(style.overflowX)){found=scroll;break;}scroll=scroll.parentElement;}
 if(!found)throw Error('表内横スクロール容器がありません');
 let narrowChecked=false;
 if(innerWidth<700){if(found.scrollWidth<=found.clientWidth+1)throw Error('狭幅で横スクロールになっていません');found.scrollLeft=50;if(found.scrollLeft<=0)throw Error('表内を横移動できません');found.scrollLeft=0;narrowChecked=true;}
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('文書全体が横へ溢れています');
 if(/undefined|NaN|__DATA__/.test(panel.innerText))throw Error('未定義の新表表示');
 return {全合格:true,手法数:ids.length,場表示数:views,場別金額数:amounts,合計金額数:totals,常時表示:true,両商品併記:true,初期選択:selector.value,既存UI維持:true,狭幅表内横移動確認:narrowChecked,表のスクロール幅:found.scrollWidth,表の表示幅:found.clientWidth,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth};
}
try{document.body.dataset.check=JSON.stringify(verifyVisibleSessions());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
'''


def render(source: str, expected: dict, name: str, width: int, height: int) -> dict:
    """機能: 新表の複製だけを隔離Chromeで検査し画像にする。

    引数: source/name(str)、expected(dict)、width/height(int)。返り値: ブラウザー検査結果(dict)。
    """
    spec = importlib.util.spec_from_file_location('全場表の隔離描画_' + name, ROOT / 'work/wave_v52/review/verify_report.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT = OUT
    module.VISUAL = HERE / 'visual_sessions'
    payload = json.dumps(expected, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    module.PROBE = '<script>const SESSION_EXPECTED=' + payload + ';\n' + PROBE + '</script>'
    extra = '<script>document.querySelector("main").replaceChildren(document.querySelector("#all-sessions-panel"));window.scrollTo(0,0);</script>'
    return module.render(source, name, width, height, extra)


def main() -> None:
    """機能: 計算済み数値を新表の全切替と広狭画面へ照合する。

    引数: なし。返り値: なし(None)。過去の検査証跡や公開HTMLは編集しない。
    """
    source = SOURCE.read_text(encoding='utf8')
    soup = BeautifulSoup(source, 'html.parser')
    expected = expectations()
    assert soup.select_one('#all-sessions-panel') is not None
    assert soup.select_one('#session-method') is not None
    assert soup.select_one('#all-session-results') is not None
    with ThreadPoolExecutor(max_workers=2) as pool:
        wide = pool.submit(render, source, expected, '全セッション表_広幅', 1480, 2050)
        narrow = pool.submit(render, source, expected, '全セッション表_狭幅', 520, 2050)
        results = [wide.result(), narrow.result()]
    proof = dict(全合格=True, 手法数=4, 場数=30, 商品数=2, 保存結果からの期待値=True,
                 実画面=results, 目視確認=False, HTML_SHA256=digest(SOURCE),
                 入力SHA256=expected['hashes'], 検査器SHA256=digest(Path(__file__)),
                 売買再実行=0, API取得=0, 既存検査器変更=False)
    (HERE / '全セッション常時表示の検査.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
