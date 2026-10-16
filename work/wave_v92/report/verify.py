"""36条件・全31場の金額と枚数表示を保存会計へ独立照合し、暗色画面を描画する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import statistics

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
OUT = ROOT / 'アルゴリズム調査/00088_回復確認と中心帰還による再参加'
MAIN = OUT / '回復確認と再参加の説明と全セッション損益.html'
ADDITIVE = ('profit', 'loss', 'net', 'gross', 'fees', 'campaigns', 'winning_campaigns',
            'losing_campaigns', 'flat_campaigns', 'winning_lots', 'losing_lots', 'flat_lots', 'lots')


def read(path):
    """
    機能: 正式な会計又は生成結果のJSONを読む。
    引数: path (Path)。
    返り値: dict の内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def check(result, fixed):
    """
    機能: 表示用会計をJavaScriptから独立に再集約する。
    引数: result (dict) は一条件の全口座、fixed (dict) は固定した期間。
    返り値: None。誤差又は欠落があれば例外を出す。
    """
    assert len(result['rows']) == 62
    for row in result['rows']:
        assert abs(row['profit'] - row['loss'] - row['net']) < 1e-5
        assert abs(row['gross'] - row['fees'] - row['net']) < 1e-5
        assert row['winning_lots'] + row['losing_lots'] + row['flat_lots'] == row['lots']
        cap = 10 if row['symbol'] == 'TOPIX' else 20
        assert row['maximums']['occupied_long'] <= cap and row['maximums']['occupied_short'] <= cap
        for field in ADDITIVE:
            assert abs(sum(value[field] for value in row['sources'].values()) - row[field]) < 1e-5
            assert abs(sum(value[field] for value in row['directions'].values()) - row[field]) < 1e-5
    sessions = fixed['全31']
    periods = {'全31': sessions, '旧30': sessions[:-1], '前16': sessions[:16], '後15': sessions[16:],
               '後14': sessions[16:-1],
               '追加1': sessions[-1:], 'デイ': [s for s in sessions if s.endswith('_Day')],
               'ナイト': [s for s in sessions if s.endswith('_Night')]}
    for period, subset in periods.items():
        for symbol in ('TOPIX', 'NK225'):
            rows = [row for row in result['rows'] if row['symbol'] == symbol and row['session'] in subset]
            actual = result['periods'][period][symbol]
            assert len(rows) == actual['session_count'] == len(subset)
            for field in ADDITIVE:
                assert abs(sum(row[field] for row in rows) - actual[field]) < 1e-5
            assert actual['positive_sessions'] == sum(row['net'] > 1e-5 for row in rows)
            assert actual['losing_sessions'] == sum(row['net'] < -1e-5 for row in rows)
            assert actual['no_trade_sessions'] == sum(row['campaigns'] == 0 for row in rows)
            denominator = actual['profit'] + actual['loss']
            expected = actual['profit'] / denominator if denominator else None
            assert actual['profit_share'] == expected
            others = [row for row in rows if row['session'][:10] != actual['best_day']]
            for field in ADDITIVE:
                assert abs(sum(row[field] for row in others) - actual['without_best_day'][field]) < 1e-5
            for source in ('J2', 'O06'):
                for field in ADDITIVE:
                    assert abs(sum(row['sources'][source][field] for row in rows) - actual['sources'][source][field]) < 1e-5


def allocation_check(diagnostic, analysis, fixed):
    """
    機能: 固定配分の相関・同時損失・標準偏差を全31の正式源会計から再計算する。
    引数: diagnostic/analysis/fixed (dict) は追加診断、正式集計、事前固定。
    返り値: None。追加の売買計算や正式会計変更は行わない。
    """
    assert diagnostic['全合格'] and diagnostic['根集計SHA256'] == hashlib.sha256(
        (WORK / 'analysis/比較結果.json').read_bytes()).hexdigest()
    assert diagnostic['配分探索'] == diagnostic['条件変更'] == diagnostic['新しい売買計算'] == 0
    assert len(diagnostic['行']) == 4
    for item in diagnostic['行']:
        ident, symbol = item['手法'], item['銘柄']
        assert ident in ('M_RB25_C', 'M_KS25') and symbol in ('TOPIX', 'NK225')
        result = analysis['results'][ident]
        summary = result['periods']['全31'][symbol]
        rows = [next(row for row in result['rows'] if row['session'] == session and row['symbol'] == symbol)
                for session in fixed['全31']]
        trend = [row['sources']['J2']['net'] for row in rows]
        reversal = [row['sources']['O06']['net'] for row in rows]
        expected = [{'場': row['session'], '追従': row['sources']['J2']['net'],
                     '反発': row['sources']['O06']['net'], '合計': row['net']} for row in rows]
        assert item['全31源別場収支'] == expected
        for label, field in [('総利益', 'profit'), ('総損失', 'loss'), ('収支', 'net'),
                             ('金額利益割合', 'profit_share'), ('併用黒字場数', 'positive_sessions')]:
            assert abs(item[label] - summary[field]) < 1e-10
        assert abs(item['源別場収支相関'] - statistics.correlation(trend, reversal)) < 1e-12
        active = [index for index, row in enumerate(rows)
                  if row['sources']['J2']['campaigns'] and row['sources']['O06']['campaigns']]
        assert item['二源とも活動場数'] == len(active)
        assert abs(item['二源活動場のみ相関'] - statistics.correlation(
            [trend[index] for index in active], [reversal[index] for index in active])) < 1e-12
        assert item['二源とも赤字場数'] == sum(a < 0 and b < 0 for a, b in zip(trend, reversal))
        assert item['追従赤字から合計黒字場数'] == sum(
            a < 0 and row['net'] > 0 for a, row in zip(trend, rows))
        baseline = [row['net'] for row in analysis['results']['J10']['rows'] if row['symbol'] == symbol]
        assert abs(item['併用の場収支標本標準偏差'] - statistics.stdev([row['net'] for row in rows])) < 1e-8
        assert abs(item['同上限追従の場収支標本標準偏差'] - statistics.stdev(baseline)) < 1e-8
        if ident == 'M_RB25_C':
            assert item['追従赤字から合計黒字場数'] == 0
            assert item['併用の場収支標本標準偏差'] < item['同上限追従の場収支標本標準偏差']
            assert summary['net'] < analysis['results']['J10']['periods']['全31'][symbol]['net']


