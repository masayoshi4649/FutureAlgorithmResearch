"""公開17条件の小会計だけを、隔離Chromeの切替・全場・広狭表示へ照合する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

from bs4 import BeautifulSoup

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT/'アルゴリズム調査/00104_E01の銘柄差の原因と修正検証'
TITLE = 'E01の銘柄差と修正後の全セッション損益'
ACCOUNTING_TITLE = 'E01の銘柄差と固定16対照の公開会計.json'
OUTPUT = HERE/'report_review'
PROOF_NAME = 'E01銘柄差17条件の全場と広狭表示確認.json'
RENDERER = ROOT/'work/wave_v52/review/verify_report.py'
INITIAL = 'E01_CROSS_B03'
SYMBOLS = ('TOPIX', 'NK225')
LABELS = {'TOPIX': 'TOPIXミニ', 'NK225': '日経マイクロ'}
TESTS = ('金額利益65以上', '赤字全場20以下', '最大赤字は平均黒字以下')


def digest(path: Path) -> str:
    """
    機能: 公開小資料又は表示sourceの指紋を求める。
    引数: path(Path)はHTML・公開JSON・QA小source。
    返り値: strはSHA256。金融source・台帳・大型入力を読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def money(value: float | None, loss: bool = False) -> str:
    """
    機能: 公開会計から期待する符号付き整数額を作る。
    引数: value(float|None)、loss(bool)は数値と正数損失の指定。
    返り値: strは桁区切り額又は「—」。JSON以外の金額を計算しない。
    """
    return '—' if value is None else format(-value if loss else value, ',.0f')


def pct(value: float | None) -> str:
    """
    機能: 公開会計の比率を表示期待文字へ変える。
    引数: value(float|None)は保存比率。
    返り値: strは小数1桁百分率又は「未定義」。
    """
    return '未定義' if value is None else format(100*value, '.1f')+'%'


def overview_rows(data: dict, ids: list) -> list:
    """
    機能: 同じ条件IDの二商品について、概要11列と未丸め金額を作る。
    引数: data(dict)、ids(list[str])は公開会計と表示対象。
    返り値: list[dict]はセル文字・原数値。個別最良商品を混ぜない。
    """
    rows = []
    for ident in ids:
        case = data['cases'][ident]
        common = all(case['summary'][s]['pass_all'] for s in SYMBOLS)
        for s in SYMBOLS:
            v = case['summary'][s]
            rows.append(dict(id=ident, symbol=s, cells=[case['description']['name']+ident, LABELS[s],
                money(v['profit']), money(v['loss'], True), money(v['net']), pct(v['profit_share']),
                f'{v["positive"]}/{v["negative"]}/{v["no_trade"]}', money(v['mean_positive_session_net']),
                money(v['worst_session_loss'], True), ' / '.join('○' if v['tests'][k] else '×' for k in TESTS),
                '両商品達成' if common else '両商品未達'],
                amounts={'2': v['profit'], '3': -v['loss'], '4': v['net'],
                    '7': v['mean_positive_session_net'], '8': -v['worst_session_loss']}))
    return rows


