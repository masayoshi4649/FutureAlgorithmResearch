"""予定リスク数量の公開四比較を、隔離Chromeの広狭画面で保存会計へ照合する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

import risk_sizing_report as report

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
OUTPUT = report.HERE/'risk_sizing_review'


def signed_money(value: float) -> str:
    """
    機能: 監査済み例の符号付き円額を本文と同じ記号へ対応する。
    引数: value(float)は保存円額。
    返り値: strは正の+又は負の−を含む整数円表示。会計を再計算しない。
    """
    return ('−' if value < 0 else '+')+report.range_report.number(abs(value))


def clock(value: dict) -> str:
    """
    機能: 診断済み価格時計の日本時刻から時分秒だけを取る。
    引数: value(dict)はJST付き原行記録。
    返り値: strはHH:MM:SS。受信時刻を推定しない。
    """
    assert value['JST'].endswith('+09:00')
    return value['JST'].split('T')[1][:8]


def expectations(data: dict, diagnosis: dict) -> dict:
    """
    機能: 公開小会計の1360セル、概要80セルと診断二例の表示期待値を作る。
    引数: data/diagnosis(dict)は公開会計と監査済み小診断。
    返り値: dictは純表示の期待値。原入力・台帳・金融を読まない。
    """
    assert data['全合格'] and diagnosis['全合格'] and len(data['cases']) == 4 and len(data['sessions']) == 33
    tables, overview = {}, []
    fields = ('profit', 'loss', 'net', 'winning_lots', 'losing_lots')
    for identifier, case in data['cases'].items():
        indices = {(r['session'], r['symbol']): r for r in case['rows']}
        assert len(indices) == 66
        rows = [[indices[session, symbol][f] for symbol in report.SYMBOLS for f in fields] for session in data['sessions']]
        rows.append([case['summary'][symbol][f] for symbol in report.SYMBOLS for f in fields])
        assert len(rows) == 34 and all(len(r) == 10 for r in rows)
        tables[identifier] = rows
        for symbol in report.SYMBOLS:
            v = case['summary'][symbol]
            cells = [report.label(case['config'])+identifier, report.LABELS[symbol], report.range_report.number(v['net']),
                report.percent(v['profit_share']), str(v['negative'])+'/33 ('+report.percent(v['red_all'])+')',
                report.percent(v['red_active']), str(v['no_trade']), report.range_report.number(v['mean_positive_session_net'], 1),
                report.range_report.number(v['worst_session_loss']), ' / '.join('達成' if v['tests'][k] else '未達' for k in report.TESTS)]
            overview.append(dict(id=identifier, symbol=symbol, cells=cells))
    # ----------------------------------------
    # 本文二例は公開会計ではなく、同親・原行を監査した保存診断へ束縛する。
    examples = []
    for key, label in (('2026-09-29_Night|TOPIX', 'TOPIX・9/29ナイト'), ('2026-10-05_Day|NK225', '日経・10/5デイ')):
        scene = diagnosis['場別'][key]
        original = scene['旧勝ち赤字化の事後参考']
        parent_id = original['新親']['親']
        parent = next(p for p in scene['新実親'] if p['親'] == parent_id)
        assert original['同一公開及び実新規'] and parent['実初回q'] == 1 and parent['side'] == 1
        assert len(parent['返済']) == 1 and parent['保存完結親']['収支'] == original['新親']['収支']
        exit = parent['返済'][0]
        cells = [label,
            clock(parent['新規'])+' 買'+str(parent['実初回q'])+'枚 @'+report.range_report.number(parent['実新規価格']),
            clock(original['旧最終返済判断'])+' '+signed_money(original['旧返済判断時の新実口座清算'])+'円（目標'+report.range_report.number(parent['比較用新P2絶対利益目標'])+'円）',
            str(original['旧親']['枚数'])+'枚 '+signed_money(original['旧親']['収支'])+'円',
            clock(exit['約定'])+' @'+report.range_report.number(exit['price'])+' / '+signed_money(original['新親']['収支'])+'円']
        examples.append(cells)
    return dict(tables=tables, overview=overview, examples=examples,
        labels=[s.replace('_Day', ' デイ').replace('_Night', ' ナイト') for s in data['sessions']]+['全33合計'])


def main() -> None:
    """
    機能: root確認後だけ隔離Chromeで四切替と広狭画面を検査し、証跡と画像を保存する。
    引数: なし。完成HTML・公開会計・監査済み小診断だけを使用する。
    返り値: None。金融・API・packet・ledgerを読まず、root目視は未確認として残す。
    """
    assert not OUTPUT.exists(), '前回の表示証跡を保持し、自動再実行しない'
    html_path = report.PUBLIC/(report.TITLE+'.html')
    accounting_path = report.PUBLIC/report.ACCOUNTING_TITLE
    source = html_path.read_text(encoding='utf-8')
    data = json.loads(accounting_path.read_text(encoding='utf-8'))
    diagnosis_bytes = report.DIAGNOSIS.read_bytes()
    assert hashlib.sha256(diagnosis_bytes).hexdigest() == data['sources'][report.DIAGNOSIS.relative_to(report.ROOT).as_posix()]
    diagnosis = json.loads(diagnosis_bytes.decode('utf-8-sig'))
    expected = expectations(data, diagnosis)
    # ----------------------------------------
    # Chromeは共通の隔離実装を利用し、公開HTMLの複製だけを実行する。
    spec = importlib.util.spec_from_file_location('予定数量表示だけの隔離Chrome', report.ROOT/'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    OUTPUT.mkdir(parents=True)
    renderer.OUT, renderer.VISUAL = report.PUBLIC, OUTPUT/'visual'
    payload = json.dumps(expected, ensure_ascii=False, allow_nan=False).replace('</', '<\\/')
    renderer.PROBE = '''<script>
/**
 * 機能: 公開四条件の全場・総計・概要・損失二例を保存小資料へ照合する。
 * 引数: なし。
 * @returns {object} 表示件数、画面幅、数値・暗色の確認結果。
 */
function verifySizingDisplay(){
 const data=__PAYLOAD__,first=document.getElementById('case').value;let amounts=0,overview=0,examples=0;
 const options=[...document.getElementById('case').options].map(x=>x.value);
 if(options.length!==4||new Set(options).size!==4||options.some(id=>!(id in data.tables)))throw Error('四条件選択肢');
 for(const [id,expected] of Object.entries(data.tables)){
  showCase(id);const visible=[...document.querySelectorAll('[data-case]')].filter(node=>!node.hidden);
  if(visible.length!==1||visible[0].dataset.case!==id||document.getElementById('case').value!==id)throw Error('条件切替');
  const table=visible[0].querySelector('table.sessions'),rows=table.tBodies[0].rows;
  const headers=table.tHead.rows[0].cells;
  if(headers[1].textContent!=='TOPIXミニ：新規1〜5枚・上限10枚'||headers[2].textContent!=='日経マイクロ：新規1〜10枚・上限20枚')throw Error('可変枚数のヘッダ');
  if(rows.length!==34)throw Error('全33場と総計');
  for(let i=0;i<34;i++){
   if(rows[i].cells.length!==11||rows[i].cells[0].textContent!==data.labels[i])throw Error('場名又は十列');
   for(let j=0;j<10;j++){
    const value=Number(rows[i].cells[j+1].textContent.replaceAll(',','').trim());
    if(!Number.isFinite(value)||Math.abs(value-expected[i][j])>.500001)throw Error('金額枚数差:'+id+'/'+i+'/'+j);amounts++;
   }
  }
  if(document.documentElement.scrollWidth>innerWidth+2)throw Error('切替後の本文横溢れ');
 }
 const summary=document.querySelector('#overview tbody').rows;if(summary.length!==8)throw Error('概要八行');
 for(let i=0;i<8;i++){
  const e=data.overview[i],r=summary[i];
  if(r.dataset.caseId!==e.id||r.dataset.symbol!==e.symbol||r.cells.length!==10)throw Error('概要同定');
  for(let j=0;j<10;j++){if(r.cells[j].textContent!==e.cells[j])throw Error('概要表示差:'+i+'/'+j);overview++;}
 }
 const loss=document.querySelector('#loss-examples tbody').rows;if(loss.length!==2)throw Error('損失二例');
 for(let i=0;i<2;i++){
  if(loss[i].cells.length!==5)throw Error('損失例五列');
  for(let j=0;j<5;j++){if(loss[i].cells[j].textContent!==data.examples[i][j])throw Error('監査済み例との差:'+i+'/'+j);examples++;}
 }
 showCase(first);
 if(getComputedStyle(document.body).backgroundColor!=='rgb(11, 17, 32)')throw Error('暗色背景');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 if(/undefined|NaN|Infinity|__[A-Z]+__/.test(document.body.innerText))throw Error('未定義表示');
 if(amounts!==1360||overview!==80||examples!==10)throw Error('照合件数');
 return {全合格:true,条件切替:4,円枚数照合:amounts,概要表示照合:overview,損失例表示照合:examples,
         画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,金融:0,API:0,packet:0,ledger:0};
}
try{document.body.dataset.check=JSON.stringify(verifySizingDisplay());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''.replace('__PAYLOAD__', payload)
    started = dict(HTML_SHA256=hashlib.sha256(source.encode('utf-8')).hexdigest(),
        公開会計_SHA256=hashlib.sha256(accounting_path.read_bytes()).hexdigest(),
        診断_SHA256=hashlib.sha256(diagnosis_bytes).hexdigest(),
        QA_source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        金融=0, API=0, packet=0, ledger=0)
    (OUTPUT/'開始.json').write_text(json.dumps(started, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    try:
        screens = [renderer.render(source, '数量四比較'+str(width), width, 1200) for width in (1450, 520)]
        preview = '<script>const details=document.getElementById("loss-examples").closest("details");details.open=true;document.querySelector("main").replaceChildren(details);window.scrollTo(0,0);</script>'
        screens.append(renderer.render(source, '数量縮小による損失二例', 1450, 850, preview))
        proof = dict(全合格=True, 画面=screens, **started, 根目視確認=False)
        (OUTPUT/'予定リスク数量の四切替全33場と広狭確認.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(proof, ensure_ascii=False), flush=True)
    except Exception:
        (OUTPUT/'表示False.json').write_text(json.dumps(dict(全合格=False, 原因=traceback.format_exc(), **started), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root-reviewed', action='store_true')
    args = parser.parse_args()
    assert args.root_reviewed, 'root確認後に表示だけを実行する'
    main()
