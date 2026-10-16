"""根が公開した会計とHTMLだけを照合し、隔離表示の検査を準備する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import traceback

from bs4 import BeautifulSoup

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT/'アルゴリズム調査/00107_保有容量と一取引利益の再検証'
TITLE = '容量を使うE01と一取引平均損益及び全セッション損益'
ACCOUNTING_TITLE = '容量別E01の一取引平均と全場会計.json'
SCHEMA_READY = False
OUTPUT = HERE/'report_review'
PROOF_NAME = '容量E01の十四政策と全親平均及び広狭表示確認.json'
RENDERER = ROOT/'work/wave_v52/review/verify_report.py'
INITIAL = 'E01_SYMBOL_FIXED'
SYMBOLS = ('TOPIX', 'NK225')
LABELS = {'TOPIX': 'TOPIXミニ', 'NK225': '日経マイクロ'}
CAPACITY = {'TOPIX': 10, 'NK225': 20}
MULTIPLIER = {'TOPIX': 1000., 'NK225': 10.}


def digest(path: Path) -> str:
    """
    機能: 小source又は公開資料の指紋を取得する。
    引数: path(Path)は保存位置。
    返り値: strはSHA256。金融結果・入力・台帳を読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value: float | None, decimals: int = 0) -> str:
    """
    機能: 公開数値を独立に桁区切り表示へ変換する。
    引数: value(float|None)、decimals(int)は数値と小数桁。
    返り値: strは表示値。負の0は0へ正規化し、Noneを0にしない。
    """
    if value is None: return '未定義'
    text = f'{value:,.{decimals}f}'
    return text[1:] if text.startswith('-') and float(text.replace(',', '')) == 0 else text


def percent(value: float | None) -> str:
    """
    機能: 公開割合を百分率へ変換する。
    引数: value(float|None)は割合又は未定義。
    返り値: strは百分率又は未定義。
    """
    return '未定義' if value is None else f'{value*100:.1f}%'


def expected_tables(item: dict, sessions: list) -> tuple:
    """
    機能: 公開会計の一候補から全表の期待文字と原円枚数を作る。
    引数: item(dict)、sessions(list[str])は固定候補と全場順。
    返り値: tuple[dict,list]は表ごとの文字セルと円枚数原値。
    """
    tables = dict(sessions=[], economic=[], capacity=[], activity=[], risk=[], **{'session-economic': []})
    numeric = []
    indexed = {(r['session'], r['symbol']): r for r in item['rows']}
    fields = ('profit', 'loss', 'net', 'winning_lots', 'losing_lots')
    for session in sessions+[None]:
        values = []
        for s in SYMBOLS:
            row = item['metrics'][s]['full'] if session is None else indexed[session, s]
            values.extend(-row[k] if k == 'loss' else row[k] for k in fields)
        numeric.append(values)
        title = '合計' if session is None else session.replace('_Day', ' デイ').replace('_Night', ' ナイト')
        tables['sessions'].append([title]+[number(v) for v in values])
    for s in SYMBOLS:
        metric = item['metrics'][s]
        for title, f in (('全33場', metric['full']), ('上位3利益場除外', metric['top3'])):
            tables['economic'].append([LABELS[s], title, number(f['campaigns']), number(f['mean_parent_net'], 1),
                '円床未指定' if f['economic_floor'] is None else ('○' if f['economic_pass'] else '未達'),
                number(f['mean_parent_capacity_net_points'], 4), percent(f['profit_share']), percent(f['red_all']),
                number(f['mean_positive_session_net'], 1), number(-f['worst_session_loss'])])
        for title, f in (('デイ', metric['day']), ('ナイト', metric['night'])):
            if f is not None: tables['activity'].append([LABELS[s], title, str(f['active'])+'/'+str(f['sessions']),
                number(f['campaigns']), number(f['net']), number(f['mean_parent_net'], 1)])
        saved = item['capacity'][s]
        tables['capacity'].append([LABELS[s], str(CAPACITY[s]), number(None if saved is None else saved['mean_initial_quantity'], 2),
            percent(None if saved is None else saved['mean_initial_capacity_fraction']),
            number(None if saved is None else saved['maximum_same_side_holding']),
            percent(None if saved is None else saved['maximum_holding_capacity_fraction']),
            number(metric['full']['capacity_net_points'], 4)])
        saved = item['risk'][s]
        tables['risk'].append([LABELS[s], number(None if saved is None else saved['observed_parents']),
            number(None if saved is None else saved['maximum_fee_liquidation_MAE_yen']),
            number(None if saved is None else saved['two_vote_parents'])])
        for r in (v for v in item['rows'] if v['symbol'] == s):
            own = [p for p in item['parents'] if p['symbol'] == s and p['session'] == r['session']]
            qs = [p['entry_quantity'] for p in own]
            tables['session-economic'].append([r['session'], LABELS[s], number(r['campaigns']),
                number(r['net']/r['campaigns'] if r['campaigns'] else None, 1),
                number(r['net']/(CAPACITY[s]*MULTIPLIER[s]), 4),
                number(statistics.mean(qs) if qs else None, 2),
                number(max((p['maximum_held_quantity'] for p in own), default=0)),
                number(max((p['parent_mae_yen'] for p in own), default=None))])
    return tables, numeric


