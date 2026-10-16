"""正式独立会計と一回の独立原因資料を、短い安定性の説明へ結ぶ。"""

import argparse
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
NAMES = {'TOPIX': 'TOPIX', 'NK225': '日経'}


def read(path: Path) -> dict:
    """
    機能: 保存された正式結果又は独立証跡を読む。
    引数: path (Path)。UTF-8のJSON資料。
    返り値: dict。資料の内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 説明の根拠資料の内容を指紋化する。
    引数: path (Path)。保存ファイル。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ratio(value: float | None) -> str:
    """
    機能: 金額割合又は未定義を短い日本語へ変換する。
    引数: value (float | None)。利益を利益と損失の合計で割った値。
    返り値: str。百分率又は未定義の理由。
    """
    return f'{value:.1%}' if value is not None else '取引なし'


def main() -> None:
    """
    機能: 独立検算後に、赤字頻度と額・実増玉・同入口の差を説明する。
    引数: CLI --root-all31-independent-complete (bool)。根による完了通知。
    返り値: None。売買、参考選定又は会計を再計算せずJSONを保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--root-all31-independent-complete', action='store_true')
    args = parser.parse_args()
    assert args.root_all31_independent_complete
    target = HERE / '説明補足.json'
    assert not target.exists()
    analysis_path = HERE / '比較結果.json'
    audit_path = WORK / 'audit/全20全31の増玉注文と親cohort及び全原板会計の独立検算.json'
    cause_path = WORK / 'review/全31の余裕と据置及び同入口の独立原因比較.json'
    analysis, audit, cause = [read(path) for path in (analysis_path, audit_path, cause_path)]
    assert analysis['全合格'] and audit['合格'] and not audit['人工専用']
    assert cause['全合格'] and cause['対象口座数'] == 310
    assert cause['検査件数']['口座'] == 310 and audit['検査件数']['口座'] == 1240
    assert cause['SHA256'][analysis_path.relative_to(ROOT).as_posix()] == digest(analysis_path)
    for name, expected in cause['SHA256'].items():
        assert digest(ROOT / name) == expected, name
    primary = analysis['primary']
    assert primary == cause['主'] == 'B1_T0_Q1_X1'
    values = cause['全計算']
    result = analysis['results']
    additional_path = WORK / 'holdout_report/追加ナイトと全32の損益.json'
    additional = read(additional_path)
    assert additional['全合格'] and additional['primary'] == primary
    assert additional['selected'] == analysis['selected'] and additional['session'] == '2026-10-12_Night'
    current = values[primary]
    conclusion = []
    successful = [ident for ident, by_symbol in additional['results'].items() if all(
        (v := by_symbol[symbol]['all32'])['campaigns'] >= 20 and v['active_sessions'] >= 8
        and v['profit_share'] is not None and v['profit_share'] >= .8
        and v['cohorts']['profit_share'] is not None and v['cohorts']['profit_share'] >= .8
        for symbol in SYMBOLS)]
    all_positive = analysis['両商品で全場黒字']
    if not successful:
        conclusion.append('両商品で十分な活動を伴う金額利益80%は未達です。今回の増玉改善だけでは、安定して稼げる手法として採用しません。')
    else:
        conclusion.append(f'親と実玉群の両方で両商品の金額利益80%を満たす条件は{len(successful)}件。既知31と追加1の全32を見た事後評価であり、未知期間の成功とは区別します。')
    main_facts = []
    for symbol in SYMBOLS:
        value = additional['results'][primary][symbol]['all32']
        main_facts.append(f'{NAMES[symbol]}は黒字{value["positive_sessions"]}・赤字{value["losing_sessions"]}・無取引{value["no_trade_sessions"]}場、収支{value["net"]:+,.0f}円')
    conclusion.append('事前主 '+primary+'の全32：'+'。'.join(main_facts)+'。')
    conclusion.append('追加10月12日ナイトの主：'+'・'.join(
        f'{NAMES[symbol]}{additional["results"][primary][symbol]["additional1"]["net"]:+,.0f}円'
        for symbol in SYMBOLS)+'。条件と参考は変更していません。')
    main_change = []
    for symbol in SYMBOLS:
        new = current['期間']['全31'][symbol]
        old = values['G1_Q1_X1']['期間']['全31'][symbol]
        main_change.append(f'{NAMES[symbol]}の赤字場{old["赤字セッション数"]}→{new["赤字セッション数"]}、最大赤字{old["最大赤字セッション円"]:,.0f}→{new["最大赤字セッション円"]:,.0f}円')
    conclusion.append('旧増玉との比較：'+'。'.join(main_change)+'。')
    best = analysis['安定性の事後診断順'][0]
    conclusion.append(f'全31を見て赤字の下方偏差を優先した事後診断の先頭は{best}です。前16で選んだ参考{analysis["selected"]}と区別し、事前主を差し替えていません。')
    if not all_positive:
        conclusion.append('両商品で全31セッション黒字は未達です。赤字頻度の改善と、全場黒字の達成を分けています。')

    # ----------------------------------------
    # 独立原因の実金額と件数をそのまま説明する。仮の出口は作らない。
    notes = dict(analysis['cause_notes'])
    notes['実際の追加'] = '。'.join(
        f'{NAMES[symbol]}の主は{current["追加診断全31"][symbol]["実追加親数"]}親に'
        f'{current["追加診断全31"][symbol]["実追加注文数"]}回追加、'
        f'追加実約定後に停止線が短縮されたのは{current["追加診断全31"][symbol]["実fill停止線短縮数"]}回'
        for symbol in SYMBOLS)+'。判断時の余裕と、後の実約定による変化は別です。'
    for ident, calculations in values.items():
        sentences = []
        for symbol in SYMBOLS:
            diagnostic = calculations['追加診断全31'][symbol]
            total = calculations['期間']['全31'][symbol]
            sentences.append(f'{NAMES[symbol]}：実追加{diagnostic["実追加注文数"]}回、赤字{total["赤字セッション数"]}/{total["活動セッション数"]}活動場、平均赤字{total["平均赤字セッション円"]:,.0f}円、最大赤字{total["最大赤字セッション円"]:,.0f}円。玉群の金額利益割合{ratio(total["建玉群金額利益割合"])}')
        notes[ident] = '。'.join(sentences)+'。'
    for ident in ('B1_T0_Q1_X1', 'B1_T1_Q1_X1', 'G1_Q1_X1'):
        for symbol in SYMBOLS:
            equality = cause['固定1枚との実金融同値'][ident][symbol]
            if equality['G0全31実注文完全同値'] and equality['G0全31実親完全同値']:
                notes[ident] += f' {NAMES[symbol]}は全31の注文と親が固定1枚と完全同値で、新しい売買上の優位ではありません。'
    notes['同じ入口の比較'] = '主と固定1枚の同入口親の実収支差に、両側の一致しない親の差を加えると全収支差へ一致することを独立確認。増玉による早い出口と後続の再参加も収支に残しています。'
    example = cause['同入口比較'][primary]['TOPIX']['同入口悪化上位'][0]
    assert example['session'] == '2026-09-24_Night'
    notes['増玉による具体的な悪化'] = (
        f'9/24ナイトTOPIXは、{example["入口時刻"].split("T")[1][:8]}に{example["初回価格"]:g}で同じ1枚を買い。'
        f'増玉は{example["左最終枚数"]}枚となり{example["左返済時刻"].split("T")[1][:8]}に{example["左返済価格"]:g}へ返して{example["左収支"]:+,.0f}円、'
        f'固定1枚は{example["右返済時刻"].split("T")[1][:8]}に{example["右返済価格"]:g}へ返して{example["右収支"]:+,.0f}円。'
        '入口を当てても、後から増やした高い建値と停止線の接近が利益を損失へ変えた実例です。時刻は保存価格時計の日本時間。')
    passage_path = WORK / 'review/固定1枚の実保有中の到達順と返却利益の全31診断.json'
    passage = read(passage_path)
    assert passage['全合格'] and passage['検査件数']['実親'] == 88
    snippets = []
    for symbol in SYMBOLS:
        stat = passage['商品別及び売買別'][symbol]['全31']
        snippets.append(f'{NAMES[symbol]}は赤字{stat["最終赤字親数"]}親中、最初の損切り幅の半分にも順行しなかったのが{stat["赤字親中の最大順行0_5S未満親数"]}親')
    notes['入口と出口の切り分け'] = '固定1枚でも、'+'。'.join(snippets)+'。実入口から実出口までの正常清算気配を全親で比較した結果です。利益を返した例もありますが、入口の弱さを出口だけで解決できる根拠はありません。'
    notes['追加データ'] = '10月12日ナイトの保存追加を固定時に発見。既知31の参考選定へ入れず、条件を変えない追加確認を行い、追加40口座を独立検算しました。元31表を保持し、追加1と全32合計を別に表示しています。'
    paths = [analysis_path, audit_path, cause_path, passage_path, additional_path, Path(__file__),
             WORK / '追加ナイトの隔離計画.json', WORK / 'audit/追加保存場隔離の独立静的確認.json']
    output = dict(全合格=True, 正式全範囲独立検算完了=True, 独立原因検査完了=True,
        根集計SHA256=digest(analysis_path),
        根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths},
        売買及び会計の変更=0, report_diagnostics={},
        conclusion=conclusion, cause_notes=notes,
        独立原因の対象=cause['scope'], 独立原因の口座数=310,
        全31既知=True, 新未見確認場数=0, 追加隔離場='2026-10-12_Night',
        API取得=0, 実注文=0)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('独立原因の実件数・実金額から安定性の説明を保存しました。', flush=True)


if __name__ == '__main__':
    main()
