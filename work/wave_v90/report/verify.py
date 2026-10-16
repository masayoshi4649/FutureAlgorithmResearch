"""全42条件の金額と枚数表示を保存会計へ独立照合し、暗色画面を描画する。"""

import hashlib
import importlib.util
import json
from pathlib import Path

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
OUT = ROOT / 'アルゴリズム調査/00086_二市場の状態で追従と指値反発を配分'
MAIN = OUT / '二つの戦略への配分と全セッション損益.html'
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
    機能: 保存会計を表示計算から独立に再集約する。
    引数: result (dict) は一条件の全口座、fixed (dict) は期間。
    返り値: None。誤差又は欠落があれば例外を出す。
    """
    assert len(result['rows']) == 60
    for row in result['rows']:
        assert abs(row['profit'] - row['loss'] - row['net']) < 1e-5
        assert abs(row['gross'] - row['fees'] - row['net']) < 1e-5
        assert row['winning_lots'] + row['losing_lots'] + row['flat_lots'] == row['lots']
        cap = 10 if row['symbol'] == 'TOPIX' else 20
        assert row['maximums']['occupied_long'] <= cap and row['maximums']['occupied_short'] <= cap
        for field in ADDITIVE:
            assert abs(sum(value[field] for value in row['sources'].values()) - row[field]) < 1e-5
            assert abs(sum(value[field] for value in row['directions'].values()) - row[field]) < 1e-5
    periods = {name: fixed[name] for name in ('全30', '前16', '後14')}
    periods.update(デイ=[s for s in fixed['全30'] if s.endswith('_Day')],
                   ナイト=[s for s in fixed['全30'] if s.endswith('_Night')])
    for period, sessions in periods.items():
        for symbol in ('TOPIX', 'NK225'):
            rows = [row for row in result['rows'] if row['symbol'] == symbol and row['session'] in sessions]
            actual = result['periods'][period][symbol]
            assert len(rows) == actual['session_count'] == len(sessions)
            for field in ADDITIVE:
                assert abs(sum(row[field] for row in rows) - actual[field]) < 1e-5
            assert actual['positive_sessions'] == sum(row['net'] > 1e-5 for row in rows)
            assert actual['losing_sessions'] == sum(row['net'] < -1e-5 for row in rows)
            assert actual['no_trade_sessions'] == sum(row['campaigns'] == 0 for row in rows)
            denominator = actual['profit'] + actual['loss']
            assert actual['profit_share'] == (actual['profit'] / denominator if denominator else None)
            best = actual['best_day']
            others = [row for row in rows if row['session'][:10] != best]
            for field in ADDITIVE:
                assert abs(sum(row[field] for row in others) - actual['without_best_day'][field]) < 1e-5
            for source in ('J2', 'O06'):
                for field in ADDITIVE:
                    assert abs(sum(row['sources'][source][field] for row in rows) - actual['sources'][source][field]) < 1e-5


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
    extra = read(WORK / 'round2/事前固定.json')
    analysis = read(WORK / 'analysis/比較結果.json')
    assert payload['primary'] == extra['主'] == 'D_C_QA'
    assert payload['default_method'] == 'M82_Q'
    assert payload['selected'] == analysis.get('selected')
    assert payload['catalog'] == fixed['条件'] + extra['条件'] and len(payload['results']) == 42
    assert payload['sessions'] == fixed['全30'] and payload['conclusion'] == analysis['conclusion']
    for identifier, result in payload['results'].items():
        location = WORK / 'round2' if 'base_id' in result['config'] else WORK
        assert result == read(location / 'results' / (identifier + '.json'))
        check(result, fixed)
    spec = importlib.util.spec_from_file_location('隔離描画90', ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = OUT
    renderer.VISUAL = HERE / 'visual'
    renderer.PROBE = '<script>' + (HERE / 'probe.js').read_text(encoding='utf-8') + '</script>'
    csp = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    errors = '<script>window.browserErrors=[];window.addEventListener("error",e=>browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>browserErrors.push(String(e.reason)));</script>'
    source = source.replace('<head>', '<head>' + csp + errors)
    views = [(source, '主全体広幅', 1450, 1520, ''),
             (source, '主全体狭幅', 520, 1670, ''),
             (source, '全30損益', 1450, 2480, '<script>document.querySelector("main").replaceChildren(document.getElementById("sessions"));window.scrollTo(0,0);</script>'),
             (source, '期間と源別寄与', 1450, 1720, '<script>const p=document.getElementById("period-detail"),s=document.getElementById("source-detail");p.open=s.open=true;document.querySelector("main").replaceChildren(p,s);window.scrollTo(0,0);</script>'),
             (source, '改善悪化と条件', 1450, 1460, '<script>const c=document.getElementById("cause-detail"),r=document.getElementById("rules-detail");c.open=r.open=true;document.querySelector("main").replaceChildren(c,r);window.scrollTo(0,0);</script>')]
    outputs = []
    for view in views:
        result = renderer.render(*view)
        outputs.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    assert hashlib.sha256(MAIN.read_bytes()).hexdigest() == original_digest
    proof = dict(全合格=True, 目視確認=False, 保存結果一致数=42, 保存会計口座数=2520,
                 HTML_SHA256=original_digest, 通信遮断='CSP接続禁止と到達不能proxy。現在データ取得・注文なし。',
                 画面=outputs)
    (HERE / '表示の独立検査.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
