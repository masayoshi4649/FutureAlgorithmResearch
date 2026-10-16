"""保存結果と全20条件の表表示を照合して、隔離したブラウザで広狭画面を描画する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
MAIN = HERE / '公開前/増玉の停止余裕を残す手法と全セッション損益.html'
FIELDS = ('profit', 'loss', 'net', 'gross', 'fees', 'winning_lots', 'losing_lots', 'flat_lots', 'lots')
CAUSE = WORK / 'review/全31の余裕と据置及び同入口の独立原因比較.json'
AUDIT = WORK / 'audit/全20全31の増玉注文と親cohort及び全原板会計の独立検算.json'
ADDITIONAL = WORK / 'holdout_report/追加ナイトと全32の損益.json'
ADDITIONAL_AUDIT = WORK / 'audit/追加ナイト全20の40口座と原板及び独立管理の検算.json'


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


def fingerprint_for(values: dict[str, str], path: Path) -> str:
    """
    機能: 指紋台帳の区切り文字を同じ相対パスへ正規化して参照する。
    引数: values(dict[str,str])は保存指紋、path(Path)はROOT内の実ファイル。
    返り値: str。同じパスの指紋。欠落又は重複別指紋で停止し、資料を書き換えない。
    """
    wanted = path.relative_to(ROOT).as_posix()
    matches = [expected for relative, expected in values.items()
               if Path(relative.replace('\\', '/')).as_posix() == wanted]
    assert matches, f'指紋台帳に対象資料がありません: {wanted}'
    assert len(set(matches)) == 1, f'同じ資料の指紋が一致しません: {wanted}'
    return matches[0]


def formal_evidence() -> dict:
    """
    機能: 元31会計・独立原因・根説明と追加40会計・全32合算を別々に指紋照合する。
    引数: なし。保存済み正式資料だけを読取り、新しい売買を再生しない。
    返り値: dict。正式集計・固定・原因・根説明及び合格会計の読取内容。
    """
    paths = {'fixed': WORK / '事前固定.json', 'analysis': WORK / 'analysis/比較結果.json',
             'explanation': WORK / 'analysis/説明補足.json', 'audit': AUDIT, 'cause': CAUSE,
             'additional': ADDITIONAL, 'additional_audit': ADDITIONAL_AUDIT}
    assert all(path.exists() for path in paths.values()), '元31と追加40の独立会計・独立原因・全32合算・根説明が必要です'
    values = {name: read(path) for name, path in paths.items()}
    fixed, analysis, explanation = values['fixed'], values['analysis'], values['explanation']
    audit, cause = values['audit'], values['cause']
    assert fixed['正式新条件損益前固定'] and fixed['全31既知'] and len(fixed['全31']) == 31
    assert analysis['全合格'] and analysis['全31既知'] and analysis['条件数'] == 20
    assert audit['合格'] and not audit['人工専用'] and audit['検査件数']['口座'] == 1240
    assert cause['全合格'] is True and isinstance(cause['scope'], str) and cause['scope'].strip()
    assert len(cause['手法一覧']) == cause['検査件数']['条件'] == 5
    assert cause['対象口座数'] == cause['検査件数']['口座'] == 5 * 31 * 2
    assert set(cause['手法一覧']).issubset(analysis['results'])
    additional, additional_audit = values['additional'], values['additional_audit']
    assert additional['全合格'] and additional['条件数'] == 20
    assert additional['元31口座数'] == 1240 and additional['追加口座数'] == 40 and additional['全32口座数'] == 1280
    assert additional_audit['合格'] and not additional_audit['人工専用']
    assert additional_audit['検査件数']['口座'] == additional_audit['検査件数']['商品期間'] == 40
    assert additional_audit['開始終端ソース一致'] and additional_audit['追加による条件変更'] == additional_audit['追加による参考再選択'] == 0
    assert additional['session'] == additional_audit['対象'] and additional['session'] not in fixed['全31']
    assert additional['primary'] == analysis['primary'] and additional['selected'] == analysis['selected']
    assert set(additional['results']) == set(analysis['results'])
    check_additional(additional, additional_audit, analysis)
    assert explanation['全合格'] and explanation['正式全範囲独立検算完了']
    assert explanation['売買及び会計の変更'] == 0
    assert explanation['根集計SHA256'] == digest(paths['analysis'])
    assert fingerprint_for(cause['SHA256'], paths['analysis']) == digest(paths['analysis']), '独立原因は現在の根集計と結合する必要があります'
    for path in (CAUSE, AUDIT, paths['analysis']):
        assert fingerprint_for(explanation['根拠SHA256'], path) == digest(path)
    assert fingerprint_for(additional['SHA256'], ADDITIONAL_AUDIT) == digest(ADDITIONAL_AUDIT)
    assert fingerprint_for(additional['SHA256'], paths['analysis']) == digest(paths['analysis'])
    for proof, field in ((cause, 'SHA256'), (explanation, '根拠SHA256'), (analysis, '正式結果SHA256'),
                         (additional, 'SHA256'), (additional_audit, 'SHA256')):
        assert proof[field]
        for relative, expected in proof[field].items():
            assert digest(ROOT / relative) == expected, relative
    return values


def check_additional(additional: dict, audit: dict, analysis: dict) -> None:
    """
    機能: 全20追加口座を独立40会計へ照合し、元31を保持した全32の金額と枚数を再集計する。
    引数: additional/audit/analysis(dict)は追加合算・追加独立会計・元31根集計。
    返り値: None。追加確認を元31へ混ぜたり、同じ収支の二会計を加算したら停止する。
    """
    counts = ('campaigns', 'winning_campaigns', 'losing_campaigns', 'flat_campaigns', 'order_count',
              'entry_order_count', 'adding_order_count', 'positive_sessions', 'losing_sessions',
              'no_trade_sessions', 'active_sessions', 'session_count')
    cohort_counts = ('cohorts', 'winning_cohorts', 'losing_cohorts', 'flat_cohorts')
    assert set(audit['全会計']) == set(additional['results'])
    for ident, markets in additional['results'].items():
        assert set(markets) == {'TOPIX', 'NK225'}
        for symbol, item in markets.items():
            known, added, all32 = item['known31'], item['additional1'], item['all32']
            assert known == analysis['results'][ident]['periods']['全31'][symbol], '元31集計が差し替えられています'
            assert added == audit['全会計'][ident]['periods']['追加ナイト1'][symbol], '追加口座は独立40会計と一致する必要があります'
            assert known['session_count'] == 31 and added['session_count'] == 1 and all32['session_count'] == 32
            for basis in ('parents', 'cohorts'):
                values = [known, added, all32] if basis == 'parents' else [value['cohorts'] for value in (known, added, all32)]
                for field in FIELDS:
                    assert abs(values[0][field] + values[1][field] - values[2][field]) < 1e-5, (ident, symbol, basis, field)
                assert abs(values[2]['profit'] - values[2]['loss'] - values[2]['net']) < 1e-5
                assert abs(values[2]['gross'] - values[2]['fees'] - values[2]['net']) < 1e-5
                assert values[2]['winning_lots'] + values[2]['losing_lots'] + values[2]['flat_lots'] == values[2]['lots']
                denominator = values[2]['profit'] + values[2]['loss']
                share = values[2]['profit_share']
                if denominator == 0:
                    assert share is None
                else:
                    assert abs(share - values[2]['profit'] / denominator) < 1e-12
            for field in counts:
                assert known[field] + added[field] == all32[field], (ident, symbol, field)
            for field in cohort_counts:
                assert known['cohorts'][field] + added['cohorts'][field] == all32['cohorts'][field]
            for value in (known, added, all32):
                assert abs(value['net'] - value['cohorts']['net']) < 1e-5
                cap = 10 if symbol == 'TOPIX' else 20
                assert value['maximums']['occupied_long'] <= cap and value['maximums']['occupied_short'] <= cap
            for field in all32['maximums']:
                assert all32['maximums'][field] == max(known['maximums'][field], added['maximums'][field])
            stability = item['stability32']
            for field in ('active_sessions', 'losing_sessions', 'no_trade_sessions'):
                assert stability[field] == all32[field], (ident, symbol, field)


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
    引数: CLIの--root-report-generated (bool) は根の生成完了と表示検査許可。
    返り値: None。売買・会計・公開HTMLを変更しない。
    """
    parser = argparse.ArgumentParser(description='正式会計と独立原因及び根生成が揃った後だけ表示を検査します。')
    parser.add_argument('--root-report-generated', action='store_true')
    args = parser.parse_args()
    assert args.root_report_generated, '根の生成完了と表示検査の明示許可が必要です'
    assert not (HERE / '表示の独立検査.json').exists(), '表示検査の旧証跡を上書きしません'
    evidence = formal_evidence()
    generated = read(HERE / '生成結果.json')
    assert generated['全合格'] and generated['条件数'] == 20 and generated['口座数'] == 1240
    original = digest(MAIN)
    assert generated['HTML_SHA256'] == original
    for relative, expected in generated['使用資料SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    source = MAIN.read_text(encoding='utf-8')
    soup = BeautifulSoup(source, 'html.parser')
    payload = json.loads(soup.select_one('#report-data').string)
    fixed, analysis, explanation = evidence['fixed'], evidence['analysis'], evidence['explanation']
    assert payload['results'] == analysis['results'] and len(payload['results']) == 20
    assert payload['catalog'] == fixed['条件'] and payload['sessions'] == fixed['全31']
    assert payload['primary'] == payload['default_method'] == analysis['primary']
    assert payload['selected'] == analysis['selected']
    assert payload['conclusion'] == explanation['conclusion']
    assert payload['cause_notes'] == explanation['cause_notes']
    assert payload['report_diagnostics'] == explanation['report_diagnostics']
    assert payload['additional'] == evidence['additional'], '追加表は現在の合算証跡そのものを表示する必要があります'
    for result in payload['results'].values():
        check_result(result, fixed)
    spec = importlib.util.spec_from_file_location('102隔離表示の共通描画', ROOT / 'work/wave_v52/review/verify_report.py')
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
             (source, '追加1と全32合計', 1700, 1500, '<script>document.querySelector("main").replaceChildren(document.getElementById("additional-section"));window.scrollTo(0,0);</script>')]
    outputs = []
    for view in views:
        outputs.append(renderer.render(*view))
        print(view[1] + ' の全20表示照合と描画が合格', flush=True)
    assert digest(MAIN) == original
    proof = dict(全合格=True, 目視確認=False, 保存結果一致数=20, 保存会計口座数=1240,
                 保存追加会計口座数=40, 保存全32口座数=1280, 元31表を不変保持=True,
                 相殺前と親表示を両検査=True, HTML_SHA256=original, 画面=outputs,
                 通信遮断='CSP接続禁止と到達不能proxy。現在API取得及び実注文0。',
                 原因の範囲=evidence['cause']['scope'],
                 正式根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in
                     (WORK / 'analysis/比較結果.json', WORK / 'analysis/説明補足.json', CAUSE, AUDIT,
                      ADDITIONAL, ADDITIONAL_AUDIT, HERE / '生成結果.json')},
                 表示検査コードSHA256={str(path.relative_to(ROOT)): digest(path) for path in
                     (Path(__file__), HERE / 'probe.js', ROOT / 'work/wave_v52/review/verify_report.py')})
    (HERE / '表示の独立検査.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
