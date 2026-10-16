"""根が公開した32政策と商品別固定組だけを、全セル及び隔離Chromeへ照合する。"""

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
PUBLIC = ROOT/'アルゴリズム調査/00106_支持の強さで注文価格を切り替えるE01'
TITLE = '支持の強さで注文価格を切り替えるE01と全セッション損益'
ACCOUNTING_TITLE = '支持強度別価格制限と銘柄別固定会計.json'
SCHEMA_READY = True
OUTPUT = HERE/'report_review'
PROOF_NAME = '支持強度E01の32政策と固定組及び広狭表示確認.json'
RENDERER = ROOT/'work/wave_v52/review/verify_report.py'
INITIAL = 'E01_SYMBOL_FIXED'
SYMBOLS = ('TOPIX', 'NK225')
LABELS = {'TOPIX': 'TOPIXミニ', 'NK225': '日経マイクロ'}
ACTIVITY_FIELDS = ('paper_candidates', 'known_votes', 'gate_accepted', 'actual_accepted', 'actual_newfills', 'fak_expired')
FAK_FIELDS = ('公開受理', '試行約定', '試行失効', '未試行取消')


def digest(path: Path) -> str:
    """
    機能: 表示 source・公開小資料・QA source の指紋を求める。
    引数: path(Path) は対象ファイル。
    返り値: str は SHA256。金融 source・入力・台帳を読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def money(value: float | None, loss: bool = False) -> str:
    """
    機能: 公開会計から独立に期待する金額・枚数の文字を作る。
    引数: value(float|None)、loss(bool) は数値と損失符号。
    返り値: str は整数文字又は未定義。負零を正規化する。
    """
    if value is None: return '未定義'
    signed = -value if loss else value
    rendered = format(0. if signed == 0 else signed, ',.0f')
    return '0' if rendered == '-0' else rendered


def pct(value: float | None) -> str:
    """
    機能: 公開会計の割合を独立に百分率文字へ変える。
    引数: value(float|None) は保存比率。
    返り値: str は小数1桁百分率又は未定義。
    """
    return '未定義' if value is None else format(value*100, '.1f')+'%'


def expected_tables(item: dict, sessions: list) -> dict:
    """
    機能: 公開小会計の一組又は一政策を、全場・補足の期待セルへ射影する。
    引数: item(dict)、sessions(list[str]) は公開会計と正式場順。
    返り値: dict は表名別のセル。未保存の票・方向・逆行を捏造しない。
    """
    fields = ('profit', 'loss', 'net', 'winning_lots', 'losing_lots')
    index = {(r['session'], r['symbol']): r for r in item['rows']}
    assert len(index) == 66
    tables = dict(sessions=[], stability=[], activity=[], risk=[], parents=[], direction=[], candidates=[], rejection=[], fak=[])
    raw = []
    for session in sessions+[None]:
        label = '全33場合計' if session is None else session.replace('_Day', ' デイ').replace('_Night', ' ナイト')
        values = [item['metrics'][s]['full'][f] if session is None else index[session, s][f] for s in SYMBOLS for f in fields]
        values[1], values[6] = -values[1], -values[6]
        tables['sessions'].append([label]+[money(v) for v in values]); raw.append(values)
    for s in SYMBOLS:
        v = item['metrics'][s]
        for tag, value in (('全33場', v['full']), ('上位3利益場除外', v['top3'])):
            tables['stability'].append([tag, LABELS[s], money(value['net']), pct(value['profit_share']), pct(value['red_all']),
                money(value['mean_positive_session_net']), money(value['worst_session_loss'], True),
                ' / '.join('○' if x else '×' for x in value['tests'].values())])
        for tag, label in (('day', 'デイ'), ('night', 'ナイト'), ('first', '前16場'), ('last', '後17場')):
            value = v[tag]
            tables['activity'].append([label, LABELS[s], money(value['net']), f'{value["active"]}/{value["sessions"]}',
                f'{value["positive"]}/{value["negative"]}/{value["no_trade"]}'])
        saved = item['risk'][s]
        tables['risk'].append([LABELS[s], '今回の統一基準の親診断は未測定'] if saved is None else
            [LABELS[s], str(saved['observed_parents']), money(saved['maximum_fee_liquidation_MAE_yen'], True),
                money(saved.get('two_vote_parents')), money(saved.get('below_four_vote_parents'))])
        full = v['full']; tables['parents'].append([LABELS[s]]+[money(full[k]) for k in ('campaigns', 'winning_campaigns', 'losing_campaigns')])
        if item['directions'] is None or item['directions'][s] is None:
            tables['direction'].append([LABELS[s]+'の方向別親集計は未保存'])
        else:
            for side, label in (('long', '買い'), ('short', '売り')):
                p = item['directions'][s][side]
                tables['direction'].append([label, LABELS[s], money(p['利益']), money(p['損失'], True), money(p['収支']),
                    money(p['勝ち枚数']), money(p['負け枚数'])])
        gu = item['gu_activity'][s] if item['gu_activity'] is not None else None
        if gu is None:
            tables['candidates'].append([LABELS[s]+'の旧全候補母数は未引用'])
            tables['rejection'].append([LABELS[s]+'の旧拒否タグは未引用'])
        for scope, label in (() if gu is None else (('全33', '全33場'), ('Day', 'デイ'), ('Night', 'ナイト'))):
            p = gu[scope]
            tables['candidates'].append([label, LABELS[s]]+[money(p[k]) for k in ACTIVITY_FIELDS])
            tables['rejection'].append([label, LABELS[s]]+[money(p['flags'].get(k, 0)) for k in
                ('票UNKNOWN', '方向票不足', '釣合い不足', '数量ゼロ', '予定静観期限', '実保有予約busy', 'その他の継続取消状態')])
        p = item['fak_summary'][s] if item['fak_summary'] is not None else None
        tables['fak'].append([LABELS[s]+'の旧FAK/取消集計は未引用'] if p is None else
            [LABELS[s]]+[money(p['実政策判断行以下の試行'][k]) for k in FAK_FIELDS]+[money(p[k]) for k in
                ('初受理と実初回差場数', '初受理未約定から後参加への尺度持越し場数', '持越し先の数量差場数')])
    return dict(tables=tables, raw_session_values=raw)


def expectations(data: dict) -> dict:
    """
    機能: 公開32政策と銘柄別固定組の全セル期待値を小JSONだけから作る。
    引数: data(dict) は根が公開した検算会計。
    返り値: dict は33切替・11220全場円枚数・概要・補足・設定の期待値。
    """
    assert data['全合格'] and len(data['sessions']) == 33 and len(data['cases']) == 32
    assert data['new_count'] == 8 and data['reused_count'] == 24
    cases = {INITIAL: data['pair'], **data['cases']}
    projections = {ident: expected_tables(item, data['sessions']) for ident, item in cases.items()}
    overview, settings = [], []
    for ident, item in data['cases'].items():
        for s in SYMBOLS:
            v = item['metrics'][s]; full, trim = v['full'], v['top3']
            overview.append([ident+('旧保存対照' if item['reused'] else '新政策'), LABELS[s], money(full['profit']),
                money(full['loss'], True), money(full['net']), pct(full['profit_share']),
                f'{full["positive"]}/{full["negative"]}/{full["no_trade"]}', money(full['mean_positive_session_net']),
                money(full['worst_session_loss'], True), money(trim['net']),
                ('合格' if full['pass_all'] else '未達')+' / '+('適合' if v['qualified'] else '不適合')])
    for s in SYMBOLS:
        p = data['pair']['parameters'][s]
        settings.append([LABELS[s], f'{p["balance_threshold"]:g}／{p["min_votes"]}票以上', p['execution_label'],
            p['target_label'], data['pair']['selected'][s]])
    count = sum(len(row) for v in projections.values() for rows in v['tables'].values() for row in rows)
    return dict(cases=projections, overview=overview, settings=settings, expected_cells=count+704+10,
        session_cells=11220, policy_session_cells=10880, pair_session_cells=340, initial=INITIAL,
        headings=['TOPIXミニ・片方向上限10枚', '日経マイクロ・片方向上限20枚'],
        required=['全33場の主三基準', '上位3利益場を除く確認', '場ごとに設定を選び直しません',
            '入口：', '途中：', '出口：', '価格時計は物理受信時計の代理', '実板の待ち順位・部分約定・到着遅延は不明'])


def load_display() -> tuple:
    """
    機能: 根公開後のHTML・公開小会計を同bytesで読み表示sourceへ結ぶ。
    引数: なし。
    返り値: tuple[str,dict,dict] はHTML・会計・指紋。金融結果を直接読まない。
    """
    assert SCHEMA_READY, '00106の正式表示schema接続完了前はQAを実行しません。'
    hp, ap = PUBLIC/(TITLE+'.html'), PUBLIC/ACCOUNTING_TITLE
    assert hp.exists() and ap.exists(), '根の公開後だけ表示検査を実行する'
    hb, ab = hp.read_bytes(), ap.read_bytes(); data = json.loads(ab.decode('utf-8-sig'))
    assert digest(HERE/'report.py') == data['sources']['display_source']
    return hb.decode('utf-8'), data, dict(HTML_SHA256=hashlib.sha256(hb).hexdigest(),
        公開会計_SHA256=hashlib.sha256(ab).hexdigest(), 表示source_SHA256=data['sources']['display_source'])


def static_check(source: str, expected: dict) -> dict:
    """
    機能: Chromeなしで公開HTMLの全セル・設定・初期選択を小会計へ照合する。
    引数: source(str)、expected(dict) は公開HTMLと独立期待値。
    返り値: dict は照合件数。画像・金融・Chromeは作らない。
    """
    soup = BeautifulSoup(source, 'html.parser'); selected = soup.select('#case option[selected]')
    assert len(selected) == 1 and selected[0]['value'] == INITIAL
    assert [n['value'] for n in soup.select('#case option')] == list(expected['cases'])
    assert [n['data-case'] for n in soup.select('section[data-case]')] == list(expected['cases'])
    count = 0
    for section in soup.select('section[data-case]'):
        ident = section['data-case']; e = expected['cases'][ident]
        for name, rows in e['tables'].items():
            actual = [[c.get_text() for c in r.find_all(['td', 'th'], recursive=False)] for r in section.select('table.'+name+' tbody tr')]
            assert actual == rows, (ident, name); count += sum(len(r) for r in rows)
        for i, row in enumerate(section.select('table.sessions tbody tr')):
            cells = row.find_all(['td', 'th'], recursive=False)[1:]
            for j, c in enumerate(cells): assert abs(float(c['data-value'])-e['raw_session_values'][i][j]) < 1e-5
    for selector, rows in (('#overview', expected['overview']), ('table.settings', expected['settings'])):
        actual = [[c.get_text() for c in r.find_all(['td', 'th'], recursive=False)] for r in soup.select(selector+' tbody tr')]
        assert actual == rows, selector; count += sum(len(r) for r in rows)
    text = soup.body.get_text(); assert all(word in text for word in expected['required'])
    assert count == expected['expected_cells']
    assert not any(c.get_text() == '-0' for c in soup.select('td'))
    return dict(全合格=True, 全セル=count, 新旧政策円枚数=10880, 固定組円枚数=340, 切替=33, 初期選択=INITIAL)


def browser_probe(expected: dict) -> str:
    """
    機能: 全33変更イベントとDOMセル及び暗色・横溢れの検査scriptを作る。
    引数: expected(dict) は公開会計だけから作った独立期待値。
    返り値: str は検査script。作成時はChromeを起動しない。
    """
    payload = json.dumps(expected, ensure_ascii=False, allow_nan=False).replace('</', '<\\/')
    return '''<script>
/**
 * 公開された一表を文字セル単位で照合する。
 * @param {HTMLTableElement} table - 対象表。
 * @param {Array<Array<string>>} expected - 公開小会計による期待値。
 * @returns {number} 照合セル数。
 */
function verifyTable(table,expected){if(!table)throw Error('表なし');const rows=table.tBodies[0].rows;let count=0;if(rows.length!==expected.length)throw Error('行数');for(let i=0;i<rows.length;i++){if(rows[i].cells.length!==expected[i].length)throw Error('列数');for(let j=0;j<rows[i].cells.length;j++){if(rows[i].cells[j].textContent!==expected[i][j])throw Error('文字差:'+i+'/'+j);count++;}}return count;}
/**
 * 固定組と32政策を切り替えて全セルと広狭配置を検査する。
 * @returns {object} 件数・背景・画面幅。通信や金融再生は行わない。
 */
function verifyReport(){
 const expected=__PAYLOAD__,picker=document.getElementById('case');let count=0;
 if(picker.value!==expected.initial)throw Error('初期選択');
 const ids=[...picker.options].map(o=>o.value);
 if(ids.length!==33||new Set(ids).size!==33||ids.some(id=>!(id in expected.cases)))throw Error('33選択');
 for(const[id,e]of Object.entries(expected.cases)){
  picker.value=id;picker.dispatchEvent(new Event('change',{bubbles:true}));
  const visible=[...document.querySelectorAll('section[data-case]')].filter(s=>!s.hidden);
  if(visible.length!==1||visible[0].dataset.case!==id)throw Error('切替:'+id);
  const section=visible[0];
  for(const[name,rows]of Object.entries(e.tables))count+=verifyTable(section.querySelector('table.'+name),rows);
  const rows=section.querySelector('table.sessions').tBodies[0].rows;
  for(let i=0;i<34;i++)for(let j=0;j<10;j++){
   const value=Number(rows[i].cells[j+1].dataset.value);
   if(!Number.isFinite(value)||Math.abs(value-e.raw_session_values[i][j])>1e-5)throw Error('原値:'+id+'/'+i+'/'+j);
  }
  const heads=section.querySelector('table.sessions').tHead.rows[0].cells;
  if(heads[1].textContent!==expected.headings[0]||heads[2].textContent!==expected.headings[1])throw Error('数量上限');
  if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ:'+id);
  if(/NaN|Infinity|undefined/.test(section.innerText))throw Error('不正表示');
 }
 count+=verifyTable(document.querySelector('#overview'),expected.overview);
 count+=verifyTable(document.querySelector('table.settings'),expected.settings);
 for(const word of expected.required)if(!document.querySelector('main').textContent.includes(word))throw Error('説明:'+word);
 picker.value=expected.initial;picker.dispatchEvent(new Event('change',{bubbles:true}));
 const bg=getComputedStyle(document.body).backgroundColor;
 if(bg!=='rgb(11, 17, 32)')throw Error('暗色');
 if(count!==expected.expected_cells)throw Error('件数');
 return{全合格:true,全セル:count,新旧政策円枚数:10880,固定組円枚数:340,切替:33,背景:bg,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,金融:0,API:0,input:0,ledger:0};
}
try{document.body.dataset.check=JSON.stringify(verifyReport());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''.replace('__PAYLOAD__', payload)


def main() -> None:
    """
    機能: 根レビュー後だけ新所有域に隔離Chromeの三画像と証跡を作る。
    引数: CLI --prepare-only/--check-only/--root-reviewed。
    返り値: None。準備は公開読取0、Chromeは根実行、根目視はFalseで保存する。
    """
    parser = argparse.ArgumentParser(); mode = parser.add_mutually_exclusive_group(required=True)
    for name in ('prepare-only', 'check-only', 'root-reviewed'): mode.add_argument('--'+name, action='store_true')
    args = parser.parse_args()
    if args.prepare_only:
        print(json.dumps(dict(prepared=True, QA_source_SHA256=digest(Path(__file__)),
            証跡予定=(OUTPUT/PROOF_NAME).relative_to(ROOT).as_posix(), 新旧32政策円枚数=10880,
            固定組円枚数=340, 切替=33, schema接続済み=SCHEMA_READY,
            広狭=[1450, 520], 画像=3, 公開読取=0, Chrome=0, 金融=0, API=0, input=0, ledger=0), ensure_ascii=False)); return
    source, data, provenance = load_display(); expected = expectations(data); pure = static_check(source, expected)
    if args.check_only:
        print(json.dumps(dict(**pure, **provenance, Chrome=0, 金融=0, API=0, input=0, ledger=0), ensure_ascii=False)); return
    assert not OUTPUT.exists(), '証跡を上書きせず、失敗後は自動再実行しない'
    spec = importlib.util.spec_from_file_location('00106表示だけの隔離Chrome', RENDERER)
    renderer = importlib.util.module_from_spec(spec); spec.loader.exec_module(renderer)
    OUTPUT.mkdir(parents=True); renderer.OUT, renderer.VISUAL, renderer.PROBE = PUBLIC, OUTPUT/'visual', browser_probe(expected)
    started = dict(**provenance, QA_source_SHA256=digest(Path(__file__)), 隔離renderer_SHA256=digest(RENDERER),
        静的照合=pure, 金融=0, API=0, input=0, ledger=0)
    (OUTPUT/'開始.json').write_text(json.dumps(started, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    try:
        screens = [renderer.render(source, '支持強度E01'+str(w), w, 1250) for w in (1450, 520)]
        preview = '''<script>showCase('E01_SYMBOL_FIXED');const s=[...document.querySelectorAll('section[data-case]')].find(s=>!s.hidden);const notes=[...s.querySelectorAll('details')].reverse();for(const d of notes)d.open=true;document.querySelector('main').replaceChildren(s.querySelector('h2'),...notes);window.scrollTo(0,0);</script>'''
        screens.append(renderer.render(source, '固定設定の基準と候補不足', 1450, 1250, preview))
        proof = dict(全合格=True, 画面=screens, **started, 根目視確認=False)
        (OUTPUT/PROOF_NAME).write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(proof, ensure_ascii=False), flush=True)
    except Exception:
        (OUTPUT/'表示False.json').write_text(json.dumps(dict(全合格=False, 原因=traceback.format_exc(), **started), ensure_ascii=False, indent=2)+'\n', encoding='utf-8'); raise


if __name__ == '__main__':
    main()
