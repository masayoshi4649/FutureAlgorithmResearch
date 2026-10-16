"""固定した38条件を、各セッションの赤字抑制と安定性から短く比較する。"""

import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
OUT = ROOT / 'アルゴリズム調査/00091_両市場追従と損失後の反転確認'
MAIN = OUT / '両市場追従と反転確認の説明と全セッション損益.html'


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
    required = [WORK / '事前固定.json', WORK / '前16参考代表.json', WORK / 'analysis/比較結果.json',
                WORK / 'analysis/説明補足.json']
    assert all(path.exists() for path in required), '正式集計が完了するまで報告HTMLは生成しません'
    fixed = read(WORK / '事前固定.json')
    selection = read(WORK / '前16参考代表.json')
    analysis = read(WORK / 'analysis/比較結果.json')
    explanation_path = WORK / 'analysis/説明補足.json'
    explanation = read(explanation_path)
    assert explanation['全合格'] and len(explanation['根拠SHA256']) >= 4
    assert explanation['正式全範囲独立検算完了'] and explanation['独立原因検査完了']
    assert explanation['根集計SHA256'] == digest(WORK / 'analysis/比較結果.json')
    assert explanation['売買及び会計の変更'] == 0
    for relative, expected in explanation['根拠SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    assert fixed['正式新条件損益前固定'] and fixed['全31既知'] and analysis['全合格']
    assert selection['全合格'] and selection['後15正式損益前選定'] and selection['全31既知']
    for relative, expected in fixed['SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    catalog = fixed['条件']
    assert len(catalog) == 38
    assert fixed['主'] == analysis['primary'] == 'P3_R3_N'
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
    periods = ['全31', '前16', '後15', '旧30', '後14', '追加1', 'デイ', 'ナイト']
    stability_policy=read(WORK / 'セッション安定性の事前評価.json')
    assert analysis['セッション安定性の事前評価']==stability_policy
    for result in results.values():
        assert len(result['rows']) == 62
        assert set(periods).issubset(result['periods'])
        assert set(periods).issubset(result['stability'])
        for period in periods:
            for symbol in ('TOPIX','NK225'):
                stable=result['stability'][period][symbol]
                assert stable['configured_quantity']>0 and stable['mean_losing_session_yen']>=0
                assert stable['worst_session_loss_yen']>=0
        assert {(row['session'], row['symbol']) for row in result['rows']} == {
            (session, symbol) for session in sessions for symbol in ('TOPIX', 'NK225')}
        for row in result['rows']:
            assert abs(row['profit'] - row['loss'] - row['net']) < 1e-5
            assert abs(row['gross'] - row['fees'] - row['net']) < 1e-5
            assert row['winning_lots'] + row['losing_lots'] + row['flat_lots'] == row['lots']
    assert isinstance(analysis['conclusion'], list) and analysis['conclusion']
    spec = importlib.util.spec_from_file_location('表示条件名95', WORK / 'catalog.py')
    condition_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(condition_module)
    labels = condition_module.labels()
    comparisons = {config['id']: condition_module.references(config['id']) for config in catalog}
    assert comparisons == analysis.get('comparison_pairs', comparisons)
    highlights = list(dict.fromkeys([analysis['primary']] + ([selected] if selected else [])
                                    + ['P0_R0', 'P3_R0', 'P3_R3_N_Q4']))
    data = dict(primary=analysis['primary'], selected=selected, default_method=analysis['primary'],
                highlights=highlights, catalog=catalog, labels=labels, sessions=sessions,
                period_names=periods, results=results,
                conclusion=explanation['conclusion'],
                cause_notes=explanation['cause_notes'],
                comparison_pairs=comparisons,
                stability_policy=stability_policy,
                both_eighty=analysis.get('both80', analysis.get('both_eighty', [])))
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    page = (HERE / 'template.html').read_text(encoding='utf-8')
    page = page.replace('__STYLE__', (HERE / 'style.css').read_text(encoding='utf-8'))
    page = page.replace('__DATA__', payload).replace('__SCRIPT__', (HERE / 'main.js').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True, exist_ok=True)
    MAIN.write_text(page, encoding='utf-8')
    paths = [WORK / '事前固定.json', WORK / '前16参考代表.json', WORK / 'analysis/比較結果.json', HERE / 'build.py',
             HERE / 'template.html', HERE / 'style.css', HERE / 'main.js']
    paths += [explanation_path] + [ROOT / relative for relative in explanation['根拠SHA256']]
    paths.append(WORK / 'catalog.py')
    paths.append(WORK / 'セッション安定性の事前評価.json')
    proof = dict(全合格=True, 条件数=38, 口座数=2356, 全31既知=True,
                 理論主=analysis['primary'], 前16参考代表=selected,
                 HTML=str(MAIN.relative_to(ROOT)), HTML_SHA256=digest(MAIN),
                 使用資料SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths})
    (HERE / '生成結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