def expectations(data: dict) -> dict:
    """
    機能: 公開17条件の5780全場セル・550概要セル・補足表を期待値へ射影する。
    引数: data(dict)は検算済みの公開会計だけ。
    返り値: dictは純表示期待値。金融・入力・台帳を再読しない。
    """
    assert data['全合格'] and len(data['cases']) == 17 and len(data['sessions']) == 33
    assert data['initial_case'] == INITIAL and len(data['main']) == 3 and len(data['selected']) == 5
    tables, details = {}, {}
    fields = ('profit', 'loss', 'net', 'winning_lots', 'losing_lots')
    for ident, case in data['cases'].items():
        index = {(r['session'], r['symbol']): r for r in case['rows']}; assert len(index) == 66
        values = [[index[session, s][f] for s in SYMBOLS for f in fields] for session in data['sessions']]
        values.append([case['summary'][s][f] for s in SYMBOLS for f in fields])
        for row in values:
            row[1] = -row[1]; row[6] = -row[6]
        tables[ident] = values
        top3, chronology, direction = [], [], []
        for s in SYMBOLS:
            tail = case['top3'][s]
            top3.append([LABELS[s], money(tail['net']), pct(tail['profit_share']),
                f'{tail["positive"]}/{tail["negative"]}/{tail["no_trade"]}',
                money(tail['mean_positive_session_net']), money(tail['worst_session_loss'], True)])
            for tag in ('前16', '後17'):
                v = case['chronology'][tag][s]
                chronology.append([tag+'場', LABELS[s], money(v['profit']), money(v['loss'], True),
                    money(v['net']), pct(v['profit_share']), f'{v["positive"]}/{v["negative"]}/{v["no_trade"]}'])
            for tag in ('買い', '売り'):
                v = case['directions'][s][tag]
                direction.append([tag, LABELS[s], money(v['利益']), money(v['損失'], True),
                    money(v['収支']), str(v['勝ち枚数']), str(v['負け枚数'])])
        details[ident] = dict(top3=top3, chronology=chronology, directions=direction,
            description=case['description'], direction_source=case['direction_source'])
    overview = {'main-overview': overview_rows(data, data['main']),
        'selected-overview': overview_rows(data, data['selected']),
        'all-overview': overview_rows(data, list(data['cases']))}
    assert [len(overview[key]) for key in overview] == [6, 10, 34]
    diagnostic = data['b03_diagnostics']
    assert diagnostic['B03実親数'] == 15 and diagnostic['B03二票親数'] == 7 and diagnostic['B03ナイト親数'] == 13
    return dict(tables=tables, details=details, overview=overview, initial=INITIAL,
        labels=[s.replace('_Day', ' デイ').replace('_Night', ' ナイト') for s in data['sessions']]+['全33場合計'],
        counts=dict(全場円枚数=5780, 主概要=66, 群概要=110, 全概要=374, 上位三除外=204, 前後期間=476, 買売=476),
        diagnostic_words=['15取引中7が2票、13が夜間', '途中清算逆行TOPIX3,166円・日経1,566円',
            '買い＋4円・売り＋3,382円'],
        headers=['TOPIXミニ・片方向10枚まで', '日経マイクロ・片方向20枚まで'])


def load_display() -> tuple:
    """
    機能: 根が公開したHTML/小JSONだけを同bytesで読み、表示sourceへ束縛する。
    引数: なし。
    返り値: tuple[str,dict,dict]はHTML・公開会計・指紋。公開前の仮表示を作らない。
    """
    hp, ap = PUBLIC/(TITLE+'.html'), PUBLIC/ACCOUNTING_TITLE
    assert hp.exists() and ap.exists(), '根の公開完了後だけ表示検査を行う'
    hb, ab = hp.read_bytes(), ap.read_bytes()
    data = json.loads(ab.decode('utf-8-sig'))
    report_path = HERE/'report.py'; key = report_path.relative_to(ROOT).as_posix()
    assert digest(report_path) == data['表示source_SHA256'][key]
    return hb.decode('utf-8'), data, dict(HTML_SHA256=hashlib.sha256(hb).hexdigest(),
        公開会計_SHA256=hashlib.sha256(ab).hexdigest(), 表示source_SHA256=data['表示source_SHA256'][key])


