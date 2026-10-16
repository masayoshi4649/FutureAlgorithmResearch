"""保存結果と全20条件の表表示を照合して、隔離したブラウザで広狭画面を描画する。"""

import hashlib
import importlib.util
import json
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
MAIN = HERE / '公開前/小さく入り利益で増やす手法と全セッション損益.html'
FIELDS = ('profit', 'loss', 'net', 'gross', 'fees', 'winning_lots', 'losing_lots', 'flat_lots', 'lots')


def read(path: Path) -> dict:
    """
    機能: 検査に使う正式保存結果を読み取る。
    引数: path(Path)。
    返り値: dict。JSON資料。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 表示内容の根拠と生成物の不変性を照合する。
    引数: path(Path)。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_result(result: dict, fixed: dict) -> None:
    """
    機能: 表示金額と枚数を各口座から独立に再集計する。
    引数: result(dict)、fixed(dict)。
    返り値: None。欠落、誤集計、枚数上限超過があれば停止する。
    """
    rows = result['rows']
    assert len(rows) == 62
    for row in rows:
        for value in (row, row['cohorts']):
            assert abs(value['profit'] - value['loss'] - value['net']) < 1e-5
            assert abs(value['gross'] - value['fees'] - value['net']) < 1e-5
            assert value['winning_lots'] + value['losing_lots'] + value['flat_lots'] == value['lots']
        cap = 10 if row['symbol'] == 'TOPIX' else 20
        assert row['maximums']['occupied_long'] <= cap and row['maximums']['occupied_short'] <= cap
    for part, period in (('front', '前16'), ('back', '後15')):
        saved = read(WORK / part / 'results' / (result['config']['id'] + '.json'))
        assert [row for row in rows if row['session'] in fixed[period]] == saved['rows']
        assert result['periods'][period] == saved['periods'][period]
    periods = {name: fixed[name] for name in ('全31', '前16', '後15', '旧30', '後14', '追加1')}
    periods.update(デイ=[s for s in fixed['全31'] if s.endswith('_Day')],
                   ナイト=[s for s in fixed['全31'] if s.endswith('_Night')])
    for period, subset in periods.items():
        for symbol in ('TOPIX', 'NK225'):
            selected = [row for row in rows if row['symbol'] == symbol and row['session'] in subset]
            total = result['periods'][period][symbol]
            for basis in ('parents', 'cohorts'):
                value = total if basis == 'parents' else total['cohorts']
                for field in FIELDS:
                    expected = sum((row if basis == 'parents' else row['cohorts'])[field] for row in selected)
                    assert abs(expected - value[field]) < 1e-5
            assert total['positive_sessions'] == sum(row['net'] > 1e-5 for row in selected)
            assert total['losing_sessions'] == sum(row['net'] < -1e-5 for row in selected)
            assert total['no_trade_sessions'] == sum(row['campaigns'] == 0 for row in selected)


# ----------------------------------------


def main() -> None:
    """
    機能: 正式資料とHTMLの一致及び全条件切替を確認し、画面画像を保存する。
    引数: なし。
    返り値: None。売買・会計・公開HTMLを変更しない。
    """
    original = digest(MAIN)
    source = MAIN.read_text(encoding='utf-8')
    soup = BeautifulSoup(source, 'html.parser')
    payload = json.loads(soup.select_one('#report-data').string)
    fixed, analysis = read(WORK / '事前固定.json'), read(WORK / 'analysis/比較結果.json')
    explanation = read(WORK / 'analysis/説明補足.json')
    assert payload['results'] == analysis['results'] and len(payload['results']) == 20
    assert payload['catalog'] == fixed['条件'] and payload['sessions'] == fixed['全31']
    assert payload['primary'] == payload['default_method'] == analysis['primary']
    assert payload['selected'] == analysis['selected']
    assert payload['conclusion'] == explanation['conclusion']
    assert payload['report_diagnostics'] == explanation['report_diagnostics']
    for result in payload['results'].values():
        check_result(result, fixed)
    spec = importlib.util.spec_from_file_location('101隔離表示の共通描画', ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = MAIN.parent
    renderer.VISUAL = HERE / 'visual'
    renderer.PROBE = '<script>' + (HERE / 'probe.js').read_text(encoding='utf-8') + '</script>'
    csp = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    errors = '<script>window.browserErrors=[];window.addEventListener("error",e=>browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>browserErrors.push(String(e.reason)));</script>'
    source = source.replace('<head>', '<head>' + csp + errors)
    views = [(source, '安定性の広幅', 1800, 1700, ''),
             (source, '安定性の狭幅', 520, 1650, ''),
             (source, '全31実玉群と親', 1450, 2550, '<script>document.querySelector("main").replaceChildren(document.getElementById("sessions"));window.scrollTo(0,0);</script>'),
             (source, '前後と親内損失及び予算', 1700, 2100, '<script>const a=document.getElementById("period-detail"),b=document.getElementById("cohort-detail");a.open=b.open=true;document.querySelector("main").replaceChildren(a,b);window.scrollTo(0,0);</script>')]
    outputs = []
    for view in views:
        outputs.append(renderer.render(*view))
        print(view[1] + ' の全20表示照合と描画が合格', flush=True)
    assert digest(MAIN) == original
    proof = dict(全合格=True, 目視確認=False, 保存結果一致数=20, 保存会計口座数=1240,
                 相殺前と親表示を両検査=True, HTML_SHA256=original, 画面=outputs,
                 通信遮断='CSP接続禁止と到達不能proxy。現在API取得及び実注文0。',
                 表示検査コードSHA256={str(path.relative_to(ROOT)): digest(path) for path in
                     (Path(__file__), HERE / 'probe.js', ROOT / 'work/wave_v52/review/verify_report.py')})
    (HERE / '表示の独立検査.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