def overview_rows(data: dict, identifiers: list) -> list:
    """
    機能: 公開会計から主表と十四候補一覧の期待セルを作る。
    引数: data(dict)、identifiers(list[str])は公開会計と対象ID。
    返り値: list[list[str]]は十一列の期待値。
    """
    rows = []
    for cid in identifiers:
        item = data['pair'] if cid == INITIAL else data['cases'][cid]
        for s in SYMBOLS:
            m = item['metrics'][s]; f = m['full']
            rows.append([cid, LABELS[s], number(f['profit']), number(-f['loss']), number(f['net']),
                number(f['campaigns']), number(f['mean_parent_net'], 1), percent(f['profit_share']),
                str(f['positive'])+'/'+str(f['negative'])+'/'+str(f['no_trade']),
                '○' if f['primary_pass'] else '未達', '○' if m['robustness_pass'] else '未達'])
    return rows


def expectations(data: dict) -> dict:
    """
    機能: 根公開の小会計を基準に、十五切替と全表の期待値を固定する。
    引数: data(dict)は公開会計のみ。
    返り値: dictはDOM・原値・見出し・必要短文の期待値。
    """
    assert data['全合格'] and data['new_count'] == len(data['cases']) == 14
    cases = {}
    for cid, item in {INITIAL: data['pair'], **data['cases']}.items():
        tables, numeric = expected_tables(item, data['sessions'])
        cases[cid] = dict(tables=tables, raw_session_values=numeric)
    settings = [[LABELS[s], data['pair']['selected'][s], data['pair']['parameters'][s]['quantity_label'],
        data['pair']['parameters'][s]['entry_label'], data['pair']['parameters'][s]['exit_label']] for s in SYMBOLS]
    overview = dict(principal=overview_rows(data, [INITIAL]), candidates=overview_rows(data, list(data['cases'])))
    total = sum(len(row) for v in cases.values() for rows in v['tables'].values() for row in rows)
    total += sum(len(row) for rows in overview.values() for row in rows)+sum(len(r) for r in settings)
    return dict(initial=INITIAL, cases=cases, settings=settings, overview=overview, expected_cells=total,
        numeric_session_cells=len(cases)*(len(data['sessions'])+1)*10,
        required=['損失込み', '1,032.5円', '9,789円', '円額床は未指定', '部分約定', '既知内選択', '上位3除外'],
        headings=['TOPIXミニ・保有上限10枚', '日経マイクロ・保有上限20枚'])


def load_display() -> tuple:
    """
    機能: 根が完成公開したHTMLと小会計を表示sourceへ結ぶ。
    引数: なし。PUBLIC(Path)は新所有公開領域。
    返り値: tuple[str,dict,dict]はHTML・公開会計・指紋。準備時は呼ばない。
    """
    assert SCHEMA_READY, '00107正式表示schema接続前は公開会計を読みません。'
    hp, ap = PUBLIC/(TITLE+'.html'), PUBLIC/ACCOUNTING_TITLE
    hb, ab = hp.read_bytes(), ap.read_bytes()
    data = json.loads(ab.decode('utf-8-sig'))
    assert data['sources']['display_source'] == digest(HERE/'report.py')
    return hb.decode('utf-8'), data, dict(公開HTML_SHA256=hashlib.sha256(hb).hexdigest(),
        公開会計_SHA256=hashlib.sha256(ab).hexdigest(), 表示source_SHA256=data['sources']['display_source'])


