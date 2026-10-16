"""全81条件の保存会計と表示を、通信遮断したブラウザで照合する。"""

from pathlib import Path
import hashlib
import importlib.util
import json

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
OUT = ROOT/'アルゴリズム調査/00085_仮想成績による参加停止と再開'
MAIN = OUT/'仮想成績で停止再開する手法と全セッション損益.html'
FIELDS = ('profit', 'loss', 'net', 'gross', 'fees', 'campaigns', 'wins', 'losses', 'new_lots', 'closed_lots',
          'gate_eligible', 'gate_allowed', 'gate_rejected', 'gate_warmup', 'virtual_campaigns')


def read(path):
    """
    機能: 保存済み日本語JSONを読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def check(result, fixed):
    """
    機能: 場会計と期間会計を独立集約し、原本からの表示値を照合する。
    引数: result/fixed(dict)。
    返り値: None。
    """
    assert len(result['rows']) == 60
    for row in result['rows']:
        assert abs(row['profit']-row['loss']-row['net']) < 1e-6
        assert abs(row['gross']-row['fees']-row['net']) < 1e-6
        assert row['new_lots'] == row['closed_lots']
        assert row['gate_eligible'] == row['gate_allowed']+row['gate_rejected']
        assert 0 <= row['gate_warmup'] <= row['gate_allowed']
        cap = 10 if row['symbol'] == 'TOPIX' else 20
        assert row['max_long'] <= cap and row['max_short'] <= cap
    for period in ('前16', '後14', '全30'):
        for symbol in ('TOPIX', 'NK225'):
            rows = [r for r in result['rows'] if r['symbol'] == symbol and r['session'] in fixed[period]]
            actual = result['periods'][period][symbol]
            for field in FIELDS:
                assert abs(actual[field]-sum(r[field] for r in rows)) < 1e-6, (period, symbol, field)
            assert actual['positive_sessions'] == sum(r['net'] > 0 for r in rows)
            assert actual['no_trade_sessions'] == sum(r['campaigns'] == 0 for r in rows)
            expected = actual['profit']/(actual['profit']+actual['loss']) if actual['profit']+actual['loss'] else None
            assert actual['profit_share'] == expected


def main():
    """
    機能: 全条件切替と広狭描画を検査し、最終HTML指紋と画像を保存する。
    引数: なし。
    返り値: None。売買コード・数値結果・公開HTMLを変更しない。
    """
    digest = hashlib.sha256(MAIN.read_bytes()).hexdigest()
    source = MAIN.read_text(encoding='utf-8')
    soup = BeautifulSoup(source, 'html.parser')
    data = json.loads(soup.select_one('#report-data').string)
    fixed = read(WORK/'事前固定.json')
    analysis = read(WORK/'analysis/比較結果.json')
    review = read(WORK/'review/独立解釈と全親会計再検算及び逃した回復利益.json')
    assert data['selected'] == analysis.get('selected') and data['primary'] == 'B0622_C16_P60'
    assert len(data['results']) == 81 and data['sessions'] == fixed['全30']
    assert data['catalog'] == fixed['catalog']
    assert data['conclusion'] == analysis.get('conclusion', [])
    assert len(data['cases']) == 4
    for case in data['cases']:
        original = next(value for value in review['回復の最初の利益を拒否した具体3件']
                        if value['symbol'] == case['symbol'] and value['session'] == '2026-09-28_Day')
        record = original if case['session'].endswith('_Day') else original['following'][0]
        assert case['clock'] == record.get('decision', record.get('clock'))
        for field in ('past_share', 'base_net', 'accepted'):
            assert case[field] == record[field]
        assert case['quantity'] == original['quantity'] == (6 if case['symbol'] == 'TOPIX' else 12)
    for identifier, result in data['results'].items():
        assert result == read(WORK/'results'/f'{identifier}.json')
        check(result, fixed)
        for period in ('前16', '後14', '全30'):
            for symbol in ('TOPIX', 'NK225'):
                parts = data['source_contributions'][identifier][period][symbol]
                for field in ('profit', 'loss', 'net', 'campaigns'):
                    assert abs(sum(part[field] for part in parts.values())-result['periods'][period][symbol][field]) < 1e-6
                difference = data['differences'][identifier][period][symbol]
                assert abs(difference['actual_net']-result['periods'][period][symbol]['net']) < 1e-6
                assert abs(difference['actual_net']-difference['base_net']-difference['delta']) < 1e-6
                assert abs(difference['saved_loss']-difference['missed_profit']-difference['delta']) < 1e-6
    expected_eighty = [identifier for identifier, result in data['results'].items()
        if all(result['periods']['全30'][symbol]['profit_share'] is not None and
               result['periods']['全30'][symbol]['profit_share'] >= .8 for symbol in ('TOPIX', 'NK225'))]
    assert data['both_eighty'] == expected_eighty
    spec = importlib.util.spec_from_file_location('隔離描画89', ROOT/'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = OUT
    renderer.VISUAL = HERE/'visual'
    renderer.PROBE = '<script>'+(HERE/'probe.js').read_text(encoding='utf-8')+'</script>'
    csp = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    errors = '<script>window.browserErrors=[];window.addEventListener("error",e=>browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>browserErrors.push(String(e.reason)));</script>'
    source = source.replace('<head>', '<head>'+csp+errors)
    views = [(source, '主全体広幅', 1450, 1550, ''), (source, '主全体狭幅', 520, 1650, ''),
        (source, '全30損益', 1450, 2450, '<script>document.querySelector("main").replaceChildren(document.getElementById("sessions"));window.scrollTo(0,0);</script>'),
        (source, '期間と見送り効果', 1450, 2050, '<script>const p=document.getElementById("period-detail"),d=document.getElementById("difference-detail");p.open=d.open=true;document.querySelector("main").replaceChildren(d,p);window.scrollTo(0,0);</script>'),
        (source, '回復を見送った4親', 1450, 850, '<script>const p=document.getElementById("case-detail");p.open=true;document.querySelector("main").replaceChildren(p);window.scrollTo(0,0);</script>')]
    outputs = []
    for view in views:
        proof = renderer.render(*view)
        outputs.append(proof)
        print(json.dumps(proof, ensure_ascii=False), flush=True)
    assert digest == hashlib.sha256(MAIN.read_bytes()).hexdigest()
    result = dict(全合格=True, 目視確認=False, 保存結果一致数=81, 保存会計口座数=4860, HTML_SHA256=digest,
        通信遮断='CSP接続禁止と到達不能proxy。データ取得・注文なし。', 画面=outputs)
    (HERE/'表示の独立検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
