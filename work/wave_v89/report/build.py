"""仮想成績による参加停止と再開を、短い説明と全場損益へまとめる。"""

from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
OUT = ROOT/'アルゴリズム調査/00085_仮想成績による参加停止と再開'
NAME = '仮想成績で停止再開する手法と全セッション損益.html'


def read(path):
    """
    機能: 保存済み日本語JSONを読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    """
    機能: 全81条件の保存結果から、説明と比較と全30場の公開HTMLを作る。
    引数: なし。
    返り値: None。条件選定・源再生・損益の再計算を行わない。
    """
    fixed = read(WORK/'事前固定.json')
    analysis = read(WORK/'analysis/比較結果.json')
    review_path = WORK/'review/独立解釈と全親会計再検算及び逃した回復利益.json'
    review = read(review_path)
    assert review['全合格']
    results = {c['id']: read(WORK/'results'/f"{c['id']}.json") for c in fixed['catalog']}
    assert len(results) == 81 and analysis['全合格']
    if 'results' in analysis:
        assert analysis['results'] == results
    selected = analysis.get('selected')
    assert selected is None or selected in results
    primary = analysis.get('primary', 'B0622_C16_P60')
    assert primary == 'B0622_C16_P60'
    controls = [c['id'] for c in fixed['catalog'] if c['gate']['mode'] == 'all']
    assert len(controls) == 3
    both_eighty = [identifier for identifier, result in results.items()
        if all(result['periods']['全30'][symbol]['profit_share'] is not None and
               result['periods']['全30'][symbol]['profit_share'] >= .8 for symbol in ('TOPIX', 'NK225'))]
    highlights = list(dict.fromkeys(controls+[primary]+([selected] if selected else [])+both_eighty))
    cases = []
    for symbol in ('TOPIX', 'NK225'):
        case = next(value for value in review['回復の最初の利益を拒否した具体3件']
                    if value['symbol'] == symbol and value['session'] == '2026-09-28_Day')
        cases.append(dict(symbol=symbol, session=case['session'], source=case['source'], cid=case['cid'],
            clock=case['decision'], past_share=case['past_share'], base_net=case['base_net'],
            accepted=case['accepted'], quantity=case['quantity'], stage='回復の初動'))
        following = case['following'][0]
        assert following['session'] == '2026-09-28_Night'
        cases.append(dict(symbol=symbol, session=following['session'], source=case['source'], cid=following['cid'],
            clock=following['clock'], past_share=following['past_share'], base_net=following['base_net'],
            accepted=following['accepted'], quantity=case['quantity'], stage='成績回復後'))
    cases.sort(key=lambda value: value['clock'])
    data = dict(results=results, catalog=fixed['catalog'], sessions=fixed['全30'], primary=primary,
        selected=selected, controls=controls, both_eighty=both_eighty, highlights=highlights,
        periods={p: fixed[p] for p in ('前16', '後14', '全30')},
        conclusion=analysis.get('conclusion', []), source_contributions=analysis.get('source_contributions', {}),
        differences=analysis.get('differences', {}), selection_proof=analysis.get('selection_proof'),
        specification=fixed['specification'], cases=cases)
    for result in results.values():
        assert len(result['rows']) == 60
        for row in result['rows']:
            assert abs(row['profit']-row['loss']-row['net']) < 1e-6
            assert abs(row['gross']-row['fees']-row['net']) < 1e-6
            assert row['new_lots'] == row['closed_lots']
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    page = (HERE/'template.html').read_text(encoding='utf-8')
    page = page.replace('__STYLE__', (HERE/'style.css').read_text(encoding='utf-8'))
    page = page.replace('__DATA__', payload).replace('__SCRIPT__', (HERE/'main.js').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT/NAME
    target.write_text(page, encoding='utf-8')
    paths = [WORK/'事前固定.json', WORK/'analysis/比較結果.json', review_path, *sorted((WORK/'results').glob('*.json')),
        HERE/'build.py', HERE/'template.html', HERE/'style.css', HERE/'main.js']
    proof = dict(全合格=True, 条件数=len(results), 各条件の口座数=60, 主仮説=primary, 前16選定=selected,
        両商品80割合候補=both_eighty, HTML=str(target.relative_to(ROOT)),
        HTML_SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),
        使用資料SHA256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (HERE/'生成結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