def static_check(source: str, expected: dict) -> dict:
    """
    機能: Chromeなしで全セル・概要・補足・初期選択を公開会計へ照合する。
    引数: source(str)、expected(dict)は公開HTMLと純表示期待値。
    返り値: dictは実照合件数。画像・公開・Chrome・金融は作らない。
    """
    soup = BeautifulSoup(source, 'html.parser'); counts = dict.fromkeys(expected['counts'], 0)
    selected = soup.select('#case option[selected]')
    assert len(selected) == 1 and selected[0]['value'] == expected['initial']
    options = [n['value'] for n in soup.select('#case option')]
    assert len(options) == len(set(options)) == 17 and set(options) == set(expected['tables'])
    sections = soup.select('section[data-case]'); assert len(sections) == 17
    for section in sections:
        ident = section['data-case']; rows = section.select('table.sessions tbody tr'); assert len(rows) == 34
        for i, row in enumerate(rows):
            cells = row.find_all(['th', 'td'], recursive=False)
            assert len(cells) == 11 and cells[0].get_text() == expected['labels'][i]
            for j, value in enumerate(expected['tables'][ident][i]):
                assert cells[j+1].get_text() == money(value)
                if j in (0, 1, 2, 5, 6, 7):
                    assert abs(float(cells[j+1]['data-value'])-value) < 1e-5
                counts['全場円枚数'] += 1
        for selector, key, count in (('top3', 'top3', '上位三除外'), ('chronology', 'chronology', '前後期間'),
            ('directions', 'directions', '買売')):
            actual = [[c.get_text() for c in r.find_all(['th', 'td'], recursive=False)]
                for r in section.select('table.'+selector+' tbody tr')]
            assert actual == expected['details'][ident][key], (ident, selector)
            counts[count] += sum(len(r) for r in actual)
    for table_id, count in (('main-overview', '主概要'), ('selected-overview', '群概要'), ('all-overview', '全概要')):
        rows = soup.select('#'+table_id+' tbody tr'); assert len(rows) == len(expected['overview'][table_id])
        for row, e in zip(rows, expected['overview'][table_id]):
            assert row['data-case-id'] == e['id'] and row['data-symbol'] == e['symbol']
            cells = row.find_all('td', recursive=False)
            assert [c.get_text() for c in cells] == e['cells']
            for i, value in e['amounts'].items():
                assert cells[int(i)]['data-value'] == '' if value is None else abs(float(cells[int(i)]['data-value'])-value) < 1e-5
            counts[count] += len(cells)
    text = soup.body.get_text()
    assert all(word in text for word in expected['diagnostic_words'])
    assert counts == expected['counts']
    return dict(全合格=True, 件数=counts, 条件=17, 初期選択=expected['initial'])


