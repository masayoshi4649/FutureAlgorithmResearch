"""保存済み研究から抽出した判断部品を、共通知見の正本へ統合する。"""

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TARGET = ROOT/'アルゴリズム調査/共通/知見台帳/data/rules.json'
INPUTS = [HERE/'entry/entry_rules.json', HERE/'continuation/continuation_rules.json',
          HERE/'exit_techniques/exit_technique_rules.json', HERE/'entry/entry_component_rules.json']


def compact_scope(value: object) -> str:
    """
    機能: 構造化された対象範囲を日本語の閲覧文字列にする。
    引数: value(object)は文字列又は抽出時の範囲辞書。
    返り値: strは意味を変えない範囲説明。
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def normalize(row: dict) -> dict:
    """
    機能: 分子分母から百分率を再計算し、正本の必須項目と表示項目を揃える。
    引数: row(dict)は担当ごとの抽出知見。
    返り値: dictは出典と元の対象範囲を維持した一知見。
    """
    row = dict(row)
    for field in ('mechanical_condition', 'use'):
        if not isinstance(row[field], str):
            row[field + '_details'] = row[field]
            row[field] = '\n'.join(f'{key}：{compact_scope(value)}' for key, value in row[field].items())
    measures = row.get('measurements', [])
    if not row.get('status'):
        row['status'] = ('条件別の観測あり' if any(item.get('successes') is not None for item in measures)
                         else '損益対照あり' if any(item.get('value') is not None for item in measures) else '未測定')
    for item in measures:
        if item.get('successes') is not None:
            item['value'] = 100 * item['successes'] / item['total']
            item['unit'] = '%'
        else:
            if item.get('total') is not None:
                item['sample_size'] = item['total']
                item['total'] = None
            if item.get('unit') in ('割合', '比率') and item.get('value') is not None:
                item['value'] *= 100
                item['unit'] = '%'
        if not isinstance(item.get('scope'), str):
            item['scope_details'] = item['scope']
            item['scope'] = compact_scope(item['scope'])
        item.setdefault('primary', True)
    if row['id'] in ('入口_001', '入口_002', '入口_003'):
        row['status'] = '複合入口の観測'
        row['limitations'].insert(0, '複数条件を組み合わせた入口の数値です。板圧力や補充など、一つの要因だけの確率には分解できていません。')
        for item in measures:
            item['primary'] = item['label'] in ('場末までに順行0.1%へ一度到達', '対称0.1%の順行側へ先着')
    elif row['id'] == '入口_004':
        row['condition'] = '自市場の進行と相手市場の進行が同方向で、相手が直近にも逆行していない。'
        row['observed'] = '両銘柄とも、相手確認ありの群で黒字率が高かった。前半・後半に分けても同じ傾向だった。'
        for item in measures:
            item['primary'] = '全29' in item['label']
            item['denominator'] = '各商品・期間・相手確認あり／なしの群に含まれる元S1の実決済数。元母集団全体は142件で、勝敗や将来値で群を選ばない。'
    elif row['id'] in ('入口_005', '入口_006'):
        for item in measures:
            item['primary'] = not item['label'].startswith('支持4')
    elif row['id'] in ('CONT01', 'CONT03'):
        for item in measures:
            item['primary'] = (item.get('successes') is not None or 'M0比収支差' in item['label'])
    elif row['id'] == 'CONT04':
        for item in measures:
            item['primary'] = '前16' not in item['label']
    elif row['id'] == 'CONT07':
        for item in measures:
            item['primary'] = '最終勝ち親の割合' not in item['label']
    elif row['id'] == 'EXIT_NARROW_TRAIL_05':
        for item in measures:
            item['primary'] = '親決済勝率' in item['label'] or item['label'].endswith('収支')
    elif row['id'] == 'ORDER_HEDGE_PROFIT_02':
        for item in measures:
            item['primary'] = '選択された' not in item['label']
    elif row['id'] == 'ORDER_FAST_REENTRY_06':
        for item in measures:
            item['primary'] = '勝率' in item['label'] or '手数料後収支' in item['label']
    if row['id'] in ('MANAGEMENT_VIRTUAL_PAUSE_08', 'MANAGEMENT_NEW_THESIS_09'):
        row['stage'] = '売買の工夫'
    if row['id'] in ('入口_008', '入口_009'):
        for item in measures:
            item['primary'] = '全32' in item['label']
    if row['id'] == 'CONT01':
        row['observed'] = '相手との不一致だけで降りるより、自市場の方向消失まで待つ方が改善。ただし、中立を理由に降りない基準より良かった入口条件は少なかった。'
        for item in measures:
            item['label'] = item['label'].replace('S-Cの収支が改善した固定入口割合', '相手不一致で返済 → 自市場の中立で返済：改善した入口条件')
            item['label'] = item['label'].replace('S-B0の収支が改善した固定入口割合', '中立返済なし → 自市場の中立で返済：改善した入口条件')
        row['limitations'].insert(0, '既知13セッションを12種類の入口条件で比較した旧・費用なしの模型です。12回の取引勝率ではありません。')
    if row['id'] == 'ORDER_HEDGE_PROFIT_02':
        for item in measures:
            if '損失削減率' in item['label']:
                item['denominator'] = '同じ32呼値停止の無保険対照T2L0_D32で発生した負組の総損失金額。取引件数ではない。'
                item['calculation'] = '100 × (無保険対照の総損失金額 − 保険ありの総損失金額) / 無保険対照の総損失金額'
    if row['id'] == 'EXIT_RISK_BEFORE_PROFIT_10':
        row['mechanical_condition_details']['S'] = 'max(2呼値, 始値0.1%を呼値切上げ)。浮動小数誤差補正1e-10を含む。'
        row['mechanical_condition'] = '\n'.join(f'{key}：{compact_scope(value)}' for key, value in row['mechanical_condition_details'].items())
        for item in measures:
            if '発動親のうち利益' in item['label']:
                item['numerator_pointer'] = item['source']['pointer'] + '/profit_trail_activated'
    return row


def main() -> None:
    """
    機能: 抽出済みの小JSONを統合し、ビューから独立した共通正本を作る。
    引数: なし。
    返り値: None。原本の板や足、現在API、金融エンジンには接続しない。
    """
    rows, origins = [], []
    for path in INPUTS:
        content = json.loads(path.read_text(encoding='utf-8'))
        rows.extend(normalize(row) for row in content['rules'])
        origins.append(dict(path=path.relative_to(ROOT).as_posix(),
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    # ----------------------------------------
    # 要因の比較を先に示し、複合入口全体の古い到達観測は入口の末尾に残す。
    stages = {'入口': 0, '継続判断': 1, '出口': 2, '売買の工夫': 3}
    rows.sort(key=lambda row: (stages[row['stage']], row['id'] in ('入口_001', '入口_002', '入口_003'), row['id']))
    counts = dict(Counter(row['stage'] for row in rows))
    value = dict(
        schema_version=1,
        updated_at=datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),
        coverage=f'既存の保存結果から{len(rows)}件の法則・仮説を整理。数値は銘柄別、既知期間の観測です。複合条件と個別部品の効果を区別し、未整理の法則も残っています。',
        stage_notes={
            '入口': '入りたい方向を何で判断するか。条件がある場合・ない場合の比較、順行幅への到達、損切りより先に届いた割合を確認します。',
            '継続判断': '保有中に何が起きたら持ち続けるか、減らすか。将来経路の割合と、管理方法を替えた収支差を分けています。',
            '出口': '何を合図に利益確定・損切りするか。避けられた損失と失った利益を合わせて確認します。',
            '売買の工夫': '両建て、再参加、配分、参加停止などが、どの条件で役立ち、どの条件で逆効果になるかを確認します。'},
        unresolved=[
            '単独の板圧力、補充、距離重み、移動平均などの全歴代研究を、同じ母集団の要因別確率へ整理し終えたものではありません。',
            '複合入口で測定した確率を、その中の単独要因の予測力と解釈しません。',
            '途中判断や出口は、対照損益の測定が中心です。記載のない条件付き確率は未測定又は未抽出です。',
            '資料ごとに期間・入口・費用・約定条件が異なるため、異なるカードの金額をそのまま順位付けしません。'],
        extraction_sources=origins, counts=counts, rules=rows)
    TARGET.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(件数=counts, 測定値=sum(len(row['measurements']) for row in rows)), ensure_ascii=False))


if __name__ == '__main__':
    main()