def main():
    """
    機能: 全条件の表切替を隔離ブラウザで照合し、広狭と詳細を画像で保存する。
    引数: なし。
    返り値: None。会計値・売買コード・公開HTMLは変更しない。
    """
    original_digest = hashlib.sha256(MAIN.read_bytes()).hexdigest()
    source = MAIN.read_text(encoding='utf-8')
    soup = BeautifulSoup(source, 'html.parser')
    payload = json.loads(soup.select_one('#report-data').string)
    fixed = read(WORK / '事前固定.json')
    selection = read(WORK / '前16参考代表.json')
    analysis = read(WORK / 'analysis/比較結果.json')
    conclusion, causes = analysis['conclusion'], analysis.get('cause_notes', {})
    explanation_path = WORK / 'analysis/説明補足.json'
    if explanation_path.exists():
        explanation = read(explanation_path)
        assert explanation['根集計SHA256'] == hashlib.sha256((WORK / 'analysis/比較結果.json').read_bytes()).hexdigest()
        assert explanation['売買及び会計の変更'] == 0
        for relative, expected in explanation['根拠SHA256'].items():
            assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
        conclusion, causes = explanation['conclusion'], explanation['cause_notes']
    assert payload['primary'] == fixed['主'] == 'R_B25_C_ESTOP'
    assert payload['default_method'] == payload['primary']
    assert payload['selected'] == analysis.get('selected') == selection['selected']
    assert selection['後15正式損益前選定'] and fixed['全31既知']
    assert payload['catalog'] == fixed['条件'] and len(payload['results']) == 36
    assert payload['sessions'] == fixed['全31'] and payload['conclusion'] == conclusion
    assert payload['cause_notes'] == causes
    assert payload['comparison_pairs'] == analysis.get('comparison_pairs', {})
    allocation_path = WORK / 'review/固定配分の同時損失と源別相関.json'
    allocation = read(allocation_path) if allocation_path.exists() else None
    assert payload.get('allocation_diagnostic') == allocation
    if allocation:
        allocation_check(allocation, analysis, fixed)
    assert payload['results'] == analysis['results']
    for ident, result in payload['results'].items():
        for directory, period in [('front', '前16'), ('back', '後15')]:
            saved = read(WORK / directory / 'results' / (ident + '.json'))
            assert [row for row in result['rows'] if row['session'] in fixed[period]] == saved['rows']
            assert result['periods'][period] == saved['periods'][period]
        check(result, fixed)
    spec = importlib.util.spec_from_file_location('隔離描画92', ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = OUT
    renderer.VISUAL = HERE / 'visual'
    renderer.PROBE = '<script>' + (HERE / 'probe.js').read_text(encoding='utf-8') + '</script>'
    csp = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    errors = '<script>window.browserErrors=[];window.addEventListener("error",e=>browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>browserErrors.push(String(e.reason)));</script>'
    source = source.replace('<head>', '<head>' + csp + errors)
    views = [(source, '主と対照の広幅', 1450, 1680, ''),
             (source, '主と対照の狭幅', 520, 1760, ''),
             (source, '全31損益', 1450, 2480, '<script>document.querySelector("main").replaceChildren(document.getElementById("sessions"));window.scrollTo(0,0);</script>'),
             (source, '前後と源別寄与', 1450, 2200, '<script>const p=document.getElementById("period-detail"),s=document.getElementById("source-detail");p.open=s.open=true;document.querySelector("main").replaceChildren(p,s);window.scrollTo(0,0);</script>'),
             (source, '改善悪化と条件', 1450, 1550, '<script>const c=document.getElementById("cause-detail"),r=document.getElementById("rules-detail");c.open=r.open=true;document.querySelector("main").replaceChildren(c,r);window.scrollTo(0,0);</script>')]
    outputs = []
    for view in views:
        result = renderer.render(*view)
        outputs.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    assert hashlib.sha256(MAIN.read_bytes()).hexdigest() == original_digest
    proof = dict(全合格=True, 目視確認=False, 保存結果一致数=36, 保存会計口座数=2232,
                 HTML_SHA256=original_digest, 通信遮断='CSP接続禁止と到達不能proxy。現在データ取得・注文なし。',
                 画面=outputs)
    if allocation:
        proof['配分診断SHA256'] = hashlib.sha256(allocation_path.read_bytes()).hexdigest()
        proof['配分診断正式会計からの再照合行数'] = 4
    (HERE / '表示の独立検査.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