def static_check(source: str, expected: dict) -> dict:
    """
    機能: 公開HTMLを公開会計と全セル・原値・初期切替まで照合する。
    引数: source(str)、expected(dict)はHTMLと独立期待値。
    返り値: dictは純表示検査。Chromeを起動しない。
    """
    soup = BeautifulSoup(source, 'html.parser')
    selected = soup.select('#case option[selected]')
    assert len(selected) == 1 and selected[0]['value'] == INITIAL
    assert [o['value'] for o in soup.select('#case option')] == list(expected['cases'])
    assert [s['data-case'] for s in soup.select('section[data-case]')] == list(expected['cases'])
    count = 0
    for section in soup.select('section[data-case]'):
        item = expected['cases'][section['data-case']]
        for name, rows in item['tables'].items():
            actual = [[c.get_text() for c in row.find_all(['td', 'th'], recursive=False)] for row in section.select('table.'+name+' tbody tr')]
            assert actual == rows, (section['data-case'], name)
            count += sum(len(r) for r in rows)
        for i, row in enumerate(section.select('table.sessions tbody tr')):
            for j, c in enumerate(row.find_all(['td', 'th'], recursive=False)[1:]):
                assert abs(float(c['data-value'])-item['raw_session_values'][i][j]) < 1e-5
    for selector, rows in (('table.principal', expected['overview']['principal']),
        ('table.all-cases', expected['overview']['candidates']), ('table.settings', expected['settings'])):
        actual = [[c.get_text() for c in row.find_all(['td', 'th'], recursive=False)] for row in soup.select(selector+' tbody tr')]
        assert actual == rows, selector
        count += sum(len(r) for r in rows)
    assert all(word in soup.body.get_text() for word in expected['required'])
    assert not any(c.get_text() in ('-0', '−0') for c in soup.select('td'))
    assert count == expected['expected_cells']
    return dict(全合格=True, 全セル=count, 全候補と固定組円枚数=expected['numeric_session_cells'], 切替=len(expected['cases']))


