"""固定した38条件の保存会計を、短い説明と追加1場・全31場の表へまとめる。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
OUT = ROOT / 'アルゴリズム調査/00087_待機基準の保持と二市場反対による返済'
MAIN = OUT / '待機基準と反対返済の改善と全セッション損益.html'


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
    機能: 全38条件の正式会計を暗色HTMLへ埋め込む。
    引数: なし。
    返り値: None。売買判断、参考代表の選択、新しい損益計算は行わない。
    正式結果がない状態をゼロ利益として公開せず、未完資料は生成前に拒否する。
    """
    fixed = read(WORK / '事前固定.json')
    selection = read(WORK / '前16参考代表.json')
    analysis = read(WORK / 'analysis/比較結果.json')
    assert fixed['完結新条件損益閲覧前固定'] and analysis['全合格']
    assert selection['全合格'] and selection['追加Day完結損益前選定']
    for relative, expected in fixed['SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    catalog = fixed['条件']
    assert len(catalog) == 38
    assert fixed['主'] == analysis['primary'] == 'P_G82_HUNL'
    results = analysis['results']
    assert set(results) == {config['id'] for config in catalog}
    sessions = fixed['全31']
    assert len(sessions) == 31 and len(set(sessions)) == 31
    assert sessions[-1] == '2026-10-12_Day'
    selected = analysis.get('selected')
    assert selected == selection['selected']
    assert selected is None or selected in results
    for relative, expected in selection['結果SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    periods = ['全31', '旧30', '前16', '後14', '追加1', 'デイ', 'ナイト']
    for result in results.values():
        assert len(result['rows']) == 62
        assert set(periods).issubset(result['periods'])
        assert {(row['session'], row['symbol']) for row in result['rows']} == {
            (session, symbol) for session in sessions for symbol in ('TOPIX', 'NK225')}
        for row in result['rows']:
            assert abs(row['profit'] - row['loss'] - row['net']) < 1e-5
            assert abs(row['gross'] - row['fees'] - row['net']) < 1e-5
            assert row['winning_lots'] + row['losing_lots'] + row['flat_lots'] == row['lots']
    assert isinstance(analysis['conclusion'], list) and analysis['conclusion']
    highlights = list(dict.fromkeys(['P_G82_HUNL'] + ([selected] if selected else [])
                                    + ['J8', 'J10', 'M82', 'P_G82']))
    data = dict(primary=analysis['primary'], selected=selected, default_method=analysis['primary'],
                highlights=highlights, fresh_highlights=list(dict.fromkeys([analysis['primary']]
                   + ([selected] if selected else []))), catalog=catalog, sessions=sessions,
                period_names=periods, results=results, conclusion=analysis['conclusion'],
                cause_notes=analysis.get('cause_notes', {}),
                both_eighty=analysis.get('both80', analysis.get('both_eighty', [])))
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    page = (HERE / 'template.html').read_text(encoding='utf-8')
    page = page.replace('__STYLE__', (HERE / 'style.css').read_text(encoding='utf-8'))
    page = page.replace('__DATA__', payload).replace('__SCRIPT__', (HERE / 'main.js').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True, exist_ok=True)
    MAIN.write_text(page, encoding='utf-8')
    paths = [WORK / '事前固定.json', WORK / '前16参考代表.json', WORK / 'analysis/比較結果.json', HERE / 'build.py',
             HERE / 'template.html', HERE / 'style.css', HERE / 'main.js']
    proof = dict(全合格=True, 条件数=38, 口座数=2356, 理論主=analysis['primary'], 前16参考代表=selected,
                 HTML=str(MAIN.relative_to(ROOT)), HTML_SHA256=digest(MAIN),
                 使用資料SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths})
    (HERE / '生成結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
