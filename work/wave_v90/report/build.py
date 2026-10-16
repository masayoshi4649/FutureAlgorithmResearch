"""旧27と執行を改めた15条件の保存会計を、短い説明と全場表へまとめる。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
OUT = ROOT / 'アルゴリズム調査/00086_二市場の状態で追従と指値反発を配分'
MAIN = OUT / '二つの戦略への配分と全セッション損益.html'


def read(path):
    """
    機能: 正式に保存された日本語JSONを読む。
    引数: path (Path)。
    返り値: dict の内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    """
    機能: 会計資料又は公開HTMLの指紋を求める。
    引数: path (Path)。
    返り値: str のSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def main():
    """
    機能: 全42条件の正式結果と親の分析を埋め込んだ暗色HTMLを生成する。
    引数: なし。
    返り値: None。売買判断、条件選択、新しい損益の計算は行わない。
    """
    fixed = read(WORK / '事前固定.json')
    extra = read(WORK / 'round2/事前固定.json')
    analysis = read(WORK / 'analysis/比較結果.json')
    assert fixed['新損益閲覧前固定'] and extra['新損益閲覧前固定'] and analysis['全合格']
    for relative, expected in extra['SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    catalog = fixed['条件'] + extra['条件']
    assert len(catalog) == 42 and extra['主'] == analysis['primary'] == 'D_C_QA'
    locations = {config['id']: WORK for config in fixed['条件']}
    locations.update({config['id']: WORK / 'round2' for config in extra['条件']})
    results = {config['id']: read(locations[config['id']] / 'results' / (config['id'] + '.json')) for config in catalog}
    if 'results' in analysis:
        assert analysis['results'] == results
    selected = analysis.get('selected')
    assert selected is None or selected in results
    highlights = list(dict.fromkeys(['D_C_QA'] + ([selected] if selected else []) + ['M82_Q', 'J10_Q', 'O10_Q']))
    data = dict(primary='D_C_QA', selected=selected, default_method='M82_Q', highlights=highlights, catalog=catalog,
                sessions=fixed['全30'], results=results, conclusion=analysis['conclusion'],
                cause_notes=analysis.get('cause_notes', {}),
                both_eighty=analysis.get('both80', analysis.get('both_eighty', [])))
    for result in results.values():
        assert len(result['rows']) == 60
        for row in result['rows']:
            assert abs(row['profit'] - row['loss'] - row['net']) < 1e-5
            assert abs(row['gross'] - row['fees'] - row['net']) < 1e-5
            assert row['winning_lots'] + row['losing_lots'] + row['flat_lots'] == row['lots']
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    page = (HERE / 'template.html').read_text(encoding='utf-8')
    page = page.replace('__STYLE__', (HERE / 'style.css').read_text(encoding='utf-8'))
    page = page.replace('__DATA__', payload).replace('__SCRIPT__', (HERE / 'main.js').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True, exist_ok=True)
    MAIN.write_text(page, encoding='utf-8')
    paths = [WORK / '事前固定.json', WORK / 'round2/事前固定.json', WORK / 'analysis/比較結果.json',
             *sorted((WORK / 'results').glob('*.json')),
             *sorted((WORK / 'round2/results').glob('*.json')),
             HERE / 'build.py', HERE / 'template.html', HERE / 'style.css', HERE / 'main.js']
    proof = dict(全合格=True, 条件数=42, 口座数=2520, 理論主='D_C_QA', 前16参考代表=selected,
                 HTML=str(MAIN.relative_to(ROOT)), HTML_SHA256=digest(MAIN),
                 使用資料SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths})
    (HERE / '生成結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
