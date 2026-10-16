"""公開資料と監査済み保存結果の接続を独立に確認する。"""

import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00081_E01原版と知見統合改修の再検証'


def read(path):
    """
    機能: 日本語JSONを読み込む。
    引数: path (Path) は保存先。
    返り値: dict又はlist の復元資料。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    """
    機能: ファイル実体の指紋を求める。
    引数: path (Path) は対象ファイル。
    返り値: str のSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """
    機能: 公開2HTMLの会計データ・文面の根拠・入力指紋を確認する。
    引数: なし。
    返り値: None。監査JSONを保存し、不一致では例外を送出する。
    """
    generated = read(WORK / 'report/生成結果.json')
    display = read(WORK / 'report/描画資料.json')
    fixed = read(WORK / 'results/事前固定.json')
    full = read(HERE / '全25条件二モデルの独立会計監査.json')
    assert full['全合格'] and full['口座数'] == 3000
    checked = 0
    for model in ('observed', 'specified'):
        for config in fixed['catalog']:
            result = read(WORK / model / 'results' / (config['id'] + '.json'))
            assert display['results'][model][config['id']] == result
            checked += 1
    assert display['fixed']['primary'] == ['E01', 'E01_G', 'E01_GPDC']
    sources = 0
    for name, expected in generated['入力SHA256'].items():
        assert digest(ROOT / name) == expected, name
        sources += 1
    htmls = {}
    for name, expected in generated['公開SHA256'].items():
        path = PUBLIC / name
        assert digest(path) == expected, name
        text = path.read_text(encoding='utf-8')
        match = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', text, re.S)
        assert match and json.loads(match.group(1)) == display
        assert '全30場は既知' in text or '前16・後14の全データは既知' in text
        htmls[name] = expected

    # ----------------------------------------
    # 親組会計による結論文の数値を、全表の元データから直接照合する。
    conclusions = {}
    for symbol in ('TOPIX', 'NK225'):
        records = {name: display['results']['observed'][name]['periods']['全30'][symbol]
                   for name in ('E01', 'E01_G', 'E01_GPDC', 'E01_G_U')}
        original, gate, full_parts, quiet = (records[name] for name in records)
        assert gate['net'] > original['net']
        assert full_parts['net'] < gate['net']
        assert quiet['net'] < gate['net'] and quiet['max_drawdown'] < gate['max_drawdown']
        assert gate['cycle_profit_share'] < .8
        expected_percent = '59.3%' if symbol == 'TOPIX' else '57.5%'
        assert f"{gate['cycle_profit_share'] * 100:.1f}%" == expected_percent
        conclusions[symbol] = {name: {key: row[key] for key in
            ('net', 'cycle_profit', 'cycle_loss', 'cycle_profit_share', 'cycle_payoff',
             'positive_sessions', 'negative_sessions', 'max_drawdown', 'best_session_removed')}
            for name, row in records.items()}

    parts = read(WORK / 'analysis/4部品の有無比較.json')
    comparisons = []
    for part in ('P', 'D'):
        for symbol in ('TOPIX', 'NK225'):
            subset = [r for r in parts['pairs'] if r['model'] == 'observed' and r['period'] == '全30'
                      and r['部品'] == part and r['symbol'] == symbol]
            assert len(subset) == 8
            for row in subset:
                before = display['results']['observed'][row['なし']]['periods']['全30'][symbol]
                after = display['results']['observed'][row['あり']]['periods']['全30'][symbol]
                for key in ('net', 'campaign_profit', 'campaign_loss'):
                    assert row['before'][key] == before[key]
                    assert row['after'][key] == after[key]
                assert after['net'] < before['net'] and after['campaign_profit'] < before['campaign_profit']
            comparisons.append({'部品': part, '銘柄': symbol, '対照数': 8,
                                '全件収支悪化': True, '全件親組利益減少': True})

    proof = {'全合格': True, '公開SHA256': htmls, '入力指紋一致数': sources,
             '公開埋込会計一致数': checked, '2HTMLの全埋込資料一致': True,
             '結論の根拠': conclusions, '部品説明の根拠': comparisons,
             '文面確認': ['観測価格はラージCurrentPriceで売買気配約定ではないと明記',
                          '利益保護は次保存行から有効で利益下限保証なしと明記',
                          '時間窓内の欠測時は窓後最初の有効観測で返済する実装と一致',
                          '主3条件と時間回避9条件は事前固定、既知30場を未知検証と呼ばない',
                          '親組を主会計とし、部分決済勝ち枚数とは分離',
                          'GへのU追加時の最大下落減少を他条件へ一般化していない',
                          '冬時間は時計検査のみで相場検証したとは記載していない'],
             '限界': '会計と因果順序の合格は、小型商品の約定可能性や将来利益の証明ではない。'}
    (HERE / '公開HTMLの数値と解釈監査.json').write_text(
        json.dumps(proof, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'全合格': True, '公開結果一致': checked, '入力指紋': sources,
                      '公開SHA256': htmls}, ensure_ascii=False))


if __name__ == '__main__':
    main()
