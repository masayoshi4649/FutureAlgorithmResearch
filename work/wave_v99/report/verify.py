"""34条件・全31場の金額と枚数表示を保存会計へ独立照合し、暗色画面を描画する。"""

import hashlib
import importlib.util
import json
import math
from pathlib import Path

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / '公開前'
MAIN = OUT / '現在方向の価格源を替えた手法と全セッション損益.html'
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


def quantile(values: list[float],fraction: float) -> float | None:
    """
    機能: 正式集計器のnumpy関数を使わず、線形補間分位を独立計算する。
    引数: values(list[float])、fraction(float)。
    返り値: float|Noneは分位又は空系列の不明。
    """
    if not values:return None
    ordered=sorted(values);position=(len(ordered)-1)*fraction;left=math.floor(position);right=math.ceil(position)
    return ordered[left]+(ordered[right]-ordered[left])*(position-left)


def stable_check(result: dict,fixed: dict,first_prices: dict) -> None:
    """
    機能: 赤字額・活動率・数量比較単位・下方偏差・分位を独立再集計する。
    引数: result/fixed/first_prices(dict)。
    返り値: Noneは表示用安定性の一致確認。新しい売買は行わない。
    """
    sessions=fixed['全31']
    periods={'全31':sessions,'前16':sessions[:16],'後15':sessions[16:],'旧30':sessions[:-1],
             '後14':sessions[16:-1],'追加1':sessions[-1:],
             'デイ':[s for s in sessions if s.endswith('_Day')],'ナイト':[s for s in sessions if s.endswith('_Night')]}
    for period,subset in periods.items():
        for symbol in ('TOPIX','NK225'):
            rows=[r for r in result['rows'] if r['symbol']==symbol and r['session'] in subset]
            active=[r for r in rows if r['campaigns']>0];red=[r for r in active if r['net']<-1e-5]
            scale,value=(1,1000.) if symbol=='TOPIX' else (2,10.)
            quantity=(result['config']['trend_budget']+result['config']['range_budget'])*scale
            comparison_cap=10*scale
            units={r['session']:comparison_cap*value*first_prices[(r['session'],symbol)]*.001 for r in rows}
            normalized=[r['net']/units[r['session']] for r in active]
            downside=[min(v,0.) for v in normalized];red_units=[-r['net']/units[r['session']] for r in red]
            nets=[r['net'] for r in rows]
            expected=dict(configured_quantity=quantity,comparison_cap=comparison_cap,session_count=len(rows),active_sessions=len(active),
              no_trade_sessions=len(rows)-len(active),losing_sessions=len(red),
              positive_session_rate=sum(r['net']>1e-5 for r in active)/len(active) if active else None,
              mean_losing_session_yen=sum(-r['net'] for r in red)/len(red) if red else 0.,
              worst_session_loss_yen=max([-r['net'] for r in red],default=0.),
              downside_rms_units=math.sqrt(sum(v*v for v in downside)/len(rows)) if rows else None,
              active_downside_rms_units=math.sqrt(sum(v*v for v in downside)/len(downside)) if downside else None,
              mean_losing_session_units=sum(red_units)/len(red_units) if red_units else 0.,
              worst_session_loss_units=max(red_units,default=0.),active_net_q25_units=quantile(normalized,.25),
              active_net_median_units=quantile(normalized,.5),session_net_q25_yen=quantile(nets,.25),
              session_net_median_yen=quantile(nets,.5),
              worst_intraday_drawdown_units=max([r['equity_drawdown']/units[r['session']] for r in rows],default=0.))
            actual=result['stability'][period][symbol]
            assert actual['comparison_units_yen']==units
            for field,wanted in expected.items():
                if wanted is None:assert actual[field] is None
                else:assert abs(actual[field]-wanted)<=1e-9*max(1.,abs(wanted)),(period,symbol,field)


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
    assert payload['primary'] == fixed['主'] == 'L1_C1_A7_X3'
    assert payload['default_method'] == payload['primary']
    assert payload['selected'] == analysis.get('selected') == selection['selected']
    assert selection['後15正式損益前選定'] and fixed['全31既知']
    spec = importlib.util.spec_from_file_location('表示名独立98', WORK / 'catalog.py')
    condition_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(condition_module)
    assert payload['labels'] == condition_module.labels()
    assert payload['comparison_pairs'] == {config['id']: condition_module.references(config['id']) for config in fixed['条件']}
    assert payload['catalog'] == fixed['条件'] and len(payload['results']) == 34
    assert payload['sessions'] == fixed['全31'] and payload['conclusion'] == conclusion
    assert payload['cause_notes'] == causes
    assert payload['comparison_pairs'] == analysis.get('comparison_pairs', {})
    assert payload['results'] == analysis['results']
    policy=read(WORK/'セッション安定性の事前評価.json')
    assert payload['stability_policy']==analysis['セッション安定性の事前評価']==policy
    spec=importlib.util.spec_from_file_location('表示正規化98の旧価格読取',WORK/'data.py')
    input_module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(input_module)
    material=input_module.load_inputs(verify=False)
    first_prices={key:float(record['price'][0]) for key,record in material['prices'].items()}
    del material
    for ident, result in payload['results'].items():
        for directory, period in [('front', '前16'), ('back', '後15')]:
            saved = read(WORK / directory / 'results' / (ident + '.json'))
            assert [row for row in result['rows'] if row['session'] in fixed[period]] == saved['rows']
            assert result['periods'][period] == saved['periods'][period]
            assert result['stability'][period]==saved['stability']
        check(result, fixed)
        stable_check(result,fixed,first_prices)
    spec = importlib.util.spec_from_file_location('隔離描画98', ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = OUT
    renderer.VISUAL = HERE / 'visual'
    renderer.PROBE = '<script>' + (HERE / 'probe.js').read_text(encoding='utf-8') + '</script>'
    csp = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    errors = '<script>window.browserErrors=[];window.addEventListener("error",e=>browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>browserErrors.push(String(e.reason)));</script>'
    source = source.replace('<head>', '<head>' + csp + errors)
    views = [(source, '主と対照の広幅', 1950, 1680, ''),
             (source, '主と対照の狭幅', 520, 1760, ''),
             (source, '全31損益', 1450, 2480, '<script>document.querySelector("main").replaceChildren(document.getElementById("sessions"));window.scrollTo(0,0);</script>'),
             (source, '安定性と前後及び源別寄与', 1750, 2750, '<script>const p=document.getElementById("period-detail"),s=document.getElementById("source-detail"),t=document.getElementById("stability-detail");p.open=s.open=t.open=true;document.querySelector("main").replaceChildren(t,p,s);window.scrollTo(0,0);</script>'),
             (source, '改善悪化と条件', 1450, 2050, '<script>const c=document.getElementById("cause-detail"),r=document.getElementById("rules-detail");c.open=r.open=true;document.querySelector("main").replaceChildren(c,r);window.scrollTo(0,0);</script>')]
    outputs = []
    for view in views:
        result = renderer.render(*view)
        outputs.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    assert hashlib.sha256(MAIN.read_bytes()).hexdigest() == original_digest
    proof = dict(全合格=True, 目視確認=False, 保存結果一致数=34, 保存会計口座数=2108,
                 HTML_SHA256=original_digest, 通信遮断='CSP接続禁止と到達不能proxy。現在データ取得・注文なし。',
                 画面=outputs,
                 表示検査コードSHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in (HERE / 'verify.py', HERE / 'probe.js', ROOT / 'work/wave_v52/review/verify_report.py')})
    (HERE / '表示の独立検査.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
