"""損失停止修正四比較の公開小会計を、隔離Chromeの広狭画面へ照合する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

from bs4 import BeautifulSoup

import loss_anchor_report as report

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
OUTPUT = report.HERE/'loss_anchor_review'


def expectations(data: dict) -> dict:
    """
    機能: 公開会計から全場1360、概要88、両停止線・不変B・旧勝ち表の期待値を作る。
    引数: data(dict)は完成した公開小会計。
    返り値: dictは表示期待値。金融・原入力・台帳を読まない。
    """
    assert data['全合格'] and len(data['cases']) == 4 and len(data['sessions']) == 33
    number, percent = report.base.range_report.number, report.base.risk_sizing_report.percent
    tables, overview, details = {}, [], {}
    fields = ('profit', 'loss', 'net', 'winning_lots', 'losing_lots')
    for identifier, case in data['cases'].items():
        index = {(r['session'], r['symbol']): r for r in case['rows']}
        assert len(index) == 66
        table = [[index[session, s][f] for s in report.SYMBOLS for f in fields] for session in data['sessions']]
        table.append([case['summary'][s][f] for s in report.SYMBOLS for f in fields])
        tables[identifier] = table
        old_rows, anchor_rows, top3_rows, contributions, recovery = [], [], [], [], []
        for s in report.SYMBOLS:
            v, old = case['summary'][s], case['comparison']['summary'][s]
            status = ' / '.join('達成' if v['tests'][k] else '未達' for k in report.TESTS)
            cells = [report.base.risk_sizing_report.label(case['config'])+identifier, report.LABELS[s],
                number(v['profit']), number(v['loss']), number(v['net']), percent(v['profit_share']),
                str(v['negative'])+'/33 ('+percent(v['red_all'])+')', number(v['mean_positive_session_net'], 1),
                number(v['worst_session_loss']), status, str(v['positive'])+'/'+str(v['negative'])+'/'+str(v['no_trade'])]
            overview.append(dict(id=identifier, symbol=s, cells=cells))
            old_rows.append([report.LABELS[s], number(v['net']), number(old['net']), number(v['net']-old['net']),
                str(v['positive'])+'/'+str(old['positive']), str(v['negative'])+'/'+str(old['negative']),
                percent(v['profit_share'])+' / '+percent(old['profit_share'])])
            a = case['anchor_summary'][s]
            anchor_rows.append([report.LABELS[s], str(a['受理あり'])+'/33', str(a['受理あり実新規なし']),
                number(a['初回受理q最小'])+'〜'+number(a['初回受理q最大']),
                number(a['固定目標最小'])+'〜'+number(a['固定目標最大']),
                number(a['固定損失線最小'])+'〜'+number(a['固定損失線最大']), number(a['新規数量選択予算円'])])
            for name, origin in (('損失線修正', case), ('旧goal版', case['comparison'])):
                full, tail = origin['summary'][s], origin['top3'][s]
                top3_rows.append([name, report.LABELS[s], number(full['median']), number(tail['net']),
                    percent(tail['profit_share']), str(tail['negative'])+'/'+str(tail['sessions']),
                    number(tail['mean_positive_session_net'], 1), number(tail['worst_session_loss'])])
            d = case['diagnosis'][s]
            contributions.append([report.LABELS[s]]+[number(d[f]) for f in report.FIVE]+[str(d['元勝ち親が赤字化'])])
            recovery.extend([report.LABELS[s], p['session'].replace('_Day', ' デイ').replace('_Night', ' ナイト'),
                str(p['parent']), number(p['old_net']), number(p['new_net'])] for p in case['recovery_examples'][s])
        details[identifier] = dict(old_rows=old_rows, anchor_rows=anchor_rows, top3_rows=top3_rows,
                                   contributions=contributions, recovery=recovery, baseline_id=case['comparison']['id'])
    counts = data['both_test_counts']
    intro = ['最新3基準を両商品で満たす条件は'+str(data['both_goal_pass'])+'/4件。収支が両方黒字の条件は'+str(data['both_net_positive'])+'/4件。',
        '両商品での達成数：利益割合 '+str(counts[report.TESTS[0]])+'/4、赤字率 '+str(counts[report.TESTS[1]])+'/4、一場損失 '+str(counts[report.TESTS[2]])+'/4。各条件の未達部分は概要表に示す。']
    return dict(tables=tables, overview=overview, details=details, intro=intro,
        labels=[s.replace('_Day', ' デイ').replace('_Night', ' ナイト') for s in data['sessions']]+['全33合計'])


def load_display(require_public: bool) -> tuple:
    """
    機能: 公開表示を読むか、公開前check-onlyで完成小会計から表示をメモリ上だけに作る。
    引数: require_public(bool)はChrome実行時の公開必須資格。
    返り値: tuple[str,dict,dict]はHTML、表示会計、指紋。ファイルを公開しない。
    """
    hp, ap = report.PUBLIC/(report.TITLE+'.html'), report.PUBLIC/report.ACCOUNTING_TITLE
    assert hp.exists() == ap.exists(), '公開HTML/会計の片側だけを利用しない'
    if hp.exists():
        hb, ab = hp.read_bytes(), ap.read_bytes()
        return hb.decode('utf-8'), json.loads(ab.decode('utf-8-sig')), dict(
            公開済み資料=True, HTML_SHA256=hashlib.sha256(hb).hexdigest(), 公開会計_SHA256=hashlib.sha256(ab).hexdigest())
    assert not require_public, '根による公開完了後だけChromeへ渡す'
    data = report.load_and_build(); source = report.render(data)
    return source, data, dict(公開済み資料=False, メモリ確認のみ=True,
        HTML_SHA256=hashlib.sha256(source.encode('utf-8')).hexdigest(),
        メモリ会計_SHA256=hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')).hexdigest())


def check_only() -> dict:
    """
    機能: Chromeなしで期待件数と実HTMLの全セル・表を純照合する。
    引数: なし。
    返り値: dictは件数と小指紋。公開・Chrome・金融実行・API・大入力・台帳は0。
    """
    source, data, provenance = load_display(False)
    expected = expectations(data); soup = BeautifulSoup(source, 'html.parser')
    counts = dict(全場円枚数=0, 概要=0, 同母比較=0, 受理停止線B=0, 上位三除外=0, 寄与=0, 旧勝ち例=0)
    sections = soup.select('section[data-case]'); assert len(sections) == 4
    for section in sections:
        identifier = section['data-case']; e = expected['details'][identifier]
        table = section.select_one('table.sessions'); rows = table.select('tbody tr'); assert len(rows) == 34
        for i, row in enumerate(rows):
            cells = row.select('td'); assert len(cells) == 11 and cells[0].get_text() == expected['labels'][i]
            for j in range(10):
                assert abs(float(cells[j+1].get_text().replace(',', ''))-expected['tables'][identifier][i][j]) <= .500001
                counts['全場円枚数'] += 1
        for selector, name, key in (('fixed-comparison', '同母比較', 'old_rows'), ('anchors', '受理停止線B', 'anchor_rows'),
                                    ('top3', '上位三除外', 'top3_rows'), ('contributions', '寄与', 'contributions'),
                                    ('recovery-examples', '旧勝ち例', 'recovery')):
            actual = [[cell.get_text() for cell in r.select('td')] for r in section.select('table.'+selector+' tbody tr')]
            assert actual == e[key], (identifier, selector)
            counts[name] += sum(len(r) for r in actual)
    rows = soup.select('#overview tbody tr'); assert len(rows) == 8
    for i, row in enumerate(rows):
        e = expected['overview'][i]
        assert row['data-case-id'] == e['id'] and row['data-symbol'] == e['symbol']
        assert [c.get_text() for c in row.select('td')] == e['cells']
        counts['概要'] += len(e['cells'])
    assert [p.get_text() for p in soup.select('main>p')[:2]] == expected['intro']
    assert {k: counts[k] for k in counts if k != '旧勝ち例'} == dict(全場円枚数=1360, 概要=88, 同母比較=56, 受理停止線B=56, 上位三除外=128, 寄与=56)
    assert counts['旧勝ち例'] == sum(len(e['recovery'])*5 for e in expected['details'].values())
    proof = dict(全合格=True, 件数=counts, **provenance, 公開実行=0, Chrome=0, 金融実行=0, API=0, 大入力=0, 台帳=0)
    print(json.dumps(proof, ensure_ascii=False), flush=True)
    return proof


def main() -> None:
    """
    機能: root確認後だけ隔離Chromeで四切替・概要・両線/B・旧勝ち表を検査する。
    引数: なし。完成HTMLと公開JSONだけを使用する。
    返り値: None。画像と証跡を保存し、根の目視は未確認として保持する。
    """
    assert not OUTPUT.exists(), '前回表示証跡は上書きせず、自動再実行しない'
    source, data, provenance = load_display(True)
    expected = expectations(data)
    # ----------------------------------------
    # 共通の隔離Chromeへ公開HTML複製だけを渡す。
    spec = importlib.util.spec_from_file_location('損失線修正表示だけの隔離Chrome', report.ROOT/'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    OUTPUT.mkdir(parents=True)
    renderer.OUT, renderer.VISUAL = report.PUBLIC, OUTPUT/'visual'
    payload = json.dumps(expected, ensure_ascii=False, allow_nan=False).replace('</', '<\\/')
    renderer.PROBE = '''<script>
/**
 * 機能: 一つの補足表を公開小会計の期待文字へ照合する。
 * @param {HTMLTableElement} table - 対象補足表。
 * @param {Array<Array<string>>} expected - 行と列の期待表示。
 * @param {string} name - 差異の同定名。
 * @returns {number} 照合したセル数。
 */
function checkAnchorTable(table,expected,name){
 if(!table)throw Error('補足表なし:'+name);const rows=table.tBodies[0].rows;let count=0;
 if(rows.length!==expected.length)throw Error('補足行数:'+name);
 for(let i=0;i<expected.length;i++){
  if(rows[i].cells.length!==expected[i].length)throw Error('補足列数:'+name);
  for(let j=0;j<expected[i].length;j++){if(rows[i].cells[j].textContent!==expected[i][j])throw Error('補足表示差:'+name+'/'+i+'/'+j);count++;}
 }
 return count;
}
/**
 * 機能: 四条件の全場・概要・同母旧版・目標固定・上位三除外を表示会計へ照合する。
 * 引数: なし。
 * @returns {object} 件数、画面幅、数値と暗色の検査結果。
 */
function verifyLossAnchorDisplay(){
 const data=__PAYLOAD__,first=document.getElementById('case').value;
 let amounts=0,summary=0,old=0,anchors=0,top3=0,contributions=0,recovery=0;
 const options=[...document.getElementById('case').options].map(x=>x.value);
 if(options.length!==4||new Set(options).size!==4||options.some(id=>!(id in data.tables)))throw Error('四条件選択肢');
 for(const [id,expected] of Object.entries(data.tables)){
  showCase(id);const visible=[...document.querySelectorAll('[data-case]')].filter(node=>!node.hidden);
  if(visible.length!==1||visible[0].dataset.case!==id||document.getElementById('case').value!==id)throw Error('条件切替');
  const section=visible[0],table=section.querySelector('table.sessions'),rows=table.tBodies[0].rows;
  const headers=table.tHead.rows[0].cells;
  if(headers[1].textContent!=='TOPIXミニ：新規1〜5枚・上限10枚'||headers[2].textContent!=='日経マイクロ：新規1〜10枚・上限20枚')throw Error('可変数量ヘッダ');
  if(rows.length!==34)throw Error('全33場と総計');
  for(let i=0;i<34;i++){
   if(rows[i].cells.length!==11||rows[i].cells[0].textContent!==data.labels[i])throw Error('場名又は十列');
   for(let j=0;j<10;j++){
    const number=Number(rows[i].cells[j+1].textContent.replaceAll(',','').trim());
    if(!Number.isFinite(number)||Math.abs(number-expected[i][j])>.500001)throw Error('円枚数差:'+id+'/'+i+'/'+j);amounts++;
   }
  }
  const e=data.details[id],folds=section.querySelectorAll('details');
  if(folds.length!==4||!folds[0].querySelector('small').textContent.includes(e.baseline_id))throw Error('比較元同定');
  old+=checkAnchorTable(section.querySelector('table.fixed-comparison'),e.old_rows,'同母旧goal版');
  anchors+=checkAnchorTable(section.querySelector('table.anchors'),e.anchor_rows,'受理qと両停止線及び不変B');
  top3+=checkAnchorTable(section.querySelector('table.top3'),e.top3_rows,'上位三場除外');
  contributions+=checkAnchorTable(section.querySelector('table.contributions'),e.contributions,'五寄与');
  recovery+=checkAnchorTable(section.querySelector('table.recovery-examples'),e.recovery,'旧勝ち赤字化例');
  if(document.documentElement.scrollWidth>innerWidth+2)throw Error('切替後本文横溢れ');
 }
 const rows=document.querySelector('#overview tbody').rows;if(rows.length!==8)throw Error('概要八行');
 for(let i=0;i<8;i++){
  const e=data.overview[i],r=rows[i];if(r.dataset.caseId!==e.id||r.dataset.symbol!==e.symbol||r.cells.length!==11)throw Error('概要同定');
  for(let j=0;j<11;j++){if(r.cells[j].textContent!==e.cells[j])throw Error('概要表示差:'+i+'/'+j);summary++;}
 }
 const intro=document.querySelectorAll('main>p');
 if(intro[0].textContent!==data.intro[0]||intro[1].textContent!==data.intro[1])throw Error('動的達成数');
 showCase(first);
 if(getComputedStyle(document.body).backgroundColor!=='rgb(11, 17, 32)')throw Error('暗色背景');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 if(/undefined|NaN|Infinity|__[A-Z]+__/.test(document.body.innerText))throw Error('未定義表示');
 if(amounts!==1360||summary!==88||old!==56||anchors!==56||top3!==128||contributions!==56)throw Error('照合件数');
 if(recovery!==Object.values(data.details).reduce((sum,e)=>sum+e.recovery.length*5,0))throw Error('旧勝ち例の実表示件数');
 return {全合格:true,四切替:4,円枚数照合:amounts,概要照合:summary,旧比較照合:old,目標固定照合:anchors,
         上位三除外照合:top3,五寄与照合:contributions,旧勝ち例照合:recovery,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,
         金融:0,API:0,packet:0,ledger:0};
}
try{document.body.dataset.check=JSON.stringify(verifyLossAnchorDisplay());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''.replace('__PAYLOAD__', payload)
    started = dict(**provenance,
        QA_source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 金融=0, API=0, packet=0, ledger=0)
    (OUTPUT/'開始.json').write_text(json.dumps(started, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    try:
        screens = [renderer.render(source, '損失停止四比較'+str(width), width, 1200) for width in (1450, 520)]
        preview = '<script>const section=[...document.querySelectorAll("[data-case]")].find(n=>!n.hidden);const nodes=[section.querySelector("h2"),section.querySelector("table.fixed-comparison").closest("details"),section.querySelector("table.anchors").closest("details"),section.querySelector("table.recovery-examples").closest("details")];for(const node of nodes)if(node.tagName==="DETAILS")node.open=true;document.querySelector("main").replaceChildren(...nodes);window.scrollTo(0,0);</script>'
        screens.append(renderer.render(source, '両停止線と不変B及び旧勝ち喪失', 1450, 1250, preview))
        proof = dict(全合格=True, 画面=screens, **started, 根目視確認=False)
        (OUTPUT/'損失停止修正の全場と広狭表示確認.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(proof, ensure_ascii=False), flush=True)
    except Exception:
        (OUTPUT/'表示False.json').write_text(json.dumps(dict(全合格=False, 原因=traceback.format_exc(), **started), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check-only', action='store_true')
    action.add_argument('--root-reviewed', action='store_true')
    args = parser.parse_args()
    check_only() if args.check_only else main()