# ----------------------------------------
def browser_probe(expected: dict) -> str:
    """
    機能: 十五切替・DOM原値・暗色・横溢れを検査するscriptを準備する。
    引数: expected(dict)は公開小会計による独立期待値。
    返り値: strは隔離表示用script。作成時はChrome・通信を使わない。
    """
    payload = json.dumps(expected, ensure_ascii=False, allow_nan=False).replace('</', '<\\/')
    return '''<script>
/**
 * 公開表を期待文字列へ照合する。
 * @param {HTMLTableElement} table - 対象表。
 * @param {Array<Array<string>>} expected - 期待セル。
 * @returns {number} 検査セル数。
 */
function verifyTable(table,expected){if(!table)throw Error('表なし');const rows=table.tBodies[0].rows;let count=0;if(rows.length!==expected.length)throw Error('行数');for(let i=0;i<rows.length;i++){if(rows[i].cells.length!==expected[i].length)throw Error('列数');for(let j=0;j<rows[i].cells.length;j++){if(rows[i].cells[j].textContent!==expected[i][j])throw Error('セル:'+i+'/'+j);count++;}}return count;}
/**
 * 固定組と十四政策を切り替え、全表と広狭配置を確認する。
 * @returns {object} 検査件数と画面幅。金融・通信は行わない。
 */
function verifyReport(){const expected=__PAYLOAD__,picker=document.getElementById('case');let count=0;if(picker.value!==expected.initial)throw Error('初期');const ids=[...picker.options].map(o=>o.value);if(ids.length!==Object.keys(expected.cases).length||ids.some(id=>!(id in expected.cases)))throw Error('候補');for(const[id,e]of Object.entries(expected.cases)){picker.value=id;picker.dispatchEvent(new Event('change',{bubbles:true}));const visible=[...document.querySelectorAll('section[data-case]')].filter(s=>!s.hidden);if(visible.length!==1||visible[0].dataset.case!==id)throw Error('切替:'+id);const section=visible[0];for(const[name,rows]of Object.entries(e.tables))count+=verifyTable(section.querySelector('table.'+name),rows);const rows=section.querySelector('table.sessions').tBodies[0].rows;for(let i=0;i<e.raw_session_values.length;i++)for(let j=0;j<10;j++){const value=Number(rows[i].cells[j+1].dataset.value);if(!Number.isFinite(value)||Math.abs(value-e.raw_session_values[i][j])>1e-5)throw Error('原値');}const h=section.querySelector('table.sessions').tHead.rows[0].cells;if(h[1].textContent!==expected.headings[0]||h[2].textContent!==expected.headings[1])throw Error('上限');if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');if(/NaN|Infinity|undefined/.test(section.innerText))throw Error('不正数');}count+=verifyTable(document.querySelector('table.principal'),expected.overview.principal);count+=verifyTable(document.querySelector('table.all-cases'),expected.overview.candidates);count+=verifyTable(document.querySelector('table.settings'),expected.settings);for(const word of expected.required)if(!document.querySelector('main').textContent.includes(word))throw Error('説明:'+word);picker.value=expected.initial;picker.dispatchEvent(new Event('change',{bubbles:true}));const bg=getComputedStyle(document.body).backgroundColor;if(bg!=='rgb(11, 17, 32)')throw Error('暗色');if(count!==expected.expected_cells)throw Error('件数');return{全合格:true,全セル:count,円枚数:expected.numeric_session_cells,切替:ids.length,背景:bg,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,金融:0,API:0,input:0,ledger:0};}
try{document.body.dataset.check=JSON.stringify(verifyReport());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''.replace('__PAYLOAD__', payload)


def main() -> None:
    """
    機能: 準備又は根のレビュー後だけ広狭三画面と証跡を新所有域へ作る。
    引数: CLI --prepare-only/--check-only/--root-reviewed。
    返り値: None。準備は公開読0、Chrome実行は根専用、目視済みはFalseで保存。
    """
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ('prepare-only', 'check-only', 'root-reviewed'): mode.add_argument('--'+name, action='store_true')
    args = parser.parse_args()
    if args.prepare_only:
        print(json.dumps(dict(prepared=True, QA_source_SHA256=digest(Path(__file__)), schema接続済み=SCHEMA_READY,
            証跡予定=(OUTPUT/PROOF_NAME).relative_to(ROOT).as_posix(), 切替=15, 円枚数セル=5100,
            広狭=[1450, 520], 画像=3, Chrome=0, 公開読取=0, 金融=0, API=0, input=0, ledger=0), ensure_ascii=False)); return
    source, data, provenance = load_display()
    expected = expectations(data)
    pure = static_check(source, expected)
    if args.check_only:
        print(json.dumps(dict(**pure, **provenance, Chrome=0, 金融=0, API=0, input=0, ledger=0), ensure_ascii=False)); return
    assert not OUTPUT.exists(), '証跡を上書きせず、失敗後に自動再実行しない。'
    spec = importlib.util.spec_from_file_location('00107表示専用隔離Chrome', RENDERER)
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    OUTPUT.mkdir(parents=True)
    renderer.OUT, renderer.VISUAL, renderer.PROBE = PUBLIC, OUTPUT/'visual', browser_probe(expected)
    started = dict(**provenance, QA_source_SHA256=digest(Path(__file__)), 隔離renderer_SHA256=digest(RENDERER), 静的照合=pure,
        金融=0, API=0, input=0, ledger=0)
    (OUTPUT/'開始.json').write_text(json.dumps(started, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    try:
        images = [renderer.render(source, '容量E01'+str(width), width, 1250) for width in (1450, 520)]
        preview = '''<script>showCase('E01_SYMBOL_FIXED');const s=[...document.querySelectorAll('section[data-case]')].find(n=>!n.hidden);const details=s.querySelector('details');details.open=true;document.querySelector('main').replaceChildren(s.querySelector('h2'),details);window.scrollTo(0,0);</script>'''
        images.append(renderer.render(source, '全親平均と容量及び上位三除外', 1450, 1250, preview))
        proof = dict(全合格=True, 画面=images, **started, 根目視確認=False)
        (OUTPUT/PROOF_NAME).write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(proof, ensure_ascii=False))
    except Exception:
        (OUTPUT/'表示False.json').write_text(json.dumps(dict(全合格=False, 原因=traceback.format_exc(), **started), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise


if __name__ == '__main__':
    main()
