"""110の固定順位を保持し、111の保存六条件と新297口座へ表示を接続する。"""

import hashlib
import json
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]


def main() -> None:
    """
    機能: 未読の111結果へ旧順位を変えず表示の名前/再利用範囲だけを接続する。
    引数: なし。コピー元sourceと110金融前の小選定だけを参照する。
    返り値: None。ROOT集計通知は受領済みだが新金融本文/入力/実台帳/APIは読まない。
    """
    selection_source = ROOT/'work/e01_entry_information_20261014/report_check/報告書選定の事前固定_v2.json'
    raw = selection_source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '44fd12b37414a74654921c7908e31709661834deb760255cd93052ea9aaee352'
    value = json.loads(raw.decode('utf-8'))
    value['段階'] = '111金融本文閲覧前。順位と主基準は110金融前固定から不変。'
    value['選定対象'] = '全十二比較。新VOL_SELECTED/VOL25六条件と旧PRICE_BOTH/AND六保存条件を商品別一組へ固定。'
    value['標本'] = '同じ保存三十三場。新唯一金融297＋内部同値99＋旧経済同値396＝792比較。独立標本へ数えない。'
    value['変更'] = '1呼値追随の価格0.75条件へ両市場2票以上を追加。価格票不足でも出来高代理入口は残し、0呼値で試す。入口/出口/数量/費用は不変。'
    value['旧保存範囲'] = 'PRICEとANDの各三出口は受理された実経済のみ同値で保存引用。不受理pub価格許容診断が同一とは言わない。旧親経路は未コピー。'
    value['ROOT集計通知'] = '一部の111結果数値はroot通知で受領。基準/順位は変更せず、本文はまだ未読。'
    target = HERE/'報告書選定の事前固定_v1.json'
    if target.exists():
        assert json.loads(target.read_text(encoding='utf-8')) == value
    else:
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    selection_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    rp, qp = HERE/'report.py', BASE/'report_review/report_view.py'
    assert hashlib.sha256(rp.read_bytes()).hexdigest() == '35468313dad4d2c3858dcf70d510b6d80f3e56eba8a55d23dd62f996f6b894f3'
    assert hashlib.sha256(qp.read_bytes()).hexdigest() == '91d8d55fdf4ed51363b27ebc8a88582162523c812ab6b4b83af8bf0fd2c1d7a3'
    report = rp.read_text(encoding='utf-8')
    replacements = {
        '00110_価格票と出来高代理票の入口切り分け': '00111_少ない価格票で注文価格を追わない検証',
        '価格票と出来高代理票で入口を切り分けるE01と全セッション損益': '少ない価格票で注文価格を追わないE01と全セッション損益',
        '入口情報別E01の全場会計.json': '価格票の最低数別E01の全場会計.json',
        'ACTUAL_NEW_COUNT = 9': 'ACTUAL_NEW_COUNT = 6', 'REUSED_COUNT = 3': 'REUSED_COUNT = 6',
        "'新account金融': 495": "'新account金融': 297",
        "HERE/'報告書選定の事前固定_v2.json'": "HERE/'報告書選定の事前固定_v1.json'",
        "'44fd12b37414a74654921c7908e31709661834deb760255cd93052ea9aaee352'": repr(selection_sha),
        "HERE/'comparisons/109_PRICE_BOTH三条件の保存会計.json'": "HERE/'comparisons/110十二比較の保存公開会計.json'",
        '6f56286c8b7dea6e9313cc09e4254ffe1033159c8eda0422b2bdce4c9a4d663a': 'a0e10058632c6891035eb15b0167f77cf35295e94f16929c660ea17d7acf9938',
        'reused_price_cases': 'reused_economic_cases', 'paired_price_id': 'paired_previous_id',
        'PRICE再金融': '旧経済同値再金融', '保存PRICE条件': '旧経済同値保存条件', '保存PRICE会計': '旧経済同値保存会計',
        "finance['新account金融'] == 495": "finance['新account金融'] == 297",
        "finance['旧経済同値保存会計'] == 198": "finance['旧経済同値保存会計'] == 396",
        "config['id'] == 'E01_INFO_'": "config['id'] == 'E01_EVID_'",
        "config['paired_previous_id'] == 'E01_NO_PRICE_EXIT_ORIGIN_'+exit_id": "config['paired_previous_id'] == 'E01_INFO_'+entry_id+'_'+exit_id",
        "config['actual_financial'] == (entry_id != 'PRICE_BOTH')": "config['actual_financial'] == (entry_id in ('VOL_SELECTED', 'VOL25'))",
        "expected_kind = '保存PRICE' if entry_id == 'PRICE_BOTH'": "expected_kind = '旧110経済同値保存' if entry_id in ('PRICE_BOTH', 'VOL25_PRICE_BOTH')",
        "config['paired_previous_id'] if entry_id == 'PRICE_BOTH'": "config['paired_previous_id'] if entry_id in ('PRICE_BOTH', 'VOL25_PRICE_BOTH')",
        "'E01_INFO_VOL_SELECTED_'+exit_id": "'E01_EVID_VOL_SELECTED_'+exit_id",
        "alias['id'].startswith('E01_INFO_VOL25_')": "alias['id'].startswith('E01_EVID_VOL25_')",
        "price_id = 'E01_NO_PRICE_EXIT_ORIGIN_'+case['parameters']['TOPIX']['exit_id']": "price_id = 'E01_INFO_'+case['parameters']['TOPIX']['entry_id']+'_'+case['parameters']['TOPIX']['exit_id']",
        "comparison_case['parameters'] = {s: dict(exit_id='TARGET')": "comparison_case['parameters'] = {s: dict(entry_id='PRICE_BOTH', exit_id='TARGET')",
        "cases={'E01_NO_PRICE_EXIT_ORIGIN_TARGET': previous_case}": "cases={'E01_INFO_PRICE_BOTH_TARGET': previous_case}",
        '新唯一金融495・旧PRICE保存198・同運転NK同値引用99': '新唯一金融297・旧経済同値保存396・同運転NK同値引用99',
        '同じ出口の保存PRICE基準': '旧110の同じ入口・出口',
        'PRICE三条件は保存再利用で新金融0。': 'PRICEとANDの六条件は実経済だけ保存再利用で新金融0。不受理pubの許容診断差は未測。',
        '全十二比較（新九・保存三）': '全十二比較（新六・保存六）'
    }
    for before, after in replacements.items():
        assert before in report, before
        report = report.replace(before, after)
    rp.write_text(report, encoding='utf-8')
    qa = qp.read_text(encoding='utf-8')
    for before, after in list(replacements.items())[:3]:
        qa = qa.replace(before, after)
    qa = qa.replace("data['new_count'] == 9 and data['reused_count'] == 3", "data['new_count'] == 6 and data['reused_count'] == 6")
    qa = qa.replace("price_id = 'E01_NO_PRICE_EXIT_ORIGIN_'+case['parameters']['TOPIX']['exit_id']", "price_id = 'E01_INFO_'+case['parameters']['TOPIX']['entry_id']+'_'+case['parameters']['TOPIX']['exit_id']")
    qa = qa.replace('新唯一金融495', '新唯一金融297').replace('旧PRICE保存198', '旧経済同値保存396')
    qa = qa.replace('入口情報十二比較と保存同値区分', '少ない価格票の十二比較と保存同値区分')
    qp.write_text(qa, encoding='utf-8')
    print(json.dumps(dict(全合格=True, selection_SHA256=selection_sha, 金融本文=0, input=0, ledger=0, API=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
