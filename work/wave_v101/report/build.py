"""全玉損失予算を固定した20条件の正式会計を、短い暗色レポートへ表示する。"""

import argparse
import hashlib
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / '公開前'
MAIN = OUT / '小さく入り利益で増やす手法と全セッション損益.html'
PRIMARY = 'G1_Q1_X1'
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('全31', '前16', '後15', '旧30', '後14', '追加1', 'デイ', 'ナイト')


def read(path: Path) -> dict:
    """
    機能: 正式な日本語JSON資料を読み取る。
    引数: path (Path) は資料の保存先。
    返り値: dict。未完成資料をゼロ損益へ置換しない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 保存資料の内容をSHA256で照合する。
    引数: path (Path) は読み取り対象。
    返り値: str。ファイル全体の指紋。
    """
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def verify_fingerprints(values: dict[str, str]) -> None:
    """
    機能: 根が保存した依存資料と現在の実ファイルを照合する。
    引数: values (dict[str,str]) はルート相対パスとSHA256。
    返り値: None。不一致ではHTMLを生成しない。
    """
    for relative, expected in values.items():
        assert digest(ROOT / relative) == expected, relative


def verify_totals(value: dict) -> None:
    """
    機能: 親会計又は実建玉群会計の金額と枚数を検算する。
    引数: value (dict) は同商品・同期間の集計。
    返り値: None。相殺前の利益と損失を収支と混同しない。
    """
    fields = ('profit', 'loss', 'net', 'gross', 'fees')
    assert all(isinstance(value[name], (int, float)) and math.isfinite(value[name]) for name in fields)
    assert value['profit'] >= 0 and value['loss'] >= 0 and value['fees'] >= 0
    assert math.isclose(value['profit'] - value['loss'], value['net'], abs_tol=1e-4)
    assert math.isclose(value['gross'] - value['fees'], value['net'], abs_tol=1e-4)
    assert value['winning_lots'] + value['losing_lots'] + value['flat_lots'] == value['lots']
    denominator = value['profit'] + value['loss']
    if denominator:
        assert math.isclose(value['profit_share'], value['profit'] / denominator, abs_tol=1e-12)
    else:
        assert value['profit_share'] is None


def verify_account(value: dict) -> None:
    """
    機能: 親内相殺と実建玉群の相殺前会計が同じ実現金損益を示すか確認する。
    引数: value (dict) は親集計とcohorts集計を含む会計。
    返り値: None。両会計は同じ収支であり加算するものではない。
    """
    verify_totals(value)
    verify_totals(value['cohorts'])
    for name in ('net', 'gross', 'fees', 'lots'):
        assert math.isclose(value[name], value['cohorts'][name], abs_tol=1e-4), name


