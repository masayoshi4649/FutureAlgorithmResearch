"""公開資料と正式会計及び描画画像を読取り、99段階の終了不変確認だけを保存する。"""

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True


def read(path: Path) -> dict:
    """
    機能: 既存の正式結果又は公開証跡をUTF-8で読む。
    引数: path(Path)は読取対象。
    返り値: dict。既存ファイルを変更しない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 公開結果と固定依存の現在SHA256を算出する。
    引数: path(Path)は保存済みファイル。
    返り値: str。16進指紋。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_hashes(values: dict) -> int:
    """
    機能: 既存証跡に記載された全指紋を現在原本へ照合する。
    引数: values(dict[str,str])はプロジェクト相対パスと期待SHA。
    返り値: int。完全一致したファイル件数。不一致は例外で停止する。
    """
    for relative, expected in values.items():
        assert digest(ROOT / relative) == expected, relative
    return len(values)


def verify_finance(actual: object, expected: object, path: str = '') -> list[dict]:
    """
    機能: 正式独立結果へ構造と会計を厳密照合し、安定性だけ既存正式公差を維持する。
    引数: actual/expected(object)、path(str)は再帰中の検査箇所。
    返り値: list[dict]。演算順による安定性の非零差。金額行と期間会計は公差0。
    正式fullの構造比較は絶対公差1e-5であり、根と独立RMSの丸め順を同一と捏造しない。
    """
    differences = []
    if isinstance(actual, dict) and isinstance(expected, dict):
        assert actual.keys() == expected.keys(), path
        for key in actual:
            differences += verify_finance(actual[key], expected[key], path + '/' + str(key))
    elif isinstance(actual, list) and isinstance(expected, list):
        assert len(actual) == len(expected), path
        for index, (left, right) in enumerate(zip(actual, expected)):
            differences += verify_finance(left, right, path + '/' + str(index))
    elif actual != expected:
        assert '/stability/' in path and isinstance(actual, (int, float)) and isinstance(expected, (int, float)), path
        assert math.isfinite(actual) and math.isfinite(expected) and abs(actual - expected) <= 1e-5, path
        differences.append(dict(箇所=path, 絶対差=abs(actual - expected)))
    return differences


def main() -> None:
    """
    機能: 金融989依存、公開6資料、旧18成果、HTML全34会計と説明及び5画像を確認する。
    引数: なし。
    返り値: None。新99reportの確認JSONだけを保存し再読込する。
    画像は同turnに既存5枚を独立目視済み。新ブラウザ再描画を行ったとは主張しない。
    """
    fixed = read(WORK / '事前固定.json')
    publish = read(HERE / '公開結果.json')
    generation = read(HERE / '生成結果.json')
    display = read(HERE / '表示の独立検査.json')
    visual = read(HERE / '根担当の目視確認.json')
    finance_path = WORK / 'audit/全34全31の台帳会計と代表待機及び全原板の独立検算.json'
    finance = read(finance_path)
    analysis_path = WORK / 'analysis/比較結果.json'
    analysis = read(analysis_path)
    explanation_path = WORK / 'analysis/説明補足.json'
    explanation = read(explanation_path)
    assert all(value.get('全合格', value.get('合格')) for value in
               (publish, generation, display, visual, finance, analysis, explanation))
    assert not finance['人工専用'] and fixed['全31既知'] and fixed['新未見確認場数'] == 0
    assert len(fixed['SHA256']) == 989
    counts = dict(固定依存=verify_hashes(fixed['SHA256']),
                  公開指紋=verify_hashes(publish['公開SHA256']),
                  旧成果指紋=verify_hashes(publish['旧成果SHA256']),
                  生成参照=verify_hashes(generation['使用資料SHA256']),
                  表示コード=verify_hashes(display['表示検査コードSHA256']),
                  目視画像=verify_hashes(visual['画像SHA256']),
                  正式監査参照=verify_hashes(finance['SHA256']),
                  説明根拠=verify_hashes(explanation['根拠SHA256']))
    assert counts['公開指紋'] == 6 and counts['旧成果指紋'] == 18 and counts['目視画像'] == 5
    # ----------------------------------------
    # 公開HTMLの埋込データを根生成器なしで読み、正式会計・全期間・説明へ厳密照合する。
    html_path = ROOT / publish['公開資料']
    html = html_path.read_text(encoding='utf-8')
    html_sha = digest(html_path)
    assert html_sha == generation['HTML_SHA256'] == display['HTML_SHA256'] == visual['HTML_SHA256']
    assert html_sha == digest(ROOT / generation['HTML'])
    matches = re.findall(r'<script id="report-data" type="application/json">(.*?)</script>', html, re.S)
    assert len(matches) == 1
    payload = json.loads(matches[0])
    assert payload['results'] == analysis['results']
    rounding = verify_finance(payload['results'], finance['全会計'])
    assert payload['catalog'] == fixed['条件'] and len(payload['catalog']) == 34
    assert payload['sessions'] == fixed['全31'] and len(payload['sessions']) == 31
    assert payload['primary'] == analysis['primary'] == generation['理論主'] == 'L1_C1_A7_X3'
    assert payload['selected'] == analysis['selected'] == generation['前16参考代表'] == 'A0_X1'
    assert payload['conclusion'] == explanation['conclusion']
    assert payload['cause_notes'] == explanation['cause_notes']
    assert payload['stability_policy'] == analysis['セッション安定性の事前評価']
    assert payload['stability_policy'] == read(WORK / 'セッション安定性の事前評価.json')
    assert payload['both_eighty'] == analysis['both80'] == []
    spec = importlib.util.spec_from_file_location('99公開後の固定条件名読取', WORK / 'catalog.py')
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    assert payload['labels'] == catalog.labels()
    assert payload['comparison_pairs'] == {item['id']: catalog.references(item['id']) for item in fixed['条件']}
    public_account_paths = [ROOT / name for name in publish['公開SHA256'] if name.endswith('公開会計.json')]
    assert len(public_account_paths) == 1 and read(public_account_paths[0]) == analysis
    expected_keys = {(session, symbol) for session in fixed['全31'] for symbol in ('TOPIX', 'NK225')}
    accounts = 0
    periods = ['全31', '前16', '後15', '旧30', '後14', '追加1', 'デイ', 'ナイト']
    assert payload['period_names'] == periods
    for result in payload['results'].values():
        assert {(row['session'], row['symbol']) for row in result['rows']} == expected_keys
        assert set(result['periods']) == set(result['stability']) == set(periods)
        for row in result['rows']:
            assert abs(row['profit'] - row['loss'] - row['net']) < 1e-5
            assert abs(row['gross'] - row['fees'] - row['net']) < 1e-5
            assert row['winning_lots'] + row['losing_lots'] + row['flat_lots'] == row['lots']
            accounts += 1
    assert accounts == display['保存会計口座数'] == generation['口座数'] == 2108
    assert display['保存結果一致数'] == 34 and len(display['画面']) == 5
    assert visual['確認画像数'] == 5
    assert digest(HERE / '生成結果.json') == visual['生成結果SHA256']
    assert digest(HERE / '表示の独立検査.json') == visual['表示検査SHA256']
    for view in display['画面']:
        image_path = Path(view['画像'])
        relative = str(image_path.relative_to(ROOT))
        assert relative in visual['画像SHA256']
        assert digest(image_path) == visual['画像SHA256'][relative]
        assert view['全合格'] and view['条件切替数'] == 34 and view['セッション口座表示数'] == 2108
        assert view['JavaScriptエラー'] == 0 and view['背景'] == 'rgb(13, 17, 24)'
        assert view['文書幅'] <= view['画面幅']
    # ----------------------------------------
    # 終端でも固定を再照合し、公開確認が金融・旧成果を変更していないことを確認する。
    verify_hashes(fixed['SHA256'])
    verify_hashes(publish['旧成果SHA256'])
    paths = [WORK / '事前固定.json', HERE / '公開結果.json', HERE / '生成結果.json',
             HERE / '表示の独立検査.json', HERE / '根担当の目視確認.json', finance_path,
             analysis_path, explanation_path, Path(__file__)]
    references = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    references.update(publish['公開SHA256'])
    references.update(publish['旧成果SHA256'])
    references.update(visual['画像SHA256'])
    proof = dict(全合格=True, 局所段階='99の正式検算と00095公開を完了。探索目標は未達。',
        検査件数=counts, 公開HTML_SHA256=html_sha, 全34全31口座数=accounts, 全8商品期間=544,
        正式会計不変=True, 旧89から94全成果不変=True, 既存金融監査証跡及びコード変更=0,
        正式数値の照合='HTML対根集計は全項目完全一致。独立会計のrows/periodsも完全一致。安定性は正式fullと同じ絶対公差1e-5で構造を照合。',
        安定性の演算順丸め差件数=len(rounding), 安定性の最大絶対差=max((item['絶対差'] for item in rounding), default=0.),
        表示と目視HTML一致=True, 独立目視画像数=5,
        独立目視内容=['広幅で主の両赤字と参考の片側赤字、旧対照と安定性を隠さず短い結論として読める。',
            '狭幅は比較表だけ横スクロールし、文書全体の横溢れ・重なりを認めない。',
            '全31行と合計でTOPIX利益7332/損失36668/収支−29336、日経利益6048/損失102368/収支−96320を表示。',
            '全8期間・安定性・売買方向・源別の会計が別表になり、無取引を黒字と数えていない。',
            '原因と未測定案は折りたたみへ分け、実判断296秒と支持格子295秒を別時計として記載。'],
        目視の範囲='既存5描画画像を独立目視。各画像の記録、表示検査、生成前HTML及び公開HTMLの同一SHAを照合。新ブラウザ再描画や既存画像の変更は行わない。',
        探索目標達成=False, 両銘柄金額利益80達成数=0, 全31既知=True, 未見確認場数=0,
        API取得=0, 実注文=0, 新売買計算=0, SHA256=references)
    destination = HERE / '公開後の独立不変確認.json'
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    assert read(destination) == proof
    print(json.dumps(dict(全合格=True, 検査件数=counts, 確認証跡SHA256=digest(destination)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