def browser_probe(expected: dict) -> str:
    """
    機能: 全17切替・表・暗色/横溢れの独立ブラウザ検査を作る。
    引数: expected(dict)は公開JSONだけから作った期待値。
    返り値: strは検査script。生成だけではChromeを起動しない。
    """
    payload = json.dumps(expected, ensure_ascii=False, allow_nan=False).replace('</', '<\\/')
    return '''<script>
/**
 * 公開会計の期待文字へ一つの表を照合する。
 * @param {HTMLTableElement} table - 公開補足表。
 * @param {Array<Array<string>>} expected - 期待する行と列。
 * @param {string} name - 差異の同定名。
 * @returns {number} 照合したセル数。
 */
function checkPublicTable(table,expected,name){
 if(!table)throw Error('表なし:'+name);const rows=table.tBodies[0].rows;let count=0;
 if(rows.length!==expected.length)throw Error('表行数:'+name);
 for(let i=0;i<expected.length;i++){
  if(rows[i].cells.length!==expected[i].length)throw Error('表列数:'+name);
  for(let j=0;j<expected[i].length;j++){if(rows[i].cells[j].textContent!==expected[i][j])throw Error('表差:'+name+'/'+i+'/'+j);count++;}
 }
 return count;
}
/**
 * 17条件を変更イベントで切り替え、5780全場数値と主/群/全概要を照合する。
 * @returns {object} 実照合件数・背景・画面幅。金融と通信は行わない。
 */
function verifyCrossMarketReport(){
 const expected=__PAYLOAD__,picker=document.getElementById('case');
 const counts={全場円枚数:0,主概要:0,群概要:0,全概要:0,上位三除外:0,前後期間:0,買売:0};
 if(picker.value!==expected.initial)throw Error('初期B03選択');
 const options=[...picker.options].map(o=>o.value);
 if(options.length!==17||new Set(options).size!==17||options.some(id=>!(id in expected.tables)))throw Error('17選択肢');
 let visible=[...document.querySelectorAll('section[data-case]')].filter(s=>!s.hidden);
 if(visible.length!==1||visible[0].dataset.case!==expected.initial)throw Error('初期B03表示');
 for(const [id,values] of Object.entries(expected.tables)){
  picker.value=id;picker.dispatchEvent(new Event('change',{bubbles:true}));
  visible=[...document.querySelectorAll('section[data-case]')].filter(s=>!s.hidden);
  if(visible.length!==1||visible[0].dataset.case!==id||picker.value!==id)throw Error('切替:'+id);
  const section=visible[0],table=section.querySelector('table.sessions'),rows=table.tBodies[0].rows;
  if(rows.length!==34||table.tHead.rows[0].cells[1].textContent!==expected.headers[0]||table.tHead.rows[0].cells[2].textContent!==expected.headers[1])throw Error('33場総計か数量ヘッダ');
  for(let i=0;i<34;i++){
   if(rows[i].cells.length!==11||rows[i].cells[0].textContent!==expected.labels[i])throw Error('場同定:'+id+'/'+i);
   for(let j=0;j<10;j++){
    const cell=rows[i].cells[j+1],value=Number(cell.textContent.replaceAll(',','').trim());
    if(!Number.isFinite(value)||Math.abs(value-values[i][j])>.500001)throw Error('全場値:'+id+'/'+i+'/'+j);
    if([0,1,2,5,6,7].includes(j)&&Math.abs(Number(cell.dataset.value)-values[i][j])>1e-5)throw Error('原円額属性');
    counts.全場円枚数++;
   }
  }
  const detail=expected.details[id];
  counts.上位三除外+=checkPublicTable(section.querySelector('table.top3'),detail.top3,'top3');
  counts.前後期間+=checkPublicTable(section.querySelector('table.chronology'),detail.chronology,'前後');
  counts.買売+=checkPublicTable(section.querySelector('table.directions'),detail.directions,'買売');
  if(!section.querySelector('table.directions').closest('details').textContent.includes(detail.direction_source))throw Error('方向枚数の定義');
  if(/NaN|Infinity|undefined/.test(section.innerText))throw Error('未定義表示');
  if(document.documentElement.scrollWidth>innerWidth+2)throw Error('切替時本文横溢れ');
 }
 for(const [tableId,key] of [['main-overview','主概要'],['selected-overview','群概要'],['all-overview','全概要']]){
  const table=document.getElementById(tableId),rows=table.tBodies[0].rows,values=expected.overview[tableId];
  if(rows.length!==values.length)throw Error('概要行数:'+tableId);
  for(let i=0;i<values.length;i++){
   const row=rows[i],e=values[i];if(row.dataset.caseId!==e.id||row.dataset.symbol!==e.symbol||row.cells.length!==11)throw Error('概要同定');
   for(let j=0;j<11;j++){if(row.cells[j].textContent!==e.cells[j])throw Error('概要値:'+tableId+'/'+i+'/'+j);counts[key]++;}
   for(const [column,value] of Object.entries(e.amounts)){
    const stored=row.cells[Number(column)].dataset.value;
    if(value===null?stored!=='':!Number.isFinite(Number(stored))||Math.abs(Number(stored)-value)>1e-5)throw Error('概要未丸め額');
   }
  }
 }
 if(!document.getElementById('selected-overview').closest('details')||!document.getElementById('all-overview').closest('details'))throw Error('群と全条件の折畳み');
 for(const word of expected.diagnostic_words)if(!document.body.innerText.includes(word))throw Error('B03留保:'+word);
 picker.value=expected.initial;picker.dispatchEvent(new Event('change',{bubbles:true}));
 const bg=getComputedStyle(document.body).backgroundColor;
 if(bg!=='rgb(11, 17, 32)')throw Error('暗色背景');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 for(const [key,value] of Object.entries(expected.counts))if(counts[key]!==value)throw Error('件数:'+key);
 return {全合格:true,件数:counts,切替:17,初期選択:expected.initial,背景:bg,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,
         Chrome:'隔離headless',金融:0,API:0,packet:0,ledger:0};
}
try{document.body.dataset.check=JSON.stringify(verifyCrossMarketReport());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''.replace('__PAYLOAD__', payload)


def prepare_only() -> dict:
    """
    機能: 公開資料の有無に依存せず、根実行用の予定だけを表示する。
    引数: なし。
    返り値: dictは準備状態。検査合格を捏造せず、Chrome/公開読取は0。
    """
    value = dict(準備済み=True, 検査未実施=True, QA_source_SHA256=digest(Path(__file__)),
        証跡予定=(OUTPUT/PROOF_NAME).relative_to(ROOT).as_posix(),
        予定=dict(条件=17, 全場円枚数=5780, 主概要行=6, 群概要行=10, 全概要行=34,
            広狭=[1450, 520], 画像=3, 初期B03=INITIAL), Chrome=0, 公開読取=0, 金融=0, API=0, 大型入力=0, 台帳=0)
    print(json.dumps(value, ensure_ascii=False), flush=True)
    return value


def main() -> None:
    """
    機能: 根のレビュー後だけ公開小資料を隔離Chromeで表示し、画像と証跡を保存する。
    引数: なし。root-reviewed CLI専用。
    返り値: None。金融/API/大型入力/台帳は0。根目視はFalseで保存する。
    """
    assert not OUTPUT.exists(), '前回証跡を上書きせず自動再実行しない'
    source, data, provenance = load_display(); expected = expectations(data)
    pure = static_check(source, expected)
    # ----------------------------------------
    # 既存の隔離rendererをメモリ上で接続し、旧sourceと旧画像へ書き込まない。
    spec = importlib.util.spec_from_file_location('00104表示だけの隔離Chrome', RENDERER)
    renderer = importlib.util.module_from_spec(spec); spec.loader.exec_module(renderer)
    OUTPUT.mkdir(parents=True)
    renderer.OUT, renderer.VISUAL, renderer.PROBE = PUBLIC, OUTPUT/'visual', browser_probe(expected)
    started = dict(**provenance, QA_source_SHA256=digest(Path(__file__)), 隔離renderer_SHA256=digest(RENDERER),
        静的照合=pure, 金融=0, API=0, 大型入力=0, 台帳=0)
    (OUTPUT/'開始.json').write_text(json.dumps(started, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    try:
        screens = [renderer.render(source, 'E01銘柄差'+str(width), width, 1250) for width in (1450, 520)]
        preview = '''<script>