def main() -> None:
    """
    機能: 根の明示許可と正式全範囲検算後だけ、新しい報告HTMLを生成する。
    引数: CLIの--root-all31-independent-complete (bool) は根による生成許可。
    返り値: None。売買再生、参考選定、会計の変更、公開と案内更新は行わない。
    """
    parser = argparse.ArgumentParser(description='正式全31場と独立検算が完了した後だけ生成します。')
    parser.add_argument('--root-all31-independent-complete', action='store_true')
    args = parser.parse_args()
    assert args.root_all31_independent_complete, '根の正式全31場・独立検算完了と生成許可が必要です'

    # ----------------------------------------
    required = [WORK / name for name in ('事前固定.json', '前16参考代表.json',
                'analysis/比較結果.json', 'analysis/説明補足.json', 'セッション安定性の事前評価.json')]
    assert all(path.exists() for path in required), '正式会計と独立検算の資料が揃っていません'
    fixed, selection, analysis, explanation, stability_policy = [read(path) for path in required]
    assert fixed['正式新条件損益前固定'] and fixed['全31既知']
    assert analysis['全合格'] and analysis['全31既知'] and analysis['条件数'] == 20
    assert explanation['全合格'] and explanation['正式全範囲独立検算完了']
    assert explanation['売買及び会計の変更'] == 0
    assert explanation['根集計SHA256'] == digest(WORK / 'analysis/比較結果.json')
    assert explanation['根拠SHA256'], '独立検算の根拠指紋が必要です'
    verify_fingerprints(fixed['SHA256'])
    verify_fingerprints(selection['結果SHA256'])
    verify_fingerprints(analysis['正式結果SHA256'])
    verify_fingerprints(explanation['根拠SHA256'])
    assert selection['全合格'] and selection['後15正式損益前選定'] and selection['全31既知']
    assert selection['固定SHA256'] == digest(WORK / '事前固定.json')
    assert fixed['主'] == analysis['primary'] == PRIMARY
    assert analysis['selected'] == selection['selected']
    assert analysis['セッション安定性の事前評価'] == stability_policy
    catalog, sessions, results = fixed['条件'], fixed['全31'], analysis['results']
    assert len(catalog) == 20 and len({value['id'] for value in catalog}) == 20
    assert analysis['catalog'] == catalog and analysis['sessions'] == sessions
    assert len(sessions) == 31 and len(set(sessions)) == 31
    assert set(results) == {value['id'] for value in catalog}
    selected = analysis['selected']
    assert selected in results

    # ----------------------------------------
    for ident, result in results.items():
        rows = result['rows']
        assert result['config'] == next(value for value in catalog if value['id'] == ident)
        assert len(rows) == 62 and {(row['session'], row['symbol']) for row in rows} == {
            (session, symbol) for session in sessions for symbol in SYMBOLS}
        for row in rows:
            verify_account(row)
        for period in PERIODS:
            for symbol in SYMBOLS:
                account = result['periods'][period][symbol]
                verify_account(account)
                stable = result['stability'][period][symbol]
                assert stable['mean_losing_session_yen'] >= 0 and stable['worst_session_loss_yen'] >= 0
                assert stable['session_count'] == account['session_count']
                assert stable['active_sessions'] == account['active_sessions']
                assert stable['no_trade_sessions'] == account['no_trade_sessions']
                assert stable['losing_sessions'] == account['losing_sessions']
                verify_account(account['without_best_day'])
        for symbol in SYMBOLS:
            chosen = [row for row in rows if row['symbol'] == symbol]
            total = result['periods']['全31'][symbol]
            for name in ('profit', 'loss', 'net', 'gross', 'fees', 'winning_lots', 'losing_lots', 'flat_lots', 'lots'):
                assert math.isclose(sum(row[name] for row in chosen), total[name], abs_tol=1e-4)
                assert math.isclose(sum(row['cohorts'][name] for row in chosen), total['cohorts'][name], abs_tol=1e-4)

    # ----------------------------------------
    highlights = list(dict.fromkeys([PRIMARY, selected, 'G0_Q1_X1', 'G0_QFULL_X1', 'G2_Q1_X1', 'G1_Q1_X3']))
    assert all(ident in results for ident in highlights)
    diagnostics = explanation.get('report_diagnostics', {})
    assert isinstance(diagnostics, dict)
    conclusion = list(explanation['conclusion'])
    assert len(conclusion) >= 3
    stable_success = analysis['両商品で全場黒字']
    target_success = analysis['活動充足の両80']
    missing_goal = ''
    if not stable_success and not target_success:
        missing_goal = '両商品で全31場黒字の手法はなく、十分な活動を伴う金額利益80%も未達です。'
    elif not target_success:
        missing_goal = '十分な活動を伴う両商品の金額利益80%は未達です。'
    elif not stable_success:
        missing_goal = '両商品で全31場黒字は未達です。金額利益80%の達成とは区別します。'
    if missing_goal and not any(word in conclusion[0] for word in ('未達', '採用しません')):
        conclusion[0] = missing_goal + ' ' + conclusion[0]
    assert selection['level'] in range(6)
    payload = dict(primary=PRIMARY, selected=selected, selection_level=selection['level'], default_method=PRIMARY,
                   highlights=highlights, catalog=catalog, labels=analysis['labels'],
                   sessions=sessions, results=results, period_names=list(PERIODS),
                   comparison_pairs=analysis['comparison_pairs'],
                   conclusion=conclusion, cause_notes=explanation['cause_notes'],
                   report_diagnostics=diagnostics, stability_policy=stability_policy,
                   both_eighty=analysis['both80'], active_both_eighty=analysis['活動充足の両80'])
    assert len(payload['conclusion']) >= 3
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    page = (HERE / 'template.html').read_text(encoding='utf-8')
    page = page.replace('__STYLE__', (HERE / 'style.css').read_text(encoding='utf-8'))
    page = page.replace('__DATA__', encoded).replace('__SCRIPT__', (HERE / 'main.js').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True, exist_ok=True)
    MAIN.write_text(page, encoding='utf-8')
    sources = required + [HERE / name for name in ('build.py', 'template.html', 'style.css', 'main.js')]
    sources += [ROOT / name for name in explanation['根拠SHA256']]
    proof = dict(全合格=True, 条件数=20, 口座数=1240, 表示親口座数=1240, 表示実玉群口座数=1240,
                 全31既知=True, 正式新未見確認場数=0, 理論主=PRIMARY, 前16参考代表=selected,
                 相殺前建玉群を主表示=True, 親会計と建玉群会計は同じ収支=True,
                 HTML=str(MAIN.relative_to(ROOT)), HTML_SHA256=digest(MAIN),
                 使用資料SHA256={str(path.relative_to(ROOT)): digest(path) for path in sources})
    (HERE / '生成結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