showCase('E01_CROSS_B03');const section=[...document.querySelectorAll('section[data-case]')].find(node=>!node.hidden);
const nodes=[section.querySelector('h2'),section.querySelector('p'),...section.querySelectorAll('details')];
for(const node of nodes)if(node.tagName==='DETAILS')node.open=true;
document.querySelector('main').replaceChildren(...nodes);window.scrollTo(0,0);
</script>'''
        screens.append(renderer.render(source, 'B03上位三除外と期間及び買売', 1450, 1250, preview))
        proof = dict(全合格=True, 画面=screens, **started, 根目視確認=False)
        (OUTPUT/PROOF_NAME).write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(proof, ensure_ascii=False), flush=True)
    except Exception:
        (OUTPUT/'表示False.json').write_text(json.dumps(dict(全合格=False, 原因=traceback.format_exc(), **started),
            ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--prepare-only', action='store_true'); actions.add_argument('--check-only', action='store_true')
    actions.add_argument('--root-reviewed', action='store_true'); args = parser.parse_args()
    if args.prepare_only:
        prepare_only()
    elif args.check_only:
        source, data, provenance = load_display()
        print(json.dumps(dict(**static_check(source, expectations(data)), **provenance, Chrome=0,
            金融=0, API=0, 大型入力=0, 台帳=0), ensure_ascii=False), flush=True)
    else:
        main()
